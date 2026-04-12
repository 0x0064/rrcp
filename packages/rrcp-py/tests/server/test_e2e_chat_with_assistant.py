from __future__ import annotations

import asyncpg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rrcp_server.protocol.content import TextPart
from rrcp_server.protocol.identity import Identity, UserIdentity
from rrcp_server.server.acp import AcpServer
from rrcp_server.server.auth import HandshakeData
from rrcp_server.store.postgres.store import PostgresThreadStore


async def test_full_chat_with_assistant(clean_db: asyncpg.Pool) -> None:
    store = PostgresThreadStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    acp = AcpServer(store=store, authenticate=auth, run_timeout_seconds=5)

    @acp.assistant("a1")
    async def helper(ctx, send):
        history = await ctx.events()
        last_user = next((e for e in reversed(history) if e.author.role == "user"), None)
        echo = "I heard nothing"
        if last_user is not None and getattr(last_user, "content", None):
            first_part = last_user.content[0]
            if hasattr(first_part, "text"):
                echo = f"You said: {first_part.text}"
        yield send.reasoning("looking at history")
        yield send.tool_call(name="echo", arguments={"input": echo}, id="call_x")
        yield send.tool_result(tool_id="call_x", result={"echo": echo})
        yield send.message(content=[TextPart(text=echo)])

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

    await client.post(
        f"/acp/threads/{thread_id}/messages",
        json={
            "client_id": "u1",
            "content": [{"type": "text", "text": "hello world"}],
        },
    )

    invoke = await client.post(
        f"/acp/threads/{thread_id}/invocations",
        json={"assistant_ids": ["a1"]},
    )
    run_id = invoke.json()["runs"][0]["id"]
    await acp.executor.await_run(run_id)

    events = (await client.get(f"/acp/threads/{thread_id}/events")).json()["items"]
    types = [e["type"] for e in events]
    assert types == [
        "message",
        "run.started",
        "reasoning",
        "tool.call",
        "tool.result",
        "message",
        "run.completed",
    ]

    last_message = events[-2]
    assert last_message["author"]["id"] == "a1"
    assert last_message["content"][0]["text"] == "You said: hello world"
