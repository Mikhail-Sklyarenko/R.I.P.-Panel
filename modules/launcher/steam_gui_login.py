"""Steam auto-login via GUI automation (FSM-like), vault + maFile TOTP."""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config.paths import get_logs_dir
from config.schema import AppConfig
from modules.launcher.errors import LauncherError, LauncherPlatformError
from modules.launcher.steam_coords import SteamLoginCoords, load_steam_login_coords
from modules.launcher.totp import generate_steam_guard_code
from modules.ui_nav import actions
from modules.ui_nav.errors import UiNavError
from modules.ui_nav.steam_window import (
    SteamWindowKind,
    SteamWindowMatch,
    classify_steam_title,
    find_main_steam_for_login,
    find_steam_hwnd,
    is_steam_login_client,
    is_steam_main_client,
    logged_in_main_visible,
    login_window_open,
    title_indicates_logged_in_as,
    wait_for_login_or_main,
)
from modules.ui_nav.window import client_size, is_invalid_hwnd_error, is_valid_hwnd
from modules.vault.store import AccountNotFoundError, load_account

_log = logging.getLogger(__name__)

_GUARD_POLL_SEC = 30.0
_PUSH_SWITCH_POLL_SEC = 10.0
_FIELD_DELAY_SEC = 0.18
_EMAIL_GUARD_MARKERS = (
    "email",
    "письм",
    "код из email",
    "email code",
)
_PUSH_GUARD_MARKERS = (
    "mobile app",
    "confirm your sign in",
    "steam mobile",
    "confirm sign in",
    "use the steam mobile",
    "enter a code instead",
    "мобильн",
    "подтвердите",
    "подтвержден",
    "введите код",
    "код вместо",
)
_TOTP_ENTRY_MARKERS = (
    "enter the code",
    "steam guard code",
    "authenticator code",
    "enter code",
    "код steam guard",
    "код аутентификатора",
    "введите код",
)


@dataclass(frozen=True)
class SteamGuiLoginResult:
    ok: bool
    login: str
    detail: str
    simulated: bool = False
    already_logged_in: bool = False


def _require_windows() -> None:
    if sys.platform != "win32":
        raise LauncherPlatformError("steam GUI login is Windows-only")


def _sim_result(login: str) -> SteamGuiLoginResult:
    return SteamGuiLoginResult(
        ok=True,
        login=login,
        detail="steam GUI login ok (sim)",
        simulated=True,
    )


def _login_ok_result(
    login: str,
    *,
    coords_profile: str = "",
    note: str = "",
) -> SteamGuiLoginResult:
    suffix = f" coords={coords_profile}" if coords_profile else ""
    if note:
        suffix = f"{suffix} ({note})" if suffix else f" ({note})"
    return SteamGuiLoginResult(
        ok=True,
        login=login,
        detail=f"steam GUI login ok [{login}]{suffix}",
    )


def _finish_if_logged_in(
    login: str,
    coords_profile: str = "",
    *,
    note: str = "",
) -> SteamGuiLoginResult | None:
    """Return success result when MAIN is visible and LOGIN is closed."""
    if logged_in_main_visible(login) is not None:
        return _login_ok_result(login, coords_profile=coords_profile, note=note)
    return None


def _recover_from_ui_error(
    login: str,
    coords_profile: str,
    exc: BaseException,
    *,
    note: str = "main visible after nav error",
) -> SteamGuiLoginResult | None:
    """Treat stale hwnd / nav errors as success when Steam is already logged in."""
    if isinstance(exc, UiNavError) or is_invalid_hwnd_error(exc):
        return _finish_if_logged_in(login, coords_profile, note=note)
    return None


def _validate_secrets(secrets: dict) -> None:
    if not (secrets.get("password") or "").strip():
        raise LauncherError("steam GUI login: empty password in vault")
    if not (secrets.get("shared_secret") or "").strip():
        raise LauncherError(
            "maFile secrets required for steam GUI login (shared_secret missing)"
        )


def _save_fail_screenshot(login: str, hwnd: int, step: str) -> str:
    if not is_valid_hwnd(hwnd):
        return ""
    try:
        from modules.ui_nav.capture import capture_client

        img = capture_client(hwnd)
        log_dir = get_logs_dir() / "steam_login"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_login = "".join(c if c.isalnum() or c in "-_" else "_" for c in login)
        path = log_dir / f"{safe_login}_{ts}_{step}.png"
        img.save(path)
        return str(path)
    except Exception:
        return ""


