# CS2 configs для Deathmatch (resources/cs2/)

Источник: копия из `../settings/` на этапе B-SETUP; **оригинал FSM не изменяется**.

## fsm.cfg (главные отличия от FSM Wingman)

| Было (FSM) | Стало (DM) |
|------------|------------|
| `ui_playsettings_mode_official_v20 scrimcomp2v2` | `ui_playsettings_mode_official_v20 deathmatch` |
| `player_competitive_maplist_2v2_...` (2v2) | **удалено** |
| `bind p "exec gamemode_def"` | **удалено** (Wingman preset) |
| — | `game_type 1` + `game_mode 2` (classic DM) |

Остальные бинды / low-FPS cvars сохранены для solo farm.

## cs2_video.txt

Минимальное разрешение **360×270**, low settings (как FSM `CS_RESOLUTION`).

Деплой: `modules/launcher/cs2.py` → `game/csgo/cfg/video.txt` (рядом с игрой).

## cs2_machine_convars.vcfg

Convars производительности; копируется в `game/csgo/cfg/cs2_machine_convars.vcfg`.

## Запуск

```
cs2.exe <ADDITIONAL_LAUNCH_OPTIONS из resources/launch_options.txt> +exec <abs>/resources/cs2/fsm.cfg
```

Пути Steam/CS2 — только `data/config.yaml` (`steam_path`, `cs2_path`).

## only_launch_steam

При `only_launch_steam: true` в config: после `steam_ok` CS2 **не** стартует, FSM → `cleanup` → `done` (см. `core/session_fsm.py`).
