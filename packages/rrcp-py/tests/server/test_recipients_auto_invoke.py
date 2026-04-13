from __future__ import annotations

import asyncio

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rrcp.protocol.content import TextPart
from rrcp.protocol.identity import Identity, UserIdentity
from rrcp.server.auth import HandshakeData
from rrcp.server.thread_server import ThreadServer
from rrcp.store.postgres.store import PostgresThreadStore


async def _build_env(
    clean_db: asyncpg.Pool,
    *,
    auto_invoke_recipients: bool = True,
) -> tuple[ThreadServer, AsyncClient, str, list[str]]:
    store = PostgresThreadStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    server = ThreadServer(
        store=store,
        authenticate=auth,
        run_timeout_seconds=5,
        auto_invoke_recipients=auto_invoke_recipients,
    )
    ran: list[str] = []

    @server.assistant("specialist")
    async def specialist(ctx, send):
        ran.append(ctx.run.id)
        yield send.message(content=[TextPart(text="specialist answered")])

    app = FastAPI()
    app.state.thread_server = server
    app.include_router(server.router, prefix="/acp")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/acp/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]
    await client.post(
        f"/acp/threads/{thread_id}/members",
        json={
            "identity": {
                "role": "assistant",
                "id": "specialist",
                "name": "Specialist",
                "metadata": {},
            }
        },
    )
    return server, client, thread_id, ran


@pytest.fixture
async def env(clean_db: asyncpg.Pool) -> tuple[ThreadServer, AsyncClient, str, list[str]]:
    return await _build_env(clean_db)


async def test_assistant_in_recipients_triggers_handler(
    env: tuple[ThreadServer, AsyncClient, str, list[str]],
) -> None:
    server, client, thread_id, ran = env

    response = await client.post(
        f"/acp/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "hello specialist"}],
            "recipients": ["specialist"],
        },
    )
    assert response.status_code == 201
    assert response.json()["recipients"] == ["specialist"]

    for task in list(server.executor._tasks.values()):
        try:
            await task
        except Exception:
            pass

    assert len(ran) == 1


async def test_broadcast_does_not_auto_invoke(
    env: tuple[ThreadServer, AsyncClient, str, list[str]],
) -> None:
    server, client, thread_id, ran = env

    response = await client.post(
        f"/acp/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "team chat, no target"}],
        },
    )
    assert response.status_code == 201
    assert response.json()["recipients"] is None

    await asyncio.sleep(0.1)
    for task in list(server.executor._tasks.values()):
        try:
            await task
        except Exception:
            pass

    assert ran == []


async def test_recipient_not_member_returns_400(
    env: tuple[ThreadServer, AsyncClient, str, list[str]],
) -> None:
    _, client, thread_id, _ = env

    response = await client.post(
        f"/acp/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "ghost"}],
            "recipients": ["ghost-id"],
        },
    )
    assert response.status_code == 400
    assert "recipient_not_member" in response.json()["detail"]


async def test_auto_invoke_disabled_preserves_current_behavior(
    clean_db: asyncpg.Pool,
) -> None:
    server, client, thread_id, ran = await _build_env(
        clean_db,
        auto_invoke_recipients=False,
    )

    response = await client.post(
        f"/acp/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "hello"}],
            "recipients": ["specialist"],
        },
    )
    assert response.status_code == 201
    assert response.json()["recipients"] == ["specialist"]

    await asyncio.sleep(0.1)
    for task in list(server.executor._tasks.values()):
        try:
            await task
        except Exception:
            pass

    assert ran == []
