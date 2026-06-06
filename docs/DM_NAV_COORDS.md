# DM UI navigation coordinates

Прототип: **solo Deathmatch**. Не использует `../settings/fsm.cfg` (Wingman / scrimcomp2v2).

## Версия и разрешение

| Параметр | Значение |
|----------|----------|
| CS2 build (калибровка) | **2025-06 Panorama RU** @ small window |
| Базовое разрешение | **360×270** (`config.cs_resolution`, FSM `CS_RESOLUTION`) |
| Файл coords | `resources/ui_nav/coords_360x270.yaml` |
| Масштаб | `load_nav_coords_for_hwnd(hwnd)` — **autoscale от `GetClientRect`**, не только config |

Если client area CS2 (например **375×308**) ≠ `cs_resolution`, в Main log:  
`CS2 client … differs from cs_resolution …; autoscaling coords to client`

## RU tab bar @ 360×270

| Вкладка | ~X (центр) | Примечание |
|---------|------------|------------|
| ИНВЕНТАРЬ | ~115 | |
| **СНАРЯЖЕНИЕ** | **~168** | **ложный main_menu** если probes сюда |
| **ИГРАТЬ** | **~217** | `main_menu_play` + probes |
| МАГАЗИН | ~255 | |

## Таймауты (config.yaml)

| FSM `settings.json` | AppConfig | Default |
|---------------------|-----------|---------|
| `GAME_SEARCH_TIMEOUT` | `game_search_timeout_sec` | 90 |
| `MAP_LOAD_DELAY` | `map_load_delay_sec` | 65 |
| `SEARCH_RETRIES_BEFORE_SHUFFLE` | `search_retries` | 5 |
| — | `cs2_main_menu_wait_timeout_sec` | 120 (launcher strict + dm_runner pre-click) |

## Клики (база 360×270, Panorama RU)

| ID | Назначение |
|----|------------|
| `main_menu_play` | Вкладка **ИГРАТЬ** @ **(217, 15)** |
| `mode_deathmatch` | Режим Deathmatch на экране выбора |
| `start_search` | GO / начать поиск |
| `leave_match` | Запас: выход UI |

Main log при nav: `dm click main_menu_play @(x,y)` — если строк нет, мышь не вызывалась.

## Детекторы (color probes)

| State | YAML key | Strict |
|-------|----------|--------|
| `main_menu` | `detectors.main_menu` @ **x=217** | launcher + dm_runner confirmed: **2/2**; warn path: soft **1/2** |
| `searching` | `detectors.searching` | N−1 из N |
| `in_dm` | `detectors.in_dm` | **все** probes (HUD, не Loadout) |

`cs2_menu_confirmed` в launcher — **только strict 2/2** на вкладке ИГРАТЬ.

## Launcher sequence

1. `wait_for_cs2_hwnd` → `waiting for CS2 window…`
2. `wait_for_cs2_main_menu` (**strict 2/2**, timeout 120s; artifacts `wait_main_menu_launch_*.png`)
3. `cs2_ok` → `cs2 menu ready` **или** `cs2 menu unconfirmed … trying dm nav`
4. `dm_runner` → strict wait before clicks if confirmed; `dm click …` → `in_dm`

## Artifacts

Каждая сессия: `data/artifacts/{session_id}/`

- `wait_main_menu_launch_*.png`, `wait_main_menu_launch_timeout.png` (launcher)
- `wait_main_menu_*.png`, `after_click_*.png` (dm_runner)
- `steps.jsonl` — клики, детекты

## Калибровка

1. CS2 в **360×270** (`resources/cs2/cs2_video.txt`) или autoscale под фактический client.
2. Скрины **client area**: `wait_main_menu_*.png` с активной вкладкой **ИГРАТЬ**.
3. RGB: `python scripts/sample_probe_rgb.py artifact.png 217 28` → yaml probe.
4. Negative check: probes @ x=168 (СНАРЯЖЕНИЕ) **не** должны давать strict `main_menu`.
5. Smoke: `set DM_NAV_SIM=0` → `python scripts/dm_nav_smoke.py --cycles 1`.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| `main_menu_play @(168,…)` на Loadout | Обновить yaml: **x=217** для ИГРАТЬ |
| `wait_in_dm_*` на СНАРЯЖЕНИЕ | Клик не попал в ИГРАТЬ; см. `after_click_main_menu_play_1.png` |
| `capture: invalid window handle` при Stop | Graceful: `dm nav: stopped or window closed` (без retry capture) |
| Клики мимо | `sample_probe_rgb.py` + `coords_360x270.yaml` |

## Модули

- `modules/ui_nav/` — detectors, actions, driver, `wait_for_cs2_main_menu`
- `modules/dm_runner/` — `navigate_to_dm`, click verify + retry
