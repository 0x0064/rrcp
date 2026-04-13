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
async def client_with_authorize(
    clean_db: asyncpg.Pool,
) -> tuple[AsyncClient, list[tuple[str, str, str]]]:
    store = PostgresThreadStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})
    calls: list[tuple[str, str, str]] = []

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    async def authorize(
        identity: Identity,
        thread_id: str,
        action: str,
        *,
        target_id: str | None = None,
    ) -> bool:
        calls.append((identity.id, thread_id, action))
        return action != "thread.delete"

    thread_server = ThreadServer(store=store, authenticate=auth, authorize=authorize)
    app = FastAPI()
    app.state.thread_server = thread_server
    app.include_router(thread_server.router, prefix="/acp")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), calls


async def test_authorize_called_on_read(
    client_with_authorize: tuple[AsyncClient, list[tuple[str, str, str]]],
) -> None:
    client, calls = client_with_authorize
    create = await client.post("/acp/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    resp = await client.get(f"/acp/threads/{thread_id}")
    assert resp.status_code == 200
    assert (alice_action := ("u_alice", thread_id, "thread.read")) in calls
    del alice_action


async def test_authorize_can_deny_an_action(
    client_with_authorize: tuple[AsyncClient, list[tuple[str, str, str]]],
) -> None:
    client, _calls = client_with_authorize
    create = await client.post("/acp/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    resp = await client.delete(f"/acp/threads/{thread_id}")
    assert resp.status_code == 403
    assert "not authorized: thread.delete" in resp.json()["detail"]


async def test_no_authorize_callback_allows_everything(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresThreadStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    thread_server = ThreadServer(store=store, authenticate=auth)
    app = FastAPI()
    app.state.thread_server = thread_server
    app.include_router(thread_server.router, prefix="/acp")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/acp/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    resp = await client.delete(f"/acp/threads/{thread_id}")
    assert resp.status_code == 204
