# Phase 01 test report

Среда: Windows 10 (10.0.19045), Python 3.11.0, pytest 9.1.1, интерпретатор `.venv\Scripts\python.exe`. Ветка `fix/fleet-foundation-v2` от `f0ff197`. Реальные Steam-аккаунты и клиент CS2 не запускались.

## До изменений

Команда и сырой итог записаны в [BASELINE.md](BASELINE.md).

- Команда: fleet-тесты `agents`, `fsm`, `safety`, `observe`
- Результат: 49 passed, 0 failed, 0 skipped, 5.96 с
- Статус: PASS для этого набора. Это не доказательство отсутствия дефектов H-01…H-09.

## Финальный прогон после независимого разбора

```text
.venv\Scripts\python.exe -m pytest -q tests/test_wingman_fleet_foundation.py tests/test_wingman_fleet_agents.py tests/test_wingman_fleet_fsm.py tests/test_wingman_fleet_safety.py tests/test_wingman_fleet_observe.py tests/test_panel_controller.py --tb=line
```

- passed: 83
- failed: 0
- skipped: 0
- errors: 0
- время: 20.85 с
- статус: PASS

Состав: 29 тестов `tests/test_wingman_fleet_foundation.py`, 49 прежних fleet-тестов, 5 тестов `tests/test_panel_controller.py`.

Разбор добавил четыре регрессии и два точечных исправления ложных переходов:

- `UNCONFIRMED` на `START_SEARCH` больше не обрывает волну в `RunMachine._search_armed`. Волна ждёт экран поиска или таймаут фазы. `FAILED` по-прежнему уводит волну в подготовку с причиной `search_not_started`. Истечение `command_timeout_sec` по-прежнему даёт `search_desync`.
- Пустой состав лобби не считается чужой группой. `LOBBY_CONFIGURE` не прыгает в `LOBBY_RESET`, а `LOBBY_RESET` не шлёт `LEAVE_LOBBY`, пока участников не видно. Непустой чужой состав по-прежнему сбрасывает лобби.
- Повторные `UNCONFIRMED` на стадии пары не доходят до `READY`. Окно подтверждения, затем лимит попыток стадии, затем бюджет пересоздания лобби, затем восстановление. За 40 шагов по 7 с команда остаётся ограниченной.
- Протокол 2: все четыре агента с `protocol=2` получают свои команды. Агент с `protocol=1` получает `protocol_mismatch`, пустой список команд и не ломает выдачу остальным. Результат `unconfirmed` известной команды принимается в `accepted_results`. Неизвестный статус даёт HTTP 400.

## Смежный прогон против чистого `f0ff197`

Одинаковая команда на рабочем дереве и на отдельном worktree `f0ff197`, один и тот же `.venv`.

До восстановления зависимостей оба дерева дали один и тот же итог: 9 failed, 7 errors, 26 passed.

- `tests/test_wingman_live.py`: 2 failed и 7 errors. `ModuleNotFoundError: No module named 'numpy'` в `vendor/csgobot/nav/minimap_reader.py`.
- `tests/test_fsm_import.py`: 7 failed. Нет `tests/fixtures/fsm_import/maFiles/acc_one.maFile` и `acc_two.maFile`.

После восстановления только окружения, без правок продуктового кода:

- В `.venv` установлены `numpy` 2.4.6 и `opencv-python-headless` 5.0.0.93. Они есть в `vendor/csgobot/requirements.txt` и не добавлены в `requirements.txt` панели. После этого `tests/test_wingman_live.py`: 30 passed и на ветке, и на `f0ff197`.
- Локально созданы фикстуры `acc_one.maFile` и `acc_two.maFile` с заглушками `fixture-shared-secret` и `fixture-identity-secret`. Это не боевые секреты Steam. Каталог `maFiles/` игнорируется `.gitignore` и в коммит не входит. После этого `tests/test_fsm_import.py`: 12 passed и на ветке, и на `f0ff197`.

Вывод: 9 failed и 7 errors были блокерами окружения на `f0ff197`. Phase 01 их не внесла и не маскировала изменением продукта.

## Windows и живая игра

| Сценарий | Статус | Почему |
| --- | --- | --- |
| Симуляция четырёх агентов, SQLite, отмена, ACK, протокол 2 | PASS | Прогон 83 passed |
| Реальный CS2, фокус окна, клики по меню | BLOCKED | Клиент не запускался. `RUN_DROP_LIVE` не включался |
| Четыре физических ПК и LAN heartbeat | BLOCKED | В этой сессии одна машина |
| Освобождение клавиатуры на живом рабочем столе | BLOCKED | Нет интерактивной сессии CS2. Контракт `safe_stop` проверен на `SimBackend` и вызове методов |
| Exactly-once эффект клика в игре | BLOCKED | Технически не обещается. Статус клика — `UNCONFIRMED` |

## Повторный разбор диффа

- Гонка «команда уже снята с очереди, эпоха сменилась» закрыта: `_run` повторно сверяет эпоху до исполнения. Тест `test_popped_command_does_not_run_after_the_epoch_moves`.
- `SAFE_STOP` увеличивает эпоху, ставит защёлку `session_stopped` и не сбрасывается пустым `run_id`. Сбрасывает её только новый непустой `run_id`.
- `STOP_GAMEPLAY` срочный, но защёлку не ставит. Тот же запуск после потери связи снова принимает команды.
- `accepted_results` содержит только что записанные или уже терминальные результаты этого `agent_id` и активного `run_id`. Агент подтверждает пересечение с отправленным. Нет поля — нет ACK.
- Чужой `agent_id` и пустой `run_id` результат не записывают. Повтор терминального результата строку не перезаписывает.
- `PairMachine` на `UNCONFIRMED` не двигает `step_index` и не тратит попытку сразу. После окна срабатывает прежний путь «result not observed», затем лимит стадии и `on_exhausted`. Бесконечного цикла нет.
- `RunMachine` больше не считает `UNCONFIRMED` провалом поиска. Других проверок `res.succeeded` в `run_fsm.py` нет.
- Игровые модули прицеливания, детекции и навигации в дифф не входят.
- В диффе нет паролей, maFile, Steam Guard и токенов. Тестовый токен — строка из символа `t` длиной 32. Локальные фикстуры импорта игнорируются git.
- В коммит не входят `vendor/csgobot/cd`, `vendor/csgobot/set`, архивы датасета, `._*` и `yolo26n.pt`.

Оставшийся риск, не закрытый тестом на живом окне: `ACCEPT_INVITE` по-прежнему записывает `_invite_from` до наблюдения приглашения. На решение пары в симуляторе это не влияет. На живом клиенте это локальное ожидание, не датчик.

Порядок обновления: сначала координатор, затем все четыре агента. Старый координатор не разбирает статус `unconfirmed` и отвечает 400. Новый координатор старому агенту команды не выдаёт.
