"""Helper for saving RGB(A) arrays as PNG previews of generated assets."""
from pathlib import Path
import numpy as np
from PIL import Image


def save_png(arr: np.ndarray, path: str | Path, *, scale: int = 1) -> Path:
    """Save a HxWxC uint8 numpy array as PNG. Optionally upscale by `scale`."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if arr.dtype != np.uint8:
        arr = arr.astype(np.uint8)
    img = Image.fromarray(arr)
    if scale != 1:
        img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    img.save(p)
    return p


def palette_to_rgb(palette: list[tuple[int, int, int]], *,
                   already_5bit: bool = True) -> list[tuple[int, int, int]]:
    """Convert a list of (r,g,b) entries to 8-bit RGB for PNG previews."""
    if already_5bit:
        return [(r << 3 | r >> 2, g << 3 | g >> 2, b << 3 | b >> 2)
                for r, g, b in palette]
    return list(palette)


def indexed_to_rgb(indices: np.ndarray, palette: list[tuple[int, int, int]],
                   *, already_5bit: bool = True) -> np.ndarray:
    """Convert a 2D array of palette indices to an HxWx3 uint8 RGB array."""
    rgb_palette = palette_to_rgb(palette, already_5bit=already_5bit)
    H, W = indices.shape
    out = np.zeros((H, W, 3), dtype=np.uint8)
    for idx, color in enumerate(rgb_palette):
        out[indices == idx] = color
    return out


def stack_horizontal(arrays: list[np.ndarray], *, gap: int = 4,
                     gap_color: tuple[int, int, int] = (0, 0, 0)) -> np.ndarray:
    """Stack several HxWx3 arrays side by side with a gap."""
    H = max(a.shape[0] for a in arrays)
    W = sum(a.shape[1] for a in arrays) + gap * (len(arrays) - 1)
    out = np.zeros((H, W, 3), dtype=np.uint8)
    out[:] = gap_color
    x = 0
    for a in arrays:
        out[:a.shape[0], x:x + a.shape[1]] = a
        x += a.shape[1] + gap
    return out


def stack_vertical(arrays: list[np.ndarray], *, gap: int = 4,
                   gap_color: tuple[int, int, int] = (0, 0, 0)) -> np.ndarray:
    W = max(a.shape[1] for a in arrays)
    H = sum(a.shape[0] for a in arrays) + gap * (len(arrays) - 1)
    out = np.zeros((H, W, 3), dtype=np.uint8)
    out[:] = gap_color
    y = 0
    for a in arrays:
        out[y:y + a.shape[0], :a.shape[1]] = a
        y += a.shape[0] + gap
    return out
