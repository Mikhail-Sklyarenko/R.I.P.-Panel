# csgobot (GPL-3.0) — subprocess only

Панель **не импортирует** код csgobot в `panel/` или `core/`. Запуск только через `modules/combat/csgobot_ai.py` → subprocess.

## Submodule (если папка пустая)

Из корня `farm-panel-prototype/`:

```bat
git submodule add https://github.com/Priler/csgobot vendor/csgobot
git submodule update --init --recursive
```

## Отдельный venv (обязательно)

```bat
cd vendor\csgobot
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

`vendor/csgobot/venv/` в `.gitignore`.

## Запуск вручную (проверка)

Окно CS2: **windowed**, заголовок содержит `Counter-Strike 2`.

```bat
cd vendor\csgobot
venv\Scripts\python.exe run.py
```

Выход: Ctrl+Q (см. upstream `run.py`).

## Интеграция панели

- `bot_mode: ai` — subprocess `venv\Scripts\python.exe run.py`, cwd = `vendor/csgobot`
- `bot_mode: simple` — `modules/combat/simple.py` (10 min, без GPL)
- `bot_mode: auto` — AI если есть `run.py` + venv, иначе simple; при падении AI → `combat_fallback` + simple
