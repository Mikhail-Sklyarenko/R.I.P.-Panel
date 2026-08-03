# Combat / csgobot — план реализации

Порядок PR для `vendor/csgobot` + subprocess (`modules/combat/csgobot_ai.py`).  
Панель/core **не** импортируют GPL-код.

Целевая среда: CS2 **1280×720** windowed, Panorama RU, OBS VC, ArmoryFarm (RTX 4060).

---

## Статус (done)

| PR | Содержание |
|----|------------|
| 4–6 | Patrol YAML, anti-stuck, aim 6a–6f |
| autobuy | Insert → `buy_rifle_dm`, respawn burst |
| auto_activate | `CSGOBOT_AUTO_ACTIVATE`, без Caps Lock |
| PR-6d | Fire modes: hold / burst / tap |
| PR-6f | Long-range detect: ROI zoom, conf 0.50, body-first |
| PR-H1 | Hybrid head aim (`head_aim_min_conf=0.8`) |
| **PR-T1** | Auto team CT/T — HUD color probes, hysteresis, Ctrl+T override 5 s |
| **PR-M1** | Auto map patrol — match-ready probes + scoreboard templates → `dust2` / `mirage` / `generic_dm` |
| **PR-L1** | Look A — `LookController` (80–90° sweeps, alternate direction) |
| **PR-L1.1** | Look cadence: wall-clock `due_at`; combat abort no longer full-resets idle (DM-visible) |
| **PR-L1.2** | Look smoothness: longer sweep, yaw-rate floor, capped mouse substeps, pause WASD |

---

## Очередь (строго по порядку)

| # | PR | Задача | Приоритет |
|---|-----|--------|-----------|
| 1 | **PR-E1** | E2E runbook `Start Farm → loot_ok` на ArmoryFarm | следующий |
| 2 | **PR-L2** | **Look B** — микро-дрейф мыши при беге (доп. к L1) | после E1 |
| 3 | **PR-L3** | **Look C** — шаги `look` в patrol YAML + jitter | после L2 |
| 4 | **PR-L4** | **Look D** — YOLO-guided look (слабый bbox на краю кадра) | позже |
| 7 | Phase 9 | Minimap / позиция на карте | опционально, если stuck-метрики плохие |

> **Look-блок (L2–L4)** идёт после **PR-L1** (done): L3 зависит от map-specific YAML (M1 done).

---

## Look / camera — детализация (после M1)

Сейчас патруль = только WASD; мышь двигается только в бою (aim). Нужен плавный осмотр без «робот-маятника».

| ID | Название | Человечность | Сложность | K/D / detect | Когда | PR |
|----|----------|--------------|-----------|--------------|-------|-----|
| **A** | `LookController` | высокая | низкая | средний | лучший старт | **PR-L1** |
| **B** | микро-дрейф | очень высокая | низкая | низкий | доп. к A | **PR-L2** |
| **C** | YAML look | средняя* | средняя | высокий на карте | после M1 | **PR-L3** |
| **D** | YOLO-guided | средняя | высокая | высокий | позже | **PR-L4** |

\* с рандомом по углу/времени (±20%) — высокая

### PR-L1 — Look A (`LookController`) — **done**

**Проблема:** бот бежит и смотрит только вперёд → мало контактов, неестественно.

**Решение:** отдельный модуль `vendor/csgobot/look/look_controller.py`:

- Работает только в `PATROL`, не в бою / unstuck / autobuy freeze.
- Интервал **12–15 s** между осмотрами.
- Один sweep yaw **80–90°** (smootherstep, ~0.45–0.65 s), **удержание** — без return.
- Направление **чередуется** (+/−) каждый sweep.
- Градусы → mouse counts через `FOVMouseMovement.angle_to_mouse` + fractional carry.
- `look_active` guard в `main.py` — один `move_relative` за кадр; combat aim имеет приоритет.
- При появлении врага — **abort**; не трогает `fire_controller` / `aim_pipeline`.
- Env: `CSGOBOT_LOOK=0`, `CSGOBOT_LOOK_DEBUG=1`.
- Тесты: `tests/test_csgobot_look_controller.py`

**Не делать:** return-sweep / маятник, WindMouse, резкие ±90° за кадр, look при `enemy_target`.

**DoD:** unit-тесты на easing/state machine; на farm PC — плавные повороты в DM без карусели прицела в бою.

---

### PR-L2 — Look B (микро-дрейф)

**Дополнение к L1:** пока зажат `W`, крошечный `dx` (1–3 counts/frame) с медленно меняющимся bias.

- Лимит накопленного yaw за цикл патруля (например ±15° от «вперёд»).
- Не активен во время активного sweep из L1.

**DoD:** визуально «живая» мышь при беге; не конфликтует с aim.

---

### PR-L3 — Look C (YAML look, после M1)

Расширение `resources/patrol/{map}.yaml`:

```yaml
steps:
  - { key: w, sec: 4.0 }
  - { look_yaw: 28, dur: 1.4, easing: smooth }
```

- Направление привязано к маршруту карты (Dust2 Long, Mirage A…).
- Jitter ±20% по углу и длительности — anti-template.
- Зависит от **PR-M1** (выбор `dust2.yaml` / `mirage.yaml`).

**DoD:** patrol на правильной карте + look в сторону коридора; тесты parse YAML.

---

### PR-L4 — Look D (YOLO-guided, позже)

- 3–5 s без врагов → широкий sweep (до ~60°).
- Слабый detect на краю ROI → короткий доворот в сторону bbox.
- Риск ложных срабатываний — только после стабильного L1.

**DoD:** больше engagement на фланге; нет дёрганья на шуме detect.

---

## PR-M1 (done)

- Match-ready green probes + scoreboard header template match @ 1280×720.
- `run.py` / `PatrolConfig`: старт `generic_dm`, авто `dust2.yaml` / `mirage.yaml`.
- Фикстуры `tests/fixtures/csgobot_map/`, тесты `tests/test_csgobot_map_detect.py`.
- Docs: `CSGOBOT_SETUP.md` (env `CSGOBOT_AUTO_MAP`, `CSGOBOT_MAP_DEBUG`).

---

## PR-E1 (кратко)

- Runbook: `git pull` → Start Farm → `loot_ok` без ручных шагов.
- Чеклист blockers в `FARM_PC_CHECKLIST.md`.
- Headless sim + live ArmoryFarm pass criteria.

---

## Приоритет мыши (все Look PR)

```
1. Combat aim (враг в кадре)
2. Look sweep / drift (патруль, нет цели)
3. — 
```

---

## Связанные документы

- `docs/CSGOBOT_SETUP.md` — установка, env, T1
- `docs/AIM_TUNING.md` — калибровка aim / detect
- `docs/FARM_PC_CHECKLIST.md` — ArmoryFarm setup
- `resources/patrol/` — YAML маршруты (M1 + L3)
