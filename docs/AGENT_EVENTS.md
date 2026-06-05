# События агента (EventType)

Краткая шпаргалка для оркестратора и UI. Полный enum: `core/events.py`.

## Запись

- Файл: `data/logs/events.jsonl` (gitignored)
- Одна строка = JSON с полем `type` = значение `EventType`
- Дублирование в UI: Main log / Drop log (позже)

## Группы

| Группа | Примеры | Кто эмитит |
|--------|---------|------------|
| Сессия | `session_start`, `session_done`, `session_failed` | core |
| Launcher | `steam_ok`, `cs2_ok` | modules.launcher |
| DM | `in_menu`, `searching_dm`, `in_dm`, `exited` | modules.dm_runner |
| Бой | `combat_ai_started`, `farming`, `combat_fallback`, `combat_stopped`, `combat_timeout` | modules.combat |
| Дроп | `level_up`, `drop_picked` | level_detector / drop_picker (4→2, OCR+price) |
| Loot | `loot_ok`, `loot_failed` | modules.looter |
| Telegram | `telegram_sent` | modules.telegram (после дропа) |
| Оператор | `operator_stop`, `idle` | panel / core |

## Связь с FSM

Часть событий двигает `SessionState` — см. `core/fsm.py` (`EVENT_TARGET_STATE`) и `docs/STATE_MACHINES.md`.

События вроде `farming`, `combat_fallback` — **телеметрия**: состояние обычно остаётся `farming`.

## Тестовый режим

`python main.py --test-mode` — fake modules не пишут JSONL; события симулируются вручную в тестах оркестратора.
