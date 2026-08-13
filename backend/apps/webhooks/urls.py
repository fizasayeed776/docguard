from django.urls import path

from .views import github_webhook

urlpatterns = [
    path("github/<uuid:workspace_id>/", github_webhook, name="github_webhook"),
]
