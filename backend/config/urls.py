from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/workspaces/", include("apps.workspaces.urls")),
    path("api/sources/", include("apps.sources.urls")),
    path("api/knowledge/", include("apps.knowledge.urls")),
    path("api/chat/", include("apps.chat.urls")),
    path("webhooks/", include("apps.webhooks.urls")),
]