def _client_coords(hwnd: int) -> SteamLoginCoords:
    if not is_valid_hwnd(hwnd):
        raise UiNavError(f"steam login: window closed (hwnd={hwnd})")
    w, h = client_size(hwnd)
    if w < 100 or h < 100:
        raise UiNavError(f"steam window client area too small: {w}x{h}")
    coords = load_steam_login_coords(w, h)
    _log.info(
        "steam coords profile: %s client=%sx%s",
        coords.profile,
        w,
        h,
    )
    return coords


def _click_named(hwnd: int, coords: SteamLoginCoords, name: str) -> None:
    actions.click_client(hwnd, coords.click(name))


def _type_field(
    hwnd: int,
    coords: SteamLoginCoords,
    field: str,
    text: str,
    *,
    clear_first: bool = False,
) -> None:
    _click_named(hwnd, coords, field)
    time.sleep(_FIELD_DELAY_SEC)
    actions.focus_window(hwnd)
    if clear_first:
        actions.select_all(hwnd)
        time.sleep(0.05)
    actions.paste_text(hwnd, text)
    time.sleep(_FIELD_DELAY_SEC)


def _resolve_login_hwnd(fallback: int = 0, *, timeout_sec: float = 10.0) -> int:
    """Live LOGIN window hwnd; re-find if fallback was closed."""
    if is_valid_hwnd(fallback):
        login = find_steam_hwnd(prefer=SteamWindowKind.LOGIN)
        if login is not None and login.hwnd == fallback:
            return fallback
        if login is not None and is_valid_hwnd(login.hwnd):
            return login.hwnd
        return fallback
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        login = find_steam_hwnd(prefer=SteamWindowKind.LOGIN)
        if login is not None and is_valid_hwnd(login.hwnd):
            return login.hwnd
        time.sleep(0.3)
    raise UiNavError("steam login window not found (closed or not yet open)")


def _guard_phase_complete(login: str) -> bool:
    """LOGIN closed and MAIN Steam visible — Guard/login finished."""
    if login_window_open():
        return False
    return logged_in_main_visible(login) is not None


def _window_text_lower(hwnd: int) -> str:
    if not is_valid_hwnd(hwnd):
        return ""
    import win32gui

    parts = [win32gui.GetWindowText(hwnd) or ""]
    children: list[str] = []

    def _child(child_hwnd: int, _ctx) -> None:
        t = win32gui.GetWindowText(child_hwnd) or ""
        if t:
            children.append(t)

    try:
        win32gui.EnumChildWindows(hwnd, _child, None)
    except Exception:
        pass
    return " ".join(parts + children).lower()


def _detect_email_guard(hwnd: int) -> bool:
    return any(m in _window_text_lower(hwnd) for m in _EMAIL_GUARD_MARKERS)


def _detect_push_guard_from_text(text: str) -> bool:
    low = (text or "").lower()
    if any(m in low for m in _EMAIL_GUARD_MARKERS):
        return False
    return any(m in low for m in _PUSH_GUARD_MARKERS)


def _detect_totp_entry_from_text(text: str) -> bool:
    low = (text or "").lower()
    if _detect_push_guard_from_text(low):
        return False
    if any(m in low for m in _TOTP_ENTRY_MARKERS):
        return True
    if "steam guard" in low and "mobile app" not in low:
        return True
    return False


def _detect_push_guard(hwnd: int) -> bool:
    return _detect_push_guard_from_text(_window_text_lower(hwnd))


def _detect_totp_entry_screen(hwnd: int) -> bool:
    return _detect_totp_entry_from_text(_window_text_lower(hwnd))


def _switch_to_totp_entry(
    hwnd: int,
    coords: SteamLoginCoords,
    *,
    login: str = "",
) -> None:
    """Push screen → click «Enter a code instead»; wait for code entry UI."""
    if _detect_totp_entry_screen(hwnd):
        return
    if "enter_code_instead" not in coords.clicks:
        if _detect_push_guard(hwnd):
            raise UiNavError("steam login: enter_code_instead coord missing in yaml")
        return
    _click_named(hwnd, coords, "enter_code_instead")
    time.sleep(1.5)
    deadline = time.monotonic() + _PUSH_SWITCH_POLL_SEC
    while time.monotonic() < deadline:
        if _detect_totp_entry_screen(hwnd):
            return
        if not _detect_push_guard(hwnd):
            return
        time.sleep(0.4)
    # Steam often does not expose Guard UI text via Win32 — proceed to guard_field paste.
    if _detect_push_guard(hwnd) and not _detect_totp_entry_screen(hwnd):
        shot = _save_fail_screenshot(login, hwnd, "enter_code_miss") if login else ""
        extra = f" screenshot={shot}" if shot else ""
        raise UiNavError(
            f"steam guard: TOTP entry screen not shown after enter_code_instead{extra}"
        )


