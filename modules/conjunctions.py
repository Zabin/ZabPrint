"""Conjunction Data Messages from space-track.org for the past 24h."""

from datetime import datetime, timedelta, timezone

import requests

from . import _common as C

# Hardcoded credentials. Fill these in on the Pi.
SPACETRACK_USER = ""  # TODO: e.g. "you@example.com"
SPACETRACK_PASS = ""  # TODO

LOGIN_URL = "https://www.space-track.org/ajaxauth/login"
QUERY_URL_TMPL = (
    "https://www.space-track.org/basicspacedata/query/class/cdm_public"
    "/CREATION_DATE/>{since}/orderby/TCA%20asc/format/json"
)


@C.safe_section("conjunctions")
def render(printer):
    C.banner(printer, "Conjunctions")
    if not SPACETRACK_USER or not SPACETRACK_PASS:
        printer.text("space-track credentials not set.\n"
                     "Edit modules/conjunctions.py to enable.\n")
        C.divider(printer)
        return

    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    with requests.Session() as s:
        s.headers.update({"User-Agent": C.USER_AGENT})
        r = s.post(
            LOGIN_URL,
            data={"identity": SPACETRACK_USER, "password": SPACETRACK_PASS},
            timeout=15,
        )
        r.raise_for_status()
        url = QUERY_URL_TMPL.format(since=since)
        r = s.get(url, timeout=20)
        r.raise_for_status()
        cdms = r.json()

    if not cdms:
        printer.text("No CDMs in the past 24h.\n")
        C.divider(printer)
        return

    # Sort by miss distance ascending
    def miss_km(c):
        try:
            return float(c.get("MISS_DISTANCE", "1e9"))
        except (TypeError, ValueError):
            return 1e9

    cdms.sort(key=miss_km)
    rows = []
    for c in cdms[:8]:
        sat = (c.get("SAT_1_NAME") or c.get("SAT1_NAME") or "?")[:14]
        partner = (c.get("SAT_2_NAME") or c.get("SAT2_NAME") or "?")[:14]
        tca = (c.get("TCA") or "")[:16].replace("T", " ")
        miss = miss_km(c)
        pc = c.get("PC", "")
        try:
            pc_str = f"{float(pc):.1e}" if pc not in (None, "") else "-"
        except ValueError:
            pc_str = str(pc)[:7]
        rows.append((sat, partner, tca[5:], f"{miss:.2f}", pc_str))

    table = C.text_table(
        rows,
        widths=[14, 14, 11, 6, 7],
        header=("Sat 1", "Sat 2", "TCA(UTC)", "km", "Pc"),
    )
    printer.text(table)
    printer.text(f"\n{len(cdms)} CDM(s) total in last 24h.\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "conjunctions")
