# Recipients Primitive Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `recipients: list[str] | None` routing field to RRCP events so the server can auto-invoke assistants based on message targeting, activate the `HandlerContext.query_event()` forward-compat filter, and collapse `sendMessage + invoke` into one wire call.

**Architecture:** One optional field on `_EventBase` and `EventDraft`. Server normalizes on write (strip author, dedup, validate member), auto-invokes each registered assistant listed in `recipients` via the existing `authorize` callback, and broadcasts the event with the field intact. Handler-side helpers (`query_event`, `events(relevant_to_me=True)`) filter events by recipients structurally. Mentions stay client-side: `parseMentions(text, members)` returns `{ recipients, spans }` where `recipients` goes on the wire and `spans` are local render hints only. Purely additive and backwards-compatible.

**Tech Stack:** Python 3.11+, Pydantic v2, `python-socketio`, FastAPI. Style: ruff (line length 120, double quotes), mypy strict, no comments, Pydantic frozen models with `ConfigDict(extra="forbid", frozen=True, populate_by_name=True)`. Typescript side: Biome (2-space, single quotes, no semicolons), TS strict.

**Reference design:** `docs/plans/2026-04-12-recipients-design.md`

---

## Conventions (read before starting any task)

- **No comments in any file this plan touches.** Names and structure carry the meaning. (rrcp-py has a zero-comments rule per `packages/rrcp-py/CLAUDE.md`; rrcp-react allows minimal JSDoc where the intent is non-obvious, match existing style.)
- **Match existing patterns exactly.** Study `protocol/event.py`, `store/postgres/store.py`, `store/postgres/schema.sql`, `server/thread_server.py`, and `server/rest/messages.py` before writing new code.
- **Tests only where a behavior guarantee is non-obvious.** One happy path + one failure mode per feature. Reuse the existing `clean_db` pg fixture for integration tests; reuse the `_FakeStore` pattern from `tests/handler/test_query_event.py` for pure unit tests.
- **Commit after each task.** Use `feat:` for new capability, `chore:` for re-exports and plumbing, `test:` for tests, `docs:` for README/CHANGELOG.
- **Working directory:** `packages/rrcp-py/` for Python tasks, `packages/rrcp-react/` for TypeScript tasks. Run checks from there with `uv run poe dev` / `npm run dev`.
- **No release tags.** This plan commits to `main` but does not create release tags. Tagging + publishing happens separately after all phases land.
- **Design-doc-first.** For any ambiguity — normalization order, authorize interaction, member validation — reread `2026-04-12-recipients-design.md` before guessing. The design doc is the source of truth.

---

## Phase 1 — protocol and storage (rrcp-py)

### Task 1: Add `recipients` field to `_EventBase` and `EventDraft`

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/protocol/event.py`

**Step 1: Add the field to `_EventBase`**

Locate the `_EventBase` class. Add `recipients: list[str] | None = None` below the existing fields, before the subclass definitions:

```python
class _EventBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str
    thread_id: str
    run_id: str | None = None
    author: Identity
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    client_id: str | None = None
    recipients: list[str] | None = None
```

**Step 2: Add the field to `EventDraft`**

Same file, `EventDraft` model:

```python
class EventDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str
    content: list[ContentPart] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    recipients: list[str] | None = None
```

**Step 3: Typecheck & lint**

```bash
cd packages/rrcp-py
uv run poe check
uv run poe typecheck
```

Expected: clean.

**Step 4: Commit**

```bash
git add packages/rrcp-py/src/rrcp/protocol/event.py
git commit -m "feat(rrcp-py): add recipients field to _EventBase and EventDraft"
```

---

### Task 2: Add `_normalize_recipients` helper

**Files:**
- Create: `packages/rrcp-py/src/rrcp/protocol/recipients.py`

**Step 1: Write the normalization function**

```python
from __future__ import annotations


def normalize_recipients(
    recipients: list[str] | None,
    *,
    author_id: str,
) -> list[str] | None:
    if not recipients:
        return None
    seen: set[str] = set()
    out: list[str] = []
    for rid in recipients:
        if rid == author_id:
            continue
        if rid in seen:
            continue
        seen.add(rid)
        out.append(rid)
    return out or None
```

Semantics from the design doc: empty list → `None`, author id stripped, order-preserving dedup, all-empty-after-stripping → `None`.

**Step 2: Write unit tests**

Create `packages/rrcp-py/tests/protocol/test_recipients.py`:

```python
from __future__ import annotations

from rrcp.protocol.recipients import normalize_recipients


def test_none_stays_none() -> None:
    assert normalize_recipients(None, author_id="u_alice") is None


def test_empty_list_becomes_none() -> None:
    assert normalize_recipients([], author_id="u_alice") is None


def test_author_stripped() -> None:
    assert normalize_recipients(["u_alice", "assistant"], author_id="u_alice") == ["assistant"]


def test_only_author_becomes_none() -> None:
    assert normalize_recipients(["u_alice"], author_id="u_alice") is None


def test_dedup_preserves_order() -> None:
    assert normalize_recipients(["a", "b", "a", "c", "b"], author_id="x") == ["a", "b", "c"]
```

**Step 3: Run tests**

```bash
cd packages/rrcp-py
uv run pytest tests/protocol/test_recipients.py -v
```

Expected: 5 passed.

**Step 4: Commit**

```bash
git add packages/rrcp-py/src/rrcp/protocol/recipients.py packages/rrcp-py/tests/protocol/test_recipients.py
git commit -m "feat(rrcp-py): add recipients normalization helper"
```

---

### Task 3: Postgres migration — add `recipients` column

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/store/postgres/schema.sql`

