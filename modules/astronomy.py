"""Sunrise / sunset, twilight, moon phase for Ottawa."""

from datetime import date, datetime
import math

from astral import LocationInfo
from astral.sun import sun
from astral.moon import phase

from . import _common as C

OTTAWA = LocationInfo("Ottawa", "Canada", "America/Toronto", 45.4215, -75.6972)


def _phase_label(p):
    # astral.moon.phase returns 0..27.99
    if p < 1.84566:
        return "New moon", "()"
    if p < 5.53699:
        return "Waxing crescent", "()"
    if p < 9.22831:
        return "First quarter", "D"
    if p < 12.91963:
        return "Waxing gibbous", "(O"
    if p < 16.61096:
        return "Full moon", "O"
    if p < 20.30228:
        return "Waning gibbous", "O)"
    if p < 23.99361:
        return "Last quarter", "C"
    if p < 27.68493:
        return "Waning crescent", "/)"
    return "New moon", "()"


@C.safe_section("astronomy")
def render(printer):
    C.banner(printer, "Astronomy")
    today = date.today()
    s = sun(OTTAWA.observer, date=today, tzinfo=OTTAWA.timezone)
    p = phase(today)
    label, glyph = _phase_label(p)
    illum = (1 - math.cos(2 * math.pi * p / 29.530588)) / 2 * 100

    rows = [
        ("Dawn", s["dawn"].strftime("%H:%M")),
        ("Sunrise", s["sunrise"].strftime("%H:%M")),
        ("Noon", s["noon"].strftime("%H:%M")),
        ("Sunset", s["sunset"].strftime("%H:%M")),
        ("Dusk", s["dusk"].strftime("%H:%M")),
    ]
    daylight = (s["sunset"] - s["sunrise"]).total_seconds() / 3600.0
    printer.text(C.text_table(rows, widths=[10, 8]))
    printer.text(f"\nDaylight: {daylight:.2f} h\n")
    printer.text(f"Moon: {label} {glyph}\n")
    printer.text(f"Illumination: {illum:.0f}%\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "astronomy")
