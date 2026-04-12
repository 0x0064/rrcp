# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Philosophy (READ FIRST)

rrcp is a **Communication Protocol** for assistant-driven threads where multiple
users and multiple assistants can interact. It is NOT an AI framework, NOT an LLM
wrapper, and NOT a chat application — it is the wire and the storage underneath them.

### Core principles

1. **Business agnostic.** The SDK never inspects credentials, never decides who can
   do what, and never owns user/assistant/tool data shapes beyond `{ id, name }`.
   Authentication, authorization, and tenancy semantics are consumer territory,
   exposed through callbacks (`authenticate`, `authorize`) and opaque scope keys.

2. **Communication-first.** The SDK ships exactly four primitives: identities,
   threads, events, runs. Everything else is composition by the consumer.

3. **REST for state, WebSocket for delivery.** Anything that can be a request/response
   IS a request/response. Socket.IO carries subscriptions and live event push.
   Action operations exist in both transports as thin shells over one handler.

4. **Plug and play.** A consumer should be able to mount the SDK on their existing
   FastAPI/Hono app in <30 lines and have a working multi-assistant chat backend.
   No forced microservices, no forced migrations of existing user/auth tables.

5. **Drop everything else.** No streaming, no MCP client, no A2A, no settings
   broadcaster, no knowledge sources, no built-in form rendering, no built-in
   blob storage. If a consumer needs these, they bring them.

### What goes where

- **Wire/storage primitive?** → in the SDK
- **Real-time push to subscribers?** → Socket.IO event
- **Request/response, no live push?** → REST endpoint
- **Decision the SDK shouldn't be making?** → consumer callback
- **Reasonable in 80% of cases?** → SDK default with opt-out
- **UI/render concern?** → docs example, not SDK code

### When in doubt, follow

> "Could the consumer build this themselves with the primitives we already ship?"
> If yes, do not add it to the SDK.

### CHANGELOG discipline

- Every PR touching `src/` updates `CHANGELOG.md` under `## [Unreleased]`.
- Breaking changes get a `BREAKING:` prefix and bump major (in lockstep with the
  other two repos: `rrcp-client-ts` and `rrcp-ts`).
- Breaking changes ship side-by-side migration notes in the changelog entry.
- The `changelog.yml` GitHub Action blocks PRs that touch `src/` without
  updating `CHANGELOG.md`.

## Repo role

`rrcp` (PyPI name) is the **Python server SDK** for the rrcp protocol.
It is the consumer-facing Python library that ships REST + Socket.IO endpoints
mountable onto FastAPI (or any ASGI app), backed by Postgres.

Built on:

- **Python 3.11+**
- **Pydantic** for protocol models
- **python-socketio (ASGI)** for the live transport
- **asyncpg** for the Postgres reference `ThreadStore`
- **FastAPI compatible** — mounts as a router on existing FastAPI apps

It is part of a three-repo family. Major versions are in lockstep:

| Repo | Publishes to | Package name |
|---|---|---|
| `rrcp-client-ts` | npm | `@0x0064/rrcp-react` |
| `rrcp-py` (this repo) | PyPI | `rrcp` |
| `rrcp-ts` | npm | `@0x0064/rrcp` |


## Commands

```bash
uv sync --all-extras         # Install all dependencies
uv run poe dev               # Full sanity check: lint + typecheck + test
uv run poe build             # Build wheel + sdist (python -m build)
uv run poe format            # Format code (ruff format)
uv run poe format:imports    # Sort imports
uv run poe check             # Lint only (ruff check)
uv run poe check:fix         # Auto-fix lint issues
uv run poe typecheck         # Type check only (mypy src/)
uv run poe test              # Run tests
uv run poe test:cov          # Tests with coverage
```

Run a single test: `uv run pytest tests/path/to/test.py::test_name -v`

### Tests require a Postgres connection

Two options. **Either** spin up the bundled docker-compose (zero config):

```bash
docker compose -f docker-compose.test.yml up -d
uv run poe test
```

**Or** point at your own Postgres via `DATABASE_URL` (use a dedicated test database
— tests truncate tables between runs, never point at dev or prod):

```bash
createdb rrcp_test
DATABASE_URL=postgresql://localhost/rrcp_test uv run poe test
```

The schema in `src/rrcp/store/postgres/schema.sql` is auto-applied on the first
test run via `CREATE TABLE IF NOT EXISTS`. No migrations to manage manually.

Default `DATABASE_URL` (when unset) points at the docker-compose service:
`postgresql://rrcp:rrcp@localhost:55432/rrcp_test`

## Architecture

See `docs/plans/2026-04-09-rrcp-v2-design.md` for the full architecture.

Source layout (target):

```
src/rrcp/
  server/        # AcpServer entrypoint, lifecycle
  protocol/      # Pydantic frame types, parser, mappers
  store/         # ThreadStore protocol + PostgresThreadStore
  handler/       # HandlerContext, HandlerSend, run executor
  socketio/      # Socket.IO event handlers
  rest/          # FastAPI router (/threads, /events, /runs, ...)
  analytics/     # AnalyticsCollector (consumer-callback sink)
```

## Code Style

- Python 3.11+, ruff for linting/formatting, line length 120
- Quote style: double quotes
- Ruff rules: E, F, I (isort), UP (pyupgrade)
- `pytest-asyncio` with `asyncio_mode = "auto"` (no need for `@pytest.mark.asyncio`)
- Pydantic for all models; dataclasses for config objects