**Step 1: Add column to the `events` table**

Locate the `CREATE TABLE IF NOT EXISTS events (...)` block. Add `recipients JSONB NULL` below the existing columns. Then add a standalone `ALTER TABLE` so it applies idempotently to pre-existing databases:

```sql
ALTER TABLE events ADD COLUMN IF NOT EXISTS recipients JSONB;
```

Place the `ALTER` immediately after the `CREATE TABLE` block. The existing `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... IF NOT EXISTS` pattern is already used elsewhere in the schema.

**Step 2: Verify schema applies clean**

Stand up a fresh test database via the docker-compose fixture:

```bash
cd packages/rrcp-py
docker compose -f docker-compose.test.yml up -d
uv run pytest tests/store/test_postgres_events.py -v
```

Expected: existing tests still pass (no recipients behavior yet, but the column exists and doesn't break inserts).

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/store/postgres/schema.sql
git commit -m "feat(rrcp-py): add recipients column to events table"
```

---

### Task 4: Serialize + hydrate `recipients` in `PostgresThreadStore`

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/store/postgres/store.py`

**Step 1: Update `append_event`**

Locate `append_event`. Find the INSERT SQL and the parameter list. Add `recipients` to both.

```python
async def append_event(self, event: Event) -> Event:
    row = await self._pool.fetchrow(
        """
        INSERT INTO events (
            id, thread_id, run_id, author, created_at, metadata,
            client_id, recipients, type, payload
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING *
        """,
        event.id,
        event.thread_id,
        event.run_id,
        json.dumps(event.author.model_dump(mode="json")),
        event.created_at,
        json.dumps(event.metadata),
        event.client_id,
        json.dumps(event.recipients) if event.recipients is not None else None,
        event.type,
        json.dumps(_event_payload(event)),
    )
    return _row_to_event(row)
```

Check the actual existing signature and parameter order — match it exactly. If the existing column list uses a different order, follow that order.

**Step 2: Update `_row_to_event` (or equivalent hydration helper)**

Find the helper that constructs `Event` subclasses from a Postgres row. Add `recipients` to the constructor kwargs:

```python
def _row_to_event(row: Record) -> Event:
    ...
    return event_cls(
        id=row["id"],
        thread_id=row["thread_id"],
        run_id=row["run_id"],
        author=Identity(...),
        created_at=row["created_at"],
        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        client_id=row["client_id"],
        recipients=json.loads(row["recipients"]) if row["recipients"] else None,
        ...
    )
```

**Step 3: Verify round-trip**

Run the existing event store tests plus a new ad-hoc test case:

```bash
cd packages/rrcp-py
uv run pytest tests/store/test_postgres_events.py -v
```

Expected: all green. If any pre-existing test broke, you introduced a regression — do not proceed.

**Step 4: Commit**

```bash
git add packages/rrcp-py/src/rrcp/store/postgres/store.py
git commit -m "feat(rrcp-py): persist and hydrate recipients in PostgresThreadStore"
```

---

### Task 5: Round-trip test for `recipients` through the store

**Files:**
- Modify: `packages/rrcp-py/tests/store/test_postgres_events.py`

**Step 1: Add a test case**

```python
async def test_recipients_round_trip(clean_db: asyncpg.Pool) -> None:
    store = PostgresThreadStore(pool=clean_db)

    thread = await store.create_thread(_make_thread())
    await store.add_member(thread.id, _user("u_alice"), role="owner")
    await store.add_member(thread.id, _assistant("ops-assistant"), role="assistant")

    event = _make_message_event(
        thread_id=thread.id,
        author=_user("u_alice"),
        text="directed message",
        recipients=["ops-assistant"],
    )
    appended = await store.append_event(event)
    assert appended.recipients == ["ops-assistant"]

    page = await store.list_events(thread.id)
    stored = page.items[-1]
    assert isinstance(stored, MessageEvent)
    assert stored.recipients == ["ops-assistant"]


async def test_recipients_none_round_trip(clean_db: asyncpg.Pool) -> None:
    store = PostgresThreadStore(pool=clean_db)

    thread = await store.create_thread(_make_thread())
    await store.add_member(thread.id, _user("u_alice"), role="owner")

    event = _make_message_event(
        thread_id=thread.id,
        author=_user("u_alice"),
        text="broadcast message",
        recipients=None,
    )
    appended = await store.append_event(event)
    assert appended.recipients is None

    page = await store.list_events(thread.id)
    stored = page.items[-1]
    assert stored.recipients is None
```

Reuse the existing `_make_thread`, `_user`, `_make_message_event` test helpers from the same file. If they don't exist, factor them from adjacent tests.

**Step 2: Run**

```bash
cd packages/rrcp-py
uv run pytest tests/store/test_postgres_events.py::test_recipients_round_trip tests/store/test_postgres_events.py::test_recipients_none_round_trip -v
```

Expected: 2 passed.

**Step 3: Commit**

```bash
git add packages/rrcp-py/tests/store/test_postgres_events.py
git commit -m "test(rrcp-py): round-trip recipients through PostgresThreadStore"
```

---

## Phase 2 — server routing (rrcp-py)

### Task 6: Add `ThreadServer.auto_invoke_recipients` option

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/server/thread_server.py`

**Step 1: Add constructor parameter**

Locate `ThreadServer.__init__`. Add `auto_invoke_recipients: bool = True` to the keyword-only parameters (after `authorize`, before `on_analytics`):

```python
def __init__(
    self,
    *,
    store: ThreadStore,
    authenticate: AuthenticateCallback,
    authorize: AuthorizeCallback | None = None,
    auto_invoke_recipients: bool = True,
    on_analytics: OnAnalyticsCallback | None = None,
    run_timeout_seconds: int = 120,
    replay_cap: int = 500,
    broadcaster: Broadcaster | None = None,
    namespace_keys: list[str] | None = None,
) -> None:
    ...
    self.auto_invoke_recipients = auto_invoke_recipients
    ...
```

**Step 2: Typecheck**

```bash
cd packages/rrcp-py
uv run poe typecheck
```

Expected: clean.

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/server/thread_server.py
git commit -m "feat(rrcp-py): add auto_invoke_recipients option to ThreadServer"
```

---

### Task 7: Validate recipients against thread membership in REST write path

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/server/rest/messages.py`

**Step 1: Read existing `POST /messages` handler**

Find the handler function (likely `send_message` or similar). Note the flow: it resolves identity, checks authorize, constructs the event, calls `server.store.append_event` (or `server.publish_event`).

**Step 2: Add recipient normalization + validation**

After the authorize check, before event construction, validate recipients:

```python
from rrcp.protocol.recipients import normalize_recipients

recipients = normalize_recipients(
    body.recipients,
    author_id=identity.id,
)
if recipients is not None:
    members = await server.store.list_members(thread_id)
    member_ids = {m.identity_id for m in members}
    unknown = [rid for rid in recipients if rid not in member_ids]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"recipient_not_member: {unknown[0]}",
        )
