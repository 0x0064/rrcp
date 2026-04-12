from __future__ import annotations

from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from rrcp.protocol.content import TextPart
from rrcp.protocol.event import MessageEvent
from rrcp.protocol.identity import UserIdentity
from rrcp.protocol.thread import Thread
from rrcp.store.postgres.store import PostgresThreadStore
from rrcp.store.types import EventCursor


@pytest.fixture
async def store(clean_db: asyncpg.Pool) -> PostgresThreadStore:
    s = PostgresThreadStore(pool=clean_db)
    now = datetime.now(UTC)
    await s.create_thread(Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now))
    return s


def _msg(id: str, ts: datetime, text: str) -> MessageEvent:
    return MessageEvent(
        id=id,
        thread_id="th_1",
        author=UserIdentity(id="u1", name="Alice"),
        created_at=ts,
        content=[TextPart(text=text)],
    )


async def test_append_and_get(store: PostgresThreadStore) -> None:
    ts = datetime.now(UTC)
    e = _msg("evt_1", ts, "hi")
    appended = await store.append_event(e)
    assert appended.id == "evt_1"

    got = await store.get_event("evt_1")
    assert got is not None
    assert isinstance(got, MessageEvent)
    assert got.content[0].text == "hi"  # type: ignore[union-attr]


async def test_list_events_in_order(store: PostgresThreadStore) -> None:
    base = datetime.now(UTC)
    for i in range(3):
        await store.append_event(_msg(f"e_{i}", base + timedelta(seconds=i), f"m{i}"))

    page = await store.list_events("th_1", limit=10)
    assert [e.id for e in page.items] == ["e_0", "e_1", "e_2"]


async def test_list_events_since_cursor(store: PostgresThreadStore) -> None:
    base = datetime.now(UTC)
    for i in range(5):
        await store.append_event(_msg(f"e_{i}", base + timedelta(seconds=i), f"m{i}"))

    cursor = EventCursor(created_at=base + timedelta(seconds=1), id="e_1")
    page = await store.list_events("th_1", since=cursor, limit=10)
    assert [e.id for e in page.items] == ["e_2", "e_3", "e_4"]


async def test_list_events_filter_by_type(store: PostgresThreadStore) -> None:
    await store.append_event(_msg("e_1", datetime.now(UTC), "hi"))
    page = await store.list_events("th_1", types=["thread.created"])
    assert page.items == []
    page = await store.list_events("th_1", types=["message"])
    assert len(page.items) == 1
