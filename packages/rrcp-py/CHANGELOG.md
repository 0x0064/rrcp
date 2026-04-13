# Changelog

## [Unreleased]

### BREAKING

- `AuthorizeCallback` signature now takes an optional `target_id: str | None = None` keyword argument. Honors per-assistant authorization for the `assistant.invoke` action: when auto-invoke fires for `recipients=[A, B]`, each target is checked independently. Migration: add `target_id: str | None = None` to your callback's keyword parameters. Callbacks that don't care about the target can ignore it.
- `ThreadServer.publish_event` is now the single write chokepoint for recipients normalization, membership validation, and auto-invoke. Handler-yielded events (`send.message(recipients=...)`, `send.reasoning(recipients=...)`, etc.) now go through the same author-strip and membership check as REST and Socket.IO write paths. A handler that yields an event with recipients referencing a non-member will fail its run with `handler_error` / `recipient_not_member`. A handler that lists its own id in recipients has it stripped on write. Previously these rules only applied to REST and Socket.IO.
- Assistant-to-assistant auto-invoke is now wired end-to-end. A handler yielding a `MessageEvent` with `recipients=[other_assistant_id]` triggers an in-thread run of `other_assistant_id` via the same auto-invoke path user-initiated sends go through. Loop protection: (1) chain depth capped at 8 via in-memory `RunExecutor._chain_depths` tracking, (2) active-run dedup via `find_active_run` breaks A→B→A cycles within a single run, (3) author-strip prevents self-invoke. In-memory depth tracking is per-process; cross-process deployments should rely on consumer handlers to self-police.

### Added

- Streaming primitive: `HandlerSend.message_stream()` and `HandlerSend.reasoning_stream()` async context managers, with ephemeral `stream:start` / `stream:delta` / `stream:end` Socket.IO broadcast channels. Deltas are not persisted; the final `MessageEvent` / `ReasoningEvent` is appended to the store on clean stream exit. On exception or cancellation, `stream:end` carries an error and no final event is published. See `docs/plans/2026-04-12-streaming-design.md`.
- `Broadcaster` protocol gains `broadcast_stream_start`, `broadcast_stream_delta`, `broadcast_stream_end`. Implemented by `SocketIOBroadcaster` and `RecordingBroadcaster`.
- `HandlerContext.query_event(events=...)` — optional pre-fetched events list. Consumers that already call `ctx.events()` for history building can pass the same list into `query_event()` to avoid a second round-trip to the store. Backwards compatible; omitting the parameter keeps the existing store-fetch behavior.
- `HandlerContext.update_thread(patch)` — handler-side thread mutation. Writes the patch to the store, publishes a `thread.tenant_changed` event if tenant changed, and broadcasts the updated thread via `publish_thread_updated`. `ctx.thread` is refreshed in place so subsequent reads reflect the update. Wired through `RunExecutor` via a new `publish_thread_updated` constructor parameter; `ThreadServer` passes it automatically. No authorize check — handlers are trusted server-side code.
- `EventDraft` and `_EventBase` gain `recipients: list[str] | None` — a routing hint indicating which thread members a message is addressed to. `None` or empty list means broadcast (unchanged default).
- `ThreadServer` gains `auto_invoke_recipients: bool = True` option. When `True`, posted messages with registered assistant ids in `recipients` auto-invoke each of those assistants via the existing `authorize` callback. `sendMessage` collapses into `sendMessage + invoke` behavior without a separate client call.
- REST `POST /threads/{id}/messages` and Socket.IO `message:send` validate recipients against current thread membership, returning `400 recipient_not_member` on unknown ids. Author id is stripped from recipients on write; empty lists are normalized to `None`.
- `HandlerContext.query_event()` now filters by `recipients` structurally — skips messages from the triggerer that are addressed to a different assistant, in multi-assistant threads. (The forward-compat scaffolding from `0.1.0a1` is now active.)
- `HandlerContext.events(relevant_to_me: bool = False)` — when `True`, returns only broadcast events and events addressed to `ctx.run.assistant.id`.
- `HandlerSend.message()`, `reasoning()`, `tool_call()`, `tool_result()` gain an optional `recipients` keyword argument so handlers can address their output events to specific thread members.

## 0.1.0a1

- Add `HandlerContext.query_event()` — returns the message event that
  triggered the current run by walking thread history backwards and
  matching on `run.triggered_by`. Race-safe replacement for the
  naive `events[-1]` pattern in multi-user threads. Forward-compatible
  with a future `recipients` field on events.

## 0.1.0a0

First version.