```

Pass `recipients=recipients` when constructing the `MessageEvent`.

**Step 3: Verify existing tests still pass**

```bash
cd packages/rrcp-py
uv run pytest tests/server/test_rest_messages.py -v
```

Expected: all green. Existing tests send drafts without `recipients` → normalization returns `None` → no behavior change.

**Step 4: Commit**

```bash
git add packages/rrcp-py/src/rrcp/server/rest/messages.py
git commit -m "feat(rrcp-py): normalize and validate recipients on POST /messages"
```

---

### Task 8: Auto-invoke registered assistants listed in recipients

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/server/rest/messages.py`

**Step 1: After publishing the event, trigger invocations**

Immediately after the `publish_event` / `append_event` call, iterate `recipients` and fire `executor.execute` for each one that is a registered assistant:

```python
if recipients and server.auto_invoke_recipients:
    for assistant_id in recipients:
        handler = server.get_handler(assistant_id)
        if handler is None:
            continue
        if not await server.check_authorize(identity, thread_id, "assistant.invoke"):
            continue
        members_list = await server.store.list_members(thread_id)
        assistant_member = next(
            (m for m in members_list if m.identity_id == assistant_id),
            None,
        )
        if assistant_member is None or not isinstance(assistant_member.identity, AssistantIdentity):
            continue
        await server.executor.execute(
            thread=thread,
            assistant=assistant_member.identity,
            triggered_by=identity,
            handler=handler,
        )
```

Notes:
- Skip unknown assistant ids (recipient could be a user — no handler).
- Skip on authorize failure silently (same policy as explicit invoke, design doc §Authorization).
- Skip if the assistant isn't a member (defensive — the earlier `recipient_not_member` check should have caught this, but members could be removed between check and execute).

**Step 2: Run existing REST tests**

```bash
cd packages/rrcp-py
uv run pytest tests/server/test_rest_messages.py tests/server/test_rest_invoke.py -v
```

Expected: green. Existing tests don't set recipients → auto-invoke is a no-op → no behavior change.

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/server/rest/messages.py
git commit -m "feat(rrcp-py): auto-invoke assistants listed in recipients"
```

---

### Task 9: Integration test — message with assistant in recipients triggers handler

**Files:**
- Create: `packages/rrcp-py/tests/server/test_recipients_auto_invoke.py`

**Step 1: Write a focused integration test**

```python
from __future__ import annotations

from typing import Any

import asyncpg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from rrcp.protocol.content import TextPart
from rrcp.protocol.identity import Identity, UserIdentity
from rrcp.server.auth import HandshakeData
from rrcp.server.thread_server import ThreadServer
from rrcp.store.postgres.store import PostgresThreadStore


async def test_assistant_in_recipients_triggers_handler(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresThreadStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    server = ThreadServer(store=store, authenticate=auth, run_timeout_seconds=5)
    ran: list[str] = []

    @server.assistant("specialist")
    async def specialist(ctx: Any, send: Any) -> Any:
        ran.append(ctx.run.id)
        yield send.message(content=[TextPart(text="specialist answered")])

    app = FastAPI()
    app.state.thread_server = server
    app.include_router(server.router, prefix="/acp")
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    thread = (await client.post("/acp/threads", json={"tenant": {"org": "A"}})).json()
    thread_id = thread["id"]
    await client.post(
        f"/acp/threads/{thread_id}/members",
        json={"identity": {"role": "assistant", "id": "specialist", "name": "S", "metadata": {}}},
    )

    response = await client.post(
        f"/acp/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "hello specialist"}],
            "recipients": ["specialist"],
        },
    )
    assert response.status_code == 201

    runs = [t for t in server.executor._tasks.values()]
    for task in runs:
        try:
            await task
        except Exception:
            pass

    assert len(ran) == 1
