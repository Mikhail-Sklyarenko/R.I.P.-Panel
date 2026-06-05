"""Пути приложения: dev source tree или frozen dist/FarmPanel/ (B-PACKAGE)."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path


def _dev_source_root() -> Path:
    return Path(__file__).resolve().parent.parent


@lru_cache(maxsize=1)
def get_app_root() -> Path:
    """
    Корень read-only assets (resources/, vendor/ без data/).
    Dev: исходники farm-panel-prototype/.
    Frozen onedir: каталог FarmPanel.exe (рядом resources/, vendor/).
    """
    override = os.environ.get("FARM_PANEL_APP_ROOT")
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _dev_source_root()


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_bundle_dir() -> Path | None:
    """PyInstaller _MEIPASS (read-only bundled libs); None in dev."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return None


def prototype_root() -> Path:
    """Alias for get_app_root() (legacy name)."""
    return get_app_root()


def get_data_dir() -> Path:
    """Writable data/ рядом с exe (vault, config, logs). Не в _MEIPASS."""
    override = os.environ.get("FARM_PANEL_DATA_DIR")
    if override:
        return Path(override)
    return get_app_root() / "data"


def get_resources_dir() -> Path:
    return get_app_root() / "resources"


def get_vendor_dir() -> Path:
    return get_app_root() / "vendor"


def get_config_path() -> Path:
    return get_data_dir() / "config.yaml"


def get_vault_enc_path() -> Path:
    return get_data_dir() / "vault.enc"


def get_accounts_index_path() -> Path:
    return get_data_dir() / "accounts.index.json"


def get_vault_key_path() -> Path:
    return get_data_dir() / ".vault_key"


def get_logs_dir() -> Path:
    return get_data_dir() / "logs"


def get_events_log_path() -> Path:
    return get_logs_dir() / "events.jsonl"


def get_artifacts_dir(session_id: str) -> Path:
    return get_data_dir() / "artifacts" / session_id


def get_price_cache_path() -> Path:
    return get_data_dir() / "price_cache.db"


def get_fsm_import_dir() -> Path:
    return get_data_dir() / "import"


def get_fsm_logpass_path() -> Path:
    return get_fsm_import_dir() / "logpass.txt"


def get_fsm_mafiles_dir() -> Path:
    return get_fsm_import_dir() / "maFiles"


_LOGPASS_TEMPLATE = """# FSM-style logpass (UTF-8). Одна строка: login:password
# Пустые строки и строки с # в начале пропускаются.
# После Import from logpass секреты только в data/vault.enc (не коммитить этот файл).
#
# example_login:example_password
"""


def ensure_fsm_import_dirs() -> Path:
    """Создать data/import/, шаблон logpass и maFiles/ при первом запуске."""
    import_dir = get_fsm_import_dir()
    import_dir.mkdir(parents=True, exist_ok=True)
    logpass = get_fsm_logpass_path()
    if not logpass.exists():
        logpass.write_text(_LOGPASS_TEMPLATE, encoding="utf-8")
    ma_dir = get_fsm_mafiles_dir()
    ma_dir.mkdir(parents=True, exist_ok=True)
    readme = ma_dir / "README.txt"
    if not readme.exists():
        readme.write_text(
            "Положите сюда {login}.maFile (как в FSM). Имена совпадают с login в logpass.txt.\n",
            encoding="utf-8",
        )
    return import_dir
