"""Наблюдение во время combat: level_up или max_dm_minutes."""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from config.schema import AppConfig
from modules.level_detector.detector import count_level_up_matches, sim_level_up_elapsed
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


def _grace_sec(config: AppConfig) -> float:
    if os.environ.get("LEVEL_DETECT_GRACE_SEC"):
        return max(0.0, float(os.environ["LEVEL_DETECT_GRACE_SEC"]))
    return float(config.level_detect_grace_minutes) * 60.0


def _consecutive_required(config: AppConfig) -> int:
    if os.environ.get("LEVEL_DETECT_CONSECUTIVE_HITS"):
        return max(1, int(os.environ["LEVEL_DETECT_CONSECUTIVE_HITS"]))
    return max(1, config.level_detect_consecutive_hits)


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
    grace_sec = _grace_sec(config)
    consecutive_required = _consecutive_required(config)
    watch_started = time.monotonic()
    deadline = watch_started + timeout_sec
    consecutive_hits = 0
    grace_logged = False

    artifacts.log_step(
        "level_watch_start",
        max_dm_minutes=config.max_dm_minutes,
        timeout_sec=timeout_sec,
        grace_sec=grace_sec,
        consecutive_required=consecutive_required,
    )

    while time.monotonic() < deadline:
        if ctx.get("stop_requested"):
            artifacts.log_step("level_watch_stopped")
            return WatchResult.STOPPED

        if sim_level_up_elapsed():
            artifacts.log_step("level_up", source="sim")
            return WatchResult.LEVEL_UP

        elapsed = time.monotonic() - watch_started
        if grace_sec > 0 and elapsed < grace_sec:
            if not grace_logged:
                artifacts.log_step("level_detect_grace", grace_sec=grace_sec)
                grace_logged = True
        else:
            try:
                frame = _capture_frame(ctx, artifacts)
                matched, required, total = count_level_up_matches(
                    frame,
                    resolution=config.cs_resolution,
                )
                if total > 0 and matched >= required:
                    consecutive_hits += 1
                    artifacts.log_step(
                        "level_probe_hit",
                        matched=matched,
                        required=required,
                        consecutive=consecutive_hits,
                    )
                    if consecutive_hits >= consecutive_required:
                        artifacts.log_step(
                            "level_up",
                            source="ui_probe",
                            matched=matched,
                            required=required,
                            consecutive=consecutive_hits,
                        )
                        return WatchResult.LEVEL_UP
                else:
                    consecutive_hits = 0
            except Exception as exc:
                consecutive_hits = 0
                artifacts.log_step("level_detect_error", err=str(exc))

        time.sleep(poll)

    artifacts.log_step("combat_timeout", max_dm_minutes=config.max_dm_minutes)
    return WatchResult.COMBAT_TIMEOUT
