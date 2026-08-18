"""
Orbital state for a satellite, in three tiers of "how real is this":

1. live       - fresh TLE fetched from CelesTrak's public gp.php API just now, propagated
                with the real SGP4 algorithm (via the `sgp4` library). Genuine current
                orbital state for a real object.
2. cached_tle - a bundled TLE snapshot (with its real epoch) used when live fetch fails
                (no internet, CelesTrak down, etc). Still real SGP4 propagation, just from
                a slightly stale element set. CelesTrak's own guidance is that TLEs for
                stable LEO orbits are good for days to weeks, so a cached snapshot from a
                past session is a reasonable, honest fallback for a demo.
3. parametric - no TLE available at all (e.g. SMAP, which we don't have a cached TLE for).
                Falls back to an idealized circular orbit built from that satellite's real,
                published mission parameters (altitude / inclination / period from the
                mission's own fact sheet). This is NOT a live position — it's a physically
                grounded approximation, and is always labeled as such in API responses via
                the "source" field so the frontend can be honest about it too.
"""
import math
import datetime
import httpx
from sgp4.api import Satrec, jday

CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php"
EARTH_RADIUS_KM = 6378.137


def clamp(x, a, b):
    return max(a, min(b, x))


def smoothstep(t):
    t = clamp(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def fetch_live_tle(norad_id: int, timeout: float = 5.0):
    """Try to fetch a fresh TLE from CelesTrak. Returns (line1, line2) or None on any failure
    (no internet, rate limited, satellite not found, etc). Never raises."""
    try:
        r = httpx.get(CELESTRAK_URL, params={"CATNR": norad_id, "FORMAT": "TLE"}, timeout=timeout)
        r.raise_for_status()
        lines = [l for l in r.text.strip().splitlines() if l.strip()]
        if len(lines) >= 3:
            return lines[-2], lines[-1]
        if len(lines) == 2:
            return lines[0], lines[1]
    except Exception:
        return None
    return None


def _sun_eci_approx(when: datetime.datetime):
    """Low-precision solar position (good to a fraction of a degree) - sufficient for
    eclipse timing on a health-monitoring demo, not for precision ops."""
    d = (when - datetime.datetime(2000, 1, 1, 12, tzinfo=datetime.timezone.utc)).total_seconds() / 86400.0
    g = math.radians((357.529 + 0.98560028 * d) % 360)
    q = math.radians((280.459 + 0.98564736 * d) % 360)
    L = q + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)
    e = math.radians(23.439 - 0.00000036 * d)
    dist_au = 1.00014 - 0.01671 * math.cos(g) - 0.00014 * math.cos(2 * g)
    au_km = 149597870.7
    x = math.cos(L) * dist_au * au_km
    y = math.cos(e) * math.sin(L) * dist_au * au_km
    z = math.sin(e) * math.sin(L) * dist_au * au_km
    return x, y, z


def _eclipse_factor(x, y, z, when):
    """Continuous 0 (fully sunlit) -> 1 (fully eclipsed) with a smoothed transition band
    around the terminator, so telemetry driven by this doesn't step discontinuously
    (a hard boolean here previously caused false anomaly triggers during eclipse entry/exit)."""
    sx, sy, sz = _sun_eci_approx(when)
    n = math.sqrt(sx * sx + sy * sy + sz * sz)
    sun_dir = (sx / n, sy / n, sz / n)
    dot = x * sun_dir[0] + y * sun_dir[1] + z * sun_dir[2]
    if dot > 0:
        return 0.0
    perp_dist = math.sqrt(max(0.0, x * x + y * y + z * z - dot * dot))
    band = 150.0  # km, approximates the penumbra transition
    t = (EARTH_RADIUS_KM + band - perp_dist) / (2 * band)
    return smoothstep(t)


def propagate(tle_line1: str, tle_line2: str, when: datetime.datetime = None,
              eclipse_when: datetime.datetime = None):
    """Real SGP4 propagation. `when` drives the actual reported position (always real time).
    `eclipse_when` (defaults to `when`) drives only the eclipse-factor calculation, so callers
    can pass an accelerated clock for demo pacing without faking the satellite's real position.
    Returns a state dict, or None if SGP4 reports an error (e.g. decayed orbit, malformed TLE)."""
    when = when or datetime.datetime.now(datetime.timezone.utc)
    eclipse_when = eclipse_when or when
    sat = Satrec.twoline2rv(tle_line1, tle_line2)
    jd, fr = jday(when.year, when.month, when.day, when.hour, when.minute, when.second + when.microsecond / 1e6)
    err, r, v = sat.sgp4(jd, fr)
    if err != 0:
        return None
    x, y, z = r
    dist = math.sqrt(x * x + y * y + z * z)
    alt_km = dist - EARTH_RADIUS_KM
    lat = math.degrees(math.asin(clamp(z / dist, -1, 1)))
    lon = math.degrees(math.atan2(y, x))
    ef = _eclipse_factor(x, y, z, eclipse_when)
    return {
        "lat": lat, "lon": lon, "alt_km": alt_km,
        "x": x, "y": y, "z": z,
        "eclipse_factor": ef, "eclipsed": ef > 0.5,
    }


def parametric_position(alt_km: float, inclination_deg: float, period_min: float,
                         when: datetime.datetime = None, epoch: datetime.datetime = None,
                         eclipse_when: datetime.datetime = None):
    """Idealized circular orbit from published mission parameters. Explicitly not a live TLE.
    `eclipse_when` behaves as in propagate() above."""
    when = when or datetime.datetime.now(datetime.timezone.utc)
    eclipse_when = eclipse_when or when
    epoch = epoch or when.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_s = (when - epoch).total_seconds()
    period_s = period_min * 60
    angle = (elapsed_s % period_s) / period_s * 2 * math.pi
    r = EARTH_RADIUS_KM + alt_km
    inc = math.radians(inclination_deg)
    x = r * math.cos(angle)
    y = -r * math.sin(angle) * math.sin(inc)
    z = r * math.sin(angle) * math.cos(inc)
    lat = math.degrees(math.asin(clamp(z / r, -1, 1)))
    lon = math.degrees(math.atan2(y, x))
    ef = _eclipse_factor(x, y, z, eclipse_when)
    return {
        "lat": lat, "lon": lon, "alt_km": alt_km,
        "x": x, "y": y, "z": z,
        "eclipse_factor": ef, "eclipsed": ef > 0.5,
    }
