# Auto Capture (CT dataset collector)

Product goal: collect **real farm frames** automatically (no manual screenshots),
soft-label them, promote into `sources/our_cs2`, then retrain.

This does **not** depend on already-good CT detect. Capture uses timers + team=T boost + soft/miss triggers.

## Roles

| PC | Job |
|----|-----|
| **Collector farm** (1–2 PCs) | `CSGOBOT_AUTO_CAPTURE=1` while farming |
| **Other farm PCs** | capture OFF (default) |
| **Train PC** | `BuildOurCs2FromRaw.bat` → merge → `TrainProductModel.bat` |

Fleet still only downloads `.pt` via `EnsureWeights.bat`.

## Enable on a collector PC

```bat
EnableAutoCapture.bat
call data\capture_collector.env.bat
FarmPanel.bat
```

Or manually:

```bat
set CSGOBOT_AUTO_CAPTURE=1
set CSGOBOT_CAPTURE_INTERVAL_SEC=1.2
set CSGOBOT_CAPTURE_MAX_PER_HOUR=400
set CSGOBOT_CONF_C=0.38
set CSGOBOT_CONF_CH=0.40
```

Play DM. Prefer sessions as **T** (enemies = CT) — highest value frames.

Captures write to:

```text
vendor/csgobot/data/captures/<pc_id>/<session_id>/
  images/
  meta/
  labels_soft/
```

Limits: max frames/hour, max MB, async writer (aim/detect not blocked), near-dupe hash reject.

## Triggers

- `timer` / `timer_t` — periodic while activated (faster when team=T)
- `soft_ct` — CT box in soft confidence band
- `roi_miss` — ROI ran but no enemies
- `enemy_appear` — enemy just appeared

## Promote to our_cs2

On machine that has the captures (or after copying `data/captures`):

```bat
BuildOurCs2FromRaw.bat
```

This filters, dedups, splits, and copies into:

`vendor/csgobot/yolov8/datasets/sources/our_cs2/`

## Then train

Merge `our_cs2` with public bootstrap (see `docs/CS2_DATASET_PIPELINE.md`), then:

```bat
TrainProductModel.bat
```

Soak → `scripts/promote_weights.py` → registry → fleet `EnsureWeights.bat`.

## Quality notes

- Soft labels are **pseudo-labels** — noisy. Gate with promote script + live soak.
- Do not commit captures to git.
- Re-label shards after a major weight change if needed.
- Target: CT box share ≥ ~55% in accepted `our_cs2` before calling the CT problem “solved”.

## Related

- Lifecycle: `docs/PRODUCT_MODEL_LIFECYCLE.md`
- Strategy: `docs/CS2_DATASET_STRATEGY.md`
- Class conf (combat): `docs/AIM_TUNING.md`