def _wait_for_guard_ui(
    fallback_hwnd: int,
    *,
    login: str = "",
    timeout_sec: float = 15.0,
) -> int:
    """Poll until LOGIN window shows push or TOTP entry (after password submit)."""
    deadline = time.monotonic() + timeout_sec
    hwnd = fallback_hwnd
    while time.monotonic() < deadline:
        login = find_steam_hwnd(prefer=SteamWindowKind.LOGIN)
        if login is not None and is_valid_hwnd(login.hwnd):
            hwnd = login.hwnd
        elif not is_valid_hwnd(hwnd):
            try:
                hwnd = _resolve_login_hwnd(timeout_sec=2.0)
            except UiNavError:
                time.sleep(0.4)
                continue
        if is_valid_hwnd(hwnd) and (
            _detect_push_guard(hwnd)
            or _detect_totp_entry_screen(hwnd)
            or _detect_email_guard(hwnd)
        ):
            return hwnd
        time.sleep(0.4)
    if is_valid_hwnd(hwnd):
        return hwnd
    if login and _guard_phase_complete(login):
        return 0
    return _resolve_login_hwnd(timeout_sec=2.0)


def _attempt_logout(hwnd: int, coords: SteamLoginCoords) -> None:
    for name in ("account_menu", "sign_out", "sign_out_confirm"):
        if name in coords.clicks:
            _click_named(hwnd, coords, name)
            time.sleep(0.8)


def _wait_main_for_login(
    login: str,
    *,
    timeout_sec: float,
    on_progress: Callable[[str], None] | None = None,
) -> SteamWindowMatch:
    deadline = time.monotonic() + timeout_sec
    last_log = 0.0

    def _heartbeat() -> None:
        main = find_main_steam_for_login(login)
        main_sz = "none"
        if main is not None and is_valid_hwnd(main.hwnd):
            try:
                w, h = client_size(main.hwnd)
                main_sz = f"{w}x{h}"
            except UiNavError:
                main_sz = "?"
        login_open = login_window_open()
        msg = f"waiting logged-in (main={main_sz} login_open={login_open})"
        _log.info("steam GUI login: %s", msg)
        if on_progress:
            on_progress(msg)

    while time.monotonic() < deadline:
        main = logged_in_main_visible(login)
        if main is not None:
            return main
        main = find_main_steam_for_login(login)
        if main is not None and is_valid_hwnd(main.hwnd):
            if is_steam_main_client(main.hwnd):
                return main
            if title_indicates_logged_in_as(main.title, login):
                return main
            login_win = find_steam_hwnd(prefer=SteamWindowKind.LOGIN)
            if login_win is None or not is_valid_hwnd(login_win.hwnd):
                return main
            if not is_steam_login_client(login_win.hwnd):
                return main
        now = time.monotonic()
        if now - last_log >= 10.0:
            _heartbeat()
            last_log = now
        time.sleep(0.5)
    raise UiNavError(
        f"steam main window / logged-in state not detected within {timeout_sec:.0f}s"
    )


def _enter_credentials(
    hwnd: int,
    coords: SteamLoginCoords,
    *,
    login: str,
    password: str,
    retry: bool,
) -> None:
    _type_field(
        hwnd, coords, "account_field", login, clear_first=retry
    )
    _type_field(
        hwnd,
        coords,
        "password_field",
        password,
        clear_first=True,
    )
    actions.focus_window(hwnd)
    actions.press_return(hwnd)
    time.sleep(0.5)
    if retry:
        _click_named(hwnd, coords, "submit")
    time.sleep(1.2 if not retry else 1.8)


