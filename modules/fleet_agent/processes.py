"""Local Steam/CS2 process presence without touching account secrets."""
from __future__ import annotations

import sys


def _running(image: str) -> bool:
    if sys.platform != "win32":
        return False
    import subprocess
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
        capture_output=True, text=True, check=False, creationflags=flags,
    )
    return image.lower() in (result.stdout or "").lower()


def steam_running() -> bool:
    return _running("steam.exe")


def cs2_running() -> bool:
    return _running("cs2.exe") or _running("csgo.exe")
