"""Импорт аккаунтов из FSM-style logpass.txt + maFiles/ → vault.enc."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config.loader import load_config
from config.paths import (
    ensure_fsm_import_dirs,
    get_fsm_logpass_path,
    get_fsm_mafiles_dir,
)
from config.schema import AppConfig
from modules.vault.store import (
    AccountExistsError,
    VaultError,
    has_account,
    upsert_account,
)


@dataclass(frozen=True)
class ImportRowResult:
    login: str
    status: str  # added | updated | skipped | error
    detail: str


def resolve_logpass_path(cfg: AppConfig | None = None, override: Path | None = None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    config = cfg or load_config()
    if config.fsm_logpass_path.strip():
        return Path(config.fsm_logpass_path).expanduser().resolve()
    ensure_fsm_import_dirs()
    return get_fsm_logpass_path()


def resolve_mafiles_dir(cfg: AppConfig | None = None, override: Path | None = None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    config = cfg or load_config()
    if config.fsm_mafiles_dir.strip():
        return Path(config.fsm_mafiles_dir).expanduser().resolve()
    ensure_fsm_import_dirs()
    return get_fsm_mafiles_dir()


def parse_logpass(path: Path) -> list[tuple[str, str]]:
    """Строки login:password; # и пустые пропуск; разделитель — первый ':'."""
    if not path.is_file():
        raise FileNotFoundError(f"logpass not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"logpass must be UTF-8: {path}") from exc

    pairs: list[tuple[str, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"logpass line {lineno}: missing ':' separator")
        login, _, password = line.partition(":")
        login = login.strip()
        password = password.strip()
        if not login:
            raise ValueError(f"logpass line {lineno}: empty login")
        if not password:
            raise ValueError(f"logpass line {lineno}: empty password")
        pairs.append((login, password))
    return pairs


def find_mafile(mafiles_dir: Path, login: str) -> Path | None:
    """{login}.maFile в mafiles_dir (сравнение имени без учёта регистра)."""
    if not mafiles_dir.is_dir():
        return None
    target = f"{login}.maFile".lower()
    for entry in mafiles_dir.iterdir():
        if entry.is_file() and entry.name.lower() == target:
            return entry
    return None


def _mafile_stems(mafiles_dir: Path) -> set[str]:
    if not mafiles_dir.is_dir():
        return set()
    stems: set[str] = set()
    for entry in mafiles_dir.iterdir():
        if entry.is_file() and entry.name.lower().endswith(".mafile"):
            stems.add(entry.name[:-7])
    return stems


def is_import_staging_empty(cfg: AppConfig | None = None) -> bool:
    """Нет строк в logpass и нет .maFile в каталоге импорта."""
    config = cfg or load_config()
    logpass = resolve_logpass_path(config)
    ma_dir = resolve_mafiles_dir(config)
    if logpass.is_file():
        try:
            if parse_logpass(logpass):
                return False
        except (ValueError, FileNotFoundError):
            pass
    return not _mafile_stems(ma_dir)


def import_from_fsm_files(
    *,
    logpass_path: Path | None = None,
    mafiles_dir: Path | None = None,
    update_existing: bool = True,
    dry_run: bool = False,
    cfg: AppConfig | None = None,
) -> list[ImportRowResult]:
    config = cfg or load_config()
    if not config.fsm_import_enabled:
        return [
            ImportRowResult(
                login="",
                status="error",
                detail="fsm_import_enabled=false in config",
            )
        ]

    lp = resolve_logpass_path(config, logpass_path)
    ma_dir = resolve_mafiles_dir(config, mafiles_dir)
    results: list[ImportRowResult] = []

    try:
        pairs = parse_logpass(lp)
    except FileNotFoundError as exc:
        return [ImportRowResult(login="", status="error", detail=str(exc))]
    except ValueError as exc:
        return [ImportRowResult(login="", status="error", detail=str(exc))]

    logins_in_logpass = {login for login, _ in pairs}

    for login, password in pairs:
        ma_path = find_mafile(ma_dir, login)
        if ma_path is None:
            results.append(
                ImportRowResult(
                    login=login,
                    status="skipped",
                    detail=(
                        f"no maFile for login (expected {login}.maFile in {ma_dir})"
                    ),
                )
            )
            continue

        if dry_run:
            action = "updated" if has_account(login) else "added"
            results.append(
                ImportRowResult(
                    login=login,
                    status=action,
                    detail=f"dry-run: {ma_path.name}",
                )
            )
            continue

        existed = has_account(login)
        try:
            entry = upsert_account(
                login=login,
                password=password,
                mafile_path=ma_path,
                update_existing=update_existing,
            )
        except AccountExistsError as exc:
            results.append(ImportRowResult(login=login, status="error", detail=str(exc)))
        except VaultError as exc:
            results.append(ImportRowResult(login=login, status="error", detail=str(exc)))
        except (ValueError, OSError) as exc:
            results.append(ImportRowResult(login=login, status="error", detail=str(exc)))
        else:
            status = "updated" if existed else "added"
            results.append(
                ImportRowResult(login=entry.login, status=status, detail=ma_path.name)
            )

    logpass_lower = {x.lower() for x in logins_in_logpass}
    for stem in sorted(_mafile_stems(ma_dir), key=str.lower):
        if stem.lower() not in logpass_lower and not any(
            r.login.lower() == stem.lower() for r in results if r.login
        ):
            results.append(
                ImportRowResult(
                    login=stem,
                    status="skipped",
                    detail="maFile present but no logpass line (not imported)",
                )
            )

    return results


def format_import_summary(results: list[ImportRowResult]) -> list[str]:
    """Строки для Main log: сводка + по одной строке на error."""
    counts = {"added": 0, "updated": 0, "skipped": 0, "error": 0}
    for row in results:
        if row.status in counts:
            counts[row.status] += 1
    lines = [
        "import: "
        f"added {counts['added']}, updated {counts['updated']}, "
        f"skipped {counts['skipped']}, errors {counts['error']}"
    ]
    for row in results:
        if row.status == "error":
            who = row.login or "(import)"
            lines.append(f"import error [{who}]: {row.detail}")
    return lines
