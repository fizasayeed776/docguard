from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer


class DashboardConsumer(AsyncJsonWebsocketConsumer):
    """Per-workspace group receiving scan progress, new inconsistencies,
    and the agent activity feed. Backing events are published by Celery
    tasks via `channel_layer.group_send` (see apps.agents.tasks)."""

    async def connect(self):
        self.workspace_id = self.scope["url_route"]["kwargs"]["workspace_id"]
        self.group_name = f"workspace_{self.workspace_id}_dashboard"

        if self.scope["user"].is_anonymous:
            await self.close(code=4001)
            return

        if not await self._is_member(self.workspace_id, self.scope["user"].id):
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # Handler name matches the "type" key used in group_send messages
    # (dashboard.event -> dashboard_event)
    async def dashboard_event(self, event):
        await self.send_json(event)

    @database_sync_to_async
    def _is_member(self, workspace_id, user_id):
        from apps.workspaces.models import WorkspaceMembership

        return WorkspaceMembership.objects.filter(workspace_id=workspace_id, user_id=user_id).exists()


class ReviewRoomConsumer(AsyncJsonWebsocketConsumer):
    """Presence (who is viewing an Inconsistency) + live status changes
    when someone triages an issue, enabling optimistic UI on the React
    side and avoiding two reviewers clobbering the same fix."""

    async def connect(self):
        self.inconsistency_id = self.scope["url_route"]["kwargs"]["inconsistency_id"]
        self.group_name = f"review_room_{self.inconsistency_id}"

        if self.scope["user"].is_anonymous:
            await self.close(code=4001)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "presence.event", "event": "joined", "user": self.scope["user"].username},
        )

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_send(
                self.group_name,
                {"type": "presence.event", "event": "left", "user": self.scope["user"].username},
            )
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # e.g. {"action": "status_change", "status": "acknowledged"}
        if content.get("action") == "status_change":
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "presence.event",
                    "event": "status_change",
                    "status": content["status"],
                    "user": self.scope["user"].username,
                },
            )

    async def presence_event(self, event):
        await self.send_json(event)
