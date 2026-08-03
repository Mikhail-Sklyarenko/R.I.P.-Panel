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
from controls.game_input import make_game_key_press
from utils.fps import FPSCounter
from utils.win32 import get_window_rect

from detectors import YOLOv8Detector
from detectors.combat_detect import run_combat_detection
from detectors.detect_debug import log_detect_status
from aiming import FOVMouseMovement, TargetSelector
from aiming.aim_mouse_controller import AimMouseController
from aiming.aim_pipeline import AimPipelineState, process_aim_frame
from aiming.fire_actions import apply_fire_action
from aiming.fire_controller import FireAction, FireController
from aiming.combat_aim import maybe_switch_to_body
from aim_tuning import aim_debug_enabled, team_debug_enabled, map_debug_enabled
from team.hud_team_detect import (
    TeamDetectState,
    detect_team_hud,
    score_probes,
    update_team_hysteresis,
)
from team.paths import resolve_team_probes_path
from team.probes import load_team_probes
from map.hud_map_detect import (
    MapDetectState,
    detect_map_hud,
    update_map_hysteresis,
)
from map.paths import resolve_map_regions_path, resolve_map_templates_dir
from map.regions import load_map_regions
from map.template_match import load_map_templates
from look import LookController
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
            "team_manual_until": 0.0,
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
        override_until = (
            time.monotonic() + self.config.team_detect.manual_override_sec
        )
        self.shared_state["team_manual_until"] = override_until
        logger.info(
            "Team changed to: %s (manual override %.0fs)",
            new_team.upper(),
            self.config.team_detect.manual_override_sec,
        )

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

    # Look must be initialized once here. Do NOT reassign look_controller=None
    # later in this function — that silently disabled all patrol yaw sweeps (PR-L1).
    look_controller: Optional[LookController] = None
    if config.look.enabled:
        look_controller = LookController(
            config=config.look,
            fov_mouse=fov_mouse,
        )
        logger.info(
            "look: enabled yaw=%.0f-%.0f° idle=%.0f-%.0fs sweep=%.2f-%.2fs "
            "abort_cd=%.1fs max_yaw=%.0f°/s max_delta=%d hz=%.0f (L1.3)",
            config.look.yaw_deg_min,
            config.look.yaw_deg_max,
            config.look.idle_sec_min,
            config.look.idle_sec_max,
            config.look.sweep_sec_min,
            config.look.sweep_sec_max,
            config.look.abort_cooldown_sec,
            config.look.max_yaw_deg_per_sec,
            config.look.max_delta,
            config.look.mouse_hz,
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

    aim_mouse: Optional[AimMouseController] = None
    if float(config.aim.mouse_hz) > 0:
        aim_mouse = AimMouseController(
            config=config.aim,
            fov_mouse=fov_mouse,
        )
        aim_mouse.start(mouse.move_relative)

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
    team_probe_set = None
    team_detect_state: Optional[TeamDetectState] = None
    last_team_debug_log = 0.0
    map_regions = None
    map_templates: tuple = ()
    map_detect_state: Optional[MapDetectState] = None
    last_map_debug_log = 0.0
    patrol_key_down = None
    patrol_key_up = None
    patrol_press = None

    if config.team_detect.enabled:
        try:
            probe_path = resolve_team_probes_path(config.team_detect.probes_path)
            team_probe_set = load_team_probes(probe_path)
            team_detect_state = TeamDetectState.from_team(
                shared_state.get("team", config.aim.current_team.value),
            )
            logger.info(
                "team_detect: loaded %d ct + %d t probes from %s",
                len(team_probe_set.ct),
                len(team_probe_set.t),
                probe_path,
            )
        except Exception as e:
            logger.error("team_detect: failed to load probes (%s); disabled", e)
            config.team_detect.enabled = False

    if config.map_detect.enabled:
        try:
            regions_path = resolve_map_regions_path(config.map_detect.regions_path)
            templates_dir = resolve_map_templates_dir(config.map_detect.templates_path)
            map_regions = load_map_regions(regions_path)
            map_templates = load_map_templates(templates_dir)
            map_detect_state = MapDetectState.from_script(config.patrol.script_name)
            shared_state["patrol_script"] = config.patrol.script_name
            logger.info(
                "map_detect: loaded %d templates from %s regions=%s",
                len(map_templates),
                templates_dir.name,
                regions_path.name,
            )
        except Exception as e:
            logger.error("map_detect: failed to load (%s); disabled", e)
            config.map_detect.enabled = False

    if config.autobuy.enabled:
        try:
            autobuy_press = make_game_key_press()
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

            patrol_key_down = pydirectinput.keyDown
            patrol_key_up = pydirectinput.keyUp
            patrol_press = pydirectinput.press

            def _load_patrol_runner(script_name: str) -> PatrolRunner:
                patrol_path = resolve_patrol_path(
                    script_name,
                    config.patrol.script_path,
                )
                patrol_script = load_patrol(patrol_path)
                logger.info(
                    "patrol: loaded %s (%d steps) from %s",
                    patrol_script.name,
                    len(patrol_script.steps),
                    patrol_path,
                )
                return PatrolRunner(
                    patrol_script,
                    key_down=patrol_key_down,
                    key_up=patrol_key_up,
                )

            patrol_runner = _load_patrol_runner(config.patrol.script_name)
            unstuck_seq = UnstuckSequence(
                press=patrol_press,
                key_down=patrol_key_down,
                key_up=patrol_key_up,
            )
            stuck_detector = StuckDetector(
                motion_threshold=config.patrol.stuck_motion_threshold,
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

            if (
                config.map_detect.enabled
                and map_regions is not None
                and map_detect_state is not None
                and map_templates
                and config.patrol.enabled
                and patrol_runner is not None
                and patrol_key_down is not None
                and patrol_key_up is not None
            ):
                detected, detect_source = detect_map_hud(
                    img,
                    map_regions,
                    map_templates,
                    use_ocr_fallback=config.map_detect.use_ocr_fallback,
                )
                map_changed, map_pending = update_map_hysteresis(
                    map_detect_state,
                    detected,
                    confirm_frames=config.map_detect.confirm_frames,
                    lock_after_confirm=config.map_detect.lock_after_confirm,
                )
                if map_changed is not None:
                    try:
                        patrol_runner.pause()
                        patrol_path = resolve_patrol_path(
                            map_changed,
                            config.patrol.script_path,
                        )
                        patrol_script = load_patrol(patrol_path)
                        patrol_runner = PatrolRunner(
                            patrol_script,
                            key_down=patrol_key_down,
                            key_up=patrol_key_up,
                        )
                        patrol_mode = PatrolMode.PATROL
                        stuck_since = None
                        if stuck_detector is not None:
                            stuck_detector.reset()
                        shared_state["patrol_script"] = map_changed
                        logger.info(
                            "map: auto patrol %s via %s (%d/%d frames)",
                            map_changed,
                            detect_source or "unknown",
                            config.map_detect.confirm_frames,
                            config.map_detect.confirm_frames,
                        )
                    except Exception as exc:
                        logger.error("map: patrol reload failed (%s)", exc)
                if map_debug_enabled() and now - last_map_debug_log >= 3.0:
                    logger.info(
                        "map: detect=%s source=%s pending=%d/%d script=%s locked=%s",
                        detected or "none",
                        detect_source or "none",
                        map_pending,
                        config.map_detect.confirm_frames,
                        map_detect_state.confirmed_script,
                        map_detect_state.locked,
                    )
                    last_map_debug_log = now

            if (
                config.team_detect.enabled
                and team_probe_set is not None
                and team_detect_state is not None
                and activated.is_set()
                and now > shared_state.get("team_manual_until", 0.0)
            ):
                winner = detect_team_hud(
                    img,
                    team_probe_set,
                    min_votes=config.team_detect.min_votes,
                )
                changed, pending = update_team_hysteresis(
                    team_detect_state,
                    winner,
                    confirm_frames=config.team_detect.confirm_frames,
                )
                if changed is not None:
                    shared_state["team"] = changed
                    logger.info(
                        "team: auto %s (confirmed %d/%d)",
                        changed,
                        config.team_detect.confirm_frames,
                        config.team_detect.confirm_frames,
                    )
                if team_debug_enabled() and now - last_team_debug_log >= 3.0:
                    ct_score = score_probes(img, team_probe_set.ct)
                    t_score = score_probes(img, team_probe_set.t)
                    logger.info(
                        "team: detect ct_score=%d t_score=%d winner=%s pending=%d/%d",
                        ct_score,
                        t_score,
                        winner or "none",
                        pending,
                        config.team_detect.confirm_frames,
                    )
                    last_team_debug_log = now

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
                if aim_mouse is not None:
                    aim_mouse.clear()
                if fire_controller.is_holding:
                    fire_action = fire_controller.force_release(now)

            in_combat = enemy_target is not None
            if in_combat:
                last_enemy_seen = now

            if not activated.is_set() and aim_mouse is not None:
                aim_mouse.clear()

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

            patrol_buy_freeze = (
                autobuy_press is not None
                and autobuy_state.patrol_freeze_until > now
            )
            unstuck_running = (
                unstuck_seq is not None and unstuck_seq.is_running
            )

            if not activated.is_set():
                if fire_controller.is_holding:
                    fire_action = fire_controller.force_release(now)
                if patrol_runner is not None:
                    patrol_runner.pause()
                if unstuck_seq is not None:
                    unstuck_seq.abort()
                if look_controller is not None:
                    look_controller.abort(now=now)
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
                    if look_controller is not None:
                        look_controller.abort(now=now)
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
                    if patrol_buy_freeze:
                        patrol_runner.pause()
                    else:
                        patrol_runner.resume()

                if unstuck_seq is not None and unstuck_seq.is_running:
                    unstuck_running = unstuck_seq.tick(now)
                    if not unstuck_running:
                        last_unstuck_time = now
                        stuck_since = None
                        if stuck_detector is not None:
                            stuck_detector.reset()
                        patrol_runner.reset()
                        if patrol_buy_freeze:
                            patrol_runner.pause()
                        else:
                            patrol_runner.resume()
                        logger.info("patrol: unstuck sequence completed")

                if patrol_buy_freeze:
                    patrol_runner.pause()
                elif (
                    patrol_runner.is_paused
                    and not unstuck_running
                    and not in_combat
                    and should_patrol_tick(
                        patrol_enabled=config.patrol.enabled,
                        activated=activated.is_set(),
                        mode=patrol_mode,
                    )
                ):
                    patrol_runner.resume()

                look_hold_movement = (
                    look_controller is not None
                    and config.look.pause_movement
                    and look_controller.is_sweeping
                )
                if look_hold_movement:
                    patrol_runner.release_all_keys()

                if (
                    not patrol_buy_freeze
                    and not unstuck_running
                    and not look_hold_movement
                    and should_patrol_tick(
                        patrol_enabled=config.patrol.enabled,
                        activated=activated.is_set(),
                        mode=patrol_mode,
                    )
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
                            if look_controller is not None:
                                look_controller.abort(now=now)
                            unstuck_seq.start(now)
                            unstuck_running = True
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

            if look_controller is not None:
                look_patrol_tick = should_patrol_tick(
                    patrol_enabled=config.patrol.enabled,
                    activated=activated.is_set(),
                    mode=patrol_mode,
                )
                look_should_abort = (
                    not activated.is_set()
                    or enemy_target is not None
                    or in_combat
                    or patrol_buy_freeze
                    or unstuck_running
                    or not config.patrol.enabled
                    or patrol_runner is None
                    or patrol_runner.is_paused
                    or patrol_mode != PatrolMode.PATROL
                )
                if look_should_abort:
                    look_controller.abort(now=now)

                look_active = (
                    config.look.enabled
                    and activated.is_set()
                    and enemy_target is None
                    and not in_combat
                    and patrol_mode == PatrolMode.PATROL
                    and look_patrol_tick
                    and not patrol_buy_freeze
                    and not unstuck_running
                    and patrol_runner is not None
                    and not patrol_runner.is_paused
                )
                look_controller.tick(
                    now=now,
                    active=look_active,
                    apply_mouse=(
                        mouse.move_relative if look_active else None
                    ),
                )
                if (
                    look_active
                    and config.look.pause_movement
                    and look_controller.is_sweeping
                    and patrol_runner is not None
                ):
                    patrol_runner.release_all_keys()

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
                    if aim_mouse is not None:
                        aim_mouse.reset_track()

                target_key = (
                    target.class_name,
                    int(target.aim_x // 8),
                    int(target.aim_y // 8),
                )
                if target_key != last_target_key:
                    aim_pipeline.reset_trackers()
                    if aim_mouse is not None:
                        aim_mouse.reset_track()
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

                if aim_mouse is not None:
                    aim_mouse.set_target(
                        frame.aim_x,
                        frame.aim_y,
                        smoothing=frame.smoothing,
                        now=now,
                    )
                    dbg_dx, dbg_dy = aim_mouse.last_delta
                    if config.aim.one_shot and aim_mouse.consume_applied():
                        activated.clear()
                else:
                    dbg_dx, dbg_dy = frame.mouse_dx, frame.mouse_dy
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
                        "fire=%s hold=%s roi=%s body_fb=%s hz=%.0f settle=%s",
                        fps(),
                        frame.pixel_distance,
                        frame.smoothing,
                        dbg_dx,
                        dbg_dy,
                        frame.aim_x,
                        frame.aim_y,
                        frame.lead.stable,
                        frame.lead.speed_px_s,
                        frame.should_move if aim_mouse is None else bool(dbg_dx or dbg_dy),
                        fire_action.mode,
                        fire_action.holding,
                        roi_used_last,
                        switched_body,
                        float(config.aim.mouse_hz),
                        aim_mouse.is_settled if aim_mouse is not None else False,
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
        if aim_mouse is not None:
            aim_mouse.stop()
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
