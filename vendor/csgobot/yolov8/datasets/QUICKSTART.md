# Dataset Quickstart (Operators)

All commands run from project root.

## 1) Build product dataset (recommended)

```bash
python vendor/csgobot/yolov8/datasets/run_product_pipeline.py \
  --workdir vendor/csgobot/yolov8/datasets \
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

## 2) Audit any YOLO dataset

```bash
python vendor/csgobot/yolov8/datasets/audit_dataset.py \
  --root vendor/csgobot/yolov8/datasets/product_v1 \
  --names c,ch,t,th
```

## 3) Build manifest only

```bash
python vendor/csgobot/yolov8/datasets/make_manifest.py \
  --root vendor/csgobot/yolov8/datasets/product_v1 \
  --classes c,ch,t,th \
  --source hf=vendor/csgobot/yolov8/datasets/sources/hf_converted \
  --source ours=vendor/csgobot/yolov8/datasets/sources/our_cs2 \
  --out vendor/csgobot/yolov8/datasets/manifests/product_v1_manifest.json
```

## 4) Gate checklist before training

- audit exit code is `0`;
- no `bbox_invalid`, no parse errors;
- CT share (`c+ch`) meets strategy target;
- manifest exists and dataset hash is recorded with training run.