```

**Step 2: Run**

```bash
cd packages/rrcp-py
uv run pytest tests/server/test_recipients_auto_invoke.py::test_assistant_in_recipients_triggers_handler -v
```

Expected: passed.

**Step 3: Commit**

```bash
git add packages/rrcp-py/tests/server/test_recipients_auto_invoke.py
git commit -m "test(rrcp-py): assistant in recipients auto-invokes handler"
```

---

### Task 10: Integration test — broadcast (no recipients) does NOT trigger

**Files:**
- Modify: `packages/rrcp-py/tests/server/test_recipients_auto_invoke.py`

**Step 1: Add the negative case**

```python
async def test_broadcast_does_not_auto_invoke(
    clean_db: asyncpg.Pool,
) -> None:
    # Same setup as the positive test — copy or extract a fixture.
    ...

    response = await client.post(
        f"/acp/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "team chat, no target"}],
        },
    )
    assert response.status_code == 201

    await asyncio.sleep(0.1)  # give the executor a moment if anything fires
    assert ran == []
```

The absence of `recipients` in the request body means the server posts the message as broadcast. No handler should run.

**Step 2: Run**

```bash
cd packages/rrcp-py
uv run pytest tests/server/test_recipients_auto_invoke.py -v
```

Expected: both tests pass.

**Step 3: Commit**

```bash
git add packages/rrcp-py/tests/server/test_recipients_auto_invoke.py
git commit -m "test(rrcp-py): broadcast messages do not auto-invoke"
```

---

### Task 11: Integration test — `recipient_not_member` returns 400

**Files:**
- Modify: `packages/rrcp-py/tests/server/test_recipients_auto_invoke.py`

**Step 1: Add validation test**

```python
async def test_recipient_not_member_returns_400(
    clean_db: asyncpg.Pool,
) -> None:
    # Same setup — thread exists, only alice is a member.
    ...

    response = await client.post(
        f"/acp/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "ghost"}],
            "recipients": ["ghost-id"],
        },
    )
    assert response.status_code == 400
    assert "recipient_not_member" in response.json()["detail"]
```

**Step 2: Run**

```bash
cd packages/rrcp-py
uv run pytest tests/server/test_recipients_auto_invoke.py -v
```

Expected: all three tests pass.

**Step 3: Commit**

```bash
git add packages/rrcp-py/tests/server/test_recipients_auto_invoke.py
git commit -m "test(rrcp-py): recipient_not_member returns 400"
```

---

### Task 12: Integration test — `auto_invoke_recipients=False` disables auto-invoke

**Files:**
- Modify: `packages/rrcp-py/tests/server/test_recipients_auto_invoke.py`

**Step 1: Add opt-out test**

```python
async def test_auto_invoke_disabled_preserves_current_behavior(
    clean_db: asyncpg.Pool,
) -> None:
    store = PostgresThreadStore(pool=clean_db)
    alice = UserIdentity(id="u_alice", name="Alice", metadata={"tenant": {"org": "A"}})

    async def auth(_h: HandshakeData) -> Identity:
        return alice

    server = ThreadServer(
        store=store,
        authenticate=auth,
        run_timeout_seconds=5,
        auto_invoke_recipients=False,
    )
    ran: list[str] = []

    @server.assistant("specialist")
    async def specialist(ctx: Any, send: Any) -> Any:
        ran.append(ctx.run.id)
        yield send.message(content=[TextPart(text="specialist answered")])

    # Setup client, thread, members identically to the positive test.
    ...

    await client.post(
        f"/acp/threads/{thread_id}/messages",
        json={
            "client_id": "c_1",
            "content": [{"type": "text", "text": "hello"}],
            "recipients": ["specialist"],
        },
    )

    await asyncio.sleep(0.1)
    assert ran == []  # auto_invoke disabled → nothing ran
```

**Step 2: Run**

```bash
cd packages/rrcp-py
uv run pytest tests/server/test_recipients_auto_invoke.py -v
```

Expected: all four tests pass.

**Step 3: Commit**

```bash
git add packages/rrcp-py/tests/server/test_recipients_auto_invoke.py
git commit -m "test(rrcp-py): auto_invoke_recipients=False disables auto-invoke"
```

---

### Task 13: Apply the same logic to the Socket.IO write path

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/socketio/server.py`

**Step 1: Mirror the REST write flow in `on_message_send`**

Find the Socket.IO handler for `message:send` (or equivalent event). It already does authorize checks and calls the store. Add the same three steps:

1. `normalize_recipients(data.get("recipients"), author_id=identity.id)`
2. Validate each id is a member, reject with `{"error": {"code": "recipient_not_member", ...}}` if not.
3. After publishing, loop recipients and fire `executor.execute` for each registered assistant (same pattern as the REST handler).

Extract the logic into a shared helper at the server layer if it simplifies things — but don't over-factor. Duplicating the 15-line block in both code paths is acceptable.

**Step 2: Run Socket.IO integration tests**

```bash
cd packages/rrcp-py
uv run pytest tests/socketio/ -v
```

Expected: existing tests pass.

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/socketio/server.py
git commit -m "feat(rrcp-py): wire recipients auto-invoke on Socket.IO message:send"
```

---

## Phase 3 — handler API upgrade (rrcp-py)

### Task 14: Activate the `query_event` recipients filter

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/handler/context.py`

**Step 1: Replace `getattr` with direct access**

Find the forward-compat scaffolding in `query_event`:

```python
recipients = getattr(evt, "recipients", None)
if recipients and my_id not in recipients:
    continue
```

Replace with:

```python
if evt.recipients and my_id not in evt.recipients:
    continue
```

The field now exists on `_EventBase` (Task 1), so direct access is safe.

**Step 2: Update the docstring**

The current docstring says `"When the event protocol gains a recipients field in a future release..."`. Rewrite to reflect the current state:

