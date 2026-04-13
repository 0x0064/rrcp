# Recipients Design

**Date:** 2026-04-12
**Status:** Design, pending implementation
**Scope:** `rrcp-py` (reference), `rrcp-react` (client), `rrcp-ts` (scaffold parity)

## Motivation

RRCP's core positioning is *multi-user, multi-assistant threads* — conversations where several humans and one or more AI assistants share a single event log. Every consumer who tries to build this today immediately hits the same wall: **how do I express "this message is for the assistant" vs "this message is for my teammate," and how do I make the server act on that distinction?**

Today the answer is "stuff it in `metadata` and parse it yourself on both sides." We've done that in `ops-maintenance-assistant` with `metadata.audience = "user" | "assistant"`. It works for a first consumer, but it has three problems:

1. **Every consumer reinvents the same primitive.** Audience, target, directedAt — different names for the same concept. When every consumer builds the same thing, it belongs in the SDK.
2. **The server can't help.** Because the routing information lives in consumer-defined metadata, the server has no structural way to auto-invoke assistants or filter events by relevance. Every consumer has to call `sendMessage` + `invoke` in two steps (today's `actions.ask`), or walk the handler's `ctx.events()` and filter by metadata.audience themselves.
3. **The handler-side query helper has to guess.** `HandlerContext.query_event()` currently walks events looking for "the triggerer's most recent message" but can't tell if that message was actually directed at *this* assistant or at a teammate. It ships forward-compat scaffolding for a `recipients` field for exactly this reason.

This document specifies `recipients` as a first-class, additive, non-breaking event field that closes the three gaps above. It is the smallest possible addition to the RRCP core: one new optional attribute on existing events, one new server behavior, one activation of existing handler-side scaffolding.

**Mentions (`@alice`) are intentionally out of scope for the protocol.** See the "Mentions belong to the client" section below — this is a deliberate rejection of a wire-level mentions primitive after an honest audit.

## Design principles

1. **Recipients is routing, not permissions.** `recipients: list[str]` tells the server *who should react*. It does not restrict who sees the message. Every member of the thread still receives every event.
2. **Broadcast is the default.** `recipients = None` means "everyone in the thread." Existing events with no recipients field stay valid; existing consumer behavior stays unchanged.
3. **The server auto-invokes targeted assistants.** If a posted `MessageEvent` lists a registered assistant in `recipients`, the server invokes that assistant's handler automatically. This is the point of the primitive — `sendMessage` becomes sufficient, no separate `invoke` call needed.
4. **Handler-side lookups upgrade automatically.** `query_event()` already has forward-compat scaffolding for `recipients`. When this design ships, that scaffolding becomes active — every consumer using `query_event()` gets the filter for free.
5. **The protocol adds one field, not a subsystem.** No new event type, no new primitive, no new collection. One optional attribute on existing events.

## Semantic model

### What `recipients` means

```
recipients: None           → broadcast to the thread (default; existing behavior)
recipients: []             → broadcast to the thread (normalized to None on write)
recipients: ["id_a"]       → directed at identity id_a
recipients: ["id_a", "b"]  → directed at both id_a and b
```

Who can be listed:

- Any member of the thread — user or assistant identities.
- The author is never a recipient. On write, the server strips the author's id from `recipients` and treats the remainder as the effective target list.

### What the server does when a message is posted

The server inspects `recipients` at write time:

1. **Normalize.** Empty list becomes `None`. Author id removed. Deduplicated.
2. **Non-member ids rejected.** If any id is not a current member of the thread, the write fails with `recipient_not_member`. Catches typos early and avoids ghost targeting.
3. **Auto-invoke each recipient who is a registered assistant.** For every assistant id in the final recipients list that has a handler registered with `ThreadServer.register_assistant`, the server creates a run and fires the handler. Non-assistant recipients (other users) get no server-side action — they're a routing hint for clients.
4. **Broadcast.** The event is appended and broadcast over Socket.IO as normal. Clients see the `recipients` field on the incoming event and render/filter however they please.

If `recipients = None`, no auto-invoke happens. Broadcast messages do not trigger assistants. This is how team chat works: you want to say something to your teammates without burning RAG on it.

### `actions.ask` becomes sugar

Today:

