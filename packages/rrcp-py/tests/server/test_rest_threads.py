from __future__ import annotations

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rrcp_server.protocol.identity import Identity, UserIdentity
from rrcp_server.server.acp import AcpServer
from rrcp_server.server.auth import HandshakeData
from rrcp_server.store.postgres.store import PostgresThreadStore


def _build_app(store: PostgresThreadStore, identity: Identity) -> FastAPI:
    async def auth(_h: HandshakeData) -> Identity:
        return identity

    acp = AcpServer(store=store, authenticate=auth)
    app = FastAPI()
    app.state.acp = acp
    app.include_router(acp.router, prefix="/acp")
    return app


@pytest.fixture
def alice() -> UserIdentity:
    return UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})


@pytest.fixture
async def client(clean_db: asyncpg.Pool, alice: UserIdentity) -> AsyncClient:
    store = PostgresThreadStore(pool=clean_db)
    app = _build_app(store, alice)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_post_threads_creates_a_thread(client: AsyncClient) -> None:
    resp = await client.post(
        "/acp/threads",
        json={"tenant": {"org": "A"}, "metadata": {"title": "test"}},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["tenant"] == {"org": "A"}
    assert body["metadata"] == {"title": "test"}
    assert body["id"].startswith("th_")


async def test_get_threads_filters_by_tenant(client: AsyncClient) -> None:
    await client.post("/acp/threads", json={"tenant": {"org": "A"}})
    await client.post("/acp/threads", json={"tenant": {"org": "A", "ws": "X"}})
    await client.post("/acp/threads", json={"tenant": {"org": "B"}})

    resp = await client.get("/acp/threads")
    assert resp.status_code == 200
    items = resp.json()["items"]
    tenants = [t["tenant"] for t in items]
    assert {"org": "A"} in tenants
    assert {"org": "B"} not in tenants
    assert {"org": "A", "ws": "X"} not in tenants


async def test_get_thread_by_id(client: AsyncClient) -> None:
    create = await client.post("/acp/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    resp = await client.get(f"/acp/threads/{thread_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == thread_id


async def test_get_thread_404(client: AsyncClient) -> None:
    resp = await client.get("/acp/threads/th_nope")
    assert resp.status_code == 404


async def test_patch_thread_metadata(client: AsyncClient) -> None:
    create = await client.post("/acp/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    resp = await client.patch(f"/acp/threads/{thread_id}", json={"metadata": {"locked": True}})
    assert resp.status_code == 200
    assert resp.json()["metadata"] == {"locked": True}


async def test_patch_thread_tenant_emits_event(client: AsyncClient) -> None:
    create = await client.post("/acp/threads", json={"tenant": {}})
    thread_id = create.json()["id"]

    resp = await client.patch(f"/acp/threads/{thread_id}", json={"tenant": {"org": "A"}})
    assert resp.status_code == 200

    events_resp = await client.get(f"/acp/threads/{thread_id}/events")
    events = events_resp.json()["items"]
    tenant_changed = [e for e in events if e["type"] == "thread.tenant_changed"]
    assert len(tenant_changed) == 1
    assert tenant_changed[0]["from"] == {}
    assert tenant_changed[0]["to"] == {"org": "A"}


async def test_create_thread_rejects_tenant_missing_namespace_keys(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresThreadStore(pool=clean_db)
    alice_id = UserIdentity(
        id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}}
    )

    async def auth(_h: HandshakeData) -> Identity:
        return alice_id

    acp = AcpServer(
        store=store,
        authenticate=auth,
        namespace_keys=["org"],
    )
    app = FastAPI()
    app.state.acp = acp
    app.include_router(acp.router, prefix="/acp")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/acp/threads", json={"tenant": {}})
        assert r.status_code == 400
        assert "namespace_keys" in r.text


async def test_rest_rejects_identity_missing_namespace_key(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresThreadStore(pool=clean_db)
    charlie = UserIdentity(id="u_charlie", name="Charlie", metadata={})

    async def auth(_h: HandshakeData) -> Identity:
        return charlie

    acp = AcpServer(
        store=store,
        authenticate=auth,
        namespace_keys=["org"],
    )
    app = FastAPI()
    app.state.acp = acp
    app.include_router(acp.router, prefix="/acp")
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/acp/threads")
        assert r.status_code == 403
        assert "namespace" in r.text.lower()


async def test_delete_thread(client: AsyncClient) -> None:
    create = await client.post("/acp/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]
    await client.post(
        f"/acp/threads/{thread_id}/messages",
        json={"client_id": "x", "content": [{"type": "text", "text": "hi"}]},
    )

    resp = await client.delete(f"/acp/threads/{thread_id}")
    assert resp.status_code == 204

    get_resp = await client.get(f"/acp/threads/{thread_id}")
    assert get_resp.status_code == 404
