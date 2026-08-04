# Dataset Quickstart (Operators)

**Same model as upstream csgobot:** images/labels are **not in git**.  
Git has scripts + empty `sources/our_cs2` scaffold. Data is downloaded externally.

## Windows (recommended): one click

From repo root after `git pull`:

```bat
BootstrapDataset.bat
```

This will:
1. ensure `huggingface_hub` in csgobot venv;
2. download `fvossel/csgo-player-detection`;
3. convert HF → YOLO;
4. build `product_v1_bootstrap`;
5. audit quality;
6. write `manifests/product_v1_bootstrap_manifest.json`.

Requires: `vendor\csgobot\venv` already created (`pip install -r requirements.txt`).

## Manual / Mac / Linux

```bash
python vendor/csgobot/yolov8/datasets/run_product_pipeline.py \
  --workdir vendor/csgobot/yolov8/datasets \
  --hf-repo fvossel/csgo-player-detection \
  --hf-local-dir hf_raw/fvossel_cs2 \
  --hf-data-subdir data \
  --out-root product_v1_bootstrap \
  --classes c,ch,t,th \
  --train-pct 80 \
  --val-pct 10 \
  --dedup-stem \
  --manifest-out manifests/product_v1_bootstrap_manifest.json
```

## Merge with your own CS2 captures (later)

1. Put YOLO pairs into `sources/our_cs2/{train,val,test}/{images,labels}`.
2. Re-run pipeline with both sources:

```bash
python vendor/csgobot/yolov8/datasets/run_product_pipeline.py \
  --workdir vendor/csgobot/yolov8/datasets \
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

## Audit only

```bash
python vendor/csgobot/yolov8/datasets/audit_dataset.py \
  --root vendor/csgobot/yolov8/datasets/product_v1_bootstrap \
  --names c,ch,t,th
```

## Gate checklist before training

- audit exit code is `0`;
- no `bbox_invalid`, no parse errors;
- CT share (`c+ch`) meets strategy target;
- manifest exists and dataset hash is recorded with training run.

See also: `docs/CS2_DATASET_STRATEGY.md`, `docs/CS2_DATASET_PIPELINE.md`.
