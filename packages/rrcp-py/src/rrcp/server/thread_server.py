from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from rrcp.analytics.collector import OnAnalyticsCallback
from rrcp.broadcast.protocol import Broadcaster
from rrcp.handler.executor import RunExecutor
from rrcp.handler.stream import StreamSink
from rrcp.handler.types import HandlerCallable
from rrcp.protocol.event import Event
from rrcp.protocol.identity import Identity
from rrcp.protocol.run import Run
from rrcp.protocol.stream import StreamDeltaFrame, StreamEndFrame, StreamStartFrame
from rrcp.protocol.thread import Thread
from rrcp.server.auth import AuthenticateCallback, AuthorizeCallback
from rrcp.server.namespace import NamespaceViolation, derive_namespace_path
from rrcp.store.protocol import ThreadStore


def _validate_namespace_keys(namespace_keys: list[str] | None) -> list[str] | None:
    if namespace_keys is None:
        return None
    if not namespace_keys:
        raise NamespaceViolation("namespace_keys must be None or a non-empty list")
    seen: set[str] = set()
    for key in namespace_keys:
        if not key:
            raise NamespaceViolation("namespace_keys contains an empty key")
        if key in seen:
            raise NamespaceViolation(f"namespace_keys contains duplicate: {key!r}")
        seen.add(key)
    return list(namespace_keys)


class _BoundStreamSink:
    def __init__(self, server: ThreadServer, thread: Thread) -> None:
        self._server = server
        self._thread = thread

    async def start(self, frame: StreamStartFrame) -> None:
        await self._server.broadcast_stream_start(frame, thread=self._thread)

    async def delta(self, frame: StreamDeltaFrame) -> None:
        await self._server.broadcast_stream_delta(frame, thread=self._thread)

    async def end(self, frame: StreamEndFrame) -> None:
        await self._server.broadcast_stream_end(frame, thread=self._thread)

    async def publish_event(self, event: Event) -> Event:
        return await self._server.publish_event(event, thread=self._thread)


