# Dataset export summary (Mac — USB reconnected)

## Ready for Train PC

| Item | Count / status |
|------|----------------|
| `product_v1_bootstrap` | **5473** images (full extract) |
| `sources/hard_negatives` | **1670** images (merged, deduped) |
| `sources/our_cs2` | empty — safe for Build |
| Poison BAD + soft captures | **482 + 482** — manifests only |

## Train PC

See `docs/DATASET_SORT_TRAIN_PC.md`.

Quick:

```bat
BuildProductWithHardNegatives.bat
TrainProductModel.bat --data vendor\csgobot\yolov8\datasets\product_data_hn.yaml --name product_golden_v1
```

Use **full** `product_v1_bootstrap` (not a trimmed copy — tiny-box filter was too aggressive for player recall).
