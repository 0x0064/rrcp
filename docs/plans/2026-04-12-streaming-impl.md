# Streaming Primitive Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an ephemeral streaming primitive to `rrcp-py` that lets assistant handlers deliver incremental `message` and `reasoning` content over Socket.IO without persisting deltas.

**Architecture:** Three new Socket.IO broadcast channels (`stream:start`, `stream:delta`, `stream:end`) carry ephemeral frames. A `Stream` async context manager on `HandlerSend` drives the lifecycle: start on `__aenter__`, delta on `append()`, end + final atomic event on `__aexit__` (success) or end with error (exception/cancellation). Deltas never touch `ThreadStore` — the event log stays untouched. Implementation is additive and non-breaking; handlers that don't stream keep working exactly as before.

**Tech Stack:** Python 3.11+, Pydantic v2, `python-socketio`, FastAPI. Style: ruff (line length 120, double quotes), mypy strict, no comments, Pydantic frozen models with `extra="forbid"`.

**Reference design:** `docs/plans/2026-04-12-streaming-design.md`

---

## Conventions (read before starting any task)

- **No comments in any file this plan touches.** Names and structure must carry the meaning.
- **Match existing patterns exactly.** Study `protocol/event.py`, `handler/send.py`, `broadcast/socketio.py`, `server/thread_server.py` before writing new code. Frozen Pydantic models use `ConfigDict(extra="forbid", frozen=True, populate_by_name=True)`. Private helpers start with `_`. Files are snake_case, classes PascalCase.
- **Tests only where a lifecycle guarantee is non-obvious.** No edge-case exhaustion. One happy path + one exception path is enough. The existing `RecordingBroadcaster` is the test sink.
- **Commit after each task.** Use `feat:` for new capability, `chore:` for re-exports and docs, `test:` for tests, `docs:` for README/CHANGELOG.
- **Working directory:** `packages/rrcp-py/` for server tasks. Run checks from there with `uv run poe dev`.

---

## Task 1: Protocol frame models

**Files:**
- Create: `packages/rrcp-py/src/rrcp/protocol/stream.py`

**Step 1: Write `protocol/stream.py`**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from rrcp.protocol.identity import AssistantIdentity


StreamTargetType = Literal["message", "reasoning"]


class StreamError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class StreamStartFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    thread_id: str
    run_id: str
    target_type: StreamTargetType
    author: AssistantIdentity


class StreamDeltaFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    thread_id: str
    text: str


class StreamEndFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    thread_id: str
    error: StreamError | None = None
```

**Step 2: Typecheck & lint**

```bash
cd packages/rrcp-py
uv run poe check
uv run poe typecheck
```

Expected: clean.

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/protocol/stream.py
git commit -m "feat(rrcp-py): add stream frame models"
```

---

## Task 2: Broadcaster protocol extension

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/broadcast/protocol.py`

**Step 1: Add three methods to the `Broadcaster` Protocol**

Full replacement of the file:

```python
from __future__ import annotations

from typing import Protocol

from rrcp.protocol.event import Event
from rrcp.protocol.identity import Identity
from rrcp.protocol.run import Run
from rrcp.protocol.stream import StreamDeltaFrame, StreamEndFrame, StreamStartFrame
from rrcp.protocol.thread import Thread


class Broadcaster(Protocol):
    async def broadcast_event(self, event: Event, *, namespace: str | None = None) -> None: ...
    async def broadcast_thread_updated(self, thread: Thread, *, namespace: str | None = None) -> None: ...
    async def broadcast_members_updated(
        self,
        thread_id: str,
        members: list[Identity],
        *,
        namespace: str | None = None,
    ) -> None: ...
    async def broadcast_run_updated(self, run: Run, *, namespace: str | None = None) -> None: ...
    async def broadcast_stream_start(
        self,
        frame: StreamStartFrame,
        *,
        namespace: str | None = None,
    ) -> None: ...
    async def broadcast_stream_delta(
        self,
        frame: StreamDeltaFrame,
        *,
        namespace: str | None = None,
    ) -> None: ...
    async def broadcast_stream_end(
        self,
        frame: StreamEndFrame,
        *,
        namespace: str | None = None,
    ) -> None: ...
