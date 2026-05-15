"""Three On-This-Day events from Wikipedia's free API."""

from datetime import date
import random

from . import _common as C

API = "https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{m:02d}/{d:02d}"


@C.safe_section("this_day_history")
def render(printer):
    C.banner(printer, "On This Day")
    today = date.today()
    url = API.format(m=today.month, d=today.day)
    data = C.http_get(url, timeout=15).json()
    events = data.get("events", []) or []
    if not events:
        printer.text("No events available.\n")
        C.divider(printer)
        return

    rng = random.Random(today.toordinal())
    sample = rng.sample(events, k=min(3, len(events)))
    sample.sort(key=lambda e: e.get("year", 0))
    for e in sample:
        year = e.get("year", "?")
        text = e.get("text", "").strip()
        printer.set(font="b", bold=True)
        printer.text(f"{year}: ")
        printer.set(font="b", bold=False)
        printer.text(C.wrap_lines(text))
        printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "this_day_history")
