from rest_framework.routers import DefaultRouter

from .views import ChatSessionViewSet

router = DefaultRouter()
router.register("sessions", ChatSessionViewSet, basename="chatsession")

urlpatterns = router.urls
