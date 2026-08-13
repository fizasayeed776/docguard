import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.sources.models import Source
from apps.webhooks.models import WebhookDelivery
from apps.webhooks.tasks import handle_github_push
from apps.workspaces.models import Workspace


class GitHubWebhookIdempotencyTests(TestCase):
    def test_duplicate_delivery_dispatches_once(self):
        workspace = Workspace.objects.create(
            name="Webhook test workspace", slug="webhook-test", webhook_secret="test-secret"
        )
        payload = {"commits": [{"modified": ["docs/guide.md"]}]}
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        headers = {
            "HTTP_X_HUB_SIGNATURE_256": signature,
            "HTTP_X_GITHUB_DELIVERY": "delivery-123",
            "HTTP_X_GITHUB_EVENT": "push",
            "content_type": "application/json",
        }

        with patch("apps.webhooks.tasks.handle_github_push.delay") as dispatch:
            first = self.client.post(reverse("github_webhook", args=[workspace.id]), data=body, **headers)
            second = self.client.post(reverse("github_webhook", args=[workspace.id]), data=body, **headers)

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(WebhookDelivery.objects.filter(provider="github", delivery_id="delivery-123").count(), 1)
        dispatch.assert_called_once_with(
            workspace_id=str(workspace.id), changed_paths=["docs/guide.md"], payload=payload
        )

    def test_push_dispatches_only_changed_files_for_matching_github_source(self):
        workspace = Workspace.objects.create(name="Webhook source workspace", slug="webhook-source")
        source = Source.objects.create(
            workspace=workspace,
            type=Source.Type.GITHUB_REPO,
            name="Test repository",
            config={"repo": "example/docguard-test-repo", "branch": "main"},
        )
        payload = {"repository": {"full_name": "example/docguard-test-repo"}}
        files = [{"path": "docs/guide.md", "content": "Updated guide", "version": "abc123"}]

        with patch("apps.sources.tasks.get_github_files_for_paths", return_value=files) as fetch, patch(
            "apps.sources.tasks.process_artifact.delay"
        ) as dispatch:
            result = handle_github_push.run(str(workspace.id), ["docs/guide.md"], payload)

        fetch.assert_called_once_with(source, ["docs/guide.md"])
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.kwargs["source_id"], str(source.id))
        self.assertEqual(dispatch.call_args.kwargs["path"], "docs/guide.md")
        self.assertEqual(result, {"sources": 1, "dispatched": 1})
