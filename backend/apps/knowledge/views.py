from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Inconsistency, ScanRun
from .serializers import InconsistencySerializer, ScanRunSerializer


class InconsistencyViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InconsistencySerializer

    def get_queryset(self):
        return Inconsistency.objects.filter(
            workspace__memberships__user=self.request.user
        ).select_related("workspace").prefetch_related("claims")

    @action(detail=True, methods=["post"])
    def accept_fix(self, request, pk=None):
        inconsistency = self.get_object()
        from apps.agents.tasks import create_pull_request_from_fix

        create_pull_request_from_fix.delay(inconsistency_id=str(inconsistency.id))
        return Response({"status": "pr_creation_queued"})

    @action(detail=True, methods=["post"])
    def mark_false_positive(self, request, pk=None):
        inconsistency = self.get_object()
        inconsistency.status = Inconsistency.Status.FALSE_POSITIVE
        inconsistency.save(update_fields=["status", "updated_at"])
        return Response({"status": "marked_false_positive"})


class ScanRunViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ScanRunSerializer

    def get_queryset(self):
        return ScanRun.objects.filter(workspace__memberships__user=self.request.user)
