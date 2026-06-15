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

## Autobuy rifle (DM)

Цель: после респавна в DM — **AK-47 (T)** или **M4A4 (CT)**, не random pistol/SMG.

| Слой | Файл | Что делает |
|------|------|------------|
| convars + cfg exec | `cs2_machine_convars.vcfg` + `fsm.cfg` | `cl_dm_buyrandomweapons 0` |
| cfg | `fsm.cfg` | `buy_rifle_dm` alias, `bind f5` + `scancode63` |
| csgobot | `CSGOBOT_AUTO_BUY=1` (default) | spawn window F5 + patrol freeze 12 s |

После смерти бот **не жмёт F5 сразу** (ещё мёртв/камера), а планирует покупки на 1.5–11 s и **стоит на месте** ~12 s — иначе WASD закрывает buy («0 сек — нельзя купить»).

Env: `CSGOBOT_AUTOBUY_RESPAWN_DELAYS_MS=1500,2000,2500,...`, `CSGOBOT_AUTOBUY_PATROL_FREEZE_MS=12000`, `CSGOBOT_AUTOBUY_STARTUP_FREEZE_MS=2000`.

```cfg
cl_dm_buyrandomweapons 0
alias buy_rifle_dm "buy ak47; buy m4a1; buy vesthelm"
bind f5 "buy_rifle_dm"
bind scancode63 "buy_rifle_dm"
bind insert "buy_rifle_dm"
```

Один alias покупает **AK или M4** для текущей стороны (не нужен sync F9/F10).

**Respawn:** csgobot планирует Insert через **0,4 / 0,9 / 1,4 с** после combat→idle (вероятный респавн). Cooldown **0,5 с** (было 1,5 с). Периодический burst **1 s** остаётся.

Env: `CSGOBOT_AUTO_BUY=0`, `CSGOBOT_AUTO_BUY_INTERVAL=0.8`, `CSGOBOT_AUTOBUY_RESPAWN_DELAYS_MS=1500,2000,2500,3000,3500,4000,5000,6000,8000,10000,11000`, `CSGOBOT_AUTOBUY_RESPAWN_COOLDOWN_MS=500`, `CSGOBOT_AUTOBUY_PATROL_FREEZE_MS=12000`, `CSGOBOT_AUTOBUY_STARTUP_FREEZE_MS=2000`.

При `cs2_vac_safe_launch=true` convars могут не деплоиться — binds в `farm_panel.cfg` (копия fsm.cfg) работают всегда.

## cs2_video.txt

Минимальное разрешение **360×270**, low settings (как FSM `CS_RESOLUTION`).

Деплой: `modules/launcher/cs2.py` → `game/csgo/cfg/video.txt` (рядом с игрой).

## cs2_machine_convars.vcfg

Convars производительности; копируется в `game/csgo/cfg/cs2_machine_convars.vcfg`.

## Запуск

```
steam.exe -applaunch 730 <ADDITIONAL_LAUNCH_OPTIONS из resources/launch_options.txt> +exec <abs>/resources/cs2/fsm.cfg
```

Пути Steam/CS2 — только `data/config.yaml` (`steam_path`, `cs2_path`).

## only_launch_steam

При `only_launch_steam: true` в config: после `steam_ok` CS2 **не** стартует, FSM → `cleanup` → `done` (см. `core/session_fsm.py`).
