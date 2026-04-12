from __future__ import annotations

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rrcp.protocol.identity import Identity, UserIdentity
from rrcp.server.auth import HandshakeData
from rrcp.server.thread_server import ThreadServer
from rrcp.store.postgres.store import PostgresThreadStore


@pytest.fixture
async def client(clean_db: asyncpg.Pool) -> AsyncClient:
    store = PostgresThreadStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    thread_server = ThreadServer(store=store, authenticate=auth)
    app = FastAPI()
    app.state.thread_server = thread_server
    app.include_router(thread_server.router, prefix="/acp")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_send_message_appends_event(client: AsyncClient) -> None:
    create = await client.post("/acp/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    resp = await client.post(
        f"/acp/threads/{thread_id}/messages",
        json={
            "client_id": "cid_1",
            "content": [{"type": "text", "text": "hello"}],
        },
    )
    assert resp.status_code == 201
    event = resp.json()
    assert event["type"] == "message"
    assert event["thread_id"] == thread_id
    assert event["author"]["id"] == "u_alice"
    assert event["client_id"] == "cid_1"
    assert event["content"][0]["text"] == "hello"


async def test_list_events_returns_appended(client: AsyncClient) -> None:
    create = await client.post("/acp/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    for i in range(3):
        await client.post(
            f"/acp/threads/{thread_id}/messages",
            json={
                "client_id": f"cid_{i}",
                "content": [{"type": "text", "text": f"m{i}"}],
            },
        )

    resp = await client.get(f"/acp/threads/{thread_id}/events")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 3
    assert [e["client_id"] for e in body["items"]] == ["cid_0", "cid_1", "cid_2"]


async def test_send_message_requires_membership(clean_db: asyncpg.Pool) -> None:
    store = PostgresThreadStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    bob = UserIdentity(id="u_bob", name="Bob", metadata={"tenant": {"org": "A"}})

    async def auth_alice(_h: HandshakeData) -> Identity:
        return alice

    async def auth_bob(_h: HandshakeData) -> Identity:
        return bob

    app_alice = FastAPI()
    thread_server_alice = ThreadServer(store=store, authenticate=auth_alice)
    app_alice.state.thread_server = thread_server_alice
    app_alice.include_router(thread_server_alice.router, prefix="/acp")
    client_alice = AsyncClient(transport=ASGITransport(app=app_alice), base_url="http://a")

    app_bob = FastAPI()
    thread_server_bob = ThreadServer(store=store, authenticate=auth_bob)
    app_bob.state.thread_server = thread_server_bob
    app_bob.include_router(thread_server_bob.router, prefix="/acp")
    client_bob = AsyncClient(transport=ASGITransport(app=app_bob), base_url="http://b")

    create = await client_alice.post("/acp/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    resp = await client_bob.post(
        f"/acp/threads/{thread_id}/messages",
        json={"client_id": "x", "content": [{"type": "text", "text": "hi"}]},
    )
    assert resp.status_code == 403
