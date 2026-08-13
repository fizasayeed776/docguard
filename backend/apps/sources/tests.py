from unittest.mock import patch

from django.test import TestCase

from apps.sources.models import Artifact, Source
from apps.sources.tasks import process_artifact
from apps.workspaces.models import Workspace


class ProcessArtifactIdempotencyTests(TestCase):
    def test_unchanged_content_skips_embedding_and_duplicate_artifact(self):
        workspace = Workspace.objects.create(name="Source test workspace", slug="source-test")
        source = Source.objects.create(workspace=workspace, type=Source.Type.UPLOAD, name="Upload")
        kwargs = {
            "source_id": str(source.id),
            "path": "docs/guide.md",
            "content": "Same source content.",
            "content_hash": "a" * 64,
        }

        with patch("apps.sources.tasks._publish_progress"), patch(
            "apps.knowledge.tasks.embed_chunks.delay"
        ) as embed:
            first = process_artifact.run(**kwargs)
            second = process_artifact.run(**kwargs)

        self.assertEqual(first["status"], "processed")
        self.assertEqual(second, {"status": "skipped", "reason": "unchanged"})
        self.assertEqual(Artifact.objects.filter(source=source, path="docs/guide.md").count(), 1)
        embed.assert_called_once()
