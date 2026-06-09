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

## VAC / matchmaking

If DM search works **manually** via Steam but fails through the panel (unsigned files / VAC dialog):

1. `git pull` — `cs2_vac_safe_launch: true` (default): `steam -applaunch 730`, **no** FSM `-nosound`/`-novid` flags, **no** overwrite of `game/csgo/cfg/video.txt`, only `farm_panel.cfg` for binds/DM.
2. CS2 **launch options** in Steam must be **empty** (no `-insecure`).
3. Set **1280×720 in-game** manually (VAC-safe mode does not push `video.txt`).
4. Main log shows `cs2 launch: ...` — copy line if VAC persists.
5. One-time: integrity verify CS2 with **normal** Steam, then farm run.

## pywin32 (ArmoryFarm)

```bat
pip show pywin32
python -c "import win32process; print(hasattr(win32process,'AttachThreadInput'))"
```

Should print `True`. (`AttachThreadInput` is in **win32process**, not win32api.)

## Calibration workflow @ 1280×720 (operator)

### Before screenshots

1. `data/config.yaml`: `cs_resolution: "1280x720"`
2. CS2: **В ОКНЕ**, **1280×720**, **16:9**, RU
3. Panel `git pull` (includes client-area window layout fix)

Verify client size (CS2 running, windowed 1280×720):

```bat
python -c "import win32gui; f=[]; e=lambda h,_: f.append(h) if win32gui.IsWindowVisible(h) and 'counter' in (win32gui.GetWindowText(h) or '').lower() else None; win32gui.EnumWindows(e,None); h=f[0]; r=win32gui.GetClientRect(h); print(r[2], 'x', r[3])"
```

Expect `1280 x 720`.

### Screens to send (4 files)

PNG must be **1280×720 client area only** — game content without title bar / desktop.

**Option A — panel artifact:** after manual menu wait, copy `artifacts/<session>/wait_main_menu_launch_*.png` if `img_w=1280`.

**Option B — Win+Shift+S:** crop exactly the game interior (not Steam, not taskbar).

| File name | When to capture |
|-----------|-----------------|
| `main_menu_play.png` | Main menu, tab **ИГРАТЬ** active (orange underline) |
| `play_dm.png` | After ИГРАТЬ: **Бой насмерть** visible + green **Начать** bottom-right |
| `searching.png` | After Начать: matchmaking / «Поиск…» |
| `in_dm.png` | Inside DM: HUD (HP/ammo) visible |

### Sample probe pixels

```bat
python scripts/sample_probe_rgb.py main_menu_play.png 663 43
python scripts/sample_probe_rgb.py main_menu_play.png 663 20
python scripts/sample_probe_rgb.py play_dm.png 667 95
python scripts/sample_probe_rgb.py play_dm.png 1125 691
python scripts/sample_probe_rgb.py in_dm.png 99 661
```

Paste output → update `resources/ui_nav/coords_1280x720.yaml`.

### Click targets (current draft — verify on your PNG)

| Action | Click (1280×720) |
|--------|------------------|
| main_menu_play | 663, 20 (was 736 — hit МАГАЗИН) |
| mode_deathmatch | 667, 95 |
| start_search | 1125, 691 |

If manual test click misses ИГРАТЬ — send PNG, we recalibrate.

## csgobot

```bat
dir vendor\csgobot\run.py
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