```

**Step 2: Typecheck**

```bash
cd packages/rrcp-py
uv run poe typecheck
```

Expected: `SocketIOBroadcaster` and `RecordingBroadcaster` fail — they don't implement the new methods yet. That's fine, we fix them next.

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/broadcast/protocol.py
git commit -m "feat(rrcp-py): extend Broadcaster protocol with stream methods"
```

---

## Task 3: SocketIOBroadcaster implementation

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/broadcast/socketio.py`

**Step 1: Add three methods**

Append to `SocketIOBroadcaster` (preserving existing imports — add `StreamDeltaFrame, StreamEndFrame, StreamStartFrame` from `rrcp.protocol.stream`):

```python
    async def broadcast_stream_start(
        self,
        frame: StreamStartFrame,
        *,
        namespace: str | None = None,
    ) -> None:
        await self._sio.emit(
            "stream:start",
            frame.model_dump(mode="json", by_alias=True),
            room=_thread_room(frame.thread_id),
            namespace=namespace or "/",
        )

    async def broadcast_stream_delta(
        self,
        frame: StreamDeltaFrame,
        *,
        namespace: str | None = None,
    ) -> None:
        await self._sio.emit(
            "stream:delta",
            frame.model_dump(mode="json", by_alias=True),
            room=_thread_room(frame.thread_id),
            namespace=namespace or "/",
        )

    async def broadcast_stream_end(
        self,
        frame: StreamEndFrame,
        *,
        namespace: str | None = None,
    ) -> None:
        await self._sio.emit(
            "stream:end",
            frame.model_dump(mode="json", by_alias=True),
            room=_thread_room(frame.thread_id),
            namespace=namespace or "/",
        )
```

**Step 2: Typecheck**

```bash
cd packages/rrcp-py
uv run poe typecheck
```

Expected: `RecordingBroadcaster` still fails. Good.

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/broadcast/socketio.py
git commit -m "feat(rrcp-py): SocketIOBroadcaster stream channels"
```

---

## Task 4: RecordingBroadcaster implementation

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/broadcast/recording.py`

**Step 1: Add stream recording**

Add to imports: `from rrcp.protocol.stream import StreamDeltaFrame, StreamEndFrame, StreamStartFrame`.

Add to `__init__`:

```python
        self.stream_starts: list[StreamStartFrame] = []
        self.stream_deltas: list[StreamDeltaFrame] = []
        self.stream_ends: list[StreamEndFrame] = []
```

Add three methods to the class:

```python
    async def broadcast_stream_start(
        self,
        frame: StreamStartFrame,
        *,
        namespace: str | None = None,
    ) -> None:
        self.stream_starts.append(frame)

    async def broadcast_stream_delta(
        self,
        frame: StreamDeltaFrame,
        *,
        namespace: str | None = None,
    ) -> None:
        self.stream_deltas.append(frame)

    async def broadcast_stream_end(
        self,
        frame: StreamEndFrame,
        *,
        namespace: str | None = None,
    ) -> None:
        self.stream_ends.append(frame)
```

**Step 2: Typecheck**

```bash
cd packages/rrcp-py
uv run poe typecheck
```

Expected: clean.

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/broadcast/recording.py
git commit -m "feat(rrcp-py): RecordingBroadcaster stream capture"
```

---

## Task 5: StreamSink protocol and Stream class

**Files:**
- Create: `packages/rrcp-py/src/rrcp/handler/stream.py`

**Step 1: Write `handler/stream.py`**

