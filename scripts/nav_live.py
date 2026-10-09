#!/usr/bin/env python3
"""Windows navigation: F8 toggles autonomous movement; CapsLock also works held."""
from __future__ import annotations

import argparse
import json
import logging
import queue
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor/csgobot"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", dest="map_id", choices=["de_dust2", "de_mirage", "de_inferno", "de_vertigo", "de_cache"], default="de_dust2")
    parser.add_argument("--drive", action="store_true")
    parser.add_argument("--visual-profile", type=Path, help="Optional additional calibrated visual atlas")
    parser.add_argument("--expanded-dust2", action="store_true", help="Experimental radar-derived full-map floor candidates")
    parser.add_argument("--roam", action="store_true", help="Choose goals freely within verified ground")
    parser.add_argument("--turn-rate", type=float, default=300., help="Camera degrees/sec, 60–360")
    parser.add_argument("--seconds", type=float, default=120.)
    parser.add_argument("--output", type=Path, default=ROOT / "data/nav_live.jsonl")
    parser.add_argument("--bundle", type=Path, help="Validated route release from Navigation Studio")
    parser.add_argument("--stop-file", type=Path, help="Studio stop signal; releases controls on exit")
    parser.add_argument("--diagnostics", action=argparse.BooleanOptionalAction, default=True,
                        help="Save at most 60 CS2 frames on navigation failures (one per second)")
    args = parser.parse_args()
    if args.visual_profile is not None and not (args.visual_profile / "atlas.json").is_file():
        parser.error("The selected visual profile has no atlas.json")
    if not 60 <= args.turn_rate <= 360:
        parser.error("--turn-rate must be 60–360")
    if sys.platform != "win32":
        parser.error("Live capture/input requires Windows. Use nav_acceptance.py for offline checks.")
    if not 0 < args.seconds <= 3600:
        parser.error("--seconds must be in (0, 3600]")
    import hashlib
    import numpy as np
    import keyboard
    import cv2
    cv2.setNumThreads(1)
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
    from nav.async_perception import AsyncVisualPerception as VisualPerception

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    config = create_config()
    if config.grabber_type == "obs_vc":
        config.capture_region = CaptureRegion(0, 0, OBS_CANVAS_WIDTH, OBS_CANVAS_HEIGHT)
    else:
        from utils.win32 import get_window_rect
        config.capture_region = CaptureRegion(*get_window_rect(config.window_title, config.border_offsets))
    if (config.capture_region.width, config.capture_region.height) != (1280, 720):
        raise RuntimeError("This navigation profile requires a 1280x720 game capture.")
    if args.expanded_dust2 and args.bundle:
        parser.error("Choose either expanded Dust2 or a Studio bundle")
    ground = None
    if args.bundle:
        from nav.studio import load_bundle
        pack, ground = load_bundle(args.bundle)
    else:
        pack = load_nav_pack(resolve_nav_pack_path("mirage_visual" if args.map_id == "de_mirage" else "dust2_visual_mvp"))
    if args.expanded_dust2 and pack.map_id != "de_dust2":
        parser.error("--expanded-dust2 requires Dust2")
    if args.roam and pack.map_id == "de_mirage" and not args.bundle:
        from nav.walkable import WalkableMap
        ground = WalkableMap.load("de_mirage")
        if ground is None:
            raise RuntimeError("Mirage profile missing")
    if args.expanded_dust2:
        from nav.walkable import WalkableMap
        ground = WalkableMap.load(pack.map_id, ROOT / "resources/nav/experimental/de_dust2")
        if ground is None:
            raise RuntimeError("Expanded profile missing")
        args.roam = True
        print("EXPERIMENTAL: radar-derived ground, not live validated; overlapping floors excluded")
    perception = VisualPerception(MinimapReader(load_calibration(resolve_calibration_path())),
                                  PlaceLocalizer(pack.map_id), visual_profile=args.visual_profile)
    pydirectinput.PAUSE = 0
    mouse = get_mouse_controls("win32") if args.drive else None
    enabled = threading.Event()
    stop = threading.Event()
    def input_allowed():
        return (not stop.is_set() and not keyboard.is_pressed("f10")
                and not (args.stop_file and args.stop_file.exists())
                and (enabled.is_set() or keyboard.is_pressed("caps lock"))
                and config.window_title.lower() in win32gui.GetWindowText(win32gui.GetForegroundWindow()).lower())
    controller = VisualNavController(pack, SimpleNamespace(fov=config.fov),
        pydirectinput.keyDown if args.drive else lambda key: None,
        pydirectinput.keyUp if args.drive else lambda key: None,
        mouse.move_relative if args.drive else lambda x, y: None, watchdog=True,
        input_allowed=input_allowed, walkable=ground, free_roam=args.roam, camera_rate=args.turn_rate)
    if controller.walkable is None:
        controller.close()
        raise RuntimeError("Missing/invalid profile. Run nav_acceptance.py first.")
    frames = queue.Queue(maxsize=1)
    capture_errors = []
    def toggle():
        if enabled.is_set():
            enabled.clear()
            controller.release_keys()
            print("Autonomous navigation: PAUSED")
        else:
            enabled.set()
            print("Autonomous navigation: ON (requires CS2 focus and fresh pose)")

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
    print(f"Engine {identity(pack.map_id)['engine']}; map {pack.map_id}; mode {'free_roam' if args.roam else 'route'}. F8 toggles navigation. F10 exits.")
    print("Mode:", "DRIVE" if args.drive else "READ ONLY")
    hotkey = keyboard.add_hotkey("f8", toggle, trigger_on_release=True)
    states, reasons = Counter(), Counter()
    goal_switches = 0
    diagnostics_dir = args.output.parent / 'nav_diagnostics' / time.strftime('%Y%m%d-%H%M%S')
    diagnostics_count, last_dump = 0, float('-inf')
    try:
        with args.output.open("w", encoding="utf-8") as log:
            log.write(json.dumps({"type": "identity", **identity(pack.map_id), "map_id": pack.map_id,
                "visual_profile": str(args.visual_profile) if args.visual_profile else None,
                "active_ground_sha256": hashlib.sha256(np.uint8(controller.walkable.free).tobytes()).hexdigest(),
                "active_ground_scope": "expanded_experimental" if args.expanded_dust2 else "studio_bundle" if args.bundle else "mid",
                "expanded_dust2": args.expanded_dust2, "navigation_mode": "free_roam" if args.roam else "route", "turn_rate": args.turn_rate, "pack_id": pack.pack_id, "bundle": str(args.bundle) if args.bundle else None, "drive": args.drive}) + "\n")
            thread.start()
            last_status = None
            while not stop.is_set() and time.monotonic() - started < args.seconds:
                if keyboard.is_pressed("f10"):
                    break
                if args.stop_file and args.stop_file.exists():
                    break
                if not input_allowed():
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
                inference_started = time.perf_counter()
                measured = perception.update(frame, now=captured_at)
                inference_ms = (time.perf_counter()-inference_started)*1000
                # Recheck activation/focus after potentially expensive recognition.
                paused = not input_allowed()
                planning_started = time.perf_counter()
                result = controller.tick(measured.pose, door_observation=getattr(perception,"door_observation",None), now=time.monotonic(), paused=paused)
                planning_ms = (time.perf_counter()-planning_started)*1000
                states[controller.state.value] += 1
                reasons[result.reason] += 1
                goal_switches += int(result.goal_switch_event)
                row = {"t": round(now - started, 3), "perception": perception.reason,
                       "state": controller.state.value, "reason": result.reason,
                       "goal": controller.goal_id, "x": measured.pose.x_norm,
                       "y": measured.pose.y_norm, "yaw": measured.pose.yaw_deg,
                       "valid": measured.pose.valid, "forward": result.forward_held,
                       "confidence": measured.pose.confidence, "map_id": pack.map_id,
                       "drive": args.drive, "paused": paused, "auto_enabled": enabled.is_set(),
                       "goal_xy": [controller._route_goal.x, controller._route_goal.y],
                       "target_xy": list(controller.face_target()), "path": controller.path_label,
                       "keys": sorted(controller._keys), "yaw_error": result.yaw_error_deg,
                       "inference_ms": round(inference_ms,2), "planning_ms": round(planning_ms,2),
                       "temporary_obstacles": len(controller._obstacles),
                       "pose_age_sec": result.pose_age_sec, "goal_switch": result.goal_switch_event,
                       "registration_source": perception.reason}
                if (args.diagnostics and not paused and diagnostics_count < 60 and now-last_dump >= 1.
                        and (not measured.pose.valid or controller.state.value == 'blocked')):
                    diagnostics_dir.mkdir(parents=True, exist_ok=True)
                    path = diagnostics_dir / f'frame-{diagnostics_count:03d}.jpg'
                    if cv2.imwrite(str(path), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92]):
                        row['diagnostic_frame'] = str(path)
                        diagnostics_count += 1
                        last_dump = now
                log.write(json.dumps(row) + "\n")
                log.flush()
                status = (perception.reason, controller.state.value, result.reason, controller.goal_id)
                if status != last_status:
                    print(status)
                    last_status = status
    finally:
        stop.set()
        keyboard.remove_hotkey(hotkey)
        controller.close()
        perception.close()
        thread.join(timeout=.5)
        summary = {"engine": identity(pack.map_id)["engine"], "drive": args.drive,
                   "duration_sec": round(time.monotonic()-started, 2),
                   "goal_switches": goal_switches, "state_ticks": dict(states),
                   "reason_ticks": dict(reasons), "capture_errors": capture_errors,
                   "diagnostic_frames": diagnostics_count, "diagnostics_dir": str(diagnostics_dir),
                   "note": "Tick counts are not elapsed time; goal switches alone do not prove collision-free traversal."}
        summary_path = args.output.with_suffix(".summary.json")
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Summary: {summary_path}")
    print(f"Session log: {args.output}")
    if capture_errors:
        print("Capture error:", capture_errors[0])
    return 1 if capture_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
