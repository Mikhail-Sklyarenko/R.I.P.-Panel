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
| SMOOTHING | `2.5` | `CSGOBOT_SMOOTHING` |
| DEAD_ZONE | `12.0` | `CSGOBOT_DEAD_ZONE` |
| Adaptive smoothing | `on` | `CSGOBOT_ADAPTIVE_SMOOTHING=0` выкл |

**Adaptive smoothing** (PR-6b): далёкая цель → меньше smoothing (быстрее доводка), близкая → больше (точнее). При FPS &lt; 25 smoothing повышается против перелёта.

## Lead aim и body fallback (PR-6b)

| Параметр | Default | Env |
|----------|---------|-----|
| Lead aim | `on` | `CSGOBOT_LEAD_ENABLED=0` |
| Lead time | `80 ms` | `CSGOBOT_LEAD_MS` |
| Body fallback | `200 ms` | `CSGOBOT_BODY_FALLBACK_MS` |

**Lead aim** — EMA-скорость центра bbox, прицел в `pos + v × lead_ms`. Помогает против бегущих в DM.

**Body fallback** — если выбрана голова, но `dist > aim_dead_zone_high` дольше `BODY_FALLBACK_MS`, цель переключается на ближайшее тело.

## Fire modes (PR-6d)

| Параметр | Default | Env |
|----------|---------|-----|
| Mode | **`hold`** (зажим) | `CSGOBOT_SHOOT_MODE=tap\|burst\|hold` |
| Burst size | `5` | `CSGOBOT_BURST_SIZE` |
| Burst interval | `70 ms` | `CSGOBOT_BURST_INTERVAL_MS` |
| Burst gap | `150 ms` | `CSGOBOT_BURST_GAP_MS` |
| Hold max spray | `800 ms` | `CSGOBOT_HOLD_MAX_MS` |
| Hold re-press gap | `50 ms` | `CSGOBOT_HOLD_GAP_MS` |
| Hold release grace | `80 ms` | `CSGOBOT_HOLD_RELEASE_GRACE_MS` |
| Shoot cooldown (tap) | `70 ms` | `CSGOBOT_SHOOT_COOLDOWN_MS` |
| Head/body conf | `0.65` / `0.55` | — |

**hold** — `mouseDown` пока цель в `shoot_dead_zone`, отпускает после `HOLD_MAX_MS` или потери цели (с grace). Ближе к «зажиму» в DM.

**burst** — серия из N выстрелов, пауза, повтор.

**tap** — одиночные клики (старое поведение).

Лог: `auto_shoot: hold fire active`, debug: `fire=hold hold=True`.

## Anti-jitter (PR-6c)

| Параметр | Default | Env |
|----------|---------|-----|
| Aim smooth EMA | `0.45` | `CSGOBOT_AIM_SMOOTH_ALPHA`, `CSGOBOT_AIM_SMOOTH=0` |
| Aim move hysteresis | high **14** / low **8** | `CSGOBOT_AIM_DEAD_ZONE_HIGH`, `_LOW` |
| Shoot zone | **18** | `CSGOBOT_SHOOT_DEAD_ZONE` |
| Mouse cap / min | **35** / **2** | `CSGOBOT_MOUSE_MAX_DELTA`, `_MIN_DELTA` |
| Lead variance gate | `on` | `CSGOBOT_LEAD_VARIANCE_GATE=0` |

Pipeline: **EMA aim point → lead (if stable) → FOV → mouse cap → hysteresis move → shoot zone**.

Legacy `CSGOBOT_DEAD_ZONE` → `aim_dead_zone_high`.

Симптом «дёргается на бегу» → `git pull` 6c; debug: `lead_stable=False` в `aim:` log.

## Hybrid head aim (PR-H1)

Близко + уверенная голова → **head**; далеко / tiny bbox / low conf → **body** (6f long-range сохранён).

| Параметр | Default | Env |
|----------|---------|-----|
| Prioritize heads (hybrid) | `true` | `CSGOBOT_PRIORITIZE_HEADS=0` → nearest only |
| Head aim min conf | `0.8` | `CSGOBOT_HEAD_AIM_MIN_CONF` |
| Min bbox height (head) | `28` | `CSGOBOT_MIN_BBOX_HEIGHT` |
| Long-range body bias | `on` | `CSGOBOT_LONG_RANGE_BODY=0` |

Shoot confidence отдельно: head `0.65`, body `0.55` (fire_controller) — не путать с **aim** conf 0.8.

Лог: `head_aim_min_conf=0.8 heads=True`.

## Детекция (env) — PR-6f long range

| Параметр | Default | Env |
|----------|---------|-----|
| Confidence (detect) | `0.50` | `CSGOBOT_CONFIDENCE` |
| Max assist dist | `320` | `CSGOBOT_MAX_DIST` |
| ROI center zoom | `on` (0.75) | `CSGOBOT_ROI_ZOOM=0`, `CSGOBOT_ROI_FRACTION` |

Shoot confidence отдельно: head `0.65`, body `0.55` (fire_controller).

**ROI fallback:** если на полном кадре 0 врагов — второй YOLO pass по центральному crop 75%. Лог при `CSGOBOT_DETECT_DEBUG=1`: `detect: enemies=N roi=True best=t conf=... bbox_h=...`.

Smoothing делит шаг мыши на N каждый кадр YOLO (не плавная кривая).

### Симптом → действие

| Симптом | Что сделать |
|---------|-------------|
| Не видит врага вдали | `git pull` 6f; `CSGOBOT_DETECT_DEBUG=1`; ↓ `CSGOBOT_CONFIDENCE` до `0.45` |
| Видит, но aim по голове-микробоксу | ↑ `CSGOBOT_MIN_BBOX_HEIGHT=32` или hybrid уже body @ range |
| ROI не помогает | `CSGOBOT_ROI_FRACTION=0.65` (крупнее crop) |
| Круговая наводка / перелёт | ↑ SMOOTHING (4–6), ↑ DEAD_ZONE (14–16), перекалибровать X360 |
| Медленно доводит | ↓ SMOOTHING (2–2.5) |
| Дёргает на месте | ↑ DEAD_ZONE |
| Не стреляет | ↓ DEAD_ZONE; shoot conf head/body отдельно |
| Aim мимо в сторону | OBS 1280×720, проверить capture region в логе |
| Промахи по голове вдали | hybrid: body @ tiny head; ↓ `CSGOBOT_HEAD_AIM_MIN_CONF` только если close fights |

---

## Debug aim (farm PC)

```bat
set CSGOBOT_AIM_DEBUG=1
set CSGOBOT_DETECT_DEBUG=1
venv\Scripts\python.exe run.py
```

Раз в ~2 с при цели в логе:

`aim: fps=... dist=... mouse=(dx,dy) target=(x,y) roi=True`

Раз в ~3 с по детекции:

`detect: enemies=N roi=True best=t conf=0.55 bbox_h=42`

---

## Стартовый профиль @ 1280×720

В `run.py` (после калибровки X360):

```python
SHOW_PREVIEW = False
X360 = <calibrated>
SMOOTHING = 3.0      # 4.0 если FPS > 35 и перелёт
DEAD_ZONE = 12.0
MAX_ASSIST_DISTANCE = 320
PRIORITIZE_HEADS = True
HEAD_AIM_MIN_CONF = 0.8
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

- `docs/COMBAT_ROADMAP.md` — порядок PR (E1 → Look L1–L4; M1 done)
- `docs/CSGOBOT_SETUP.md` — OBS, CUDA, auto_shoot, patrol  
- `docs/AI_PC_PROFILE.md` — профиль ArmoryFarm  
