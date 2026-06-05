# Looter (B9)

Node subprocess только из **`vendor/looter/`** (копия FSM, не `../looter/`).

## Запуск

```text
cwd: farm-panel-prototype/vendor/looter
cmd: node looter_core.js <login> <password> <shared_secret> <identity_secret> <tradeOfferLink> [730/2]
```

Секреты — `modules.vault` (`data/vault.enc`). Trade URL — `trade_offer_link` в `data/config.yaml`.

Перед первым запуском на Windows:

```bat
cd vendor\looter
npm install
```

## Поведение панели

| Условие | Действие |
|---------|----------|
| `auto_collect_drop: false` | Looter **не** вызывается; `loot_ok` с `skipped: …` |
| `trade_offer_link` пустой | `loot_failed` |
| Node exit code **1** | `loot_ok` (offer confirmed, как в `looter_core.js`) |
| Иной exit | `loot_failed` |

Пауза между аккаунтами в конвейере: `cooldown_between_accounts_sec` (FSM `ACCOUNTS_LAUNCH_DELAY`) — `core/orchestrator.py`.

## Тесты

```bash
LOOTER_SIM=1 LOOTER_SIM_EXIT=1 pytest tests/test_looter.py -q
```

`LOOTER_SIM=1` — без Node/Steam; `LOOTER_SIM_EXIT` задаёт код возврата.

## Изменения `looter_core.js`

Логику скрипта не менять без ADR: `docs/ADR_looter.md` (создать при необходимости).
