"""S3 puller — fetch a contiguous range of TIF frames per (district, roll)."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from poc.env import s3_client

BUCKET = "servflow-image-one"
ROOT = "Osceola Co School District"


def build_keys(
    district: int,
    roll: str,
    frame_start: int,
    frame_end: int,
) -> list[str]:
    """Return inclusive list of S3 keys for frames [frame_start, frame_end]."""
    if district == 1 and roll == "001":
        prefix = f"{ROOT}/Test Input/ROLL {roll}"
    else:
        prefix = f"{ROOT}/Input/OSCEOLA SCHOOL DISTRICT-{district}/ROLL {roll}"
    return [f"{prefix}/{n:05d}.tif" for n in range(frame_start, frame_end + 1)]


def pull_frames(
    bucket: str,
    keys: Iterable[str],
    out_dir: Path,
) -> int:
    """Download keys to out_dir/<filename>. Skips existing files. Returns new-pull count."""
    out_dir.mkdir(parents=True, exist_ok=True)
    client = s3_client()
    n = 0
    for key in keys:
        local = out_dir / Path(key).name
        if local.exists():
            continue
        client.download_file(bucket, key, str(local))
        n += 1
    return n
