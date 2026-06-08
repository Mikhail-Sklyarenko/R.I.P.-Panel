# csgobot (GPL-3.0) — subprocess only

Upstream: https://github.com/Priler/csgobot — **vendored** in `vendor/csgobot/` (plain files in repo, no submodule).

Панель **не импортирует** код csgobot в `panel/` или `core/`. Запуск только через `modules/combat/csgobot_ai.py` → subprocess.

После `git pull` проверка:

```bat
dir vendor\csgobot\run.py
```

## YOLO weights (не в git)

Файлы `*.pt` **не хранятся** в репозитории (слишком большие). Для `bot_mode: ai` скачайте веса вручную в `vendor\csgobot\yolov8\`:

- Основной файл из upstream: `cs2_yolov8m_640_augmented_v4.pt` (см. [Priler/csgobot](https://github.com/Priler/csgobot) releases / README)
- `run.py` ожидает: `vendor\csgobot\yolov8\cs2_yolov8m_640_augmented_v4.pt`

Для `bot_mode: simple` веса **не нужны**.

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

См. также `docs/AI_PC_PROFILE.md`.
