from __future__ import annotations

import socketio

from rrcp.protocol.event import Event
from rrcp.protocol.identity import Identity
from rrcp.protocol.run import Run
from rrcp.protocol.thread import Thread


def _thread_room(thread_id: str) -> str:
    return f"thread:{thread_id}"


class SocketIOBroadcaster:
    def __init__(self, sio: socketio.AsyncServer) -> None:
        self._sio = sio

    async def broadcast_event(self, event: Event, *, namespace: str | None = None) -> None:
        await self._sio.emit(
            "event",
            event.model_dump(mode="json", by_alias=True),
            room=_thread_room(event.thread_id),
            namespace=namespace or "/",
        )

    async def broadcast_thread_updated(self, thread: Thread, *, namespace: str | None = None) -> None:
        await self._sio.emit(
            "thread:updated",
            thread.model_dump(mode="json", by_alias=True),
            room=_thread_room(thread.id),
            namespace=namespace or "/",
        )

    async def broadcast_members_updated(
        self,
        thread_id: str,
        members: list[Identity],
        *,
        namespace: str | None = None,
    ) -> None:
        await self._sio.emit(
            "members:updated",
            {
                "thread_id": thread_id,
                "members": [m.model_dump(mode="json") for m in members],
            },
            room=_thread_room(thread_id),
            namespace=namespace or "/",
        )

    async def broadcast_run_updated(self, run: Run, *, namespace: str | None = None) -> None:
        await self._sio.emit(
            "run:updated",
            run.model_dump(mode="json", by_alias=True),
            room=_thread_room(run.thread_id),
            namespace=namespace or "/",
        )
