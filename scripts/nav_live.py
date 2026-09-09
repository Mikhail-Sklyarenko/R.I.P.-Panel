#!/usr/bin/env python3
"""Windows navigation-only harness. Read-only unless --drive; hold CapsLock to move."""
from __future__ import annotations

import argparse
import json
import logging
import queue
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor/csgobot"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drive", action="store_true")
    parser.add_argument("--seconds", type=float, default=120.)
    parser.add_argument("--output", type=Path, default=ROOT / "data/nav_live.jsonl")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Live capture/input requires Windows. Use nav_acceptance.py for offline checks.")
    if not 0 < args.seconds <= 3600:
        parser.error("--seconds must be in (0, 3600]")
    import keyboard
    import pydirectinput
    import win32gui
    from run import create_config, OBS_CANVAS_WIDTH, OBS_CANVAS_HEIGHT
    from config import CaptureRegion
    from grabbers import get_grabber
    from controls.mouse import get_mouse_controls
    from nav.calibration import load_calibration
    from nav.minimap_reader import MinimapReader
    from nav.pack import load_nav_pack
    from nav.paths import resolve_calibration_path, resolve_nav_pack_path
    from nav.place_localizer import PlaceLocalizer
    from nav.release import identity
    from nav.visual_controller import VisualNavController
    from nav.visual_perception import VisualPerception

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    config = create_config()
    if config.grabber_type == "obs_vc":
        config.capture_region = CaptureRegion(0, 0, OBS_CANVAS_WIDTH, OBS_CANVAS_HEIGHT)
    else:
        from utils.win32 import get_window_rect
        config.capture_region = CaptureRegion(*get_window_rect(config.window_title, config.border_offsets))
    if (config.capture_region.width, config.capture_region.height) != (1280, 720):
        raise RuntimeError("This navigation profile requires a 1280x720 game capture.")
    pack = load_nav_pack(resolve_nav_pack_path("dust2_visual_mvp"))
    perception = VisualPerception(MinimapReader(load_calibration(resolve_calibration_path())),
                                  PlaceLocalizer(pack.map_id))
    pydirectinput.PAUSE = 0
    mouse = get_mouse_controls("win32") if args.drive else None
    controller = VisualNavController(pack, SimpleNamespace(fov=config.fov),
        pydirectinput.keyDown if args.drive else lambda key: None,
        pydirectinput.keyUp if args.drive else lambda key: None,
        mouse.move_relative if args.drive else lambda x, y: None, watchdog=True)
    if controller.walkable is None:
        controller.close()
        raise RuntimeError("Missing/invalid profile. Run nav_acceptance.py first.")
    frames, stop = queue.Queue(maxsize=1), threading.Event()
    capture_errors = []

    def capture():
        grabber = None
        try:
            grabber = get_grabber(config.grabber_type, **config.grabber_options)
            while not stop.is_set():
                captured_at = time.monotonic()
                frame = grabber.get_image(config.capture_region.to_dict())
                if frame is None:
                    stop.wait(.01)
                    continue
                try:
                    frames.get_nowait()
                except queue.Empty:
                    pass
                frames.put_nowait((captured_at, frame))
        except Exception as exc:
            capture_errors.append(str(exc))
            logging.exception("Capture failed")
            stop.set()
        finally:
            if grabber is not None:
                grabber.cleanup()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    thread = threading.Thread(target=capture, daemon=True)
    started = time.monotonic()
    print("Dust2 MID lane only, 1280x720. Hold CapsLock to move; release to pause. F10 exits.")
    print("Mode:", "DRIVE" if args.drive else "READ ONLY")
    try:
        with args.output.open("w", encoding="utf-8") as log:
            log.write(json.dumps({"type": "identity", **identity(pack.map_id), "drive": args.drive}) + "\n")
            thread.start()
            last_status = None
            while not stop.is_set() and time.monotonic() - started < args.seconds:
                if keyboard.is_pressed("f10"):
                    break
                focused = config.window_title.lower() in win32gui.GetWindowText(win32gui.GetForegroundWindow()).lower()
                if not focused or not keyboard.is_pressed("caps lock"):
                    controller.release_keys()
                try:
                    captured_at, frame = frames.get(timeout=.02)
                except queue.Empty:
                    continue
                now = time.monotonic()
                if frame.shape[:2] != (720, 1280) or now - captured_at > .25:
                    controller.release_keys()
                    status = "wrong_resolution" if frame.shape[:2] != (720, 1280) else "stale_capture"
                    if status != last_status:
                        print(status)
                        last_status = status
                    continue
                measured = perception.update(frame, now=captured_at)
                # Recheck activation/focus after potentially expensive recognition.
                focused = config.window_title.lower() in win32gui.GetWindowText(win32gui.GetForegroundWindow()).lower()
                paused = not focused or not keyboard.is_pressed("caps lock")
                result = controller.tick(measured.pose, now=time.monotonic(), paused=paused)
                row = {"t": round(now - started, 3), "perception": perception.reason,
                       "state": controller.state.value, "reason": result.reason,
                       "goal": controller.goal_id, "x": measured.pose.x_norm,
                       "y": measured.pose.y_norm, "yaw": measured.pose.yaw_deg,
                       "valid": measured.pose.valid, "forward": result.forward_held,
                       "drive": args.drive, "paused": paused}
                log.write(json.dumps(row) + "\n")
                log.flush()
                status = (perception.reason, controller.state.value, result.reason, controller.goal_id)
                if status != last_status:
                    print(status)
                    last_status = status
    finally:
        stop.set()
        controller.close()
        thread.join(timeout=.5)
    print(f"Session log: {args.output}")
    if capture_errors:
        print("Capture error:", capture_errors[0])
    return 1 if capture_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
