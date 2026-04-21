"""Broad index-page probe across all 100 rolls.

Samples first 40 + last 5 frames of every roll, classifies each via Bedrock
Haiku 4.5, writes findings to samples/index_probe/broad/.

Usage:
    python3 scripts/broad_index_probe.py

Idempotent: already-downloaded TIFs and already-classified frames are skipped
on re-run.

Env:
    .env          -> Servflow-image1 S3 creds (AWS_ACCESS_KEY_ID etc)
    .env.bedrock  -> tanishq Bedrock creds

No FERPA data is written outside samples/ (which is gitignored).
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import dotenv_values
from PIL import Image

# ---------- configuration ----------

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = REPO_ROOT / "samples" / "index_probe" / "broad"
OUT_PNG = OUT_ROOT / "png"
JSONL_PATH = OUT_ROOT / "classifications.jsonl"
SUMMARY_JSON = OUT_ROOT / "summary.json"
SUMMARY_MD = OUT_ROOT / "SUMMARY.md"

BUCKET = "servflow-image-one"
ROOT_PREFIX = "Osceola Co School District/Input/"
REGION = "us-west-2"

FIRST_N_FRAMES = 40
LAST_N_FRAMES = 5

MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
MAX_SIDE_PX = 2000
TEMPERATURE = 0.0
MAX_TOKENS = 400

DOWNLOAD_WORKERS = 10
CLASSIFY_WORKERS = 20

BUDGET_CEILING_USD = 10.0
HAIKU_IN_USD_PER_MTOK = 1.00
HAIKU_OUT_USD_PER_MTOK = 5.00

CLASSIFY_PROMPT = """Classify this microfilm frame.

Index = tabular page titled "STUDENT RECORDS INDEX" with columns LAST / FIRST / MIDDLE / DOB listing 5 or more students in rows.

