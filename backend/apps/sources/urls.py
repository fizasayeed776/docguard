from rest_framework.routers import DefaultRouter

from .views import ArtifactViewSet, SourceViewSet

router = DefaultRouter()
router.register("artifacts", ArtifactViewSet, basename="artifact")
router.register("", SourceViewSet, basename="source")

urlpatterns = router.urls
