# Farm PC checklist (Level 0)

One-time setup on the Windows farm machine. After this, **Start Farm** should reach `loot_ok` → `DONE` without manual steps.

## 1. Repo and panel

```powershell
cd C:\Users\ArmoryFarm\Downloads\R.I.P.-Panel-main\farm-panel-prototype
git pull
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

Run panel: `FarmPanel.bat` or `python -m panel.main`.

## 2. Config #1 (panel UI)

| Field | Value |
|-------|--------|
| `steam_path` | Path to `steam.exe` |
| `cs2_path` | Path to `cs2.exe` |
| **`trade_offer_link`** | **Required** — Trade URL of storage account |
| **`cs2_sensitivity`** | CS2 console `sensitivity` (default `2.1`) → csgobot X360 |
| **`cs_resolution`** | `1280x720` for AI farm + minimap nav |
| `auto_collect_drop` | `true` |
| `bot_mode` | `ai` or `auto` |
| `cs_resolution` | `1280x720` (AI farm PC) |
| `cs2_main_menu_wait_timeout_sec` | `60` (default); raise to `120` if slow PC |

### Trade URL (storage)

1. Log into storage Steam account in browser.
2. Inventory → **Trade Offers** → **Who can send me Trade Offers?**
3. Copy link, format:

```
https://steamcommunity.com/tradeoffer/new/?partner=XXXXXXXX&token=YYYYYYYY
```

Paste into **trade_offer_link** → **Save Config**.

Empty link → session ends with **`loot_failed`**, not `DONE`.

## 3. Accounts

- `data/import/logpass.txt` + `data/import/maFiles/`
- Utils → **Import from logpass**

See `docs/FSM_ACCOUNT_IMPORT.md`.

## 4. csgobot venv

```powershell
cd vendor\csgobot
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\pip install pygrabber pyyaml
.\venv\Scripts\python tools\preflight.py
.\venv\Scripts\python tools\check_cuda_torch.py
```

`preflight.py` → JSON `"ok": true`, `"cuda_available": true`. `check_cuda_torch.py` → `"cuda": true` and GPU name.

Nav preflight (when Config #3 **csgobot_nav_enabled** is on):

```powershell
.\venv\Scripts\python tools\nav_preflight.py
set CSGOBOT_NAV_PACK=auto
.\venv\Scripts\python tools\nav_preflight.py
```

Expected auto: `"ok": true`, `"packs_ok": ["dust2_dm", "mirage_dm"]`. Panel startup log shows `csgobot nav: auto preflight ok (dust2_dm v1.2.0, mirage_dm v1.0.0)`.

**Mirage soak (PR-N6):** 30+ min Mirage DM with `csgobot_nav_pack=auto` — log `nav: auto pack mirage_dm` and `nav_metrics` every 30s (`pose_valid_pct` ≥ 80%). See `docs/NAV_IMPLEMENTATION.md`.

**Fleet nav metrics (PR-N7):** Panel → **Nav Fleet** tab or `python scripts\nav_fleet_report.py`. JSONL: `data\logs\nav_metrics.jsonl`.

**Multi-PC fleet (PR-N8):** Copy each PC's `nav_metrics.jsonl` to `data\fleet_inbox\`. Panel → **Import fleet inbox** or `python scripts\nav_fleet_import.py`. Tune goals: **Nav Packs** tab → Save override → `data\nav_packs\`.

**HTTP fleet push (PR-N9):** Master PC → **Nav Fleet** → **Start collector**. Farm PC → Config #3 `nav_fleet_push_url=http://<master>:8765/api/v1/nav_metrics`. Visual goal editor: **Nav Packs** → click radar map.

See `docs/NAV_IMPLEMENTATION.md`.

## 5. YOLO weights (~52 MB, not the dataset)

**Farm PCs download only the production `.pt`.** Never run `BootstrapDataset.bat` here (multi-GB training data).

```bat
EnsureWeights.bat
```

This reads `resources/csgobot/weights_registry.json`, downloads the active artifact, and verifies sha256.

Expected path (baseline):

```
vendor/csgobot/yolov8/cs2_yolov8m_640_augmented_v4.pt
```

Panel startup warns if missing. Full lifecycle: `docs/PRODUCT_MODEL_LIFECYCLE.md`.

## 6. OBS Virtual Camera