```ts
await client.sendMessage(threadId, draft)
await client.invoke(threadId, { assistantIds: ['ops-assistant'] })
```

And the higher-level `actions.ask(assistantIds, draft)` bundles the two into one public API call (two wire calls).

After this ships:

```ts
await client.sendMessage(threadId, { ...draft, recipients: ['ops-assistant'] })
// Server auto-invokes ops-assistant because it's in recipients.
```

`actions.ask(assistantIds, draft)` keeps its signature and still works — internally it now sets `draft.recipients = [...assistantIds, ...(draft.recipients ?? [])]` and calls `sendMessage`. No separate `invoke` call. Backwards compatible on the public API, one wire call instead of two.

### Mentions belong to the client

An earlier draft of this design proposed a parallel `mentions: list[Mention]` field on events and a `Mention` protocol model with offset data. **That has been cut.**

The question to ask is: *what does the server need to do with mention data?*

- Routing? No — that's `recipients`.
- Auto-invoke? No — that's `recipients`.
- Authorization? No — the authorize callback doesn't read mention data.
- Validation? No — invalid offsets would be a client bug, and the server can't meaningfully catch them.
- Persistence? Only for rendering consistency across clients. But clients that use the SDK's canonical parser stay consistent without the wire carrying the parsed result.

The only real argument for a wire-level mentions field was "clients should not have to agree on parser implementation." That argument collapses when the SDK ships a canonical `parseMentions` in each client package (`rrcp-react`, `rrcp-ts`) with identical regex, identical offset semantics, and identical member resolution. Every SDK-using client gets the same spans from the same text + member list. The wire does not need to carry the result.

So `parseMentions` ships as a **client-side pure function** that returns:

```ts
// rrcp-react / rrcp-ts — client type, never serialized over the wire
type MentionSpan = {
  identityId: string
  text: string           // the typed form ("alice", "ops-assistant")
  start: number          // UTF-16 code unit offset in the message text
  length: number         // UTF-16 length of the @-span including the @
}

function parseMentions(
  text: string,
  members: Identity[],
): {
  recipients: string[]   // identity ids to put in the event's recipients field
  spans: MentionSpan[]   // local render hints for highlighting
}
```

The consumer flow:

```ts
// Send path
const { recipients, spans } = parseMentions(text, members)
await client.sendMessage(threadId, {
  clientId: crypto.randomUUID(),
  content: [{ type: 'text', text }],
  recipients,            // ← wire, drives routing + auto-invoke
})
// spans are used for the local composer preview; never sent.

// Receive path
const event = events[i]
const { spans } = parseMentions(extractText(event), members)
// Render the event's text with the spans highlighted.
// Same input (text + members), same parser, same spans — cross-client
// consistency without the wire carrying anything extra.
```

Why this works for the 90% case:

- Every modern chat app uses `@token` mentions. The canonical parser handles `@[\w-]+` against the current member list. That's the whole vocabulary.
- Every client that uses the SDK gets the same parser, so render hints don't drift.
- Re-parsing on display is cheap (linear scan); memoization handles scroll perf if it becomes real.
- The edge case of "mention someone in text without routing to them" (`as @alice said yesterday`) is a deliberate non-goal — in 90% of chat UX, `@alice` *means* "I'm addressing alice." Consumers who want the reference-only form can use backticks or a different convention.

What stays in `rrcp-react` / `rrcp-ts`:

- `parseMentions(text, members) → { recipients, spans }` — the canonical parser.
- `MentionSpan` as a **client-only TypeScript interface**, not a protocol Pydantic model and not a wire field.

What does **not** exist in `rrcp-py` or on the wire:

- No `Mention` Pydantic model.
- No `mentions` field on `_EventBase` or `EventDraft`.
- No `mentions` column in the events table.
- No `useMentions(threadId)` hook (it would be a one-liner over the existing `useThreadMembers` hook and `parseMentions` function; not worth a dedicated surface).

### The 90% flow end to end

