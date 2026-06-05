# FSM сессии (SessionState)

Одна сессия = один аккаунт, один процесс CS2, solo Deathmatch.

## Состояния

| State | Смысл |
|-------|--------|
| `queued` | В очереди конвейера |
| `launching` | Steam / CS2 |
| `in_menu` | Главное меню |
| `searching_dm` | Поиск DM |
| `in_dm` | На карте, до старта бота |
| `farming` | Цикл боя (csgobot) |
| `level_up` | Уровень получен |
| `drop_picking` | Выбор дропа |
| `looting` | Node looter |
| `cleanup` | Выход, закрытие Steam |
| `done` | Успех |
| `failed` | Ошибка / стоп оператора |

## Переходы

Допустимые рёбра: `core/session_state.py` → `ALLOWED_TRANSITIONS`.

Проверка: `can_transition(a, b)`; применение: `advance(a, b)`.

По событию: `core/fsm.py` → `apply_event(state, EventType)`.

## Типовой happy-path

```
queued → launching → in_menu → searching_dm → in_dm → farming
  → level_up → drop_picking → looting → cleanup → done
```

## Аварийные

- Из почти любого активного состояния → `failed` (если разрешено в `ALLOWED_TRANSITIONS`)
- `queued → failed` — немедленный отказ (нет аккаунта, vault, operator_stop)
- `searching_dm → in_menu` — retry поиска DM

## Терминальные

`done` и `failed` — без исходящих переходов.
