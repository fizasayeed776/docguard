import asyncio
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

LOW_CONFIDENCE_MESSAGE = "I couldn't find that in your docs."
MIN_COSINE_SIMILARITY = 0.60
MEMORY_MESSAGE_LIMIT = 6
FALLBACK_PREFIX = "[heuristic answer — AI quota exhausted]\n\n"

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """Streams RAG responses token by token - the flagship ASGI feature.
    Client sends {"session_id": ..., "message": "..."} and receives a
    sequence of {"type": "token", "text": ...} frames followed by
    {"type": "done", "citation_chunk_ids": [...]}."""

    async def connect(self):
        if self.scope["user"].is_anonymous:
            await self.close(code=4001)
            return
        await self.accept()

    async def receive_json(self, content, **kwargs):
        session_id = content.get("session_id")
        user_message = content.get("message")
        if not session_id or not user_message:
            await self.close(code=4000)
            return

        if not await self._can_access_session(session_id, self.scope["user"].id):
            await self.close(code=4003)
            return

        await self._save_message(session_id, "user", user_message, [])

        chunks = await self._hybrid_retrieve(session_id, user_message)

        # RRF is only a rank-fusion score (with k=60 its maximum is ~0.033),
        # so it is not meaningful as a relevance/confidence threshold.
        if not chunks or chunks[0]["similarity"] < MIN_COSINE_SIMILARITY:
            await self.send_json({"type": "token", "text": LOW_CONFIDENCE_MESSAGE})
            await self.send_json({"type": "done", "citation_chunk_ids": []})
            await self._save_message(session_id, "assistant", LOW_CONFIDENCE_MESSAGE, [])
            return

        full_text = ""
        async for token in self._stream_answer(session_id, user_message, chunks):
            full_text += token
            await self.send_json({"type": "token", "text": token})

        citation_ids = [c["id"] for c in chunks]
        await self.send_json({"type": "done", "citation_chunk_ids": citation_ids})
        await self._save_message(session_id, "assistant", full_text, citation_ids)

    @database_sync_to_async
    def _can_access_session(self, session_id, user_id):
        from .models import ChatSession

        return ChatSession.objects.filter(
            id=session_id,
            user_id=user_id,
            workspace__memberships__user_id=user_id,
        ).exists()

    @database_sync_to_async
    def _save_message(self, session_id, role, content, citation_chunk_ids):
        from .models import ChatMessage

        ChatMessage.objects.create(
            session_id=session_id, role=role, content=content, citation_chunk_ids=citation_chunk_ids
        )

    @database_sync_to_async
    def _hybrid_retrieve(self, session_id, query, top_k=8):
        """pgvector cosine similarity + PostgreSQL full-text search, merged
        via reciprocal rank fusion."""
        from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
        from pgvector.django import CosineDistance

        from apps.knowledge.models import Chunk
        from apps.knowledge.tasks import _call_openai_embeddings

        from .models import ChatSession

        workspace_id = ChatSession.objects.values_list("workspace_id", flat=True).get(id=session_id)

        [query_vector] = _call_openai_embeddings([query])
        vector_ranked = list(
            Chunk.objects.filter(artifact__source__workspace_id=workspace_id)
            .annotate(cosine_distance=CosineDistance("embedding", query_vector))
            .order_by("cosine_distance")[:top_k]
            .values_list("id", flat=True)
        )

        fts_ranked = list(
            Chunk.objects.filter(artifact__source__workspace_id=workspace_id)
            .annotate(search=SearchVector("text"), rank=SearchRank(SearchVector("text"), SearchQuery(query)))
            .filter(search=SearchQuery(query))
            .order_by("-rank")[:top_k]
            .values_list("id", flat=True)
        )

        rrf_scores = {}
        k = 60
        for rank, chunk_id in enumerate(vector_ranked):
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1 / (k + rank + 1)
        for rank, chunk_id in enumerate(fts_ranked):
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1 / (k + rank + 1)

        top_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)[:top_k]
        # Preserve RRF ordering, but retain true cosine relevance separately
        # for the low-confidence guardrail.  pgvector's <=> operator is cosine
        # distance, therefore 1 - distance is cosine similarity.
        chunks = (
            Chunk.objects.filter(id__in=top_ids)
            .annotate(cosine_distance=CosineDistance("embedding", query_vector))
            .select_related("artifact")
        )
        by_id = {c.id: c for c in chunks}
        return [
            {
                "id": str(cid),
                "text": by_id[cid].text,
                "score": rrf_scores[cid],  # RRF ordering only, not confidence.
                "similarity": max(0.0, min(1.0, 1.0 - by_id[cid].cosine_distance)),
            }
            for cid in top_ids if cid in by_id
        ]

    async def _stream_answer(self, session_id, query, chunks):
        """Stream a Gemini answer grounded only in retrieved chunks.

        The synchronous Gemini iterator is consumed in a worker thread so a
        long-running model response never blocks Channels' event loop.
        """
        history = await self._recent_messages(session_id)
        prompt = self._build_rag_prompt(query, chunks, history)

        try:
            from google import genai

            api_key = settings.GEMINI_API_KEY
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY is not configured")

            client = genai.Client(api_key=api_key)
            stream = client.models.generate_content_stream(
                model=settings.GEMINI_CHAT_MODEL,
                contents=prompt,
                config={"temperature": 0.2},
            )

            while True:
                response = await asyncio.to_thread(next, stream, None)
                if response is None:
                    break
                text = getattr(response, "text", None)
                if text:
                    yield text

        except Exception as exc:
            # Keep the quota handling identical to the consistency pipeline.
            from apps.agents.tasks import _is_quota_error

            if not _is_quota_error(exc):
                logger.exception("Gemini chat stream failed for session %s", session_id)
                raise

            logger.warning(
                "Gemini chat quota exhausted for session %s; using retrieval fallback. error=%s",
                session_id,
                exc,
            )
            fallback = FALLBACK_PREFIX + chunks[0]["text"]
            for text in self._text_chunks(fallback):
                yield text

    @database_sync_to_async
    def _recent_messages(self, session_id):
        from .models import ChatMessage

        messages = ChatMessage.objects.filter(session_id=session_id).order_by("-created_at")[:MEMORY_MESSAGE_LIMIT]
        return list(reversed(list(messages.values("role", "content"))))

    @staticmethod
    def _build_rag_prompt(query, chunks, history):
        sources = "\n\n".join(
            f"[Chunk {index} | id={chunk['id']}]\n{chunk['text']}"
            for index, chunk in enumerate(chunks, start=1)
        )
        conversation = "\n".join(
            f"{message['role'].title()}: {message['content']}" for message in history
        ) or "(No prior conversation.)"
        return (
            "You are DocGuard's documentation assistant. Answer the user's latest "
            "question using only the retrieved document excerpts below. If the excerpts "
            "do not answer it, say so plainly. Do not invent facts, sources, or chunk IDs. "
            "Be concise.\n\n"
            f"Conversation memory:\n{conversation}\n\n"
            f"Retrieved document excerpts:\n{sources}\n\n"
            f"Latest user question: {query}"
        )

    @staticmethod
    def _text_chunks(text, size=160):
        """Yield readable chunks for fallback streaming instead of one fake token."""
        for start in range(0, len(text), size):
            yield text[start : start + size]