def _enter_guard_code(
    hwnd: int,
    coords: SteamLoginCoords,
    shared_secret: str,
    *,
    login: str = "",
) -> None:
    deadline = time.monotonic() + _GUARD_POLL_SEC
    guard_hwnd = hwnd
    totp_attempts = 0
    max_totp_attempts = 2

    while time.monotonic() < deadline:
        if _guard_phase_complete(login):
            return

        login_win = find_steam_hwnd(prefer=SteamWindowKind.LOGIN)
        if login_win is not None and is_valid_hwnd(login_win.hwnd):
            guard_hwnd = login_win.hwnd
        elif not is_valid_hwnd(guard_hwnd):
            if _guard_phase_complete(login):
                return
            try:
                guard_hwnd = _resolve_login_hwnd(timeout_sec=2.0)
            except UiNavError:
                time.sleep(0.4)
                continue

        if _detect_email_guard(guard_hwnd):
            raise LauncherError(
                "steam GUI login: email Steam Guard not supported (use mobile TOTP maFile)"
            )

        coords = _client_coords(guard_hwnd)

        if not _detect_totp_entry_screen(guard_hwnd):
            _switch_to_totp_entry(
                guard_hwnd, coords, login=login
            )
            if _guard_phase_complete(login):
                return
            if not is_valid_hwnd(guard_hwnd):
                login_win = find_steam_hwnd(prefer=SteamWindowKind.LOGIN)
                if login_win is None or not is_valid_hwnd(login_win.hwnd):
                    if _guard_phase_complete(login):
                        return
                    time.sleep(0.4)
                    continue
                guard_hwnd = login_win.hwnd
            coords = _client_coords(guard_hwnd)
            time.sleep(0.5)

        if totp_attempts >= max_totp_attempts:
            break

        try:
            code = generate_steam_guard_code(shared_secret)
        except LauncherError:
            if login:
                _save_fail_screenshot(login, guard_hwnd, "totp_gen_fail")
            raise

        totp_attempts += 1
        if not is_valid_hwnd(guard_hwnd):
            if _guard_phase_complete(login):
                return
            raise UiNavError("steam guard: login window closed during TOTP entry")

        _type_field(
            guard_hwnd,
            coords,
            "guard_field",
            code,
            clear_first=True,
        )
        actions.focus_window(guard_hwnd)
        actions.press_return(guard_hwnd)
        time.sleep(2.0)

        if _guard_phase_complete(login):
            return

        main = find_steam_hwnd(prefer=SteamWindowKind.MAIN)
        if (
            main is not None
            and is_valid_hwnd(main.hwnd)
            and classify_steam_title(main.title) != SteamWindowKind.LOGIN
        ):
            return
        login_win = find_steam_hwnd(prefer=SteamWindowKind.LOGIN)
        if login_win is None or not is_valid_hwnd(login_win.hwnd):
            return
        if not _detect_push_guard(guard_hwnd) and not _detect_totp_entry_screen(
            guard_hwnd
        ):
            return
        time.sleep(0.6)

    if login and is_valid_hwnd(guard_hwnd):
        _save_fail_screenshot(login, guard_hwnd, "guard_timeout")
    raise UiNavError("steam guard field timeout (30s)")


