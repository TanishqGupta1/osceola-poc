import re
import time
from datetime import datetime, timezone
from pathlib import Path

from poc.bedrock_client import DEFAULT_MODEL_ID, classify_via_bedrock
from poc.convert import tif_to_png_bytes
from poc.schemas import PageResult, RollMeta, Separator, Student

_FRAME_RE = re.compile(r"(\d{5})")


def _extract_frame(path: Path) -> str:
    m = _FRAME_RE.search(path.stem)
    return m.group(1) if m else path.stem


def classify_page(tif_path: str | Path, roll_id: str) -> PageResult:
    tif_path = Path(tif_path)
    png = tif_to_png_bytes(tif_path)
    t0 = time.monotonic()
    tool_input, _usage = classify_via_bedrock(png)
    latency_ms = int((time.monotonic() - t0) * 1000)
    return PageResult(
        frame=_extract_frame(tif_path),
        roll_id=roll_id,
        page_class=tool_input["page_class"],
        separator=Separator(**tool_input.get("separator", {})),
        student=Student(**tool_input.get("student", {})),
        roll_meta=RollMeta(**tool_input.get("roll_meta", {})),
        confidence_overall=float(tool_input.get("confidence_overall", 0.0)),
        confidence_name=float(tool_input.get("confidence_name", 0.0)),
        notes=tool_input.get("notes", "") or "",
        model_version=DEFAULT_MODEL_ID,
        processed_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        latency_ms=latency_ms,
    )
