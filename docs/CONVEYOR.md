# Conveyor (B10)

Solo-конвейер: **unfarmed** → сессия → `farmed_this_week=true` → cooldown → следующий acc.

## Vault

`data/accounts.index.json`: `level`, `xp`, `farmed_this_week`.

## UI

| Кнопка | Действие |
|--------|----------|
| Start Farm | Все unfarmed (или выбранные, если есть ☑) |
| Start Selected | Только отмеченные |
| Launch Selected | Только launch; при `start_farm_when_launched=true` — полный фарм |
| Get LVL | `STEAM_LEVEL_SIM=1` или Steam Web → обновить level в vault |

Счётчики: **Selected | Launched | Farmed**.

## Headless (ночь, 3 acc)

```bash
set FAKE_SESSION_SECONDS=0.1
set DM_NAV_SIM=1
set LEVEL_DETECT_SIM=1
set DROP_PICKER_SIM=1
set LOOTER_SIM=1
python -m core.conveyor_cli --test-mode --max 3
```

или `python main.py --test-mode --conveyor --conveyor-max 3`

## Config

- `start_farm_when_launched=false` — после launch ждёт **Start Farm** (`force_farm` на старте)
- `cooldown_between_accounts_sec` — пауза между acc в очереди
