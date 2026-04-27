"""Live Textract smoke. Gated on TEXTRACT_SMOKE_TEST=1. Costs ~$0.0015."""
import os
from pathlib import Path

import pytest

from textract_probe import client as tc
from textract_probe.convert import tif_to_png_bytes

SMOKE = os.environ.get("TEXTRACT_SMOKE_TEST") == "1"
SAMPLES = Path("samples")


@pytest.mark.skipif(not SMOKE, reason="TEXTRACT_SMOKE_TEST not set")
def test_detect_document_text_smoke():
    fixture = SAMPLES / "test_input_roll001/00097.tif"
    assert fixture.exists(), f"missing fixture: {fixture}"

    png = tif_to_png_bytes(fixture)
    resp, cost = tc.detect_document_text(png)

    blocks = resp.get("Blocks", [])
    line_blocks = [b for b in blocks if b.get("BlockType") == "LINE"]

    print(f"smoke: {len(blocks)} blocks, {len(line_blocks)} LINE, cost ${cost:.4f}")
    assert blocks, "Textract returned zero blocks"
    assert line_blocks, "Textract returned no LINE blocks"
    assert cost == pytest.approx(0.0015)