```python
from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from typing import Any, Protocol

from rrcp.protocol.content import TextPart
from rrcp.protocol.event import Event, MessageEvent, ReasoningEvent
from rrcp.protocol.identity import AssistantIdentity
from rrcp.protocol.stream import (
    StreamDeltaFrame,
    StreamEndFrame,
    StreamError,
    StreamStartFrame,
    StreamTargetType,
)


class StreamSink(Protocol):
    async def start(self, frame: StreamStartFrame) -> None: ...
    async def delta(self, frame: StreamDeltaFrame) -> None: ...
    async def end(self, frame: StreamEndFrame) -> None: ...
    async def publish_event(self, event: Event) -> Event: ...


def _new_event_id() -> str:
    return f"evt_{secrets.token_hex(8)}"


class Stream:
    def __init__(
        self,
        sink: StreamSink,
        target_type: StreamTargetType,
        thread_id: str,
        run_id: str,
        author: AssistantIdentity,
        metadata: dict[str, Any] | None,
    ) -> None:
        self._sink = sink
        self._target_type = target_type
        self._thread_id = thread_id
        self._run_id = run_id
        self._author = author
        self._metadata = metadata or {}
        self._buffer: list[str] = []
        self.event_id = _new_event_id()

    async def __aenter__(self) -> Stream:
        await self._sink.start(
            StreamStartFrame(
                event_id=self.event_id,
                thread_id=self._thread_id,
                run_id=self._run_id,
                target_type=self._target_type,
                author=self._author,
            )
        )
        return self

    async def append(self, text: str) -> None:
        if not text:
            return
        self._buffer.append(text)
        await self._sink.delta(
            StreamDeltaFrame(
                event_id=self.event_id,
                thread_id=self._thread_id,
                text=text,
            )
        )

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            await self._sink.end(
                StreamEndFrame(
                    event_id=self.event_id,
                    thread_id=self._thread_id,
                    error=None,
                )
            )
            await self._sink.publish_event(self._build_event())
            return
        error = self._error_for(exc_type, exc)
        await self._sink.end(
            StreamEndFrame(
                event_id=self.event_id,
                thread_id=self._thread_id,
                error=error,
            )
        )

    def _build_event(self) -> Event:
        text = "".join(self._buffer)
        now = datetime.now(UTC)
        if self._target_type == "message":
            return MessageEvent(
                id=self.event_id,
                thread_id=self._thread_id,
                run_id=self._run_id,
                author=self._author,
                created_at=now,
                metadata=self._metadata,
                content=[TextPart(text=text)],
            )
        return ReasoningEvent(
            id=self.event_id,
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            created_at=now,
            metadata=self._metadata,
            content=text,
        )

    def _error_for(self, exc_type: Any, exc: Any) -> StreamError:
        if exc_type is asyncio.CancelledError:
            return StreamError(code="cancelled", message="run cancelled")
        if exc_type is TimeoutError:
            return StreamError(code="timeout", message="run timed out")
        return StreamError(code="handler_error", message=str(exc) or exc_type.__name__)
```

**Step 2: Typecheck & lint**

```bash
cd packages/rrcp-py
uv run poe check
uv run poe typecheck
```

Expected: clean.

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/handler/stream.py
git commit -m "feat(rrcp-py): Stream context manager and StreamSink protocol"
```

---

## Task 6: HandlerSend gains stream factories

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/handler/send.py`

**Step 1: Add sink parameter and stream methods**

Change the imports to add:

```python
from rrcp.handler.stream import Stream, StreamSink
```

Change `HandlerSend.__init__` to accept an optional sink and store it:

```python
    def __init__(
        self,
        thread_id: str,
        run_id: str,
        author: AssistantIdentity,
        stream_sink: StreamSink | None = None,
    ) -> None:
        self._thread_id = thread_id
        self._run_id = run_id
        self._author = author
        self._stream_sink = stream_sink
```

Append two methods to the class:

```python
    def message_stream(self, metadata: dict[str, Any] | None = None) -> Stream:
        sink = self._require_sink()
        return Stream(
            sink=sink,
            target_type="message",
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            metadata=metadata,
        )

    def reasoning_stream(self, metadata: dict[str, Any] | None = None) -> Stream:
        sink = self._require_sink()
        return Stream(
            sink=sink,
            target_type="reasoning",
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            metadata=metadata,
        )

    def _require_sink(self) -> StreamSink:
        if self._stream_sink is None:
            raise RuntimeError("streaming is not available: no stream_sink configured")
        return self._stream_sink
```

**Step 2: Typecheck**

