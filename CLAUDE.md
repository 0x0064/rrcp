# CLAUDE.md

Monorepo-level guidance for Claude Code. Each package under `packages/` has its own `CLAUDE.md` with stack-specific detail — this file covers the cross-package shape.

## Philosophy (READ FIRST)

rrcp is a **Communication Protocol** for assistant-driven threads. It is NOT an AI framework, NOT an LLM wrapper, and NOT a chat application — it is the wire and the storage underneath them.

### Core principles

1. **Business agnostic.** The SDK never inspects credentials, never decides who can do what, and never owns user/assistant/tool data shapes beyond `{ id, name, metadata }`. Auth, authorization, and tenancy semantics flow through consumer callbacks.
2. **Communication-first.** Exactly four primitives: identities, threads, events, runs. Everything else is composition by the consumer.
3. **REST for state, WebSocket for delivery.** Request/response IS a REST endpoint. Socket.IO carries subscriptions and live event push. Action operations exist in both as thin shells over one internal handler.
4. **Plug-and-play.** Mount onto the consumer's existing FastAPI / Hono app in <30 lines.
5. **Drop everything else.** No streaming, no MCP, no A2A, no settings broadcaster, no knowledge sources, no built-in form rendering, no built-in blob storage.

### Decision rule

> "Could the consumer build this themselves with the primitives we already ship?" If yes, do not add it to the SDK.

## Repo layout

```
rrcp/
├── packages/
│   ├── rrcp-react/      @0x0064/rrcp-react     (React 19, TypeScript)
│   ├── rrcp-ts/       @0x0064/rrcp    (Node 22+, Hono, TypeScript)
│   └── rrcp-py/     rrcp (PyPI)     (Python 3.11+, FastAPI)
├── docs/
│   └── plans/             design doc + implementation plans
├── examples/              runnable consumer examples
└── .github/workflows/     path-filtered CI + tag-triggered releases
```

## Package naming cheat sheet

| Package | PyPI / npm name | Import |
|---|---|---|
| rrcp-react | `@0x0064/rrcp-react` | `import { ThreadProvider } from '@0x0064/rrcp-react'` |
| rrcp-ts | `@0x0064/rrcp` | `import { ThreadServer } from '@0x0064/rrcp'` |
| rrcp-py | `rrcp` | `from rrcp import ThreadServer` |

**Note on the Python name:** the PyPI package is `rrcp` (with hyphen), but the Python import is `rrcp_server` (with underscore). This is the standard Python convention — PyPI uses hyphens, modules use underscores. We deliberately chose a flat module name over a namespace package (`rrcp.server`) because namespace packages have footguns with mypy, editable installs, and top-level re-exports.

## Lockstep versioning

**Major versions** are kept in lockstep across all three packages. Any breaking change in any package bumps all three to the next major together. Minor and patch versions are independent per package.

When a breaking change lands in one package, the other two get a new major tag + a migration-note entry in their `CHANGELOG.md` even if their public API didn't technically change.

## Releases

One publish workflow per package. All three trigger on `release: published` and filter by the Release's tag name prefix, so drafting a Release with tag `rrcp-py-v0.3.0` only fires `release-rrcp-py.yml`.

| Tag prefix | Workflow | Publishes to | Auth |
|---|---|---|---|
| `rrcp-react-v*` | `release-rrcp-react.yml` | npm | `NPM_TOKEN` secret |
| `rrcp-ts-v*` | `release.rrcp-ts.yml` | npm | `NPM_TOKEN` secret |
| `rrcp-py-v*` | `release-rrcp-py.yml` | PyPI | OIDC trusted publishing (no secret) |

Each workflow does **build and publish only**: checkout → install → `npm run build` or `python -m build` → publish. There is deliberately **no CI workflow** — no lint, no typecheck, no tests run on push or PR. The repo is early-stage; testing happens locally (`npm run dev` / `uv run poe dev` in each package) until there's a reason to automate it. Add CI later when there's a second contributor or a regression worth guarding.

Release flow:

```
1. Bump the version in packages/<pkg>/package.json (or pyproject.toml) + CHANGELOG
2. Merge that to main
3. On GitHub: Releases → Draft a new release
     - Tag: rrcp-py-v0.2.0a6 (create on publish)
     - Target: main
     - Write release notes
     - Publish release
4. release-rrcp-py.yml fires → builds → publishes to PyPI via OIDC
```

### PyPI trusted publishing setup

`release-rrcp-py.yml` uses OIDC trusted publishing — no `PYPI_TOKEN` secret. One-time setup on PyPI (https://pypi.org/manage/account/publishing/):

| Field | Value |
|---|---|
| PyPI Project Name | `rrcp` |
| Owner | `0x0064` |
| Repository name | `rrcp` |
| Workflow filename | `release-rrcp-py.yml` |
| Environment name | `pypi` |

And on GitHub (Repo Settings → Environments → New environment):

- Create an environment named `pypi` (must match the PyPI form exactly)
- Optional: under **Deployment branches and tags**, add pattern `rrcp-py-v*` so only correctly-prefixed tags can deploy

### npm setup

Create an environment named `npm` (Repo Settings → Environments → New environment). Add `NPM_TOKEN` as a secret scoped to that environment (Repo Settings → Environments → npm → Environment secrets). The token is an npm automation token with publish rights to the `@0x0064` scope.

Both `release-rrcp-react.yml` and `release-rrcp-ts.yml` share the same `npm` environment and the same `NPM_TOKEN` secret.

### CHANGELOG discipline

- Every PR touching `packages/<pkg>/src/**` updates that package's `CHANGELOG.md` under `## [Unreleased]`.
- Breaking changes get a `BREAKING:` prefix and bump major.
- Breaking changes ship side-by-side migration notes in the changelog entry.

## Design document

The canonical design lives at `docs/plans/2026-04-09-rrcp-v2-design.md`. Per-slice implementation plans live in the same directory, named `YYYY-MM-DD-slice-N-<name>.md`.

## Code style

- **Python** (`packages/rrcp-py/`): ruff, line length 120, double quotes, pytest-asyncio auto mode, Pydantic v2, mypy strict.
- **TypeScript** (`packages/rrcp-react/`, `packages/rrcp-ts/`): Biome, 2-space indent, single quotes, no semicolons, 100-char line width, TS strict with `noUncheckedIndexedAccess`.

## Commands

Each package is independently testable from its directory. There is no root-level build orchestrator.

```bash
# Python
cd packages/rrcp-py
uv sync --all-extras
uv run poe dev                # lint + typecheck + test
uv run poe build              # wheel + sdist

# React client
cd packages/rrcp-react
npm install
npm run dev                   # lint + typecheck + test
npm run build                 # ESM + CJS + types via tsup

# Node server
cd packages/rrcp-ts
npm install
npm run test                  # vitest (passes with no tests while it's a scaffold)
```
