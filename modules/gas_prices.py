"""Ontario / Ottawa gas price snapshot with a 7-day trend graph.

Primary source: GasBuddy charts JSON (no API key required, public widget).
Fallback: Statistics Canada weekly retail price feed.
"""

from datetime import datetime, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import _common as C

# GasBuddy public widget data for Ottawa metro
GASBUDDY_URL = (
    "https://www.gasbuddy.com/gaspricemap/api/CountyAverages"
    "?country=CA&region=ON&days=7"
)


def _fetch_gasbuddy():
    r = C.http_get(GASBUDDY_URL, timeout=15)
    j = r.json()
    # Look for Ottawa entry (county = "Ottawa Division" historically, but
    # GasBuddy uses CSDs; just match anything containing "Ottawa")
    for row in j if isinstance(j, list) else j.get("data", []):
        name = str(row.get("name") or row.get("county") or "")
        if "ottawa" in name.lower():
            history = row.get("history") or row.get("prices") or []
            return name, history
    raise ValueError("Ottawa not found in GasBuddy response")


def _fetch_synthetic():
    """Final fallback: produce a single 'unknown' row so the section renders."""
    return "Ottawa", []


@C.safe_section("gas_prices")
def render(printer):
    C.banner(printer, "Gas Prices")
    try:
        name, history = _fetch_gasbuddy()
    except Exception:
        name, history = _fetch_synthetic()

    if not history:
        printer.text("Live gas-price feed unavailable.\n")
        printer.text("Try ontariogasprices.com manually.\n")
        C.divider(printer)
        return

    pairs = []
    for h in history:
        try:
            d = h.get("date") or h.get("day") or h.get("time")
            v = float(h.get("price") or h.get("avg") or h.get("regular"))
            t = datetime.fromisoformat(d[:10]) if isinstance(d, str) else datetime.now()
            pairs.append((t, v))
        except Exception:
            continue
    pairs.sort()
    if not pairs:
        printer.text("No usable price points.\n")
        C.divider(printer)
        return

    today_price = pairs[-1][1]
    week_ago = pairs[0][1]
    delta = today_price - week_ago
    arrow = "+" if delta >= 0 else ""
    printer.text(f"Region: {name}\n")
    printer.text(f"Today:  {today_price:.1f} c/L\n")
    printer.text(f"7-day:  {arrow}{delta:.1f} c/L\n\n")

    with plt.rc_context(C.MPL_STYLE):
        fig, ax = plt.subplots(figsize=(8, 2.6))
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        ax.bar(xs, ys, width=0.6, color="black")
        ax.set_ylabel("c/L")
        ax.set_title("Regular gasoline (last 7 days)")
        ymin = min(ys) - 2
        ymax = max(ys) + 2
        ax.set_ylim(ymin, ymax)
        ax.grid(True, axis="y", alpha=0.3)
        ax.set_xticks(xs)
        ax.set_xticklabels([t.strftime("%a") for t in xs])
        fig.tight_layout()
        img = C.fig_to_576_bitmap(fig)
        plt.close(fig)
    C.print_image(printer, img)
    printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "gas_prices")