```bash
cd packages/rrcp-py
uv run poe typecheck
```

Expected: clean.

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/handler/send.py
git commit -m "feat(rrcp-py): HandlerSend message_stream and reasoning_stream"
```

---

## Task 7: Executor wires a per-run StreamSink

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/handler/executor.py`

**Step 1: Add sink factory parameter and wire it into the run**

Add to imports:

```python
from collections.abc import Callable

from rrcp.handler.stream import StreamSink
```

(`Callable` is already imported via `from collections.abc import Callable`.)

Add to the module:

```python
StreamSinkFactory = Callable[[Thread], StreamSink]
```

Extend `RunExecutor.__init__` to accept an optional factory and store it:

```python
    def __init__(
        self,
        store: ThreadStore,
        on_analytics: OnAnalyticsCallback | None = None,
        run_timeout_seconds: int = 120,
        publish_event: PublishEventCallable | None = None,
        handler_resolver: HandlerResolver | None = None,
        stream_sink_factory: StreamSinkFactory | None = None,
    ) -> None:
```

At the end of `__init__`, add:

```python
        self._stream_sink_factory = stream_sink_factory
```

In `_drive`, replace the current `HandlerSend(...)` construction with:

```python
            stream_sink = (
                self._stream_sink_factory(thread) if self._stream_sink_factory is not None else None
            )
            send = HandlerSend(
                thread_id=thread.id,
                run_id=run.id,
                author=assistant,
                stream_sink=stream_sink,
            )
```

**Step 2: Typecheck**

```bash
cd packages/rrcp-py
uv run poe typecheck
```

Expected: clean.

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/handler/executor.py
git commit -m "feat(rrcp-py): executor wires per-run StreamSink into HandlerSend"
```

---

## Task 8: ThreadServer builds the StreamSink

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/server/thread_server.py`

**Step 1: Add broadcast methods and a sink factory**

Add to imports:

```python
from rrcp.handler.stream import StreamSink
from rrcp.protocol.stream import StreamDeltaFrame, StreamEndFrame, StreamStartFrame
```

Add three methods to `ThreadServer` (alongside the existing `publish_*` methods):

```python
    async def broadcast_stream_start(self, frame: StreamStartFrame, *, thread: Thread) -> None:
        if self.broadcaster is None:
            return
        namespace = self.namespace_for_thread(thread)
        await self.broadcaster.broadcast_stream_start(frame, namespace=namespace)

    async def broadcast_stream_delta(self, frame: StreamDeltaFrame, *, thread: Thread) -> None:
        if self.broadcaster is None:
            return
        namespace = self.namespace_for_thread(thread)
        await self.broadcaster.broadcast_stream_delta(frame, namespace=namespace)

    async def broadcast_stream_end(self, frame: StreamEndFrame, *, thread: Thread) -> None:
        if self.broadcaster is None:
            return
        namespace = self.namespace_for_thread(thread)
        await self.broadcaster.broadcast_stream_end(frame, namespace=namespace)
```

Add a bound sink adapter at module level (below `_validate_namespace_keys`):

```python
class _BoundStreamSink:
    def __init__(self, server: ThreadServer, thread: Thread) -> None:
        self._server = server
        self._thread = thread

    async def start(self, frame: StreamStartFrame) -> None:
        await self._server.broadcast_stream_start(frame, thread=self._thread)

    async def delta(self, frame: StreamDeltaFrame) -> None:
        await self._server.broadcast_stream_delta(frame, thread=self._thread)

    async def end(self, frame: StreamEndFrame) -> None:
        await self._server.broadcast_stream_end(frame, thread=self._thread)

    async def publish_event(self, event: Event) -> Event:
        return await self._server.publish_event(event, thread=self._thread)
```

In `ThreadServer.__init__`, change the executor construction to pass the factory:

```python
        self.executor = RunExecutor(
            store=store,
            on_analytics=on_analytics,
            run_timeout_seconds=run_timeout_seconds,
            publish_event=self.publish_event,
            handler_resolver=self.get_handler,
            stream_sink_factory=self._make_stream_sink,
        )
```

And add the factory method:

