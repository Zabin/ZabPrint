"""Notable earthquakes: significant worldwide + nearby Ottawa (last 24h)."""

import math

from . import _common as C

SIGNIFICANT = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_day.geojson"
NEARBY = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"

OTTAWA = (45.4215, -75.6972)
NEARBY_RADIUS_KM = 500.0


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


@C.safe_section("earthquakes")
def render(printer):
    C.banner(printer, "Earthquakes")

    # Significant worldwide
    try:
        big = C.http_get(SIGNIFICANT, timeout=10).json().get("features", []) or []
    except Exception:
        big = []

    printer.set(font="b", bold=True)
    printer.text("Significant (24h):\n")
    printer.set(font="b", bold=False)
    if not big:
        printer.text("  None reported.\n")
    else:
        for f in big[:5]:
            p = f.get("properties", {}) or {}
            mag = p.get("mag", "?")
            place = p.get("place", "")
            printer.text(C.wrap_lines(f"  M{mag} {place}"))

    printer.text("\n")
    printer.set(font="b", bold=True)
    printer.text(f"Within {int(NEARBY_RADIUS_KM)} km of Ottawa:\n")
    printer.set(font="b", bold=False)
    try:
        feats = C.http_get(NEARBY, timeout=10).json().get("features", []) or []
    except Exception:
        feats = []

    nearby = []
    for f in feats:
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        d = _haversine(OTTAWA[0], OTTAWA[1], lat, lon)
        if d <= NEARBY_RADIUS_KM:
            p = f.get("properties", {}) or {}
            nearby.append((d, p.get("mag", "?"), p.get("place", "")))
    nearby.sort()
    if not nearby:
        printer.text("  None.\n")
    else:
        for d, m, place in nearby[:5]:
            printer.text(C.wrap_lines(f"  M{m} {place} ({d:.0f} km)"))
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "earthquakes")
