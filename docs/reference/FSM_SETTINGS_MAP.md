# Соответствие FSM `settings.json` → Farm Panel `AppConfig`

Справка read-only: `../settings/settings.json` (оригинал FSM **не** читается и **не** копируется в git прототипа).

Пути в таблице: поле в `data/config.yaml` (`config/schema.py`).

| FSM `settings.json` | Наше поле | Примечание |
|---------------------|-----------|------------|
| `STEAM_PATH` | `steam_path` | UI: **Set Steam path** → filedialog → `steam.exe` |
| `CSGO_PATH` | `cs2_path` | UI: **Set CS2 path** → filedialog → `cs2.exe` / `csgo.exe` |
| `TRADEOFFER_LINK` | `trade_offer_link` | Хранилка для looter |
| `AUTO_LOOT` | `auto_collect_drop` | Автовыбор дропа |
| `START_FARM_WHEN_LAUNCHED` | `start_farm_when_launched` | Старт после запуска |
| — | `only_launch_steam` | **Новое**: только Steam, без CS2 |
| — | `steam_auto_login` | **Новое**: vault + GUI или API login |
| — | `steam_login_mode` | `gui` (default) \| `api` \| `gui_then_api` |
| — | `steam_classic_login_ui` | Убрать `-noreactlogin` (default `true`, форма 705×440) |
| — | `steam_login_coords_profile` | Авто: `705x440` если client ~705×440, иначе `1920x1080` (см. LAUNCHER.md) |
| — | `steam_login_timeout_sec` | Таймаут GUI / API (default 120) |
| — | `steam_kill_before_login` | Kill Steam/CS2 перед сменой acc |
| `TG_BOT_API_KEY` | `telegram_bot_token` | Telegram BotFather |
| `TG_BOT_CHAT_ID` | `telegram_chat_id` | Chat / user id |
| `ITEM_PICTURES_IN_TG` | `telegram_send_screenshot` | sendPhoto с кадром дропа |
| `CHANGE_BATCH_AFTER_N_MINUTES` | `autofarm_timer_minutes` | Лимит сессии (solo: один acc) |
| — | `cs2_fps_limit_nvidia` | **Новое**: лимит FPS (NVIDIA) |
| `ACCOUNTS_LAUNCH_DELAY` | `cooldown_between_accounts_sec` | Пауза между acc (solo конвейер) |
| `GAME_SEARCH_TIMEOUT` / таймаут DM | `max_dm_minutes` | Макс. время в DM без level |
| `FARMING_MODE` + csgobot | `bot_mode` | `auto` / `ai` / `simple` |
| — | `combat_simple_minutes` | Длительность simple-бота (10) |
| — | `proxy_expected_ip` | **Новое**: ожидаемый exit IP |
| — | `test_mode` | **Новое**: fake modules |
| `../logpass.txt` | `fsm_logpass_path` (default `data/import/logpass.txt`) | Вход импорта → `vault.enc` |
| `maFiles/{login}.maFile` | `fsm_mafiles_dir` (default `data/import/maFiles/`) | UI **Import from logpass** / `import-fsm` |
| — | `fsm_import_enabled` | Включить импорт (default `true`) |
| — | `fsm_import_on_refresh` | Авто-импорт при Refresh (default `false`) |

## Поля FSM без прямого аналога в B1 (позже / DM-only)

| FSM | Статус в прототипе |
|-----|-------------------|
| `RUNNING2VS2`, `LOBBY_*`, `SEARCH_RETRIES_*` | Нет (solo DM) |
| `NO_AVAST_MODE`, `AVASTSANDBOX_FOLDER` | Нет (1 окно CS2) |
| `BES_REDUCTION_PERCENT` | Отдельный модуль / OS |
| `ADDITIONAL_LAUNCH_OPTIONS`, `STEAM_LAUNCH_OPTIONS` | `resources/cs2/` + launcher |
| `CS_RESOLUTION` | `cs_resolution` + `resources/ui_nav/coords_360x270.yaml` |
| `MAP_LOAD_DELAY` | `map_load_delay_sec` |
| `GAME_SEARCH_TIMEOUT` | `game_search_timeout_sec` |
| `SEARCH_RETRIES_BEFORE_SHUFFLE` | `search_retries` |
| `DELAY_BETWEEN_TRADES` | `cooldown_between_accounts_sec` (orchestrator между acc) |
| `REPLACE_ERROR_ACCOUNT` | orchestrator policy |
| `DROP_HISTORY_CACHE` | data/ (позже) |
| `launched_this_week.json` | `accounts.index.json` → `farmed_this_week` |

## Аккаунты

| FSM | Прототип |
|-----|----------|
| `logpass.txt` + `maFiles/` | `data/import/` → **Import from logpass** или `import-fsm` |
| Пароли в plaintext на диске | staging в `data/import/` (gitignored); runtime `vault.enc` |
| CLI add (один acc) | `vault_cli.bat add` (advanced) |
| Список acc в UI FSM | `accounts.index.json` (login, level, farmed_this_week) |
