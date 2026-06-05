"""Utils: move CS windows, kill CS+Steam, recovery (B12)."""

from __future__ import annotations

from modules.utils.confirm import confirm_kill, should_confirm
from modules.utils.errors import UtilsError, UtilsPlatformError
from modules.utils.kill import KillResult, kill_all_cs_and_steam, kill_all_with_confirm
from modules.utils.recovery import RecoveryResult, recover_hang, recover_move_windows
from modules.utils.windows import CsWindow, MoveResult, list_cs_windows, move_all_cs_windows

__all__ = [
    "CsWindow",
    "KillResult",
    "MoveResult",
    "RecoveryResult",
    "UtilsError",
    "UtilsPlatformError",
    "confirm_kill",
    "kill_all_cs_and_steam",
    "kill_all_with_confirm",
    "list_cs_windows",
    "move_all_cs_windows",
    "recover_hang",
    "recover_move_windows",
    "should_confirm",
]
