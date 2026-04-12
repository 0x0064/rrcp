from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from rrcp.handler.stream import Stream, StreamSink
from rrcp.protocol.content import ContentPart
from rrcp.protocol.event import (
    MessageEvent,
    ReasoningEvent,
    ToolCall,
    ToolCallEvent,
    ToolResult,
    ToolResultEvent,
)
from rrcp.protocol.identity import AssistantIdentity


def _new_id() -> str:
    return f"evt_{secrets.token_hex(8)}"


class HandlerSend:
    def __init__(
        self,
        thread_id: str,
        run_id: str,
        author: AssistantIdentity,
        stream_sink: StreamSink | None = None,
    ) -> None:
        self._thread_id = thread_id
        self._run_id = run_id
        self._author = author
        self._stream_sink = stream_sink

    def message(
        self,
        content: list[ContentPart],
        metadata: dict[str, Any] | None = None,
    ) -> MessageEvent:
        return MessageEvent(
            id=_new_id(),
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            created_at=datetime.now(UTC),
            metadata=metadata or {},
            content=content,
        )

    def reasoning(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> ReasoningEvent:
        return ReasoningEvent(
            id=_new_id(),
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            created_at=datetime.now(UTC),
            metadata=metadata or {},
            content=text,
        )

    def tool_call(
        self,
        name: str,
        arguments: Any,
        id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolCallEvent:
        return ToolCallEvent(
            id=_new_id(),
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            created_at=datetime.now(UTC),
            metadata=metadata or {},
            tool=ToolCall(
                id=id or f"call_{secrets.token_hex(8)}",
                name=name,
                arguments=arguments,
            ),
        )

    def tool_result(
        self,
        tool_id: str,
        result: Any | None = None,
        error: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResultEvent:
        return ToolResultEvent(
            id=_new_id(),
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            created_at=datetime.now(UTC),
            metadata=metadata or {},
            tool=ToolResult(id=tool_id, result=result, error=error),
        )

    def message_stream(self, metadata: dict[str, Any] | None = None) -> Stream:
        sink = self._require_sink()
        return Stream(
            sink=sink,
            target_type="message",
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            metadata=metadata,
        )

    def reasoning_stream(self, metadata: dict[str, Any] | None = None) -> Stream:
        sink = self._require_sink()
        return Stream(
            sink=sink,
            target_type="reasoning",
            thread_id=self._thread_id,
            run_id=self._run_id,
            author=self._author,
            metadata=metadata,
        )

    def _require_sink(self) -> StreamSink:
        if self._stream_sink is None:
            raise RuntimeError("streaming is not available: no stream_sink configured")
        return self._stream_sink
