from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rrcp_server.handler.context import HandlerContext
    from rrcp_server.handler.send import HandlerSend
    from rrcp_server.protocol.event import Event

HandlerCallable = Callable[
    ["HandlerContext", "HandlerSend"],
    AsyncGenerator["Event", None],
]