class ThreadServer:
    def __init__(
        self,
        *,
        store: ThreadStore,
        authenticate: AuthenticateCallback,
        authorize: AuthorizeCallback | None = None,
        on_analytics: OnAnalyticsCallback | None = None,
        run_timeout_seconds: int = 120,
        replay_cap: int = 500,
        broadcaster: Broadcaster | None = None,
        namespace_keys: list[str] | None = None,
    ) -> None:
        self.store = store
        self.authenticate = authenticate
        self.authorize = authorize
        self.replay_cap = replay_cap
        self.broadcaster = broadcaster
        self.namespace_keys = _validate_namespace_keys(namespace_keys)
        self._handlers: dict[str, HandlerCallable] = {}
        self._socketio: Any = None
        self.executor = RunExecutor(
            store=store,
            on_analytics=on_analytics,
            run_timeout_seconds=run_timeout_seconds,
            publish_event=self.publish_event,
            publish_thread_updated=self.publish_thread_updated,
            handler_resolver=self.get_handler,
            stream_sink_factory=self._make_stream_sink,
        )

        from rrcp.server.rest.invocations import build_router as build_invocations
        from rrcp.server.rest.members import build_router as build_members
        from rrcp.server.rest.messages import build_router as build_messages
        from rrcp.server.rest.runs import build_router as build_runs
        from rrcp.server.rest.threads import build_router as build_threads

        self.router = APIRouter()
        self.router.include_router(build_threads())
        self.router.include_router(build_messages())
        self.router.include_router(build_members())
        self.router.include_router(build_invocations())
        self.router.include_router(build_runs())

    def register_assistant(self, assistant_id: str, handler: HandlerCallable) -> None:
        self._handlers[assistant_id] = handler

    def assistant(self, assistant_id: str) -> Callable[[HandlerCallable], HandlerCallable]:
        def decorator(handler: HandlerCallable) -> HandlerCallable:
            self.register_assistant(assistant_id, handler)
            return handler

        return decorator

    def get_handler(self, assistant_id: str) -> HandlerCallable | None:
        return self._handlers.get(assistant_id)

    async def check_authorize(self, identity: Identity, thread_id: str, action: str) -> bool:
        if self.authorize is None:
            return True
        return await self.authorize(identity, thread_id, action)

    async def publish_event(self, event: Event, *, thread: Thread | None = None) -> Event:
        appended = await self.store.append_event(event)
        if self.broadcaster is not None:
            namespace: str | None = None
            if self.namespace_keys is not None:
                if thread is None:
                    thread = await self.store.get_thread(event.thread_id)
                if thread is not None:
                    namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
            await self.broadcaster.broadcast_event(appended, namespace=namespace)
        return appended

    async def publish_thread_updated(self, thread: Thread) -> None:
        if self.broadcaster is not None:
            namespace: str | None = None
            if self.namespace_keys is not None:
                namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
            await self.broadcaster.broadcast_thread_updated(thread, namespace=namespace)

    async def publish_members_updated(
        self,
        thread_id: str,
        members: list[Identity],
        *,
        thread: Thread | None = None,
    ) -> None:
        if self.broadcaster is not None:
            namespace: str | None = None
            if self.namespace_keys is not None:
                if thread is None:
                    thread = await self.store.get_thread(thread_id)
                if thread is not None:
                    namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
            await self.broadcaster.broadcast_members_updated(thread_id, members, namespace=namespace)

    async def publish_run_updated(self, run: Run, *, thread: Thread | None = None) -> None:
        if self.broadcaster is not None:
            namespace: str | None = None
            if self.namespace_keys is not None:
                if thread is None:
                    thread = await self.store.get_thread(run.thread_id)
                if thread is not None:
                    namespace = derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)
            await self.broadcaster.broadcast_run_updated(run, namespace=namespace)

    async def broadcast_stream_start(self, frame: StreamStartFrame, *, thread: Thread) -> None:
        if self.broadcaster is None:
            return
        namespace = self.namespace_for_thread(thread)
        await self.broadcaster.broadcast_stream_start(frame, namespace=namespace)

    async def broadcast_stream_delta(self, frame: StreamDeltaFrame, *, thread: Thread) -> None:
        if self.broadcaster is None:
            return
        namespace = self.namespace_for_thread(thread)
        await self.broadcaster.broadcast_stream_delta(frame, namespace=namespace)

    async def broadcast_stream_end(self, frame: StreamEndFrame, *, thread: Thread) -> None:
        if self.broadcaster is None:
            return
        namespace = self.namespace_for_thread(thread)
        await self.broadcaster.broadcast_stream_end(frame, namespace=namespace)

    def _make_stream_sink(self, thread: Thread) -> StreamSink:
        return _BoundStreamSink(self, thread)

    def namespace_for_thread(self, thread: Thread) -> str | None:
        if self.namespace_keys is None:
            return None
        return derive_namespace_path(thread.tenant, namespace_keys=self.namespace_keys)

    def enforce_namespace_on_identity(self, identity: Identity) -> None:
        if self.namespace_keys is None:
            return
        tenant_raw = identity.metadata.get("tenant", {})
        if not isinstance(tenant_raw, dict):
            tenant: dict[str, str] = {}
        else:
            # Drop non-string values rather than coercing via str(), so that
            # a consumer accidentally storing a bool/number/list cannot
            # silently pass validation — derive_namespace_path will raise a
            # clear "missing required key" error on the dropped key instead.
            tenant = {k: v for k, v in tenant_raw.items() if isinstance(v, str)}
        derive_namespace_path(tenant, namespace_keys=self.namespace_keys)

    def mount_socketio(self, fastapi_app: Any) -> Any:
        from rrcp.broadcast.socketio import SocketIOBroadcaster
        from rrcp.socketio.server import ThreadSocketIO

        sio_server = ThreadSocketIO(self, replay_cap=self.replay_cap)
        self.broadcaster = SocketIOBroadcaster(sio_server.sio)
        self._socketio = sio_server
        return sio_server.asgi_app(fastapi_app)
