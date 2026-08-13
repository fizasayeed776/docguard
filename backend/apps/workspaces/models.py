import uuid

from django.conf import settings
from django.db import models


class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    webhook_secret = models.CharField(max_length=128, blank=True)
    teams_webhook_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class WorkspaceMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MEMBER = "member", "Member"
        VIEWER = "viewer", "Viewer"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace_memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("workspace", "user")

    def __str__(self):
        return f"{self.user} @ {self.workspace} ({self.role})"


class TriageRule(models.Model):
    """User-defined rule evaluated on Inconsistency creation, e.g.
    'auto-acknowledge minor issues under /archive/'."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="triage_rules")
    name = models.CharField(max_length=255)
    path_pattern = models.CharField(max_length=255, help_text="Glob pattern matched against artifact path")
    max_severity = models.CharField(max_length=16, help_text="Only auto-apply at or below this severity")
    action = models.CharField(max_length=32, default="acknowledge")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.workspace})"