```python
    def _make_stream_sink(self, thread: Thread) -> StreamSink:
        return _BoundStreamSink(self, thread)
```

**Step 2: Typecheck & lint**

```bash
cd packages/rrcp-py
uv run poe check
uv run poe typecheck
```

Expected: clean.

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/server/thread_server.py
git commit -m "feat(rrcp-py): ThreadServer builds per-run stream sink"
```

---

## Task 9: Top-level re-exports

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/__init__.py`

**Step 1: Add new imports**

Add:

```python
from rrcp.handler.stream import Stream, StreamSink
from rrcp.protocol.stream import (
    StreamDeltaFrame,
    StreamEndFrame,
    StreamError,
    StreamStartFrame,
    StreamTargetType,
)
```

Add to `__all__` (keep the list alphabetised to match existing style):

```
"Stream",
"StreamDeltaFrame",
"StreamEndFrame",
"StreamError",
"StreamSink",
"StreamStartFrame",
"StreamTargetType",
```

**Step 2: Typecheck**

```bash
cd packages/rrcp-py
uv run poe typecheck
```

Expected: clean.

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/__init__.py
git commit -m "chore(rrcp-py): re-export streaming primitives"
```

---

## Task 10: Lifecycle tests

**Files:**
- Create: `packages/rrcp-py/tests/handler/test_stream.py`

Two tests only. No edges. Both drive a `HandlerSend` directly with `RecordingBroadcaster` as the sink — no executor, no postgres, no network.

**Step 1: Write the test file**

```python
from __future__ import annotations

import pytest

from rrcp.broadcast.recording import RecordingBroadcaster
from rrcp.handler.send import HandlerSend
from rrcp.handler.stream import StreamSink
from rrcp.protocol.event import Event, MessageEvent
from rrcp.protocol.identity import AssistantIdentity
from rrcp.protocol.stream import StreamDeltaFrame, StreamEndFrame, StreamStartFrame


class _FakeSink:
    def __init__(self) -> None:
        self.broadcaster = RecordingBroadcaster()
        self.published: list[Event] = []

    async def start(self, frame: StreamStartFrame) -> None:
        await self.broadcaster.broadcast_stream_start(frame)

    async def delta(self, frame: StreamDeltaFrame) -> None:
        await self.broadcaster.broadcast_stream_delta(frame)

    async def end(self, frame: StreamEndFrame) -> None:
        await self.broadcaster.broadcast_stream_end(frame)

    async def publish_event(self, event: Event) -> Event:
        self.published.append(event)
        return event


def _send(sink: StreamSink) -> HandlerSend:
    return HandlerSend(
        thread_id="th_test",
        run_id="run_test",
        author=AssistantIdentity(id="asst", name="asst"),
        stream_sink=sink,
    )


async def test_message_stream_happy_path() -> None:
    sink = _FakeSink()
    send = _send(sink)

    async with send.message_stream() as stream:
        await stream.append("hello")
        await stream.append(" world")

    assert len(sink.broadcaster.stream_starts) == 1
    assert [d.text for d in sink.broadcaster.stream_deltas] == ["hello", " world"]
    assert len(sink.broadcaster.stream_ends) == 1
    assert sink.broadcaster.stream_ends[0].error is None
    assert len(sink.published) == 1

    event = sink.published[0]
    assert isinstance(event, MessageEvent)
    assert event.content[0].type == "text"
    assert event.content[0].text == "hello world"


async def test_message_stream_handler_error_publishes_no_event() -> None:
    sink = _FakeSink()
    send = _send(sink)

    with pytest.raises(RuntimeError):
        async with send.message_stream() as stream:
            await stream.append("partial")
            raise RuntimeError("boom")

    assert len(sink.broadcaster.stream_starts) == 1
    assert len(sink.broadcaster.stream_deltas) == 1
    assert len(sink.broadcaster.stream_ends) == 1
    end = sink.broadcaster.stream_ends[0]
    assert end.error is not None
    assert end.error.code == "handler_error"
    assert sink.published == []
