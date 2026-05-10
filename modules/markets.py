"""Market summary: TSX, S&P 500, CAD/USD, BTC-CAD as a 4-panel 7-day chart."""

from datetime import datetime, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import _common as C

# Stooq is a free CSV source that doesn't need yfinance/Yahoo flakiness.
SYMBOLS = [
    ("S&P 500", "^spx"),
    ("TSX", "^tsx"),
    ("CAD/USD", "cadusd"),
    ("BTC-CAD", "btccad"),
]


def _fetch_stooq(sym):
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    text = C.http_get(url, timeout=15).text.strip().splitlines()
    if len(text) < 3:
        raise ValueError(f"No data for {sym}")
    header = text[0].split(",")
    di = header.index("Date")
    ci = header.index("Close")
    out = []
    for line in text[1:]:
        parts = line.split(",")
        if len(parts) <= max(di, ci):
            continue
        try:
            d = datetime.strptime(parts[di], "%Y-%m-%d")
            c = float(parts[ci])
        except ValueError:
            continue
        out.append((d, c))
    return out[-30:]  # last ~30 trading days


@C.safe_section("markets")
def render(printer):
    C.banner(printer, "Markets")

    series = []
    for label, sym in SYMBOLS:
        try:
            data = _fetch_stooq(sym)
            if data:
                series.append((label, data))
        except Exception as e:
            series.append((label, [(datetime.now(), float("nan"))]))

    # Text summary first
    rows = []
    for label, pts in series:
        if not pts or any(p != p for _, p in pts[-1:]):  # NaN
            rows.append((label, "n/a", "n/a"))
            continue
        last = pts[-1][1]
        # 7-day-ish: 5 trading days back
        prev = pts[-6][1] if len(pts) >= 6 else pts[0][1]
        chg = (last - prev) / prev * 100 if prev else 0.0
        rows.append((label, f"{last:.2f}", f"{chg:+.2f}%"))

    table = C.text_table(
        rows,
        widths=[10, 14, 10],
        header=("Symbol", "Last", "7d%"),
    )
    printer.text(table)
    printer.text("\n")

    # 2x2 grid of last-7-day mini-charts
    with plt.rc_context(C.MPL_STYLE):
        fig, axes = plt.subplots(2, 2, figsize=(8, 4.5))
        for ax, (label, pts) in zip(axes.flat, series):
            if not pts or any(p != p for _, p in pts):
                ax.text(0.5, 0.5, "n/a", ha="center", va="center",
                        transform=ax.transAxes)
                ax.set_title(label)
                ax.set_xticks([])
                ax.set_yticks([])
                continue
            last7 = pts[-7:]
            xs = [p[0] for p in last7]
            ys = [p[1] for p in last7]
            ax.plot(xs, ys, color="black", marker="o", markersize=3)
            ax.set_title(f"{label}  {ys[-1]:.2f}")
            ax.set_xticks([xs[0], xs[-1]])
            ax.set_xticklabels([xs[0].strftime("%m-%d"),
                                xs[-1].strftime("%m-%d")])
            ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()
        img = C.fig_to_576_bitmap(fig)
        plt.close(fig)
    C.print_image(printer, img)
    printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "markets")