csgobot uses `GRABBER_TYPE = "obs_vc"` in `vendor/csgobot/run.py`.

1. OBS → **Settings → Video** → Base resolution **1280×720**
2. Source: **Window Capture** → Counter-Strike 2
3. **Start Virtual Camera** (keep on between sessions, or start before farm)

Check from csgobot venv:

```powershell
.\venv\Scripts\python tools\check_obs_vc.py
```

Exit 0 = device found. Panel startup warns if missing.

See `docs/CSGOBOT_SETUP.md`.

## 7. CS2 client

- Windowed **1280×720**
- Panorama UI (RU OK with `coords_1280x720.yaml`)
- Deathmatch farm profile applied by panel

## 8. Success log chain

After **Start Farm** (one account, no manual input):

```
session_start
steam_login_ok
cs2_ok
in_menu
in_dm
combat_ai_started (auto_activate)
csgobot: nav pack dust2_dm v1.2.0 goals=['mid', 'bombsite_a']
farming
level_up
drop_picked
loot_ok
session_done
```

Must **not** appear: `loot_failed`, `session_failed`, long idle on main menu when menu is already visible.

## 9. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `loot_failed (trade_offer_link empty)` | Set trade URL in Config #1 |
| `OBS Virtual Camera not found` | Start OBS, enable Virtual Camera |
| 60s menu wait then DM works | Recalibrate probe: screenshot + `scripts/sample_probe_rgb.py` → `coords_1280x720.yaml` |
| `combat_fallback` / `early exit` instantly | Check `data/logs/csgobot_*.stderr.txt`; run `tools\preflight.py`; OBS VC |
| Weak aim / carousel crosshair | Set **cs2_sensitivity** in Config #1; CUDA torch; PR-6c anti-jitter (`git pull`) |
| Aim jerky / slideshow pacing | PR-A1: need `aim_hz=120` in log; `CSGOBOT_AIM_MOUSE_HZ=120`; step_max 18–22 |
| Aim hunts up/down on target | PR-A1.1 settle: `settle=True` in debug; ↑ `CSGOBOT_AIM_SETTLE_PX` / unlock; coast min speed |
| Slow aim / late fire / low K/D | PR-A1.2.1: log `(A1.2.1)`; if slow try `CSGOBOT_SMOOTHING=2.0` / `CSGOBOT_AIM_MOUSE_STEP_MAX=24`; if wobble ↑ settle / ↓ `CSGOBOT_AIM_NEAR_Y_SCALE` |
| Screen jitters on running targets | PR-6c defaults; `CSGOBOT_AIM_DEBUG=1` → check `lead_stable`, `move=False` in band |
| Misses on running enemies | `CSGOBOT_LEAD_MS=100`; `CSGOBOT_BODY_FALLBACK_MS=200`; `CSGOBOT_AIM_DEBUG=1` |
| No detect at long range | PR-6f: ROI zoom + conf 0.50; `CSGOBOT_DETECT_DEBUG=1`; try `CSGOBOT_CONFIDENCE=0.45` |
| Bot farms with pistol/SMG | PR autobuy: `git pull`; restart CS2; log `autobuy: startup burst` / `autobuy: respawn stagger` |
| Bot walks into walls / no nav | Config #3 `csgobot_nav_enabled`; run `tools\nav_preflight.py`; check `nav: preflight ok` in stderr log |
| `nav: preflight failed` | Missing `resources/nav/` — `git pull`; macro patrol still runs |
| Slow single-tap fire | PR-6d default `hold`; or `CSGOBOT_SHOOT_MODE=burst` + `BURST_SIZE=5` |
| `WARN: PyTorch CPU-only` | Install torch+cu124 in csgobot venv; optional **csgobot_require_cuda** in Config #3 |
| False `csgobot: finished ok` after 1s | Fixed — should show `early exit` + stderr tail |
| `retry in_dm wait attempt 2` + 65s | Fixed — soft_peek 1/2 probes; retry skips if already in DM |
| False `level_up` in first seconds | Already fixed (grace period); `git pull` |

## Related docs

- `docs/WINDOWS_FIRST_RUN.md`
- `docs/CSGOBOT_SETUP.md`
- `docs/AI_PC_PROFILE.md`
- `docs/DM_NAV_COORDS.md`
