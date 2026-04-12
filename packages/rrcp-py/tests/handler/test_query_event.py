from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from rrcp.analytics.collector import AssistantAnalytics
from rrcp.handler.context import HandlerContext
from rrcp.protocol.content import TextPart
from rrcp.protocol.event import Event, MessageEvent
from rrcp.protocol.identity import AssistantIdentity, UserIdentity
from rrcp.protocol.run import Run
from rrcp.protocol.thread import Thread
from rrcp.store.protocol import ThreadStore
from rrcp.store.types import Page


class _FakeStore:
    """Minimal ThreadStore fake that only implements list_events.

    query_event() doesn't touch anything else, so we don't need to stand
    up Postgres for this test.
    """

    def __init__(self, events: list[Event]) -> None:
        self._events = events

    async def list_events(
        self,
        thread_id: str,
        since: Any = None,
        until: Any = None,
        limit: int = 100,
        types: Any = None,
    ) -> Page[Event]:
        # Return oldest-first, matching the real PostgresThreadStore contract.
        return Page[Event](items=list(self._events[:limit]), next_cursor=None)


def _message(
    *,
    id: str,
    author_id: str,
    author_role: str,
    text: str,
    minutes_ago: int,
) -> MessageEvent:
    return MessageEvent(
        id=id,
        thread_id="t_test",
        author=(
            UserIdentity(id=author_id, name=author_id, metadata={})
            if author_role == "user"
            else AssistantIdentity(id=author_id, name=author_id, metadata={})
        ),
        created_at=datetime.now(UTC).replace(microsecond=minutes_ago * 1000),
        content=[TextPart(text=text)],
    )


def _build_ctx(events: list[Event], triggerer_id: str, assistant_id: str = "ops-assistant") -> HandlerContext:
    store = cast(ThreadStore, _FakeStore(events))
    thread = Thread(
        id="t_test",
        tenant={"location": "warehouse_a"},
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assistant = AssistantIdentity(id=assistant_id, name="Ops Assistant", metadata={})
    run = Run(
        id="r_1",
        thread_id="t_test",
        assistant=assistant,
        triggered_by=UserIdentity(id=triggerer_id, name=triggerer_id, metadata={}),
        status="running",
        started_at=datetime.now(UTC),
    )
    analytics = AssistantAnalytics(
        on_analytics=None,
        thread_id="t_test",
        run_id="r_1",
        assistant_id=assistant_id,
    )
    return HandlerContext(store=store, thread=thread, run=run, assistant=assistant, analytics=analytics)


async def test_query_event_returns_none_when_no_triggerer_message() -> None:
    events: list[Event] = [
        _message(id="e1", author_id="u_bob", author_role="user", text="bob's note", minutes_ago=3),
        _message(id="e2", author_id="u_carol", author_role="user", text="carol's note", minutes_ago=2),
    ]
    ctx = _build_ctx(events, triggerer_id="u_alice")
    assert await ctx.query_event() is None


async def test_query_event_returns_simple_latest_message() -> None:
    events: list[Event] = [
        _message(id="e1", author_id="u_alice", author_role="user", text="first", minutes_ago=3),
        _message(id="e2", author_id="u_alice", author_role="user", text="second", minutes_ago=2),
    ]
    ctx = _build_ctx(events, triggerer_id="u_alice")
    result = await ctx.query_event()
    assert result is not None
    assert result.id == "e2"
    assert result.content[0].text == "second"  # type: ignore[union-attr]


async def test_query_event_skips_team_chat_from_other_users() -> None:
    # Alice asks a question, then Bob posts team chat that lands right before
    # Alice's invoke fires. query_event must walk past Bob's message and
    # return Alice's, not events[-1].
    events: list[Event] = [
        _message(id="e1", author_id="u_alice", author_role="user", text="what is the valve spec", minutes_ago=5),
        _message(id="e2", author_id="u_bob", author_role="user", text="I'll check the drawings", minutes_ago=2),
    ]
    ctx = _build_ctx(events, triggerer_id="u_alice")
    result = await ctx.query_event()
    assert result is not None
    assert result.id == "e1"
    assert result.content[0].text == "what is the valve spec"  # type: ignore[union-attr]


async def test_query_event_ignores_assistant_replies() -> None:
    # The triggerer is a user, but we should not accidentally pick the
    # assistant's reply if the assistant id happens to match something weird.
    events: list[Event] = [
        _message(id="e1", author_id="u_alice", author_role="user", text="question", minutes_ago=4),
        _message(id="e2", author_id="ops-assistant", author_role="assistant", text="answer", minutes_ago=3),
    ]
    ctx = _build_ctx(events, triggerer_id="u_alice")
    result = await ctx.query_event()
    assert result is not None
    assert result.id == "e1"
