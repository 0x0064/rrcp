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
  other two repos: `rrcp-py` and `rrcp-ts`).
- Breaking changes ship side-by-side migration notes in the changelog entry.
- The `changelog.yml` GitHub Action blocks PRs that touch `src/` without
  updating `CHANGELOG.md`.

## Repo role

`@0x0064/rrcp-react` is the **React client SDK** for the rrcp protocol. It is
the consumer-facing browser-side library that wires React applications to an
`@0x0064/rrcp` (Node) or `rrcp` (Python) backend.

Built on:

- **React 19** (compiler-friendly hooks, `use()`, `useTransition`)
- **Socket.IO client** for the live transport
- **Zustand** for live state (events, runs, members)
- **TanStack Query** for REST cache + invalidation

It is part of a three-repo family. Major versions are in lockstep:

| Repo | Publishes to | Package name |
|---|---|---|
| `rrcp-client-ts` (this repo) | npm | `@0x0064/rrcp-react` |
| `rrcp-py` | PyPI | `rrcp` |
| `rrcp-ts` | npm | `@0x0064/rrcp` |


## Commands

```bash
npm install            # Install all dependencies
npm run dev            # Full sanity check: lint + typecheck + test
npm run build          # Build ESM + CJS + types via tsup
npm run format         # Format code (Biome)
npm run check          # Lint only (Biome)
npm run check:fix      # Auto-fix lint issues
npm run typecheck      # Type check only (tsc --noEmit)
npm run test           # Run all tests (Vitest, jsdom)
npm run test:watch     # Watch mode
```

## Architecture

See `docs/plans/2026-04-09-rrcp-v2-design.md` for the full architecture.

Source layout (target):

```
src/
  client/        # AcpClient (Socket.IO + REST wrapper)
  store/         # Zustand store (events, runs, members, sessions)
  hooks/         # React hooks (useThreadSession, useThreadEvents, ...)
  protocol/      # Wire types + mappers (snake_case ↔ camelCase)
  utils/         # parseMentions, useUpload, etc.
  main.ts        # public barrel export
```

## Code Style

- Biome for linting and formatting: 2-space indent, single quotes, no semicolons
  (except ASI-hazard), trailing commas in ES5 positions, 100-char line width, LF.
- TypeScript strict mode with `noUncheckedIndexedAccess`, `noUnusedLocals`,
  `noUnusedParameters`.
- `useLiteralKeys` and `noNonNullAssertion` lint rules are disabled.
