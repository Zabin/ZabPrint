"""Make `gba` package importable from tests."""
import sys
from pathlib import Path

_GBA_ROOT = Path(__file__).resolve().parent.parent
if str(_GBA_ROOT) not in sys.path:
    sys.path.insert(0, str(_GBA_ROOT))
