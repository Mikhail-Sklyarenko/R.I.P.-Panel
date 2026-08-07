# Product Model Lifecycle (Farm vs Train)

Senior rule: **the fleet never downloads the training dataset.**

| Role | Machine | What lives there | Size |
|------|---------|------------------|------|
| **Farm** | many PCs | code + one production `.pt` | ~50 MB weights |
| **Train** | one PC / Colab / server | HF raw + `product_v1_*` + train runs | multi-GB |

This matches upstream csgobot: heavy data outside git; runtime ships weights only.

## Farm PC (every machine)

```bat
git pull
EnsureWeights.bat
FarmPanel.bat
```

- Registry: `resources/csgobot/weights_registry.json` (active version, URL, sha256).
- Tool: `scripts/ensure_weights.py` (download + size + sha256 check).
- **Do not** run `BootstrapDataset.bat` or `TrainProductModel.bat` on farm boxes.

### Collector farm PC (1–2 machines only)

```bat
EnableAutoCapture.bat
call data\capture_collector.env.bat
FarmPanel.bat
```

Writes frames to `vendor/csgobot/data/captures/` (gitignored).  
See `docs/AUTO_CAPTURE.md`.

## Train PC (once per model generation)

1. `BootstrapDataset.bat` — build `product_v1_bootstrap` + audit + manifest.  
2. Optional: collector captures → `BuildOurCs2FromRaw.bat` → merge `sources/our_cs2`.  
2b. Texture FP: `ImportEmptyYoloSplits.bat` (bootstrap empties) and/or `EnableHardNegCapture.bat` → `BuildHardNegativesFromRaw.bat` → `BuildProductWithHardNegatives.bat` (`docs/HARD_NEGATIVES.md`).  
3. `TrainProductModel.bat` — fine-tune from current production `.pt`.  
4. `python scripts/promote_weights.py runs/.../best.pt --version v0.2.0-ctfix --filename ...`  
5. Host the `.pt` (GitHub Release / CDN), put real `url` in registry, set `active`.  
6. Soak on **1–2** farm PCs → then `git pull && EnsureWeights.bat` on the fleet.

## Release gates (before setting `active`)

From `docs/CS2_DATASET_STRATEGY.md`:

- CT (`c`/`ch`) recall uplift vs baseline; T (`t`/`th`) regression ≤ 2%.
- Live soak: no FP spike on long farm sessions.
- Registry entry must include sha256 + size_bytes + dataset_manifest pointer.

## What is “product dataset”

Immutable YOLO tree under `vendor/csgobot/yolov8/datasets/product_v1_*` plus
`manifests/*_manifest.json`. Binaries stay **out of git**; scripts + manifests +
`product_data.yaml` stay **in git**.

Farm PCs never need that tree.

## Related docs

- Strategy: `docs/CS2_DATASET_STRATEGY.md`
- Dataset E2E: `docs/CS2_DATASET_PIPELINE.md`
- Farm setup: `docs/FARM_PC_CHECKLIST.md`
- csgobot runtime: `docs/CSGOBOT_SETUP.md`
