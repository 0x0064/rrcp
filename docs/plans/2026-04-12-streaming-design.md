# Streaming Primitive Design

**Date:** 2026-04-12
**Status:** Design approved, pending implementation
**Scope:** `rrcp-py` (reference), `rrcp-react` (client), `rrcp-ts` (scaffold parity)

## Motivation

RRCP ships four primitives — identities, threads, events, runs — and deliberately excludes streaming from the core protocol. The philosophy has been: "consumers can build it themselves on top of the event broadcast."

In practice, every AI chat consumer needs streaming, and every one of them would reinvent the same mechanism. When every consumer builds the same thing, that's a signal the protocol is missing an abstraction.

This document specifies a streaming primitive that:

- Stays consistent with RRCP's "communication-first, business-agnostic" philosophy
- Adds minimal surface area to the wire and handler API
- Does not bloat the event log or replay behavior
- Composes cleanly with existing run lifecycle and event semantics

## Design principles

1. **Streaming is transport, not storage.** Deltas are ephemeral broadcast frames. The append-only event log remains the single source of truth for *what was said*, never *how it was delivered*.
2. **Streams live inside runs.** A stream is always bound to a run and to a target event id. There is no such thing as a free-floating stream or a user-initiated stream.
3. **The final event is atomic.** Either a streamable event completes and is persisted in full, or it does not exist. No partial events, no truncation markers.
4. **The handler API hides lifecycle mechanics.** Handlers express intent ("I'm about to stream a message"), the executor handles the start/delta/end choreography.

## Semantic model

### What can be streamed

Only content-producing, single-text-body events are streamable:

- `MessageEvent` (when `content` is a single `TextPart`)
- `ReasoningEvent`

Atomic events are **never** streamed:

- `ToolCallEvent`, `ToolResultEvent` — arrive complete
- `thread.*`, `run.*` — lifecycle markers
- `MessageEvent` with non-text parts (image, audio, document, form) — handler yields them atomically

A handler that needs to send an image alongside a streamed text reply emits two separate events: one streamed `MessageEvent` for the text, one atomic `MessageEvent` for the image.

### Streams are nested inside runs

A run can contain zero, one, or many streams interleaved with atomic events:

```
run.started
  stream.start   (reasoning,  event_id=evt_r1)
  stream.delta   "Let me think..."
  stream.delta   " about this."
  stream.end     (evt_r1)
  ReasoningEvent (evt_r1) — persisted, broadcast on "event" channel

  ToolCallEvent  (evt_t1)   — atomic
  ToolResultEvent(evt_t2)   — atomic

  stream.start   (message,  event_id=evt_m1)
  stream.delta   "Based on the"
  stream.delta   " search results..."
  stream.end     (evt_m1)
  MessageEvent   (evt_m1) — persisted, broadcast on "event" channel
run.completed
```

Every `stream:start` carries the `run_id` it belongs to. Run cancellation tears down any open streams (see Error handling below).

### Deltas are ephemeral

Deltas are broadcast live to connected clients and then discarded. They are not persisted, not returned by `GET /threads/{id}/events`, and not replayed by `thread:join` with a `since` cursor.

**The store only ever sees the final event.** A 50,000-token message is one row in Postgres and one replay event — the thousands of deltas exist only for clients watching live.

**A client that joins after a stream completes** sees the final `MessageEvent` or `ReasoningEvent` as if streaming never happened. Same final state, no divergence.

**A client that joins mid-stream** misses the deltas it was not present for, but will receive the final event on the `"event"` channel once the stream closes. The UX tradeoff: no partial catch-up of in-flight generation. This is intentional — partial catch-up would require persisting or buffering deltas, which violates principle 1.

### No user-initiated streaming

User messages (via `POST /messages` or `message:send`) are always atomic. Users cannot stream their own messages to other thread members. Rationale:

- User input is already complete in the text box by the time `send()` is called — there's nothing to stream.
- "Live typing" is a separate UX feature (typing indicators) that does not require the streaming primitive.
- Making streams work outside runs would fork the wire semantics and the authorization paths.

Consumers that want live-typing indicators can build them as custom transport concerns without touching the streaming primitive.

## Wire protocol

Streams ride three dedicated Socket.IO broadcast channels, separate from the existing `"event"` channel. Each is scoped to the thread room (`"thread:{thread_id}"`) just like `"event"`.

### `stream:start`

Signals the start of a stream targeting a specific event id.

```json
{
  "event_id": "evt_m1",
  "run_id": "run_abc",
  "thread_id": "th_xyz",
  "target_type": "message" | "reasoning",
  "author": { "id": "...", "name": "...", "role": "assistant", "metadata": {} }
}
```

The client uses this to create a placeholder event locally with the given `event_id` and render a streaming indicator. The placeholder's author, run association, and target type are all known upfront — no inference from subsequent deltas.

