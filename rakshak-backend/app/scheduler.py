import asyncio
import datetime
from . import config
from .db import SessionLocal
from .models import TelemetrySample, AnomalyEvent, Diagnosis
from .telemetry_engine import SatelliteSim
from .satellite_registry import SATELLITES
from .ws_manager import manager
from .diagnosis import generate_diagnosis

sims: dict[str, SatelliteSim] = {}
_open_events: dict[tuple, int] = {}  # (satellite_id, channel_id) -> AnomalyEvent.id


def get_sim(sat_id: str) -> SatelliteSim:
    if sat_id not in SATELLITES:
        raise KeyError(sat_id)
    if sat_id not in sims:
        sims[sat_id] = SatelliteSim(SATELLITES[sat_id])
    return sims[sat_id]


async def _tick_satellite(sat_id: str):
    sim = sims[sat_id]
    results, ostate = sim.tick()
    now = datetime.datetime.now(datetime.timezone.utc)

    db = SessionLocal()
    try:
        for r in results:
            db.add(TelemetrySample(
                satellite_id=sat_id, channel_id=r["channel"], ts=now, value=r["value"],
                status=r["status"], severity=r["severity"], z_score=r["z"],
                baseline_mean=r["baseline_mean"], baseline_std=r["baseline_std"],
            ))
            key = (sat_id, r["channel"])
            if r["status"] != r["prev_status"]:
                if r["status"] == "anomaly":
                    ev = AnomalyEvent(satellite_id=sat_id, channel_id=r["channel"], ts_start=now,
                                       peak_severity=r["severity"], peak_z=r["z"])
                    db.add(ev)
                    db.flush()
                    _open_events[key] = ev.id
                    asyncio.create_task(_run_diagnosis(sat_id, r, ev.id))
                elif r["prev_status"] == "anomaly" and r["status"] != "watch":
                    ev_id = _open_events.pop(key, None)
                    if ev_id:
                        ev = db.get(AnomalyEvent, ev_id)
                        if ev:
                            ev.ts_end = now
                            ev.resolved = True
            elif key in _open_events:
                ev = db.get(AnomalyEvent, _open_events[key])
                if ev and r["severity"] > ev.peak_severity:
                    ev.peak_severity = r["severity"]
                    ev.peak_z = r["z"]
        db.commit()
    finally:
        db.close()

    await manager.broadcast(sat_id, {
        "type": "tick", "satellite": sat_id, "orbit": ostate,
        "channels": results, "ts": now.isoformat(),
    })


async def _run_diagnosis(sat_id: str, channel_result: dict, event_id: int):
    narrative, source = await generate_diagnosis(channel_result)
    db = SessionLocal()
    try:
        db.add(Diagnosis(event_id=event_id, narrative=narrative, source=source))
        db.commit()
    finally:
        db.close()
    await manager.broadcast(sat_id, {
        "type": "diagnosis", "satellite": sat_id, "channel": channel_result["channel"],
        "narrative": narrative, "source": source, "event_id": event_id,
    })


async def loop():
    while True:
        for sat_id in list(sims.keys()):
            try:
                await _tick_satellite(sat_id)
            except Exception as e:
                print(f"[scheduler] tick error for {sat_id}: {e!r}")
        await asyncio.sleep(config.TICK_SECONDS)
