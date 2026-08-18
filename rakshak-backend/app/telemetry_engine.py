"""
Per-satellite live simulation state.

Housekeeping telemetry (power draw, temperatures, attitude error, etc) for real
operational satellites isn't public for any agency — for the obvious reason that it's
sensitive operational data. So these five channels are generated, not fetched. What makes
this different from a generic demo: the solar power channel is modulated by the satellite's
REAL, currently-propagated eclipse state (see orbit.py) rather than an arbitrary sine wave -
so a satellite that's actually in Earth's shadow right now will show a real power dip here.

Detection thresholds, fault ramp shapes, and the thermal->power cascade timing were all
validated in a standalone simulation before being ported here (see project notes) - in
particular, catching a case where a slow-onset secondary effect could get silently absorbed
by the adaptive baseline instead of tripping an alert.
"""
import math
import random
import datetime
from . import orbit
from . import config
from .detection import Detector

CHANNELS = [
    {"id": "P-1", "label": "Solar Array Power", "unit": "W", "part": "panels"},
    {"id": "T-4", "label": "Battery Temperature", "unit": "\u00b0C", "part": "body"},
    {"id": "R-2", "label": "Radiation Flux", "unit": "mRad/s", "part": "sensor"},
    {"id": "A-3", "label": "Attitude Error", "unit": "\u00b0", "part": "jitter"},
    {"id": "C-1", "label": "Comms Signal", "unit": "dBm", "part": "antenna"},
]

INIT = {
    "P-1": (0.0, 81.0),   # residual after subtracting the known eclipse curve - see note below
    "T-4": (21.0, 0.16),
    "R-2": (2.1, 0.0625),
    "A-3": (0.05, 0.0004),
    "C-1": (-62.0, 2.0),
}

FAULT_DEFS = {
    "thermal":   {"channel": "T-4", "label": "Thermal Anomaly"},
    "power":     {"channel": "P-1", "label": "Power Degradation"},
    "attitude":  {"channel": "A-3", "label": "Attitude Drift"},
    "radiation": {"channel": "R-2", "label": "Radiation Spike"},
    "comms":     {"channel": "C-1", "label": "Comms Dropout"},
}


def clamp(x, a, b):
    return max(a, min(b, x))


def gaussian():
    return random.gauss(0, 1)


