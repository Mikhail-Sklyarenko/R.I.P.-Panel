# FSM Panel vs Farm Panel Prototype

Что **не** переносим из оригинального FSM (`../Panel.exe`, `../settings/settings.json`).

## Не копируем

| FSM | Прототип |
|-----|----------|
| **Panel.exe** (closed source, ~59 MB) | `farm-panel-prototype/main.py` + open `core/` |
| **2v2 Wingman**, 4 acc / 2 лобби | Solo **Deathmatch**, 1 acc = 1 CS2 |
| **5v5 Simulation**, 10 acc | Нет |
| **Пачки 4/10**, shuffle лобби | Конвейер **по одному** acc |
| **16 PC + диспетчер** | **1 PC**, без диспетчера |
| **`logpass.txt` + maFiles/** plaintext | `data/import/` (staging) → **Import from logpass** → `vault.enc` |
| **`../looter/`** как runtime | Копия только `vendor/looter/` (subprocess) |
| NO AVAST / Avast Sandbox | Обычное окно CS2 |
| `RUNNING2VS2`, lobby invite modes | `modules/dm_runner` DM-only |
| HWID-лицензия FSM | Нет |

## Что берём по смыслу (не бинарник)

| Идея FSM | У нас |
|----------|--------|
| CustomTkinter панель | `panel/` |
| Кнопки путей Steam/CS2 + filedialog | Config #1: **Set Steam path** / **Set CS2 path** → `data/config.yaml` |
| Steam login + Guard (maFile TOTP) | **GUI** `steam_gui_login` (default) или API `steam_login.js` → `docs/LAUNCHER.md` (B-STEAM-GUI) |
| `settings.json` поля | `data/config.yaml` — см. `FSM_SETTINGS_MAP.md` |
| `looter_core.js` | `vendor/looter/looter_core.js` |
| CS2 configs | `resources/cs2/` (адаптация под DM) |
| Telegram уведомления | `telegram_*` в config (B3+ stub) |
| События / логи | `data/logs/events.jsonl` + Main / Drop log |

## B3: test_mode

- `modules/_fakes/*` — sleep ~20s, события в JSONL, **без Steam**
- Looter fake: лог `would call vendor/looter/looter_core.js` (не трогаем `../looter/`)

## Дальше (не FSM)

- `vendor/csgobot/` submodule (GPL), subprocess
- Proxy check → `proxy_expected_ip`
- Реальные `modules/*` вместо `_fakes` при `test_mode: false`
