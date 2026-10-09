# Phase 01 findings

Подтверждено по коду на `f0ff197` и закрыто на `fix/fleet-foundation-v2`. Отдельный прогон новых тестов на старом дереве не снимался: тесты добавлены вместе с исправлением. Ниже указан тест, который фиксирует новый контракт.

## H-01 — очередь живёт после SAFE_STOP

- Severity: P0
- Инварианты: I-01, I-03, I-04
- Где: `modules/fleet_agent/service.py`, `AgentService.drain`, срочный путь `_accept`
- Сценарий: обычная команда уже в очереди, затем приходит `SAFE_STOP`. Раньше stop только ставил `cancel` и сразу выполнялся, а `drain()` вызывал `cancel.clear()` перед каждой следующей командой.
- Почему: один флаг отмены сбрасывался самим исполнителем очереди. Отдельной эпохи сессии не было.
- Что сделано: целое `epoch`. `SAFE_STOP` увеличивает эпоху, ставит защёлку `session_stopped`, снимает очередь и пишет ей отказ. `drain()` больше не очищает `cancel`. Команда исполняется только в своей эпохе. Повторный `SAFE_STOP` выполняется снова и не поднимает старую очередь. Новый непустой `run_id` снимает защёлку. Пустой `run_id` (координатор без активного запуска) защёлку не снимает. `STOP_GAMEPLAY` по-прежнему срочный, но сессию не запирает, иначе восстановление после обрыва связи перестаёт принимать команды того же запуска.
- Тест: `test_safe_stop_drops_queue_and_second_stop_is_safe`, `test_new_run_does_not_resume_cancelled_session`, `test_popped_command_does_not_run_after_the_epoch_moves`, `test_link_loss_then_restore_accepts_the_same_run`

## H-02 — раннее подтверждение результата

- Severity: P1
- Инвариант: I-06
- Где: `AgentService.tick`; ответ собирает `Coordinator.handle_heartbeat`
- Сценарий: HTTP 200 с `ok: false` и без списка принятых id. Журнал помечал все отправленные результаты подтверждёнными до разбора ответа.
- Почему: `journal.ack` стоял сразу после успешного чтения тела.
- Что сделано: координатор возвращает `accepted_results`. Туда попадает id, который только что записан, либо уже лежит в базе как терминальный результат этого же агента и этого же запуска. Агент подтверждает только пересечение со своим отправлением. Нет поля — нет подтверждения, результат уйдёт снова. Потеря ответа и рестарт координатора между отправкой и подтверждением этим покрыты: повторная доставка не перезаписывает терминальный статус и снова попадает в `accepted_results`.
- Тест: `test_false_ok_without_accepted_list_does_not_ack`, `test_transport_outage_keeps_the_result`, `test_lost_ack_is_recovered_after_coordinator_restart`, `test_protocol_mismatch_records_result_but_sends_no_commands`

## H-03 — лобби записывалось из ожидания, а не из наблюдения

- Severity: P1
- Инварианты: I-08, I-11
- Где: `WindowsBackend.observe`, `WindowsBackend._ui` (`CONFIGURE_LOBBY`); `PairMachine.solo`
- Сценарий: клик по настройке лобби подставлял ожидаемые mode/map. На меню лобби собиралось из persona. Пустой список участников считался «игрок один».
- Что сделано: клик больше не пишет `_lobby`. Каждый `observe()` публикует пустое лобби, пока нет отдельного датчика. `solo()` требует ровно одного увиденного участника. Симулятор по-прежнему отдаёт лобби из модели мира, поэтому циклы на `SimWorld` не сломаны. Живой клиент лобби сам не подтверждает. Сбор группы в Phase 01 не автоматизировался.
- Тест: `test_stale_gsi_and_old_fingerprint_are_not_ready` (пустое лобби после меню), существующие циклы `test_wingman_fleet_fsm.py`

## H-04 — клик считался успешным эффектом

- Severity: P1
- Инвариант: I-08
- Где: `WindowsBackend._click_seq`, `WindowsBackend._console_or_click`; статус `ResultStatus.UNCONFIRMED`; ветка `PairMachine._run_stage`
- Сценарий: после серии `click_client` результат был `COMPLETED`, и пара двигала шаг.
- Что сделано: клик и неподтверждённая консоль возвращают `UNCONFIRMED`. Это терминальный статус, `succeeded` у него ложь. Пара открывает окно ожидания наблюдения и не тратит попытку стадии. Переход по-прежнему делает `spec.done()` по свежему наблюдению. `SAFE_STOP`, preflight и снимок с реальным файлом остаются `COMPLETED` или `FAILED` по локально проверенному эффекту. Симулятор по-прежнему возвращает `COMPLETED`, потому что сам применяет эффект.
- Тест: `test_unconfirmed_click_waits_for_observation`, `test_stale_gsi_and_old_fingerprint_are_not_ready`

## H-05 — таймаут post-match увеличивал успешные циклы

