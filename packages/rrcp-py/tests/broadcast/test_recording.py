from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rrcp_server.broadcast.recording import RecordingBroadcaster
from rrcp_server.protocol.content import TextPart
from rrcp_server.protocol.event import MessageEvent
from rrcp_server.protocol.identity import Identity, UserIdentity
from rrcp_server.protocol.thread import Thread
from rrcp_server.server.acp import AcpServer
from rrcp_server.server.auth import HandshakeData
from rrcp_server.store.postgres.store import PostgresThreadStore


@pytest.fixture
async def setup(
    clean_db: asyncpg.Pool,
) -> tuple[AcpServer, RecordingBroadcaster, str]:
    store = PostgresThreadStore(pool=clean_db)
    rec = RecordingBroadcaster()

    async def auth(_h: HandshakeData) -> Identity:
        return UserIdentity(id="u1", name="Alice")

    acp = AcpServer(store=store, authenticate=auth, broadcaster=rec)
    now = datetime.now(UTC)
    await store.create_thread(Thread(id="th_1", tenant={}, metadata={}, created_at=now, updated_at=now))
    return acp, rec, "th_1"


async def test_publish_event_calls_broadcaster(
    setup: tuple[AcpServer, RecordingBroadcaster, str],
) -> None:
    acp, rec, thread_id = setup
    event = MessageEvent(
        id="evt_1",
        thread_id=thread_id,
        author=UserIdentity(id="u1", name="Alice"),
        created_at=datetime.now(UTC),
        content=[TextPart(text="hi")],
    )
    await acp.publish_event(event)
    assert len(rec.events) == 1
    assert rec.events[0].id == "evt_1"


async def test_recording_broadcaster_records_namespace() -> None:
    rec = RecordingBroadcaster()
    event1 = MessageEvent(
        id="evt_1",
        thread_id="th_1",
        author=UserIdentity(id="u1", name="Alice"),
        created_at=datetime.now(UTC),
        content=[TextPart(text="hi")],
    )
    event2 = MessageEvent(
        id="evt_2",
        thread_id="th_1",
        author=UserIdentity(id="u1", name="Alice"),
        created_at=datetime.now(UTC),
        content=[TextPart(text="bye")],
    )
    await rec.broadcast_event(event1, namespace="/A")
    await rec.broadcast_event(event2)
    assert rec.events_with_namespace == [(event1, "/A"), (event2, None)]


async def test_rest_message_send_triggers_broadcast(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresThreadStore(pool=clean_db)
    rec = RecordingBroadcaster()
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    acp = AcpServer(store=store, authenticate=auth, broadcaster=rec)
    app = FastAPI()
    app.state.acp = acp
    app.include_router(acp.router, prefix="/acp")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/acp/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    await client.post(
        f"/acp/threads/{thread_id}/messages",
        json={"client_id": "c1", "content": [{"type": "text", "text": "hi"}]},
    )

    assert len(rec.events) == 1
    assert rec.events[0].thread_id == thread_id
    assert len(rec.members_updated) == 1


async def test_run_lifecycle_events_broadcast(clean_db: asyncpg.Pool) -> None:
    store = PostgresThreadStore(pool=clean_db)
    rec = RecordingBroadcaster()
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    acp = AcpServer(store=store, authenticate=auth, broadcaster=rec, run_timeout_seconds=5)

    @acp.assistant("a1")
    async def helper(ctx, send):
        yield send.message(content=[TextPart(text="hello")])

    app = FastAPI()
    app.state.acp = acp
    app.include_router(acp.router, prefix="/acp")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/acp/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]
    await client.post(
        f"/acp/threads/{thread_id}/members",
        json={
            "identity": {
                "role": "assistant",
                "id": "a1",
                "name": "Helper",
                "metadata": {},
            }
        },
    )

    invoke = await client.post(
        f"/acp/threads/{thread_id}/invocations",
        json={"assistant_ids": ["a1"]},
    )
    run_id = invoke.json()["runs"][0]["id"]
    await acp.executor.await_run(run_id)

    types = [e.type for e in rec.events]
    assert "run.started" in types
    assert "message" in types
    assert "run.completed" in types
