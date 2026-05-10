# ZabPrint

Daily report for an 80mm thermal printer (576 px wide) on a Raspberry Pi.

Each section lives in its own `modules/<name>.py` and exposes `render(printer)`.
The central `print_daily.py` calls them in order. Failures are caught and the
exception text is printed in place of the section, so a single broken feed
never aborts the report.

## Setup

```
pip install -r requirements.txt
```

Edit the printer constants at the top of `print_daily.py`
(`PRINTER_KIND`, `USB_VENDOR_ID`, etc.).

For conjunctions, edit `SPACETRACK_USER` / `SPACETRACK_PASS` in
`modules/conjunctions.py`.

## Usage

```
python print_daily.py                       # live print
python print_daily.py --dry-run             # write out/daily-YYYY-MM-DD.bin
python print_daily.py --only weather_ottawa # run a subset
python -m modules.weather_ottawa            # render one module to out/
```

## Modules

News: `global_news`, `military_news`, `space_news`, `hacker_news`
Weather/local: `weather_ottawa`, `weather_alerts`, `emergency_alerts`,
`air_quality`, `transit_alerts`, `gas_prices`, `earthquakes`
Space: `launches`, `conjunctions`, `iss_passes`, `aurora_kp`
Markets: `markets`
Astronomy: `astronomy`
Trivia: `this_day_history`
Puzzles: `puzzles` (rotates Sudoku / Word Search / Mini Crossword /
Maze + Cryptogram by weekday)
