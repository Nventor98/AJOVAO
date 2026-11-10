from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import AgentCommunityAssignment, AgentConsent, CommunityAgent, CommunityMembership
from app.models.user import User


def ensure_agent_consent(
    db: Session,
    *,
    agent_id: str,
    member_id: str,
    scope: str,
    consent_id: str | None = None,
) -> AgentConsent:
    agent = db.scalar(select(CommunityAgent).where(CommunityAgent.user_id == agent_id))
    if agent is None or agent.status != "APPROVED" or not agent.identity_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent is not approved.")
    agent_user = db.get(User, agent_id)
    if agent_user is None or "community_agent" not in (agent_user.roles or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent access is suspended.")

    assigned_community = db.scalar(
        select(AgentCommunityAssignment.id)
        .join(
            CommunityMembership,
            CommunityMembership.community_id == AgentCommunityAssignment.community_id,
        )
        .where(
            AgentCommunityAssignment.agent_id == agent_id,
            CommunityMembership.user_id == member_id,
        )
    )
    if assigned_community is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent is not assigned to the member's community.")

    now = datetime.now(timezone.utc)
    if consent_id is not None:
        consent = db.get(AgentConsent, consent_id)
    else:
        consents = db.scalars(
            select(AgentConsent)
            .where(
                AgentConsent.agent_id == agent_id,
                AgentConsent.member_id == member_id,
                AgentConsent.revoked_at.is_(None),
            )
            .order_by(AgentConsent.created_at.desc())
        ).all()
        consent = next(
            (
                item
                for item in consents
                if _aware(item.expires_at) > now and scope in (item.scopes or [])
            ),
            None,
        )
    if (
        consent is None
        or consent.agent_id != agent_id
        or consent.member_id != member_id
        or consent.revoked_at is not None
        or _aware(consent.expires_at) <= now
        or scope not in (consent.scopes or [])
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Valid member consent is required.")
    return consent


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
