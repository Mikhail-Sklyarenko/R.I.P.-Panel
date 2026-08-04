# Product dataset (TRAIN machine)

## Farm PCs
Do **not** bootstrap here. Run `EnsureWeights.bat` (~50 MB `.pt` only).
See `docs/PRODUCT_MODEL_LIFECYCLE.md`.

## Train PC — build dataset

From repo root:

```bat
BootstrapDataset.bat
```

This will:
1. ensure `huggingface_hub` in csgobot venv;
2. download `fvossel/csgo-player-detection` via Python API (`snapshot_download`);
3. convert HF → YOLO;
4. build `product_v1_bootstrap`;
5. audit quality;
6. write `manifests/product_v1_bootstrap_manifest.json`.

No `huggingface-cli` / PATH required (Windows-safe).

## Train PC — train + promote

```bat
TrainProductModel.bat
python scripts\promote_weights.py path\to\best.pt --version v0.2.0-ctfix --filename cs2_yolov8m_640_product_v1.pt
```

Host `.pt`, update `resources/csgobot/weights_registry.json`, then farm fleet runs `EnsureWeights.bat`.

YOLO data yaml: `product_data.yaml` (points at `product_v1_bootstrap`).
