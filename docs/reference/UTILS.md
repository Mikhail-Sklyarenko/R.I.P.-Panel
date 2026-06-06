# Utils (B12)

Recovery после зависания CS2/Steam.

## Кнопки (Utils #1)

| Действие | Модуль |
|----------|--------|
| **Move all CS windows** | `move_all_cs_windows` — все окна CS2/CSGO, каскад, размер `cs_resolution` |
| **Kill ALL CS & Steam** | `recover_hang` — stop orchestrator + `taskkill` (B4 `launcher.cleanup`) |

## Recovery flow

1. Оператор: зависание / чёрный экран / залипший поиск DM  
2. **Kill ALL CS & Steam** — один клик, без диалога  
3. Оркестратор получает `stop`  
4. При необходимости — **Move all CS windows** перед следующим launch  

## Тесты (macOS/Linux)

```bash
UTILS_SIM=1 pytest tests/test_utils.py -q
```

## Windows

Требует `pywin32`; kill — только на Windows (без `UTILS_SIM`).
