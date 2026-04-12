from importlib.metadata import version as _pkg_version

__version__ = _pkg_version("rrcp")

from rrcp.analytics.collector import (
    AnalyticsEvent,
    AssistantAnalytics,
    OnAnalyticsCallback,
)
from rrcp.broadcast.protocol import Broadcaster
from rrcp.broadcast.recording import RecordingBroadcaster
from rrcp.broadcast.socketio import SocketIOBroadcaster
from rrcp.handler.context import HandlerContext
from rrcp.handler.send import HandlerSend
from rrcp.handler.types import HandlerCallable
from rrcp.protocol.content import (
    AudioPart,
    ContentPart,
    DocumentPart,
    FormPart,
    FormStatus,
    ImagePart,
    TextPart,
    parse_content_part,
)
from rrcp.protocol.event import (
    Event,
    EventDraft,
    MessageEvent,
    ReasoningEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunFailedEvent,
    RunStartedEvent,
    ThreadCreatedEvent,
    ThreadMemberAddedEvent,
    ThreadMemberRemovedEvent,
    ThreadTenantChangedEvent,
    ToolCall,
    ToolCallEvent,
    ToolResult,
    ToolResultEvent,
    parse_event,
)
from rrcp.protocol.identity import (
    AssistantIdentity,
    Identity,
    SystemIdentity,
    UserIdentity,
    parse_identity,
)
from rrcp.protocol.run import Run, RunError, RunStatus
from rrcp.protocol.tenant import TenantScope, matches
from rrcp.protocol.thread import Thread, ThreadMember, ThreadPatch
from rrcp.server.auth import AuthenticateCallback, AuthorizeCallback, HandshakeData
from rrcp.server.namespace import (
    NamespaceViolation,
    derive_namespace_path,
    parse_namespace_path,
    validate_namespace_value,
)
from rrcp.server.thread_server import ThreadServer
from rrcp.store.postgres.store import PostgresThreadStore
from rrcp.store.protocol import ThreadStore
from rrcp.store.types import EventCursor, Page, ThreadCursor

__all__ = [
    "ThreadServer",
    "AnalyticsEvent",
    "AssistantAnalytics",
    "AssistantIdentity",
    "AudioPart",
    "AuthenticateCallback",
    "AuthorizeCallback",
    "Broadcaster",
    "ContentPart",
    "DocumentPart",
    "Event",
    "EventCursor",
    "EventDraft",
    "FormPart",
    "FormStatus",
    "HandlerCallable",
    "HandlerContext",
    "HandlerSend",
    "HandshakeData",
    "Identity",
    "ImagePart",
    "MessageEvent",
    "NamespaceViolation",
    "OnAnalyticsCallback",
    "Page",
    "PostgresThreadStore",
    "ReasoningEvent",
    "RecordingBroadcaster",
    "Run",
    "RunCancelledEvent",
    "RunCompletedEvent",
    "RunError",
    "RunFailedEvent",
    "RunStartedEvent",
    "RunStatus",
    "SocketIOBroadcaster",
    "SystemIdentity",
    "TenantScope",
    "TextPart",
    "Thread",
    "ThreadCreatedEvent",
    "ThreadCursor",
    "ThreadMember",
    "ThreadMemberAddedEvent",
    "ThreadMemberRemovedEvent",
    "ThreadPatch",
    "ThreadStore",
    "ThreadTenantChangedEvent",
    "ToolCall",
    "ToolCallEvent",
    "ToolResult",
    "ToolResultEvent",
    "UserIdentity",
    "__version__",
    "derive_namespace_path",
    "matches",
    "parse_content_part",
    "parse_event",
    "parse_identity",
    "parse_namespace_path",
    "validate_namespace_value",
]
