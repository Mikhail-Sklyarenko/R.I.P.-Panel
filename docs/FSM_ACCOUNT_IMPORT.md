# Импорт аккаунтов (как в FSM, через vault)

Операторы, привыкшие к FSM, могут добавлять аккаунты **без командной строки**: положить файлы в `data/import/`, нажать **Import from logpass** в Utils #1.

## Куда положить файлы

По умолчанию (рядом с `FarmPanel.exe` или в dev `farm-panel-prototype/data/`):

| FSM | Прототип |
|-----|----------|
| `logpass.txt` | `data/import/logpass.txt` |
| `maFiles/{login}.maFile` | `data/import/maFiles/{login}.maFile` |

При первом запуске панель создаёт каталог и шаблон `logpass.txt` с комментариями.

Кнопка **Open import folder** открывает `data/import/` в проводнике (Windows).

Пути можно переопределить в **Config #3**: `fsm_logpass_path`, `fsm_mafiles_dir` (пусто = defaults).

## Формат logpass.txt

- Кодировка **UTF-8**
- Одна строка: `login:password`
- Разделитель — **первый** `:` (пароль может содержать `:`)
- Пустые строки и строки с `#` в начале — пропуск

Пример:

```text
# my_steam_login:my_steam_password
farmer01:SecretPass123
```

## maFile

- Имя файла: `{login}.maFile` (как FSM, без учёта регистра)
- В JSON поле `account_name` должно совпадать с `login` (проверяется при импорте)
- Файл **не копируется** в `data/` после импорта — только секреты в `vault.enc`

## Импорт без maFile

Строка в logpass **без** соответствующего `.maFile` → **skipped** (не попадает в vault).  
Для looter нужны `shared_secret` / `identity_secret` из maFile.

## UI

1. Заполнить `data/import/logpass.txt` и положить maFiles
2. **Utils #1 → Import from logpass**
3. Main log: `import: added N, updated M, skipped K, errors E`
4. Список аккаунтов обновится автоматически

## CLI (advanced)

```bat
vault_cli.bat import-fsm
vault_cli.bat import-fsm --dry-run
python -m modules.vault.cli import-fsm --logpass PATH --mafiles-dir PATH
```

## Отличие от FSM

| | FSM | Прототип после импорта |
|--|-----|------------------------|
| Пароли на диске | plaintext в `logpass.txt` | один раз в `data/import/`, затем только `vault.enc` |
| Runtime store | файлы + UI | **`vault.enc`** + `accounts.index.json` |
| Удаление строки из logpass | не всегда удаляет acc | **не удаляет** acc из vault (как FSM) |

Синхронизация **односторонняя**: logpass/maFiles → vault. Обратный экспорт в logpass не реализован.

## Безопасность

- **Не коммитить** `data/import/logpass.txt`, `*.maFile`, `vault.enc`, `.vault_key`
- Каталог `data/` в `.gitignore`
- Импорт из установленного FSM (`../logpass.txt`) — post-MVP, read-only, не в repo defaults

## test_mode

Mock-аккаунты в UI показываются только если **пусты** и vault, и import staging.
