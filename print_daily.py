"""Central daily report script. Imports every module under modules/ and
calls render(printer) in a fixed order.

Usage:
  python print_daily.py              # live print
  python print_daily.py --dry-run    # write out/daily-YYYY-MM-DD.bin instead
  python print_daily.py --only weather_ottawa,launches
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date

# ---- Printer connection (fill these in for your hardware) -------------------
# python-escpos supports Usb, Network, Serial, File, Dummy. Pick one and
# replace the constants below.
PRINTER_KIND = "usb"          # "usb" | "network" | "serial" | "file"
USB_VENDOR_ID = 0x0416        # TODO: your printer's USB vendor id
USB_PRODUCT_ID = 0x5011       # TODO: your printer's USB product id
USB_IN_EP = 0x81              # usually 0x81
USB_OUT_EP = 0x03             # usually 0x03
NETWORK_HOST = "192.168.1.50"
SERIAL_DEV = "/dev/serial0"
FILE_DEV = "/dev/usb/lp0"

# ---- Module run order -------------------------------------------------------
from modules import (
    global_news,
    military_news,
    space_news,
    weather_ottawa,
    weather_alerts,
    emergency_alerts,
    air_quality,
    transit_alerts,
    gas_prices,
    markets,
    launches,
    conjunctions,
    iss_passes,
    aurora_kp,
    earthquakes,
    astronomy,
    this_day_history,
    hacker_news,
    puzzles,
)

ORDER = [
    ("global_news",       global_news),
    ("military_news",     military_news),
    ("space_news",        space_news),
    ("weather_ottawa",    weather_ottawa),
    ("weather_alerts",    weather_alerts),
    ("emergency_alerts",  emergency_alerts),
    ("air_quality",       air_quality),
    ("transit_alerts",    transit_alerts),
    ("gas_prices",        gas_prices),
    ("markets",           markets),
    ("launches",          launches),
    ("conjunctions",      conjunctions),
    ("iss_passes",        iss_passes),
    ("aurora_kp",         aurora_kp),
    ("earthquakes",       earthquakes),
    ("astronomy",         astronomy),
    ("this_day_history",  this_day_history),
    ("hacker_news",       hacker_news),
    ("puzzles",           puzzles),
]


def _open_printer(dry_run):
    if dry_run:
        from escpos.printer import Dummy
        return Dummy()
    if PRINTER_KIND == "usb":
        from escpos.printer import Usb
        return Usb(USB_VENDOR_ID, USB_PRODUCT_ID,
                   in_ep=USB_IN_EP, out_ep=USB_OUT_EP)
    if PRINTER_KIND == "network":
        from escpos.printer import Network
        return Network(NETWORK_HOST)
    if PRINTER_KIND == "serial":
        from escpos.printer import Serial
        return Serial(devfile=SERIAL_DEV)
    if PRINTER_KIND == "file":
        from escpos.printer import File
        return File(FILE_DEV)
    raise ValueError(f"Unknown PRINTER_KIND: {PRINTER_KIND}")


def _intro(printer):
    printer.set(align="center", bold=True, double_height=True, double_width=True)
    printer.text("DAILY REPORT\n")
    printer.set(align="center", bold=False, double_height=False, double_width=False)
    printer.text(date.today().strftime("%A, %B %d, %Y") + "\n")
    printer.text("=" * 48 + "\n\n")
    printer.set(align="left")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Write to out/ instead of printing")
    ap.add_argument("--only", default="",
                    help="Comma-separated list of module names to run")
    args = ap.parse_args(argv)

    selected = [s.strip() for s in args.only.split(",") if s.strip()]
    sections = [(n, m) for n, m in ORDER if not selected or n in selected]

    printer = _open_printer(args.dry_run)

    try:
        _intro(printer)
        for name, mod in sections:
            try:
                mod.render(printer)
            except Exception as e:
                # Belt-and-suspenders: safe_section already handles this,
                # but if a module forgot the decorator we still don't crash.
                printer.text(f"[{name}] crashed in main loop: {e}\n")
                printer.text("-" * 48 + "\n\n")
        printer.cut()
    finally:
        if args.dry_run:
            os.makedirs("out", exist_ok=True)
            stamp = date.today().isoformat()
            with open(f"out/daily-{stamp}.bin", "wb") as f:
                f.write(printer.output)
            text_only = bytes(b for b in printer.output
                              if 32 <= b < 127 or b in (10, 13))
            with open(f"out/daily-{stamp}.txt", "wb") as f:
                f.write(text_only)
            print(f"wrote out/daily-{stamp}.bin "
                  f"({len(printer.output)} bytes) and out/daily-{stamp}.txt",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
