from __future__ import annotations

import pytest

from rrcp.broadcast.recording import RecordingBroadcaster
from rrcp.handler.send import HandlerSend
from rrcp.handler.stream import StreamSink
from rrcp.protocol.content import TextPart
from rrcp.protocol.event import Event, MessageEvent
from rrcp.protocol.identity import AssistantIdentity
from rrcp.protocol.stream import StreamDeltaFrame, StreamEndFrame, StreamStartFrame


class _FakeSink:
    def __init__(self) -> None:
        self.broadcaster = RecordingBroadcaster()
        self.published: list[Event] = []

    async def start(self, frame: StreamStartFrame) -> None:
        await self.broadcaster.broadcast_stream_start(frame)

    async def delta(self, frame: StreamDeltaFrame) -> None:
        await self.broadcaster.broadcast_stream_delta(frame)

    async def end(self, frame: StreamEndFrame) -> None:
        await self.broadcaster.broadcast_stream_end(frame)

    async def publish_event(self, event: Event) -> Event:
        self.published.append(event)
        return event


def _send(sink: StreamSink) -> HandlerSend:
    return HandlerSend(
        thread_id="th_test",
        run_id="run_test",
        author=AssistantIdentity(id="asst", name="asst"),
        stream_sink=sink,
    )


async def test_message_stream_happy_path() -> None:
    sink = _FakeSink()
    send = _send(sink)

    async with send.message_stream() as stream:
        await stream.append("hello")
        await stream.append(" world")

    assert len(sink.broadcaster.stream_starts) == 1
    assert [d.text for d in sink.broadcaster.stream_deltas] == ["hello", " world"]
    assert len(sink.broadcaster.stream_ends) == 1
    assert sink.broadcaster.stream_ends[0].error is None
    assert len(sink.published) == 1

    event = sink.published[0]
    assert isinstance(event, MessageEvent)
    assert len(event.content) == 1
    part = event.content[0]
    assert isinstance(part, TextPart)
    assert part.text == "hello world"


async def test_message_stream_handler_error_publishes_no_event() -> None:
    sink = _FakeSink()
    send = _send(sink)

    with pytest.raises(RuntimeError):
        async with send.message_stream() as stream:
            await stream.append("partial")
            raise RuntimeError("boom")

    assert len(sink.broadcaster.stream_starts) == 1
    assert len(sink.broadcaster.stream_deltas) == 1
    assert len(sink.broadcaster.stream_ends) == 1
    end = sink.broadcaster.stream_ends[0]
    assert end.error is not None
    assert end.error.code == "handler_error"
    assert sink.published == []
