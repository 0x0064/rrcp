from __future__ import annotations

import asyncio

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rrcp_server.protocol.content import TextPart
from rrcp_server.protocol.identity import Identity, UserIdentity
from rrcp_server.server.acp import AcpServer
from rrcp_server.server.auth import HandshakeData
from rrcp_server.store.postgres.store import PostgresThreadStore


@pytest.fixture
async def setup(clean_db: asyncpg.Pool) -> tuple[AcpServer, AsyncClient, str]:
    store = PostgresThreadStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    acp = AcpServer(store=store, authenticate=auth, run_timeout_seconds=5)

    @acp.assistant("a1")
    async def helper(ctx, send):
        yield send.reasoning("considering")
        yield send.message(content=[TextPart(text="hello back")])

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
    return acp, client, thread_id


async def test_invoke_runs_handler_to_completion(
    setup: tuple[AcpServer, AsyncClient, str],
) -> None:
    acp, client, thread_id = setup

    resp = await client.post(
        f"/acp/threads/{thread_id}/invocations",
        json={"assistant_ids": ["a1"]},
    )
    assert resp.status_code == 201
    runs = resp.json()["runs"]
    assert len(runs) == 1
    run_id = runs[0]["id"]

    await acp.executor.await_run(run_id)

    events_resp = await client.get(f"/acp/threads/{thread_id}/events")
    types = [e["type"] for e in events_resp.json()["items"]]
    assert types == ["run.started", "reasoning", "message", "run.completed"]


async def test_invoke_unknown_assistant_404(
    setup: tuple[AcpServer, AsyncClient, str],
) -> None:
    _, client, thread_id = setup
    resp = await client.post(
        f"/acp/threads/{thread_id}/invocations",
        json={"assistant_ids": ["unknown"]},
    )
    assert resp.status_code == 404


async def test_invoke_assistant_not_member_403(
    setup: tuple[AcpServer, AsyncClient, str],
) -> None:
    acp, client, thread_id = setup

    @acp.assistant("a_other")
    async def other(ctx, send):
        yield send.message(content=[TextPart(text="x")])

    resp = await client.post(
        f"/acp/threads/{thread_id}/invocations",
        json={"assistant_ids": ["a_other"]},
    )
    assert resp.status_code == 403


async def test_get_and_cancel_run(
    setup: tuple[AcpServer, AsyncClient, str],
) -> None:
    acp, client, thread_id = setup

    started = asyncio.Event()

    @acp.assistant("a_slow")
    async def slow(ctx, send):
        started.set()
        await asyncio.sleep(5)
        yield send.message(content=[TextPart(text="never")])

    await client.post(
        f"/acp/threads/{thread_id}/members",
        json={
            "identity": {
                "role": "assistant",
                "id": "a_slow",
                "name": "Slow",
                "metadata": {},
            }
        },
    )

    invoke = await client.post(
        f"/acp/threads/{thread_id}/invocations",
        json={"assistant_ids": ["a_slow"]},
    )
    run_id = invoke.json()["runs"][0]["id"]

    await asyncio.wait_for(started.wait(), timeout=2)

    get_resp = await client.get(f"/acp/runs/{run_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] in ("pending", "running")

    cancel_resp = await client.delete(f"/acp/runs/{run_id}")
    assert cancel_resp.status_code == 204

    await acp.executor.await_run(run_id)
    final = await client.get(f"/acp/runs/{run_id}")
    assert final.json()["status"] == "cancelled"


async def test_invoke_idempotency(
    setup: tuple[AcpServer, AsyncClient, str],
) -> None:
    acp, client, thread_id = setup

    r1 = await client.post(
        f"/acp/threads/{thread_id}/invocations",
        json={"assistant_ids": ["a1"], "idempotency_key": "key_x"},
    )
    run_id_1 = r1.json()["runs"][0]["id"]
    await acp.executor.await_run(run_id_1)

    r2 = await client.post(
        f"/acp/threads/{thread_id}/invocations",
        json={"assistant_ids": ["a1"], "idempotency_key": "key_x"},
    )
    assert r2.json()["runs"][0]["id"] == run_id_1
