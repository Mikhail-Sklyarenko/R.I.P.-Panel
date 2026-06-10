# DM UI navigation coordinates

Прототип: **solo Deathmatch**. Не использует `../settings/fsm.cfg` (Wingman / scrimcomp2v2).

## Версия и разрешение

| Параметр | Значение |
|----------|----------|
| CS2 build (калибровка) | **2025-06 Panorama RU** |
| Default (lite / FSM) | **360×270** — `coords_360x270.yaml` |
| AI Farm PC | **1280×720** windowed — `coords_1280x720.yaml` (см. `docs/AI_PC_PROFILE.md`) |
| Выбор профиля | `config.cs_resolution` → `resolve_cs_coords_path()` |
| Масштаб hwnd | `load_nav_coords_for_hwnd` — autoscale client rect к **base yaml**, не к 360 |

Если client area ≠ base профиля (например **375×308** при base 360×270), в Main log:  
`CS2 client … differs from coords profile …; autoscaling coords to client`

## RU tab bar @ 360×270

| Вкладка | ~X (центр) | Примечание |
|---------|------------|------------|
| ИНВЕНТАРЬ | ~115 | |
| **СНАРЯЖЕНИЕ** | **~168** | **ложный main_menu** если probes сюда |
| **ИГРАТЬ** | **~217** | `main_menu_play` + probes |
| МАГАЗИН | ~255 | |

## ArmoryFarm z3l9272eg3 (v4 probes + v5 capture)

**v4:** orange @ **(217, 26)**, text @ **(218, 13)** — fixture `tests/fixtures/armoryfarm/z3l9272eg3/`.

**v5 (capture/focus):**
- `last@(217,26)=[0,0,0]` = **чёрный grab**, не «не те coords» — не переходить на 720p
- `capture_client` использует **`focus_window`** (как клики), не голый `SetForegroundWindow`
- Launcher: **`move_all_cs_windows` до** `wait_for_cs2_main_menu` → `launcher layout: …`
- Black frame: `capture_suspect_black` + refocus retry (1× per poll)
- dm retry после clicks: **`dm nav: retry in_dm wait`** — без повторного 60s menu wait

**Probes ≠ mouse:** gate читает RGB; курсор — после wait или controlled fallback @217.

## Таймауты (config.yaml)

| FSM `settings.json` | AppConfig | Default |
|---------------------|-----------|---------|
| `GAME_SEARCH_TIMEOUT` | `game_search_timeout_sec` | 90 |
| `MAP_LOAD_DELAY` | `map_load_delay_sec` | 65 |
| `SEARCH_RETRIES_BEFORE_SHUFFLE` | `search_retries` | 5 |
| — | `cs2_main_menu_wait_timeout_sec` | 60 (launcher strict + dm_runner pre-click; 15s if menu unconfirmed) |

## Клики (база 360×270, Panorama RU)

| ID | Назначение |
|----|------------|
| `main_menu_play` | Вкладка **ИГРАТЬ** @ **(217, 14)** |
| `mode_deathmatch` | Режим Deathmatch на экране выбора |
| `start_search` | GO / начать поиск |
| `leave_match` | Запас: выход UI |

Main log при nav: `dm click main_menu_play @(x,y)` — если строк нет, мышь не вызывалась.

## Детекторы (color probes)

| State | YAML key | Strict |
|-------|----------|--------|
| `main_menu` | `detectors.main_menu` @ **x≈217** | launcher + dm_runner confirmed: **2/2**; warn path: soft **1/2** |
| `searching` | `detectors.searching` | N−1 из N |
| `in_dm` | `detectors.in_dm` | **все** probes (HUD, не Loadout) |

`cs2_menu_confirmed` в launcher — **только strict 2/2** на вкладке ИГРАТЬ.  
`cs2_menu_soft_peek` — если soft 1/2 был хотя бы раз (hint, не confirmed).

## Launcher + dm_runner sequence

1. `wait_for_cs2_hwnd` → `waiting for CS2 window…`
2. **`move_all_cs_windows`** → `launcher layout: …` (v5)
3. `wait_for_cs2_main_menu` (**strict 2/2**, unified focus capture)
4. `cs2_ok` → ready **или** unconfirmed
5. dm_runner: menu wait / fallback click @217
6. Retry fail **in_dm** only: `dm nav: retry in_dm wait (attempt N)` — **не** повторный soft probe wait

Timeout log: `main_menu timeout: p0=… p1=… last@(x,y)=[r,g,b] expected=[…]`

## Artifacts

Каждая сессия: `data/artifacts/{session_id}/`

- `wait_main_menu_launch_*.png`, `wait_main_menu_launch_timeout.png` (launcher)
- `wait_main_menu_*.png`, `after_click_*.png` (dm_runner)
- `steps.jsonl` — клики, детекты, **p0/p1/rgb0/rgb1**

## Калибровка

1. CS2 в **360×270** (`resources/cs2/cs2_video.txt`) или autoscale под фактический client.
2. Скрины **client area**: `wait_main_menu_launch_timeout.png` с активной вкладкой **ИГРАТЬ** (не `wait_main_menu_84.png` с другой машины).
3. RGB: `python scripts/sample_probe_rgb.py artifact.png 217 26` → yaml probe; scan y=22–32 для orange underline.
4. Negative check: probes @ x=168 (СНАРЯЖЕНИЕ) **не** должны давать strict `main_menu`.
5. Smoke: `set DM_NAV_SIM=0` → `python scripts/dm_nav_smoke.py --cycles 1`.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| `last@…=[0,0,0]` | v5 focus capture; не 720p; не кликать в Farm Panel во время farm |
| `soft probe wait` после `searching_dm` | v5 phased retry — обновить до v5 |
| 720s без `dm click` | v4 fallback; v5 focus |
| `SetForegroundWindow` error | focus retry; panel steals focus |

## Модули

- `modules/ui_nav/` — detectors, `probe_match_results`, `wait_for_cs2_main_menu`
- `modules/dm_runner/` — `navigate_to_dm`, controlled fallback click
