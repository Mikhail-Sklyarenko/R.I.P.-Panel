# Farm Panel Prototype

Desktop farm panel prototype (CustomTkinter + Python core), separated from the original **FSM_PANEL** distribution in the parent directory.

- **Do not** run or modify `../Panel.exe`, `../looter/` (original), or `../settings/settings.json`.
- All product code lives under this folder only.

## Layout

| Path | Purpose |
|------|---------|
| `panel/` | CustomTkinter UI |
| `core/` | Orchestrator, session FSM |
| `modules/` | launcher, dm_runner, combat, drop_picker, looter, telegram, vault |
| `vendor/looter/` | Node trade helper (copied from FSM `looter/`) |
| `vendor/csgobot/` | GPL bot vendored (subprocess, own venv) |
| `resources/cs2/` | CS2 configs adapted for Deathmatch (from FSM `settings/`) |
| `docs/reference/` | Optional copies of FSM business docs |
| `data/` | Gitignored: vault, local config, logs |

## Prerequisites

- **Windows 10/11** (target runtime)
- **Python 3.11** (dev/build; end-user may use exe only)
- **Node.js** (for `vendor/looter` only)

## Distribution (B-PACKAGE)

Portable folder like FSM (not MSI):

```powershell
powershell -ExecutionPolicy Bypass -File build\build_windows.ps1
```

Output: `dist/FarmPanel/FarmPanel.exe`, `resources/`, `vendor/looter/`, writable `data/`.

- **First run:** `docs/WINDOWS_FIRST_RUN.md`
- **Accounts:** `data/import/logpass.txt` + `maFiles/` → UI **Import from logpass** (see `docs/FSM_ACCOUNT_IMPORT.md`)
- **Vault CLI:** `vault_cli.bat import-fsm` or `FarmPanel.exe --vault-cli list`
- **Dev launcher:** `FarmPanel.bat` (pythonw + source tree)
- Tokens/vault: only in `data/` (gitignored)

## vendor/looter (Node)

Copied from FSM: `looter_core.js`, `package.json`. Dependencies are **not** committed.

On Windows, from this directory:

```bat
cd vendor\looter
npm install
```

Wrapper: `modules/looter/runner.py` (cwd `vendor/looter`, exit **1** = `loot_ok`). См. `docs/reference/LOOTER.md`.

## vendor/csgobot (vendored, GPL)

См. `docs/CSGOBOT_SETUP.md`. Кратко (после `git pull` — `run.py` уже в репо):

```bat
cd vendor\csgobot
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Панель запускает `venv\Scripts\python.exe run.py` через **subprocess** (`modules/combat/csgobot_ai.py`). **Не** импортируйте csgobot в `panel/` или `core/`.

`bot_mode`: `auto` (AI если run.py + venv есть) | `ai` | `simple` (10 min).

## Utils (B12)

**Move all CS windows** / **Kill ALL CS & Steam** (recovery) — `docs/reference/UTILS.md`.

## Telegram (B11)

Config #2 + **Test Telegram**; дроп → `sendPhoto` + caption. См. `docs/reference/TELEGRAM.md`. Токены только в `data/config.yaml`.

## Conveyor (B10)

Headless: `python main.py --test-mode --conveyor --conveyor-max 3`  
Документация: `docs/CONVEYOR.md`

## Git

This directory is its own repository (`git init` here). The parent FSM_PANEL tree is reference-only; run `git status` only inside `farm-panel-prototype/`.

## Stack (planned)

Python 3.11, CustomTkinter, pywin32, pydantic, yaml; events in `data/logs/events.jsonl` (gitignored).
