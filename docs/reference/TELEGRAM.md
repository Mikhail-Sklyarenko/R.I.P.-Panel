# Telegram (B11)

Как FSM: после **drop_picked** — сообщение + скриншот CARE_PACKAGE из `data/artifacts/{session_id}/`.

## Config #2

| Поле | FSM |
|------|-----|
| `telegram_bot_token` | `TG_BOT_API_KEY` |
| `telegram_chat_id` | `TG_BOT_CHAT_ID` |
| `telegram_send_screenshot` | `ITEM_PICTURES_IN_TG` |

Токены только в `data/config.yaml` (gitignored). **Не** коммитить в git.

## UI

**Test Telegram** (Utils #1) → `send_test_ping()` (текст + мини-скрин при `telegram_send_screenshot`).

## API

- `modules/telegram/notify.py` — `notify_drop`, `send_test_ping`
- `TELEGRAM_SIM=1` — запись в `data/telegram_sim/outbox.jsonl` без сети

## Тесты

```bash
TELEGRAM_SIM=1 pytest tests/test_telegram.py -q
```
