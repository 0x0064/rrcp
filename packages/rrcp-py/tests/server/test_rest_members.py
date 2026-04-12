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
async def setup(clean_db: asyncpg.Pool) -> tuple[AsyncClient, str]:
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
    return client, create.json()["id"]


async def test_list_members_includes_creator(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    resp = await client.get(f"/acp/threads/{thread_id}/members")
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 1
    assert members[0]["identity_id"] == "u_alice"


async def test_add_member(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    resp = await client.post(
        f"/acp/threads/{thread_id}/members",
        json={
            "identity": {
                "role": "user",
                "id": "u_bob",
                "name": "Bob",
                "metadata": {},
            }
        },
    )
    assert resp.status_code == 201

    list_resp = await client.get(f"/acp/threads/{thread_id}/members")
    ids = {m["identity_id"] for m in list_resp.json()}
    assert ids == {"u_alice", "u_bob"}


async def test_remove_member(setup: tuple[AsyncClient, str]) -> None:
    client, thread_id = setup
    await client.post(
        f"/acp/threads/{thread_id}/members",
        json={
            "identity": {
                "role": "user",
                "id": "u_bob",
                "name": "Bob",
                "metadata": {},
            }
        },
    )
    resp = await client.delete(f"/acp/threads/{thread_id}/members/u_bob")
    assert resp.status_code == 204

    list_resp = await client.get(f"/acp/threads/{thread_id}/members")
    ids = {m["identity_id"] for m in list_resp.json()}
    assert ids == {"u_alice"}