```python
async def query_event(self, events: list[Event] | None = None) -> MessageEvent | None:
    """Return the message event that most likely triggered this run.

    Walks thread history backwards from the most recent event and returns
    the first MessageEvent authored by ``self.run.triggered_by`` where
    ``recipients`` is either empty (broadcast) or contains
    ``self.run.assistant.id``. This is the canonical way to answer "what
    did the user just say to me" from inside a handler.

    :param events: Optional pre-fetched events list. If provided, the
        method walks this list instead of calling the store. Use this
        when the handler already needs event history for other purposes
        (history building, command routing) to avoid a redundant
        round-trip.

    Returns None if no matching message is found within the lookback
    window (``_QUERY_LOOKBACK``). Typical cause: the run was invoked
    without a preceding directed message, or the triggering message
    scrolled out behind a large volume of intervening events.
    """
```

**Step 3: Verify existing tests still pass**

```bash
cd packages/rrcp-py
uv run pytest tests/handler/test_query_event.py -v
```

Expected: all 5 tests pass. The pre-Phase-1 tests used mocked events with no `recipients` field, which after Task 1 defaults to `None`, which the filter treats as broadcast — same behavior as before.

**Step 4: Commit**

```bash
git add packages/rrcp-py/src/rrcp/handler/context.py
git commit -m "feat(rrcp-py): activate query_event recipients filter"
```

---

### Task 15: Add `events(relevant_to_me=True)` parameter

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/handler/context.py`

**Step 1: Update `events` method signature**

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
        items = [e for e in items if not e.recipients or my_id in e.recipients]
    return items
```

**Step 2: Write unit test**

Add to `packages/rrcp-py/tests/handler/test_query_event.py` (reuses the `_FakeStore` pattern):

```python
async def test_events_relevant_to_me_filters_by_recipients() -> None:
    events: list[Event] = [
        _message(id="e1", author_id="u_alice", author_role="user", text="broadcast", minutes_ago=5),
        _message_with_recipients(id="e2", author_id="u_alice", recipients=["specialist"], text="for specialist", minutes_ago=4),
        _message_with_recipients(id="e3", author_id="u_alice", recipients=["other-assistant"], text="for other", minutes_ago=3),
    ]
    ctx = _build_ctx(events, triggerer_id="u_alice", assistant_id="specialist")

    all_events = await ctx.events(limit=10)
    assert len(all_events) == 3

    relevant = await ctx.events(limit=10, relevant_to_me=True)
    relevant_ids = [e.id for e in relevant]
    assert "e1" in relevant_ids   # broadcast included
    assert "e2" in relevant_ids   # addressed to specialist included
    assert "e3" not in relevant_ids  # addressed to other-assistant excluded
```

Add a `_message_with_recipients` helper next to the existing `_message` helper.

**Step 3: Run**

```bash
cd packages/rrcp-py
uv run pytest tests/handler/test_query_event.py -v
```

Expected: all 6 tests pass (5 existing + 1 new).

**Step 4: Commit**

```bash
git add packages/rrcp-py/src/rrcp/handler/context.py packages/rrcp-py/tests/handler/test_query_event.py
git commit -m "feat(rrcp-py): add HandlerContext.events(relevant_to_me=) filter"
```

---

### Task 16: Add optional `recipients` kwarg to `HandlerSend` helpers

**Files:**
- Modify: `packages/rrcp-py/src/rrcp/handler/send.py`

**Step 1: Add the parameter to each factory**

For `HandlerSend.message`, `HandlerSend.reasoning`, `HandlerSend.tool_call`, `HandlerSend.tool_result`, add an optional keyword-only parameter:

```python
def message(
    self,
    *,
    content: list[ContentPart],
    metadata: dict[str, Any] | None = None,
    recipients: list[str] | None = None,
) -> MessageEvent:
    return MessageEvent(
        id=_event_id(),
        thread_id=self.thread_id,
        run_id=self.run_id,
        author=self.author,
        created_at=_now(),
        metadata=metadata or {},
        recipients=recipients,
        content=content,
    )
```

Apply the same pattern to the other three factories.

**Step 2: Verify existing tests still pass**

```bash
cd packages/rrcp-py
uv run pytest tests/handler/test_send.py -v
```

Expected: 4 tests pass (no call site uses the new parameter yet, default `None` preserves behavior).

**Step 3: Commit**

```bash
git add packages/rrcp-py/src/rrcp/handler/send.py
git commit -m "feat(rrcp-py): add recipients kwarg to HandlerSend helpers"
```

---

### Task 17: Update CHANGELOG `[Unreleased]` section

**Files:**
- Modify: `packages/rrcp-py/CHANGELOG.md`

**Step 1: Add entries under `## [Unreleased] / ### Added`**

```markdown
- `EventDraft` and `_EventBase` gain `recipients: list[str] | None` — a routing hint indicating which thread members a message is addressed to. `None` or empty list means broadcast (unchanged default).
- `ThreadServer` gains `auto_invoke_recipients: bool = True` option. When `True`, posted messages with registered assistant ids in `recipients` auto-invoke each of those assistants via the existing `authorize` callback. `sendMessage` collapses into `sendMessage + invoke` behavior without a separate client call.
- REST `POST /threads/{id}/messages` and Socket.IO `message:send` validate recipients against current thread membership, returning `400 recipient_not_member` on unknown ids. Author id is stripped from recipients on write; empty lists are normalized to `None`.
- `HandlerContext.query_event()` now filters by `recipients` structurally — skips messages from the triggerer that are addressed to a different assistant, in multi-assistant threads. (The forward-compat scaffolding from `0.1.0a1` is now active.)
- `HandlerContext.events(relevant_to_me: bool = False)` — when `True`, returns only broadcast events and events addressed to `ctx.run.assistant.id`.
- `HandlerSend.message()`, `reasoning()`, `tool_call()`, `tool_result()` gain an optional `recipients` keyword argument so handlers can address their output events to specific thread members.
```

