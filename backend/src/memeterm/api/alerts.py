"""REST endpoints for the alert feed + mute rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from memeterm.db.models import Alert, MuteRule
from memeterm.db.session import get_sessionmaker, session_scope

router = APIRouter()


@router.get("/alerts")
async def list_alerts(
    severity: Literal["info", "watch", "action", "critical"] | None = Query(default=None),
    include_acknowledged: bool = Query(default=False),
    since_minutes: int = Query(default=24 * 60, ge=1, le=24 * 60 * 7),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
    sm = get_sessionmaker()
    async with sm() as session:
        stmt = (
            select(Alert)
            .where(Alert.triggered_at >= cutoff)
            .order_by(desc(Alert.triggered_at))
            .limit(limit)
        )
        if severity is not None:
            stmt = stmt.where(Alert.severity == severity)
        if not include_acknowledged:
            stmt = stmt.where(Alert.acknowledged_at.is_(None))
        rows = (await session.execute(stmt)).scalars().all()
    return {
        "count": len(rows),
        "items": [
            {
                "id": a.id,
                "severity": a.severity,
                "rule": a.rule,
                "subject_kind": a.subject_kind,
                "subject_id": a.subject_id,
                "title": a.title,
                "body": a.body,
                "channels": a.delivered_channels or [],
                "triggered_at": a.triggered_at.isoformat(),
                "acknowledged_at": a.acknowledged_at.isoformat()
                if a.acknowledged_at
                else None,
            }
            for a in rows
        ],
    }


@router.post("/alerts/{alert_id}/ack")
async def ack_alert(alert_id: int) -> dict[str, Any]:
    async with session_scope() as session:
        row = await session.get(Alert, alert_id)
        if row is None:
            raise HTTPException(status_code=404, detail="alert not found")
        row.acknowledged_at = datetime.now(timezone.utc)
        return {"id": alert_id, "acknowledged_at": row.acknowledged_at.isoformat()}


class MutePayload(BaseModel):
    severity: Literal["info", "watch", "action", "critical"] | None = None
    rule: str | None = Field(default=None, max_length=80)
    subject_kind: Literal["coin", "position", "wallet", "narrative"] | None = None
    subject_id: str | None = Field(default=None, max_length=128)
    minutes: int = Field(default=60, ge=1, le=24 * 60 * 7)
    note: str | None = Field(default=None, max_length=200)


@router.get("/mutes")
async def list_mutes(active_only: bool = Query(default=True)) -> dict[str, Any]:
    sm = get_sessionmaker()
    async with sm() as session:
        rows = (await session.execute(select(MuteRule).order_by(desc(MuteRule.created_at)))).scalars().all()
    now = datetime.now(timezone.utc)
    items: list[dict[str, Any]] = []
    for m in rows:
        is_active = (m.active_until is None or m.active_until >= now) and (
            m.active_from is None or m.active_from <= now
        )
        if active_only and not is_active:
            continue
        items.append(
            {
                "id": m.id,
                "severity": m.severity,
                "rule": m.rule,
                "subject_kind": m.subject_kind,
                "subject_id": m.subject_id,
                "active_from": m.active_from.isoformat() if m.active_from else None,
                "active_until": m.active_until.isoformat() if m.active_until else None,
                "note": m.note,
                "created_at": m.created_at.isoformat(),
                "is_active": is_active,
            }
        )
    return {"count": len(items), "items": items}


@router.post("/mutes")
async def create_mute(payload: MutePayload) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    until = now + timedelta(minutes=payload.minutes)
    async with session_scope() as session:
        row = MuteRule(
            severity=payload.severity,
            rule=payload.rule,
            subject_kind=payload.subject_kind,
            subject_id=payload.subject_id,
            active_from=now,
            active_until=until,
            note=payload.note,
            created_at=now,
        )
        session.add(row)
        await session.flush()
        return {"id": row.id, "active_until": until.isoformat()}


@router.delete("/mutes/{mute_id}")
async def delete_mute(mute_id: int) -> dict[str, Any]:
    async with session_scope() as session:
        row = await session.get(MuteRule, mute_id)
        if row is None:
            raise HTTPException(status_code=404, detail="mute not found")
        await session.delete(row)
        return {"id": mute_id, "deleted": True}
