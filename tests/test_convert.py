import io
from pathlib import Path
from PIL import Image

from poc.convert import tif_to_png_bytes


def _write_sample_tif(path: Path) -> None:
    img = Image.new("L", (200, 300), color=255)
    img.save(path, format="TIFF")


def test_tif_to_png_bytes_returns_png(tmp_path: Path):
    tif = tmp_path / "sample.tif"
    _write_sample_tif(tif)
    data = tif_to_png_bytes(tif)
    assert isinstance(data, bytes)
    # PNG magic bytes
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_tif_to_png_bytes_downscale(tmp_path: Path):
    tif = tmp_path / "big.tif"
    Image.new("L", (4000, 5000), color=255).save(tif, format="TIFF")
    data = tif_to_png_bytes(tif, max_side=1500)
    im = Image.open(io.BytesIO(data))
    assert max(im.size) <= 1500


def test_tif_to_png_bytes_mode_conversion(tmp_path: Path):
    tif = tmp_path / "cmyk.tif"
    Image.new("CMYK", (100, 100)).save(tif, format="TIFF")
    data = tif_to_png_bytes(tif)
    im = Image.open(io.BytesIO(data))
    assert im.mode in ("RGB", "L")