```

**Step 2: Run the tests**

```bash
cd packages/rrcp-py
uv run pytest tests/handler/test_stream.py -v
```

Expected: 2 passed.

**Step 3: Commit**

```bash
git add packages/rrcp-py/tests/handler/test_stream.py
git commit -m "test(rrcp-py): stream lifecycle happy path and handler error"
```

---

## Task 11: CHANGELOG entry

**Files:**
- Modify: `packages/rrcp-py/CHANGELOG.md`

**Step 1: Add an `Unreleased` entry**

Read the current top of `CHANGELOG.md` and add under `## [Unreleased]`:

```markdown
### Added

- Streaming primitive: `HandlerSend.message_stream()` and `HandlerSend.reasoning_stream()` async context managers, with ephemeral `stream:start` / `stream:delta` / `stream:end` Socket.IO broadcast channels. Deltas are not persisted; the final `MessageEvent` / `ReasoningEvent` is appended to the store on clean stream exit. On exception or cancellation, `stream:end` carries an error and no final event is published. See `docs/plans/2026-04-12-streaming-design.md`.
- `Broadcaster` protocol gains `broadcast_stream_start`, `broadcast_stream_delta`, `broadcast_stream_end`. Implemented by `SocketIOBroadcaster` and `RecordingBroadcaster`.
```

This is additive — not a breaking change. No major bump.

**Step 2: Commit**

```bash
git add packages/rrcp-py/CHANGELOG.md
git commit -m "docs(rrcp-py): changelog entry for streaming primitive"
```

---

## Task 12: Root README update

**Files:**
- Modify: `README.md`

**Step 1: Edit the "Deliberately small" paragraph**

Locate the line in the Architecture section that reads:

> **Deliberately small.** No streaming, no MCP client, no A2A, no settings broadcaster, no knowledge sources, no built-in form rendering, no built-in blob storage. If you need these, you bring them.

Replace with:

> **Deliberately small.** No MCP client, no A2A, no settings broadcaster, no knowledge sources, no built-in form rendering, no built-in blob storage. If you need these, you bring them.
>
> **Streaming is first-class but ephemeral.** Handlers can stream `message` and `reasoning` events via an async context manager. Deltas ride dedicated Socket.IO channels and are never persisted — only the final event lands in the log, so replay and `thread:join` stay one-row-per-message regardless of stream length.

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: mention streaming in root README"
```

---

## Task 13: Anthropic streaming example

**Files:**
- Create: `examples/streaming-anthropic/README.md`
- Create: `examples/streaming-anthropic/server.py`
- Create: `examples/streaming-anthropic/pyproject.toml`

The example is a runnable FastAPI server with one assistant that streams a reply from `claude-opus-4-6` via the `anthropic` SDK. It shows the streaming primitive in its native habitat.

**Step 1: Write `examples/streaming-anthropic/pyproject.toml`**

```toml
[project]
name = "rrcp-example-streaming-anthropic"
version = "0.0.0"
requires-python = ">=3.11"
dependencies = [
    "rrcp>=0.2.0",
    "anthropic>=0.40.0",
    "fastapi>=0.115",
    "uvicorn>=0.32",
    "asyncpg>=0.30",
]
```

**Step 2: Write `examples/streaming-anthropic/server.py`**

```python
from __future__ import annotations

import os

import asyncpg
import uvicorn
from anthropic import AsyncAnthropic
from fastapi import FastAPI

