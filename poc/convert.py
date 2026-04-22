import io
from pathlib import Path
from PIL import Image


def tif_to_png_bytes(path: str | Path, max_side: int = 1500) -> bytes:
    """Load TIF, downscale to max_side px, normalize mode to RGB, return PNG bytes."""
    img = Image.open(path)
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
