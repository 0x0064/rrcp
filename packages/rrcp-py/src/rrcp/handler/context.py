from __future__ import annotations

from collections.abc import Awaitable, Callable

from rrcp_server.analytics.collector import AssistantAnalytics
from rrcp_server.protocol.event import Event
from rrcp_server.protocol.identity import AssistantIdentity, Identity
from rrcp_server.protocol.run import Run
from rrcp_server.protocol.thread import Thread
from rrcp_server.store.protocol import ThreadStore

InvokeAssistantCallable = Callable[[str], Awaitable[Run]]


class HandlerContext:
    def __init__(
        self,
        store: ThreadStore,
        thread: Thread,
        run: Run,
        assistant: AssistantIdentity,
        analytics: AssistantAnalytics,
        invoke_assistant: InvokeAssistantCallable | None = None,
    ) -> None:
        self._store = store
        self._invoke_assistant = invoke_assistant
        self.thread = thread
        self.run = run
        self.assistant = assistant
        self.analytics = analytics

    async def events(self, limit: int | None = None) -> list[Event]:
        page = await self._store.list_events(self.thread.id, limit=limit or 100)
        return page.items

    async def members(self) -> list[Identity]:
        rows = await self._store.list_members(self.thread.id)
        return [m.identity for m in rows]

    async def invoke(self, assistant_id: str) -> Run:
        if self._invoke_assistant is None:
            raise RuntimeError("ctx.invoke is not available: no handler_resolver configured")
        return await self._invoke_assistant(assistant_id)
