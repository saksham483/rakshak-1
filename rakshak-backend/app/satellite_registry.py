"""
Curated set of real satellites the console can monitor. Each entry's orbital parameters
are real published figures. Where we have a cached TLE snapshot, it's a real element set
(verified against the actual `sgp4` propagator — see project notes) with its true epoch,
used only as a fallback when a live CelesTrak fetch isn't available. Live fetch is always
attempted first (see orbit.fetch_live_tle).
"""

SATELLITES = {
    "iss": dict(
        id="iss", name="ISS (ZARYA)", norad_id=25544, operator="NASA / Roscosmos / ESA / JAXA / CSA",
        tle_line1="1 25544U 98067A   26214.50635181  .00006342  00000-0  12183-3 0  9997",
        tle_line2="2 25544  51.6315  70.8679 0007172   4.7554 355.3502 15.49313226578933",
        tle_epoch="2026-08-02",
        alt_km=420, inclination_deg=51.64, period_min=92.68,
        note="Well-known LEO station orbit; widely used as a TLE reference case.",
    ),
    "cartosat3": dict(
        id="cartosat3", name="CARTOSAT-3", norad_id=44804, operator="ISRO",
        tle_line1="1 44804U 19081A   26111.58047706  .00006517  00000-0  31176-3 0  9997",
        tle_line2="2 44804  97.4340 174.3434 0011694 355.7664   4.3470 15.19259691354875",
        tle_epoch="2026-04-21",
        alt_km=509, inclination_deg=97.45, period_min=95.0,
        note="ISRO sun-synchronous Earth observation satellite, launched 2019.",
    ),
    "smap": dict(
        id="smap", name="SMAP (Soil Moisture Active Passive)", norad_id=40376, operator="NASA / JPL",
        tle_line1=None, tle_line2=None, tle_epoch=None,
        alt_km=685, inclination_deg=98.12, period_min=98.46,
        note="No cached TLE bundled — position uses the parametric fallback from SMAP's "
             "published mission orbit unless a live CelesTrak fetch succeeds. This is the "
             "same spacecraft the NASA SMAP/MSL anomaly benchmark dataset comes from "
             "(see /api/replay).",
    ),
}
