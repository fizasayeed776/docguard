from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from apps.knowledge.tasks import embed_chunks
from apps.sources.models import Artifact, Source
from apps.workspaces.models import Workspace


class EmbeddingCacheTests(TestCase):
    def test_same_chunk_text_calls_embedding_provider_once(self):
        workspace = Workspace.objects.create(name="Cache test workspace", slug="cache-test")
        source = Source.objects.create(workspace=workspace, type=Source.Type.UPLOAD, name="Upload")
        artifact = Artifact.objects.create(source=source, path="docs/cache.md", content_hash="b" * 64)
        chunks = [{"text": "Identical chunk text for cache verification.", "position": 0}]
        cache.clear()

        with patch("apps.knowledge.tasks._call_openai_embeddings", return_value=[[0.0] * 3072]) as embed, patch(
            "apps.knowledge.tasks._notify_dashboard"
        ), patch("apps.agents.tasks.extract_claims.delay"):
            embed_chunks.run(str(artifact.id), chunks)
            embed_chunks.run(str(artifact.id), chunks)

        embed.assert_called_once_with([chunks[0]["text"]])
