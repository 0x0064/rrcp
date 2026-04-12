from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rrcp.protocol.identity import Identity


class HandshakeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    headers: dict[str, str] = Field(default_factory=dict)
    auth: dict[str, Any] = Field(default_factory=dict)


AuthenticateCallback = Callable[[HandshakeData], Awaitable[Identity | None]]
AuthorizeCallback = Callable[[Identity, str, str], Awaitable[bool]]
