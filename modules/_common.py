"""Shared helpers for daily thermal-report modules.

Print width is 576 px / 48 chars at the standard ESC/POS font on an 80mm head.
Every module is expected to define render(printer) and wrap its body in
@safe_section so any failure ends up printed on the receipt instead of
crashing the whole report.
"""

from __future__ import annotations

import functools
import io
import textwrap
import time
import traceback
from datetime import datetime

import requests
from PIL import Image

PRINT_WIDTH_PX = 576
PRINT_WIDTH_CHARS = 48
USER_AGENT = "ZabPrint/1.0 (+raspberrypi thermal daily report)"

MPL_STYLE = {
    "font.size": 11,
    "axes.linewidth": 1.5,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "lines.linewidth": 2.5,
    "xtick.major.width": 1.5,
    "ytick.major.width": 1.5,
    "xtick.major.size": 5,
    "ytick.major.size": 5,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
}


def banner(printer, title: str) -> None:
    today = datetime.now().strftime("%Y-%m-%d %a")
    printer.set(align="center", bold=True, double_height=True, double_width=True)
    printer.text(title.upper()[:24] + "\n")
    printer.set(align="center", bold=False, double_height=False, double_width=False)
    printer.text(today + "\n")
    printer.set(align="left")
    printer.text("=" * PRINT_WIDTH_CHARS + "\n")


def divider(printer) -> None:
    printer.set(align="left", bold=False, double_height=False, double_width=False)
    printer.text("-" * PRINT_WIDTH_CHARS + "\n")
    printer.text("\n")


def wrap_lines(text: str, width: int = PRINT_WIDTH_CHARS) -> str:
    out = []
    for line in text.splitlines() or [text]:
        if not line.strip():
            out.append("")
            continue
        out.extend(textwrap.wrap(line, width=width) or [""])
    return "\n".join(out) + "\n"


def safe_section(name: str):
    """Decorator: wrap a render() body so exceptions print, never abort the report."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(printer, *args, **kwargs):
            try:
                return fn(printer, *args, **kwargs)
            except Exception as e:
                try:
                    printer.set(align="left", bold=False,
                                double_height=False, double_width=False)
                    printer.text(f"[{name}] FAILED\n")
                    printer.text(f"{type(e).__name__}: {e}\n")
                    tb = traceback.format_exc(limit=3)
                    for line in tb.splitlines()[-6:]:
                        printer.text(line[:PRINT_WIDTH_CHARS] + "\n")
                    printer.text("-" * PRINT_WIDTH_CHARS + "\n\n")
                except Exception:
                    pass
        return wrapper
    return deco


def http_get(url, *, timeout=10, headers=None, auth=None, params=None):
    """GET with stable UA and one retry on connection error."""
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    last_err = None
    for attempt in range(2):
        try:
            r = requests.get(url, timeout=timeout, headers=h,
                             auth=auth, params=params)
            r.raise_for_status()
            return r
        except requests.exceptions.ConnectionError as e:
            last_err = e
            time.sleep(1.5)
        except requests.exceptions.RequestException:
            raise
    raise last_err


def fig_to_576_bitmap(fig) -> Image.Image:
    """Render a matplotlib Figure to a 576-px-wide 1-bit PIL image (FS dither)."""
    fig.set_dpi(72)
    cur_w, cur_h = fig.get_size_inches()
    fig.set_size_inches(8.0, cur_h)  # 8 in * 72 dpi = 576 px
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=72, bbox_inches="tight", pad_inches=0.1)
    buf.seek(0)
    img = Image.open(buf).convert("L")
    if img.width != PRINT_WIDTH_PX:
        new_h = int(img.height * PRINT_WIDTH_PX / img.width)
        img = img.resize((PRINT_WIDTH_PX, new_h), Image.LANCZOS)
    return img.convert("1", dither=Image.FLOYDSTEINBERG)


def text_to_bitmap(lines, font_size=18, padding=8) -> Image.Image:
    """Render arbitrary text lines as a 576-px 1-bit image. Useful for puzzles."""
    from PIL import ImageDraw, ImageFont
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            font_size,
        )
    except Exception:
        font = ImageFont.load_default()
    line_h = font_size + 4
    height = padding * 2 + line_h * max(1, len(lines))
    img = Image.new("1", (PRINT_WIDTH_PX, height), 1)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((padding, padding + i * line_h), line, font=font, fill=0)
    return img


def text_table(rows, widths, header=None) -> str:
    """Build a fixed-width text table that fits in PRINT_WIDTH_CHARS."""
    out = []
    if header:
        out.append(_format_row(header, widths))
        out.append("-" * min(sum(widths) + len(widths) - 1, PRINT_WIDTH_CHARS))
    for r in rows:
        out.append(_format_row(r, widths))
    return "\n".join(out) + "\n"


def _format_row(cells, widths) -> str:
    parts = []
    for cell, w in zip(cells, widths):
        s = str(cell)
        if len(s) > w:
            s = s[: max(1, w - 1)] + "…"
        parts.append(s.ljust(w))
    return " ".join(parts)[:PRINT_WIDTH_CHARS]


def print_image(printer, img: Image.Image) -> None:
    """Send a PIL image to the printer using the column-mode bitmap that
    works on the widest range of generic 80mm boards."""
    printer.image(img, impl="bitImageColumn")


def print_text_block(printer, text: str) -> None:
    printer.set(align="left", bold=False, double_height=False, double_width=False)
    printer.text(wrap_lines(text))


def standalone_dummy_run(render_fn, name: str) -> None:
    """Helper for `python -m modules.<name>`: render to a Dummy and dump preview."""
    import os
    from escpos.printer import Dummy
    os.makedirs("out", exist_ok=True)
    p = Dummy()
    render_fn(p)
    raw = p.output
    with open(f"out/{name}.bin", "wb") as f:
        f.write(raw)
    # Also write text-only fallback so you can read it without an emulator
    text_only = bytes(b for b in raw if 32 <= b < 127 or b in (10, 13))
    with open(f"out/{name}.txt", "wb") as f:
        f.write(text_only)
    print(f"wrote out/{name}.bin ({len(raw)} bytes) and out/{name}.txt")
