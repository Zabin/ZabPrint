"""NOAA SWPC planetary K-index 7-day bar graph + outlook."""

from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import _common as C

KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"


@C.safe_section("aurora_kp")
def render(printer):
    C.banner(printer, "Aurora / Kp Index")
    rows = C.http_get(KP_URL, timeout=15).json()
    # First row is the header
    header, *data = rows
    # columns: time_tag, Kp, a_running, station_count
    idx_time = header.index("time_tag")
    idx_kp = header.index("Kp")

    # Take last ~7 days of 3-hour values
    recent = data[-7 * 8:]
    times = []
    kps = []
    for r in recent:
        try:
            t = datetime.fromisoformat(r[idx_time].replace("Z", ""))
            kp = float(r[idx_kp])
        except Exception:
            continue
        times.append(t)
        kps.append(kp)

    if not kps:
        printer.text("No Kp data available.\n")
        C.divider(printer)
        return

    current = kps[-1]
    peak = max(kps)
    storm_label = (
        "G5 extreme" if peak >= 9 else
        "G4 severe" if peak >= 8 else
        "G3 strong" if peak >= 7 else
        "G2 moderate" if peak >= 6 else
        "G1 minor" if peak >= 5 else
        "Quiet"
    )
    printer.text(f"Current Kp: {current:.1f}\n")
    printer.text(f"7-day peak: {peak:.1f} ({storm_label})\n\n")

    with plt.rc_context(C.MPL_STYLE):
        fig, ax = plt.subplots(figsize=(8, 3.0))
        colors = ["black" if k < 5 else "#202020" for k in kps]
        ax.bar(times, kps, width=0.12, color=colors)
        ax.axhline(5, color="black", linestyle="--", linewidth=1.2,
                   label="G1 storm")
        ax.set_ylabel("Kp")
        ax.set_title("Planetary K-index (last 7 days)")
        ax.set_ylim(0, 9)
        ax.grid(True, axis="y", alpha=0.3)
        ax.legend(loc="upper left")
        fig.autofmt_xdate(rotation=0, ha="center")
        fig.tight_layout()
        img = C.fig_to_576_bitmap(fig)
        plt.close(fig)
    C.print_image(printer, img)
    printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "aurora_kp")