**Step 2: Commit**

```bash
git add packages/rrcp-py/CHANGELOG.md
git commit -m "docs(rrcp-py): record recipients protocol additions in [Unreleased]"
```

---

## Phase 4 — React client (rrcp-react)

### Task 18: Add `recipients` to TypeScript `EventDraft` and event types

**Files:**
- Modify: `packages/rrcp-react/src/protocol/types.ts` (or wherever `EventDraft` and the event type union live — find via grep).

**Step 1: Extend the types**

```ts
export type EventDraft = {
  clientId: string
  content?: ContentPart[]
  metadata?: Record<string, unknown>
  recipients?: string[] | null
}

export type EventBase = {
  id: string
  threadId: string
  runId?: string
  author: Identity
  createdAt: string
  metadata: Record<string, unknown>
  clientId?: string
  recipients: string[] | null
}
```

Every existing event subtype inherits from `EventBase`, so adding it there propagates to `MessageEvent`, `ReasoningEvent`, etc.

**Step 2: Update the wire parser / mapper**

Find the `snake_case → camelCase` mapper for incoming events (typically in `protocol/mappers.ts` or similar). Add:

```ts
recipients: raw.recipients ?? null,
```

And the outgoing draft mapper:

```ts
recipients: draft.recipients ?? null,
```

**Step 3: Typecheck**

```bash
cd packages/rrcp-react
npm run typecheck
```

Expected: clean.

**Step 4: Commit**

```bash
git add packages/rrcp-react/src/protocol/types.ts packages/rrcp-react/src/protocol/mappers.ts
git commit -m "feat(rrcp-react): add recipients to EventDraft and EventBase types"
```

---

### Task 19: Upgrade `parseMentions` return shape

**Files:**
- Modify: `packages/rrcp-react/src/utils/parseMentions.ts` (or wherever it lives — grep for `parseMentions`).

**Step 1: Define `MentionSpan` type**

```ts
export type MentionSpan = {
  identityId: string
  text: string
  start: number
  length: number
}
```

**Step 2: Change the function signature**

Before:

```ts
export function parseMentions(text: string, members: Identity[]): MentionSpan[]
```

After:

```ts
export function parseMentions(
  text: string,
  members: Identity[],
): { recipients: string[]; spans: MentionSpan[] } {
  const spans: MentionSpan[] = []
  const recipients: string[] = []
  const seen = new Set<string>()

  const regex = /@([\w-]+)/g
  let match: RegExpExecArray | null
  while ((match = regex.exec(text)) !== null) {
    const token = match[1]
    const member = members.find(
      (m) => m.name === token || m.id === token,
    )
    if (!member) continue
    spans.push({
      identityId: member.id,
      text: token,
      start: match.index,
      length: match[0].length,
    })
    if (!seen.has(member.id)) {
      seen.add(member.id)
      recipients.push(member.id)
    }
  }

  return { recipients, spans }
}
```

Keep the regex narrow: `@[\w-]+`. Token matching is exact against `member.name` or `member.id`.

**Step 3: Update existing call sites**

Grep the `rrcp-react` package for `parseMentions(` and update destructuring at each call site. Likely few sites today — the utility is exported but rarely referenced internally.

```bash
cd packages/rrcp-react
grep -r "parseMentions(" src/ tests/
```

For each hit:

```ts
// before
const spans = parseMentions(text, members)
// after
const { spans } = parseMentions(text, members)
```

**Step 4: Export `MentionSpan` from main barrel**

Add to `src/main.ts`:

```ts
export { parseMentions, type MentionSpan } from './utils/parseMentions'
```

**Step 5: Run tests + typecheck**

```bash
cd packages/rrcp-react
npm run dev
```

Expected: lint + typecheck + tests pass.

**Step 6: Commit**

```bash
git add packages/rrcp-react/src/utils/parseMentions.ts packages/rrcp-react/src/main.ts packages/rrcp-react/tests/utils/
git commit -m "feat(rrcp-react): parseMentions returns { recipients, spans }"
```

---

### Task 20: Add `parseMentions` unit tests

**Files:**
- Create (or extend): `packages/rrcp-react/tests/utils/parseMentions.test.ts`

**Step 1: Write tests covering 4 cases**

```ts
import { describe, it, expect } from 'vitest'
import { parseMentions } from '../../src/utils/parseMentions'
import type { Identity } from '../../src/protocol/types'

const alice: Identity = { role: 'user', id: 'u_alice', name: 'alice', metadata: {} }
const bob: Identity = { role: 'user', id: 'u_bob', name: 'bob', metadata: {} }
const assistant: Identity = { role: 'assistant', id: 'ops-assistant', name: 'ops-assistant', metadata: {} }

describe('parseMentions', () => {
  it('returns no mentions for plain text', () => {
    const result = parseMentions('just a regular message', [alice, bob])
    expect(result.recipients).toEqual([])
    expect(result.spans).toEqual([])
  })

  it('matches a single @-token against member name', () => {
    const result = parseMentions('hey @alice look at this', [alice, bob])
    expect(result.recipients).toEqual(['u_alice'])
    expect(result.spans).toHaveLength(1)
    expect(result.spans[0]).toMatchObject({
      identityId: 'u_alice',
      text: 'alice',
      start: 4,
      length: 6,
    })
  })

  it('dedupes multiple mentions of the same identity', () => {
    const result = parseMentions('@alice and @alice again', [alice, bob])
    expect(result.recipients).toEqual(['u_alice'])
    expect(result.spans).toHaveLength(2)
  })

  it('skips tokens that do not match any member', () => {
    const result = parseMentions('@ghost not here, but @alice is', [alice, bob])
    expect(result.recipients).toEqual(['u_alice'])
    expect(result.spans).toHaveLength(1)
  })

  it('matches an assistant identity by id-shaped name', () => {
    const result = parseMentions('@ops-assistant please check', [alice, assistant])
    expect(result.recipients).toEqual(['ops-assistant'])
  })
})
```

