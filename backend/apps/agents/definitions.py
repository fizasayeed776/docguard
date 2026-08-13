"""
Agent definitions using the Strands Agents SDK with a Gemini-backed custom model.

Pattern: Orchestrator uses the other four agents as *tools* ("agents-as-
tools"). Each agent has a narrow, single-purpose system prompt and a
schema-enforced output where possible, so the Judge is the one place
where "quality" is actually adjudicated (per the eval rubric).
"""
from __future__ import annotations

import time
from typing import Any, Iterable, Optional, cast

from django.conf import settings
from strands import Agent, tool
from strands.types.content import Messages
from strands.types.models import Model


class GeminiModel(Model):
    """Strands ``Model`` adapter backed by the current ``google-genai`` SDK.

    Strands 0.1.0 consumes Bedrock-shaped stream events.  Gemini streams
    response chunks instead, so ``stream`` translates them into the small
    event sequence Strands needs for a text-only response.
    """

    def __init__(self, model_id: str, api_key: str | None = None, **model_config):
        self.model_id = model_id
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.config: dict[str, Any] = {"model_id": model_id}
        self.update_config(**model_config)

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> Any:
        return self.config

    def format_request(
        self, messages: Messages, tool_specs: Optional[list[Any]] = None, system_prompt: Optional[str] = None
    ) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "messages": list(messages),
            "tool_specs": tool_specs or [],
            "system_prompt": system_prompt,
        }

    def format_chunk(self, event: Any) -> Any:
        """Gemini events are already translated to Strands StreamEvents."""
        return cast(Any, event)

    def stream(self, request: Any) -> Iterable[Any]:
        from google import genai

        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        contents: list[dict[str, Any]] = []
        for message in request.get("messages", []):
            if isinstance(message, dict):
                role = message.get("role", "user")
                content = message.get("content", [])
            else:
                role = getattr(message, "role", "user")
                content = getattr(message, "content", [])

            text_parts = [
                part["text"]
                for part in content if isinstance(part, dict) and part.get("text")
            ]
            if not text_parts:
                continue

            if role == "assistant":
                role = "model"
            contents.append({"role": role, "parts": [{"text": "\n".join(text_parts)}]})

        client = genai.Client(api_key=self.api_key)
        started_at = time.monotonic()
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}

        output_tokens = 0
        for response in client.models.generate_content_stream(
            model=request["model_id"],
            contents=contents,
            config={
                "system_instruction": request.get("system_prompt"),
                **{
                    key: value
                    for key, value in self.config.items()
                    if key in {"temperature", "top_p", "top_k", "max_output_tokens"} and value is not None
                },
            },
        ):
            text = getattr(response, "text", None)
            if text:
                output_tokens += len(text.split())
                yield {"contentBlockDelta": {"delta": {"text": text}}}

        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 0, "outputTokens": output_tokens, "totalTokens": output_tokens},
                "metrics": {"latencyMs": int((time.monotonic() - started_at) * 1000)},
            }
        }


FAST_MODEL = GeminiModel(model_id=settings.AGENT_MODEL_FAST, api_key=settings.GEMINI_API_KEY)
JUDGE_MODEL = GeminiModel(model_id=settings.AGENT_MODEL_JUDGE, api_key=settings.GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# Tools available to agents
# ---------------------------------------------------------------------------
@tool
def chunk_retriever(artifact_id: str) -> list[dict]:
    """Fetch ordered text chunks for a given artifact."""
    from apps.knowledge.models import Chunk

    return list(
        Chunk.objects.filter(artifact_id=artifact_id)
        .order_by("position")
        .values("id", "text", "position")
    )


@tool
def vector_search_similar_claims(claim_text: str, workspace_id: str, top_k: int = 5) -> list[dict]:
    """Vector-search for Claims semantically similar to the given text,
    scoped to a workspace, using pgvector cosine distance."""
    from apps.knowledge.models import Chunk, Claim

    # Embed claim_text with the same embedding model, then search Chunk
    # embeddings via cosine distance, then map back to Claims on those chunks.
    from apps.knowledge.tasks import _call_openai_embeddings

    [query_vector] = _call_openai_embeddings([claim_text])
    similar_chunks = (
        Chunk.objects.filter(artifact__source__workspace_id=workspace_id)
        .order_by(f"embedding <-> '{query_vector}'")[:top_k]
    )
    return list(
        Claim.objects.filter(chunk__in=similar_chunks).values("id", "statement", "category", "artifact_id")
    )


@tool
def file_reader(artifact_id: str) -> str:
    from apps.sources.models import Artifact

    return Artifact.objects.get(id=artifact_id).raw_text


@tool
def diff_generator(original: str, corrected: str) -> str:
    import difflib

    return "\n".join(
        difflib.unified_diff(original.splitlines(), corrected.splitlines(), lineterm="")
    )


@tool
def github_pr_creator(repo: str, branch: str, file_path: str, new_content: str, pr_title: str, pr_body: str) -> dict:
    """Placeholder: create a branch, commit, and PR via the GitHub API."""
    raise NotImplementedError("Wire up PyGithub / GitHub REST client here")


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
extractor_agent = Agent(
    model=FAST_MODEL,
    system_prompt=(
        "You extract factual, checkable claims from documentation and code "
        "comments. Output ONLY a JSON array of objects with fields: "
        "statement, category (endpoint|config_value|process_step|version_number), "
        "confidence (0-1). Do not include opinions or non-factual statements."
    ),
    tools=[chunk_retriever],
)

comparator_agent = Agent(
    model=FAST_MODEL,
    system_prompt=(
        "Given a Claim, retrieve semantically similar claims from other "
        "artifacts and decide, for each pair, whether they are "
        "consistent, contradicts, or unrelated. Always give brief reasoning."
    ),
    tools=[vector_search_similar_claims],
)

judge_agent = Agent(
    model=JUDGE_MODEL,
    system_prompt=(
        "You review candidate contradictions flagged by the Comparator. "
        "Assign severity (critical|major|minor), filter out false "
        "positives (e.g. claims about different API versions that are "
        "both intentionally valid), and give a one-paragraph justification. "
        "Be conservative: when uncertain, mark as false_positive rather "
        "than raising a low-confidence issue."
    ),
)

fixer_agent = Agent(
    model=FAST_MODEL,
    system_prompt=(
        "You draft a corrected version of a document section to resolve a "
        "confirmed inconsistency, preserving style and surrounding context. "
        "Then create a GitHub pull request with a clear description linking "
        "back to the inconsistency."
    ),
    tools=[file_reader, diff_generator, github_pr_creator],
)

orchestrator_agent = Agent(
    model=FAST_MODEL,
    system_prompt=(
        "You coordinate a documentation-consistency scan: for the given "
        "ScanRun scope, delegate to Extractor, Comparator, and Judge as "
        "needed, aggregate results, and report progress."
    ),
    # strands-agents==0.1.0 has no Agent.as_tool() API. Keep this agent
    # importable; wire agent delegation after a deliberate SDK upgrade.
    tools=[],
)
