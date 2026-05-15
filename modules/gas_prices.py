"""Ottawa-area gas price snapshot + 7-day trend.

Primary: Statistics Canada vector 11214038 (avg retail gasoline, Ottawa-Gatineau).
Fallback: Stooq RBOB-gasoline futures (RB.F), 7-day daily.
"""

from datetime import datetime, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import _common as C

STATCAN_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"
OTTAWA_VECTOR_ID = 21581065  # 18-10-0001-01, Ottawa-Gatineau regular gasoline
STOOQ_RB = "https://stooq.com/q/d/l/?s=rb.f&i=d"


def _fetch_statcan(n=8):
    import requests
    payload = [{"vectorId": OTTAWA_VECTOR_ID, "latestN": n}]
    r = requests.post(STATCAN_URL, json=payload, timeout=15,
                      headers=C.DEFAULT_HEADERS)
    r.raise_for_status()
    body = r.json()
    if not body or body[0].get("status") != "SUCCESS":
        raise RuntimeError("StatCan returned non-SUCCESS")
    points = body[0]["object"]["vectorDataPoint"]
    pairs = []
    for pt in points:
        d = datetime.strptime(pt["refPer"], "%Y-%m-%d")
        v = float(pt["value"])
        pairs.append((d, v))
    pairs.sort()
    return "Ottawa-Gatineau (StatCan)", pairs, "c/L"


def _fetch_stooq_rbob():
    text = C.http_get(STOOQ_RB, timeout=15).text.strip().splitlines()
    if len(text) < 3:
        raise RuntimeError("No RBOB data")
    header = text[0].split(",")
    di = header.index("Date")
    ci = header.index("Close")
    pairs = []
    for line in text[1:]:
        parts = line.split(",")
        if len(parts) <= max(di, ci):
            continue
        try:
            d = datetime.strptime(parts[di], "%Y-%m-%d")
            c = float(parts[ci])
        except ValueError:
            continue
        pairs.append((d, c))
    return "RBOB gasoline future (USD/gal)", pairs[-14:], "USD/gal"


@C.safe_section("gas_prices")
def render(printer):
    C.banner(printer, "Gas Prices")
    label, pairs, unit = None, [], ""
    try:
        label, pairs, unit = _fetch_statcan(8)
    except Exception:
        pass
    if not pairs:
        label, pairs, unit = _fetch_stooq_rbob()
    if not pairs:
        printer.text("No gas-price data available.\n")
        C.divider(printer)
        return

    today_price = pairs[-1][1]
    week_ago = pairs[0][1]
    delta = today_price - week_ago
    arrow = "+" if delta >= 0 else ""
    printer.text(f"{label}\n")
    printer.text(f"Latest:  {today_price:.2f} {unit}\n")
    printer.text(f"7-day:   {arrow}{delta:.2f} {unit}\n\n")

    with plt.rc_context(C.MPL_STYLE):
        fig, ax = plt.subplots(figsize=(8, 2.6))
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        ax.bar(xs, ys, width=0.6, color="black")
        ax.set_ylabel(unit)
        ax.set_title(f"{label} - last {len(pairs)} pts")
        ymin = min(ys) * 0.97
        ymax = max(ys) * 1.03
        ax.set_ylim(ymin, ymax)
        ax.grid(True, axis="y", alpha=0.3)
        if len(xs) <= 10:
            ax.set_xticks(xs)
            ax.set_xticklabels([t.strftime("%m-%d") for t in xs], rotation=0)
        fig.tight_layout()
        img = C.fig_to_576_bitmap(fig)
        plt.close(fig)
    C.print_image(printer, img)
    printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "gas_prices")
