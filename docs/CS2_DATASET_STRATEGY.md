# CS2 Dataset Strategy (CT Detect Fix)

Goal: improve CT (`c`/`ch`) detection reliability without regressing T (`t`/`th`) and keep the pipeline reproducible for future releases.

## 1) Public dataset review and filter

### Candidate A (recommended base): `fvossel/csgo-player-detection`
- URL: https://huggingface.co/datasets/fvossel/csgo-player-detection
- Pros:
  - Explicit CS2 framing in dataset card.
  - Team/body-head split, with class counts documented.
  - Includes negatives and split notes (block-wise split).
  - Practical details about crop geometry (640x640 native center crop).
- Risks:
  - Format is HF `imagefolder` + `metadata.jsonl` (not YOLO txt directly).
  - Research-oriented licensing/derivative Valve assets constraints.
- Decision: **Use as reference/base source after legal check and format conversion.**

### Candidate B (conditional source): Kaggle `Counter Strike 2 Body and Head Classification`
- URL: https://www.kaggle.com/datasets/merfarukgnaydn/counter-strike-2-body-and-head-classification
- Pros:
  - Widely referenced by other CS2 detector projects.
  - Directly aligned class semantics (`ct_body`, `ct_head`, `t_body`, `t_head`).
- Risks:
  - License clarity may be limited or absent depending on snapshot.
  - Redistribution rights can be unclear.
- Decision: **Use only if license terms are accepted for our use-case.**

### Candidate C (optional experiments only): Roboflow Universe community datasets
- Example URLs:
  - https://universe.roboflow.com/smandres/cs2-player-detection-oysvw
  - https://universe.roboflow.com/1-swrjn/cs2-player-models-main-1-jpszb
- Pros:
  - Easy export and quick baseline experiments.
- Risks:
  - Quality/label consistency varies by author.
  - Different geometries/classes and unknown capture conditions.
- Decision: **Do not use as primary training source. Use only for controlled ablations.**

## 2) Best strategy for our own dataset

### Source policy (hard rule)
- Primary data must come from **real CS2 gameplay captures** in our target runtime conditions.
- Do not use random internet CT images as a main source.
- Do not rely on synthetic/generated images as a main source.

Why: domain match beats volume. Our issue is domain shift + class robustness for CT.

### Data specification
- Resolution: keep native source and stable preprocessing.
- Training geometry: preserve inference geometry consistency (no accidental scale mismatch).
- Classes:
  - `c`: CT body
  - `ch`: CT head
  - `t`: T body
  - `th`: T head

### Collection targets (Phase 1)
- Total labeled images: 6k-10k.
- CT emphasis:
  - `c` + `ch` boxes should be at least 55% of all positive boxes.
  - `ch` should not lag `th` by more than 10% relative share.
- Scenario mix:
  - Close / medium / far distances.
  - Different maps and lighting conditions.
  - Movement states (strafe, jump, peek, crouch).
  - Partial occlusions and non-target clutter.
  - Both team perspectives.

### Labeling workflow
1. **Preferred (product):** farm auto-capture (`docs/AUTO_CAPTURE.md`) + soft labels + `BuildOurCs2FromRaw.bat`.
2. Optional: auto-label refresh with newer weights on raw shards.
3. Human correction is **not required** for MVP; soak gates replace manual QC.
4. Second pass QC on sampled shards is optional for major releases.

### Quality gates before training
- Broken label files: 0.
- Missing image/label pairs: 0.
- Out-of-range YOLO boxes: 0.
- Duplicate-near-identical frames: controlled (drop obvious burst duplicates).
- Class balance constraints above are met (collector should bias team=T sessions).

## 3) Training and release policy

### Training policy
- Start from current production weights.
- Keep one immutable holdout set from our own captures.
- Track per-class metrics (`c`, `ch`, `t`, `th`) and not only global mAP.

### Go/No-go metrics (release gate)
- CT recall uplift vs previous production model:
  - `c` recall: +8% minimum.
  - `ch` recall: +10% minimum.
- No major regression:
  - `t` and `th` recall drop <= 2%.
- Precision floor:
  - No FP explosion in live farm soak.

### Deployment policy
- Version weights as immutable artifacts (`weights-vX.Y.Z-ctfix.pt`).
- Log dataset lineage and training config hash with each weight.
- Promote only after farm soak on both teams.

## 4) Repository/storage policy

- Keep scripts/configs/docs in git.
- Keep large dataset assets outside core repo:
  - HF dataset storage, DVC remote, or object storage.
- Keep a manifest in git with:
  - dataset version,
  - source provenance,
  - split checksums,
  - class counts.
- **Fleet policy:** farm PCs receive only versioned `.pt` via
  `resources/csgobot/weights_registry.json` + `EnsureWeights.bat`.
  Never distribute `hf_raw/` / `product_v1_*` to the farm fleet.

## 5) Immediate execution plan

**Train machine (once):**

1. `BootstrapDataset.bat` → `product_v1_bootstrap` + manifest.
2. Audit must pass (`audit_dataset.py` / pipeline gate).
3. Optional: merge `sources/our_cs2` CT-heavy captures → rebuild product set.
4. `TrainProductModel.bat` (fine-tune from current production weights).
5. `scripts/promote_weights.py` → host `.pt` → update registry `active`.
6. Soak 1–2 farm PCs → roll `EnsureWeights.bat` to fleet.

**Farm machines (always):**

1. `git pull`
2. `EnsureWeights.bat` (~50 MB)
3. Run panel — no dataset download.

Canonical product doc: `docs/PRODUCT_MODEL_LIFECYCLE.md`.  
Commands: `docs/CS2_DATASET_PIPELINE.md`.

---

This strategy deliberately prioritizes reproducibility, legal clarity, and real CS2 domain coverage over quick-but-fragile shortcuts.