- Severity: P1
- Инвариант: I-09
- Где: `RunMachine._post_match` в `core/wingman_fleet/run_fsm.py`
- Сценарий: клиенты не вернулись в меню до `post_match_timeout_sec`, счётчик `cycles` всё равно рос.
- Что сделано: в `RunCtx` добавлен `failed_cycles` со значением по умолчанию 0, старый `state_json` читается. Таймаут увеличивает только его. `cycles` растёт, когда все агенты в меню и worker остановлен. `max_cycles` смотрит на успешные `cycles`.
- Тест: `test_post_match_timeout_is_not_a_successful_cycle`

## H-06 — старый fingerprint переживал сессию

- Severity: P1
- Инварианты: I-10, I-11
- Где: `WindowsBackend.observe`
- Сценарий: если свежий разбор roster не получался, в наблюдение подставлялся `_last_fp`, и это же значение снова сохранялось.
- Что сделано: fingerprint публикуется только при свежем GSI (не старше 2 с) и свежем разборе. Вне `IN_MATCH` и в `safe_stop` `_last_fp` сбрасывается.
- Тест: `test_stale_gsi_and_old_fingerprint_are_not_ready`

## H-07 — результат чужого агента закрывал команду

- Severity: P0
- Инвариант: I-12
- Где: `FleetStore.record_result`, вызов из `Coordinator.handle_heartbeat`
- Сценарий: запись искалась только по `command_id`. Любой авторизованный агент мог прислать результат чужой команды или другого запуска.
- Что сделано: запись требует совпадения `agent_id` и `run_id` с строкой команды и непустой активный запуск. Чужой агент не попадает в `accepted_results`. Повтор своего терминального результата не перезаписывается и может быть подтверждён агенту.
- Тест: `test_wrong_agent_cannot_complete_another_agents_command`, `test_harness_duplicate_result_stays_terminal`, `test_four_agents_addressing_stop_restart_and_sqlite`

## H-08 — устаревший preflight и GSI выглядели готовыми

- Severity: P1
- Инвариант: I-11
- Где: `Preflight.cached`, `Preflight.refresh_for_observation`, `WindowsBackend._check_gsi`
- Сценарий: `_check_gsi` считал успехом любой конечный возраст пакета. Наблюдение брало кэш без TTL, поэтому проверка старше своего срока оставалась `preflight_ok`.
- Что сделано: просроченный TTL в `cached()` — это `stale` без повторного запуска. На heartbeat обновляются только проверки с TTL не больше 5 с. Более тяжёлые остаются в кэше до команды `PREFLIGHT`. `_check_gsi` требует `GsiView.fresh`. Установка cfg по-прежнему отделена от свежести пакетов.
- Тест: `test_preflight_cache_expires_without_rerunning_expensive_checks`, `test_stale_gsi_and_old_fingerprint_are_not_ready`

## H-09 — остановка агента не дожидалась потока и могла выполниться дважды

- Severity: P1
- Инвариант: I-03
- Где: `AgentService.shutdown`, `AgentService.drain`, `FleetHost.stop`
- Сценарий: `drain()` не смотрел на `_stop`. `FleetHost.stop` вызывал `shutdown()` и не присоединял поток. `run_forever` в `finally` вызывал `shutdown()` ещё раз. Два `drain()` могли взять одну очередь.
- Что сделано: один флаг `_shut_down`. `drain()` выходит по `_stop` и чужой эпохе, второй вызов не входит, пока первый не закончил. `FleetHost.stop` сначала сигналит остановку, ждёт поток до 3 с, затем вызывает идемпотентный `shutdown`. Освобождение ввода остаётся в `safe_stop` и не ждёт координатора.
- Тест: `test_shutdown_is_idempotent_and_blocks_the_queue`, `test_two_drain_threads_execute_each_command_once_in_order`, `test_host_stop_joins_before_a_second_shutdown`

## H-10 — граница сети, без смены архитектуры

- Severity: P2, в этот патч не переносилась
- Где: `core/wingman_fleet/server.py` (`0.0.0.0`, тело до 512 КиБ, HMAC, пустой access-log)
- Что проверено: чужой результат и протокол закрыты в H-02 и H-07. Привязка ко всем интерфейсам и отсутствие TLS оставлены: четыре ПК в локальной сети иначе не видят координатор. Это следующий этап, не этот патч.

## Дополнительно по ревью

После первого зелёного прогона отдельно проверен уже извлечённый из очереди элемент. Смена `run_id` увеличивает эпоху и снимает `cancel`. Если смотреть только на `cancel`, такая команда успевала выполниться. `_run` теперь повторно сверяет эпоху под тем же замком. Это закрывает гонку, которую первый набор тестов не ловил. Тест: `test_popped_command_does_not_run_after_the_epoch_moves`.

Продление gameplay lease самим агентом не подтвердилось. TTL ставится из heartbeat, локальные monotonic-часы его не удлиняют. Тест: `test_gameplay_lease_expires_and_does_not_extend_itself`.

Протокол поднят с 1 до 2 из-за статуса `unconfirmed`. Старый агент получает `protocol_mismatch` и новые команды. Уже принятые результаты известных статусов записываются до этой проверки. Порядок обновления: сначала координатор, затем агенты.