1. User types `hey @ops-assistant what's the valve spec?` in the composer.
2. Client autocomplete dropdown resolves `@ops-assistant` to identity id `assistant-ops-001` as the user selects it.
3. On send, client calls `parseMentions(text, members)`, gets `{ recipients: ["assistant-ops-001"], spans: [{…}] }`.
4. Client builds the draft with `recipients: ["assistant-ops-001"]` and calls `sendMessage`. **One wire call.**
5. Server writes the event, strips the author from recipients (no-op here — author is a user, not the assistant), verifies `assistant-ops-001` is a member, auto-invokes the registered handler for `assistant-ops-001`, broadcasts the event.
6. Every client in the thread receives the event. Each client runs `parseMentions` locally on the text for render highlighting.
7. The ops-assistant handler runs. Inside, `ctx.query_event()` walks history looking for a message authored by `ctx.run.triggered_by` — and *additionally* filters on `recipients`: the message must either have no recipients (broadcast) or include `ctx.run.assistant.id`. Team-chat messages from the triggerer are structurally skipped.

A team-chat message takes the same wire format but with `recipients = None` (or a list containing only user ids) — no auto-invoke, no handler run, zero RAG cost.

## Wire protocol

### Event schema additions

One additive field on `_EventBase` (everything that inherits it — `MessageEvent`, `ReasoningEvent`, `ToolCallEvent`, `ToolResultEvent`, the thread.* events, and the run.* events):

```python
class _EventBase(BaseModel):
    # ...existing fields
    recipients: list[str] | None = None
```

- Optional, default `None`, normalized to `None` on empty list.
- Why on the base class instead of only `MessageEvent`? Because an assistant-emitted reasoning event may be addressed to a specific participant, and because consumers filtering by "events I should see" want a uniform field location. The cost is one column per event row in Postgres; the column is `NULL` for event types that don't use it.

### `EventDraft` additions

```python
class EventDraft(BaseModel):
    client_id: str
    content: list[ContentPart] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    recipients: list[str] | None = None
```

One new field. Optional. Defaults to broadcast.

### REST wire

`POST /threads/{thread_id}/messages` accepts `recipients` on the request body. The response echoes it back on the created event. No new endpoints.

### Socket.IO wire

No new channels. The existing `"event"` broadcast channel carries events with the new field inline. Clients that don't understand it ignore it.

## Storage

### Postgres schema

One new column on the `events` table:

```sql
ALTER TABLE events
    ADD COLUMN recipients JSONB NULL;
```

- Nullable, default `NULL`.
- No index by default. Consumers that want to query "all events where identity X is in recipients" can add a GIN index themselves; the SDK does not query by this column.
- Migration is purely additive — existing rows get `NULL`, which the read path translates to "broadcast."

### Migration

Additive. No data backfill. Ship the schema change in the same minor version as the field.

## Handler API

### `query_event()` gets its filter activated

Today `HandlerContext.query_event()` already has forward-compat scaffolding:

```python
async def query_event(self, events: list[Event] | None = None) -> MessageEvent | None:
    # ...
    for evt in reversed(events):
        if not isinstance(evt, MessageEvent):
            continue
        if evt.author.id != triggerer_id:
            continue
        # Forward-compatible recipients check: no-op today because
        # the field doesn't exist yet on the event model.
        recipients = getattr(evt, "recipients", None)
        if recipients and my_id not in recipients:
            continue
        return evt
    return None
```

After this ships, `recipients` exists on `MessageEvent` as a real field. The `getattr` becomes direct attribute access and the filter activates:

```python
if evt.recipients and my_id not in evt.recipients:
    continue
```

**Behavior change:** a handler whose assistant id is not in the triggerer's recipients list gets skipped. That's the point — in a multi-assistant thread, you don't want assistant B answering a question addressed to assistant A. Consumers that already use `query_event()` (like ops-maintenance) get this upgrade for free, no code change.

### `ctx.events(relevant_to_me=True)`

New convenience parameter on `HandlerContext.events()`:

```python
async def events(
    self,
    limit: int | None = None,
    *,
    relevant_to_me: bool = False,
) -> list[Event]:
    page = await self._store.list_events(self.thread.id, limit=limit or 100)
    items = page.items
    if relevant_to_me:
        my_id = self.assistant.id
        items = [
            e for e in items
            if not e.recipients or my_id in e.recipients
        ]
    return items
```

Gives handlers a one-liner to get "only events I should care about" without filtering metadata conventions themselves. Returns broadcast events plus events explicitly addressed to this assistant.

