"""Ottawa AQHI (Air Quality Health Index) from Environment Canada GeoMet."""

from . import _common as C

COLLECTION_IDS = [
    "aqhi-observations-realtime",
    "aqhi-realtime",
]
API_TMPL = "https://api.weather.gc.ca/collections/{cid}/items"
PARAMS = {
    "f": "json",
    "limit": 5,
    "sortby": "-observation_datetime",
    "bbox": "-76.0,45.2,-75.4,45.7",
}

RISK_BANDS = [
    (3, "Low risk"),
    (6, "Moderate risk"),
    (10, "High risk"),
    (10**9, "Very high risk"),
]


@C.safe_section("air_quality")
def render(printer):
    C.banner(printer, "Air Quality (AQHI)")
    data = None
    last_err = None
    for cid in COLLECTION_IDS:
        try:
            data = C.http_get(API_TMPL.format(cid=cid),
                              params=PARAMS, timeout=15).json()
            break
        except Exception as e:
            last_err = e
    if data is None:
        raise last_err if last_err else RuntimeError("No AQHI API responded")
    feats = data.get("features") or []
    if not feats:
        printer.text("No AQHI observations near Ottawa.\n")
        C.divider(printer)
        return

    # Pick the most recent feature
    best = feats[0]
    p = best.get("properties", {}) or {}
    aqhi = p.get("aqhi")
    station = p.get("location_name_en") or p.get("station_name") or "Ottawa"
    obs_time = p.get("observation_datetime") or ""
    band = "?"
    if aqhi is not None:
        for thresh, label in RISK_BANDS:
            if aqhi <= thresh:
                band = label
                break

    printer.set(font="b", bold=True, double_height=True)
    printer.text(f"AQHI {aqhi if aqhi is not None else '-'}\n")
    printer.set(font="b", bold=False, double_height=False)
    printer.text(f"{band}\n")
    printer.text(f"Station: {station}\n")
    if obs_time:
        printer.text(f"Obs: {obs_time[:16].replace('T', ' ')}Z\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "air_quality")
