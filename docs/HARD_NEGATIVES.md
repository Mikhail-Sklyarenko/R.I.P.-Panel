# Hard Negatives (texture FP fix)

Product goal: stop YOLO from boxing **map textures** (crates, walls, cars) as players.

**Do not delete empty map frames.** Teach the model with **empty YOLO labels**.

## Strategy (automated)

```
0. Bootstrap empties    ImportEmptyYoloSplits.bat  → fastest HN seed (~1k frames)
1. Runtime band-aid     EnableFpGuard.bat          → raise conf now
2. Collect HN           EnableHardNegCapture.bat   → walk map, force empty labels
3. Also passive         empty_scene in normal capture (no dets → empty)
4. Promote              BuildHardNegativesFromRaw.bat
5. Optional mine        mine_hard_negatives.py --mode folder|predict
6. Merge + train        BuildProductWithHardNegatives.bat + TrainProductModel.bat
7. Promote weights      EnsureWeights / registry
```

## 0) Fastest path — empty frames from product_v1_bootstrap

Public bootstrap already has ~20% **empty YOLO labels** (map/UI without players).
Do **not** delete them. Import into `sources/hard_negatives` (preserves train/val/test):

```bat
ImportEmptyYoloSplits.bat D:\datasets\product_v1_bootstrap
REM or a USB parent that contains train\ val\ test\
ImportEmptyYoloSplits.bat E:\

BuildProductWithHardNegatives.bat
TrainProductModel.bat --data vendor\csgobot\yolov8\datasets\product_data_hn.yaml --name product_fpfix_v1
```

Mac / offline:

```bash
python vendor/csgobot/yolov8/datasets/import_empty_yolo_splits.py \
  --dataset-root "/Volumes/NO NAME" \
  --out-root vendor/csgobot/yolov8/datasets/sources/hard_negatives \
  --summary vendor/csgobot/yolov8/datasets/manifests/hard_negatives_bootstrap_summary.json
```

Then zip `sources/hard_negatives` to the Train PC if datasets live only there.

`product_v2_ours` is **not** required for this import — use it later as the `ours=` merge source for CT/T positives.

## Roles

| PC | Job |
|----|-----|
| Collector | `EnableHardNegCapture` session (separate from CT soft-label farm) |
| Any farm | `EnableFpGuard` until new weights |
| Train | promote HN → merge `hard_negatives` → fine-tune |

## 1) Immediate FP guard (no retrain)

```bat
EnableFpGuard.bat
call data\fp_guard.env.bat
FarmPanel.bat
```

Sets ~`CSGOBOT_CONFIDENCE=0.58`. Temporary — lowers texture FP; may hide weak CT.

## 2) Hard-neg collector (best automated data)

```bat
EnableHardNegCapture.bat
call data\capture_hardneg.env.bat
FarmPanel.bat
```

- Caps Lock ON, walk **empty** areas: crates, doors, cars, walls (Mirage / Dust2).
- Triggers: `texture_fp` (model fired on texture), `hard_neg_timer`, `empty_scene`.
- **Always empty** `labels_soft` — never reinforce FP as CT/T.

Captures: `vendor/csgobot/data/captures/`

## 3) Promote

```bat
BuildHardNegativesFromRaw.bat
```

→ `vendor/csgobot/yolov8/datasets/sources/hard_negatives/{train,val,test}/`

## 4) Optional offline mine

Known-empty screenshot folder (your 3 examples):

```bat
cd vendor\csgobot
venv\Scripts\python.exe yolov8\datasets\mine_hard_negatives.py --mode folder --images-dir D:\fp_dump
```

Player-free folder; keep only frames where **current** model still fires (true FP mine):

```bat
venv\Scripts\python.exe yolov8\datasets\mine_hard_negatives.py --mode predict --images-dir D:\fp_dump --conf 0.45
```

## 5) Merge into product + train

Preferred (TRAIN PC):

```bat
BuildProductWithHardNegatives.bat
TrainProductModel.bat --data vendor\csgobot\yolov8\datasets\product_data_hn.yaml --name product_fpfix_v1
```

Manual equivalent:

```bat
venv\Scripts\python.exe yolov8\datasets\build_product_dataset.py ^
  --source bootstrap=yolov8/datasets/product_v1_bootstrap ^
  --source ours=yolov8/datasets/sources/our_cs2 ^
  --source hn=yolov8/datasets/sources/hard_negatives ^
  --out-root yolov8/datasets/product_v2_hn ^
  --classes c,ch,t,th --copy-images
```

Soak on crate walls / Dust2 car, then promote `.pt` via registry + `EnsureWeights.bat`.

## Normal CT collector (also helps)

`EnableAutoCapture.bat` now enables **`empty_scene`**: when YOLO sees nothing, saves empty-label backgrounds (passive negatives).  
`BuildOurCs2FromRaw.bat` accepts empties up to **15%**.

Dedicated HN sessions still better for **high-conf** texture FPs (`ct 0.88` on crates).

## Quality gates

- Prefer **500–2000** hard-neg images before calling FP “fixed”.
- Soak: same Mirage A crates / Dust2 car — boxes should vanish or conf collapse.
- CT/T recall must not regress > ~2% (see `CS2_DATASET_STRATEGY.md`).

## Related

- `docs/AUTO_CAPTURE.md`
- `docs/CS2_DATASET_STRATEGY.md`
- `docs/CS2_DATASET_PIPELINE.md`
- `docs/AIM_TUNING.md`
