"""Alert Ready / public-safety broadcast intrusions for Ontario.

Pulls the National Alert Aggregation & Dissemination (NAAD) public mirror
from a community feed and filters to Ontario, non-meteorological events.
"""

import xml.etree.ElementTree as ET

from . import _common as C

# Public CAP archive mirror used by Alert Ready monitors
NAAD_FEED = "https://capcp1.naad-adna.pelmorex.com/active.xml"
NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}


@C.safe_section("emergency_alerts")
def render(printer):
    C.banner(printer, "Emergency Alerts")
    try:
        raw = C.http_get(NAAD_FEED, timeout=15).content
        root = ET.fromstring(raw)
    except Exception:
        # Fallback: weather.gc.ca general alerts feed
        raw = C.http_get(
            "https://api.weather.gc.ca/collections/alerts-realtime/items"
            "?bbox=-95,42,-74,57&f=json&limit=50",
            timeout=15,
        ).json()
        feats = raw.get("features", []) or []
        nonmet = []
        for f in feats:
            p = f.get("properties", {}) or {}
            cat = str(p.get("category", "")).lower()
            evt = str(p.get("event", "")).lower()
            if cat in ("safety", "security", "rescue", "fire", "health",
                       "env", "transport", "infra"):
                nonmet.append(p)
            elif "amber" in evt or "civil" in evt or "evac" in evt:
                nonmet.append(p)
        if not nonmet:
            printer.text("No active public-safety alerts in Ontario.\n")
            C.divider(printer)
            return
        for p in nonmet[:6]:
            headline = p.get("headline") or p.get("event") or "Alert"
            printer.set(bold=True)
            printer.text(f"* {headline}\n")
            printer.set(bold=False)
            desc = p.get("description") or ""
            if desc:
                printer.text(C.wrap_lines(str(desc)[:300]))
            printer.text("\n")
        C.divider(printer)
        return

    alerts = []
    for alert in root.iter():
        if not alert.tag.endswith("}alert"):
            continue
        info = alert.find("cap:info", NS)
        if info is None:
            continue
        category = (info.findtext("cap:category", default="", namespaces=NS) or "").lower()
        event = info.findtext("cap:event", default="", namespaces=NS) or ""
        headline = info.findtext("cap:headline", default="", namespaces=NS) or event
        severity = info.findtext("cap:severity", default="", namespaces=NS) or ""
        desc = info.findtext("cap:description", default="", namespaces=NS) or ""
        # Geographic filter to Ontario
        in_ontario = False
        for area in info.findall("cap:area", NS):
            desc_area = (area.findtext("cap:areaDesc", default="", namespaces=NS) or "").lower()
            if "ontario" in desc_area or "on" in desc_area.split(",")[-1:]:
                in_ontario = True
                break
        if not in_ontario:
            continue
        if category in ("met",):
            # Skip purely meteorological; weather_alerts module handles those
            continue
        alerts.append((severity, headline, desc))

    if not alerts:
        printer.text("No active public-safety alerts in Ontario.\n")
        C.divider(printer)
        return

    sev_rank = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}
    alerts.sort(key=lambda a: sev_rank.get(a[0], 9))
    for severity, headline, desc in alerts[:6]:
        printer.set(bold=True)
        printer.text(f"* {headline}\n")
        printer.set(bold=False)
        if severity:
            printer.text(f"  Severity: {severity}\n")
        if desc:
            printer.text(C.wrap_lines(desc[:300]))
        printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "emergency_alerts")
