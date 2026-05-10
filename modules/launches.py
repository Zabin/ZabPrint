"""Upcoming rocket launches from The Space Devs (free, no key)."""

from datetime import datetime

from . import _common as C

API = "https://ll.thespacedevs.com/2.2.0/launch/upcoming/?limit=5&mode=list"


@C.safe_section("launches")
def render(printer):
    C.banner(printer, "Upcoming Launches")
    data = C.http_get(API, timeout=15).json()
    results = data.get("results", []) or []
    if not results:
        printer.text("No upcoming launches in the window.\n")
        C.divider(printer)
        return

    for i, r in enumerate(results, 1):
        name = r.get("name", "(unknown)")
        net = r.get("net", "")
        try:
            t = datetime.fromisoformat(net.replace("Z", "+00:00"))
            when = t.strftime("%Y-%m-%d %H:%MZ")
        except Exception:
            when = net
        provider = (r.get("launch_service_provider") or {}).get("name", "")
        pad = (r.get("pad") or {}).get("name", "")
        loc = ((r.get("pad") or {}).get("location") or {}).get("name", "")

        printer.set(bold=True)
        printer.text(f"{i}. {name}\n")
        printer.set(bold=False)
        printer.text(f"   {when}\n")
        if provider:
            printer.text(f"   {provider}\n")
        if pad or loc:
            printer.text(C.wrap_lines(f"   {pad} - {loc}".strip(" -")))
        printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "launches")
