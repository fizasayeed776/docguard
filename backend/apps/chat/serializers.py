from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from apps.workspaces.models import WorkspaceMembership

from .models import ChatMessage, ChatSession


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["id", "role", "content", "citation_chunk_ids", "created_at"]
        read_only_fields = fields


class ChatSessionSerializer(serializers.ModelSerializer):
    messages = ChatMessageSerializer(many=True, read_only=True)

    def validate_workspace(self, workspace):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            raise PermissionDenied("Authentication is required.")
        if not WorkspaceMembership.objects.filter(workspace=workspace, user=request.user).exists():
            raise PermissionDenied("You are not a member of this workspace.")
        return workspace

    class Meta:
        model = ChatSession
        fields = ["id", "workspace", "title", "messages", "created_at"]
        read_only_fields = ["id", "messages", "created_at"]