class SatelliteSim:
    def __init__(self, sat_config: dict):
        self.cfg = sat_config
        # P-1 (solar power) has a genuinely bimodal nominal range - full sun vs eclipse -
        # not just noise around one mean. Two earlier approaches were tried and rejected:
        # a single fixed-baseline detector missed real faults during eclipse (baseline
        # too far from the true night-time value), and a pair of day/night detectors
        # switched on a hard eclipse_factor>0.5 threshold still false-triggered at every
        # transition, because the actual value right at the terminator crossing matches
        # neither fixed mean. The fix: since the eclipse curve itself is fully known (we
        # compute eclipse_factor from real orbital geometry), subtract it from the raw
        # sample before detection ("seasonal decomposition"). The detector then only ever
        # sees the residual - small Gaussian noise plus whatever a real fault adds - with
        # a single stable near-zero baseline, regardless of orbital phase.
        self.detectors = {cid: Detector(*INIT[cid]) for cid in INIT}
        self.active_faults = {}     # fault_key -> elapsed seconds when injected
        self.cascade_timer = 0.0
        self.cascade_from_thermal = 0.0
        self.sim_start = datetime.datetime.now(datetime.timezone.utc)
        self._last_cascade_ts = 0.0

        self.tle_line1 = sat_config.get("tle_line1")
        self.tle_line2 = sat_config.get("tle_line2")
        self.tle_source = "cached_tle" if self.tle_line1 else "no_cached_tle"
        self._try_live_refresh()

    def _try_live_refresh(self):
        live = orbit.fetch_live_tle(self.cfg["norad_id"])
        if live:
            self.tle_line1, self.tle_line2 = live
            self.tle_source = "live"

    def elapsed_seconds(self) -> float:
        return (datetime.datetime.now(datetime.timezone.utc) - self.sim_start).total_seconds()

    def orbit_state(self) -> dict:
        real_now = datetime.datetime.now(datetime.timezone.utc)

        # Reported POSITION: always true real-time propagation, fully unaccelerated.
        if self.tle_line1 and self.tle_line2:
            state = orbit.propagate(self.tle_line1, self.tle_line2, when=real_now)
            if state is None:
                state = orbit.parametric_position(self.cfg["alt_km"], self.cfg["inclination_deg"], self.cfg["period_min"], when=real_now)
                state["source"] = "parametric_fallback_propagation_error"
            else:
                state["source"] = self.tle_source
        else:
            state = orbit.parametric_position(self.cfg["alt_km"], self.cfg["inclination_deg"], self.cfg["period_min"], when=real_now)
            state["source"] = "parametric_published_params"

        # Eclipse phase for TELEMETRY PACING only: a satellite's real eclipse cycle takes
        # ~90-100 real minutes to repeat - too slow to watch live in a demo. So this specific
        # signal comes from a separate idealized-orbit calc with the satellite's orbital phase
        # advanced on an accelerated clock (config.ORBIT_TIME_SCALE), while the sun's direction
        # stays on real time (it barely moves within a demo session, so real time is correct
        # there). This never touches the position fields above, which stay fully real.
        demo_when = self.sim_start + datetime.timedelta(seconds=self.elapsed_seconds() * config.ORBIT_TIME_SCALE)
        demo = orbit.parametric_position(self.cfg["alt_km"], self.cfg["inclination_deg"], self.cfg["period_min"],
                                          when=demo_when, epoch=self.sim_start, eclipse_when=real_now)
        state["eclipse_factor"] = demo["eclipse_factor"]
        state["eclipsed"] = demo["eclipsed"]
        state["time_scale"] = config.ORBIT_TIME_SCALE
        return state

    def inject_fault(self, key: str) -> bool:
        if key not in FAULT_DEFS or key in self.active_faults:
            return False
        self.active_faults[key] = self.elapsed_seconds()
        return True

    def clear_faults(self):
        self.active_faults = {}
        self.cascade_timer = 0.0
        self.cascade_from_thermal = 0.0

    def _fault_progress(self, key: str, ramp_s: float) -> float:
        if key not in self.active_faults:
            return 0.0
        return min(1.0, (self.elapsed_seconds() - self.active_faults[key]) / ramp_s)

    def _sample_p1(self, eclipse_factor: float):
        """Returns (raw_watts, residual, expected). `expected` is the known eclipse curve;
        `residual` = raw - expected is what the detector evaluates; `raw` is what gets
        displayed/stored as the channel's actual value."""
        expected = 640.0 - 600.0 * eclipse_factor
        fault_effect = 0.0
        if "power" in self.active_faults:
            fault_effect -= self._fault_progress("power", 30) * 480
        fault_effect -= self.cascade_from_thermal * 130
        raw = max(0.0, expected + gaussian() * 9 + fault_effect)
        residual = raw - expected
        return raw, residual, expected

    def _sample(self, channel_id: str, eclipse_factor: float) -> float:
        t = self.elapsed_seconds()
        if channel_id == "T-4":
            base = 21.0 + gaussian() * 0.4
            if "thermal" in self.active_faults:
                base += self._fault_progress("thermal", 25) * 38
            return base
        if channel_id == "R-2":
            base = 2.1 + gaussian() * 0.25
            if "radiation" in self.active_faults:
                dt = t - self.active_faults["radiation"]
                base += math.exp(-dt / 1.2) * 14
            return max(0.0, base)
        if channel_id == "A-3":
            base = 0.05 + abs(gaussian()) * 0.02
            if "attitude" in self.active_faults:
                base += self._fault_progress("attitude", 20) * 2.4
            return base
        if channel_id == "C-1":
            base = -62.0 + gaussian() * 1.4
            if "comms" in self.active_faults:
                dt = t - self.active_faults["comms"]
                base -= dt * 7 if dt < 6 else 42
            return base
        raise ValueError(channel_id)

    def tick(self):
        """Advance one step. Returns (channel_results: list[dict], orbit_state: dict)."""
        ostate = self.orbit_state()
        eclipse_factor = ostate.get("eclipse_factor", 0.0)

        now_s = self.elapsed_seconds()
        dt = max(0.0, min(5.0, now_s - self._last_cascade_ts))  # cap dt so a long pause can't jump-start the cascade
        self._last_cascade_ts = now_s

        t4_status = self.detectors["T-4"].status
        if t4_status == "anomaly":
            self.cascade_timer = min(60.0, self.cascade_timer + dt)
        else:
            self.cascade_timer = max(0.0, self.cascade_timer - dt * 2)
        self.cascade_from_thermal = clamp((self.cascade_timer - 8) / 4, 0.0, 1.0) if self.cascade_timer > 8 else 0.0

        results = []
        by_id = {c["id"]: c for c in CHANNELS}

        for cid in ("P-1", "T-4", "R-2", "A-3", "C-1"):
            det = self.detectors[cid]
            meta = by_id[cid]
            if cid == "P-1":
                raw, residual, expected = self._sample_p1(eclipse_factor)
                prev, status = det.update(residual)
                value = raw
                baseline_display = expected + det.base_mean  # reconstruct a watts-scale baseline for display
            else:
                value = self._sample(cid, eclipse_factor)
                prev, status = det.update(value)
                baseline_display = det.base_mean
            results.append({
                "channel": cid, "label": meta["label"], "unit": meta["unit"], "part": meta["part"],
                "value": value, "status": status, "prev_status": prev,
                "severity": det.severity, "z": det.ema_z,
                "baseline_mean": baseline_display, "baseline_std": math.sqrt(det.base_var),
            })
        return results, ostate
