"""
CS2 Aimbot entry point

Architecture: [Grab Process] --queue--> [Detection Process] --queue--> [Preview Process]
"""

import json
import logging
import multiprocessing
import os
import random
import signal
import sys
import time
from math import hypot
from pathlib import Path
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
from aiming.combat_contact import CombatContact
from aiming.combat_aim import maybe_switch_to_body, observed_fire_distance
from aim_tuning import aim_debug_enabled, team_debug_enabled
from team.hud_team_detect import (
    TeamDetectState,
    detect_team_hud,
    score_probes,
    update_team_hysteresis,
)
from team.paths import resolve_team_probes_path
from team.probes import load_team_probes
from map.hud_map_detect import (
    MatchReadyLatch,
    MapDetectState,
    detect_map_hud,
    unlock_map_detect,
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
            "team_force_sync": False,
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
        """Toggle between CT and T teams (buy/HUD side; aim uses target_mode)."""
        current = self.shared_state["team"]
        new_team = "t" if current == "ct" else "ct"
        self.shared_state["team"] = new_team
        # Detection process must reset hysteresis confirmed_team or auto
        # snaps back to the stale side after override expires.
        self.shared_state["team_force_sync"] = True
        override_until = (
            time.monotonic() + self.config.team_detect.manual_override_sec
        )
        self.shared_state["team_manual_until"] = override_until
        logger.info(
            "Team changed to: %s (manual override %.0fs, target_mode=%s)",
            new_team.upper(),
            self.config.team_detect.manual_override_sec,
            self.config.aim.target_mode,
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
        from fleet_gate import gate as fleet_gate
        try:
            while not self.stop_event.is_set():
                if fleet_gate().stop_requested():
                    logger.info("fleet: cooperative stop requested")
                    self.stop_event.set()
                    break
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
            captured_at = time.monotonic()
            img = grabber.get_image(grab_area)
            if img is None:
                continue

            # drop old frames, keep only latest
            while not queue.empty():
                try:
                    queue.get_nowait()
                except Exception:
                    break

            queue.put_nowait((captured_at, img))

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

    # Small radar operations share this process with detector and map workers.
    cv2.setNumThreads(1)
    logger.info("nav: OpenCV threads=%d", cv2.getNumThreads())

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

    from nav.farm_runtime import CameraOwnership, expanded_mode, create_navigation
    from utils.win32 import get_foreground_window_title
    from fleet_gate import gate as fleet_gate
    integrated_roam = expanded_mode()
    control_frame_at = [0.]
    wingman = None
    if os.environ.get("CSGOBOT_GAME_MODE") == "wingman":
        try:
            from nav.wingman_runtime import WingmanRuntime
            wingman = WingmanRuntime(config,mouse,lambda: activated.is_set() and not stop_event.is_set()
                and fleet_gate().admitted()
                and 0 <= time.monotonic()-control_frame_at[0] <= .25
                and config.window_title.lower() in get_foreground_window_title().lower())
        except Exception:
            logger.exception("Wingman initialization failed")
            stop_event.set()
            return
    camera_owner = CameraOwnership(mouse.move_relative,
        lambda: activated.is_set() and not stop_event.is_set()
        and fleet_gate().admitted()
        and (wingman is None or wingman.camera_allowed())
        and 0 <= time.monotonic()-control_frame_at[0] <= .25
        and config.window_title.lower() in get_foreground_window_title().lower(),
        objective_allowed=wingman.objective_camera_allowed if wingman is not None else None)
    if wingman is not None:wingman.objective_camera=camera_owner

    aim_mouse: Optional[AimMouseController] = None
    if float(config.aim.mouse_hz) > 0:
        aim_mouse = AimMouseController(
            config=config.aim,
            fov_mouse=fov_mouse,
            command_history=camera_owner.commands_since if wingman is not None else None,
        )
        aim_mouse.start(lambda dx,dy: camera_owner.emit("combat",dx,dy))

    fps = FPSCounter()
    last_move_time = 0.0
    fire_controller = FireController.from_aim_config(config.aim)
    fire_announced = False
    patrol_runner: Optional[PatrolRunner] = None
    unstuck_seq: Optional[UnstuckSequence] = None
    stuck_detector: Optional[StuckDetector] = None
    patrol_mode = PatrolMode.PATROL
    last_enemy_seen = 0.0
    combat_contact = CombatContact(grace_sec=.18 if wingman is not None else .10)
    if wingman is not None:
        from aiming.wingman_target import WingmanTargetLock
        wingman_target = WingmanTargetLock()
    stuck_since: Optional[float] = None
    last_unstuck_time = 0.0
    aim_debug = aim_debug_enabled()
    last_aim_debug_log = 0.0
    aim_pipeline = AimPipelineState.from_aim_config(config.aim)
    head_miss_since: Optional[float] = None
    body_preferred_until = 0.
    last_target_key: Optional[tuple] = None
    last_target_aim: Optional[tuple] = None
    last_detect_debug_log = 0.0
    roi_used_last = False

    auto_capture = None
    try:
        from dataset_capture import AutoCaptureController, resolve_auto_capture_config

        capture_cfg = resolve_auto_capture_config(
            default_enabled=bool(getattr(config.auto_capture, "enabled", False))
        )
        if capture_cfg.enabled:
            auto_capture = AutoCaptureController(
                capture_cfg,
                cwd=Path(__file__).resolve().parent,
                weights_name=str(Path(config.detector.weights_path).name),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto_capture: init failed: %s", exc)
        auto_capture = None
    autobuy_state = AutoBuyState()
    autobuy_press = None
    team_probe_set = None
    team_detect_state: Optional[TeamDetectState] = None
    last_team_debug_log = 0.0
    map_regions = None
    map_templates: tuple = ()
    map_detect_state: Optional[MapDetectState] = None
    last_map_debug_log = 0.0
    last_nav_debug_log = 0.0
    last_nav_metrics_at = 0.0
    # Preserve intent through init failures: do not silently substitute blind
    # patrol/auto_move when measured navigation was requested.
    nav_requested = config.nav.enabled
    map_transition_active = False
    match_ready_latch = MatchReadyLatch(confirm_frames=20)
    nav_reader = None
    nav_map_selector = None
    nav_map_seen_at = 0.
    nav_map_confirmed = config.nav.pack_id not in ("", "auto")
    nav_pose_filter = None
    nav_perception = None
    nav_pack = None
    active_nav_pack_id = ""
    nav_controller = None
    nav_metrics = None
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

    if config.nav.enabled:
        try:
            from nav.pack_resolve import resolve_initial_nav_pack_id, measured_runtime_pack
            from nav.preflight import run_nav_preflight
            from nav.paths import resolve_calibration_path, resolve_nav_pack_path

            active_nav_pack_id = resolve_initial_nav_pack_id(
                explicit_pack=config.nav.pack_id,
                patrol_script=config.patrol.script_name,
            )
            active_nav_pack_id = measured_runtime_pack(active_nav_pack_id, config.nav.pack_id)
            pf = run_nav_preflight(
                pack_id=active_nav_pack_id,
                calibration_path=config.nav.calibration_path,
            )
            for warn in pf.get("warnings", []):
                logger.warning("nav: preflight warn — %s", warn)
            if not pf.get("ok"):
                for err in pf.get("errors", []):
                    logger.error("nav: preflight — %s", err)
                logger.error("nav: preflight failed; navigation input disabled")
                config.nav.enabled = False
            else:
                cal_path = resolve_calibration_path(config.nav.calibration_path)
                pack_path = resolve_nav_pack_path(active_nav_pack_id)
                logger.info(
                    "nav: preflight ok pack=%s v%s strategy=%s goals=%s",
                    active_nav_pack_id,
                    pf.get("pack_version") or pf.get("pack_versions"),
                    pf.get("strategy"),
                    pf.get("goals") or pf.get("packs_ok"),
                )
        except Exception as exc:
            logger.error("nav: preflight error (%s); disabled", exc)
            config.nav.enabled = False

    if config.nav.enabled:
        try:
            if patrol_key_down is None:
                import pydirectinput
                patrol_key_down, patrol_key_up = pydirectinput.keyDown, pydirectinput.keyUp
            from nav.calibration import load_calibration
            from nav.metrics import NavMetrics
            from nav.minimap_reader import MinimapReader
            from nav.pack import load_nav_pack
            from nav.paths import resolve_calibration_path, resolve_nav_pack_path
            from nav.async_perception import AsyncVisualPerception as NavPerception
            from nav.place_localizer import PlaceLocalizer
            from nav.pose_filter import PoseFilter
            nav_cal_path = resolve_calibration_path(config.nav.calibration_path)
            nav_cal = load_calibration(nav_cal_path)
            if integrated_roam and config.nav.pack_id in ("", "auto"):
                from nav.map_selector import AsyncVisualMapSelector
                nav_map_selector = AsyncVisualMapSelector(nav_cal)
            nav_pack_path = resolve_nav_pack_path(active_nav_pack_id)
            nav_pack = load_nav_pack(nav_pack_path)
            nav_reader = MinimapReader(nav_cal)
            nav_pose_filter = PoseFilter(nav_cal.pose)
            nav_place = PlaceLocalizer(nav_pack.map_id)
            nav_perception = NavPerception(nav_reader, nav_place)
            from nav.release import identity
            logger.info("nav: integrated mode=%s", "wingman_fixed_goal" if wingman is not None else "expanded_roam" if integrated_roam else "route")
            logger.info("nav: runtime_identity %s", json.dumps(wingman.navigation_identity() if wingman is not None else identity(nav_pack.map_id), sort_keys=True))
            if not config.nav.read_only:
                if patrol_key_down is None or patrol_key_up is None:
                    raise RuntimeError(
                        "nav movement requires patrol keys (pydirectinput)"
                    )
                nav_controller = create_navigation(
                    nav_pack, fov_mouse, patrol_key_down, patrol_key_up, camera_owner,
                    expanded=integrated_roam, logger=logger,
                )
                nav_metrics = NavMetrics(
                    log_interval_sec=config.nav.metrics_log_interval_sec,
                )
                nav_metrics.set_pack_id(nav_pack.pack_id)
                goal_ids = ", ".join(g.id for g in nav_pack.goals)
                logger.info(
                    "nav: controller ready pack=%s strategy=%s goals=[%s] "
                    "locomotion=measured-visual",
                    nav_pack.pack_id,
                    nav_pack.strategy,
                    goal_ids,
                )
            else:
                logger.info(
                    "nav: read_only pose pack=%s map=%s goal=%s (%.2f,%.2f)",
                    nav_pack.pack_id,
                    nav_pack.map_id,
                    nav_pack.goal.id,
                    nav_pack.goal.x,
                    nav_pack.goal.y,
                )
        except Exception as exc:
            logger.error("nav: init failed (%s); disabled", exc)
            config.nav.enabled = False

    if integrated_roam and (nav_controller is None or nav_controller.walkable is None):
        logger.error("Integrated navigation unavailable; stopping combat worker")
        stop_event.set()

    from concurrent.futures import ThreadPoolExecutor
    nav_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nav-current-frame")
    previous_nav_combat_hold = False
    last_nav_timing_log = 0.
    try:
        while not stop_event.is_set():
            try:
                captured_at, img = frame_queue.get(timeout=0.01)
            except Exception:
                if not camera_owner.allowed():
                    camera_owner.select(None)
                    if aim_mouse is not None:
                        aim_mouse.clear()
                    if fire_controller.is_holding:
                        apply_fire_action(mouse,fire_controller.force_release(time.monotonic()))
                # A stalled capture must release movement even without another
                # frame reaching the controller's normal freshness check.
                if nav_controller is not None:
                    observed = getattr(nav_controller.last_pose, "observed_at", None)
                    if not getattr(nav_controller,"input_active", observed is not None and time.monotonic()-observed<=.25):
                        nav_controller.release_keys()
                continue

            now = time.monotonic()
            control_frame_at[0] = captured_at
            if now - captured_at > .25:
                camera_owner.select(None)
                if aim_mouse is not None:
                    aim_mouse.clear()
                if fire_controller.is_holding:
                    apply_fire_action(mouse,fire_controller.force_release(now))
                if nav_controller is not None:
                    nav_controller.release_keys()
                continue

            if wingman is not None:
                current_state=wingman.receiver.state.snapshot()
                if (current_state is not None and current_state.observation.connected
                        and current_state.observation.own_player
                        and current_state.observation.map_id!=wingman.map_id):
                    camera_owner.select(None)
                    if aim_mouse is not None:aim_mouse.clear()
                    apply_fire_action(mouse,fire_controller.force_release(now))
                    if nav_controller is not None:nav_controller.release_keys()
                    try:
                        selected_map=current_state.observation.map_id
                        selected_pack={"de_inferno":"inferno_visual","de_nuke":"nuke_wingman"}[selected_map]
                        check=run_nav_preflight(pack_id=selected_pack,calibration_path=config.nav.calibration_path)
                        if not check.get("ok"):raise ValueError(str(check.get("errors")))
                        new_pack=load_nav_pack(resolve_nav_pack_path(selected_pack))
                        # Every previous nav future is consumed within its own frame.
                        # Closing perception additionally invalidates atlas workers.
                        if nav_perception is not None:nav_perception.close()
                        wingman.select_map(selected_map)
                        if nav_controller is not None:nav_controller.reload_pack(new_pack)
                        nav_reader=MinimapReader(nav_cal)
                        nav_reader.competitive_markers=True
                        nav_perception=NavPerception(nav_reader,PlaceLocalizer(selected_map))
                        nav_pose_filter.reset();wingman_target.reset()
                        aim_pipeline.reset_trackers()
                        combat_contact.update(detected=False,active=False,now=now)
                        previous_nav_combat_hold=False
                        if nav_metrics is not None:
                            nav_metrics.set_pack_id(selected_pack)
                            nav_metrics.start(now)
                        nav_pack=new_pack;active_nav_pack_id=selected_pack
                        logger.info("nav: runtime_identity %s",json.dumps(wingman.navigation_identity(),sort_keys=True))
                    except Exception:
                        logger.exception("wingman: map switch failed; stopping worker")
                        break
                if nav_reader is not None:nav_reader.competitive_markers = True
                wingman.observe(img,nav_controller,now=now)
                if nav_reader is not None:
                    nav_reader.objective_overlay_allowed=bool(wingman.snapshot and
                        wingman.snapshot.observation.bomb=="planted" and wingman.decision.navigation)
                wingman.set_objective(nav_controller,now=now)
                if not wingman.decision.combat or wingman.interaction is not None or wingman.restoring_camera:
                    wingman_target.reset()
                    camera_owner.select(None)
                    if aim_mouse is not None:aim_mouse.clear()
                    apply_fire_action(mouse,fire_controller.force_release(now))
                    if nav_controller is not None:nav_controller.release_keys()
                    if wingman.decision.state == "finished":
                        logger.info("wingman: match_finished")
                        stop_event.set()
                        break
                    camera_owner.select("objective" if wingman.objective_camera_allowed() else None)
                    wingman.idle_tick(nav_controller,now=now)
                    continue

            if not camera_owner.allowed():
                camera_owner.select(None)
                if aim_mouse is not None:
                    aim_mouse.clear()
                if nav_controller is not None:
                    nav_controller.release_keys()
                if look_controller is not None:
                    look_controller.abort(now=now)
                if fire_controller.is_holding:
                    apply_fire_action(mouse,fire_controller.force_release(now))
                continue

            map_transition_active = False
            if (
                config.map_detect.enabled
                and map_regions is not None
                and map_detect_state is not None
                and map_templates
            ):
                detected, detect_source = detect_map_hud(
                    img,
                    map_regions,
                    map_templates,
                    use_ocr_fallback=config.map_detect.use_ocr_fallback,
                )
                from nav.map_confirmation import named_match_ready, active_map_confirmed
                # Only a detected map name may activate the match-ready hold.
                # The old bare pixel probe falsely fired on live Mirage scenery.
                map_transition_active = match_ready_latch.update(
                    named_match_ready(detected, detect_source)
                )
                if map_transition_active and nav_controller is not None:
                    nav_controller.release_keys()
                # Do not discard the known map on a readiness probe. The named
                # map detector/geometry selector below confirms actual changes.
                # Training may show neither scoreboard nor match-ready map name.
                # Query geometry only after the current map has lost localization.
                if nav_map_selector is not None:
                    if detected is None and (not nav_map_confirmed or now-nav_map_seen_at > 3.):
                        candidate = nav_map_selector.update(img, now=captured_at)
                        if candidate is not None:
                            detected = candidate.removeprefix("de_")
                            detect_source = "visual_geometry"
                    else:
                        nav_map_selector.reset()
                # Match-ready with a *different* map name also unlocks before hysteresis.
                if (
                    detect_source in ("match_ready", "visual_geometry")
                    and detected is not None
                    and detected != map_detect_state.confirmed_script
                    and map_detect_state.locked
                ):
                    if unlock_map_detect(map_detect_state):
                        logger.info(
                            "map: unlock (match_ready map=%s) was=%s",
                            detected,
                            map_detect_state.confirmed_script,
                        )

                map_changed, map_pending = update_map_hysteresis(
                    map_detect_state,
                    detected,
                    confirm_frames=1 if detect_source == "visual_geometry" else config.map_detect.confirm_frames,
                    lock_after_confirm=config.map_detect.lock_after_confirm,
                    allow_reconfirm=True,
                )
                if map_changed is not None:
                    try:
                        if config.patrol.enabled and patrol_runner is not None and not config.nav.enabled:
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
                            "map: confirmed %s via %s (%d/%d frames)",
                            map_changed,
                            detect_source or "unknown",
                            config.map_detect.confirm_frames,
                            config.map_detect.confirm_frames,
                        )
                        if (
                            config.nav.enabled
                            and nav_pack is not None
                        ):
                            from nav.pack_resolve import nav_pack_for_script

                            new_pack_id = nav_pack_for_script(
                                map_changed,
                                config.nav.pack_id,
                            )
                            if new_pack_id:
                                new_pack_id = measured_runtime_pack(new_pack_id, config.nav.pack_id)
                            if (
                                new_pack_id
                                and new_pack_id != nav_pack.pack_id
                            ):
                                from nav.pack import load_nav_pack
                                from nav.paths import resolve_nav_pack_path

                                new_pack = load_nav_pack(
                                    resolve_nav_pack_path(new_pack_id)
                                )
                                if nav_controller is not None:
                                    nav_controller.reload_pack(new_pack)
                                if nav_perception is not None:
                                    nav_perception.localizer = PlaceLocalizer(new_pack.map_id)
                                    nav_perception.reload_map(new_pack.map_id)
                                else:
                                    nav_perception = NavPerception(nav_reader, PlaceLocalizer(new_pack.map_id))
                                if nav_pose_filter is not None:
                                    nav_pose_filter.reset()
                                nav_pack = new_pack
                                active_nav_pack_id = new_pack_id
                                logger.info("nav: runtime_identity %s", json.dumps(identity(new_pack.map_id), sort_keys=True))
                                if nav_metrics is not None:
                                    nav_metrics = NavMetrics(
                                        log_interval_sec=config.nav.metrics_log_interval_sec,
                                    )
                                    nav_metrics.set_pack_id(new_pack.pack_id)
                                    nav_metrics.start(now)
                                logger.info(
                                    "nav: auto pack %s v%s goals=%s (map hot-swap)",
                                    new_pack.pack_id,
                                    new_pack.version,
                                    ", ".join(g.id for g in new_pack.goals),
                                )
                        if nav_pack is not None and nav_pack.map_id == "de_" + map_changed:
                            nav_map_confirmed = True
                            nav_map_seen_at = now
                    except Exception as exc:
                        nav_map_confirmed = False
                        logger.error("map: profile reload failed (%s)", exc)
                        if nav_controller is not None:
                            nav_controller.release_keys()
                        if nav_pose_filter is not None:
                            nav_pose_filter.reset()
                        # Never feed the previous map's registered coordinates
                        # to a controller after a failed map switch.
                        if nav_perception is not None:
                            nav_perception.close()
                        nav_perception = None
                # Reconfirming the SAME map deliberately returns map_changed=None.
                # Recover the movement gate from the confirmed detector state,
                # provided the matching profile and perception really are loaded.
                if (nav_pack is not None and nav_perception is not None
                        and nav_controller is not None and nav_controller.walkable is not None
                        and active_map_confirmed(nav_pack.map_id, map_detect_state)):
                    if not nav_map_confirmed:
                        logger.info("nav: map confirmation restored map=%s", nav_pack.map_id)
                    nav_map_confirmed = True
                # Product: always log map_detect status (farm observability).
                if now - last_map_debug_log >= 5.0:
                    logger.info(
                        "map: detect=%s source=%s pending=%d/%d script=%s locked=%s",
                        detected or "none",
                        detect_source or "none",
                        map_pending,
                        config.map_detect.confirm_frames,
                        map_detect_state.confirmed_script,
                        map_detect_state.locked,
                    )
                    if nav_map_selector is not None:
                        logger.info("map: geometry=%s", nav_map_selector.status)
                    last_map_debug_log = now

            if (
                config.team_detect.enabled
                and team_probe_set is not None
                and team_detect_state is not None
            ):
                if shared_state.get("team_force_sync"):
                    forced = str(shared_state.get("team", "ct"))
                    team_detect_state.force_confirm(forced)
                    shared_state["team_force_sync"] = False
                    logger.info(
                        "team: manual sync confirmed=%s (hysteresis reset)",
                        forced.upper(),
                    )

                if (
                    activated.is_set()
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
                        ct_score = score_probes(
                            img,
                            team_probe_set.ct,
                            base_width=team_probe_set.base_width,
                            base_height=team_probe_set.base_height,
                        )
                        t_score = score_probes(
                            img,
                            team_probe_set.t,
                            base_width=team_probe_set.base_width,
                            base_height=team_probe_set.base_height,
                        )
                        logger.info(
                            "team: detect ct_score=%d t_score=%d winner=%s "
                            "pending=%d/%d confirmed=%s target_mode=%s",
                            ct_score,
                            t_score,
                            winner or "none",
                            pending,
                            config.team_detect.confirm_frames,
                            team_detect_state.confirmed_team,
                            config.aim.target_mode,
                        )
                        last_team_debug_log = now

            # Update team from shared state
            current_team_str = shared_state.get("team", "ct")
            if wingman is not None and wingman.snapshot is not None:
                current_team_str = wingman.snapshot.observation.team.lower()
                shared_state["team"] = current_team_str
                nav_map_confirmed = True
                map_transition_active = False
            target_selector.config.current_team = Team(current_team_str)
            # Keep AimConfig.target_mode as source of truth for enemy_classes
            target_selector.config.target_mode = config.aim.target_mode

            # Navigation and detection read the SAME capture in parallel. Consume
            # this future before the next frame/map reload; never queue old frames.
            nav_stage_started = time.monotonic()
            nav_job = None
            if (config.nav.enabled and nav_perception is not None
                    and nav_reader is not None and nav_pose_filter is not None
                    and activated.is_set()):
                nav_job = nav_executor.submit(nav_perception.update, img.copy(),
                    now=captured_at, allow_global=not previous_nav_combat_hold)

            # Wingman retries after teammate filtering; a vetoed full-frame
            # box must not suppress the ROI recovery pass.
            if wingman is not None:
                from detectors.wingman_detect import detect_wingman
                detections,roi_used_last,team_reason,raw_counts=detect_wingman(
                    detector,img,config.detector,wingman.snapshot.observation.team)
                if now-getattr(wingman,"last_team_log",0.)>2:
                    logger.info("wingman_detect: reason=%s raw=%s eligible=%s roi=%s",
                        team_reason,raw_counts,{k:len(v) for k,v in detections.items()},roi_used_last)
                    wingman.last_team_log=now
            else:
                detections, roi_used_last = run_combat_detection(
                    detector,img,config.detector,config.aim)
            last_detect_debug_log = log_detect_status(
                detections=detections,
                enemy_classes=config.aim.enemy_classes,
                roi_used=roi_used_last,
                activated=activated.is_set(),
                now=now,
                last_log=last_detect_debug_log,
            )

            if auto_capture is not None:
                try:
                    auto_capture.maybe_capture(
                        img,
                        detections=detections,
                        team=current_team_str,
                        activated=activated.is_set(),
                        roi_used=roi_used_last,
                        enemy_classes=config.aim.enemy_classes,
                        now=now,
                        combat_conf=config.detector.confidence_threshold,
                        class_conf=config.detector.class_confidence_thresholds,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("auto_capture: %s", exc)

            enemy_target = None
            if activated.is_set() and detections:
                if wingman is not None:
                    enemy_target = wingman_target.select(target_selector,detections,now=captured_at,
                        project=aim_mouse.project_point if aim_mouse is not None else None)
                else:
                    enemy_target = target_selector.select_best_target(
                        detections, max_distance=config.aim.max_assist_distance)
            contact_now = time.monotonic()
            contact_held = combat_contact.update(
                detected=enemy_target is not None, active=activated.is_set(), now=contact_now)
            fire_action = FireAction()
            if enemy_target is None:
                if not contact_held:
                    if wingman is not None:wingman_target.reset()
                    body_preferred_until = 0.
                    head_miss_since = None
                    last_target_key = None
                    last_target_aim = None
                    aim_pipeline.reset_trackers()
                if aim_mouse is not None:
                    aim_mouse.clear()
                if fire_controller.is_holding:
                    fire_action = fire_controller.force_release(now)

            in_combat = contact_held
            if enemy_target is not None:
                last_enemy_seen = now

            # A selected target owns aim regardless of its screen distance.
            # Switching ownership serializes with both background mouse writers.
            nav_combat_hold = contact_held
            previous_nav_combat_hold = nav_combat_hold
            camera_owner.select("combat" if nav_combat_hold else "nav")
            if nav_combat_hold and nav_controller is not None:
                nav_controller.release_keys()

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

            # Aim and fire consume this capture BEFORE waiting for navigation.
            now = time.monotonic()
            if activated.is_set() and enemy_target is not None:
                target = enemy_target
                if target.is_head and now<body_preferred_until:
                    body = target_selector.select_body_for_head(target,detections,
                        max_distance=config.aim.max_assist_distance)
                    if body is not None:target=body
                target, head_miss_since, switched_body = maybe_switch_to_body(
                    target,
                    prioritize_heads=config.aim.prioritize_heads,
                    aim_dead_zone_high=config.aim.aim_dead_zone_high,
                    body_fallback_sec=config.aim.body_fallback_sec,
                    head_miss_since=head_miss_since,
                    now=now,
                    select_body=lambda: target_selector.select_body_for_head(
                        target, detections,
                        max_distance=config.aim.max_assist_distance,
                    ),
                )
                if switched_body:
                    body_preferred_until = now+1.0
                    aim_pipeline.reset_trackers()
                    if aim_mouse is not None:
                        aim_mouse.reset_track()
                    last_target_aim = None

                # A1.2.1: hard-retarget only on class change or large aim jump.
                # The old aim_x//8 bucket reset cleared settle every few pixels
                # and caused on-target vertical thrash.
                hard_px = max(8.0, float(config.aim.aim_hard_retarget_px))
                target_key = (target.class_name,)
                jump = 0.0
                if last_target_aim is not None:
                    jump = hypot(
                        target.aim_x - last_target_aim[0],
                        target.aim_y - last_target_aim[1],
                    )
                hard_retarget = (
                    last_target_key is None
                    or target_key != last_target_key
                    or jump >= hard_px
                )
                if hard_retarget:
                    aim_pipeline.reset_trackers()
                    if aim_mouse is not None:
                        aim_mouse.reset_track()
                    last_target_key = target_key
                last_target_aim = (float(target.aim_x), float(target.aim_y))

                frame = process_aim_frame(
                    raw_x=target.aim_x,
                    raw_y=target.aim_y,
                    target_distance=target.distance,
                    now=captured_at,
                    aim_config=config.aim,
                    fov_mouse=fov_mouse,
                    pipeline=aim_pipeline,
                    fps_value=fps(),
                    reproject=aim_mouse.project_point if aim_mouse is not None else None,
                )

                if aim_mouse is not None:
                    aim_mouse.set_target(
                        frame.aim_x,
                        frame.aim_y,
                        smoothing=frame.smoothing,
                        now=captured_at,
                    )
                    dbg_dx, dbg_dy = aim_mouse.last_delta
                    if config.aim.one_shot and aim_mouse.consume_applied():
                        activated.clear()
                else:
                    dbg_dx, dbg_dy = frame.mouse_dx, frame.mouse_dy
                    if frame.should_move and (frame.mouse_dx or frame.mouse_dy):
                        camera_owner.emit("combat",frame.mouse_dx,frame.mouse_dy)

                        if config.aim.one_shot:
                            activated.clear()

                # Fire against the actual detection, not the EMA/lead ghost.
                fire_measure = observed_fire_distance
                if wingman is not None:
                    from aiming.combat_aim import precise_fire_distance
                    fire_measure = precise_fire_distance
                fire_distance = fire_measure(
                    target, center_x=fov_mouse._center_x, center_y=fov_mouse._center_y,
                    captured_at=captured_at, now=time.monotonic(),
                    project=aim_mouse.project_point if aim_mouse is not None else None)
                fire_action = fire_controller.tick(
                    pixel_distance=fire_distance,
                    confidence=target.confidence,
                    is_head=target.is_head,
                    now=time.monotonic(),
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
                if camera_owner.allowed():
                    apply_fire_action(mouse, fire_action)
                    if (fire_action.press or fire_action.click) and not combat_contact.shot_reported:
                        logger.info(
                            "aim_contact: first_fire_ms=%.0f frame_age_ms=%.0f raw_error_px=%.1f corrected_error_px=%.1f",
                            1000 * (time.monotonic() - (combat_contact.acquired_at or contact_now)),
                            1000 * (time.monotonic() - captured_at), target.distance, fire_distance)
                        combat_contact.shot_reported = True
                else:
                    apply_fire_action(mouse,fire_controller.force_release(time.monotonic()))
                if not fire_announced and (
                    fire_action.fired or fire_action.press
                ):
                    logger.info(
                        "auto_shoot: %s fire active",
                        config.aim.shoot_mode,
                    )
                    fire_announced = True

            # Combat ownership/release above takes effect before waiting for nav.
            # Drain even if deactivated mid-frame so reset cannot race perception.
            nav_wait_started = time.monotonic()
            nav_result = nav_job.result() if nav_job is not None else None
            nav_finished = time.monotonic()
            if nav_job is not None and nav_finished-last_nav_timing_log >= 5.:
                logger.info("nav_timing: capture_age_ms=%.0f parallel_stage_ms=%.0f wait_nav_ms=%.0f",
                    (nav_finished-captured_at)*1000.,
                    (nav_finished-nav_stage_started)*1000.,
                    (nav_finished-nav_wait_started)*1000.)
                last_nav_timing_log = nav_finished
            nav_pose = None
            if (
                config.nav.enabled
                and nav_reader is not None
                and nav_pose_filter is not None
                and activated.is_set()
            ):
                if nav_perception is not None:
                    perc = nav_result if nav_result is not None else nav_perception.update(
                        img, now=captured_at, allow_global=not nav_combat_hold
                    )
                    raw_pose = perc.pose
                    if raw_pose.valid and nav_map_confirmed:
                        nav_map_seen_at = now
                else:
                    raw_pose = nav_reader.read(img)
                now = time.monotonic()
                nav_pose = nav_pose_filter.update(raw_pose, now=now)

            use_nav_movement = (
                config.nav.enabled
                and nav_map_confirmed
                and not config.nav.read_only
                and nav_controller is not None
                and activated.is_set()
            )

            nav_tick_result = None

            if not activated.is_set():
                if fire_controller.is_holding:
                    fire_action = fire_controller.force_release(now)
                if patrol_runner is not None:
                    patrol_runner.pause()
                if unstuck_seq is not None:
                    unstuck_seq.abort()
                if look_controller is not None:
                    look_controller.abort(now=now)
                if nav_controller is not None:
                    nav_controller.release_keys()
                stuck_since = None
                patrol_mode = PatrolMode.PATROL
            elif use_nav_movement and nav_pose is not None:
                prev_mode = patrol_mode
                patrol_mode = next_mode_after_combat_check(
                    mode=patrol_mode,
                    in_combat=in_combat,
                    now=now,
                    last_enemy_seen=last_enemy_seen,
                    combat_clear_sec=config.patrol.combat_clear_sec,
                )
                if nav_combat_hold:
                    if look_controller is not None:
                        look_controller.abort(now=now)

                # Combat > Nav > Look: mute Look while seeking / waiting place.
                nav_blocks_look = bool(
                    nav_controller is not None and nav_controller.suppresses_look
                )
                nav_locomoting = bool(
                    nav_controller is not None and nav_controller.is_locomoting
                )
                if nav_blocks_look and look_controller is not None:
                    look_controller.abort(now=now)

                look_hold_movement = (
                    look_controller is not None
                    and config.look.pause_movement
                    and look_controller.is_sweeping
                    and not nav_blocks_look
                )
                # Pause nav only on confirmed match-ready (latched), not RGB flicker.
                nav_paused = (
                    (wingman is not None and wingman.mission is None)
                    or nav_combat_hold
                    or patrol_buy_freeze
                    or look_hold_movement
                    or map_transition_active
                )
                if nav_paused:
                    if map_transition_active and patrol_runner is not None:
                        patrol_runner.pause()
                    # Keep path state — tick paused so logs retain path=…
                    radar_progressing = False
                    nav_tick_result = nav_controller.tick(
                        nav_pose,
                        motion_hint=getattr(nav_perception,"motion_hint",None),
                        door_observation=getattr(nav_perception,"door_observation",None),
                        now=time.monotonic(),
                        paused=True,
                        team=current_team_str,
                        look_sweeping=False,
                        radar_progressing=radar_progressing,
                    )
                else:
                    look_sweeping = (
                        look_controller is not None
                        and look_controller.is_sweeping
                        and not nav_blocks_look
                    )
                    radar_progressing = False
                    nav_tick_result = nav_controller.tick(
                        nav_pose,
                        motion_hint=getattr(nav_perception,"motion_hint",None),
                        door_observation=getattr(nav_perception,"door_observation",None),
                        now=time.monotonic(),
                        paused=False,
                        team=current_team_str,
                        look_sweeping=look_sweeping,
                        radar_progressing=radar_progressing,
                    )
                    if nav_metrics is not None and nav_tick_result is not None:
                        nav_dt = (
                            1.0 / 60.0
                            if last_nav_metrics_at <= 0.0
                            else min(0.1, max(1.0 / 240.0, now - last_nav_metrics_at))
                        )
                        nav_metrics.observe_tick(
                            nav_tick_result,
                            nav_pose,
                            now=now,
                            dt=nav_dt,
                            goal_id=nav_tick_result.goal_id,
                            target_id=nav_tick_result.target_id,
                        )
                        nav_metrics.maybe_log(now, logger)
                        last_nav_metrics_at = now
                    if nav_tick_result.use_macro_patrol:
                        if patrol_runner is not None:
                            if patrol_runner.is_paused:
                                patrol_runner.resume()
                            patrol_runner.tick(now)
                    elif patrol_runner is not None:
                        patrol_runner.pause()

                if (
                    config.nav.debug
                    or config.nav.read_only
                    or now - last_nav_debug_log >= config.nav.debug_log_interval_sec
                ):
                    goal_label = (
                        nav_tick_result.goal_id
                        if nav_tick_result is not None and nav_tick_result.goal_id
                        else (nav_pack.goal.id if nav_pack is not None else "?")
                    )
                    target_label = (
                        nav_tick_result.target_id
                        if nav_tick_result is not None and nav_tick_result.target_id
                        else goal_label
                    )
                    phase_label = (
                        nav_tick_result.phase
                        if nav_tick_result is not None and nav_tick_result.phase
                        else "?"
                    )
                    state_label = (
                        nav_tick_result.state.value
                        if nav_tick_result is not None
                        else "paused"
                    )
                    pause_reason = ""
                    if nav_paused or (
                        nav_tick_result is not None
                        and nav_tick_result.state.value == "paused"
                    ):
                        if nav_combat_hold:
                            pause_reason = " combat_engage"
                        elif patrol_buy_freeze:
                            pause_reason = " buy_freeze"
                        elif map_transition_active:
                            pause_reason = " map_transition"
                        elif look_hold_movement:
                            pause_reason = " look"
                    elif nav_tick_result is None:
                        if nav_combat_hold:
                            pause_reason = " combat_engage"
                        elif patrol_buy_freeze:
                            pause_reason = " buy_freeze"
                        elif map_transition_active:
                            pause_reason = " map_transition"
                        elif look_hold_movement:
                            pause_reason = " look"
                    yaw_err = (
                        nav_tick_result.yaw_error_deg
                        if nav_tick_result is not None
                        else 0.0
                    )
                    fwd = (
                        "1"
                        if nav_tick_result is not None and nav_tick_result.forward_held
                        else "0"
                    )
                    fail_open = (
                        "1"
                        if nav_tick_result is not None and nav_tick_result.forward_fail_open
                        else "0"
                    )
                    log_pose = nav_pose
                    if (
                        nav_tick_result is not None
                        and nav_tick_result.pose_mode == "world"
                        and nav_controller is not None
                        and nav_controller.last_pose is not None
                    ):
                        log_pose = nav_controller.last_pose
                    logger.info(
                        "nav: state=%s phase=%s pose=(%.2f,%.2f) yaw=%.0f conf=%.2f "
                        "valid=%s mode=%s dist=%.3f yaw_err=%.0f fwd=%s fail_open=%s "
                        "goal=%s target=%s path=%s%s reason=%s",
                        state_label,
                        phase_label,
                        log_pose.x_norm,
                        log_pose.y_norm,
                        log_pose.yaw_deg,
                        log_pose.confidence,
                        log_pose.valid,
                        (
                            nav_tick_result.pose_mode
                            if nav_tick_result is not None and nav_tick_result.pose_mode
                            else getattr(log_pose, "radar_mode", "?")
                        ),
                        nav_tick_result.dist_to_goal if nav_tick_result else 0.0,
                        yaw_err,
                        fwd,
                        fail_open,
                        goal_label,
                        target_label,
                        (
                            nav_tick_result.path
                            if nav_tick_result is not None and nav_tick_result.path
                            else (
                                nav_controller.path_label
                                if nav_controller is not None
                                else "-"
                            )
                        ),
                        pause_reason,
                        nav_tick_result.reason if nav_tick_result else getattr(nav_perception, "reason", "read_only"),
                    )
                    last_nav_debug_log = now
            elif config.patrol.enabled and patrol_runner is not None and not nav_requested:
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
                and not nav_requested
                and now - last_move_time >= config.aim.move_interval_sec
            ):
                try:
                    import pydirectinput

                    pydirectinput.press(random.choice(["w", "a", "s", "d"]))
                    last_move_time = now
                except Exception as e:
                    logger.debug(f"auto_move failed: {e}")

            if look_controller is not None:
                nav_locomotion = (
                    use_nav_movement
                    and nav_tick_result is not None
                    and not nav_tick_result.use_macro_patrol
                    and not in_combat
                    and not patrol_buy_freeze
                )
                # Product: Look never while path-seeking / waiting place.
                nav_allows_look = not nav_requested
                if use_nav_movement and nav_controller is not None:
                    nav_allows_look = not nav_controller.suppresses_look
                look_patrol_tick = nav_locomotion or should_patrol_tick(
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
                    or not nav_allows_look
                    or (
                        not nav_locomotion
                        and (
                            not config.patrol.enabled
                            or patrol_runner is None
                            or patrol_runner.is_paused
                        )
                    )
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
                    and nav_allows_look
                    and (
                        nav_locomotion
                        or (
                            patrol_runner is not None
                            and not patrol_runner.is_paused
                        )
                    )
                )
                look_controller.tick(
                    now=now,
                    active=look_active,
                    apply_mouse=(
                        mouse.move_relative if look_active else None
                    ),
                )
                if look_active and config.look.pause_movement and look_controller.is_sweeping:
                    if patrol_runner is not None:
                        patrol_runner.release_all_keys()
                    # Do not release Nav keys while locomoting (Combat > Nav > Look).
                    if (
                        nav_controller is not None
                        and not nav_controller.is_locomoting
                    ):
                        nav_controller.release_keys()

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
        if wingman is not None:wingman.close()
        if nav_controller is not None:
            nav_controller.release_keys()
        nav_executor.shutdown(wait=True, cancel_futures=True)
        if nav_map_selector is not None:
            nav_map_selector.close()
        if nav_perception is not None and hasattr(nav_perception, "close"):
            nav_perception.close()
        if auto_capture is not None:
            try:
                auto_capture.stop()
            except Exception:
                pass
        if aim_mouse is not None:
            aim_mouse.stop()
        apply_fire_action(mouse, fire_controller.force_release(time.monotonic()))
        if unstuck_seq is not None:
            unstuck_seq.abort()
        if patrol_runner is not None:
            patrol_runner.release_all_keys()
        if nav_controller is not None:
            nav_controller.close()
        if nav_metrics is not None:
            nav_metrics.maybe_log(time.monotonic(), logger, force=True)

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
