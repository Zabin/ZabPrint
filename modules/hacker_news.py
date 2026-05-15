"""Top 5 Hacker News stories via the Firebase API."""

from . import _common as C

TOPSTORIES = "https://hacker-news.firebaseio.com/v0/topstories.json"
ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
TOP_N = 5


@C.safe_section("hacker_news")
def render(printer):
    C.banner(printer, "Hacker News")
    ids = C.http_get(TOPSTORIES, timeout=10).json()[:TOP_N]
    for i, item_id in enumerate(ids, 1):
        try:
            it = C.http_get(ITEM.format(id=item_id), timeout=8).json() or {}
        except Exception:
            continue
        title = it.get("title", "(untitled)")
        score = it.get("score", 0)
        comments = it.get("descendants", 0)
        printer.set(font="b", bold=True)
        printer.text(f"{i}. ")
        printer.set(font="b", bold=False)
        printer.text(C.wrap_lines(title))
        printer.text(f"   {score} pts / {comments} cmts\n\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "hacker_news")
