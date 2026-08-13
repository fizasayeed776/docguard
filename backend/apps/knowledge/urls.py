from rest_framework.routers import DefaultRouter

from .views import InconsistencyViewSet, ScanRunViewSet

router = DefaultRouter()
router.register("inconsistencies", InconsistencyViewSet, basename="inconsistency")
router.register("scan-runs", ScanRunViewSet, basename="scanrun")

urlpatterns = router.urls
