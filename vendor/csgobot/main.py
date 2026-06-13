"""
CS2 Aimbot entry point

Architecture: [Grab Process] --queue--> [Detection Process] --queue--> [Preview Process]
"""

import logging
import multiprocessing
import random
import signal
import sys
import time
from typing import Optional

import cv2
import keyboard

from config import (
    AppConfig,
    CaptureRegion,
    Team,
    create_default_config,
    adjust_region_to_multiple,
)

from grabbers import get_grabber
from controls.mouse import get_mouse_controls
from controls.autobuy import AutoBuyState, update_autobuy
from utils.fps import FPSCounter
from utils.win32 import get_window_rect

from detectors import YOLOv8Detector
from detectors.combat_detect import run_combat_detection
from detectors.detect_debug import log_detect_status
from aiming import FOVMouseMovement, TargetSelector
from aiming.aim_pipeline import AimPipelineState, process_aim_frame
from aiming.fire_actions import apply_fire_action
from aiming.fire_controller import FireAction, FireController
from aiming.combat_aim import maybe_switch_to_body
from aim_tuning import aim_debug_enabled
from patrol import (
    PatrolMode,
    PatrolRunner,
    StuckDetector,
    UnstuckSequence,
    load_patrol,
    next_mode_after_combat_check,
    resolve_patrol_path,
    should_patrol_tick,
    should_trigger_unstuck,
)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("CS2Bot")


class CS2Bot:
    """
    Main class.
    Manages the multiprocess architecture and coordinates all components.
    """

    def __init__(self, config: AppConfig):
        self.config = config

        # Multiprocessing primitives
        self.stop_event = multiprocessing.Event()
        self.activated = multiprocessing.Event()
        self.frame_queue = multiprocessing.Queue()
        self.preview_queue = multiprocessing.Queue()

        # Shared state (using Manager for cross-process access)
        self.manager = multiprocessing.Manager()
        self.shared_state = self.manager.dict({
            "team": config.aim.current_team.value,
            "fps": 0.0,
        })

        self.processes = []

    def _setup_hotkeys(self) -> None:
        """Set up keyboard hotkeys."""
        keyboard.add_hotkey(
            self.config.hotkeys.activation,
            self._toggle_activation,
        )
        keyboard.add_hotkey(
            self.config.hotkeys.change_team,
            self._toggle_team,
        )
        keyboard.add_hotkey(
            self.config.hotkeys.exit,
            self._shutdown,
        )

    def _toggle_activation(self) -> None:
        """Toggle bot activation."""
        if self.activated.is_set():
            self.activated.clear()
            logger.info("Bot DEACTIVATED")
        else:
            self.activated.set()
            logger.info("Bot ACTIVATED")

    def _toggle_team(self) -> None:
        """Toggle between CT and T teams."""
        current = self.shared_state["team"]
        new_team = "t" if current == "ct" else "ct"
        self.shared_state["team"] = new_team
        logger.info(f"Team changed to: {new_team.upper()}")

    def _shutdown(self, *args) -> None:
        """Signal shutdown."""
        logger.info("Shutdown requested...")
        self.stop_event.set()

    def run(self) -> int:
        """
        Run the bot.

        Returns:
            Exit code (0 for success)
        """
        logger.info("Starting CS2 Bot...")

        # Setup
        self._setup_hotkeys()
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        # Start processes
        self.processes = [
            multiprocessing.Process(
                target=grab_process,
                args=(self.frame_queue, self.stop_event, self.config),
                name="GrabProcess",
            ),
            multiprocessing.Process(
                target=detection_process,
                args=(
                    self.frame_queue,
                    self.preview_queue,
                    self.stop_event,
                    self.activated,
                    self.shared_state,
                    self.config,
                ),
                name="DetectionProcess",
            ),
        ]

        if self.config.preview.enabled:
            self.processes.append(
                multiprocessing.Process(
                    target=preview_process,
                    args=(
                        self.preview_queue,
                        self.stop_event,
                        self.shared_state,
                        self.config,
                    ),
                    name="PreviewProcess",
                )
            )

        for p in self.processes:
            p.daemon = True
            p.start()
            logger.info(f"Started {p.name}")

        if self.config.hotkeys.auto_activate:
            self.activated.set()
            logger.info("auto_activate: bot enabled (Caps Lock not required)")

        # Main loop
        child_died = False
        try:
            while not self.stop_event.is_set():
                # Check if any process died
                for p in self.processes:
                    if not p.is_alive():
                        logger.error(f"{p.name} died unexpectedly")
                        child_died = True
                        self.stop_event.set()
                        break
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.stop_event.set()

        # Cleanup
        logger.info("Stopping processes...")
        for p in self.processes:
            p.join(timeout=3)
            if p.is_alive():
                p.terminate()

        logger.info("Shutdown complete")
        return 1 if child_died else 0


