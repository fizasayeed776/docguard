import uuid

from django.db import models
from pgvector.django import VectorField

from apps.sources.models import Artifact
from apps.workspaces.models import Workspace


class Chunk(models.Model):
    """RAG unit: a slice of an Artifact's text plus its embedding."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="chunks")
    text = models.TextField()
    embedding = VectorField(dimensions=3072, null=True, blank=True)
    token_count = models.PositiveIntegerField(default=0)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["artifact", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["artifact", "position"],
                name="unique_chunk_artifact_position",
            )
        ]

    def __str__(self):
        return f"{self.artifact.path} #{self.position}"


class Claim(models.Model):
    """A single extracted factual assertion, produced by the Extractor agent."""

    class Category(models.TextChoices):
        ENDPOINT = "endpoint", "Endpoint"
        CONFIG_VALUE = "config_value", "Config Value"
        PROCESS_STEP = "process_step", "Process Step"
        VERSION_NUMBER = "version_number", "Version Number"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="claims")
    chunk = models.ForeignKey(Chunk, on_delete=models.SET_NULL, null=True, blank=True, related_name="claims")
    statement = models.TextField()
    category = models.CharField(max_length=32, choices=Category.choices)
    confidence = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.statement[:80]


class Inconsistency(models.Model):
    """Links two or more conflicting Claims, produced by the Comparator +
    Judge agents."""

    class Severity(models.TextChoices):
        CRITICAL = "critical", "Critical"
        MAJOR = "major", "Major"
        MINOR = "minor", "Minor"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        FIXED = "fixed", "Fixed"
        FALSE_POSITIVE = "false_positive", "False Positive"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="inconsistencies")
    claims = models.ManyToManyField(Claim, related_name="inconsistencies")
    severity = models.CharField(max_length=16, choices=Severity.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    agent_reasoning = models.TextField(blank=True)
    suggested_fix = models.TextField(blank=True)
    scan_run = models.ForeignKey(
        "ScanRun", on_delete=models.SET_NULL, null=True, blank=True, related_name="inconsistencies"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.severity}] {self.id}"


class ScanRun(models.Model):
    class Trigger(models.TextChoices):
        WEBHOOK = "webhook", "Webhook"
        SCHEDULED = "scheduled", "Scheduled"
        MANUAL = "manual", "Manual"

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        COMPLETED_WITH_FALLBACK = "completed_with_fallback", "Completed with heuristic fallback"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="scan_runs")
    trigger = models.CharField(max_length=16, choices=Trigger.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.RUNNING)
    failure_message = models.TextField(blank=True)
    statistics = models.JSONField(default=dict, blank=True)  # claims_extracted, comparisons_made, etc.
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    @property
    def duration(self):
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    def __str__(self):
        return f"ScanRun {self.id} ({self.trigger})"
