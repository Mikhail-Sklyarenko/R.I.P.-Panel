# FSM Panel — Полная спецификация проекта

**Версия документа:** 1.0  
**Дата:** 2026-05-29  
**Основа:** анализ FSM Panel v.3.0.1 (структура файлов, конфиги, looter, публичная документация)  
**Назначение:** единый справочник для инвесторов, разработчиков и личного использования при проектировании улучшенной системы.

---

## Содержание

1. [Executive Summary](#1-executive-summary)
2. [Что представляет собой проект](#2-что-представляет-собой-проект)
3. [Предметная область (Domain Model)](#3-предметная-область-domain-model)
4. [Архитектура системы](#4-архитектура-системы)
5. [Бизнес-процессы](#5-бизнес-процессы)
6. [Модель данных и конфигурация](#6-модель-данных-и-конфигурация)
7. [Модули и технологии](#7-модули-и-технологии)
8. [Интеграции](#8-интеграции)
9. [Карта файлов проекта](#9-карта-файлов-проекта)
10. [Риски и минусы для оператора](#10-риски-и-минусы-для-оператора)
11. [Нефункциональные требования (to-be)](#11-нефункциональные-требования-to-be)
12. [Roadmap разработки](#12-roadmap-разработки)
13. [Открытые вопросы (black box Panel.exe)](#13-открытые-вопросы-black-box-panelexe)
14. [Приложения](#14-приложения)

---

## 1. Executive Summary

### 1.1 Суть продукта

**FSM Panel** — коммерческая Windows desktop-система для автоматизации «фарма» еженедельных дропов в **Counter-Strike 2** на множестве Steam-аккаунтов.

Пользователь загружает список аккаунтов, нажимает несколько кнопок — панель сама:

- запускает Steam и CS2 на 4–12+ аккаунтах;
- собирает лобби и ищет матчи между «своими» аккаунтами;
- проводит матч автоматически (убийства, плент, дефуз);
- качает XP до получения недельного дропа;
- собирает лучший предмет и отправляет его на trade-ссылку;
- переключается на следующую пачку аккаунтов.

### 1.2 Бизнес-модель оригинального продукта

| Элемент | Описание |
|---------|----------|
| Монетизация | Платная лицензия, привязка к HWID |
| Продажи | Telegram-бот (@moonlighter_shop_bot) |
| Документация | [fsmpanel.gitbook.io](https://fsmpanel.gitbook.io/guide/funkcional-fsm-panel) |
| Канал | [@fsm_panel](https://t.me/fsm_panel) |
| Целевая аудитория | Операторы CS2-ферм (case/drop farming) |

### 1.3 Цель собственной разработки

Создать **контролируемую, прозрачную, расширяемую** замену закрытому `Panel.exe`:

- открытая архитектура и исходный код;
- безопасное хранение секретов (не plaintext);
- модульность — можно отключать и улучшать блоки отдельно;
- observability — логи, метрики, алерты;
- независимость от стороннего лицензирования.

> **Compliance notice:** автоматизированный фарм CS2 нарушает [Steam Subscriber Agreement](https://store.steampowered.com/subscriber_agreement/). Документ описывает техническую логику существующей системы. Команда и инвесторы должны осознанно принять юридические и операционные риски.

---

## 2. Что представляет собой проект

### 2.1 Тип проекта

Это **не open-source приложение** и **не серверный сервис**. Это:

- упакованное **desktop-приложение** (`Panel.exe`, ~59 MB);
- набор **вспомогательных скриптов** (`looter/`);
- **игровые конфиги** CS2 (`settings/`);
- **утилиты оптимизации** (BES — ограничение CPU);
- **файлы данных** (аккаунты, maFiles, трекинг недели).

### 2.2 Чем проект НЕ является

| Не является | Пояснение |
|-------------|-----------|
| Open-source | Основная логика внутри скомпилированного `Panel.exe` |
| Серверным приложением | Всё работает локально на Windows-машине |
| Классическим читом | По документации — без инжекта и чтения памяти, через симуляцию ввода |
| Кросс-платформенным | Только Windows, требует прав администратора |

### 2.3 Режимы фарма

| Режим | Аккаунтов | Лобби | Описание |
|-------|-----------|-------|----------|
| **2×2 Wingman** | 4 | 2 × 2 игрока | Режим «Напарники» (scrimcomp2v2) |
| **5×5 Competitive** | 10 | 2 × 5 игроков | Соревновательный режим |

В текущей конфигурации (`settings/settings.json`):

- `RUNNING2VS2: true` — активен режим Wingman;
- `FARMING_MODE: 2` — сценарий счёта (ничья или random);
- `ROUND_TARGET: 22` — целевое количество раундов.

### 2.4 Дополнительные функции (из документации FSM)

- **Telegram-бот** — уведомления, удалённое управление, скриншоты;
- **Looter** — автосбор и отправка дропов;
- **Activity Booster** — накрутка онлайна в других играх;
- **Steam Route Tool (SRT)** — выбор оптимального сервера CS2;
- **Armory Pass Collector** — фарм звёзд Armory Pass;
- **Таймер автофарма** — отложенный запуск, автовыключение ПК;
- **NO AVAST MODE / Avast Sandbox** — фоновый запуск окон CS2.

---

## 3. Предметная область (Domain Model)

### 3.1 Диаграмма сущностей

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Account   │────▶│    Batch     │────▶│   Session   │
│ (Steam user)│     │ (пачка 4/10) │     │ (1 farm-run)│
└─────────────┘     └──────────────┘     └─────────────┘
       │                    │                    │
       ▼                    ▼                    ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  maFile     │     │    Lobby     │     │    Match    │
│ (2FA secrets)│    │ (2v2 / 5v5)  │     │ (матч CS2)  │
└─────────────┘     └──────────────┘     └─────────────┘
       │                    │                    │
       ▼                    ▼                    ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Inventory  │     │     Drop     │     │ TradeOffer  │
│ (730/2 etc) │     │ (weekly item)│     │ (вывод)     │
└─────────────┘     └──────────────┘     └─────────────┘
```

### 3.2 Гlossary

| Термин | Определение |
|--------|-------------|
| **Account** | Steam-аккаунт с Prime: login, password, maFile |
| **Batch / Пачка** | Группа аккаунтов для одновременного фарма (4 или 10) |
| **Farm cycle** | Полный цикл: запуск → лобби → матч → XP → дроп → loot → следующая пачка |
| **Drop** | Еженедельный предмет CS2 за повышение уровня профиля |
| **Looter** | Node.js-модуль отправки инвентаря на trade-ссылку |
| **Wingman / 2v2** | Режим «Напарники», 4 аккаунта = 2 лобби |
| **5v5 Simulation** | Соревновательный режим, 10 аккаунтов = 2 лобби по 5 |
| **NO AVAST MODE** | Встроенный способ фонового запуска окон CS2 без песочницы |
| **Shuffle** | Перемешивание состава лобби при неудачном поиске |
| **maFile** | Файл Steam Guard Mobile Authenticator с секретами 2FA |

### 3.3 State Machine аккаунта

```
IDLE → LAUNCHING → IN_MENU → IN_LOBBY → SEARCHING → IN_MATCH
  → POST_MATCH → LEVEL_UP → LOOTING → FARMED (week) → IDLE
         ↓           ↓          ↓           ↓
       ERROR    DISCONNECTED  TIMEOUT    TRADE_FAILED
```

| Статус | Описание | Действие системы |
|--------|----------|------------------|
| IDLE | Готов к запуску | Ожидание в очереди |
| LAUNCHING | Стартует Steam/CS2 | Retry до N попыток |
| IN_MENU | Главное меню CS2 | Создание лобби |
| IN_LOBBY | В лобби | Invite, ready check |
| SEARCHING | Поиск матча | Timeout → shuffle |
| IN_MATCH | Идёт матч | Bot scenarios, round control |
| POST_MATCH | После матча | Disconnect, return to menu |
| LEVEL_UP | Получен уровень | Trigger loot |
| LOOTING | Отправка trade | Looter subprocess |
| FARMED | Отфармлен на неделе | Исключить из очереди |
| ERROR | Ошибка | Replace account (optional) |

---

## 4. Архитектура системы

### 4.1 High-Level Architecture

```
┌────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR (Panel.exe)               │
│  Python 3.11 + CustomTkinter + PyInstaller + Admin rights   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Account  │ │Matchmaking│ │ In-Game │ │ Config/TG   │  │
│  │ Manager  │ │ Engine    │ │ Bot      │ │ Integration │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
└───────────┬──────────────┬──────────────┬──────────────────┘
            │              │              │
    ┌───────▼──────┐ ┌─────▼─────┐ ┌─────▼──────┐
    │ Steam Client │ │ CS2 Client│ │ Node.js    │
    │ (×N windows) │ │ (×N inst.)│ │ Looter     │
    └──────────────┘ └───────────┘ └────────────┘
            │              │
    ┌───────▼──────────────▼───────┐
    │  Input Simulation Layer      │
    │  (AutoIt / Win32 / no inject)│
    └──────────────────────────────┘
            │
    ┌───────▼───────┐  ┌────────────┐
    │ BES (CPU cap) │  │ JSON files │
    └───────────────┘  │ persistence│
                       └────────────┘
```

### 4.2 As-Is vs To-Be

| Модуль | As-Is (FSM v3.0.1) | To-Be (рекомендация) |
|--------|---------------------|----------------------|
| Orchestrator | `Panel.exe` (closed) | Python/Go service + REST API |
| GUI | CustomTkinter | Web dashboard или desktop UI |
| Account Manager | Внутри Panel | Отдельный сервис + encrypted vault |
| Steam Launcher | Внутри Panel | Process manager module |
| Matchmaking | Внутри Panel | State machine + queue |
| In-Game Bot | AutoIt + cfg binds | Pluggable strategy pattern |
| Looter | `looter/looter_core.js` | Microservice + item filter |
| Config | `settings/settings.json` | Schema-validated config + env secrets |
| Monitoring | Telegram bot | Telegram + structured logs + metrics |
| CPU Throttle | BES.exe | Windows Job Objects / BES |
| License | HWID (commercial) | Не нужен для personal use |

### 4.3 Technology Stack

| Слой | Технология |
|------|------------|
| Main app | Python 3.11, CustomTkinter, PyInstaller |
| Windows API | win32api, win32gui, win32process, pywin32 |
| Looter | Node.js, steam-user, steamcommunity, steam-totp, steam-tradeoffer-manager |
| Game config | CS2 VDF/cfg (fsm.cfg, cs2_video.txt, cs2_machine_convars.vcfg) |
| CPU limiter | BES (Battle Encoder Shirase, C++) |
| Persistence | JSON files |
| Remote | Telegram Bot API |
| Platform | Windows only, requires Administrator |

---

## 5. Бизнес-процессы

### 5.1 Главный процесс: Weekly Farm Cycle

```
[Оператор] → Выбор пачки аккаунтов
    → [Panel] Запуск Steam + CS2 (×N)
    → [Panel] Ожидание главного меню (все аккаунты)
    → [Panel] Создание лобби + поиск игры
    → [Panel] AutoAccept матча
    → [Panel] Загрузка карты (MAP_LOAD_DELAY: 65 сек)
    → [Panel] In-game automation (раунды, сценарии)
    → [Panel] Завершение матча → disconnect (bind j)
    → [Panel] Проверка XP / level up
    → IF all leveled → [Looter] сбор лучшего дропа
    → [Looter] trade offer + mobile confirm
    → [Panel] Следующая пачка из очереди
    → REPEAT
```

**Ключевые триггеры автоматизации:**

| Настройка | Значение | Эффект |
|-----------|----------|--------|
| `START_FARM_WHEN_LAUNCHED` | true | Автосбор лобби после запуска всех аккаунтов |
| `AUTO_LOOT` | true | Автосбор дропа после level up |
| `ENABLE_AUTOACCEPT` | true | Автопринятие найденного матча |
| `REPLACE_ERROR_ACCOUNT` | false | Не заменять упавшие аккаунты автоматически |

### 5.2 Процесс: Запуск аккаунта

**Input:**
- `logpass.txt` → формат `login:password`
- `maFiles/{login}.maFile` → `shared_secret`, `identity_secret`
- `settings/settings.json` → пути, launch options, resolution

**Steps:**
1. Применить `STEAM_LAUNCH_OPTIONS` и `ADDITIONAL_LAUNCH_OPTIONS`
2. Запустить Steam (NO AVAST MODE или Avast Sandbox)
3. Автологин через GUI automation / Steam flags
4. Запустить CS2 с конфигами:
   - `settings/fsm.cfg` — бинды, режим Wingman
   - `settings/cs2_video.txt` — 360×270, минимальная графика
   - `settings/cs2_machine_convars.vcfg` — convars
5. Throttle CPU через BES (`BES_REDUCTION_PERCENT: 25`)
6. Записать аккаунт в `launched_accounts.json`

**Output:** Account status = IN_MENU

**Launch options (из settings.json):**

Steam:
```
-nofriendsui -vgui -noreactlogin -noverifyfiles -nobootstrapupdate
-skipinitialbootstrap -norepairfiles -overridepackageurl -disable-winh264 -language english
```

CS2:
```
-swapcores -noqueuedload -vrdisable -windowed -nopreload -limitvsconst
-softparticlesdefaultoff -nohltv -noaafonts -nosound -novid
+violence_hblood 0 +sethdmodels 0 +mat_disable_fancy_blending 1 +r_dynamic 0
+engine_no_focus_sleep 120
```

### 5.3 Процесс: Matchmaking (2v2 Wingman)

**Preconditions:**
- 4 аккаунта в статусе IN_MENU
- `RUNNING2VS2: true`
- `ui_playsettings_mode_official_v20 scrimcomp2v2` (fsm.cfg)

**Steps:**
1. Создать 2 лобби по 2 игрока
2. Invite между аккаунтами (`LOBBY_INVITE_MODE: 1`)
3. Ready → Search (`mm_dedicated_search_maxping 400`)
4. Retry до `SEARCH_RETRIES_BEFORE_SHUFFLE: 5`
5. Timeout `GAME_SEARCH_TIMEOUT: 90` сек → shuffle
6. AutoAccept (`AUTOACCEPT_READ_TIME: 300` ms)
7. Дождаться загрузки карты (`MAP_LOAD_DELAY: 65` сек)

**In-match logic (fsm.cfg):**
- `bind k +attack` — стрельба
- `bind l +attack2` — альт-огонь
- `bind scancode12 "buy molotov; buy incgrenade;"` — покупка молотова
- `bind scancode39 "buy defuser"` — покупка дефуза
- `bind j disconnect` — выход после матча
- `bind p "exec gamemode_def"` — переключение сценария
- `ROUND_TARGET: 22` — целевое кол-во раундов

**Карты (fsm.cfg):**
- 5v5: `mg_de_ancient`
- 2v2: `mg_de_inferno`

### 5.4 Процесс: Drop Collection (Looter)

**Trigger:** все аккаунты пачки получили level up

**Invocation:**
```bash
node looter_core.js \
  <login> \
  <password> \
  <shared_secret> \
  <identity_secret> \
  <tradeOfferLink> \
  [inventoryString]   # default: "730/2"
```

**Algorithm (`looter/looter_core.js`):**
1. Steam login + TOTP через `shared_secret`
2. Web session → TradeOfferManager
3. Fetch inventory(ies) — поддержка нескольких: `730/2,753/6,...`
4. Add all items to trade offer
5. Send offer → if pending → confirm via `identity_secret`
6. Exit codes: `1` = success, `-1` = error, `0` = insufficient args

**Post-processing:**
- `DELAY_BETWEEN_TRADES: 60` сек между аккаунтами
- Telegram notification (`ITEM_PICTURES_IN_TG: true`)
- Update drop history cache (`DROP_HISTORY_CACHE: true`)

### 5.5 Процесс: Weekly Tracking

**Файлы:**
- `settings/launched_this_week.json` — `{ week_start, week_end, launched_this_week[] }`
- `launched_accounts.json` — текущая сессия

**Business rule:** аккаунт, уже отфармленный на текущей неделе, не включается в очередь (или сортируется — `SORT_ACCOUNTS_BY_LVL`, `ACCOUNTS_SORT_MODE`).

### 5.6 Процесс: Remote Control (Telegram)

**Config:** `TG_BOT_API_KEY`, `TG_BOT_CHAT_ID`

**Capabilities:**
- Уведомления: дроп, ошибки, статус панели
- Скриншот экрана
- Start/stop аккаунтов
- Create lobbies
- Статистика дропов
- Поддержка нескольких пользователей и топиков

### 5.7 Business Rules (Retry & Fallback)

| Событие | Правило | Config key |
|---------|---------|------------|
| Lobby fail | Shuffle after N attempts | `LOBBY_CREATION_ATTEMPTS_BEFORE_SHUFFLE: 3` |
| Search fail | Shuffle after N retries | `SEARCH_RETRIES_BEFORE_SHUFFLE: 5` |
| Search timeout | Abort + shuffle | `GAME_SEARCH_TIMEOUT: 90` |
| Login fail | Retry N times | `ACCOUNT_LOGIN_ATTEMPTS: 2` |
| Account crash | Replace with next in queue | `REPLACE_ERROR_ACCOUNT: false` |
| Batch time limit | Rotate batch | `CHANGE_BATCH_AFTER_N_MINUTES: 70` |

### 5.8 Batch Sizing

| Mode | Accounts | Lobbies | Players/lobby |
|------|----------|---------|---------------|
| 2v2 Wingman | 4 | 2 | 2 |
| 5v5 Competitive | 10 | 2 | 5 |

---

## 6. Модель данных и конфигурация

### 6.1 Account (сущность)

```yaml
Account:
  login: string              # из logpass.txt
  password: string           # ⚠️ plaintext в as-is
  steam_id: string           # optional
  maFile:
    shared_secret: string    # TOTP для логина
    identity_secret: string  # подтверждение трейдов
    revocation_code: string
  status: AccountStatus
  level: int
  xp: int
  farmed_this_week: boolean
  trade_offer_link: string   # optional per-account override
  last_drop: Item | null
  last_error: string | null
```

### 6.2 Item / Drop

```yaml
Item:
  app_id: int                # 730 = CS2
  context_id: int            # 2
  asset_id: string
  market_hash_name: string
  estimated_price: float     # STATS_SKIN_PRICE: 0.6 как baseline
  account_login: string
  received_at: datetime
  traded_at: datetime | null
  trade_offer_id: string | null
```

### 6.3 Полная карта settings.json

#### Paths
| Key | Тип | Описание |
|-----|-----|----------|
| `STEAM_PATH` | string | Путь к Steam |
| `CSGO_PATH` | string | Путь к CS2 |

#### Launch
| Key | Тип | Текущее значение | Описание |
|-----|-----|------------------|----------|
| `STEAM_LAUNCH_OPTIONS` | string | см. раздел 5.2 | Флаги запуска Steam |
| `ADDITIONAL_LAUNCH_OPTIONS` | string | см. раздел 5.2 | Флаги запуска CS2 |
| `DISABLE_STEAM_OVERLAY` | bool | true | Отключить оверлей Steam |
| `CS_RESOLUTION` | string | "360x270" | Разрешение окна CS2 |
| `NO_AVAST_MODE` | bool | true | Встроенный фоновый режим |
| `AVASTSANDBOX_FOLDER` | string | "C:\\avast! sandbox" | Путь к песочнице Avast |
| `DISABLE_CS2_BACKGROUND` | bool | true | Отключить фон CS2 |

#### Farm
| Key | Тип | Текущее значение | Описание |
|-----|-----|------------------|----------|
| `RUNNING2VS2` | bool | true | Режим Wingman 2v2 |
| `FARMING_MODE` | int | 2 | Сценарий счёта (1=ничья, 2=random) |
| `ROUND_TARGET` | int | 22 | Целевое кол-во раундов |
| `START_FARM_WHEN_LAUNCHED` | bool | true | Авто-старт фарма |
| `ANCIENT_MAP_PRELOAD` | bool | true | Предзагрузка карты Ancient |
| `AUTOSHUFFLE_AFTER_GAME` | bool | false | Shuffle после каждой игры |

#### Matchmaking
| Key | Тип | Текущее значение | Описание |
|-----|-----|------------------|----------|
| `LOBBY_INVITE_MODE` | int | 1 | Режим приглашений в лобби |
| `LOBBY_CREATION_ATTEMPTS_BEFORE_SHUFFLE` | int | 3 | Попытки создания лобби |
| `SEARCH_RETRIES_BEFORE_SHUFFLE` | int | 5 | Попытки поиска игры |
| `GAME_SEARCH_TIMEOUT` | int | 90 | Таймаут поиска (сек) |
| `ENABLE_AUTOACCEPT` | bool | true | Автопринятие матча |
| `ALTERNATIVE_AUTOACCEPTER` | bool | false | Альтернативный accept |
| `AUTOACCEPT_READ_TIME` | int | 300 | Задержка accept (ms) |
| `MAP_LOAD_DELAY` | int | 65 | Ожидание загрузки карты (сек) |

#### Accounts
| Key | Тип | Текущее значение | Описание |
|-----|-----|------------------|----------|
| `ACCOUNTS_LAUNCH_DELAY` | int | 0 | Задержка между запусками |
| `ACCOUNT_LOGIN_ATTEMPTS` | int | 2 | Попытки логина |
| `REPLACE_ERROR_ACCOUNT` | bool | false | Автозамена упавших |
| `SORT_ACCOUNTS_BY_LVL` | bool | false | Сортировка по уровню |
| `ACCOUNTS_SORT_MODE` | int | 0 | Режим сортировки |
| `CHANGE_BATCH_AFTER_N_MINUTES` | int | 70 | Ротация пачки (мин) |

#### In-Match
| Key | Тип | Текущее значение | Описание |
|-----|-----|------------------|----------|
| `AUTODISCONNECTS` | bool | false | Авто-дисконнект |
| `AUTODISCONNECTS_DELAY` | int | 11 | Задержка дисконнекта |
| `AUTODISCONNECTS_CHANGE_TEAMS_DELAY` | int | 25 | Смена команд |
| `ANTI_AFK` | bool | false | Анти-AFK |
| `ANTI_AFK_DELAY` | int | 85 | Задержка AFK |
| `ANTI_AFK_MINIMIZE` | bool | false | Минимизация при AFK |
| `ANTI_AFK_POWER` | int | 2 | Интенсивность AFK |

#### Loot
| Key | Тип | Текущее значение | Описание |
|-----|-----|------------------|----------|
| `AUTO_LOOT` | bool | true | Автосбор дропов |
| `TRADEOFFER_LINK` | string | "" | Trade URL для отправки |
| `DELAY_BETWEEN_TRADES` | int | 60 | Задержка между трейдами |
| `DROP_HISTORY_CACHE` | bool | true | Кэш истории дропов |
| `STATS_SKIN_PRICE` | float | 0.6 | Baseline цена для статистики |

#### Performance
| Key | Тип | Текущее значение | Описание |
|-----|-----|------------------|----------|
| `BES_REDUCTION_PERCENT` | int | 25 | % ограничения CPU |
| `CS2_AUTOUPDATER_ENABLED` | bool | true | Автообновление CS2 |

#### Telegram
| Key | Тип | Описание |
|-----|-----|----------|
| `TG_BOT_API_KEY` | string | API ключ бота |
| `TG_BOT_CHAT_ID` | string | Chat ID для уведомлений |
| `ITEM_PICTURES_IN_TG` | bool | Отправлять картинки предметов |

#### UI
| Key | Тип | Текущее значение | Описание |
|-----|-----|------------------|----------|
| `PANEL_POSITION` | string | "1150x665+208+208" | Позиция окна панели |
| `GUI_SCALING` | string | "100%" | Масштаб GUI |
| `KILL_MONITOR_POSITION` | bool | false | Сброс позиции монитора |

---

## 7. Модули и технологии

### 7.1 Panel.exe (Orchestrator)

- **Размер:** ~59 MB
- **Стек:** Python 3.11 + CustomTkinter + PyInstaller
- **Права:** requireAdministrator
- **Статус:** closed source, строки обфусцированы
- **Роль:** GUI, оркестрация всех процессов, управление аккаунтами

### 7.2 Looter (looter/looter_core.js)

Единственный **читаемый исходник** в проекте.

**Зависимости (package.json):**
```json
{
  "steam-session": "^1.3.3",
  "steam-totp": "^2.1.2",
  "steam-tradeoffer-manager": "^2.12.0",
  "steam-user": "^4.29.2",
  "steamcommunity": "^3.45.2"
}
```

**Поток данных:**
```
CLI args → SteamUser.logOn → webSession → TradeOfferManager
  → getInventoryContents(730/2) → createOffer → send
  → acceptConfirmationForObject(identity_secret) → exit(1)
```

### 7.3 BES (Battle Encoder Shirase)

- **Назначение:** ограничение CPU для процессов cs2.exe
- **Конфиг:** `BES/bes.ini` — csgo.exe limit 50%, python.exe as friend
- **Зачем:** при 4–12 окнах CS2 без throttling машина захлёбывается

### 7.4 CS2 Configs

| Файл | Назначение |
|------|------------|
| `settings/fsm.cfg` | Бинды ботов, gamemode, карты, ping |
| `settings/cs2_video.txt` | 360×270, shaderquality 0, msaa 0 |
| `settings/cs2_machine_convars.vcfg` | Полный набор convars CS2 |

### 7.5 Масштабирование (hardware)

| Scale | Accounts | Hardware |
|-------|----------|----------|
| Mini | 4 (2v2) | 1 PC, 16 GB RAM, mid GPU |
| Standard | 10 (5v5) | 1 PC, 32 GB RAM, strong CPU |
| Large | 12+ | Dedicated farm PC, BES required |

---

## 8. Интеграции

```
┌────────────┐    ┌────────────┐    ┌────────────┐
│ Steam API  │    │ CS2 Client │    │ Telegram   │
│ (login,    │    │ (local     │    │ Bot API    │
│  trade,    │    │  process)  │    │            │
│  inventory)│    │            │    │            │
└─────┬──────┘    └─────┬──────┘    └─────┬──────┘
      │                 │                 │
      └────────┬────────┴────────┬────────┘
               │                 │
         ┌─────▼─────────────────▼─────┐
         │      FSM Orchestrator       │
         └─────────────────────────────┘
```

| Integration | Protocol | Used for |
|-------------|----------|----------|
| Steam Client | Local process + web session | Login, launch CS2 |
| Steam Web API | HTTPS + cookies | Inventory, trades |
| Steam Guard TOTP | steam-totp | 2FA login |
| Mobile Confirm | identity_secret | Trade confirmation |
| CS2 | Local game + cfg/exec | Match gameplay |
| Telegram | Bot API | Alerts, remote control |
| BES | Local process control | CPU limiting |

---

## 9. Карта файлов проекта

```
FSM_PANEL v.3.0.1/
├── Panel.exe                    # Main orchestrator (closed source, ~59 MB)
├── icon.ico                     # Иконка приложения
│
├── settings/
│   ├── settings.json            # ★ Master config (51 параметр)
│   ├── fsm.cfg                  # ★ CS2 binds + gamemode Wingman
│   ├── cs2_video.txt            # Min graphics (360×270)
│   ├── cs2_machine_convars.vcfg # CS2 convars
│   └── launched_this_week.json  # Weekly farm tracking
│
├── looter/
│   ├── looter_core.js           # ★ Trade automation (readable source)
│   ├── package.json             # Node.js dependencies
│   ├── package-lock.json
│   └── node_modules/            # steam-user, steamcommunity, etc.
│
├── logpass.txt                  # ⚠️ Account credentials (login:password)
├── maFiles/                     # ⚠️ Steam Guard secrets (.maFile)
├── launched_accounts.json       # Current session tracking
├── sessions/                    # Runtime sessions (empty by default)
│
├── BES/
│   ├── BES.exe                  # CPU limiter
│   ├── bes.ini                  # BES config (csgo.exe 50%)
│   └── src/                     # BES source (C++, GPL)
│
├── autoit/                      # AutoIt scripts (input simulation)
├── customtkinter/               # Python GUI library (bundled)
├── psutil/                      # Process utilities (bundled)
├── Crypto/                      # Cryptography library (bundled)
├── PIL/                         # Python Imaging (bundled)
│
├── python311.dll                # Python 3.11 runtime
├── python3.dll
├── [win32*.pyd]                 # Windows API bindings
├── [tcl/tk]                     # Tkinter runtime
└── [other PyInstaller DLLs]
```

**★ — ключевые файлы для понимания логики**

---

## 10. Риски и минусы для оператора

### 10.1 Risk Register

| ID | Risk | Impact | Likelihood | Mitigation (to-be) |
|----|------|--------|------------|---------------------|
| R1 | Steam ban / trade ban | Critical | Medium-High | Accept; diversify; don't over-invest |
| R2 | Credential theft via malware | Critical | Medium | Encrypted vault; open-source code |
| R3 | CS2 patch breaks automation | High | High | Modular bot; quick config updates |
| R4 | Negative ROI (drops < costs) | High | Medium | Track unit economics per account |
| R5 | Closed vendor lock-in | Medium | N/A for to-be | Own orchestrator |
| R6 | Legal / ToS violation | High | Certain | Document acceptance |
| R7 | Trade hold (15 days) | Medium | Medium | Pre-warm accounts |
| R8 | HWID / license issues | Medium | N/A for to-be | Self-hosted, no license |
| R9 | Looter sends wrong items | High | Low | Item filter; confirm best drop only |
| R10 | Detection via behavior patterns | High | Medium | Randomization; human-like delays |

### 10.2 Детальный разбор рисков

#### 10.2.1 Потеря аккаунтов (критический)

- Нарушение Steam Subscriber Agreement и правил CS2
- Trade ban, game ban, VAC — аккаунт мёртв
- Массовая блокировка пачки обнуляет все вложения
- Панель заявляет «без инжекта», но Valve банит по паттернам: координированные лобби, одинаковое поведение, совпадение IP

#### 10.2.2 Экономика

| Статья расходов | Комментарий |
|-----------------|-------------|
| Лицензия FSM Panel | HWID-bound, перепривязка при смене ПК |
| Аккаунты с Prime | Дешёвые часто «грязные» |
| Прокси / IP | Без них выше риск связки |
| Электричество, железо | 4–12 окон CS2 |
| Время на отладку | Ломается при обновлениях |

`STATS_SKIN_PRICE: 0.6` — baseline ~$0.60 за предмет. Средний дроп может не покрыть затраты.

#### 10.2.3 Зависимость от закрытого ПО

- Обновление CS2/Steam ломает фарм (`CS2_AUTOUPDATER_ENABLED`)
- Разработчик может исчезнуть, поднять цены
- HWID-привязка — проблемы при смене железа
- Баги исправляются только автором

#### 10.2.4 Безопасность

- `logpass.txt` — пароли в plaintext
- `maFiles/` — полные секреты Steam Guard
- Looter использует секреты для автоподтверждения трейдов
- `Panel.exe` с правами администратора — red flag
- Telegram API key — удалённый доступ при утечке

#### 10.2.5 Технические проблемы

- Matchmaking может не находить игру (timeout, shuffle)
- AutoAccept, лобби, загрузка карты — точки отказа
- Один аккаунт «завис» — вся пачка встаёт
- Trade hold 15 дней на новом устройстве
- Looter шлёт **весь инвентарь CS2**, не только лучший дроп

### 10.3 Unit Economics Template

```
Revenue per account/week  = E(drop_value)           # ~$0.10–$2.00 variable
Cost per account/week     = (license + HW + elec) / N_accounts / 52
Margin                    = Revenue - Cost - amortized_account_cost

Break-even requires:
  E(drop_value) > cost_per_account + risk_premium
```

### 10.4 Сводная диаграмма рисков

```
FSM Panel
  ├── Ban аккаунтов ──────────► Потеря всей инвестиции
  ├── Кража через maFiles ────► Потеря всей инвестиции
  ├── Экономика не сходится ──► Работа в минус
  └── Слом после патча CS2 ───► Простой + лицензия впустую
```

---

## 11. Нефункциональные требования (to-be)

### 11.1 Reliability

- [ ] Graceful recovery при краше одного аккаунта
- [ ] Idempotent looter (не дублировать trade offers)
- [ ] Checkpoint state после каждого этапа farm cycle
- [ ] Health checks: Steam running? CS2 in menu? Match alive?

### 11.2 Security (критичный gap as-is)

- [ ] **Не хранить пароли в plaintext** (logpass.txt → encrypted vault)
- [ ] maFiles в encrypted storage (OS keychain / AES-256)
- [ ] Secrets через env vars, не в settings.json
- [ ] Audit log всех trade operations
- [ ] Principle of least privilege (убрать requireAdministrator)

### 11.3 Observability

- [ ] Structured logging (JSON) per account
- [ ] Metrics: success rate, drop value, ban rate, uptime
- [ ] Dashboard: текущие статусы всех аккаунтов
- [ ] Alerting: Telegram + optional webhook

### 11.4 Maintainability

- [ ] Open source orchestrator (не closed exe)
- [ ] Versioned game configs (отдельно от кода)
- [ ] Plugin system для in-game scenarios
- [ ] CI/CD + automated tests для looter module

---

## 12. Roadmap разработки

### Phase 0 — Discovery (1–2 недели)

- [ ] Behavioral analysis Panel.exe (мониторинг процессов, файлов, сети)
- [ ] Инвентаризация всех JSON/cfg контрактов
- [ ] PoC: looter на 1 аккаунте
- [ ] Документирование AutoIt scripts

### Phase 1 — Foundation (2–4 недели)

- [ ] Account vault (encrypted credentials + maFiles)
- [ ] Process manager: launch Steam/CS2
- [ ] Config service (schema-validated settings)
- [ ] Structured logging

### Phase 2 — Core Farm Loop (4–6 недель)

- [ ] Account state machine
- [ ] Lobby creation + invite logic
- [ ] AutoAccept module
- [ ] In-game bot v1 (cfg binds + input simulation)
- [ ] Post-match disconnect + menu detection

### Phase 3 — Loot & Monitoring (2–3 недели)

- [ ] Looter v2: best-drop selection (not full inventory dump)
- [ ] Weekly tracking DB (PostgreSQL)
- [ ] Telegram bot
- [ ] Basic dashboard

### Phase 4 — Hardening (ongoing)

- [ ] Error recovery + replace account
- [ ] CS2 update adapter
- [ ] Performance profiling (BES replacement)
- [ ] Unit economics dashboard

---

## 13. Открытые вопросы (black box Panel.exe)

Следующая логика **не видна в исходниках** и требует reverse engineering:

| # | Вопрос | Приоритет |
|---|--------|-----------|
| 1 | Алгоритм «лучший дроп» — как сравниваются предметы? | High |
| 2 | Menu/lobby detection — OCR, pixel checks, window titles? | High |
| 3 | AutoAccept — чтение экрана или Steam API? | High |
| 4 | In-game scenarios — полная карта FARMING_MODE значений | Medium |
| 5 | NO AVAST MODE — механизм изоляции окон | Medium |
| 6 | Steam Route Tool (SRT) — алгоритм выбора сервера | Medium |
| 7 | Activity Booster — scope для v2? | Low |
| 8 | Armory Pass Collector — scope для v2? | Low |
| 9 | SQLite schema — если используется внутри Panel | Medium |
| 10 | Telegram bot — полный список команд | Medium |

---

## 14. Приложения

### 14.1 Looter CLI Contract

```bash
# Invocation
node looter_core.js \
  <login> \
  <password> \
  <shared_secret> \
  <identity_secret> \
  <tradeOfferLink> \
  [inventoryString]

# inventoryString examples:
#   "730/2"              — CS2 items only (default)
#   "730/2,753/6"        — CS2 + Steam Community items
#   "730/2,440/2"        — CS2 + TF2

# Exit codes:
#   0  = insufficient args (silent exit)
#   1  = trade confirmed successfully
#  -1  = any error (login, inventory, send, confirm)
```

### 14.2 fsm.cfg — ключевые бинды

```
bind k +attack                          # Стрельба
bind l +attack2                         # Альт-огонь
bind j disconnect                       # Выход после матча
bind scancode12 "buy molotov; buy incgrenade;"  # Молотов
bind scancode39 "buy defuser"           # Дефуз
bind p "exec gamemode_def"              # Смена сценария
ui_playsettings_mode_official_v20 scrimcomp2v2    # Wingman mode
mm_dedicated_search_maxping 400         # Max ping
player_competitive_maplist_2v2_10_0_C8D88986 mg_de_inferno  # 2v2 map
player_competitive_maplist_8_10_0_5069769 mg_de_ancient     # 5v5 map
```

### 14.3 cs2_video.txt — оптимизация

```
setting.defaultres: 360
setting.defaultresheight: 270
setting.fullscreen: 0
setting.shaderquality: 0
setting.msaa_samples: 0
setting.gpu_level: 0
setting.cpu_level: 0
```

### 14.4 Decision Log (recommended)

| Date | Decision | Rationale |
|------|----------|-----------|
| TBD | Open-source orchestrator | No vendor lock-in, security audit |
| TBD | Encrypted vault for secrets | logpass.txt is unacceptable |
| TBD | Looter: best drop only | Reduce accidental full inventory loss |
| TBD | PostgreSQL over JSON files | Concurrent access, query stats |
| TBD | Web UI over CustomTkinter | Remote access, multi-operator |

### 14.5 Полезные ссылки

| Resource | URL |
|----------|-----|
| FSM Panel Docs | https://fsmpanel.gitbook.io/guide |
| Функционал | https://fsmpanel.gitbook.io/guide/funkcional-fsm-panel |
| 2v2 Wingman guide | https://fsmpanel.gitbook.io/guide/rabota-s-panelyu/zapusk-avtomaticheskogo-farma-v-rezhime-naparniki-wingman-2x2 |
| 5v5 Simulation guide | https://fsmpanel.gitbook.io/guide/rabota-s-panelyu/zapusk-avtomaticheskogo-farma-v-rezhime-5x5-simulation |
| Telegram channel | https://t.me/fsm_panel |
| Steam SSA | https://store.steampowered.com/subscriber_agreement/ |

---

*Document prepared for internal use. Version 1.0 — 2026-05-29.*
