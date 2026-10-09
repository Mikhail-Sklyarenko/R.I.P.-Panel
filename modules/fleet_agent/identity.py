"""Which Steam account is actually signed in on this PC — without any secrets.

Sources, strongest first:
* GSI `provider.steamid` while CS2 runs (the game itself reports the account);
* HKCU\\Software\\Valve\\Steam\\ActiveProcess\\ActiveUser (AccountID of the running client);
* loginusers.vdf (persona name / remembered accounts, never used alone as proof).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.wingman_fleet.models import Identity

STEAMID64_BASE = 76561197960265728


def account_id_to_steam64(account_id: int) -> str:
    return str(STEAMID64_BASE + int(account_id)) if account_id > 0 else ""


def steam64_to_friend_code(steam_id64: str) -> str:
    """Steam friend code = AccountID (the number Steam shows under «Add a friend»)."""
    return str(int(steam_id64) - STEAMID64_BASE) if steam_id64.isdigit() else ""


def _read_registry() -> tuple[int, str]:
    """(ActiveUser AccountID, SteamPath) from HKCU; (0, "") off Windows or on error."""
    if sys.platform != "win32":
        return 0, ""
    import winreg
    active, steam_path = 0, ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess") as key:
            active = int(winreg.QueryValueEx(key, "ActiveUser")[0])
    except OSError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam_path = str(winreg.QueryValueEx(key, "SteamPath")[0])
    except OSError:
        pass
    return active, steam_path


_VDF_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def parse_vdf(text: str) -> dict:
    """Minimal KeyValues parser (enough for loginusers.vdf / localconfig sections)."""
    stack: list[dict] = [{}]
    key: str | None = None
    for m in _VDF_TOKEN.finditer(text):
        s, brace = m.group(1), m.group(2)
        if brace == "{":
            child: dict = {}
            stack[-1][key or ""] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = s
        else:
            stack[-1][key] = s.replace('\\"', '"').replace("\\\\", "\\")
            key = None
    return stack[0]


@dataclass(frozen=True)
class SteamIdentity:
    identity: Identity
    steam_id64: str = ""
    persona: str = ""
    account_name: str = ""
    detail: str = ""

    @property
    def friend_code(self) -> str:
        return steam64_to_friend_code(self.steam_id64)


class IdentityProbe:
    def __init__(self, *, registry: Callable[[], tuple[int, str]] = _read_registry,
                 steam_root: Path | None = None):
        self._registry = registry
        self._steam_root = steam_root

    def _users(self, steam_path: str) -> dict:
        root = self._steam_root or (Path(steam_path) if steam_path else None)
        if root is None:
            return {}
        vdf = root / "config" / "loginusers.vdf"
        try:
            return parse_vdf(vdf.read_text(encoding="utf-8", errors="replace")).get("users", {})
        except OSError:
            return {}

    def probe(self, *, gsi_steam_id64: str = "", gsi_fresh: bool = False,
              expected_steam_id64: str = "") -> SteamIdentity:
        active, steam_path = self._registry()
        local = account_id_to_steam64(active)
        users = self._users(steam_path)
        info = users.get(local, {}) if local else {}
        persona, account = str(info.get("PersonaName", "")), str(info.get("AccountName", ""))
        if gsi_fresh and gsi_steam_id64:
            if local and gsi_steam_id64 != local:
                return SteamIdentity(Identity.MISMATCH, gsi_steam_id64, persona, account,
                                     f"GSI {gsi_steam_id64} != Steam {local}")
            found = SteamIdentity(Identity.GSI, gsi_steam_id64, persona, account)
        elif local:
            found = SteamIdentity(Identity.STEAM_LOCAL, local, persona, account)
        else:
            return SteamIdentity(Identity.UNCONFIRMED, detail="Steam не запущен или вход не выполнен")
        if expected_steam_id64 and found.steam_id64 != expected_steam_id64:
            return SteamIdentity(Identity.MISMATCH, found.steam_id64, persona, account,
                                 f"ожидался {expected_steam_id64}")
        return found

    def remembered_accounts(self) -> list[SteamIdentity]:
        """Accounts with «remember me» on this PC, for the registration screen."""
        _, steam_path = self._registry()
        out = []
        for sid, info in self._users(steam_path).items():
            if isinstance(info, dict) and str(sid).isdigit():
                out.append(SteamIdentity(Identity.UNCONFIRMED, str(sid), str(info.get("PersonaName", "")),
                                         str(info.get("AccountName", "")),
                                         "remembered" if info.get("RememberPassword") == "1" else "no remember-me"))
        return out