### `HandlerSend` recipient kwargs

The `HandlerSend` helpers (`send.message`, `send.reasoning`, `send.tool_call`, `send.tool_result`) already pass `content` and `metadata`. Add an optional `recipients` parameter:

```python
yield send.message(
    content=[TextPart(text="replying directly to alice")],
    recipients=[alice.id],
)
```

Defaults to `None`. An assistant replying to `@alice` can reflect that in the reply event's recipients; a broadcast response uses the default.

## Client API

### `rrcp-react` changes

**`ThreadClient.sendMessage`** — `EventDraft` type gains `recipients`. No new method.

**`parseMentions(text, members)`** — upgraded to return `{ recipients, spans }`:

```ts
export function parseMentions(
  text: string,
  members: Identity[],
): { recipients: string[]; spans: MentionSpan[] }
```

Regex-scans the text for `@[\w-]+` tokens, matches each against the member list by short-name or id, produces `spans` with offsets for local rendering, and adds the matched identity ids to `recipients`. Tokens that don't match any member are not mentions — they stay as plain text in the message.

**`MentionSpan`** — exported TypeScript interface, client-side only, never serialized. Documented in the public types so consumers can type their own render components.

**Existing `parseMentions` helper** in `@0x0064/rrcp-react`'s main export currently returns only spans. This design **upgrades** its return shape to `{ recipients, spans }`. Existing consumers calling it only for render highlighting need to update one destructure. Minor breaking change on the utility; no protocol change.

**Autocomplete UI is out of scope.** The SDK ships the parser and types; consumers build their own `@`-dropdown using whatever component library they want. A typical integration is ~30 lines wrapping `useThreadMembers` and a `<Command>` popover.

### `rrcp-ts` parity

Same `recipients` field on the Node draft. Same `parseMentions` export with identical behavior. Cross-client consistency is the whole point of putting the parser in the SDK.

## Server configuration

### `ThreadServer.auto_invoke_recipients: bool = True`