### `stream:delta`

Appends text to the placeholder identified by `event_id`.

```json
{
  "event_id": "evt_m1",
  "thread_id": "th_xyz",
  "text": " search results..."
}
```

Delta semantics are **append-only raw text**. There is no part indexing, no replace-at-offset, no structural editing. The client concatenates `text` onto whatever it has accumulated so far for `event_id`.

### `stream:end`

Closes the stream for `event_id`. After `stream:end`, no further `stream:delta` frames will arrive for that id.

```json
{
  "event_id": "evt_m1",
  "thread_id": "th_xyz",
  "error": { "code": "handler_error", "message": "..." }   // optional
}
```

On clean completion, `error` is absent and the final event is broadcast on the `"event"` channel immediately after `stream:end`. The client replaces its placeholder with the persisted event.

On failure or cancellation, `error` is present and **no final event is broadcast**. The client drops the placeholder.

### Ordering guarantees

The broadcaster enforces these ordering invariants per run:

1. `stream:start` for a given `event_id` precedes any `stream:delta` for that id.
2. `stream:end` for a given `event_id` follows all `stream:delta` frames for that id and is sent exactly once.
3. When a stream ends cleanly, the corresponding `"event"` broadcast for the persisted event follows `stream:end` (not the other way around).
4. Any terminal run event (`run.completed`, `run.failed`, `run.cancelled`) is broadcast **after** all open streams for that run have been closed via `stream:end`.

Invariant 4 is the key guarantee for clients: "if I receive `run.failed` for run X, I can trust that every stream belonging to run X has already been terminated." No orphaned placeholders.

### Channel separation rationale

Streams are transport; events are state. Keeping them on separate Socket.IO channels means:

- The Zustand `addEvent` reducer stays single-purpose — it never has to branch on "is this real or ephemeral?"
- Stream handlers in the client can be added, removed, or swapped without touching event handling.
- Future transport concerns (presence, typing indicators, read receipts) get their own channels following the same pattern. The channel surface scales with distinct concerns, not with activity.

## Handler API

Handlers express streaming intent via an async context manager on `send`:

```python
@server.assistant("my_assistant")
async def handler(ctx: HandlerContext, send: HandlerSend):
    # Atomic events still use yield
    yield send.tool_call(name="search", arguments={"q": "..."})
    yield send.tool_result(tool_id="...", result=[...])

    # Streams use a context manager
    async with send.message_stream() as stream:
        async for token in llm.stream(messages):
            await stream.append(token)
    # On context exit: stream.end is emitted, final MessageEvent is broadcast

    # Multiple streams per run are fine
    async with send.reasoning_stream() as stream:
        await stream.append("Summarizing findings...")
```

### Why a context manager

The context manager is the only shape that guarantees `stream:end` fires on every exit path:

- **Normal completion** — `__aexit__` with no exception emits `stream:end` (no error) and broadcasts the final event.
- **Handler exception** — `__aexit__` receives the exception, emits `stream:end` with `error={code: "handler_error", ...}`, does not broadcast a final event, then re-raises so the executor marks the run as failed.
- **Run cancellation** — `asyncio.CancelledError` propagates through the context manager. `__aexit__` emits `stream:end` with `error={code: "cancelled", ...}`, does not broadcast a final event, then re-raises so the executor marks the run as cancelled.

Explicit `start()`/`delta()`/`finish()` methods cannot provide this guarantee without duplicating exception handling at every call site.

### `send.message_stream()` and `send.reasoning_stream()`

Both return an async context manager that yields a `Stream` object with a single async method:

```python
class Stream:
    event_id: str   # allocated at open, available to the handler for logging

    async def append(self, text: str) -> None:
        """Broadcast a stream:delta frame with the given text."""
```

`append` is `async` because it pushes to the broadcaster. This is different from `yield send.message(...)`, which is synchronous from the handler's POV. Handlers learn "yield for atomic, await for streaming." The API asymmetry is a small cost for the exception-safety guarantee.

Optional parameters on the stream constructors mirror the atomic event helpers:

```python
send.message_stream(metadata: dict = ...)
send.reasoning_stream(metadata: dict = ...)
```

Metadata is attached to the eventual persisted event, not to individual deltas.

### Interleaving with atomic events

A handler can freely interleave atomic yields and streamed blocks. The executor drains atomic yields through the existing path (persist + broadcast on `"event"`) and streamed blocks through the stream path. Order of emission is preserved.

### What the handler never touches

Handlers do not construct stream frames, do not allocate event ids manually, do not call start/end methods, and do not know which Socket.IO channels exist. The primitive is the context manager; everything else is executor responsibility.

## Error handling

All three failure modes emit `stream:end` with an `error` payload and skip the final event broadcast:

