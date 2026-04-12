# Changelog

## 0.1.0a1

- Add `HandlerContext.query_event()` — returns the message event that
  triggered the current run by walking thread history backwards and
  matching on `run.triggered_by`. Race-safe replacement for the
  naive `events[-1]` pattern in multi-user threads. Forward-compatible
  with a future `recipients` field on events.

## 0.1.0a0

First version.
