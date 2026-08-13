from rest_framework import serializers

from .models import Claim, Inconsistency, ScanRun


class ClaimSerializer(serializers.ModelSerializer):
    class Meta:
        model = Claim
        fields = ["id", "artifact", "statement", "category", "confidence", "created_at"]
        read_only_fields = fields


class InconsistencySerializer(serializers.ModelSerializer):
    claims = ClaimSerializer(many=True, read_only=True)

    class Meta:
        model = Inconsistency
        fields = [
            "id", "workspace", "claims", "severity", "status",
            "agent_reasoning", "suggested_fix", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "claims", "agent_reasoning", "suggested_fix", "created_at", "updated_at"]


class ScanRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScanRun
        fields = [
            "id",
            "workspace",
            "trigger",
            "status",
            "error_message",
            "statistics",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields
