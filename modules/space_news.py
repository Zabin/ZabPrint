"""Top space-industry headlines from Spaceflight Now / SpaceNews."""

from . import _common as C

FEEDS = [
    "https://spaceflightnow.com/feed/",
    "https://spacenews.com/feed/",
]
TOP_N = 5


@C.safe_section("space_news")
def render(printer):
    C.banner(printer, "Space News")
    entries = []
    last_err = None
    for url in FEEDS:
        try:
            raw = C.http_get(url, timeout=10).content
            entries = C.parse_feed(raw, limit=TOP_N)
            if entries:
                break
        except Exception as e:
            last_err = e
    if not entries:
        if last_err:
            raise last_err
        printer.text("No space headlines available.\n")
        C.divider(printer)
        return
    for i, e in enumerate(entries, 1):
        printer.set(font="b", bold=True)
        printer.text(f"{i}. ")
        printer.set(font="b", bold=False)
        printer.text(C.wrap_lines(e["title"]))
        printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "space_news")
