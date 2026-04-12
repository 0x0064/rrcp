# rrcp

**agent communication protocol** — a small, opinionated, business-agnostic communication layer for assistant-driven threads where multiple users and multiple assistants interact in shared rooms.

## Packages

| Package | Stack | Install | Status |
|---|---|---|---|
| [`@0x0064/rrcp-react`](./packages/rrcp-react) | React 19, TypeScript | `npm install @0x0064/rrcp-react` | alpha |
| [`@0x0064/rrcp`](./packages/rrcp-ts) | Node 22+, Hono, TypeScript | `npm install @0x0064/rrcp` | scaffold |
| [`rrcp`](./packages/rrcp-py) | Python 3.11+, FastAPI | `pip install rrcp` | alpha |

Major versions are kept in lockstep. Any breaking change in any one package bumps all three together.

## Primitives

The whole protocol surface, on every stack:

| Primitive | What it is |
|---|---|
| **Identity** | `UserIdentity` / `AssistantIdentity` / `SystemIdentity`, each `{ id, name, metadata }`. `metadata` is opaque to the SDK — attach whatever you need. |
| **Thread** | Ordered event log. Not owned; members join explicitly. 1:1 to a Socket.IO room. |
| **Event** | Discriminated union: `message`, `reasoning`, `tool.call`, `tool.result`, `thread.*`, `run.*` |
| **Run** | Assistant execution lifecycle (`pending → running → completed/failed/cancelled`) |

Everything else — auth, tenancy, assistant routing, LLM calls, file storage, form rendering — is **consumer territory**.

## Architecture

**REST for state, WebSocket for delivery.** Anything that can be a request/response is a REST endpoint. Socket.IO carries subscriptions and live event push. Action operations (`message:send`, `assistant:invoke`, `run:cancel`) exist in both transports as thin shells over one internal handler — connected clients save a round-trip over WS, server-to-server / webhooks use REST.

**Plug-and-play.** A consumer mounts the SDK onto their existing FastAPI / Hono app in <30 lines and has a working multi-user, multi-assistant chat backend. No forced microservices, no forced migrations of existing user/auth tables.

**Business-agnostic.** The SDK never inspects credentials, never decides who can do what, and never owns user/assistant data shapes beyond `{ id, name, metadata }`. Authentication, authorization, and tenancy semantics flow through consumer-provided callbacks.

**Deliberately small.** No streaming, no MCP client, no A2A, no settings broadcaster, no knowledge sources, no built-in form rendering, no built-in blob storage. If you need these, you bring them.

## 5-minute example

**Server (Python / FastAPI):**

```python
from fastapi import FastAPI
import asyncpg
from rrcp_server import ThreadServer, HandshakeData, PostgresThreadStore, TextPart, UserIdentity

async def authenticate(handshake: HandshakeData) -> UserIdentity | None:
    user = await lookup_user(handshake.headers.get("authorization", ""))
    if user is None:
        return None
    return UserIdentity(id=user.id, name=user.name, metadata={"tenant": {"organization": user.org}})

pool = await asyncpg.create_pool("postgresql://localhost/myapp")
thread_server = ThreadServer(store=PostgresThreadStore(pool=pool), authenticate=authenticate)

@thread_server.assistant("helper")
async def helper(ctx, send):
    yield send.message(content=[TextPart(text="Hello from an assistant!")])

app = FastAPI()
app.state.thread_server = thread_server
app.include_router(thread_server.router, prefix="/acp")
asgi = thread_server.mount_socketio(app)
```

**Client (React):**

```tsx
import { ThreadProvider, useThreadActions, useThreadEvents, useThreadSession } from '@0x0064/rrcp-react'

export function App() {
  return (
    <ThreadProvider
      url="http://localhost:8000"
      authenticate={async () => ({ headers: { authorization: `Bearer ${getToken()}` } })}
    >
      <Chat threadId="th_demo" />
    </ThreadProvider>
  )
}

function Chat({ threadId }: { threadId: string }) {
  const session = useThreadSession(threadId)
  const events = useThreadEvents(threadId)
  const { ask, isPending } = useThreadActions(threadId)
  if (session.status !== 'joined') return null
  return (
    <>
      <ul>{events.map((e) => <li key={e.id}>{renderEvent(e)}</li>)}</ul>
      <button
        onClick={() =>
          ask(['helper'], {
            clientId: crypto.randomUUID(),
            content: [{ type: 'text', text: 'hi' }],
          })
        }
        disabled={isPending}
      >
        Ask helper
      </button>
    </>
  )
}
```

See each package's README for the full reference:

- **[`packages/rrcp-react/README.md`](./packages/rrcp-react/README.md)** — hooks, provider, wire types, error classes, Suspense support, `parseMentions`, `useUpload`
- **[`packages/rrcp-py/README.md`](./packages/rrcp-py/README.md)** — FastAPI integration, handler API, REST + Socket.IO protocol, tenant model, `namespace_keys` hardening
- **[`packages/rrcp-ts/README.md`](./packages/rrcp-ts/README.md)** — Hono integration (scaffold — slice 4)


## License

MIT — see [`LICENSE`](./LICENSE).
