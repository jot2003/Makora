"""API endpoints for LLM usage statistics and cost tracking."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import func

from app.models.database import SessionLocal, LLMUsageLog

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/summary")
def usage_summary(days: int = Query(30, ge=1, le=365)):
    db = SessionLocal()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)

        rows = (
            db.query(
                LLMUsageLog.model,
                func.sum(LLMUsageLog.prompt_tokens).label("prompt_tokens"),
                func.sum(LLMUsageLog.completion_tokens).label("completion_tokens"),
                func.sum(LLMUsageLog.total_tokens).label("total_tokens"),
                func.sum(LLMUsageLog.estimated_cost).label("total_cost"),
                func.count(LLMUsageLog.id).label("request_count"),
                func.avg(LLMUsageLog.latency_ms).label("avg_latency_ms"),
            )
            .filter(LLMUsageLog.created_at >= since)
            .group_by(LLMUsageLog.model)
            .all()
        )

        models = []
        totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "total_cost": 0.0, "request_count": 0, "avg_latency_ms": 0}
        for r in rows:
            entry = {
                "model": r.model,
                "prompt_tokens": r.prompt_tokens or 0,
                "completion_tokens": r.completion_tokens or 0,
                "total_tokens": r.total_tokens or 0,
                "total_cost": round(r.total_cost or 0, 6),
                "request_count": r.request_count or 0,
                "avg_latency_ms": int(r.avg_latency_ms or 0),
            }
            models.append(entry)
            totals["prompt_tokens"] += entry["prompt_tokens"]
            totals["completion_tokens"] += entry["completion_tokens"]
            totals["total_tokens"] += entry["total_tokens"]
            totals["total_cost"] += entry["total_cost"]
            totals["request_count"] += entry["request_count"]

        if totals["request_count"] > 0:
            all_latency = (
                db.query(func.avg(LLMUsageLog.latency_ms))
                .filter(LLMUsageLog.created_at >= since)
                .scalar()
            )
            totals["avg_latency_ms"] = int(all_latency or 0)

        totals["total_cost"] = round(totals["total_cost"], 6)

        return {"totals": totals, "by_model": models, "days": days}
    finally:
        db.close()


@router.get("/daily")
def usage_daily(days: int = Query(30, ge=1, le=365)):
    db = SessionLocal()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)

        rows = (
            db.query(
                func.date(LLMUsageLog.created_at).label("date"),
                LLMUsageLog.model,
                func.sum(LLMUsageLog.total_tokens).label("tokens"),
                func.sum(LLMUsageLog.estimated_cost).label("cost"),
                func.count(LLMUsageLog.id).label("requests"),
            )
            .filter(LLMUsageLog.created_at >= since)
            .group_by(func.date(LLMUsageLog.created_at), LLMUsageLog.model)
            .order_by(func.date(LLMUsageLog.created_at))
            .all()
        )

        daily: dict[str, dict] = {}
        for r in rows:
            d = str(r.date)
            if d not in daily:
                daily[d] = {"date": d, "total_tokens": 0, "total_cost": 0.0, "requests": 0, "models": {}}
            daily[d]["total_tokens"] += r.tokens or 0
            daily[d]["total_cost"] += round(r.cost or 0, 6)
            daily[d]["requests"] += r.requests or 0
            daily[d]["models"][r.model] = {
                "tokens": r.tokens or 0,
                "cost": round(r.cost or 0, 6),
                "requests": r.requests or 0,
            }

        result = list(daily.values())
        for entry in result:
            entry["total_cost"] = round(entry["total_cost"], 6)

        return {"daily": result, "days": days}
    finally:
        db.close()


@router.get("/by-meeting")
def usage_by_meeting(limit: int = Query(50, ge=1, le=200)):
    db = SessionLocal()
    try:
        rows = (
            db.query(
                LLMUsageLog.meeting_id,
                func.sum(LLMUsageLog.total_tokens).label("total_tokens"),
                func.sum(LLMUsageLog.estimated_cost).label("total_cost"),
                func.count(LLMUsageLog.id).label("request_count"),
                func.avg(LLMUsageLog.latency_ms).label("avg_latency_ms"),
                func.max(LLMUsageLog.created_at).label("last_used"),
            )
            .filter(LLMUsageLog.meeting_id.isnot(None))
            .group_by(LLMUsageLog.meeting_id)
            .order_by(func.max(LLMUsageLog.created_at).desc())
            .limit(limit)
            .all()
        )

        meetings = []
        for r in rows:
            meetings.append({
                "meeting_id": r.meeting_id,
                "total_tokens": r.total_tokens or 0,
                "total_cost": round(r.total_cost or 0, 6),
                "request_count": r.request_count or 0,
                "avg_latency_ms": int(r.avg_latency_ms or 0),
                "last_used": str(r.last_used) if r.last_used else None,
            })

        return {"meetings": meetings}
    finally:
        db.close()


@router.get("/recent")
def usage_recent(limit: int = Query(50, ge=1, le=200)):
    db = SessionLocal()
    try:
        rows = (
            db.query(LLMUsageLog)
            .order_by(LLMUsageLog.created_at.desc())
            .limit(limit)
            .all()
        )

        items = []
        for r in rows:
            items.append({
                "id": r.id,
                "meeting_id": r.meeting_id,
                "model": r.model,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "estimated_cost": round(r.estimated_cost or 0, 6),
                "request_type": r.request_type,
                "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })

        return {"items": items}
    finally:
        db.close()
