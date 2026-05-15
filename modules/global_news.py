"""Top global headlines from BBC World."""

from . import _common as C

FEED_URL = "http://feeds.bbci.co.uk/news/world/rss.xml"
TOP_N = 5


@C.safe_section("global_news")
def render(printer):
    C.banner(printer, "World News")
    raw = C.http_get(FEED_URL, timeout=10).content
    entries = C.parse_feed(raw, limit=TOP_N)
    if not entries:
        printer.text("No headlines available.\n")
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
    C.standalone_dummy_run(render, "global_news")