New constructor option. When `True` (default), a `MessageEvent` posted with registered assistant ids in `recipients` auto-invokes each of those assistants. When `False`, recipients is a pure routing hint and consumers must call `invoke` explicitly (preserving today's behavior exactly).

**Default `True`** because the overwhelming majority of consumers will want it. The whole point of the primitive is to collapse `sendMessage` + `invoke` into one semantic operation.

**Opt-out** because some consumers may want to approve messages before the assistant runs (content moderation, rate limiting, billing checks). Setting `auto_invoke_recipients=False` lets them intercept between write and invoke.

### Authorization

Auto-invoke still goes through `check_authorize(identity, thread_id, "assistant.invoke")`. If the author isn't authorized to invoke a given assistant, the invoke is silently skipped (the message is still written, recipients field is still stored, but no handler runs). The consumer's authorize callback governs exactly like it does for explicit `invoke` calls.

If the author is authorized for assistant A but not B, and both are in recipients, A runs and B does not. Each recipient is checked independently.

### `recipient_not_member` validation

Posting a message with a `recipients` id that is not a current thread member returns `400 recipient_not_member`. Catches typos and stale state before the message lands.

Rationale: allowing ghost recipients silently would create routing ambiguity ("did the client mean to tag them, or was it a bug?") and would force readers to handle unknown ids. Strict validation at write time keeps the invariant that every recipient on a stored event was, at some point, addressable.

Edge case: what if a recipient is removed from the thread *after* the message is written? The stored event still has the removed id in `recipients`. That's correct — the message was legitimately addressed to them at the time, and the event log is append-only history. Handlers and UIs that render events should tolerate stale recipient ids.

## Backwards compatibility

### Wire

- Events with no `recipients` field continue to deserialize as broadcast (`recipients = None`).
- Drafts that don't set `recipients` continue to create broadcast events.
- Existing REST responses gain one nullable field; clients that ignore unknown fields are unaffected.

### Consumer code

- `actions.ask(assistantIds, draft)` keeps the same signature. Internally it now sets `draft.recipients = [...assistantIds]` and relies on auto-invoke. If the consumer passes `draft.recipients` already, the two are merged (dedup).
- `sendMessage(draft)` without recipients → broadcast → no auto-invoke → current behavior.
- `sendMessage(draft)` with recipients containing assistant ids → auto-invoke (new behavior).
- `ThreadServer` constructed without `auto_invoke_recipients` → default `True`. No existing consumer sets `recipients` on drafts today (the field doesn't exist), so the behavior change surfaces only when consumers opt in by setting the field.

### Minor breaking change: `parseMentions` return shape

`rrcp-react`'s existing `parseMentions` helper returns spans only. This design changes it to return `{ recipients, spans }`. Consumers that were calling it for render-highlighting need to update one destructure:

```ts
// before
const spans = parseMentions(text, members)
// after
const { spans } = parseMentions(text, members)
```

This is a breaking change on a utility function, not on a protocol surface. Release notes + an update line in the migration doc cover it. Ships in the same minor version as the protocol change for clean grouping.

### Existing `ops-maintenance-assistant`

Currently uses `metadata.audience = "user" | "assistant"` as a workaround. Migration:

- `metadata.audience = "assistant"` → `recipients = ["ops-assistant"]`. Backend handler's audience guard becomes redundant (the message won't reach the handler if `recipients` doesn't include the assistant — the server won't invoke).
- `metadata.audience = "user"` → `recipients = null` (broadcast). No auto-invoke, no handler run.
- Frontend `parseMentions` produces the `recipients` list automatically when the user types `@ops-assistant`.
- Drop the backend audience guard entirely; drop the `_is_assistant_directed` history filter — events the handler shouldn't see are already filtered structurally by `query_event` and `events(relevant_to_me=True)`.

Net code reduction on the consumer side. This is the benefit of moving the primitive into the SDK.

## What this does NOT add to rrcp core

The primitive list in `CLAUDE.md` today says: **identities, threads, events, runs.** After this ships:

- **Identities** — unchanged
- **Threads** — unchanged
- **Events** — gains one new optional field (`recipients`). Same model, same lifecycle, same semantics. The event is not gaining a new "mentions" sub-system — it's gaining a routing hint.
- **Runs** — unchanged (still the unit of handler execution; auto-invoke just creates them implicitly from recipients)

**No new primitive.** **No new event type.** **No new protocol model for mentions.** One new field on one existing primitive, one new server behavior implicit in how that field is interpreted on write.

The minimal surgical addition that lets the SDK do what every consumer currently has to do by hand.

## Implementation phases

Ordered for clean rollout. Each phase is independently shippable and testable.

### Phase 1 — protocol and storage (rrcp-py)

1. Add `recipients: list[str] | None` to `_EventBase` and `EventDraft`.
2. Postgres migration: one nullable JSONB column on `events`.
3. Update `PostgresThreadStore.append_event` and `list_events` to serialize and hydrate the field.
4. Update wire validators in `rrcp/protocol/event.py::parse_event` to accept and pass through.
5. Unit tests: round-trip event with `recipients`, without, with empty list (normalized to None), with author id (stripped).

### Phase 2 — server routing (rrcp-py)

1. `ThreadServer.__init__` gains `auto_invoke_recipients: bool = True`.
2. `publish_event` (or the `POST /messages` handler) inspects `recipients`, runs `check_authorize` per assistant recipient, fires `executor.execute` for each authorized assistant. Skip with log for unauthorized.
3. `recipient_not_member` validation in the REST and Socket.IO write paths.
4. Integration test: message with assistant in recipients triggers handler; message with user in recipients does not; message with no recipients does not.
5. Integration test: `auto_invoke_recipients=False` preserves current behavior (no auto-invoke, consumers must call `invoke` explicitly).
6. Integration test: `recipient_not_member` returns 400 for a ghost id.

### Phase 3 — handler API upgrade (rrcp-py)

1. Activate the real recipients filter in `HandlerContext.query_event` — replace `getattr(evt, "recipients", None)` with direct access `evt.recipients`.
2. Add `events(relevant_to_me: bool = False)` parameter on `HandlerContext`.
3. Optional `recipients` kwarg on `HandlerSend.message`, `reasoning`, `tool_call`, `tool_result`.
4. Unit tests: `query_event` with recipients filter (broadcast, self-addressed, other-assistant-addressed); `events(relevant_to_me=True)` includes broadcast + self-addressed only.

### Phase 4 — React client (rrcp-react)

1. `EventDraft` and `Event` TypeScript types gain `recipients`.
2. Upgrade `parseMentions` to return `{ recipients, spans }`. Export `MentionSpan` TypeScript interface.
3. `ThreadClient.sendMessage` passes the new field through without transformation.
4. `actions.ask(assistantIds, draft)` internally sets `draft.recipients = assistantIds` and skips the separate `invoke` wire call.

### Phase 5 — Node client (rrcp-ts)

Scaffold parity — same type addition, same `parseMentions` export. Can ship in the same release or lag one version behind depending on the scaffold's readiness.

### Phase 6 — ops-maintenance migration

1. Frontend: replace `metadata.audience = "assistant"` with `recipients = ["ops-assistant"]` in all send sites. Drop the audience metadata entirely from drafts.
2. Backend handler: remove the `metadata.audience == "user"` guard; remove `_is_assistant_directed`; remove `_events_to_history`'s audience-based filter and replace with `events(relevant_to_me=True)`.
3. Frontend: wire `parseMentions` and add a minimal `@`-dropdown in `ChatInput`.
4. Verify the escalation flow still works — escalate is a command (metadata.command), not an audience.

Each phase produces a backwards-compatible SDK release. Phases 1–3 can ship together as `rrcp-py 0.2.0a0`. Phase 4 ships as `rrcp-react 0.2.0-alpha.0` in lockstep. Phase 5 catches up when rrcp-ts is past scaffold. Phase 6 is a consumer update inside ops-maintenance-assistant's own release cycle.

## Open questions

### 1. Should `recipients` validate that at least one id is a registered assistant for auto-invoke?

**No.** `recipients = ["u_alice"]` is a valid routing hint ("this message is for Alice to read") even if it doesn't trigger a handler. Requiring at least one assistant would overload the field with "triggers stuff" semantics; keeping it pure routing metadata is cleaner.

### 2. Should assistant-to-assistant mentions auto-invoke?

**Yes.** If assistant A yields a message with `recipients=["assistant-b"]`, the server auto-invokes assistant B. This is already covered by Phase 2's logic — the author is A, but A's identity is the `triggered_by` for B's run. This is the "multi-assistant collaboration" use case and it comes for free.

### 3. Should the server coalesce duplicate runs triggered by the same message?

**Yes.** If a message lists assistant A in `recipients` twice (client bug), the server deduplicates before invoking. Covered by the Phase 2 normalization step.

### 4. Does `@here` or `@everyone` exist?

**No.** Broadcast is already the default (empty recipients). The `@here`/`@everyone` affordance is a UI concern — clients can render a shortcut that resolves to "all current members," but the wire representation is just `recipients = [member_id_1, member_id_2, ...]` or `None` for "broadcast to current and future members." No special tokens in the protocol.

### 5. Should `recipients` restrict who can see the event?

**No.** Visibility is unchanged: every thread member sees every event regardless of `recipients`. `recipients` is routing, not access control. Consumers that need private subchannels should create a separate thread with a restricted member list — that's what threads are for.

The existing `authorize` callback remains the sole access-control point.

### 6. What if a consumer wants mention-as-reference without routing (`as @alice said yesterday`)?

**Not supported in the 90% case.** The parser treats every `@token` as a mention, and every mention adds to `recipients`. Consumers that want to reference a name without routing can use backticks (`` `alice` ``), a different convention, or disable the parser for specific text spans.

If demand materializes later, a protocol-level distinction could be added (e.g. a `recipients_override: list[str]` draft field that takes precedence over parser output), but not as part of this design. Keeping the mental model single-layered — "every `@` targets" — is the 90% win.

## References

- `docs/plans/2026-04-12-streaming-design.md` — companion design for the streaming primitive, same "move ubiquitous patterns into the SDK" philosophy.
- Existing `HandlerContext.query_event` forward-compat scaffolding in `rrcp/handler/context.py:119-125`.
- Consumer workaround in `filterbuy/ops-maintenance-assistant/backend/src/acp/handler.py` — `metadata.audience` guard and `_is_assistant_directed` history filter. Both become dead code after Phase 6.
