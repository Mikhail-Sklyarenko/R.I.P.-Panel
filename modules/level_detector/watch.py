"""Наблюдение во время combat: level_up или max_dm_minutes."""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from config.schema import AppConfig
from modules.level_detector.detector import detect_level_up, sim_level_up_elapsed
from modules.level_detector.result import WatchResult
from modules.ui_nav.artifacts import ArtifactStore


def _capture_frame(ctx: dict[str, Any], artifacts: ArtifactStore) -> Any:
    from PIL import Image

    if os.environ.get("LEVEL_DETECT_SIM", "").lower() in ("1", "true", "yes"):
        from modules.ui_nav.coords import load_nav_coords
        from modules.ui_nav.driver import SimDriver

        config: AppConfig = ctx.get("config")
        res = config.cs_resolution if config else "360x270"
        coords = load_nav_coords(res)
        driver = SimDriver(coords, artifacts)
        driver.set_phase("level_up")
        return driver.capture()

    if sys.platform != "win32":
        return Image.new("RGB", (360, 270), (0, 0, 0))

    from modules.ui_nav.capture import capture_client
    from modules.ui_nav.window import find_cs2_hwnd

    hwnd = ctx.get("hwnd")
    if hwnd is None:
        hwnd = find_cs2_hwnd()
        ctx["hwnd"] = hwnd
    img = capture_client(hwnd)
    artifacts.save_image("level_detect_frame", img)
    return img


def watch(ctx: dict[str, Any] | None = None) -> WatchResult:
    """
    Блокируется до level_up, combat_timeout (max_dm_minutes) или stop_requested.
    """
    if ctx is None:
        ctx = {}
    config: AppConfig | None = ctx.get("config")
    if config is None:
        from config.loader import load_config

        config = load_config()
        ctx["config"] = config

    session_id = str(ctx.get("session_id", "level"))
    artifacts = ArtifactStore(session_id)

    timeout_sec = float(config.max_dm_minutes) * 60.0
    if os.environ.get("LEVEL_DETECT_TIMEOUT_SEC"):
        timeout_sec = max(1.0, float(os.environ["LEVEL_DETECT_TIMEOUT_SEC"]))

    if os.environ.get("LEVEL_DETECT_SIM", "").lower() in ("1", "true", "yes"):
        os.environ["_LEVEL_DETECT_SIM_START"] = str(time.monotonic())

    poll = float(os.environ.get("LEVEL_DETECT_POLL_SEC", "0.5"))
    deadline = time.monotonic() + timeout_sec
    artifacts.log_step(
        "level_watch_start",
        max_dm_minutes=config.max_dm_minutes,
        timeout_sec=timeout_sec,
    )

    while time.monotonic() < deadline:
        if ctx.get("stop_requested"):
            artifacts.log_step("level_watch_stopped")
            return WatchResult.STOPPED

        if sim_level_up_elapsed():
            artifacts.log_step("level_up", source="sim")
            return WatchResult.LEVEL_UP

        try:
            frame = _capture_frame(ctx, artifacts)
            if detect_level_up(frame, resolution=config.cs_resolution):
                artifacts.log_step("level_up", source="ui_probe")
                return WatchResult.LEVEL_UP
        except Exception as exc:
            artifacts.log_step("level_detect_error", err=str(exc))

        time.sleep(poll)

    artifacts.log_step("combat_timeout", max_dm_minutes=config.max_dm_minutes)
    return WatchResult.COMBAT_TIMEOUT
