"""Top global headlines from BBC World."""

import feedparser

from . import _common as C

FEED_URL = "http://feeds.bbci.co.uk/news/world/rss.xml"
TOP_N = 5


@C.safe_section("global_news")
def render(printer):
    C.banner(printer, "World News")
    raw = C.http_get(FEED_URL, timeout=10).content
    feed = feedparser.parse(raw)
    if not feed.entries:
        printer.text("No headlines available.\n")
        C.divider(printer)
        return
    for i, entry in enumerate(feed.entries[:TOP_N], 1):
        title = entry.get("title", "(untitled)").strip()
        printer.set(bold=True)
        printer.text(f"{i}. ")
        printer.set(bold=False)
        printer.text(C.wrap_lines(title))
        summary = entry.get("summary", "").strip()
        if summary:
            # Strip rudimentary HTML
            summary = summary.replace("<p>", "").replace("</p>", " ")
            summary = summary.split("<")[0]
            if summary:
                printer.text(C.wrap_lines(summary[:200]))
        printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "global_news")
