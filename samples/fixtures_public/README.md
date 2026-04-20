# Public fixtures

3 non-PII sample images from the Osceola microfilm dataset. Safe to commit publicly.

| File | Class | Description |
|---|---|---|
| `separator_styleA_clapperboard_START.png` | `roll_separator` | Style A clapperboard card — "START ROLL NO. 12" (diagonal hatched rectangles). No student data. |
| `separator_styleB_certificate_START.png` | `roll_leader` ⚠ | **Mis-labeled (2026-04-20 bake-off finding).** All 4 Bedrock models (Haiku 4.5, Sonnet 4.6, Nova Lite, Nova Pro) identify this image as vendor letterhead ("Total Information Management Systems"), not a Style B certificate separator. Use `samples/verify_probe/png/d1r001_01923.png` for a real Style B END card. This file will be re-sourced before the next bake-off. |
| `roll_leader_microfilm_resolution_target.png` | `roll_leader` | Microfilm resolution calibration target. No student data. |

Full sample set lives in S3 at `s3://servflow-image-one/Osceola Co School District/` (FERPA-protected; request access separately).