**Step 2: Run**

```bash
cd packages/rrcp-react
npm run test -- parseMentions
```

Expected: 5 tests pass.

**Step 3: Commit**

```bash
git add packages/rrcp-react/tests/utils/parseMentions.test.ts
git commit -m "test(rrcp-react): cover parseMentions { recipients, spans } shape"
```

---

### Task 21: `actions.ask` internally sets `recipients`

**Files:**
- Modify: `packages/rrcp-react/src/hooks/useThreadActions.ts` (verify path — the file containing `useThreadActions`).

**Step 1: Find the current `ask` implementation**

```bash
cd packages/rrcp-react
grep -n "ask" src/hooks/useThreadActions.ts
```

It likely does:

```ts
ask: async (assistantIds, draft) => {
  const message = await client.sendMessage(threadId, draft)
  const { runs } = await client.invoke(threadId, { assistantIds })
  return { message, runs }
}
```

**Step 2: Collapse into one wire call**

```ts
ask: async (assistantIds, draft) => {
  const mergedRecipients = Array.from(
    new Set([...(draft.recipients ?? []), ...assistantIds]),
  )
  const message = await client.sendMessage(threadId, {
    ...draft,
    recipients: mergedRecipients,
  })
  return { message, runs: null, error: undefined }
}
```

The server auto-invokes via recipients, so no separate `invoke` call is needed. `runs: null` is a deliberate signal to callers that the run set is not returned synchronously — it will arrive via the normal event stream (`run.started`, `run.completed`).

