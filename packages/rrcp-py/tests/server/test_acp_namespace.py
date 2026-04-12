from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from rrcp_server.protocol.identity import Identity, UserIdentity
from rrcp_server.protocol.thread import Thread
from rrcp_server.server.acp import AcpServer
from rrcp_server.server.auth import HandshakeData
from rrcp_server.server.namespace import NamespaceViolation


class _StubStore:
    """Minimal ThreadStore stub — every method raises. Used when we only
    need to check construction-time validation."""

    def __getattr__(self, name: str) -> Any:
        raise NotImplementedError(name)


async def _auth(_: HandshakeData) -> Identity:
    return UserIdentity(id="u", name="U", metadata={})


class TestAcpServerNamespaceKeys:
    def test_defaults_to_none(self) -> None:
        acp = AcpServer(store=_StubStore(), authenticate=_auth)  # type: ignore[arg-type]
        assert acp.namespace_keys is None

    def test_accepts_list(self) -> None:
        acp = AcpServer(
            store=_StubStore(),  # type: ignore[arg-type]
            authenticate=_auth,
            namespace_keys=["organization", "workspace"],
        )
        assert acp.namespace_keys == ["organization", "workspace"]

    def test_rejects_empty_list(self) -> None:
        with pytest.raises(NamespaceViolation, match="non-empty"):
            AcpServer(
                store=_StubStore(),  # type: ignore[arg-type]
                authenticate=_auth,
                namespace_keys=[],
            )

    def test_rejects_duplicate_keys(self) -> None:
        with pytest.raises(NamespaceViolation, match="duplicate"):
            AcpServer(
                store=_StubStore(),  # type: ignore[arg-type]
                authenticate=_auth,
                namespace_keys=["org", "org"],
            )

    def test_rejects_empty_key(self) -> None:
        with pytest.raises(NamespaceViolation, match="empty key"):
            AcpServer(
                store=_StubStore(),  # type: ignore[arg-type]
                authenticate=_auth,
                namespace_keys=["org", ""],
            )



def _thread(tenant: dict[str, str]) -> Thread:
    return Thread(
        id="th_1",
        tenant=tenant,
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestNamespaceForThread:
    def test_returns_none_when_keys_not_configured(self) -> None:
        acp = AcpServer(store=_StubStore(), authenticate=_auth)  # type: ignore[arg-type]
        assert acp.namespace_for_thread(_thread({"org": "A"})) is None

    def test_returns_path_when_keys_configured(self) -> None:
        acp = AcpServer(
            store=_StubStore(),  # type: ignore[arg-type]
            authenticate=_auth,
            namespace_keys=["org"],
        )
        assert acp.namespace_for_thread(_thread({"org": "A"})) == "/A"

    def test_raises_when_thread_missing_required_key(self) -> None:
        acp = AcpServer(
            store=_StubStore(),  # type: ignore[arg-type]
            authenticate=_auth,
            namespace_keys=["org"],
        )
        with pytest.raises(NamespaceViolation, match="missing required key"):
            acp.namespace_for_thread(_thread({}))


class TestEnforceNamespaceOnIdentity:
    def test_noop_when_keys_not_configured(self) -> None:
        acp = AcpServer(store=_StubStore(), authenticate=_auth)  # type: ignore[arg-type]
        acp.enforce_namespace_on_identity(
            UserIdentity(id="u", name="U", metadata={})
        )

    def test_passes_when_identity_has_all_keys(self) -> None:
        acp = AcpServer(
            store=_StubStore(),  # type: ignore[arg-type]
            authenticate=_auth,
            namespace_keys=["org"],
        )
        acp.enforce_namespace_on_identity(
            UserIdentity(
                id="u",
                name="U",
                metadata={"tenant": {"org": "A"}},
            )
        )

    def test_raises_when_identity_missing_tenant(self) -> None:
        acp = AcpServer(
            store=_StubStore(),  # type: ignore[arg-type]
            authenticate=_auth,
            namespace_keys=["org"],
        )
        with pytest.raises(NamespaceViolation, match="missing required key"):
            acp.enforce_namespace_on_identity(
                UserIdentity(id="u", name="U", metadata={})
            )

    def test_raises_when_identity_missing_one_of_many_keys(self) -> None:
        acp = AcpServer(
            store=_StubStore(),  # type: ignore[arg-type]
            authenticate=_auth,
            namespace_keys=["org", "ws"],
        )
        with pytest.raises(NamespaceViolation, match="missing required key: ws"):
            acp.enforce_namespace_on_identity(
                UserIdentity(
                    id="u",
                    name="U",
                    metadata={"tenant": {"org": "A"}},
                )
            )