def login_steam_gui(
    login: str,
    config: AppConfig,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> SteamGuiLoginResult:
    """
    GUI login: account + password + TOTP in Steam client window.
    Secrets from vault only — never log password/TOTP.
    """
    login = login.strip()
    if not login:
        raise LauncherError("steam GUI login: login required")

    if os.environ.get("STEAM_GUI_LOGIN_SIM") == "1":
        return _sim_result(login)

    if not config.steam_auto_login:
        return SteamGuiLoginResult(
            ok=True,
            login=login,
            detail="steam_auto_login disabled — manual Steam login expected",
        )

    _require_windows()

    try:
        secrets = load_account(login)
    except AccountNotFoundError as exc:
        raise LauncherError(f"account not in vault: {login}") from exc

    _validate_secrets(secrets)
    password = secrets["password"]
    shared_secret = secrets["shared_secret"]

    timeout = max(30, int(config.steam_login_timeout_sec))
    wait_boot = min(45.0, timeout * 0.25)
    coords_profile = ""

    try:
        done = _finish_if_logged_in(login, coords_profile, note="already in main")
        if done is not None:
            return done

        existing = find_main_steam_for_login(login)
        if existing and title_indicates_logged_in_as(existing.title, login):
            return SteamGuiLoginResult(
                ok=True,
                login=login,
                detail=f"already logged in as {login}",
                already_logged_in=True,
            )

        if existing and existing.kind == SteamWindowKind.MAIN:
            try:
                coords = _client_coords(existing.hwnd)
                _attempt_logout(existing.hwnd, coords)
                time.sleep(2.0)
            except UiNavError as exc:
                recovered = _recover_from_ui_error(
                    login, coords_profile, exc, note="main after logout error"
                )
                if recovered is not None:
                    return recovered

        try:
            login_win, already_logged_in = wait_for_login_or_main(
                timeout_sec=wait_boot,
                login=login,
            )
        except UiNavError as exc:
            recovered = _recover_from_ui_error(
                login, coords_profile, exc, note="main after boot wait"
            )
            if recovered is not None:
                return recovered
            raise

        if already_logged_in:
            return _login_ok_result(
                login, coords_profile=coords_profile, note="main at boot"
            )

        hwnd = login_win.hwnd if login_win is not None else 0

        for attempt in range(2):
            done = _finish_if_logged_in(
                login,
                coords_profile,
                note="main before attempt" if attempt else "main at start",
            )
            if done is not None:
                return done

            if attempt > 0:
                try:
                    login_win, already_logged_in = wait_for_login_or_main(
                        timeout_sec=15.0,
                        login=login,
                    )
                except UiNavError as exc:
                    recovered = _recover_from_ui_error(
                        login,
                        coords_profile,
                        exc,
                        note="main after retry wait",
                    )
                    if recovered is not None:
                        return recovered
                    raise
                if already_logged_in:
                    return _login_ok_result(
                        login,
                        coords_profile=coords_profile,
                        note="main after guard",
                    )
                hwnd = login_win.hwnd if login_win is not None else 0

            try:
                hwnd = _resolve_login_hwnd(hwnd, timeout_sec=5.0)
                coords = _client_coords(hwnd)
            except UiNavError as exc:
                recovered = _recover_from_ui_error(
                    login, coords_profile, exc, note="main after resolve login"
                )
                if recovered is not None:
                    return recovered
                if attempt == 0:
                    continue
                raise

            coords_profile = coords.profile
            _enter_credentials(
                hwnd,
                coords,
                login=login,
                password=password,
                retry=attempt > 0,
            )
            time.sleep(1.0)

            done = _finish_if_logged_in(
                login, coords_profile, note="already in main after creds"
            )
            if done is not None:
                return done

            guard_win = find_steam_hwnd(prefer=SteamWindowKind.LOGIN)
            if guard_win is not None and is_valid_hwnd(guard_win.hwnd):
                hwnd = guard_win.hwnd
            else:
                try:
                    hwnd = _wait_for_guard_ui(
                        hwnd, login=login, timeout_sec=15.0
                    )
                except UiNavError as exc:
                    recovered = _recover_from_ui_error(
                        login,
                        coords_profile,
                        exc,
                        note="main after guard wait",
                    )
                    if recovered is not None:
                        return recovered
                    if attempt == 0:
                        continue
                    raise

            if not is_valid_hwnd(hwnd):
                done = _finish_if_logged_in(
                    login, coords_profile, note="login closed after guard wait"
                )
                if done is not None:
                    return done
                if attempt == 0:
                    continue
                raise UiNavError("steam login window closed before guard entry")

            if _detect_email_guard(hwnd):
                shot = _save_fail_screenshot(login, hwnd, "email_guard")
                extra = f" screenshot={shot}" if shot else ""
                return SteamGuiLoginResult(
                    ok=False,
                    login=login,
                    detail="email Steam Guard not supported" + extra,
                )

            if (
                _detect_push_guard(hwnd)
                or _detect_totp_entry_screen(hwnd)
                or find_steam_hwnd(prefer=SteamWindowKind.LOGIN) is not None
            ):
                try:
                    _enter_guard_code(
                        hwnd, coords, shared_secret, login=login
                    )
                except UiNavError as exc:
                    recovered = _recover_from_ui_error(
                        login,
                        coords_profile,
                        exc,
                        note="main after guard entry",
                    )
                    if recovered is not None:
                        return recovered
                    if attempt == 0:
                        continue
                    raise
                except LauncherError:
                    raise

            done = _finish_if_logged_in(
                login, coords_profile, note="main after guard"
            )
            if done is not None:
                return done

            try:
                _wait_main_for_login(
                    login,
                    timeout_sec=timeout,
                    on_progress=on_progress,
                )
                return _login_ok_result(login, coords_profile=coords_profile)
            except UiNavError as exc:
                recovered = _recover_from_ui_error(
                    login,
                    coords_profile,
                    exc,
                    note="main after wait_main",
                )
                if recovered is not None:
                    return recovered
                if attempt == 0:
                    continue
                raise

        return SteamGuiLoginResult(
            ok=False,
            login=login,
            detail="steam GUI login failed after retry",
        )
    except LauncherError:
        raise
    except UiNavError as exc:
        recovered = _recover_from_ui_error(login, coords_profile, exc)
        if recovered is not None:
            return recovered
        hwnd_match = find_steam_hwnd()
        shot = ""
        if hwnd_match is not None and is_valid_hwnd(hwnd_match.hwnd):
            shot = _save_fail_screenshot(login, hwnd_match.hwnd, "fail")
        detail = str(exc)
        if shot:
            detail = f"{detail} screenshot={shot}"
        return SteamGuiLoginResult(ok=False, login=login, detail=detail)
    except Exception as exc:
        recovered = _recover_from_ui_error(login, coords_profile, exc)
        if recovered is not None:
            return recovered
        raise LauncherError(f"steam GUI login: {exc}") from exc
