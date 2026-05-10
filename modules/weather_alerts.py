"""Environment Canada weather alerts for Ottawa via the GeoMet OGC API."""

from . import _common as C

# OGC API Features endpoint for active alerts (free, no key)
ALERTS_API = "https://api.weather.gc.ca/collections/alerts-realtime/items"
OTTAWA_BBOX = "-76.0,45.2,-75.4,45.7"  # minlon,minlat,maxlon,maxlat


@C.safe_section("weather_alerts")
def render(printer):
    C.banner(printer, "Weather Alerts")
    params = {
        "bbox": OTTAWA_BBOX,
        "f": "json",
        "limit": 25,
    }
    data = C.http_get(ALERTS_API, params=params, timeout=15).json()
    features = data.get("features", []) or []

    # Filter to meteorological alerts only (alert_type or status active)
    weather = []
    for f in features:
        props = f.get("properties", {}) or {}
        alert_type = (props.get("alert_type") or props.get("type") or "").lower()
        if "test" in alert_type:
            continue
        weather.append(props)

    if not weather:
        printer.text("No active weather alerts for Ottawa.\n")
        C.divider(printer)
        return

    # Sort by severity if present
    severity_rank = {"extreme": 0, "severe": 1, "moderate": 2, "minor": 3}

    def rank(p):
        return severity_rank.get(str(p.get("severity", "")).lower(), 9)

    weather.sort(key=rank)

    for p in weather[:6]:
        headline = p.get("headline") or p.get("event") or "Alert"
        sev = p.get("severity", "")
        urgency = p.get("urgency", "")
        printer.set(bold=True)
        printer.text(f"* {headline}\n")
        printer.set(bold=False)
        meta = " / ".join(x for x in [sev, urgency] if x)
        if meta:
            printer.text(f"  {meta}\n")
        desc = p.get("description") or p.get("descrip_en") or ""
        if desc:
            printer.text(C.wrap_lines(str(desc)[:300]))
        printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "weather_alerts")
