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

## Таймауты (config.yaml)

| FSM `settings.json` | AppConfig | Default |
|---------------------|-----------|---------|
| `GAME_SEARCH_TIMEOUT` | `game_search_timeout_sec` | 90 |
| `MAP_LOAD_DELAY` | `map_load_delay_sec` | 65 |
| `SEARCH_RETRIES_BEFORE_SHUFFLE` | `search_retries` | 5 |
| — | `cs2_main_menu_wait_timeout_sec` | 120 |

## Клики (база 360×270, Panorama RU)

| ID | Назначение |
|----|------------|
| `main_menu_play` | Вкладка **ИГРАТЬ** (верх, центр) |
| `mode_deathmatch` | Режим Deathmatch на экране выбора |
| `start_search` | GO / начать поиск |
| `leave_match` | Запас: выход UI |

Main log при nav: `dm click main_menu_play @(x,y)` — если строк нет, мышь не вызывалась.

## Детекторы (color probes)

| State | YAML key | Strict |
|-------|----------|--------|
| `main_menu` | `detectors.main_menu` | launcher: **1 из 2**; dm_runner pre-click: **soft 1/2** (или skip если launcher confirmed); `in_dm`: **все** |
| `searching` | `detectors.searching` | N−1 из N |
| `in_dm` | `detectors.in_dm` | **все** probes (HUD, не тёмный угол меню) |

`in_dm` на чёрном меню **не** должен срабатывать.

## Launcher sequence

1. `wait_for_cs2_hwnd` → `waiting for CS2 window…`
2. `wait_for_cs2_main_menu` → `waiting for CS2 main menu…` (**soft**: min 1 of 2 probes; artifacts `wait_main_menu_launch_*.png`)
3. `cs2_ok` → `cs2 menu ready (hwnd=…)` **или** `cs2 menu unconfirmed … trying dm nav` (timeout fallback, не `session_failed`)
4. `dm_runner` → если launcher `cs2 menu ready`: **skip strict re-wait**, `dm click …` → `in_dm`

## Artifacts

Каждая сессия: `data/artifacts/{session_id}/`

- `wait_main_menu_launch_*.png`, `wait_main_menu_launch_timeout.png` (launcher)
- `wait_main_menu_*.png`, `after_click_*.png` (dm_runner)
- `steps.jsonl` — клики, детекты

## Калибровка

1. CS2 в **360×270** (`resources/cs2/cs2_video.txt`) или autoscale под фактический client.
2. Скрины **client area** (не full desktop): меню, поиск, in_dm — `data/artifacts/{session_id}/wait_main_menu_*.png`.
3. RGB pipette: `python scripts/sample_probe_rgb.py wait_main_menu_84.png X Y` → строка для yaml.
4. Обновите `coords_360x270.yaml` (`main_menu` probes + `main_menu_play` click на вкладку **ИГРАТЬ**).
5. Smoke: `set DM_NAV_SIM=0` → `python scripts/dm_nav_smoke.py --cycles 1`.

Shared timeout: `cs2_main_menu_wait_timeout_sec` (launcher + dm_runner soft wait, default **120s**).

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Курсор не двигается | Main log: есть ли `dm click …`? Если нет — ложный `in_dm` или nav не стартовал |
| `in_dm` на чёрном меню | Обновить build (strict `in_dm`); калибровать probes |
| `timeout waiting for main_menu (45s)` при `cs2 menu ready` | Обновить build: dm_runner skip re-wait + soft probes; см. `wait_main_menu_*.png` |
| Клики мимо | `load_nav_coords_for_hwnd` + Panorama coords (ИГРАТЬ сверху) |

## Модули

- `modules/ui_nav/` — detectors, actions, driver, `wait_for_cs2_main_menu`
- `modules/dm_runner/` — `navigate_to_dm`, click verify + retry
