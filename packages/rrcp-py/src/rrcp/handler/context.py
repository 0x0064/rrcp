from __future__ import annotations

from collections.abc import Awaitable, Callable

from rrcp.analytics.collector import AssistantAnalytics
from rrcp.protocol.event import Event, MessageEvent
from rrcp.protocol.identity import AssistantIdentity, Identity
from rrcp.protocol.run import Run
from rrcp.protocol.thread import Thread
from rrcp.store.protocol import ThreadStore

InvokeAssistantCallable = Callable[[str], Awaitable[Run]]

# Window used by query_event() when walking back through thread history.
# Large enough that a user's question won't scroll out behind routine team
# chat or tool-call fan-out, small enough to keep the store query cheap.
_QUERY_LOOKBACK = 50


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

    async def query_event(self) -> MessageEvent | None:
        """Return the message event that most likely triggered this run.

        Walks thread history backwards from the most recent event and returns
        the first MessageEvent authored by ``self.run.triggered_by``. This is
        the canonical way to answer "what did the user just say to me" from
        inside a handler and is race-safe in multi-user threads where other
        members may post events between the invoker's sendMessage and invoke.

        When the event protocol gains a ``recipients`` field in a future
        release, this method will additionally require that recipients is
        empty (broadcast) or contains ``self.run.assistant.id``, so team
        chat from the triggerer is skipped. Today the check is a no-op
        because the field does not exist yet — callers that need this
        today can filter on ``event.metadata`` at the consumer level.

        Returns None if no matching message is found within the lookback
        window (``_QUERY_LOOKBACK``). Typical cause: the run was invoked
        without a preceding user message, or the triggering message has
        scrolled out behind a large volume of intervening events.
        """
        events = await self.events(limit=_QUERY_LOOKBACK)
        triggerer_id = self.run.triggered_by.id
        my_id = self.assistant.id

        for evt in reversed(events):
            if not isinstance(evt, MessageEvent):
                continue
            if evt.author.id != triggerer_id:
                continue
            # Forward-compatible recipients check: if the field is present
            # and non-empty, require that this assistant is addressed.
            # Absent or empty recipients means broadcast, accept.
            recipients = getattr(evt, "recipients", None)
            if recipients and my_id not in recipients:
                continue
            return evt
        return None
