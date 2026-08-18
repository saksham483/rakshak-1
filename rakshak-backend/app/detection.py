"""
Adaptive EWMA baseline anomaly detector.

Method: maintain a slow-moving mean/variance estimate of a channel's nominal behaviour.
While the channel reads as nominal, the baseline keeps adapting (with outlier-clipped
updates so a single spike can't distort it). The moment the smoothed z-score crosses
the anomaly threshold, the baseline FREEZES — this is what lets a slow, sustained ramp
(like a thermal runaway) stay flagged for its full duration instead of the detector
quietly "learning" the fault as the new normal.

Thresholds and update rule were validated in a standalone simulation (see project notes)
against two failure modes this kind of naive online detector is prone to: a hysteresis
bug that freezes status permanently, and a runaway-variance feedback loop that lets a
slow ramp evade detection entirely. Both are guarded against here.

Inspired by NASA JPL's Telemanom dynamic-thresholding approach for the SMAP/MSL spacecraft
anomaly benchmark (Hundman et al., 2018) — this is a lightweight statistical reimplementation,
not the original LSTM forecaster.
"""
import math


def clamp(x, a, b):
    return max(a, min(b, x))


class Detector:
    ANOMALY_Z = 3.4
    WATCH_Z = 2.0
    ALPHA = 0.05
    EMA_SMOOTH = 0.35

    def __init__(self, base_mean: float, base_var: float, warmup: int = 6):
        self.base_mean = base_mean
        self.base_var = max(base_var, 1e-6)
        self.ema_z = 0.0
        self.status = "nominal"
        self.severity = 0
        self._pending_raw = "nominal"
        self._pending_count = 1
        self._initialized = False
        self._warmup_remaining = warmup

    def update(self, value: float):
        """Feed one new sample. Returns (previous_status, new_status).

        The first few samples calibrate the baseline to wherever the channel actually
        starts (fast-adapting, no anomaly evaluation) rather than assuming the caller's
        initial guess was exactly right - a satellite can just as easily start a session
        mid-eclipse as not, and without this a starting condition the hardcoded initial
        baseline didn't anticipate would instantly read as a huge false anomaly."""
        if self._warmup_remaining > 0:
            self._warmup_remaining -= 1
            diff = value - self.base_mean
            self.base_mean += 0.3 * diff
            self.base_var = max(1e-6, 0.7 * self.base_var + 0.3 * diff * diff)
            self.ema_z = 0.0
            prev = self.status
            self.status = "nominal"
            self.severity = 0
            return prev, self.status

        std = math.sqrt(self.base_var) or 1e-4
        diff = value - self.base_mean
        z = diff / std
        self.ema_z = z if not self._initialized else (self.EMA_SMOOTH * z + (1 - self.EMA_SMOOTH) * self.ema_z)
        self._initialized = True

        abs_z = abs(self.ema_z)
        raw = "anomaly" if abs_z > self.ANOMALY_Z else "watch" if abs_z > self.WATCH_Z else "nominal"

        if self._pending_raw == raw:
            self._pending_count += 1
        else:
            self._pending_raw = raw
            self._pending_count = 1

        prev = self.status
        if self._pending_count >= 2:
            self.status = raw

        if self.status == "nominal":
            clipped = clamp(diff, -3 * std, 3 * std)
            self.base_mean += self.ALPHA * clipped
            self.base_var = (1 - self.ALPHA) * self.base_var + self.ALPHA * clipped * clipped

        self.severity = int(clamp(round(((abs_z - self.WATCH_Z) / 4.0) * 100), 0, 100))
        return prev, self.status
