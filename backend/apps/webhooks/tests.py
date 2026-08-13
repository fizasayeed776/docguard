import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.webhooks.models import WebhookDelivery
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
