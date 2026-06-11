# Aim tuning (csgobot Level 1)

Калибровка наводки для DM @ **1280×720**. Параметры задаются в `vendor/csgobot/run.py` или через env (без правки git на farm PC).

## Prerequisites

1. CS2: **оконный** режим **1280×720**, Panorama RU  
2. OBS: canvas **1280×720**, Virtual Camera on  
3. В логе `run.py`: `Capture region (OBS canvas): ... 1280 x 720`  
4. GPU (CUDA обязателен для приемлемой наводки):

```bat
cd vendor\csgobot
venv\Scripts\python.exe tools\check_cuda_torch.py
```

Должно быть `"cuda": true`. Иначе см. `docs/CSGOBOT_SETUP.md` (PyTorch CUDA).

Панель при старте пишет `csgobot CUDA: …` или `WARN: PyTorch CPU-only`. В **Config #3** можно включить **`csgobot_require_cuda`** — тогда farm не запустит csgobot без GPU.

5. **`SHOW_PREVIEW = False`** — уже default для фарма (True только для отладки)

---

## X360 (обязательно под sens)

`X360` — сколько «единиц мыши» нужно для поворота на 360°. Неверное значение → перелёт, недолёт, «карусель».

### Вариант A — из sens (рекомендуется через панель)

**Config #1 → `cs2_sensitivity`** — значение из CS2 console (`sensitivity`). Панель передаёт его в subprocess как `CS2_SENSITIVITY` и в логе после `combat_ai_started` пишет `csgobot: x360 from CS2_SENSITIVITY=…`.

Ручная проверка формулы:

```bat
venv\Scripts\python.exe tools\calibrate_x360.py --sensitivity 2.1
```

Или env без панели:

```bat
set CS2_SENSITIVITY=2.1
```

### Вариант B — явный X360

```bat
set CSGOBOT_X360=8182
```

Приоритет: **`CSGOBOT_X360`** > **`CS2_SENSITIVITY`** > константа в `run.py`.

### Вариант C — тест в игре

```bat
venv\Scripts\python.exe tools\calibrate_x360.py --test 7792
```

Caps Lock → проверка поворота на 360°.

---

## SMOOTHING и DEAD_ZONE

| Параметр | Default | Env |
|----------|---------|-----|
| SMOOTHING | `3.0` | `CSGOBOT_SMOOTHING` |
| DEAD_ZONE | `12.0` | `CSGOBOT_DEAD_ZONE` |

Smoothing делит шаг мыши на N каждый кадр YOLO (не плавная кривая).

### Симптом → действие

| Симптом | Что сделать |
|---------|-------------|
| Круговая наводка / перелёт | ↑ SMOOTHING (4–6), ↑ DEAD_ZONE (14–16), перекалибровать X360 |
| Медленно доводит | ↓ SMOOTHING (2–2.5) |
| Дёргает на месте | ↑ DEAD_ZONE |
| Не стреляет | ↓ DEAD_ZONE или `PRIORITIZE_HEADS = False` |
| Aim мимо в сторону | OBS 1280×720, проверить capture region в логе |
| Промахи по голове | `PRIORITIZE_HEADS = False` (цель — тело) |

---

## Debug aim (farm PC)

```bat
set CSGOBOT_AIM_DEBUG=1
venv\Scripts\python.exe run.py
```

Раз в ~2 с при цели в логе:

`aim: fps=... dist=... mouse=(dx,dy) target=(x,y)`

---

## Стартовый профиль @ 1280×720

В `run.py` (после калибровки X360):

```python
SHOW_PREVIEW = False
X360 = <calibrated>
SMOOTHING = 3.0      # 4.0 если FPS > 35 и перелёт
DEAD_ZONE = 12.0
MAX_ASSIST_DISTANCE = 280
PRIORITIZE_HEADS = True
AUTO_SHOOT = True
SHOOT_COOLDOWN_SEC = 0.1
```

---

## Проверка через панель

1. `git pull`, OBS VC on  
2. `bot_mode: ai`, Start Farm  
3. После `combat_ai_started (auto_activate)` — **10+ мин** в DM  
4. **Pass:** бегает, видит врагов, стреляет, **нет** карусели прицела >5 с  

---

## Связанные документы

- `docs/CSGOBOT_SETUP.md` — OBS, CUDA, auto_shoot, patrol  
- `docs/AI_PC_PROFILE.md` — профиль ArmoryFarm  
