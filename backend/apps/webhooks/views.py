import hashlib
import hmac
import json
import logging

from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def github_webhook(request, workspace_id):
    """Inbound webhook: GitHub notifies us of pushes/PR merges. Triggers
    re-analysis of ONLY the affected artifacts (not a full re-sync)."""
    from apps.workspaces.models import Workspace

    from .models import WebhookDelivery

    try:
        workspace = Workspace.objects.get(id=workspace_id)
    except Workspace.DoesNotExist:
        return HttpResponse(status=404)

    if not _verify_github_signature(request, workspace.webhook_secret):
        return HttpResponseForbidden("Invalid signature")

    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    event_type = request.headers.get("X-GitHub-Event", "")

    # Idempotency: GitHub retries deliveries on timeout/5xx. get_or_create
    # on the unique (provider, delivery_id) constraint means a duplicate
    # delivery is recorded but never re-dispatches a scan.
    delivery, created = WebhookDelivery.objects.get_or_create(
        provider="github", delivery_id=delivery_id, defaults={"event_type": event_type}
    )
    if not created:
        logger.info("Duplicate GitHub delivery %s ignored", delivery_id)
        return HttpResponse(status=200)

    payload = json.loads(request.body)
    changed_paths = _extract_changed_paths(event_type, payload)

    if changed_paths:
        from .tasks import handle_github_push

        handle_github_push.delay(
            workspace_id=str(workspace_id), changed_paths=changed_paths, payload=payload
        )

    delivery.processed = True
    delivery.save(update_fields=["processed"])
    return HttpResponse(status=202)


def _verify_github_signature(request, secret: str) -> bool:
    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header.startswith("sha256=") or not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _extract_changed_paths(event_type: str, payload: dict) -> list[str]:
    if event_type != "push":
        return []
    paths = set()
    for commit in payload.get("commits", []):
        paths.update(commit.get("added", []))
        paths.update(commit.get("modified", []))
    return list(paths)
