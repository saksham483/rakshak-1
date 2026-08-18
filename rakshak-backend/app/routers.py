import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from sqlalchemy import select, desc

from .db import SessionLocal
from .models import TelemetrySample, AnomalyEvent, Diagnosis, FaultInjection
from .satellite_registry import SATELLITES
from .telemetry_engine import FAULT_DEFS
from . import scheduler
from .ws_manager import manager
from . import replay

router = APIRouter()


@router.get("/satellites")
def list_satellites():
    out = []
    for sid, cfg in SATELLITES.items():
        out.append({
            "id": sid, "name": cfg["name"], "operator": cfg["operator"], "norad_id": cfg["norad_id"],
            "alt_km": cfg["alt_km"], "inclination_deg": cfg["inclination_deg"], "period_min": cfg["period_min"],
            "has_cached_tle": bool(cfg.get("tle_line1")), "note": cfg.get("note", ""),
            "monitoring_active": sid in scheduler.sims,
        })
    return out


@router.post("/satellites/{sat_id}/select")
def select_satellite(sat_id: str):
    """Start (or resume) monitoring this satellite. Call this before opening the websocket -
    it does the (potentially slow) live TLE fetch synchronously so the tick loop never blocks on it."""
    if sat_id not in SATELLITES:
        raise HTTPException(404, "unknown satellite id")
    sim = scheduler.get_sim(sat_id)
    return {"selected": sat_id, "tle_source": sim.tle_source}


@router.get("/telemetry/{sat_id}")
def telemetry_history(sat_id: str, channel: str | None = None, limit: int = 200):
    db = SessionLocal()
    try:
        q = select(TelemetrySample).where(TelemetrySample.satellite_id == sat_id)
        if channel:
            q = q.where(TelemetrySample.channel_id == channel)
        q = q.order_by(desc(TelemetrySample.ts)).limit(limit)
        rows = db.execute(q).scalars().all()
        return [{
            "channel": r.channel_id, "ts": r.ts.isoformat(), "value": r.value, "status": r.status,
            "severity": r.severity, "z": r.z_score, "baseline_mean": r.baseline_mean,
        } for r in reversed(rows)]
    finally:
        db.close()


@router.get("/events/{sat_id}")
def event_log(sat_id: str, limit: int = 50):
    db = SessionLocal()
    try:
        q = (select(AnomalyEvent).where(AnomalyEvent.satellite_id == sat_id)
             .order_by(desc(AnomalyEvent.ts_start)).limit(limit))
        events = db.execute(q).scalars().all()
        out = []
        for e in events:
            diag = db.execute(select(Diagnosis).where(Diagnosis.event_id == e.id)).scalars().first()
            out.append({
                "id": e.id, "channel": e.channel_id, "ts_start": e.ts_start.isoformat(),
                "ts_end": e.ts_end.isoformat() if e.ts_end else None,
                "peak_severity": e.peak_severity, "peak_z": e.peak_z, "resolved": e.resolved,
                "diagnosis": diag.narrative if diag else None,
                "diagnosis_source": diag.source if diag else None,
            })
        return out
    finally:
        db.close()


@router.get("/faults")
def list_fault_types():
    return FAULT_DEFS


@router.post("/faults/{sat_id}/inject")
def inject_fault(sat_id: str, fault: str):
    if sat_id not in SATELLITES:
        raise HTTPException(404, "unknown satellite id")
    sim = scheduler.get_sim(sat_id)
    ok = sim.inject_fault(fault)
    if ok:
        db = SessionLocal()
        try:
            db.add(FaultInjection(satellite_id=sat_id, fault_type=fault))
            db.commit()
        finally:
            db.close()
    return {"injected": ok, "fault": fault}


@router.post("/faults/{sat_id}/clear")
def clear_faults(sat_id: str):
    if sat_id not in SATELLITES:
        raise HTTPException(404, "unknown satellite id")
    scheduler.get_sim(sat_id).clear_faults()
    return {"cleared": True}


@router.get("/replay/channels")
def replay_channels():
    return replay.list_available_channels()


@router.get("/replay/benchmark")
def replay_benchmark(channel: str | None = None, limit_channels: int = 5):
    return replay.run_benchmark(channel=channel, limit_channels=limit_channels)


@router.websocket("/ws/live/{sat_id}")
async def ws_live(ws: WebSocket, sat_id: str):
    if sat_id not in SATELLITES:
        await ws.close(code=4404)
        return
    scheduler.get_sim(sat_id)
    await manager.connect(sat_id, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(sat_id, ws)
