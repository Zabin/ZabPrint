"""OC Transpo service alerts."""

import feedparser

from . import _common as C

# OC Transpo publishes service updates as an RSS feed
FEEDS = [
    "https://www.octranspo.com/en/feeds/updates-en/",
    "https://www.octranspo.com/feeds/updates-en/",
]
TOP_N = 6


@C.safe_section("transit_alerts")
def render(printer):
    C.banner(printer, "OC Transpo")
    entries = []
    for url in FEEDS:
        try:
            raw = C.http_get(url, timeout=10).content
            feed = feedparser.parse(raw)
            if feed.entries:
                entries = feed.entries
                break
        except Exception:
            continue

    if not entries:
        printer.text("No OC Transpo alerts.\n")
        C.divider(printer)
        return

    for i, e in enumerate(entries[:TOP_N], 1):
        title = e.get("title", "(untitled)").strip()
        printer.set(bold=True)
        printer.text(f"{i}. ")
        printer.set(bold=False)
        printer.text(C.wrap_lines(title))
        summary = e.get("summary", "").strip()
        if summary:
            summary = summary.replace("<p>", "").replace("</p>", " ")
            summary = summary.split("<")[0]
            if summary:
                printer.text(C.wrap_lines(summary[:200]))
        printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "transit_alerts")
