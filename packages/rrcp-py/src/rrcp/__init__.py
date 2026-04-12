from importlib.metadata import version as _pkg_version

__version__ = _pkg_version("rrcp")

from rrcp_server.analytics.collector import (
    AnalyticsEvent,
    AssistantAnalytics,
    OnAnalyticsCallback,
)
from rrcp_server.broadcast.protocol import Broadcaster
from rrcp_server.broadcast.recording import RecordingBroadcaster
from rrcp_server.broadcast.socketio import SocketIOBroadcaster
from rrcp_server.handler.context import HandlerContext
from rrcp_server.handler.send import HandlerSend
from rrcp_server.handler.types import HandlerCallable
from rrcp_server.protocol.content import (
    AudioPart,
    ContentPart,
    DocumentPart,
    FormPart,
    FormStatus,
    ImagePart,
    TextPart,
    parse_content_part,
)
from rrcp_server.protocol.event import (
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
from rrcp_server.protocol.identity import (
    AssistantIdentity,
    Identity,
    SystemIdentity,
    UserIdentity,
    parse_identity,
)
from rrcp_server.protocol.run import Run, RunError, RunStatus
from rrcp_server.protocol.tenant import TenantScope, matches
from rrcp_server.protocol.thread import Thread, ThreadMember, ThreadPatch
from rrcp_server.server.acp import AcpServer
from rrcp_server.server.auth import AuthenticateCallback, AuthorizeCallback, HandshakeData
from rrcp_server.server.namespace import (
    NamespaceViolation,
    derive_namespace_path,
    parse_namespace_path,
    validate_namespace_value,
)
from rrcp_server.store.postgres.store import PostgresThreadStore
from rrcp_server.store.protocol import ThreadStore
from rrcp_server.store.types import EventCursor, Page, ThreadCursor

__all__ = [
    "AcpServer",
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
