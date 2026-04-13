# Streaming example

A minimal rrcp server that streams a Claude reply into a thread using the `message_stream()` primitive.

## What this shows

- One assistant registered with `@thread_server.assistant("claude")`
- Handler reads thread history via `ctx.events()` and maps it to Anthropic's message shape
- Handler opens a `send.message_stream()` async context manager
- Each text chunk from `anthropic.messages.stream` is pushed via `stream.append()`
- On clean exit, the final `MessageEvent` is persisted and broadcast on the `event` channel
- On exception or run cancellation, `stream:end` carries an error and nothing is persisted

No deltas are stored. Late joiners of the thread see exactly one `MessageEvent` with the full reply.

## Run it

### 1. Start Postgres

From the `rrcp-py` package root:

```bash
docker compose -f ../../docker-compose.test.yml up -d
```

### 2. Export your Anthropic key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Install and run

```bash
cd packages/rrcp-py/examples/stream
uv sync
uv run python server.py
```

The server listens on `http://localhost:8000`. REST endpoints are mounted under `/acp`, Socket.IO under `/acp/ws`.

The example depends on the local `rrcp` package via `[tool.uv.sources]` pointing at `../..`, so you always get the in-tree version — no need for a PyPI release.

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
