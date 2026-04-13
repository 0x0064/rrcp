# Changelog

## [Unreleased]

### Added

- `EventDraft` and events gain optional `recipients: string[] | null` for directed routing. Server auto-invokes assistants listed in recipients.
- `parseMentions(text, members)` now returns `{ recipients, spans }`. Feed `recipients` into your draft; use `spans` for local render highlighting. `MentionSpan` and `ParseMentionsResult` types are exported.

### Changed

- `actions.ask(assistantIds, draft)` now collapses into a single `sendMessage` call with recipients set. The return shape still includes `message` but `runs` is `null` — consumers observe run lifecycle through the event stream (`run.started`, `run.completed`) instead of synchronously. If your code depended on the previous `runs` array, migrate to `useThreadActiveRuns(threadId)` for the same data via the event stream.

## 0.1.0-alpha.0

First version.
