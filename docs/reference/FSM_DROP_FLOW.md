# FSM Drop Flow (product knowledge, not Panel.exe reverse)

Описание типового поведения **FSM Panel** при еженедельном дропе CS2. Реализация прототипа — своя (`modules/drop_picker/`), без анализа бинарника.

## Контекст

1. Аккаунт получает **level up** в DM (см. `level_detector`).
2. CS2 показывает экран **Care Package** — **4 предмета** на выбор.
3. Игрок (или панель) выбирает **2** из 4.
4. После подтверждения предметы попадают в инвентарь → **looter** отправляет trade на storage (`vendor/looter/looter_core.js`).

## Логика выбора (как у FSM по смыслу)

| Шаг | FSM / продукт | Прототип B8 |
|-----|---------------|-------------|
| Детект экрана | Care package UI | `drop_picker.detector` (color probes) |
| Прочитать 4 имени | OCR по слотам | `drop_picker.ocr` |
| Оценка | Steam Market / кэш | `pricing` + `data/price_cache.db` |
| Выбор | **Топ-2 по цене** | `selection.select_top_slots(2)` |
| Клики | 2 слота + Confirm | `drop_picker.actions` |
| Артефакты | Скрины для оператора | `data/artifacts/{session_id}/drop_*.png` |

Если `auto_collect_drop: false` в config — панель может пропустить клики (только лог/OCR в артефактах).

## После выбора

- Событие `drop_picked` → FSM `drop_picking` → `looting`
- `modules/looter` — Node subprocess, инвентарь `730/2`
- Telegram (опционально) — имя + цена лучших предметов

## Отличия solo DM прототипа

| FSM (as-is) | Прототип |
|-------------|----------|
| Пачки 4/10, Wingman | 1 acc, DM |
| Дроп после batch level | Дроп после `level_up` одного acc |
| `DROP_HISTORY_CACHE` | `price_cache.db` + JSONL events |

## Калибровка

- Разрешение **360×270** (`cs_resolution`)
- Координаты: `resources/ui_nav/drop_slots_360x270.yaml`
- См. также `docs/DM_NAV_COORDS.md`

## GPL / vendor

- **csgobot** — только combat, не drop UI
- **looter** — Node, отдельный subprocess
- **drop_picker** — MIT-стиль код в `modules/drop_picker/`, без импорта Panel.exe
