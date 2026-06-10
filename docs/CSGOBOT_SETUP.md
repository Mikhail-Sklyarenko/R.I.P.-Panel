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
2. Settings → Video → Base **1280×720**
3. **Start Virtual Camera** (можно держать включённой между сессиями)

Проверка из csgobot venv:

```powershell
cd vendor\csgobot
.\venv\Scripts\python tools\check_obs_vc.py
```

Панель при старте и перед `combat_ai_started` предупреждает, если VC недоступна.

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

Полная инструкция: **`docs/AIM_TUNING.md`**.

Частые причины:

1. **OBS** — в логе должно быть `Capture region (OBS canvas): ... 1280 x 720`, не `704`.
2. **Высокий FPS + перелёт** — в `run.py`: `SMOOTHING = 3.0`, `DEAD_ZONE = 12.0`.
3. **Неверная команда** — **Ctrl+T** (CT / T).
4. **Чувствительность** — `X360` / `CS2_SENSITIVITY` / `CSGOBOT_X360` (см. AIM_TUNING.md).

Env без правки `run.py`: `CS2_SENSITIVITY`, `CSGOBOT_X360`, `CSGOBOT_SMOOTHING`, `CSGOBOT_DEAD_ZONE`, `CSGOBOT_AIM_DEBUG=1`.

Окно с рамками: `SHOW_PREVIEW = True` (для фарма по умолчанию **False**).

## Автострельба (AUTO_SHOOT)

В `run.py` по умолчанию `AUTO_SHOOT = True`: ЛКМ, когда прицел в `DEAD_ZONE` от цели.

| Параметр | По умолчанию | Зачем |
|----------|--------------|-------|
| `AUTO_SHOOT` | `True` | выключить = только наводка |
| `SHOOT_COOLDOWN_SEC` | `0.1` | пауза между выстрелами (80–150 ms) |
| `DEAD_ZONE` | `12.0` | стрелять, когда расстояние до цели ≤ этого порога |

Нужны **Caps Lock** (`Bot ACTIVATED`), фокус окна CS2. В логе один раз: `auto_shoot: enabled (first shot fired)`.

Риск VAC выше, чем при одной только наводке.

## Патруль (PATROL)

В DM респавн **случайный** — патруль это **относительный макрос** (W/A/S/D по времени), не GPS по карте.

| Параметр | По умолчанию | Зачем |
|----------|--------------|-------|
| `PATROL_ENABLED` | `True` | сценарий вместо random WASD |
| `PATROL_SCRIPT` | `generic_dm` | файл `resources/patrol/{name}.yaml` |
| `PATROL_COMBAT_CLEAR_SEC` | `0.75` | пауза после врага перед бегом |
| `AUTO_MOVE` | `False` | legacy random tap |

Сценарии: `generic_dm.yaml`, `dust2.yaml`, `mirage.yaml`. В логе: `patrol: loaded ...`.

При враге патруль **пауза** (клавиши отпущены) → aim + `AUTO_SHOOT`. Враг пропал → снова патруль.

```bat
pip install pyyaml
```

## Анти-застревание (ANTI_STUCK)

Пока патруль **двигается**, но картинка в центре кадра почти не меняется ~6 с — бот считает, что застрял в геометрии, и выполняет макрос:

1. `space` (прыжок)
2. `s` 0.5 с (назад)
3. случайный `a` или `d` 1–2 с
4. патруль с начала сценария

| Параметр | По умолчанию | Зачем |
|----------|--------------|-------|
| `ANTI_STUCK_ENABLED` | `True` | выключить = только патруль |
| `STUCK_SEC` | `6.0` | сколько секунд «нет движения» |
| `STUCK_MOTION_THRESHOLD` | `2.0` | порог diff центра кадра (ниже = застрял) |
| `UNSTUCK_COOLDOWN_SEC` | `3.0` | пауза между unstuck-подряд |

В бою anti-stuck **не срабатывает**. В логе: `patrol: stuck detected, unstuck started` → `patrol: unstuck sequence completed`.

Если ложные срабатывания — поднимите `STUCK_SEC` или `STUCK_MOTION_THRESHOLD`. Если не вытаскивает из угла — понизьте порог или увеличьте `STUCK_SEC`.

## Бот не ходит (legacy AUTO_MOVE)

Если `PATROL_ENABLED = False`, можно включить **`AUTO_MOVE = True`** — случайный тап W/A/S/D раз в ~8 с.

1. **Caps Lock** — бот активен только пока включён.
2. **Окно CS2 в фокусе** — иначе клавиши/клики не попадут в игру.

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

### Авто-активация (фаза 3)

Панель передаёт `CSGOBOT_AUTO_ACTIVATE=1` в subprocess → **Caps Lock не нужен** после `combat_ai_started`.

В логе панели: `csgobot: subprocess started (auto_activate)`. В логе csgobot: `auto_activate: bot enabled`.

Ручной `run.py` без env — по-прежнему **Caps Lock**. Для ручного теста с авто: `set CSGOBOT_AUTO_ACTIVATE=1` или `AUTO_ACTIVATE = True` в `run.py`.

См. также `docs/AI_PC_PROFILE.md`.
