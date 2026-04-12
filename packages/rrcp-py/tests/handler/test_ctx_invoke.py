from __future__ import annotations

from typing import Any

import asyncpg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rrcp.protocol.content import TextPart
from rrcp.protocol.identity import Identity, UserIdentity
from rrcp.server.auth import HandshakeData
from rrcp.server.thread_server import ThreadServer
from rrcp.store.postgres.store import PostgresThreadStore


async def test_ctx_invoke_chains_to_another_assistant(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresThreadStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    thread_server = ThreadServer(store=store, authenticate=auth, run_timeout_seconds=5)

    @thread_server.assistant("orchestrator")
    async def orchestrator(ctx: Any, send: Any) -> Any:
        yield send.reasoning("delegating to specialist")
        chained_run = await ctx.invoke("specialist")
        await thread_server.executor.await_run(chained_run.id)
        yield send.message(content=[TextPart(text="orchestrator done")])

    @thread_server.assistant("specialist")
    async def specialist(ctx: Any, send: Any) -> Any:
        yield send.message(content=[TextPart(text="specialist finished")])

    app = FastAPI()
    app.state.thread_server = thread_server
    app.include_router(thread_server.router, prefix="/acp")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    create = await client.post("/acp/threads", json={"tenant": {"org": "A"}})
    thread_id = create.json()["id"]

    for aid, name in [("orchestrator", "Orchestrator"), ("specialist", "Specialist")]:
        await client.post(
            f"/acp/threads/{thread_id}/members",
            json={
                "identity": {
                    "role": "assistant",
                    "id": aid,
                    "name": name,
                    "metadata": {},
                }
            },
        )

    invoke = await client.post(
        f"/acp/threads/{thread_id}/invocations",
        json={"assistant_ids": ["orchestrator"]},
    )
    orchestrator_run_id = invoke.json()["runs"][0]["id"]
    await thread_server.executor.await_run(orchestrator_run_id)

    events_resp = await client.get(f"/acp/threads/{thread_id}/events")
    events = events_resp.json()["items"]

    specialist_messages = [e for e in events if e["type"] == "message" and e["author"]["id"] == "specialist"]
    orchestrator_messages = [e for e in events if e["type"] == "message" and e["author"]["id"] == "orchestrator"]
    assert len(specialist_messages) == 1
    assert specialist_messages[0]["content"][0]["text"] == "specialist finished"
    assert len(orchestrator_messages) == 1
    assert orchestrator_messages[0]["content"][0]["text"] == "orchestrator done"

    orchestrator_completions = [
        e for e in events if e["type"] == "run.completed" and e["author"]["id"] == "orchestrator"
    ]
    specialist_completions = [e for e in events if e["type"] == "run.completed" and e["author"]["id"] == "specialist"]
    assert len(orchestrator_completions) == 1
    assert len(specialist_completions) == 1
