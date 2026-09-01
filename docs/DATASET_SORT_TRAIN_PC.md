# Dataset sort — Train PC instructions (after Mac export)

This run sorted **existing archives** (no new live screenshots):

- Merged **hard negatives** (~1669 frames: archive HN + empty captures + dedup).
- **Quarantined** all `our_cs2_BAD` (482) and soft-label captures (482) — **not for train**.
- Cleared `sources/our_cs2` (empty scaffold only).
- **Bootstrap on Mac: COMPLETE** (5473 images) after USB reconnected.

## Copy to Train PC (`C:\Users\FermK\Downloads\R.I.P.-Panel`)

### Option A — copy from Mac repo (if you sync/git large files)

Copy both folders:

```
vendor\csgobot\yolov8\datasets\sources\hard_negatives   (~1670 images)
vendor\csgobot\yolov8\datasets\product_v1_bootstrap   (~5473 images, ~4GB)
```

### Option B — from USB RAR on Train PC

```bat
ExtractDatasetArchives.bat
```

Then copy only `hard_negatives` from Mac if you already ran sort there, **or** use `hard_negatives.rar` from USB + run `RunSortDatasetExport.bat` after extracting `captures.rar`.

Verify bootstrap:

```bat
dir vendor\csgobot\yolov8\datasets\product_v1_bootstrap\train\images
```

Expect **thousands** of `.png` files.

### 3) Empty our_cs2 (required)

Ensure **no images** in:

```
vendor\csgobot\yolov8\datasets\sources\our_cs2\train\images
```

Only `.gitkeep` is OK. **Do not** restore `our_cs2_BAD` into `our_cs2`.

### 4) Quarantine manifests (optional, for audit)

Copy from Mac:

```
dataset_export\quarantine\*.json
```

These list poisoned files — **never merge into train**.

## Train (golden v1)

```bat
cd /d C:\Users\FermK\Downloads\R.I.P.-Panel
EnsureWeights.bat
BuildProductWithHardNegatives.bat
```

Must show: `our_cs2 empty/missing — building bootstrap + hn only`

```bat
TrainProductModel.bat --data vendor\csgobot\yolov8\datasets\product_data_hn.yaml --name product_golden_v1
```

After soak:

```bat
copy /Y vendor\csgobot\yolov8\runs\detect\product_golden_v1\weights\best.pt vendor\csgobot\yolov8\cs2_yolov8m_640_augmented_v4.pt
```

Test **without** `EnableFpGuard.bat`.

## Optional: re-run sort on Train PC (full bootstrap)

If you copied `dataset_staging` from USB rars:

```bat
cd /d C:\Users\FermK\Downloads\R.I.P.-Panel
RunSortDatasetExport.bat
```

Then Build → Train again.

## What was quarantined (do not train)

| Source | Count | Reason |
|--------|-------|--------|
| our_cs2_BAD | 482 | Soft-label poison (texture as player) |
| captures soft-label | 482 | Non-empty labels from farm capture |
| captures empty | 555 | **Added to HN** (good) |

See `dataset_export\SORT_REPORT.json` on Mac for full stats.
