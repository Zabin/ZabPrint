"""OC Transpo service alerts."""

from . import _common as C

FEEDS = [
    "https://www.octranspo.com/en/feeds/updates-en/",
    "https://www.octranspo.com/feeds/updates-en/",
]
TOP_N = 6


@C.safe_section("transit_alerts")
def render(printer):
    C.banner(printer, "OC Transpo")
    entries = []
    last_err = None
    fetched_ok = False
    for url in FEEDS:
        try:
            raw = C.http_get(url, timeout=10).content
            fetched_ok = True
            entries = C.parse_feed(raw, limit=TOP_N)
            if entries:
                break
        except Exception as e:
            last_err = e

    if not fetched_ok and last_err is not None:
        raise last_err

    if not entries:
        printer.text("No OC Transpo alerts.\n")
        C.divider(printer)
        return

    for i, e in enumerate(entries, 1):
        printer.set(font="b", bold=True)
        printer.text(f"{i}. ")
        printer.set(font="b", bold=False)
        printer.text(C.wrap_lines(e["title"]))
        if e["summary"]:
            printer.text(C.wrap_lines(e["summary"][:200]))
        printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "transit_alerts")
