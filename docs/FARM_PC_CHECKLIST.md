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

## 5. YOLO weights (~52 MB, not in git)

Place file:

```
vendor/csgobot/yolov8/cs2_yolov8m_640_augmented_v4.pt
```

Panel startup warns if missing.

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
| Weak aim / carousel crosshair | Set **cs2_sensitivity** in Config #1; install CUDA PyTorch (`check_cuda_torch.py`) |
| `WARN: PyTorch CPU-only` | Install torch+cu124 in csgobot venv; optional **csgobot_require_cuda** in Config #3 |
| False `csgobot: finished ok` after 1s | Fixed — should show `early exit` + stderr tail |
| `retry in_dm wait attempt 2` + 65s | Fixed — soft_peek 1/2 probes; retry skips if already in DM |
| False `level_up` in first seconds | Already fixed (grace period); `git pull` |

## Related docs

- `docs/WINDOWS_FIRST_RUN.md`
- `docs/CSGOBOT_SETUP.md`
- `docs/AI_PC_PROFILE.md`
- `docs/DM_NAV_COORDS.md`
