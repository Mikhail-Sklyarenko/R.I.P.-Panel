# csgobot (GPL-3.0) — subprocess only

Upstream: https://github.com/Priler/csgobot — **vendored** in `vendor/csgobot/` (plain files in repo, no submodule).

Панель **не импортирует** код csgobot в `panel/` или `core/`. Запуск только через `modules/combat/csgobot_ai.py` → subprocess.

После `git pull` проверка:

```bat
dir vendor\csgobot\run.py
```

## YOLO weights (не в git)

Файлы `*.pt` **не хранятся** в репозитории (слишком большие). Для `bot_mode: ai` скачайте веса вручную в `vendor\csgobot\yolov8\`:

- Файл: `cs2_yolov8m_640_augmented_v4.pt` (~50 МБ)
- Путь: `vendor\csgobot\yolov8\cs2_yolov8m_640_augmented_v4.pt`
- Прямая ссылка (PowerShell, из папки `yolov8`):

```powershell
Invoke-WebRequest -Uri https://media.githubusercontent.com/media/Priler/csgobot/main/yolov8/cs2_yolov8m_640_augmented_v4.pt -OutFile cs2_yolov8m_640_augmented_v4.pt
```

Проверка: `dir` → ~52 078 401 bytes (не 0).

Для `bot_mode: simple` веса **не нужны**.

## OBS Virtual Camera (`obs_vc`)

В `vendor\csgobot\run.py` по умолчанию `GRABBER_TYPE = "obs_vc"`.

1. OBS → источник **«Захват окна»** → Counter-Strike 2
2. **Настройки → Видео** → базовое разрешение **1280×720**
3. **Запустить виртуальную камеру** до старта бота
4. `pip install pygrabber` в venv csgobot

Исправление grabber (уже в репо): виртуальная камера отдаёт сцену OBS без смещения `left/top` экрана — файл `grabbers/obs_vc_grabber.py`.

## FPS (цель 30+)

**6–7 FPS** на CPU с YOLOv8m — нормально без GPU. Для 30+ FPS нужна **видеокарта NVIDIA** и PyTorch с CUDA.

Проверка:

```bat
cd vendor\csgobot
venv\Scripts\python.exe torch_check_gpu.py
```

Если `cpu` — переустановите torch (пример CUDA 12.1):

```bat
venv\Scripts\pip.exe install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

В `run.py` (уже настроено для фарма):

| Параметр | Значение | Зачем |
|----------|----------|-------|
| `SHOW_PREVIEW` | `False` | окно отладки жрёт FPS |
| `YOLO_IMGSZ` | `640` | размер модели |
| `DETECTOR_DEVICE` | `""` | авто cuda/cpu |

Ручной тест с превью: временно `SHOW_PREVIEW = True`, после проверки снова `False`.

В логе `run.py` должно быть `PyTorch: cuda (...)` и `Detector: ... device=cuda`.

## Наводка крутит по кругу

Частые причины:

1. **OBS** — в логе должно быть `Capture region (OBS canvas): ... 1280 x 720`, не `704`.
2. **Высокий FPS + перелёт** — в `run.py`: `SMOOTHING = 3.0`, `DEAD_ZONE = 12.0`.
3. **Неверная команда** — **Ctrl+T** (CT / T).
4. **Чувствительность** — подстройте `X360` в `run.py` под вашу sens в CS2.

Окно с рамками: `SHOW_PREVIEW = True` (для фарма можно `False`).

## Бот не ходит сам (WASD)

**csgobot** — это **aim-assist**: наводит мышь на врагов. Сам по себе он **не бегает** по карте и **не стреляет** (авто-стрельба в коде пока не подключена).

Что нужно:

1. **Caps Lock** — бот активен только пока включён (в логе `Bot ACTIVATED`).
2. **Окно CS2 в фокусе** — иначе клавиши не попадут в игру.
3. **`AUTO_MOVE = True`** в `run.py` — лёгкие тапы W/A/S/D раз в ~8 с (как `simple` бот панели). После `git pull` включено по умолчанию.

Стрельба — вручную ЛКМ или доработка `AUTO_SHOOT` отдельно.

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