from rrcp import (
    HandshakeData,
    PostgresThreadStore,
    TextPart,
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
```

**Step 3: Write `examples/streaming-anthropic/README.md`**

```markdown
# Streaming with Anthropic

A minimal rrcp server that streams a Claude reply into a thread using the `message_stream()` primitive.

## What this shows

- One assistant registered with `@thread_server.assistant("claude")`
- Handler reads thread history via `ctx.events()` and maps it to Anthropic's message shape
- Handler opens a `send.message_stream()` context manager
- Each text chunk from `anthropic.messages.stream` is pushed via `stream.append()`
- On clean exit, the final `MessageEvent` is persisted and broadcast on the `event` channel
- On exception or run cancellation, `stream:end` carries an error and nothing is persisted

No deltas are stored. Late joiners of the thread see exactly one `MessageEvent` with the full reply.

## Run it

### 1. Start Postgres

Use the rrcp test compose file or any local Postgres instance:

```bash
docker compose -f ../../packages/rrcp-py/docker-compose.test.yml up -d
```

### 2. Export your Anthropic key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Install and run

```bash
cd examples/streaming-anthropic
uv sync
uv run python server.py
```

The server listens on `http://localhost:8000`. REST endpoints are mounted under `/acp`, Socket.IO under `/acp/ws`.

### 4. Talk to it

Any rrcp client can connect. Pass `Authorization: Bearer <user_id>` — the handshake callback treats the token as the user id for this demo. Create a thread, add the assistant identity `{id: "claude", name: "claude", role: "assistant"}` as a member, post a message, and invoke the `claude` assistant. You'll see:

- `stream:start` on the thread room
- N `stream:delta` frames as tokens arrive
- `stream:end` (no error)
- The final `MessageEvent` on the `event` channel

## Wire-level walkthrough

```
client → POST /acp/threads/{id}/messages          (user message persisted + broadcast)
client → POST /acp/threads/{id}/invocations       (run created)
server ← run.started                              (broadcast on event)
server ← stream:start { event_id, run_id, ... }   (stream channel)
server ← stream:delta { event_id, text: "Hello" } (stream channel)
server ← stream:delta { event_id, text: " there" }
...
server ← stream:end { event_id }                  (stream channel)
server ← MessageEvent { id: event_id, ... }       (broadcast on event, persisted)
server ← run.completed                            (broadcast on event)
```

The `event_id` is the same across `stream:start`, every `stream:delta`, `stream:end`, and the final persisted `MessageEvent`.
```

**Step 4: Commit**

```bash
git add examples/streaming-anthropic
git commit -m "docs: streaming-anthropic example"
```

---

## Task 14: Full sanity check

**Step 1: Run the whole dev suite**

```bash
cd packages/rrcp-py
uv run poe dev
```

Expected: lint clean, mypy clean, all tests passing (existing tests plus the two new stream tests).

**Step 2: If anything fails, fix the root cause and rerun.** Do not skip, do not silence, do not adapt tests to broken behavior.

**Step 3: No commit unless a fix was needed.**

---

## Out of scope for this plan

These are deliberately deferred:

- **`rrcp-react` client updates.** The three `stream:*` Socket.IO subscriptions, placeholder event store slice, and `useThreadStream` hook are a separate implementation plan — write it once the Python side is in and a real UI needs the primitive.
- **`rrcp-ts` parity.** Scaffold package; mirror the Python design when that package is promoted past scaffold status.
- **Delta buffering / coalescing.** `Stream.append()` broadcasts immediately. If a consumer hits wire chatter issues, they batch tokens in the handler before calling `append()`. Server-side coalescing is a future optimization.
- **Concurrent streams per run.** No cap. Handlers are expected to open one stream at a time per run in normal use.

---

## Summary of touched files

```
packages/rrcp-py/src/rrcp/protocol/stream.py           (new)
packages/rrcp-py/src/rrcp/handler/stream.py            (new)
packages/rrcp-py/src/rrcp/handler/send.py              (modified)
packages/rrcp-py/src/rrcp/handler/executor.py          (modified)
packages/rrcp-py/src/rrcp/broadcast/protocol.py        (modified)
packages/rrcp-py/src/rrcp/broadcast/socketio.py        (modified)
packages/rrcp-py/src/rrcp/broadcast/recording.py       (modified)
packages/rrcp-py/src/rrcp/server/thread_server.py     (modified)
packages/rrcp-py/src/rrcp/__init__.py                  (modified)
packages/rrcp-py/tests/handler/test_stream.py          (new)
packages/rrcp-py/CHANGELOG.md                          (modified)
README.md                                              (modified)
examples/streaming-anthropic/pyproject.toml            (new)
examples/streaming-anthropic/server.py                 (new)
examples/streaming-anthropic/README.md                 (new)
```

Additive, non-breaking, minor version bump when released.
