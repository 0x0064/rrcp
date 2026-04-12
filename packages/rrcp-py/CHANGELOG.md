# Changelog

## [Unreleased]

### Added

- Streaming primitive: `HandlerSend.message_stream()` and `HandlerSend.reasoning_stream()` async context managers, with ephemeral `stream:start` / `stream:delta` / `stream:end` Socket.IO broadcast channels. Deltas are not persisted; the final `MessageEvent` / `ReasoningEvent` is appended to the store on clean stream exit. On exception or cancellation, `stream:end` carries an error and no final event is published. See `docs/plans/2026-04-12-streaming-design.md`.
- `Broadcaster` protocol gains `broadcast_stream_start`, `broadcast_stream_delta`, `broadcast_stream_end`. Implemented by `SocketIOBroadcaster` and `RecordingBroadcaster`.
- `HandlerContext.query_event(events=...)` — optional pre-fetched events list. Consumers that already call `ctx.events()` for history building can pass the same list into `query_event()` to avoid a second round-trip to the store. Backwards compatible; omitting the parameter keeps the existing store-fetch behavior.
- `HandlerContext.update_thread(patch)` — handler-side thread mutation. Writes the patch to the store, publishes a `thread.tenant_changed` event if tenant changed, and broadcasts the updated thread via `publish_thread_updated`. `ctx.thread` is refreshed in place so subsequent reads reflect the update. Wired through `RunExecutor` via a new `publish_thread_updated` constructor parameter; `ThreadServer` passes it automatically. No authorize check — handlers are trusted server-side code.

## 0.1.0a1

- Add `HandlerContext.query_event()` — returns the message event that
  triggered the current run by walking thread history backwards and
  matching on `run.triggered_by`. Race-safe replacement for the
  naive `events[-1]` pattern in multi-user threads. Forward-compatible
  with a future `recipients` field on events.

## 0.1.0a0

First version.