def grab_process(
    queue: multiprocessing.Queue,
    stop_event: multiprocessing.Event,
    config: AppConfig,
) -> None:
    """
    Screen capture process.
    """
    logger = logging.getLogger("GrabProcess")
    logger.info("Starting...")

    try:
        grabber = get_grabber(config.grabber_type, **config.grabber_options)
    except Exception as e:
        logger.error(f"Failed to initialize grabber: {e}")
        stop_event.set()
        return

    grab_area = config.capture_region.to_dict()

    while not stop_event.is_set():
        try:
            img = grabber.get_image(grab_area)
            if img is None:
                continue

            # drop old frames, keep only latest
            while not queue.empty():
                try:
                    queue.get_nowait()
                except Exception:
                    break

            queue.put_nowait(img)

        except Exception as e:
            logger.error(f"Capture error: {e}")
            stop_event.set()
            break

    grabber.cleanup()
    logger.info("Stopped")


def detection_process(
    frame_queue: multiprocessing.Queue,
    preview_queue: multiprocessing.Queue,
    stop_event: multiprocessing.Event,
    activated: multiprocessing.Event,
    shared_state: dict,
    config: AppConfig,
) -> None:
    """
    Detection and aiming process.

    - Receives frames from grab process
    - Runs YOLO inference
    - Calculates aim movement (hopefully with correct FOV math xD)
    - Moves mouse (for now, without windmouse, etc.)
    - Sends frames to preview (if enabled)
    """
    logger = logging.getLogger("DetectionProcess")
    logger.info("Starting...")

    import torch

    if config.detector.torch_num_threads > 0:
        torch.set_num_threads(config.detector.torch_num_threads)

    device = config.detector.device or None
    # Initialize detector
    try:
        detector = YOLOv8Detector(
            class_names=config.detector.class_names,
            weights_path=config.detector.weights_path,
            confidence_threshold=config.detector.confidence_threshold,
            iou_threshold=config.detector.iou_threshold,
            device=device,
            half_precision=config.detector.half_precision,
            imgsz=config.detector.imgsz,
            max_det=config.detector.max_det,
        )
        detector.set_colors(config.detector.class_colors)
        logger.info(
            f"Detector: {config.detector.weights_path} "
            f"imgsz={config.detector.imgsz} device={detector.device}"
        )
    except Exception as e:
        logger.error(f"Failed to initialize detector: {e}")
        stop_event.set()
        return

    # Initialize aiming components
    fov_mouse = FOVMouseMovement(
        screen=config.capture_region,
        fov=config.fov,
    )

    target_selector = TargetSelector(
        aim_config=config.aim,
        screen=config.capture_region,
    )

    # Initialize mouse control
    try:
        mouse = get_mouse_controls("win32")
    except Exception as e:
        logger.error(f"Failed to initialize mouse control: {e}")
        stop_event.set()
        return

    fps = FPSCounter()
    last_move_time = 0.0
    fire_controller = FireController.from_aim_config(config.aim)
    fire_announced = False
    patrol_runner: Optional[PatrolRunner] = None
    unstuck_seq: Optional[UnstuckSequence] = None
    stuck_detector: Optional[StuckDetector] = None
    patrol_mode = PatrolMode.PATROL
    last_enemy_seen = 0.0
    stuck_since: Optional[float] = None
    last_unstuck_time = 0.0
    aim_debug = aim_debug_enabled()
    last_aim_debug_log = 0.0
    aim_pipeline = AimPipelineState.from_aim_config(config.aim)
    head_miss_since: Optional[float] = None
    last_target_key: Optional[tuple] = None
    last_detect_debug_log = 0.0
    roi_used_last = False
    autobuy_state = AutoBuyState()
    autobuy_press = None

    if config.autobuy.enabled:
        try:
            import pydirectinput

            autobuy_press = pydirectinput.press
            logger.info(
                "autobuy: enabled key=%s interval=%.1fs burst=%d",
                config.autobuy.buy_key,
                config.autobuy.interval_sec,
                config.autobuy.burst_count,
            )
        except ImportError:
            logger.error("autobuy: pydirectinput missing; disabled")
            config.autobuy.enabled = False

    if config.patrol.enabled:
        try:
            import pydirectinput

            patrol_path = resolve_patrol_path(
                config.patrol.script_name,
                config.patrol.script_path,
            )
            patrol_script = load_patrol(patrol_path)
            patrol_runner = PatrolRunner(
                patrol_script,
                key_down=pydirectinput.keyDown,
                key_up=pydirectinput.keyUp,
            )
            unstuck_seq = UnstuckSequence(
                press=pydirectinput.press,
                key_down=pydirectinput.keyDown,
                key_up=pydirectinput.keyUp,
            )
            stuck_detector = StuckDetector(
                motion_threshold=config.patrol.stuck_motion_threshold,
            )
            logger.info(
                f"patrol: loaded {patrol_script.name} "
                f"({len(patrol_script.steps)} steps) from {patrol_path}"
            )
        except Exception as e:
            logger.error(f"patrol: failed to load ({e}); disabled")
            config.patrol.enabled = False

    try:
        while not stop_event.is_set():
            try:
                img = frame_queue.get(timeout=0.01)
            except Exception:
                continue

            now = time.monotonic()

            # Update team from shared state
            current_team_str = shared_state.get("team", "ct")
            target_selector.config.current_team = Team(current_team_str)

            # Run detection (full frame + optional ROI fallback)
            detections, roi_used_last = run_combat_detection(
                detector,
                img,
                config.detector,
                config.aim,
            )
            last_detect_debug_log = log_detect_status(
                detections=detections,
                enemy_classes=config.aim.enemy_classes,
                roi_used=roi_used_last,
                activated=activated.is_set(),
                now=now,
                last_log=last_detect_debug_log,
            )

            enemy_target = None
            if activated.is_set() and detections:
                enemy_target = target_selector.select_best_target(
                    detections,
                    max_distance=config.aim.max_assist_distance,
                )
            fire_action = FireAction()
            if enemy_target is None:
                head_miss_since = None
                last_target_key = None
                aim_pipeline.reset_trackers()
                if fire_controller.is_holding:
                    fire_action = fire_controller.force_release(now)

            in_combat = enemy_target is not None
            if in_combat:
                last_enemy_seen = now

            if not activated.is_set():
                if fire_controller.is_holding:
                    fire_action = fire_controller.force_release(now)
                if patrol_runner is not None:
                    patrol_runner.pause()
                if unstuck_seq is not None:
                    unstuck_seq.abort()
                stuck_since = None
                patrol_mode = PatrolMode.PATROL
            elif config.patrol.enabled and patrol_runner is not None:
                prev_mode = patrol_mode
                patrol_mode = next_mode_after_combat_check(
                    mode=patrol_mode,
                    in_combat=in_combat,
                    now=now,
                    last_enemy_seen=last_enemy_seen,
                    combat_clear_sec=config.patrol.combat_clear_sec,
                )
                if in_combat:
                    stuck_since = None
                    if unstuck_seq is not None and unstuck_seq.is_running:
                        unstuck_seq.abort()
                        patrol_runner.pause()

                if (
                    config.patrol.pause_on_combat
                    and prev_mode == PatrolMode.PATROL
                    and patrol_mode == PatrolMode.COMBAT
                ):
                    patrol_runner.pause()
                elif (
                    prev_mode == PatrolMode.COMBAT
                    and patrol_mode == PatrolMode.PATROL
                ):
                    patrol_runner.resume()

                unstuck_running = False
                if unstuck_seq is not None and unstuck_seq.is_running:
                    unstuck_running = unstuck_seq.tick(now)
                    if not unstuck_running:
                        last_unstuck_time = now
                        stuck_since = None
                        if stuck_detector is not None:
                            stuck_detector.reset()
                        patrol_runner.reset()
                        patrol_runner.resume()
                        logger.info("patrol: unstuck sequence completed")

                if not unstuck_running and should_patrol_tick(
                    patrol_enabled=config.patrol.enabled,
                    activated=activated.is_set(),
                    mode=patrol_mode,
                ):
                    is_moving = patrol_runner.current_key is not None
                    if (
                        not in_combat
                        and config.patrol.anti_stuck_enabled
                        and stuck_detector is not None
                        and unstuck_seq is not None
                    ):
                        stuck_detector.update(img)
                        if is_moving and stuck_detector.is_low_motion():
                            if stuck_since is None:
                                stuck_since = now
                        else:
                            stuck_since = None

                        if should_trigger_unstuck(
                            anti_stuck_enabled=config.patrol.anti_stuck_enabled,
                            activated=activated.is_set(),
                            patrol_mode=patrol_mode,
                            in_combat=in_combat,
                            is_moving=is_moving,
                            stuck_since=stuck_since,
                            now=now,
                            stuck_sec=config.patrol.stuck_sec,
                            last_unstuck_time=last_unstuck_time,
                            unstuck_cooldown_sec=config.patrol.unstuck_cooldown_sec,
                        ):
                            patrol_runner.pause()
                            unstuck_seq.start(now)
                            stuck_since = None
                            logger.info("patrol: stuck detected, unstuck started")
                        else:
                            patrol_runner.tick(now)
                    else:
                        stuck_since = None
                        patrol_runner.tick(now)
            elif (
                activated.is_set()
                and config.aim.auto_move
                and now - last_move_time >= config.aim.move_interval_sec
            ):
                try:
                    import pydirectinput

                    pydirectinput.press(random.choice(["w", "a", "s", "d"]))
                    last_move_time = now
                except Exception as e:
                    logger.debug(f"auto_move failed: {e}")

            if autobuy_press is not None:
                autobuy_state = update_autobuy(
                    autobuy_state,
                    config=config.autobuy,
                    team=current_team_str,
                    in_combat=in_combat,
                    activated=activated.is_set(),
                    now=now,
                    press=autobuy_press,
                )

            if activated.is_set() and enemy_target is not None:
                target = enemy_target
                target, head_miss_since, switched_body = maybe_switch_to_body(
                    target,
                    prioritize_heads=config.aim.prioritize_heads,
                    aim_dead_zone_high=config.aim.aim_dead_zone_high,
                    body_fallback_sec=config.aim.body_fallback_sec,
                    head_miss_since=head_miss_since,
                    now=now,
                    select_body=lambda: target_selector.select_nearest_body(
                        detections,
                        max_distance=config.aim.max_assist_distance,
                    ),
                )
                if switched_body:
                    aim_pipeline.reset_trackers()

                target_key = (
                    target.class_name,
                    int(target.aim_x // 8),
                    int(target.aim_y // 8),
                )
                if target_key != last_target_key:
                    aim_pipeline.reset_trackers()
                    last_target_key = target_key

                frame = process_aim_frame(
                    raw_x=target.aim_x,
                    raw_y=target.aim_y,
                    target_distance=target.distance,
                    now=now,
                    aim_config=config.aim,
                    fov_mouse=fov_mouse,
                    pipeline=aim_pipeline,
                    fps_value=fps(),
                )

                if frame.should_move and (frame.mouse_dx or frame.mouse_dy):
                    mouse.move_relative(frame.mouse_dx, frame.mouse_dy)

                    if config.aim.one_shot:
                        activated.clear()

                fire_action = fire_controller.tick(
                    pixel_distance=frame.pixel_distance,
                    confidence=target.confidence,
                    is_head=target.is_head,
                    now=now,
                )

                if aim_debug and now - last_aim_debug_log >= 2.0:
                    logger.info(
                        "aim: fps=%.0f dist=%.1f smooth=%.2f "
                        "mouse=(%d,%d) target=(%.0f,%.0f) "
                        "lead_stable=%s speed=%.0f move=%s "
                        "fire=%s hold=%s roi=%s body_fb=%s",
                        fps(),
                        frame.pixel_distance,
                        frame.smoothing,
                        frame.mouse_dx,
                        frame.mouse_dy,
                        frame.aim_x,
                        frame.aim_y,
                        frame.lead.stable,
                        frame.lead.speed_px_s,
                        frame.should_move,
                        fire_action.mode,
                        fire_action.holding,
                        roi_used_last,
                        switched_body,
                    )
                    last_aim_debug_log = now

                if config.preview.enabled:
                    detector.draw_aim_point(
                        img,
                        frame.aim_x,
                        frame.aim_y,
                        color=(0, 255, 0),
                    )

            if (
                fire_action.click
                or fire_action.press
                or fire_action.release
            ):
                apply_fire_action(mouse, fire_action)
                if not fire_announced and (
                    fire_action.fired or fire_action.press
                ):
                    logger.info(
                        "auto_shoot: %s fire active",
                        config.aim.shoot_mode,
                    )
                    fire_announced = True

            # Update FPS
            current_fps = fps()
            shared_state["fps"] = current_fps

            # Send to preview
            if config.preview.enabled:
                if config.preview.paint_boxes:
                    detector.draw_boxes(img, detections)

                while not preview_queue.empty():
                    try:
                        preview_queue.get_nowait()
                    except Exception:
                        break

                preview_queue.put_nowait(img)
    finally:
        apply_fire_action(mouse, fire_controller.force_release(time.monotonic()))
        if unstuck_seq is not None:
            unstuck_seq.abort()
        if patrol_runner is not None:
            patrol_runner.release_all_keys()

    logger.info("Stopped")


def preview_process(
    queue: multiprocessing.Queue,
    stop_event: multiprocessing.Event,
    shared_state: dict,
    config: AppConfig,
) -> None:
    """
    Preview window process (for debug purpose).
    """
    logger = logging.getLogger("PreviewProcess")
    logger.info("Starting...")

    font = cv2.FONT_HERSHEY_SIMPLEX

    while not stop_event.is_set():
        try:
            img = queue.get(timeout=0.01)
        except Exception:
            continue

        # Draw FPS
        if config.preview.show_fps:
            fps_text = f"FPS: {shared_state.get('fps', 0):.1f}"
            cv2.putText(
                img, fps_text, (20, 50),
                font, 1.0, (0, 255, 0), 2, cv2.LINE_AA,
            )

        # Draw team indicator
        if config.preview.show_team:
            team = shared_state.get("team", "ct").upper()
            color = (245, 185, 115) if team == "CT" else (0, 208, 247)
            cv2.putText(
                img, f"Team: {team}", (20, 90),
                font, 1.0, color, 2, cv2.LINE_AA,
            )

        # Convert color if needed
        if config.preview.convert_rgb_to_bgr:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        # Resize for display
        display = cv2.resize(img, config.preview.size)

        cv2.imshow(config.preview.title, display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            stop_event.set()

    cv2.destroyAllWindows()
    logger.info("Stopped")


def main() -> int:
    """Main entry point."""
    # Create configuration
    config = create_default_config()

    # Try to get window rect
    try:
        rect = get_window_rect(
            config.window_title,
            config.border_offsets,
        )
        config.capture_region = CaptureRegion(
            left=rect[0],
            top=rect[1],
            width=rect[2],
            height=rect[3],
        )
        config.capture_region = adjust_region_to_multiple(config.capture_region, 32)
        logger.info(f"Capture region: {config.capture_region}")
    except Exception as e:
        logger.warning(f"Could not get window rect: {e}")
        logger.info("Using default capture region")

    # Create and run bot
    bot = CS2Bot(config)
    return bot.run()


if __name__ == "__main__":
    sys.exit(main())
