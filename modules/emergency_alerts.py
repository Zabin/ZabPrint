"""Non-weather public-safety alerts for Ontario.

Pulls all active alerts from MSC GeoMet for Ontario, then filters out the
meteorological category (which `weather_alerts` already covers).
"""

from . import _common as C

COLLECTION_IDS = ["alerts-realtime", "alerts"]
API_TMPL = "https://api.weather.gc.ca/collections/{cid}/items"
ONTARIO_BBOX = "-95,42,-74,57"


@C.safe_section("emergency_alerts")
def render(printer):
    C.banner(printer, "Emergency Alerts")
    data = None
    last_err = None
    for cid in COLLECTION_IDS:
        try:
            data = C.http_get(
                API_TMPL.format(cid=cid),
                params={"bbox": ONTARIO_BBOX, "f": "json", "limit": 50},
                timeout=15,
            ).json()
            break
        except Exception as e:
            last_err = e
    if data is None:
        raise last_err if last_err else RuntimeError("No alerts API responded")

    feats = data.get("features", []) or []
    nonmet = []
    for f in feats:
        p = f.get("properties", {}) or {}
        cat = str(p.get("category", "")).lower()
        evt = str(p.get("event", "")).lower()
        if cat in ("safety", "security", "rescue", "fire", "health",
                   "env", "transport", "infra"):
            nonmet.append(p)
        elif "amber" in evt or "civil" in evt or "evac" in evt or "test" in evt:
            nonmet.append(p)

    if not nonmet:
        printer.text("No active public-safety alerts in Ontario.\n")
        C.divider(printer)
        return

    for p in nonmet[:6]:
        headline = p.get("headline") or p.get("event") or "Alert"
        printer.set(font="b", bold=True)
        printer.text(f"* {headline}\n")
        printer.set(font="b", bold=False)
        desc = p.get("description") or ""
        if desc:
            printer.text(C.wrap_lines(str(desc)[:300]))
        printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "emergency_alerts")
