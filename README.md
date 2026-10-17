# AWS Rekognition Video Annotation

[![Tests](https://github.com/DuongDuyet2909/aws-rekognition-video-annotation/actions/workflows/tests.yml/badge.svg)](https://github.com/DuongDuyet2909/aws-rekognition-video-annotation/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
[![Code license: MIT](https://img.shields.io/badge/Code-MIT-green.svg)](LICENSE)

Read a zebra video, use Amazon Rekognition Image for selected frames, and export YOLO-format labels. Offline tools repair old labels, render detections and prepare a human-review subset. Output is not a count of distinct animals and does not establish model accuracy.


![Annotated frame from the demo](docs/preview.jpg)

Built from [Computer Vision Engineer's AWS Rekognition tutorial](https://github.com/computervisioneng/object-detection-aws-rekognition-tutorial), with added repair, resumability, request limits, rendering and evaluation tooling. This is an engineering and annotation project; it does not claim to train a new model or establish detection accuracy.

## Source and complete project data

The Git repository contains all application code, documentation, tests, CI and recorded summaries. The [v1.0.0 Release](https://github.com/DuongDuyet2909/aws-rekognition-video-annotation/releases/tag/v1.0.0) contains the complete demo archive: the source video and every existing output file, including 755 original frames, 755 annotated frames, labels, metadata, review samples, the annotated video and the original label backup. Credentials, environments and Python caches are excluded.

The archive is over 500 MiB, so it is hosted as a Release asset rather than thousands of large Git objects. [Download the complete demo](https://github.com/DuongDuyet2909/aws-rekognition-video-annotation/releases/download/v1.0.0/aws-rekognition-complete-demo.zip), or restore it using the checksum-verifying helper below. No AWS account is needed to use saved results.

Recorded local results: **755 frames, 12,720 boxes and zero duplicate label rows after repair**, with **12,720 duplicate rows removed**. These are output-integrity counts, not accuracy or distinct-animal counts. There are **26 pending human-review samples**; precision/recall on real data remains unavailable until review is completed. See [the Vietnamese report](TONG_QUAN.md) and [recorded verification](reports/verification_after.json).

## Setup

Use Python 3.11 in a fresh environment. This project needs NumPy 2 for OpenCV 5; keep it separate from TensorFlow projects that require NumPy 1.

```bash
git clone https://github.com/DuongDuyet2909/aws-rekognition-video-annotation.git
cd aws-rekognition-video-annotation
python -m venv .venv
```

Activate `.venv` (`.\.venv\Scripts\Activate.ps1` in PowerShell, or `source .venv/bin/activate` on Linux/macOS), then:

```bash
python -m pip install -r requirements.txt
python -X utf8 scripts/restore_demo.py --download
```

The restore helper verifies the archive's SHA-256, rejects unsafe paths, preserves existing output and regenerates machine-specific YOLO image lists. It requires a clean clone with no existing `output/` or `zebras.mp4`. If the archive is already downloaded, use `python scripts/restore_demo.py --archive /path/to/aws-rekognition-complete-demo.zip` instead. Archive details are in [reports/demo_asset.json](reports/demo_asset.json).

On the project owner's Windows computer, `run_offline.cmd` can also use the prepared `%USERPROFILE%\.aws-rekognition-venv` runtime. Other users should create `.venv` as shown above.

## Use the existing output without AWS calls

```powershell
python -X utf8 main.py detect --offline --stride 1 --max-api-calls 0
python -X utf8 main.py render
python -X utf8 main.py audit
```

Or run `run_offline.cmd` from the terminal. The release demo already contains repaired frames and imported cache metadata; restore it first on a new clone. `detect --offline` verifies cache files and never creates an AWS client. `render` writes `output/annotated_images/`, `output/preview.jpg` and `output/annotated_video.mp4`, keeping the original frame rate and duration. A frame without predictions is explicitly marked `Not analysed`, not presented as an empty detection result.

To repair another legacy set, first keep the matching video at `zebras.mp4`, with paired `output/images/frame_XXXX.jpg` and `output/annotations/frame_XXXX.txt`:

```powershell
python -X utf8 main.py repair
```

Repair validates labels, saves the originals in `output/backups/annotations_before_repair_*.zip`, removes identical duplicate rows, creates compatible `output/labels/` files and writes metadata. Imported old results have `confidence: null`, no raw API response and `origin: legacy_import`. Their request settings are inferred from the previous code: Zebra, label confidence 50, no separate instance filtering, JPEG quality 95 and 1280-pixel maximum dimension. Do not treat that provenance as an AWS audit log.

## New AWS processing

The application uses Boto3's standard credential providers: environment, shared AWS profiles or IAM roles. There are no access-key literals in the application. Configure your own profile, for example with the AWS CLI command `aws configure --profile aws-rekognition-tutorial`, or use an existing IAM/environment setup. No credentials are included in Git or the release archive.

```powershell
python -X utf8 main.py detect --profile aws-rekognition-tutorial --stride 30 --max-api-calls 25
```

- Default sampling is one frame every 30 source frames. For this 755-frame video that selects **26 frames**, versus 755 previously. That is 96.56% fewer candidate image requests on an uncached run, not an observed billing reduction. With a budget of 25, a fully uncached run stops short; rerun to process the remaining frame from cache-aware progress.
- `--max-api-calls` caps new logical `detect_labels` calls in that invocation. Each can have up to three SDK HTTP attempts with standard retry/backoff. It is not a currency limit. `--max-api-calls 0` forbids new API calls.
- A completed matching cache entry is skipped. Raw responses are written before final artifacts so an interrupted write can be recovered without another request. Cache validation includes video hash, request settings, image and annotation hashes. Use a different output directory for another video or changed detection settings, preventing mixed-policy datasets.
- `--refresh` explicitly requests regeneration, bypassing the cache. It cannot be combined with `--offline`.
- Authentication/permission errors stop the run. Other failed frames are recorded in `output/run_summary.json`; a later invocation retries only missing/invalid entries. Incomplete processing exits with status 2; input/config errors exit with status 1.
- Request JPEG encoding is checked; overly large images are rejected with guidance. `--max-dimension` and `--jpeg-quality` control payload size. Normalized box coordinates remain mapped to the original frame dimensions.

Example of stricter instance filtering for newly obtained responses:

```powershell
python -X utf8 main.py detect --profile aws-rekognition-tutorial --output output_conf70 --instance-confidence 70 --max-api-calls 5
```

The default `--label-confidence 50 --instance-confidence 0` preserves the old policy. A changed threshold requires a separate output directory and fresh responses. Old TXT labels cannot be retroactively filtered by unknown confidence. The schema is intentionally single-class Zebra; no tracker or model training is included.

## YOLO export

```powershell
python -X utf8 main.py export-yolo --every 5 --validation-fraction 0.2 --gap 30
```

This creates `output/data.yaml`, `output/splits/train.txt` and `output/splits/val.txt`. Images remain in `output/images/`, paired with `output/labels/`; image lists reference them without duplicating the entire dataset. Temporal splitting plus a frame gap reduces adjacent-frame overlap. These are pseudo-labels from one video; both splits still share the scene and animals, so validation is not independent. Review labels before training. Regenerate the lists if the project is moved, because generated image-list paths are absolute.

## Human review and evaluation

```powershell
python -X utf8 main.py prepare-review --every 30
```

`output/review/` contains 26 images and proposed labels plus `review.csv`. Open these in a YOLO-compatible annotation tool, correct missing/false/misplaced boxes, then set each completed frame's `status` to `reviewed` and fill in `reviewer`. Do not mark uninspected samples reviewed. The tool refuses to overwrite an existing review set.

```powershell
python -X utf8 main.py evaluate --ground-truth output/review --iou 0.5
```

Evaluation requires a separate, fully reviewed set. It reports TP/FP/FN, precision, recall, F1 and mean matched IoU on that subset. With genuine per-instance confidence scores it also reports one-class AP50 and mean AP over IoU 0.50:0.95, using 101-point interpolation. It is a small evaluator, not the full COCO evaluation protocol (no crowd/area categories). AP/mAP is left null for legacy boxes without confidence; no scores are invented. No actual accuracy result is claimed until human review is completed.

## Output and tests

```text
output/images/             Original frames
output/annotations/        Deduplicated YOLO labels (legacy-compatible location)
output/labels/             YOLO directory convention
output/metadata/           Detection scores/provenance/settings/hashes
output/responses/          New AWS responses and request context; absent for legacy data
output/annotated_images/   Frames with boxes
output/annotated_video.mp4 Annotated video at source FPS
output/review/             Human review set and status manifest
output/*_report.json       Audit, repair, render, dataset and optional evaluation summaries
```

```powershell
python -X utf8 -m unittest discover -s tests -v
python -m pip check
```

The suite has 16 tests: 12 pipeline/evaluation tests and four release-archive integrity/safety tests. Tests use synthetic short videos and explicit fake AWS clients. They verify repair, filtering, confidence handling, cache invalidation, budget limits, response recovery, auth-error handling, video duration, temporal splitting and review gating. They make no AWS calls and do not measure zebra detection quality.

Large data and video output are delivered through GitHub Releases; ignore rules prevent them from being added to Git history. Full analysis and measured before/after results are in [TONG_QUAN.md](TONG_QUAN.md).

## Attribution and license

Original tutorial by computervisiondeveloper / Computer Vision Engineer (MIT, 2022). Modifications preserve that copyright notice in [LICENSE](LICENSE). Video/data provenance is described in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); the code license is not a new license grant for third-party footage.

References: [Boto3 credentials](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html), [Boto3 retries](https://docs.aws.amazon.com/boto3/latest/guide/retries.html), [DetectLabels](https://docs.aws.amazon.com/rekognition/latest/APIReference/API_DetectLabels.html).
