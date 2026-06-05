# DM UI navigation coordinates

Прототип: **solo Deathmatch**. Не использует `../settings/fsm.cfg` (Wingman / scrimcomp2v2).

## Версия и разрешение

| Параметр | Значение |
|----------|----------|
| CS2 build (калибровка) | **2025-06** (post-Armory — уточните локально) |
| Базовое разрешение | **360×270** (`config.cs_resolution`, FSM `CS_RESOLUTION`) |
| Файл coords | `resources/ui_nav/coords_360x270.yaml` |
| Масштаб | `ui_nav.coords.load_nav_coords()` масштабирует X/Y при другом `cs_resolution` |

## Таймауты (config.yaml)

| FSM `settings.json` | AppConfig | Default |
|---------------------|-----------|---------|
| `GAME_SEARCH_TIMEOUT` | `game_search_timeout_sec` | 90 |
| `MAP_LOAD_DELAY` | `map_load_delay_sec` | 65 |
| `SEARCH_RETRIES_BEFORE_SHUFFLE` | `search_retries` | 5 |

## Клики (база 360×270)

| ID | Назначение |
|----|------------|
| `main_menu_play` | Play |
| `mode_deathmatch` | Режим Deathmatch |
| `start_search` | Start / GO |
| `leave_match` | Запас: выход UI |

## Детекторы (color probes)

| State | YAML key | Смысл |
|-------|----------|--------|
| `main_menu` | `detectors.main_menu` | Кнопка Play |
| `searching` | `detectors.searching` | Экран поиска |
| `in_dm` | `detectors.in_dm` | HUD / ammo UI в матче |

Порог: ≥ N−1 probe из N совпали (tolerance в YAML).

## Artifacts

Каждая сессия: `data/artifacts/{session_id}/`

- `0001_wait_main_menu_1.png` — скрины шагов
- `steps.jsonl` — клики, детекты, циклы
- `meta.json`, `cycles_result.json` (smoke)

## Калибровка

1. Запустите CS2 в **360×270** (см. `resources/cs2/cs2_video.txt`).
2. Сделайте скриншоты: меню, поиск, in_dm.
3. Обновите `rgb` в `coords_360x270.yaml` (pipette / Paint).
4. Smoke: `set DM_NAV_SIM=0` и `python scripts/dm_nav_smoke.py --cycles 5`.

Симуляция без игры (CI / dev):

```bat
set DM_NAV_SIM=1
python scripts/dm_nav_smoke.py --cycles 5
```

## Модули

- `modules/ui_nav/` — detectors, actions, driver (Win32 / Sim)
- `modules/dm_runner/` — `navigate_to_dm`, `disconnect`, `run_in_dm_cycles`
