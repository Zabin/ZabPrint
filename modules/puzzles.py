"""Daily puzzle: rotates Sudoku / Word Search / Mini Crossword / Maze+Cryptogram.

Picks a generator based on weekday %4. All output is a 576-px-wide 1-bit
PIL image rendered through _common.print_image.
"""

from datetime import date
import random

from PIL import Image, ImageDraw, ImageFont

from . import _common as C

PUZZLE_W = C.PRINT_WIDTH_PX


def _font(size, bold=False):
    name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    try:
        return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)
    except Exception:
        try:
            return ImageFont.truetype(
                "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"
                if bold else
                "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
                size,
            )
        except Exception:
            return ImageFont.load_default()


# ---------------------------- Sudoku ----------------------------

def _gen_sudoku(seed):
    rng = random.Random(seed)
    base = 3
    side = base * base

    def pattern(r, c):
        return (base * (r % base) + r // base + c) % side

    def shuffle(s):
        s = list(s)
        rng.shuffle(s)
        return s

    rows = [g * base + r for g in shuffle(range(base)) for r in shuffle(range(base))]
    cols = [g * base + c for g in shuffle(range(base)) for c in shuffle(range(base))]
    nums = shuffle(range(1, side + 1))
    board = [[nums[pattern(r, c)] for c in cols] for r in rows]

    # Remove ~50 cells for a medium puzzle
    cells = [(r, c) for r in range(side) for c in range(side)]
    rng.shuffle(cells)
    puzzle = [row[:] for row in board]
    for r, c in cells[:50]:
        puzzle[r][c] = 0
    return puzzle, board


def _render_sudoku(seed):
    puzzle, solution = _gen_sudoku(seed)
    cell = 60
    margin = 12
    grid = cell * 9
    height = grid + margin * 2 + 80  # space for footer
    img = Image.new("1", (PUZZLE_W, height), 1)
    draw = ImageDraw.Draw(img)
    font = _font(36, bold=True)
    title_font = _font(22, bold=True)

    offset_x = (PUZZLE_W - grid) // 2
    offset_y = margin

    for i in range(10):
        w = 3 if i % 3 == 0 else 1
        draw.line([(offset_x, offset_y + i * cell),
                   (offset_x + grid, offset_y + i * cell)], fill=0, width=w)
        draw.line([(offset_x + i * cell, offset_y),
                   (offset_x + i * cell, offset_y + grid)], fill=0, width=w)

    for r in range(9):
        for c in range(9):
            v = puzzle[r][c]
            if v:
                bbox = draw.textbbox((0, 0), str(v), font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                tx = offset_x + c * cell + (cell - tw) // 2
                ty = offset_y + r * cell + (cell - th) // 2 - 4
                draw.text((tx, ty), str(v), font=font, fill=0)

    draw.text((offset_x, offset_y + grid + 8),
              "Sudoku - Medium", font=title_font, fill=0)
    return img


# ---------------------------- Word Search ----------------------------

WORDLISTS = [
    ("Space", ["ORBIT", "COMET", "NEBULA", "PLANET", "STAR",
               "GALAXY", "ROCKET", "LUNAR", "SOLAR", "VOID"]),
    ("Weather", ["RAIN", "SNOW", "FROST", "WIND", "CLOUD",
                 "STORM", "SLEET", "FOG", "HAIL", "GUST"]),
    ("Canada", ["MAPLE", "BEAVER", "TUNDRA", "MOUNTIE", "HOCKEY",
                "POUTINE", "OTTAWA", "QUEBEC", "YUKON", "INUIT"]),
    ("Animals", ["BEAR", "OTTER", "MOOSE", "LYNX", "WOLF",
                 "EAGLE", "HERON", "FOX", "RAVEN", "CARIBOU"]),
]


def _render_word_search(seed):
    rng = random.Random(seed)
    theme, words = rng.choice(WORDLISTS)
    size = 14
    grid = [["."] * size for _ in range(size)]

    dirs = [(0, 1), (1, 0), (1, 1), (-1, 1), (0, -1), (-1, 0), (1, -1), (-1, -1)]

    def place(word):
        for _ in range(120):
            d = rng.choice(dirs)
            r0 = rng.randrange(size)
            c0 = rng.randrange(size)
            r1 = r0 + d[0] * (len(word) - 1)
            c1 = c0 + d[1] * (len(word) - 1)
            if not (0 <= r1 < size and 0 <= c1 < size):
                continue
            ok = True
            for k, ch in enumerate(word):
                rr, cc = r0 + d[0] * k, c0 + d[1] * k
                if grid[rr][cc] not in (".", ch):
                    ok = False
                    break
            if not ok:
                continue
            for k, ch in enumerate(word):
                grid[r0 + d[0] * k][c0 + d[1] * k] = ch
            return True
        return False

    placed = []
    for w in words:
        if place(w):
            placed.append(w)

    for r in range(size):
        for c in range(size):
            if grid[r][c] == ".":
                grid[r][c] = chr(rng.randrange(ord("A"), ord("Z") + 1))

    cell = 36
    margin = 12
    grid_px = cell * size
    list_h = ((len(placed) + 1) // 2) * 28 + 60
    height = grid_px + margin * 2 + list_h
    img = Image.new("1", (PUZZLE_W, height), 1)
    draw = ImageDraw.Draw(img)
    font = _font(22, bold=True)
    title_font = _font(22, bold=True)
    list_font = _font(20)

    offset_x = (PUZZLE_W - grid_px) // 2
    offset_y = margin

    draw.rectangle([offset_x - 2, offset_y - 2,
                    offset_x + grid_px + 2, offset_y + grid_px + 2],
                   outline=0, width=2)
    for r in range(size):
        for c in range(size):
            ch = grid[r][c]
            bbox = draw.textbbox((0, 0), ch, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text((offset_x + c * cell + (cell - tw) // 2,
                       offset_y + r * cell + (cell - th) // 2 - 2),
                      ch, font=font, fill=0)

    title_y = offset_y + grid_px + 12
    draw.text((margin, title_y),
              f"Word Search: {theme}", font=title_font, fill=0)
    col_w = (PUZZLE_W - margin * 2) // 2
    for i, word in enumerate(placed):
        col = i % 2
        row = i // 2
        draw.text((margin + col * col_w, title_y + 32 + row * 28),
                  f"- {word}", font=list_font, fill=0)
    return img


# ---------------------------- Mini Crossword ----------------------------

# Tiny offline corpus of 5x5 themed puzzles. Each puzzle is grid (with '#'
# for black squares) and across/down clue lists.
CROSSWORDS = [
    {
        "grid": [
            "ORBIT",
            "MOON#",
            "ARID#",
            "##SUN",
            "##ICE",
        ],
        "across": [
            "1A. Path of a satellite",
            "6A. Earth's natural satellite",
            "8A. Like a desert",
            "10A. Star at the centre",
            "11A. Frozen water",
        ],
        "down": [
            "1D. Sphere",
            "2D. Red planet",
            "3D. Pluto's biggest moon",
            "4D. Constellation hunter",
            "5D. Tide cause",
        ],
    },
    {
        "grid": [
            "MAPLE",
            "OTTER",
            "OTTAW",
            "SNOW#",
            "EH###",
        ],
        "across": [
            "1A. Canada's tree",
            "6A. River playful mammal",
            "8A. Capital city",
            "11A. Winter precip",
            "12A. Canadian interjection",
        ],
        "down": [
            "1D. Big antlered mammal",
            "2D. Old, as a relic",
            "3D. ___ Transpo",
            "4D. Like ice",
            "5D. Empty",
        ],
    },
    {
        "grid": [
            "STORM",
            "TIDES",
            "OCEAN",
            "RAINS",
            "MIST#",
        ],
        "across": [
            "1A. Bad weather",
            "6A. Lunar pulls",
            "7A. Big saltwater",
            "8A. Falling drops",
            "9A. Light fog",
        ],
        "down": [
            "1D. Sleep stage",
            "2D. ___ pool",
            "3D. ___ liner",
            "4D. Drying agent",
            "5D. Gloomy",
        ],
    },
]


def _render_crossword(seed):
    rng = random.Random(seed)
    pz = rng.choice(CROSSWORDS)
    grid = pz["grid"]
    n = len(grid)
    cell = 60
    margin = 12
    grid_px = cell * n
    clue_h = 28 * (len(pz["across"]) + len(pz["down"])) + 80
    height = grid_px + margin * 2 + clue_h
    img = Image.new("1", (PUZZLE_W, height), 1)
    draw = ImageDraw.Draw(img)
    title = _font(22, bold=True)
    label_f = _font(14)
    clue_f = _font(18)

    offset_x = (PUZZLE_W - grid_px) // 2
    offset_y = margin

    num = 0
    numbers = {}
    for r in range(n):
        for c in range(n):
            if grid[r][c] == "#":
                continue
            starts_across = (c == 0 or grid[r][c - 1] == "#") and \
                            (c + 1 < n and grid[r][c + 1] != "#")
            starts_down = (r == 0 or grid[r - 1][c] == "#") and \
                          (r + 1 < n and grid[r + 1][c] != "#")
            if starts_across or starts_down:
                num += 1
                numbers[(r, c)] = num

    for r in range(n):
        for c in range(n):
            x0 = offset_x + c * cell
            y0 = offset_y + r * cell
            if grid[r][c] == "#":
                draw.rectangle([x0, y0, x0 + cell, y0 + cell], fill=0)
            else:
                draw.rectangle([x0, y0, x0 + cell, y0 + cell],
                               outline=0, width=2)
                if (r, c) in numbers:
                    draw.text((x0 + 3, y0 + 2),
                              str(numbers[(r, c)]), font=label_f, fill=0)

    y = offset_y + grid_px + 12
    draw.text((margin, y), "Mini Crossword", font=title, fill=0)
    y += 32
    draw.text((margin, y), "ACROSS", font=title, fill=0)
    y += 28
    for clue in pz["across"]:
        draw.text((margin, y), clue, font=clue_f, fill=0)
        y += 26
    y += 8
    draw.text((margin, y), "DOWN", font=title, fill=0)
    y += 28
    for clue in pz["down"]:
        draw.text((margin, y), clue, font=clue_f, fill=0)
        y += 26

    return img


# ---------------------------- Maze + Cryptogram ----------------------------

QUOTES = [
    "THE STARS DONT LOOK BIGGER, BUT THEY LOOK BRIGHTER. - ALAN SHEPARD",
    "THAT'S ONE SMALL STEP FOR MAN. - NEIL ARMSTRONG",
    "EARTH IS THE CRADLE OF HUMANITY. - TSIOLKOVSKY",
    "WE CHOOSE TO GO TO THE MOON. - JOHN F KENNEDY",
    "THE GOOD THING ABOUT SCIENCE IS IT'S TRUE. - NEIL DEGRASSE TYSON",
    "FAILURE IS NOT AN OPTION. - GENE KRANZ",
]


def _gen_maze(rng, w, h):
    """Recursive-backtracker maze. Returns walls dict per cell."""
    walls = [[{"N": True, "S": True, "E": True, "W": True}
              for _ in range(w)] for _ in range(h)]
    visited = [[False] * w for _ in range(h)]
    stack = [(0, 0)]
    visited[0][0] = True
    dirs = [("N", -1, 0), ("S", 1, 0), ("E", 0, 1), ("W", 0, -1)]
    opp = {"N": "S", "S": "N", "E": "W", "W": "E"}
    while stack:
        r, c = stack[-1]
        nbrs = []
        for d, dr, dc in dirs:
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and not visited[nr][nc]:
                nbrs.append((d, nr, nc))
        if not nbrs:
            stack.pop()
            continue
        d, nr, nc = rng.choice(nbrs)
        walls[r][c][d] = False
        walls[nr][nc][opp[d]] = False
        visited[nr][nc] = True
        stack.append((nr, nc))
    return walls


def _render_maze_cryptogram(seed):
    rng = random.Random(seed)
    cols, rows = 18, 18
    cell = 28
    maze_w = cols * cell
    maze_h = rows * cell
    margin = 12

    quote = rng.choice(QUOTES)
    alphabet = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    shuffled = alphabet[:]
    rng.shuffle(shuffled)
    cipher = dict(zip(alphabet, shuffled))
    encoded = "".join(cipher.get(ch, ch) for ch in quote)

    crypto_lines = []
    line = ""
    for word in encoded.split(" "):
        if len(line) + len(word) + 1 > 36:
            crypto_lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        crypto_lines.append(line)

    height = margin * 2 + maze_h + 60 + (len(crypto_lines) + 4) * 26
    img = Image.new("1", (PUZZLE_W, height), 1)
    draw = ImageDraw.Draw(img)
    title = _font(22, bold=True)
    body = _font(20)

    walls = _gen_maze(rng, cols, rows)
    offset_x = (PUZZLE_W - maze_w) // 2
    offset_y = margin

    for r in range(rows):
        for c in range(cols):
            x0 = offset_x + c * cell
            y0 = offset_y + r * cell
            w = walls[r][c]
            if w["N"]:
                draw.line([(x0, y0), (x0 + cell, y0)], fill=0, width=2)
            if w["W"]:
                draw.line([(x0, y0), (x0, y0 + cell)], fill=0, width=2)
            if r == rows - 1 and w["S"]:
                draw.line([(x0, y0 + cell), (x0 + cell, y0 + cell)],
                          fill=0, width=2)
            if c == cols - 1 and w["E"]:
                draw.line([(x0 + cell, y0), (x0 + cell, y0 + cell)],
                          fill=0, width=2)
    # Mark entrance/exit
    draw.text((offset_x - 12, offset_y - 4), "S", font=body, fill=0)
    draw.text((offset_x + maze_w + 2, offset_y + maze_h - 22), "E",
              font=body, fill=0)

    y = offset_y + maze_h + 12
    draw.text((margin, y), "Cryptogram", font=title, fill=0)
    y += 30
    for line in crypto_lines:
        draw.text((margin, y), line, font=body, fill=0)
        y += 26
    y += 6
    # Frequency hint
    common = sorted(set(encoded.replace(" ", "").replace("-", "")
                        .replace(".", "").replace(",", "").replace("'", "")),
                    key=lambda c: -encoded.count(c))[:3]
    draw.text((margin, y),
              "Hint: most common cipher letters: " + " ".join(common),
              font=body, fill=0)
    return img


# ---------------------------- Dispatch ----------------------------

@C.safe_section("puzzles")
def render(printer):
    today = date.today()
    weekday = today.weekday()
    seed = today.toordinal()
    kind = weekday % 4
    if kind == 0:
        title = "Puzzle: Sudoku"
        img = _render_sudoku(seed)
    elif kind == 1:
        title = "Puzzle: Word Search"
        img = _render_word_search(seed)
    elif kind == 2:
        title = "Puzzle: Mini Crossword"
        img = _render_crossword(seed)
    else:
        title = "Puzzle: Maze + Cryptogram"
        img = _render_maze_cryptogram(seed)
    C.banner(printer, title)
    C.print_image(printer, img)
    printer.text("\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "puzzles")
