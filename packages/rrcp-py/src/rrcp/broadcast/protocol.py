from __future__ import annotations

from typing import Protocol

from rrcp.protocol.event import Event
from rrcp.protocol.identity import Identity
from rrcp.protocol.run import Run
from rrcp.protocol.thread import Thread


class Broadcaster(Protocol):
    async def broadcast_event(self, event: Event, *, namespace: str | None = None) -> None: ...
    async def broadcast_thread_updated(self, thread: Thread, *, namespace: str | None = None) -> None: ...
    async def broadcast_members_updated(
        self,
        thread_id: str,
        members: list[Identity],
        *,
        namespace: str | None = None,
    ) -> None: ...
    async def broadcast_run_updated(self, run: Run, *, namespace: str | None = None) -> None: ...