If callers today depend on the `runs` array, flag the break and update them. If none do (likely, since Phase 3 hasn't introduced stream-based run observation patterns), the change is backwards compatible at the type level.

**Step 3: Run tests**

```bash
cd packages/rrcp-react
npm run test
```

Expected: existing `useThreadActions` tests pass. If any asserts on `runs` being an array, update them.

**Step 4: Commit**

```bash
git add packages/rrcp-react/src/hooks/useThreadActions.ts packages/rrcp-react/tests/
git commit -m "feat(rrcp-react): actions.ask sets recipients and skips explicit invoke"
```

---

### Task 22: Update `rrcp-react` CHANGELOG

**Files:**
- Modify: `packages/rrcp-react/CHANGELOG.md`

**Step 1: Add entries**

```markdown
## [Unreleased]

### Added

- `EventDraft` and events gain optional `recipients: string[] | null` for directed routing. Server auto-invokes assistants listed in recipients.
- `parseMentions(text, members)` now returns `{ recipients, spans }`. Feed `recipients` into your draft; use `spans` for local render highlighting. `MentionSpan` type is exported.

### Changed

- `actions.ask(assistantIds, draft)` now collapses into a single `sendMessage` call with recipients set. The return shape still includes `message` but `runs` is `null` — consumers observe run lifecycle through the event stream (`run.started`, `run.completed`) instead of synchronously. If your code depended on the previous `runs` array, migrate to `useThreadActiveRuns(threadId)` for the same data via the event stream.
```

**Step 2: Commit**

```bash
git add packages/rrcp-react/CHANGELOG.md
git commit -m "docs(rrcp-react): record recipients additions in [Unreleased]"
```

---

## Phase 5 — Node client (rrcp-ts)

### Task 23: Scaffold parity placeholder

**Files:**
- Modify: `packages/rrcp-ts/CHANGELOG.md` (if it exists)
- Optionally: `packages/rrcp-ts/src/main.ts` placeholder

**Status:** `rrcp-ts` is currently a scaffold with no real wire implementation. Full parity with the recipients field and `parseMentions` ships when `rrcp-ts` implements its REST client.

**Step 1: Record the dependency in the rrcp-ts CHANGELOG or a TODO file**

```markdown
## [Unreleased]

### Pending

- Recipients field and `parseMentions` utility. Blocked on base REST client implementation. See `docs/plans/2026-04-12-recipients-design.md` Phase 5.
```

**Step 2: Commit**

```bash
git add packages/rrcp-ts/CHANGELOG.md
git commit -m "docs(rrcp-ts): note pending recipients parity with scaffold"
```

**Skip** the actual implementation until the scaffold has a base client. This task is a one-line placeholder so nothing falls through the cracks.

---

## Phase 6 — ops-maintenance migration (SEPARATE REPO)

> **Note:** Phase 6 happens in `filterbuy/ops-maintenance-assistant/`, not in this repo. Each task is framed as "do this in that repo." Track it as a companion migration, not as rrcp work.

### Task 24: Frontend — replace `metadata.audience` with `recipients`

**Files (ops-maintenance repo):**
- Modify: `frontend/src/app/(main)/threads/[threadId]/use-thread-chat.ts`
- Modify: `frontend/src/app/(main)/use-home-page.ts`
- Modify: `frontend/src/components/features/resolve-dialog.tsx`

**Step 1: Every send site**

Find every `sendMessage` / `actions.ask` call that currently sets `metadata.audience`. Replace:

```ts
// before
metadata: { audience: "assistant", ... }

// after — assistant audience
recipients: ["ops-assistant"],
metadata: { ... }
```

```ts
// before
metadata: { audience: "user", ... }

// after — team chat (broadcast)
// remove the audience key, omit recipients or set to null
metadata: { ... }
```

Keep the other metadata keys (`command`, `input_type`, `voice_reply`, etc.) — only the `audience` tag goes away.

**Step 2: Wire `parseMentions` into the composer**

In `use-thread-chat.ts` `onSend`, before calling `actions.ask`, run:

```ts
import { parseMentions } from '@0x0064/rrcp-react'

// inside onSend
const members = /* fetch from useThreadMembers(threadId) */
const { recipients: mentionRecipients } = parseMentions(trimmed, members)
const finalRecipients = messageAudience === "assistant"
  ? Array.from(new Set(["ops-assistant", ...mentionRecipients]))
  : mentionRecipients
```

Pass `finalRecipients` into the draft.

**Step 3: Verify typecheck**

```bash
cd frontend
npx tsc --noEmit
```

**Step 4: Commit (in the ops-maintenance repo)**

```bash
git add frontend/src/...
git commit -m "feat: use rrcp recipients instead of metadata.audience for routing"
```

---

### Task 25: Backend — remove audience guard and `_is_assistant_directed`

**Files (ops-maintenance repo):**
- Modify: `backend/src/acp/handler.py`

**Step 1: Remove the audience guard**

Delete:

```python
if metadata.get("audience") == "user":
    logger.info(...)
    return
```

The server no longer invokes the handler for messages that don't list this assistant in `recipients`, so this guard is unreachable.

**Step 2: Replace history filter with `events(relevant_to_me=True)`**

Find the `_events_to_history` call that passes a pre-filtered `assistant_directed` list. Replace:

```python
# before
events = await ctx.events(limit=200)
query_msg = await ctx.query_event(events=events)
...
prior = [e for e in events if e.id != query_msg.id and e.created_at < query_msg.created_at]
history = _events_to_history(prior, ctx.assistant.id)
```

with:

```python
# after
relevant = await ctx.events(limit=200, relevant_to_me=True)
query_msg = await ctx.query_event(events=relevant)
...
prior = [e for e in relevant if e.id != query_msg.id and e.created_at < query_msg.created_at]
history = _events_to_history(prior, ctx.assistant.id)
```

**Step 3: Delete `_is_assistant_directed`**

Now that `events(relevant_to_me=True)` does the filtering at the SDK level, the consumer-side helper is dead code. Delete:

```python
def _is_assistant_directed(event: Event) -> bool:
    ...
```

And the call inside `_events_to_history` that references it. The pair-walk algorithm stays.

**Step 4: Typecheck + lint**

```bash
cd backend
uv run poe check
uv run poe typecheck
```

**Step 5: Commit (in the ops-maintenance repo)**

```bash
git add backend/src/acp/handler.py
git commit -m "refactor: drop metadata.audience workaround, use ctx.events(relevant_to_me=)"
```

---

### Task 26: Verify escalation flow still works end-to-end

**Files (ops-maintenance repo):**
- No code change. Smoke test only.

**Step 1: Start the stack locally**

```bash
cd backend
uv run poe dev  # or however you run the dev server
cd ../frontend
npm run dev
```

**Step 2: Manual flow**

1. Sign in as a technician.
2. Create a thread from the home page.
3. Ask a question → verify the assistant responds.
4. Click "Escalate to Team" → verify the summary message appears and the thread's metadata flips to `visibility: public`.
5. Sign in as a lead in a different browser window → verify the escalated thread appears in the sidebar.
6. Lead sends a message in team mode → verify no assistant response fires (no RAG call in logs).
7. Lead switches to assistant mode → sends a follow-up question → verify the assistant responds.
8. Resolve the thread via the dialog → verify QA extraction + ingestion.

**Step 3: No commit**

This is a smoke test only. If any step fails, fix the underlying code and re-run.

---

## Phases summary

| Phase | Repo | Tasks | Status |
|---|---|---|---|
| 1. Protocol + storage | `rrcp-py` | 1–5 | |
| 2. Server routing | `rrcp-py` | 6–13 | |
| 3. Handler API upgrade | `rrcp-py` | 14–17 | |
| 4. React client | `rrcp-react` | 18–22 | |
| 5. Node client | `rrcp-ts` | 23 (placeholder) | |
| 6. Consumer migration | `ops-maintenance-assistant` | 24–26 | out-of-repo |

**Release groupings** (for later, not in this plan):
- Phases 1–3 → `rrcp-py 0.2.0a0` (one minor bump, one release tag)
- Phase 4 → `rrcp-react 0.2.0-alpha.0` in lockstep
- Phase 5 → `rrcp-ts` catches up when the scaffold has a base client
- Phase 6 → consumer release cycle

**No release tags in this plan.** This plan commits the code. Tagging + publishing is a separate step decided by the humans after smoke-testing.

---

## Post-plan checklist

After Task 22 lands (end of Phase 4):

- [ ] `uv run poe dev` green in `packages/rrcp-py/`
- [ ] `npm run dev` green in `packages/rrcp-react/`
- [ ] CHANGELOG `[Unreleased]` sections populated in both rrcp-py and rrcp-react
- [ ] No `TODO` / `FIXME` introduced by this plan
- [ ] `ops-maintenance-assistant` compiles against the local editable rrcp checkout (sanity check via `uv sync` + `npx tsc --noEmit`)

After Task 26 lands (end of Phase 6):

- [ ] `metadata.audience` has zero occurrences under `filterbuy/ops-maintenance-assistant/`
- [ ] `_is_assistant_directed` has zero occurrences
- [ ] Full escalation smoke test passes
- [ ] Design doc moved to `Status: Implemented`