Return JSON only, no markdown, no prose:
{"is_index": true|false, "row_count": 0, "first_3_names": [], "other_class": "roll_leader|roll_separator|student_cover|student_other|unknown"}"""


# ---------- shared state ----------

spend_lock = threading.Lock()
total_tokens_in = 0
total_tokens_out = 0
processed_ids: set[str] = set()
log_lock = threading.Lock()

# ---------- clients ----------


def load_env_file(path: Path) -> dict:
    return {k: v for k, v in dotenv_values(path).items() if v}


def make_s3_client() -> boto3.client:
    env = load_env_file(REPO_ROOT / ".env")
    return boto3.client(
        "s3",
        aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
        region_name=env.get("AWS_REGION", REGION),
        config=Config(
            retries={"max_attempts": 8, "mode": "standard"},
            max_pool_connections=DOWNLOAD_WORKERS * 2,
        ),
    )


def make_bedrock_client() -> boto3.client:
    env = load_env_file(REPO_ROOT / ".env.bedrock")
    return boto3.client(
        "bedrock-runtime",
        aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
        region_name=env.get("AWS_REGION", REGION),
        config=Config(
            retries={"max_attempts": 4, "mode": "adaptive"},
            max_pool_connections=CLASSIFY_WORKERS * 2,
        ),
    )


# ---------- utilities ----------


def log(msg: str) -> None:
    with log_lock:
        print(msg, flush=True)


def district_roll_from_key(key: str) -> tuple[int, str] | None:
    m = re.search(r"OSCEOLA SCHOOL DISTRICT-(\d)/ROLL (\S+)/", key)
    if not m:
        return None
    return int(m.group(1)), m.group(2)


def page_id(district: int, roll: str, frame: str) -> str:
    roll_slug = roll.replace(" ", "").lower()
    return f"d{district}r{roll_slug}_{frame}"


def local_tif_path(district: int, roll: str, frame: str) -> Path:
    roll_slug = roll.replace(" ", "").lower()
    return OUT_ROOT / f"d{district}r{roll_slug}" / f"{frame}.tif"


def frame_num_from_key(key: str) -> str:
    # "00123.tif" -> "00123"
    return key.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def check_budget() -> None:
    with spend_lock:
        in_cost = total_tokens_in / 1e6 * HAIKU_IN_USD_PER_MTOK
        out_cost = total_tokens_out / 1e6 * HAIKU_OUT_USD_PER_MTOK
        total = in_cost + out_cost
        if total >= BUDGET_CEILING_USD:
            log(f"[BUDGET] exceeded ${BUDGET_CEILING_USD:.2f} (actual ${total:.4f}). Halting.")
            os._exit(2)


# ---------- stage 1: list every roll ----------


def list_all_rolls(s3) -> list[tuple[int, str, str]]:
    """Return list of (district, roll, prefix) across 7 districts."""
    rolls: list[tuple[int, str, str]] = []
    for d in range(1, 8):
        prefix = f"{ROOT_PREFIX}OSCEOLA SCHOOL DISTRICT-{d}/"
        resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix, Delimiter="/")
        for p in resp.get("CommonPrefixes", []):
            sub = p["Prefix"]
            m = re.search(r"ROLL (\S+)/", sub)
            if not m:
                continue
            rolls.append((d, m.group(1), sub))
    return rolls


def list_frames_for_roll(s3, prefix: str) -> list[tuple[str, int]]:
    """Return sorted [(frame_key, size), ...]."""
    paginator = s3.get_paginator("list_objects_v2")
    out = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for o in page.get("Contents", []):
            k = o["Key"]
            if k.endswith(".tif"):
                out.append((k, o["Size"]))
    out.sort(key=lambda x: x[0])
    return out


def pick_sample_frames(frames: list[tuple[str, int]]) -> list[tuple[str, int]]:
    if len(frames) <= FIRST_N_FRAMES + LAST_N_FRAMES:
        return frames
    return frames[:FIRST_N_FRAMES] + frames[-LAST_N_FRAMES:]


# ---------- stage 2: download ----------


def download_tif(s3, key: str, out_path: Path) -> bool:
    if out_path.exists() and out_path.stat().st_size > 0:
        return True
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tif.tmp")
    try:
        s3.download_file(BUCKET, key, str(tmp))
        tmp.rename(out_path)
        return True
    except ClientError as e:
        log(f"[S3] download fail {key}: {e}")
        if tmp.exists():
            tmp.unlink()
        return False


# ---------- stage 3: classify ----------


def load_png_bytes(tif_path: Path) -> bytes:
    im = Image.open(tif_path)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    if max(im.size) > MAX_SIDE_PX:
        im.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def parse_json_reply(text: str) -> dict | None:
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("```")
        if len(parts) >= 2:
            t = parts[1]
            if t.startswith("json"):
                t = t[4:]
            t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        # try to locate a { ... } block
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return None


def classify_frame(br, tif_path: Path) -> dict:
    png = load_png_bytes(tif_path)
    t0 = time.monotonic()
    resp = br.converse(
        modelId=MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": "png", "source": {"bytes": png}}},
                    {"text": CLASSIFY_PROMPT},
                ],
            }
        ],
        inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": TEMPERATURE},
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    txt = resp["output"]["message"]["content"][0]["text"]
    usage = resp.get("usage", {})
    parsed = parse_json_reply(txt) or {}
    return {
        "raw_text": txt[:300],
        "is_index": bool(parsed.get("is_index", False)),
        "row_count": int(parsed.get("row_count", 0) or 0),
        "first_3_names": parsed.get("first_3_names", []) or [],
        "other_class": parsed.get("other_class", "unknown"),
        "tokens_in": usage.get("inputTokens"),
        "tokens_out": usage.get("outputTokens"),
        "latency_ms": latency_ms,
    }


def save_index_png(tif_path: Path, district: int, roll: str, frame: str) -> None:
    roll_slug = roll.replace(" ", "").lower()
    dest = OUT_PNG / f"d{district}r{roll_slug}_{frame}_INDEX.png"
    if dest.exists():
        return
    OUT_PNG.mkdir(parents=True, exist_ok=True)
    im = Image.open(tif_path)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    if max(im.size) > MAX_SIDE_PX:
        im.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    im.save(dest, format="PNG", optimize=True)


# ---------- stage 4: aggregate ----------


def write_summary(records: list[dict]) -> None:
    per_roll: dict[tuple[int, str], dict] = {}
    per_district: dict[int, dict] = {d: {"rolls": set(), "rolls_with_index": set(), "index_frames": 0, "names_total": 0} for d in range(1, 8)}

    for r in records:
        d, roll = r["district"], r["roll"]
        key = (d, roll)
        slot = per_roll.setdefault(
            key,
            {
                "district": d,
                "roll": roll,
                "sampled_frames": 0,
                "index_frames": [],
                "student_frames": 0,
                "leader_frames": 0,
                "separator_frames": 0,
                "other_frames": 0,
                "error_frames": 0,
                "est_names_total": 0,
            },
        )
        slot["sampled_frames"] += 1
        per_district[d]["rolls"].add(roll)

        if r.get("error"):
            slot["error_frames"] += 1
            continue

        if r.get("is_index"):
            slot["index_frames"].append(
                {"frame": r["frame"], "row_count": r["row_count"], "first_3": r["first_3_names"]}
            )
            slot["est_names_total"] += r["row_count"]
            per_district[d]["rolls_with_index"].add(roll)
            per_district[d]["index_frames"] += 1
            per_district[d]["names_total"] += r["row_count"]
        else:
            oc = r.get("other_class", "unknown")
            if oc == "roll_leader":
                slot["leader_frames"] += 1
            elif oc == "roll_separator":
                slot["separator_frames"] += 1
            elif oc == "student_cover":
                slot["student_frames"] += 1
            else:
                slot["other_frames"] += 1

    summary = {
        "total_records": len(records),
        "total_rolls": len(per_roll),
        "total_index_frames": sum(len(s["index_frames"]) for s in per_roll.values()),
        "est_total_names_indexed": sum(s["est_names_total"] for s in per_roll.values()),
        "per_district": {
            d: {
                "rolls_total": len(v["rolls"]),
                "rolls_with_index": len(v["rolls_with_index"]),
                "index_frames": v["index_frames"],
                "names_total": v["names_total"],
            }
            for d, v in per_district.items()
        },
        "per_roll": [per_roll[k] for k in sorted(per_roll)],
        "budget_usd_used": (total_tokens_in / 1e6 * HAIKU_IN_USD_PER_MTOK)
        + (total_tokens_out / 1e6 * HAIKU_OUT_USD_PER_MTOK),
        "total_tokens_in": total_tokens_in,
        "total_tokens_out": total_tokens_out,
    }

    SUMMARY_JSON.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2))

    lines = [
        "# Broad Index-Page Probe — Summary",
        "",
        f"- Total sampled frames: **{summary['total_records']}**",
        f"- Total rolls probed: **{summary['total_rolls']} / 100**",
        f"- Total confirmed index frames: **{summary['total_index_frames']}**",
        f"- Estimated total names indexed in sampled pages: **{summary['est_total_names_indexed']}**",
        f"- Bedrock spend: **${summary['budget_usd_used']:.4f}** (in {summary['total_tokens_in']:,} tok, out {summary['total_tokens_out']:,} tok)",
        "",
        "## Per-district",
        "",
        "| District | Rolls total | Rolls with index | Index frames | Names (est) |",
        "|---|---|---|---|---|",
    ]
    for d in range(1, 8):
        v = summary["per_district"].get(d, {})
        lines.append(
            f"| D{d} | {v.get('rolls_total', 0)} | {v.get('rolls_with_index', 0)} | {v.get('index_frames', 0)} | {v.get('names_total', 0)} |"
        )

    lines.extend(["", "## Rolls with confirmed index pages", ""])
    lines.append("| District | Roll | Sampled | Index frames | Names (est) | Sample first names |")
    lines.append("|---|---|---|---|---|---|")
    for s in summary["per_roll"]:
        if not s["index_frames"]:
            continue
        positions = ",".join(f["frame"] for f in s["index_frames"])
        sample_names = []
        for f in s["index_frames"][:2]:
            for n in (f.get("first_3") or [])[:2]:
                if n:
                    sample_names.append(n)
        sample_names = sample_names[:4]
        lines.append(
            f"| D{s['district']} | {s['roll']} | {s['sampled_frames']} | {positions} | {s['est_names_total']} | {'; '.join(sample_names)} |"
        )

    lines.extend(["", "## Rolls WITHOUT any confirmed index pages", ""])
    empty_rolls = [s for s in summary["per_roll"] if not s["index_frames"]]
    for s in empty_rolls:
        lines.append(
            f"- D{s['district']} {s['roll']}  (sampled={s['sampled_frames']}, leader={s['leader_frames']}, sep={s['separator_frames']}, cover={s['student_frames']}, other={s['other_frames']})"
        )

    lines.extend(["", "---", "", "Generated by `scripts/broad_index_probe.py`."])
    SUMMARY_MD.write_text("\n".join(lines) + "\n")


# ---------- main ----------


def load_existing_classifications() -> list[dict]:
    records: list[dict] = []
    if not JSONL_PATH.exists():
        return records
    with JSONL_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                records.append(r)
                processed_ids.add(r["page_id"])
            except Exception:
                continue
    return records


def main() -> int:
    global total_tokens_in, total_tokens_out

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    OUT_PNG.mkdir(parents=True, exist_ok=True)

    log(f"[init] output root: {OUT_ROOT}")
    records = load_existing_classifications()
    log(f"[init] loaded {len(records)} previously-classified records ({len(processed_ids)} unique ids)")

    s3 = make_s3_client()
    br = make_bedrock_client()

    # 1. enumerate rolls
    log("[stage 1] listing rolls ...")
    rolls = list_all_rolls(s3)
    log(f"[stage 1] {len(rolls)} rolls across 7 districts")

    # 2. pick sample frames per roll
    log("[stage 2] picking sample frames per roll ...")
    plan: list[tuple[int, str, str, str, int]] = []  # (district, roll, key, frame, size)
    for d, roll, prefix in rolls:
        frames = list_frames_for_roll(s3, prefix)
        sample = pick_sample_frames(frames)
        for key, size in sample:
            plan.append((d, roll, key, frame_num_from_key(key), size))
    log(f"[stage 2] total targets: {len(plan)} TIFs across {len(rolls)} rolls")

    # 3. download in parallel (idempotent)
    log("[stage 3] downloading TIFs ...")
    to_download = []
    for d, roll, key, frame, _size in plan:
        out = local_tif_path(d, roll, frame)
        if not out.exists() or out.stat().st_size == 0:
            to_download.append((d, roll, key, frame, out))
    log(f"[stage 3] downloading {len(to_download)} missing TIFs ({len(plan) - len(to_download)} cached)")

    dl_ok = 0
    dl_fail = 0
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as ex:
        futs = {ex.submit(download_tif, s3, key, out): (d, roll, frame) for d, roll, key, frame, out in to_download}
        for i, fut in enumerate(as_completed(futs), 1):
            ok = fut.result()
            if ok:
                dl_ok += 1
            else:
                dl_fail += 1
            if i % 200 == 0:
                log(f"  [dl {i}/{len(to_download)}] ok={dl_ok} fail={dl_fail}")
    log(f"[stage 3] done. ok={dl_ok} fail={dl_fail}")

    # 4. classify in parallel
    log("[stage 4] classifying ...")
    to_classify = []
    for d, roll, key, frame, size in plan:
        pid = page_id(d, roll, frame)
        if pid in processed_ids:
            continue
        tif = local_tif_path(d, roll, frame)
        if not tif.exists():
            continue
        to_classify.append((d, roll, key, frame, size, pid, tif))
    random.shuffle(to_classify)  # spread districts across time
    log(f"[stage 4] classifying {len(to_classify)} frames (already done: {len(processed_ids)})")

    def worker(job):
        d, roll, key, frame, size, pid, tif = job
        attempt = 0
        backoff = 1.0
        while True:
            try:
                res = classify_frame(br, tif)
                return (d, roll, key, frame, size, pid, res, None)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code in {"ThrottlingException", "ServiceUnavailableException", "InternalServerException"} and attempt < 4:
                    time.sleep(backoff + random.random() * 0.5)
                    backoff *= 2
                    attempt += 1
                    continue
                return (d, roll, key, frame, size, pid, None, str(e)[:200])
            except Exception as e:
                return (d, roll, key, frame, size, pid, None, str(e)[:200])

    jsonl_lock = threading.Lock()
    written = 0
    with ThreadPoolExecutor(max_workers=CLASSIFY_WORKERS) as ex, JSONL_PATH.open("a") as jf:
        futs = [ex.submit(worker, job) for job in to_classify]
        for i, fut in enumerate(as_completed(futs), 1):
            d, roll, key, frame, size, pid, res, err = fut.result()
            record = {
                "page_id": pid,
                "district": d,
                "roll": roll,
                "frame": frame,
                "s3_key": key,
                "size_bytes": size,
                "error": err,
            }
            if res:
                global total_tokens_in, total_tokens_out  # noqa: PLW0603
                with spend_lock:
                    total_tokens_in += (res.get("tokens_in") or 0)
                    total_tokens_out += (res.get("tokens_out") or 0)
                record.update(
                    {
                        "is_index": res["is_index"],
                        "row_count": res["row_count"],
                        "first_3_names": res["first_3_names"],
                        "other_class": res["other_class"],
                        "tokens_in": res["tokens_in"],
                        "tokens_out": res["tokens_out"],
                        "latency_ms": res["latency_ms"],
                    }
                )
                if res["is_index"] and res["row_count"] >= 3:
                    try:
                        tif = local_tif_path(d, roll, frame)
                        save_index_png(tif, d, roll, frame)
                    except Exception as e:
                        log(f"[png] save fail {pid}: {e}")
            with jsonl_lock:
                jf.write(json.dumps(record) + "\n")
                jf.flush()
                processed_ids.add(pid)
                written += 1

            if i % 100 == 0:
                spend = (total_tokens_in / 1e6 * HAIKU_IN_USD_PER_MTOK) + (
                    total_tokens_out / 1e6 * HAIKU_OUT_USD_PER_MTOK
                )
                log(
                    f"  [cls {i}/{len(to_classify)}] last={pid} is_index={record.get('is_index')} spend=${spend:.4f}"
                )
            if i % 500 == 0:
                check_budget()

    log(f"[stage 4] done. wrote {written} records this run")

    # 5. aggregate
    log("[stage 5] aggregating ...")
    records = load_existing_classifications()
    write_summary(records)
    spend = (total_tokens_in / 1e6 * HAIKU_IN_USD_PER_MTOK) + (total_tokens_out / 1e6 * HAIKU_OUT_USD_PER_MTOK)
    log(f"[done] summary -> {SUMMARY_MD}")
    log(f"[done] spend this run: ${spend:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
