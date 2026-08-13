from django.urls import re_path

from .consumers import DashboardConsumer, ReviewRoomConsumer

websocket_urlpatterns = [
    re_path(r"^ws/workspaces/(?P<workspace_id>[^/]+)/dashboard/$", DashboardConsumer.as_asgi()),
    re_path(r"^ws/inconsistencies/(?P<inconsistency_id>[^/]+)/review/$", ReviewRoomConsumer.as_asgi()),
]
