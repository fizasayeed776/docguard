from apps.chat.routing import websocket_urlpatterns as chat_ws_urls
from apps.realtime.routing import websocket_urlpatterns as realtime_ws_urls

websocket_urlpatterns = realtime_ws_urls + chat_ws_urls
