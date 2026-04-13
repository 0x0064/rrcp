from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status

from rrcp.protocol.event import Event, EventDraft, MessageEvent
from rrcp.protocol.identity import AssistantIdentity, Identity
from rrcp.protocol.recipients import normalize_recipients
from rrcp.protocol.tenant import matches
from rrcp.server.rest.deps import get_server, identity_tenant, resolve_identity
from rrcp.store.types import Page


def build_router() -> APIRouter:
    router = APIRouter(prefix="/threads/{thread_id}", tags=["messages"])

    @router.post(
        "/messages",
        status_code=status.HTTP_201_CREATED,
        response_model=MessageEvent,
    )
    async def send_message(
        thread_id: str,
        draft: EventDraft,
        request: Request,
        identity: Identity = Depends(resolve_identity),
    ) -> MessageEvent:
        server = get_server(request)
        thread = await server.store.get_thread(thread_id)
        if thread is None or not matches(thread.tenant, identity_tenant(identity)):
            raise HTTPException(status_code=404, detail="thread not found")
        if not await server.store.is_member(thread_id, identity.id):
            raise HTTPException(status_code=403, detail="not a member of this thread")
        if not await server.check_authorize(identity, thread_id, "message.send"):
            raise HTTPException(status_code=403, detail="not authorized: message.send")
        if draft.content is None:
            raise HTTPException(status_code=422, detail="message draft must include content")

        recipients = normalize_recipients(draft.recipients, author_id=identity.id)
        members = await server.store.list_members(thread_id) if recipients is not None else []
        if recipients is not None:
            member_ids = {m.identity_id for m in members}
            unknown = [rid for rid in recipients if rid not in member_ids]
            if unknown:
                raise HTTPException(
                    status_code=400,
                    detail=f"recipient_not_member: {unknown[0]}",
                )

        event = MessageEvent(
            id=f"evt_{secrets.token_hex(8)}",
            thread_id=thread_id,
            author=identity,
            created_at=datetime.now(UTC),
            metadata=draft.metadata,
            client_id=draft.client_id,
            recipients=recipients,
            content=draft.content,
        )
        await server.publish_event(event, thread=thread)

        if recipients and server.auto_invoke_recipients:
            members_by_id = {m.identity_id: m for m in members}
            for assistant_id in recipients:
                handler = server.get_handler(assistant_id)
                if handler is None:
                    continue
                if not await server.check_authorize(identity, thread_id, "assistant.invoke"):
                    continue
                member = members_by_id.get(assistant_id)
                if member is None or not isinstance(member.identity, AssistantIdentity):
                    continue
                await server.executor.execute(
                    thread=thread,
                    assistant=member.identity,
                    triggered_by=identity,
                    handler=handler,
                )

        return event

    @router.get("/events", response_model=Page[Event])
    async def list_events(
        thread_id: str,
        request: Request,
        limit: int = 100,
        identity: Identity = Depends(resolve_identity),
    ) -> Page[Event]:
        server = get_server(request)
        thread = await server.store.get_thread(thread_id)
        if thread is None or not matches(thread.tenant, identity_tenant(identity)):
            raise HTTPException(status_code=404, detail="thread not found")
        if not await server.store.is_member(thread_id, identity.id):
            raise HTTPException(status_code=403, detail="not a member of this thread")
        if not await server.check_authorize(identity, thread_id, "thread.read"):
            raise HTTPException(status_code=403, detail="not authorized: thread.read")
        return await server.store.list_events(thread_id, limit=limit)

    return router
