"""Kill ALL CS2/CSGO + Steam (B4 cleanup)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any

from config.schema import AppConfig
from modules.utils.errors import UtilsPlatformError


@dataclass(frozen=True)
class KillResult:
    cs2: list[str] = field(default_factory=list)
    steam: list[str] = field(default_factory=list)
    simulated: bool = False
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return not self.cancelled

    def summary(self) -> str:
        if self.cancelled:
            return "cancelled"
        parts: list[str] = []
        if self.cs2:
            parts.append(f"cs2={','.join(self.cs2)}")
        if self.steam:
            parts.append(f"steam={','.join(self.steam)}")
        return "; ".join(parts) if parts else "no processes matched"


def _sim_enabled() -> bool:
    return os.environ.get("UTILS_SIM", "").lower() in ("1", "true", "yes")


def kill_all_cs_and_steam() -> KillResult:
    """Принудительно завершить cs2/csgo + steam (taskkill)."""
    if _sim_enabled():
        return KillResult(
            cs2=["cs2.exe", "csgo.exe"],
            steam=["steam.exe"],
            simulated=True,
        )
    if sys.platform != "win32":
        raise UtilsPlatformError("kill is Windows-only (set UTILS_SIM=1 in tests)")

    from modules.launcher import cleanup

    raw = cleanup.kill_all()
    return KillResult(cs2=list(raw.get("cs2", [])), steam=list(raw.get("steam", [])))


def kill_all_with_confirm(
    *,
    parent: Any | None = None,
    config: AppConfig | None = None,
) -> KillResult:
    del parent, config  # kept for API compatibility
    return kill_all_cs_and_steam()
