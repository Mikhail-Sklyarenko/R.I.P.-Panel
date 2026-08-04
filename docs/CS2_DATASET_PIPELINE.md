# CS2 Dataset Pipeline (End-to-End)

This is the practical runbook for building a production-ready CT/T dataset.

## 0) Folder conventions

Work under `vendor/csgobot/yolov8/datasets/`.

- `hf_raw/` - downloaded Hugging Face imagefolder sources.
- `sources/<name>/` - YOLO-formatted normalized sources.
- `product_v1/` / `product_v1_bootstrap/` - merged + split output dataset.

**TRAIN machine only:** `BootstrapDataset.bat` — downloads external dataset, builds, audits, writes manifest.  
**Farm fleet:** do **not** run this. Use `EnsureWeights.bat` (~50 MB `.pt`). See `docs/PRODUCT_MODEL_LIFECYCLE.md`.

## 1) Download a public source (optional bootstrap)

Example (HF CLI):

```bash
huggingface-cli download fvossel/csgo-player-detection \
  --repo-type dataset \
  --local-dir vendor/csgobot/yolov8/datasets/hf_raw/fvossel_cs2
```

Or run full orchestrator (download + convert + merge + audit + manifest):

```bash
python vendor/csgobot/yolov8/datasets/run_product_pipeline.py \
  --hf-repo fvossel/csgo-player-detection \
  --hf-local-dir hf_raw/fvossel_cs2 \
  --hf-data-subdir data \
  --source ours=vendor/csgobot/yolov8/datasets/sources/our_cs2 \
  --out-root product_v1 \
  --classes c,ch,t,th \
  --train-pct 80 \
  --val-pct 10 \
  --dedup-stem \
  --manifest-out manifests/product_v1_manifest.json
```

## 2) Convert HF imagefolder -> YOLO

```bash
python vendor/csgobot/yolov8/datasets/hf_to_yolo.py \
  --hf-root vendor/csgobot/yolov8/datasets/hf_raw/fvossel_cs2/data \
  --out-root vendor/csgobot/yolov8/datasets/sources/fvossel_yolo \
  --splits train,validation
```

Notes:
- If split name is `validation`, either keep it as source-only split or copy to `val` before merge.
- Keep class IDs consistent with your model (`c,ch,t,th` mapping).

## 3) Add our own CS2 captures (required)

Prepare your own YOLO source:

```
vendor/csgobot/yolov8/datasets/sources/our_cs2/
  train/images
  train/labels
  val/images
  val/labels
  test/images
  test/labels
```

Focus on CT-heavy coverage (close/mid/far, varied maps, occlusion, movement).

## 4) Build product dataset from multiple sources

```bash
python vendor/csgobot/yolov8/datasets/build_product_dataset.py \
  --source fvossel=vendor/csgobot/yolov8/datasets/sources/fvossel_yolo \
  --source ours=vendor/csgobot/yolov8/datasets/sources/our_cs2 \
  --out-root vendor/csgobot/yolov8/datasets/product_v1 \
  --classes c,ch,t,th \
  --train-pct 80 \
  --val-pct 10 \
  --dedup-stem
```

What this gives:
- deterministic scene-key split (reduces leakage),
- merged source names in output filenames,
- per-split class and CT/T share report.

## 5) Audit quality gates (must pass)

```bash
python vendor/csgobot/yolov8/datasets/audit_dataset.py \
  --root vendor/csgobot/yolov8/datasets/product_v1 \
  --names c,ch,t,th
```

Gate expectations:
- `missing_labels=0`, `missing_images=0`,
- `parse_errors=0`,
- `class_oob=0`,
- `bbox_invalid=0`.

## 6) Train (TRAIN machine only)

```bat
TrainProductModel.bat
```

Or:

```bash
vendor/csgobot/venv/Scripts/python.exe vendor/csgobot/yolov8/train_product.py \
  --data vendor/csgobot/yolov8/datasets/product_data.yaml
```

## 7) Promote weights to the farm fleet

```bash
python scripts/promote_weights.py path/to/best.pt \
  --version v0.2.0-ctfix \
  --filename cs2_yolov8m_640_product_v1.pt \
  --dataset-manifest vendor/csgobot/yolov8/datasets/manifests/product_v1_bootstrap_manifest.json
```

1. Host the `.pt` (GitHub Release / CDN).
2. Add artifact + set `active` in `resources/csgobot/weights_registry.json`.
3. Farm PCs: `git pull` && `EnsureWeights.bat`.

## 8) Release criteria before setting registry `active`

- CT uplift target:
  - `c` recall +8% minimum vs current production baseline.
  - `ch` recall +10% minimum.
- Regression guard:
  - `t`/`th` recall drop <= 2%.
- Live soak on 1–2 farm PCs:
  - no false-positive spike during long farm sessions.

## 9) Storage policy

- Keep dataset binaries out of core git repo and **off farm PCs**.
- Keep scripts/config/docs and dataset manifests in git.
- Store heavy assets in HF/DVC/object storage with explicit version tags.
- Runtime artifact channel: `weights_registry.json` + hosted `.pt`.

## 10) Dataset provenance registry

- `vendor/csgobot/yolov8/datasets/source_registry.yaml` tracks approved/conditional sources and rationale.
- Update this file whenever adding a new external source.
