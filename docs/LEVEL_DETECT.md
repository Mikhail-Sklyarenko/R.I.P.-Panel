# Level detector (B7)

Модуль `modules/level_detector/` наблюдает UI CS2 **во время combat** и останавливает бота.

## События

| Событие | FSM | Действие |
|---------|-----|----------|
| `level_up` | `farming` → `level_up` | `stop_combat()`, далее `drop_picker` |
| `combat_timeout` | `farming` → `cleanup` | `max_dm_minutes` из config (по умолчанию 90 min) |

## UI detection

- Probes: `resources/ui_nav/level_probes.yaml` (360×270) или `level_probes_{cs_resolution}.yaml`
- **Все пробы** должны совпасть (`min_matches` в meta = число проб)
- **Grace period:** первые `level_detect_grace_minutes` (по умолчанию **10**) UI не проверяется — защита от ложного level up на HUD в DM
- **Подряд:** `level_detect_consecutive_hits` (по умолчанию **3**) опроса с полным совпадением
- Скрины: `artifacts/{session_id}/level_detect_frame*.png`

### Калибровка @ 1280×720

1. Скрин **реального** баннера level up (client area 1280×720)
2. `python scripts/sample_probe_rgb.py your_level_up.png X Y` для точек баннера
3. Обновить `resources/ui_nav/level_probes_1280x720.yaml`

## Config (`data/config.yaml`)

```yaml
level_detect_grace_minutes: 10
level_detect_consecutive_hits: 3
max_dm_minutes: 90
```

## Env overrides (отладка)

```bat
set LEVEL_DETECT_GRACE_SEC=600
set LEVEL_DETECT_CONSECUTIVE_HITS=3
set LEVEL_DETECT_SIM=1
set LEVEL_DETECT_AFTER_SEC=0.5
set LEVEL_DETECT_TIMEOUT_SEC=60
```

## Симуляция (тесты / CI)

`LEVEL_DETECT_SIM=1` — без захвата окна; level up по таймеру `LEVEL_DETECT_AFTER_SEC`.

## Интеграция

`modules/combat/phase.py` — поток бота + `level_detector.watch()` в main thread.

Логи → panel Main log через `ctx.emit` (orchestrator UI callback).
