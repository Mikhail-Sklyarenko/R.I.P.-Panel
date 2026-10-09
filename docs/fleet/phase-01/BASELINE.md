# Phase 01 baseline

Снято до исправлений инфраструктуры Coordinator + Fleet Agent.

## Исходный коммит

- Репозиторий: `C:\Users\FermK\Downloads\R.I.P.-Panel`
- Ветка на момент снимка: `main`
- HEAD: `f0ff19701bf28287c2b7ec07535c2794f4e952b1`
- Сообщение: Ship the multi-map farm and the Inferno Wingman fleet so the repo matches the working product.
- Дата коммита: 2026-10-09 14:36:13 +0300
- Рабочая ветка исправлений: `fix/fleet-foundation-v2` (создана от этого HEAD)
- Отслеживаемых незакоммиченных правок не было. Неотслеживаемые `yolo26n.pt` и служебные файлы в `vendor/csgobot` не использовались и не входят в изменения.

## Среда

- ОС: Windows 10 (10.0.19045)
- Python системный: 3.11.0, пакет `pytest` в нём отсутствует
- Интерпретатор прогона: `.venv\Scripts\python.exe` (Python 3.11.0)
- pytest: 9.1.1
- Зависимости: `pip install -r requirements.txt` внутрь `.venv`
- Дата прогона: 2026-10-09

## Команда

```text
.venv\Scripts\python.exe -m pytest -q tests/test_wingman_fleet_agents.py tests/test_wingman_fleet_fsm.py tests/test_wingman_fleet_safety.py tests/test_wingman_fleet_observe.py --tb=no
```

## Результат

- passed: 49
- failed: 0
- skipped: 0
- время: 5.96 с
- код выхода: 0

Это состояние до патча. Оно не доказывает отсутствие дефектов отмены, ACK и принадлежности результата: эти пути существующими тестами не закрыты.

## Ограничения снимка

- Windows live-тесты (`RUN_DROP_LIVE`, реальный CS2, фокус окна, четыре физических ПК) не запускались.
- Сетевой стенд из четырёх машин недоступен. Дальнейшая проверка четырёх агентов идёт через `SimWorld`.
