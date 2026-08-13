import logging

import requests
from celery import shared_task
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def send_weekly_digest():
    """Celery Beat: every Monday. Renders an HTML summary per workspace
    and emails the team + posts to Microsoft Teams."""
    from apps.knowledge.models import Inconsistency, ScanRun
    from apps.workspaces.models import Workspace

    since = timezone.now() - timezone.timedelta(days=7)

    for workspace in Workspace.objects.all():
        scan_runs = ScanRun.objects.filter(workspace=workspace, started_at__gte=since)
        new_inconsistencies = Inconsistency.objects.filter(workspace=workspace, created_at__gte=since)
        fixed = new_inconsistencies.filter(status="fixed").count()

        context = {
            "workspace": workspace,
            "scan_count": scan_runs.count(),
            "new_issue_count": new_inconsistencies.count(),
            "fixed_count": fixed,
            "critical_count": new_inconsistencies.filter(severity="critical").count(),
            "issues": new_inconsistencies.select_related().prefetch_related("claims")[:10],
        }

        html_body = render_to_string("automation/weekly_digest.html", context)

        recipients = list(
            workspace.memberships.select_related("user").values_list("user__email", flat=True)
        )
        if recipients:
            send_mail(
                subject=f"DocGuard weekly digest - {workspace.name}",
                message="",  # plain-text fallback omitted for brevity
                html_message=html_body,
                from_email=None,
                recipient_list=recipients,
            )

        if workspace.teams_webhook_url:
            _post_to_teams(workspace.teams_webhook_url, context)


def _post_to_teams(webhook_url: str, context: dict):
    """Outbound webhook: posts an adaptive-card-style summary to a
    Microsoft Teams channel."""
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": "DocGuard Weekly Digest",
        "title": f"DocGuard weekly digest - {context['workspace'].name}",
        "text": (
            f"{context['new_issue_count']} new issues "
            f"({context['critical_count']} critical), "
            f"{context['fixed_count']} fixed, "
            f"{context['scan_count']} scans this week."
        ),
    }
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to post weekly digest to Teams for %s", context["workspace"])
