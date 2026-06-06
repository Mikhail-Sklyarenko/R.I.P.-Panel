# Первый запуск на Windows (реальный фарм)

## Что нужно на ПК

| Компонент | Обязательно |
|-----------|-------------|
| Windows 10/11 | Да |
| Steam + CS2 | Да |
| Node.js LTS | Да (looter + **Steam auto-login**) |
| Python (end-user) | **Нет**, если используете `dist/FarmPanel/FarmPanel.exe` |
| Tesseract | Нет (опционально для live OCR дропа) |

## Сборка exe (разработчик)

На машине с Python 3.11:

```powershell
cd farm-panel-prototype
powershell -ExecutionPolicy Bypass -File build\build_windows.ps1
```

Результат: `dist/FarmPanel/FarmPanel.exe` + `resources/` + `vendor/looter/`.

## Подготовка dist/FarmPanel

```bat
cd dist\FarmPanel\vendor\looter
npm install
```

Опционально csgobot: см. `docs/CSGOBOT_SETUP.md` (submodule + venv в **исходниках**, скопировать `vendor/csgobot` в dist при необходимости).

## Импорт аккаунтов (рекомендуется: import folder)

1. Запустить `FarmPanel.exe` один раз (создаст `data/import/`)
2. Положить в `data/import/`:
   - `logpass.txt` — строки `login:password` (UTF-8)
   - `maFiles/{login}.maFile` — как в FSM
3. В панели: **Utils #1 → Import from logpass** (или **Open import folder**)

Подробно: [FSM_ACCOUNT_IMPORT.md](FSM_ACCOUNT_IMPORT.md).

Секреты после импорта только в `data/vault.enc` (рядом с exe), **не** в git.

### CLI (advanced)

```bat
vault_cli.bat import-fsm
vault_cli.bat add --login MYLOGIN --password MYPASS --mafile C:\path\to\login.maFile
vault_cli.bat list
```

## Config (`data/config.yaml`)

### Пути Steam / CS2 (рекомендуется)

В панели: **Config #1 → Set Steam path** → выберите `steam.exe` → **Set CS2 path** → выберите `cs2.exe` (обычно `…\\Counter-Strike Global Offensive\\game\\bin\\win64\\cs2.exe`). Путь сохраняется сразу в `data/config.yaml`, строка появляется в Main log. На macOS/Linux кнопки недоступны — задайте пути вручную в yaml.

### Остальные поля

После **Save Config #1** / #2 / #3 или вручную в yaml:

```yaml
test_mode: false
steam_path: "C:\\Program Files (x86)\\Steam\\steam.exe"
cs2_path: "C:\\...\\cs2.exe"
trade_offer_link: "https://steamcommunity.com/tradeoffer/new/?..."
cs_resolution: "360x270"
start_farm_when_launched: true
auto_collect_drop: true
cooldown_between_accounts_sec: 180
```

**AI Farm PC:** `cs_resolution: "1280x720"`, `bot_mode: ai` — см. `docs/AI_PC_PROFILE.md` и `docs/config.ai_pc.example.yaml`.

CS2: **оконный** режим, разрешение как в `cs_resolution`. Launcher копирует `resources/cs2/profiles/{cs_resolution}/cs2_video.txt` (или default `cs2_video.txt` для 360×270) + convars в cfg игры и exec `fsm.cfg` (Deathmatch).

### Steam auto-login (B-STEAM-GUI, default)

- **Config #1:** `Auto Steam login` = on, `steam_login_mode` = **gui** (default), maFile обязателен при импорте.
- Панель: `steam.exe` → **в окне Steam** ввод login/password + Guard TOTP из vault → `steam_login_ok` → `cs2.exe`.
- Оператор должен **видеть** вход в нужный аккаунт в клиенте Steam (не только строку в логе).
- Окно **входа** Steam: client area **705×440** (DPI 100% на ArmoryFarm). Coords: `steam_login_705x440.yaml`. При 125% DPI — перекалибровка. См. [LAUNCHER.md](LAUNCHER.md).
- **steam_classic_login_ui** по умолчанию **вкл** (Config #3) — классическая форма без React.
- Экран **«подтвердите в приложении Steam»**: панель кликает **Enter a code instead** и вводит 5-символьный код из maFile. Нужен `npm install` в `vendor/looter` для TOTP.
- Fallback API: `steam_login_mode: api` → Node `steam_login.js` (без GUI-ввода).
- При fail React-login: Config #3 **steam_classic_login_ui** или убрать `-noreactlogin`.

## Первый реальный прогон

1. Запустить `FarmPanel.exe`
2. Main log: проверить `app_root`, нет ли `WARN:` (steam_path, steam_login coords, Node при mode=api)
3. Импорт acc + maFile → vault
4. Отметить **один** аккаунт → **Start Selected**
5. Task Manager: `steam.exe`, `cs2.exe` (и `node.exe` только при `steam_login_mode: api`)
6. Main log: `steam_login_ok` → `steam_ok` → `cs2_ok` → `in_dm` → … → `DONE`
6. При зависании: **Kill ALL CS & Steam** (Utils), затем снова Start

## Known limitations

- Калибровка UI (`resources/ui_nav/*.yaml`) под 360×270; на другом разрешении — правка coords
- Drop OCR без Tesseract — ограниченная точность; live-тест на машине с Tesseract
- Права администратора могут понадобиться для taskkill/окон (зависит от политики ПК)
- `bot_mode: ai` требует отдельный csgobot venv; иначе **simple** бот
- Node **не** внутри exe — только `vendor/looter` рядом

## Dev без exe

```bat
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
FarmPanel.bat
```