| Mode | `stream:end.error.code` | Final event? | Run outcome |
|---|---|---|---|
| Handler raises | `handler_error` | No | `run.failed` |
| Run cancelled mid-stream | `cancelled` | No | `run.cancelled` |
| Run times out mid-stream | `timeout` | No | `run.failed` (code `timeout`) |

The client drops the placeholder on any `stream:end` with an error. It never has to reason about "was a partial message saved?" — the answer is always no.

If a consumer wants to preserve partial generations for its own UX (e.g., offer the user a "keep what we got" option on cancellation), it buffers deltas locally. The protocol does not do this.

## What the protocol does not do

These are deliberate exclusions, consistent with RRCP's decision rule ("could the consumer build this themselves?"):

- **No partial event persistence.** A stream either completes and persists in full, or nothing is stored.
- **No multi-part content streaming.** Deltas are raw text append only. A handler that needs to stream into a multi-part message structure is out of scope — yield atomic events instead.
- **No user-initiated streaming.** Users cannot stream their own messages.
- **No server-side delta coalescing.** If a handler yields 10,000 single-token deltas, 10,000 frames go on the wire. Consumers that want batching buffer tokens in the handler before calling `append()`.
- **No mid-stream replay for late joiners.** A client that connects during generation receives only the deltas that arrive after it joined, plus the final event. No catch-up buffer.
- **No progress metadata on streams.** No token counts, no estimated completion, no heartbeats. Consumers that want these ship them as `metadata` on the final event or as custom transport.

Any of these can be added later as thin layers on top of the primitive if a real consumer hits the problem. None of them belong in the first cut.

## Impact on existing code

### `rrcp-py` (server reference)

- **New:** `protocol/stream.py` — Pydantic models for `StreamStartFrame`, `StreamDeltaFrame`, `StreamEndFrame`. These are wire types, not persisted types. Not part of the `Event` union.
- **New:** `handler/send.py` — add `message_stream()` and `reasoning_stream()` methods returning async context managers.
- **New:** `handler/stream.py` — `Stream` class implementing `append()`, `__aenter__`/`__aexit__`.
- **Changed:** `handler/executor.py` — ensure that on run termination, any open streams on the current `HandlerSend` are closed with the appropriate error before emitting the terminal run event. Exception paths in `_drive` wrap the handler coroutine so that cancellation and timeout propagate through the stream context manager's `__aexit__`.
- **Changed:** `broadcast/protocol.py` — extend the broadcaster interface with `broadcast_stream_start`, `broadcast_stream_delta`, `broadcast_stream_end` methods.
- **Changed:** `broadcast/socketio.py` — implement the three new broadcast methods as emits on `"stream:start"`, `"stream:delta"`, `"stream:end"` to the thread room.
- **Unchanged:** `store/` — no schema changes, no new store methods. The event log is untouched.
- **Unchanged:** REST endpoints — streaming is Socket.IO only.

### `rrcp-react` (client)

- **New:** three Socket.IO subscriptions in `provider/ThreadProvider.tsx` for `stream:start`, `stream:delta`, `stream:end`.
- **New:** Zustand store slice for placeholder events keyed by `event_id`. Separate from the persisted `events` slice.
- **New:** a `useThreadStream(threadId)` hook (or equivalent) exposing in-flight streams for rendering.
- **Changed:** the `"event"` handler remains single-purpose (addEvent), but when a persisted event arrives whose `event_id` matches an active placeholder, the placeholder is removed in the same transaction.

### `rrcp-ts` (Node server scaffold)

Mirror the Python design once the reference implementation stabilizes. No code yet, but the wire protocol and handler API shape are pinned by this document.

## Breaking change status

**Additive, non-breaking.** No existing event types change. No existing Socket.IO channels change. No existing REST endpoints change. Handlers that don't use `message_stream()` / `reasoning_stream()` continue to work unchanged. Clients that don't subscribe to the new `stream:*` channels continue to receive only persisted events and behave exactly as they do today.

Version bump is minor, not major. Lockstep rule still requires all three packages to release together once the feature lands.

## Open questions for implementation

Deferred to the implementation slice, not blocking on this design:

1. **Delta buffering strategy in `Stream.append()`.** Push each call to the broadcaster immediately, or accumulate within an `asyncio` task and flush on a timer? First cut: immediate, measure later.
2. **Max concurrent streams per run.** Is there a reason to cap this? First cut: no cap, handlers discipline themselves.
3. **React placeholder rendering contract.** Does the placeholder expose a `content: string` that the UI renders directly, or does it expose a typed `TextPart` so existing message renderers work unchanged? First cut: typed `TextPart` so the rendering path is shared with persisted messages.

These will be resolved in `docs/plans/YYYY-MM-DD-streaming-impl.md` when implementation starts.
