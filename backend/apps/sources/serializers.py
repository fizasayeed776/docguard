from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from apps.workspaces.models import WorkspaceMembership

from .models import Artifact, Source


class SourceSerializer(serializers.ModelSerializer):
    def validate_workspace(self, workspace):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            raise PermissionDenied("Authentication is required.")
        if not WorkspaceMembership.objects.filter(workspace=workspace, user=request.user).exists():
            raise PermissionDenied("You are not a member of this workspace.")
        return workspace

    class Meta:
        model = Source
        fields = [
            "id", "workspace", "type", "name", "config",
            "sync_status", "last_synced_at", "created_at",
        ]
        read_only_fields = ["id", "sync_status", "last_synced_at", "created_at"]


class ArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Artifact
        fields = [
            "id",
            "source",
            "path",
            "content_hash",
            "version",
            "file_type",
            "extraction_status",
            "extraction_error",
            "updated_at",
        ]
        read_only_fields = fields
