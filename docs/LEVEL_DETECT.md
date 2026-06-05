# Level detector (B7)

Модуль `modules/level_detector/` наблюдает UI CS2 **во время combat** и останавливает бота.

## События

| Событие | FSM | Действие |
|---------|-----|----------|
| `level_up` | `farming` → `level_up` | `stop_combat()`, далее `drop_picker` (без кликов в B7) |
| `combat_timeout` | `farming` → `cleanup` | `max_dm_minutes` из config (FSM: 90 min) |

## UI detection

- Probes: `resources/ui_nav/level_probes.yaml` (база **360×270**)
- Скрины: `data/artifacts/{session_id}/level_detect_frame*.png`

## Симуляция (тесты / CI)

```bat
set LEVEL_DETECT_SIM=1
set LEVEL_DETECT_AFTER_SEC=0.5
set LEVEL_DETECT_TIMEOUT_SEC=60
```

## Интеграция

`modules/combat/phase.py` — поток бота + `level_detector.watch()` в main thread.

Логи → panel Main log через `ctx.emit` (orchestrator UI callback).
