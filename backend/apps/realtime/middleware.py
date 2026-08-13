"""
Websocket connections can't send an Authorization header via the browser
WebSocket API, so JWT auth here works via the `?token=` query string,
validated against the same SIMPLE_JWT signing key used by DRF's
JWTAuthentication - a single shared auth mechanism across WSGI and ASGI.
"""
from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.tokens import AccessToken


@database_sync_to_async
def get_user_from_token(token: str):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        validated_token = AccessToken(token)
        return User.objects.get(id=validated_token["user_id"])
    except (InvalidToken, User.DoesNotExist):
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query_string = parse_qs(scope["query_string"].decode())
        token = query_string.get("token", [None])[0]

        scope["user"] = await get_user_from_token(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    # Layers session-based AuthMiddlewareStack (for admin/dev tooling) under
    # our JWT layer, so either credential type authenticates the socket.
    return JWTAuthMiddleware(AuthMiddlewareStack(inner))
