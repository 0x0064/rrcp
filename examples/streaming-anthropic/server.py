from __future__ import annotations

import os

import asyncpg
import uvicorn
from anthropic import AsyncAnthropic
from fastapi import FastAPI

from rrcp import (
    HandshakeData,
    PostgresThreadStore,
    ThreadServer,
    UserIdentity,
)


client = AsyncAnthropic()


async def authenticate(handshake: HandshakeData) -> UserIdentity | None:
    token = handshake.headers.get("authorization", "")
    if not token.startswith("Bearer "):
        return None
    user_id = token.removeprefix("Bearer ").strip()
    if not user_id:
        return None
    return UserIdentity(id=user_id, name=user_id)


async def build_server() -> tuple[FastAPI, object]:
    pool = await asyncpg.create_pool(
        os.environ.get("DATABASE_URL", "postgresql://rrcp:rrcp@localhost:55432/rrcp_test")
    )
    thread_server = ThreadServer(
        store=PostgresThreadStore(pool=pool),
        authenticate=authenticate,
    )

    @thread_server.assistant("claude")
    async def claude(ctx, send):
        history = await ctx.events()
        messages = []
        for event in history:
            if event.type != "message":
                continue
            role = "user" if event.author.role == "user" else "assistant"
            text = "".join(p.text for p in event.content if p.type == "text")
            if text:
                messages.append({"role": role, "content": text})
        if not messages:
            return

        async with send.message_stream() as stream:
            async with client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=1024,
                messages=messages,
            ) as result:
                async for text in result.text_stream:
                    await stream.append(text)

    app = FastAPI()
    app.state.thread_server = thread_server
    app.include_router(thread_server.router, prefix="/acp")
    asgi = thread_server.mount_socketio(app)
    return app, asgi


if __name__ == "__main__":
    import asyncio

    app, asgi = asyncio.run(build_server())
    uvicorn.run(asgi, host="0.0.0.0", port=8000)
