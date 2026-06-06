# AI Farm PC profile (1280×720 windowed)

Dedicated PC: **farm + YOLO (csgobot)**. Lite PCs stay on **360×270**.

## Hardware

| Component | Minimum |
|-----------|---------|
| GPU | NVIDIA 6+ GB VRAM (GTX 1660 / RTX 3050+) |
| RAM | 16 GB |
| OS | Windows 10/11 |
| Monitor | 1920×1080 (CS2 window 1280×720, not fullscreen) |

## CS2 video (in-game)

| Setting | RU label | Value |
|---------|----------|--------|
| Display mode | Режим отображения → **В ОКНЕ** | Windowed |
| Resolution | Разрешение | **1280 × 720** |
| Aspect | Формат экрана | **16:9** |
| Language | Panorama | **RU** |

Launcher deploys `resources/cs2/profiles/1280x720/cs2_video.txt` → `game/csgo/cfg/video.txt` when `cs_resolution: "1280x720"`.

## Config (`data/config.yaml`)

Copy from `docs/config.ai_pc.example.yaml`:

```yaml
cs_resolution: "1280x720"
bot_mode: ai
steam_path: "C:\\Program Files (x86)\\Steam\\steam.exe"
cs2_path: "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Counter-Strike Global Offensive\\game\\bin\\win64\\cs2.exe"
```

## Resource profiles

| cs_resolution | Files |
|---------------|--------|
| `360x270` | default FSM / lite PC |
| `1280x720` | `coords_1280x720.yaml`, `drop_slots_1280x720.yaml`, `level_probes_1280x720.yaml`, `cs2/profiles/1280x720/cs2_video.txt` |

Missing profile → startup warning + `UiNavError` at runtime.

**Current 1280×720 coords:** `calibration: armoryfarm_screenshot_2025-06` from operator screenshots (ИГРАТЬ + БОЙ НАСМЕРТЬ + НАЧАТЬ). Fixture: `tests/fixtures/ai_pc/1280x720/main_menu_play_dm.png`. Still **draft** for `searching` / `in_dm` / drop — send live grabs.

## pywin32 (ArmoryFarm)

```bat
pip show pywin32
python -c "import win32api; print(hasattr(win32api,'AttachThreadInput'))"
```

If `False`: reinstall pywin32 for the same Python as the panel. Code falls back without `AttachThreadInput`, but fix env for reliable focus/capture.

## csgobot

```bat
git submodule update --init vendor/csgobot
cd vendor\csgobot
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

`bot_mode: ai` → subprocess; `auto` falls back to simple if venv missing.

## Calibration checklist

PNG must be **exactly 1280×720 client area** (not full desktop 1920×1080).

| File | Screen |
|------|--------|
| `main_menu_play.png` | Main menu, tab **ИГРАТЬ** active |
| `play_dm_screen.png` | Play mode selection, Deathmatch visible |
| `in_dm.png` | In DM match, HUD visible |
| `care_package.png` | Weekly drop selection |

Sample RGB:

```bat
python scripts/sample_probe_rgb.py main_menu_play.png 771 69
```

Update `resources/ui_nav/coords_1280x720.yaml` probes/clicks; set `calibration: armoryfarm_<session>`.

## Acceptance log (AI-PC)

```
launcher layout: 1 CS window(s) → 1280x720
waiting for CS2 main menu…
cs2 menu ready (strict 2/2)  OR  controlled fallback @ main_menu_play (NOT shop)
dm click main_menu_play @(…,…)
dm click mode_deathmatch @(…,…)
dm click start_search @(…,…)
in_dm
combat_ai_started
farming
```

**Must NOT:** clicks on МАГАЗИН / IEM Cologne; persistent `[0,0,0]` probes; `AttachThreadInput` crash.

## Upgrade to 1080p

Add `coords_1920x1080.yaml` + profile folder under `resources/cs2/profiles/1920x1080/`; set `cs_resolution: "1920x1080"`. Do not autoscale from 360 or 720 alone.
