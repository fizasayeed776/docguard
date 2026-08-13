import uuid

from django.db import models

from apps.workspaces.models import Workspace


class Source(models.Model):
    class Type(models.TextChoices):
        GITHUB_REPO = "github_repo", "GitHub Repository"
        UPLOAD = "upload", "Uploaded File Set"
        WIKI_EXPORT = "wiki_export", "Wiki Export"

    class SyncStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        SYNCING = "syncing", "Syncing"
        SYNCED = "synced", "Synced"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="sources")
    type = models.CharField(max_length=32, choices=Type.choices)
    name = models.CharField(max_length=255)
    # Reference to a secret in the credentials store, never the raw token.
    credentials_ref = models.CharField(max_length=255, blank=True)
    config = models.JSONField(default=dict, blank=True)  # e.g. {"repo": "org/name", "branch": "main"}
    sync_status = models.CharField(max_length=16, choices=SyncStatus.choices, default=SyncStatus.PENDING)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.type})"


class Artifact(models.Model):
    class AgentStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        COMPLETED_HEURISTIC = "completed_heuristic", "Completed with heuristic fallback"
        FAILED = "failed", "Failed"

    class ExtractionStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        HEURISTIC = "heuristic", "Heuristic"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="artifacts")
    path = models.CharField(max_length=1024)
    content_hash = models.CharField(max_length=64, db_index=True)  # SHA-256
    version = models.CharField(max_length=64, blank=True)  # e.g. git commit SHA
    raw_text = models.TextField(blank=True)
    file_type = models.CharField(max_length=32, blank=True)  # markdown / pdf / openapi / code_docstring
    # Durable agent state lets the UI explain the latest scan after reconnecting.
    agent_status = models.CharField(
        max_length=32, choices=AgentStatus.choices, default=AgentStatus.PENDING
    )
    agent_status_message = models.TextField(blank=True)
    claim_extraction_method = models.CharField(max_length=16, blank=True)  # ai | heuristic
    last_scanned_at = models.DateTimeField(null=True, blank=True)
    # Extraction durable state for the extractor agent
    extraction_status = models.CharField(
        max_length=32, choices=ExtractionStatus.choices, default=ExtractionStatus.PENDING
    )
    extraction_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("source", "path")
        indexes = [models.Index(fields=["source", "content_hash"])]

    def __str__(self):
        return self.path
