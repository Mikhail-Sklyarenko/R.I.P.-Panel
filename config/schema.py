"""Схема настроек панели (аналог части FSM settings.json)."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class BotMode(str, Enum):
    """Режим боя: auto → ai если csgobot готов, иначе simple."""

    AUTO = "auto"
    AI = "ai"
    SIMPLE = "simple"


class AppConfig(BaseModel):
    """Пользовательские настройки; пути Steam/CS2 задаются в UI позже."""

    steam_path: str = Field(default="", description="Путь к steam.exe")
    cs2_path: str = Field(default="", description="Путь к cs2.exe")
    trade_offer_link: str = Field(default="", description="Trade URL хранилки")
    auto_collect_drop: bool = Field(
        default=True, description="Автовыбор дропа после level up"
    )
    start_farm_when_launched: bool = Field(
        default=True, description="Старт фарма после запуска CS2"
    )
    only_launch_steam: bool = Field(
        default=False, description="Только Steam, без CS2/DM"
    )
    steam_auto_login: bool = Field(
        default=True,
        description="Автовход Steam из vault (login/password + maFile TOTP)",
    )
    steam_login_mode: Literal["gui", "api", "gui_then_api"] = Field(
        default="gui",
        description="gui: Steam client UI | api: steam_login.js | gui_then_api: fallback",
    )
    steam_classic_login_ui: bool = Field(
        default=True,
        description="Убрать -noreactlogin (классическая форма входа 705×440)",
    )
    steam_login_timeout_sec: int = Field(
        default=120,
        ge=30,
        description="Таймаут GUI login / steam-user logOn",
    )
    steam_kill_before_login: bool = Field(
        default=True,
        description="Kill CS2+Steam перед входом следующего аккаунта",
    )
    steam_dismiss_promo: bool = Field(
        default=True,
        description="Закрыть промо-баннер Steam после login OK (best-effort)",
    )
    steam_promo_dismiss_timeout_sec: int = Field(
        default=10,
        ge=3,
        description="Таймаут detect/dismiss промо-окон Steam",
    )
    telegram_bot_token: str = Field(default="", description="TG Bot API token")
    telegram_chat_id: str = Field(default="", description="TG chat id")
    telegram_send_screenshot: bool = Field(
        default=True,
        description="FSM ITEM_PICTURES_IN_TG: sendPhoto с кадром дропа",
    )
    autofarm_timer_minutes: int = Field(
        default=70, ge=1, description="Лимит сессии / смена acc (мин)"
    )
    cs2_fps_limit_nvidia: int = Field(
        default=0, ge=0, description="Лимит FPS NVIDIA (0 = выкл)"
    )
    cooldown_between_accounts_sec: int = Field(
        default=180, ge=0, description="Пауза между аккаунтами"
    )
    max_dm_minutes: int = Field(
        default=90, ge=1, description="Таймаут в DM без level up"
    )
    level_detect_grace_minutes: int = Field(
        default=10,
        ge=0,
        description="Не проверять level up первые N минут в DM (ложные срабатывания на HUD)",
    )
    level_detect_consecutive_hits: int = Field(
        default=3,
        ge=1,
        description="Сколько опросов подряд должны совпасть все пробы level up",
    )
    game_search_timeout_sec: int = Field(
        default=90, ge=10, description="FSM GAME_SEARCH_TIMEOUT — поиск DM"
    )
    map_load_delay_sec: int = Field(
        default=65, ge=10, description="FSM MAP_LOAD_DELAY — загрузка карты"
    )
    in_dm_min_match: int = Field(
        default=1,
        ge=1,
        description="Soft in_dm: минимум совпавших probes (strict path = все probes)",
    )
    cs2_window_wait_timeout_sec: int = Field(
        default=90,
        ge=15,
        description="Таймаут ожидания окна CS2 после Popen",
    )
    cs2_main_menu_wait_timeout_sec: int = Field(
        default=60,
        ge=15,
        description="Launcher + dm_runner main-menu wait (shared timeout, default 60s)",
    )
    search_retries: int = Field(
        default=5, ge=1, description="FSM SEARCH_RETRIES_BEFORE_SHUFFLE"
    )
    dm_autobuy_spawn_wait_sec: int = Field(
        default=0,
        ge=0,
        le=30,
        description="Deprecated extra delay before buy; use dm_autobuy_offsets_sec",
    )
    dm_autobuy_offsets_sec: str = Field(
        default="3,5,7,9,11",
        description="Buy key times (sec) after team random click — inside DM invuln window",
    )
    cs_resolution: str = Field(
        default="360x270", description="Разрешение CS2 для ui_nav coords"
    )
    cs2_vac_safe_launch: bool = Field(
        default=True,
        description="VAC-safe CS2: applaunch 730, minimal flags, farm_panel.cfg only (no video.txt overwrite)",
    )
    bot_mode: BotMode = Field(
        default=BotMode.AUTO, description="auto | ai | simple"
    )
    cs2_sensitivity: float = Field(
        default=2.1,
        gt=0,
        le=20,
        description="CS2 sensitivity для csgobot X360 (console: sensitivity)",
    )
    csgobot_require_cuda: bool = Field(
        default=False,
        description="Блокировать AI если PyTorch без CUDA (farm GPU only)",
    )
    combat_simple_minutes: int = Field(
        default=10, ge=1, description="Длительность simple-бота (мин)"
    )
    proxy_expected_ip: str = Field(
        default="", description="Ожидаемый exit IP (проверка перед Steam)"
    )
    test_mode: bool = Field(
        default=False, description="Fake modules, без реального Steam"
    )
    appearance_mode: str = Field(
        default="dark", description="dark | light | system"
    )
    gui_scaling: str = Field(
        default="100%", description="Масштаб UI, как FSM GUI_SCALING"
    )
    panel_geometry: str = Field(
        default="1150x665", description="Размер окна WxH"
    )
    fsm_import_enabled: bool = Field(
        default=True,
        description="Импорт из data/import/logpass.txt + maFiles/",
    )
    fsm_logpass_path: str = Field(
        default="",
        description="Путь к logpass.txt (пусто → data/import/logpass.txt)",
    )
    fsm_mafiles_dir: str = Field(
        default="",
        description="Каталог maFiles (пусто → data/import/maFiles/)",
    )
    fsm_import_on_refresh: bool = Field(
        default=False,
        description="Авто-импорт при Refresh accounts (post-MVP)",
    )

    model_config = {"extra": "ignore"}
