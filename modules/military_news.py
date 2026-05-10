"""Top military / defense headlines."""

import feedparser

from . import _common as C

FEEDS = [
    "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
    "https://breakingdefense.com/feed/",
]
TOP_N = 5


@C.safe_section("military_news")
def render(printer):
    C.banner(printer, "Defense News")
    entries = []
    last_err = None
    for url in FEEDS:
        try:
            raw = C.http_get(url, timeout=10).content
            feed = feedparser.parse(raw)
            if feed.entries:
                entries = feed.entries
                break
        except Exception as e:
            last_err = e
    if not entries:
        if last_err:
            raise last_err
        printer.text("No defense headlines available.\n")
        C.divider(printer)
        return
    for i, entry in enumerate(entries[:TOP_N], 1):
        title = entry.get("title", "(untitled)").strip()
        printer.set(bold=True)
        printer.text(f"{i}. ")
        printer.set(bold=False)
        printer.text(C.wrap_lines(title))
        printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "military_news")
