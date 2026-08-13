from rest_framework import viewsets

from .models import Artifact, Source
from .serializers import ArtifactSerializer, SourceSerializer
from .tasks import sync_source


class SourceViewSet(viewsets.ModelViewSet):
    serializer_class = SourceSerializer

    def get_queryset(self):
        return Source.objects.filter(workspace__memberships__user=self.request.user)

    def perform_create(self, serializer):
        source = serializer.save()
        sync_source.delay(str(source.id))


class ArtifactViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ArtifactSerializer

    def get_queryset(self):
        return Artifact.objects.filter(source__workspace__memberships__user=self.request.user)
