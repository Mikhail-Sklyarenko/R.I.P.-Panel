"""
Entry point for configuring and running the bot.
"""

import os
import sys
import logging

from config import (
    AppConfig,
    CaptureRegion,
    OBSConfig,
    FOVConfig,
    DetectorConfig,
    DetectorType,
    AimConfig,
    PatrolConfig,
    AutoBuyConfig,
    TeamDetectConfig,
    MapDetectConfig,
    Team,
    PreviewConfig,
    HotkeyConfig,
    adjust_region_to_multiple,
)


# =============
# CONFIGURATION
# =============

# Game window title (must match exactly)
WINDOW_TITLE = "Counter-Strike 2"

# Screen capture method
# Options: "mss", "obs_vc", "dxcam", "dxcam_capture", "win32"
# - "mss": Cross-platform, good performance
# - "obs_vc": OBS Virtual Camera (see docs/CSGOBOT_SETUP.md)
# - "dxcam": Windows only, GPU accelerated (fastest in theory, but mixed results)
GRABBER_TYPE = "obs_vc"

# OBS Virtual Camera settings (only for GRABBER_TYPE == "obs_vc")
OBS_DEVICE_INDEX = -1  # -1 to use device name instead
OBS_DEVICE_NAME = "OBS Virtual Camera"
# Must match OBS Settings → Video → Base resolution (and CS2 windowed size)
OBS_CANVAS_WIDTH = 1280
OBS_CANVAS_HEIGHT = 720

# YOLO model settings
YOLO_WEIGHTS = "./yolov8/cs2_yolov8m_640_augmented_v4.pt"
CONFIDENCE_THRESHOLD = 0.50  # detect; shoot uses head/body conf in fire_controller
IOU_THRESHOLD = 0.2
YOLO_IMGSZ = 640  # must match weights name; do not raise without retraining
DETECTOR_DEVICE = ""  # "" = auto, "cuda", or "cpu"
TORCH_NUM_THREADS = 0  # 0 = default; try 4-8 on CPU-only PCs

# FOV settings (CS2 defaults for 16:9)
# These are the field of view angles in degrees
FOV_HORIZONTAL = 106.26
FOV_VERTICAL = 73.74

# Mouse calibration
# x360 = mouse movement units required for 360 degree turn
# You might need to calibrate this for your sensitivity:
# 1. Set a marker in-game
# 2. Record mouse movement while doing a full 360
# 3. That number is your x360
# X360 = 16364  # Default for CS2 at sensitivity 1.0
X360 = 7792  # fallback ~sens 2.1; override via CS2_SENSITIVITY / panel Config #1

# Aim settings
CURRENT_TEAM = Team.CT  # Your starting team
PRIORITIZE_HEADS = True  # hybrid head @ conf≥HEAD_AIM_MIN_CONF; env CSGOBOT_PRIORITIZE_HEADS=0
HEAD_AIM_MIN_CONF = 0.8  # aim at head only when detect conf ≥ this
MAX_ASSIST_DISTANCE = 320  # override: CSGOBOT_MAX_DIST
MIN_BBOX_HEIGHT_FOR_HEAD = 28.0
LONG_RANGE_BODY_BIAS = True
ROI_ZOOM_ENABLED = True
ROI_FRACTION = 0.75
SMOOTHING = 2.5  # base; adaptive_smoothing scales by dist/fps
LEAD_AIM_ENABLED = True  # velocity lead for moving targets
LEAD_MS = 80.0  # override: CSGOBOT_LEAD_MS
ADAPTIVE_SMOOTHING = True  # override: CSGOBOT_ADAPTIVE_SMOOTHING=0
BODY_FALLBACK_SEC = 0.2  # override: CSGOBOT_BODY_FALLBACK_MS=200
AUTO_SHOOT = True  # LMB when crosshair on target; False = aim only
SHOOT_MODE = "hold"  # tap | burst | hold (зажим)
SHOOT_COOLDOWN_SEC = 0.05  # tap mode; env CSGOBOT_SHOOT_COOLDOWN_MS
BURST_SIZE = 7
BURST_SHOT_INTERVAL_SEC = 0.05
BURST_GAP_SEC = 0.10
HOLD_MAX_SEC = 0.8
HOLD_REPRESS_GAP_SEC = 0.05
HOLD_RELEASE_GRACE_SEC = 0.08
HEAD_SHOOT_CONFIDENCE = 0.65
BODY_SHOOT_CONFIDENCE = 0.55
PATROL_ENABLED = True
PATROL_SCRIPT = "generic_dm"  # resources/patrol/{name}.yaml — relative macro, any DM spawn
PATROL_COMBAT_CLEAR_SEC = 0.75  # resume patrol after enemy gone (seconds)
ANTI_STUCK_ENABLED = True
STUCK_SEC = 6.0  # seconds low motion while moving before unstuck
STUCK_MOTION_THRESHOLD = 2.0  # mean pixel diff on center ROI (tune on farm PC)
UNSTUCK_COOLDOWN_SEC = 3.0
AUTO_BUY_RIFLE = True
AUTO_BUY_INTERVAL_SEC = 1.0
AUTO_BUY_KEY = "f5"  # pydirectinput breaks Insert; F5 → buy_rifle_dm in fsm.cfg
AUTO_BUY_RESPAWN_DELAYS_SEC = (
    0.3, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 11.0,
)
AUTO_BUY_RESPAWN_COOLDOWN_SEC = 0.5
AUTO_BUY_PATROL_FREEZE_SEC = 12.0
AUTO_BUY_STARTUP_FREEZE_SEC = 2.0
AUTO_TEAM_DETECT = True
TEAM_DETECT_CONFIRM_FRAMES = 3
TEAM_MANUAL_OVERRIDE_SEC = 5.0
AUTO_MAP_DETECT = True
MAP_DETECT_CONFIRM_FRAMES = 3
MAP_DETECT_LOCK = True
AUTO_MOVE = False  # legacy random tap; use PATROL when enabled
MOVE_INTERVAL_SEC = 8.0
DEAD_ZONE = 12.0  # legacy; maps to AIM_DEAD_ZONE_HIGH if unset
AIM_DEAD_ZONE_HIGH = 14.0
AIM_DEAD_ZONE_LOW = 8.0
SHOOT_DEAD_ZONE = 18.0
MOUSE_MAX_DELTA = 35
MOUSE_MIN_DELTA = 2
AIM_SMOOTH_ENABLED = True
AIM_SMOOTH_ALPHA = 0.45
AIM_SMOOTH_JUMP_RESET_PX = 80.0
LEAD_VARIANCE_GATE = True
LEAD_MIN_SPEED_PX_S = 40.0
ONE_SHOT = False  # Only move once per activation

# Hotkeys
ACTIVATION_HOTKEY = 58  # CAPS LOCK
AUTO_ACTIVATE = False  # panel sets CSGOBOT_AUTO_ACTIVATE=1; manual run keeps Caps Lock
TEAM_CHANGE_HOTKEY = "ctrl+t"
EXIT_HOTKEY = "ctrl+q"

# Preview window (False = max FPS for farming; True = debug boxes on enemies)
SHOW_PREVIEW = False
PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 360


# ===========================
# DON'T TOUCH BELOW THIS LINE
# ===========================

def create_config() -> AppConfig:
    """Create application configuration from settings above."""
    from aim_tuning import (
        resolve_adaptive_smoothing,
        resolve_aim_dead_zone_high,
        resolve_aim_dead_zone_low,
        resolve_aim_smooth_alpha,
        resolve_aim_smooth_enabled,
        resolve_body_fallback_sec,
        resolve_confidence,
        resolve_dead_zone,
        resolve_head_aim_min_conf,
        resolve_lead_enabled,
        resolve_lead_min_speed,
        resolve_lead_ms,
        resolve_lead_variance_gate,
        resolve_long_range_body_bias,
        resolve_max_assist_distance,
        resolve_min_bbox_height_for_head,
        resolve_mouse_max_delta,
        resolve_mouse_min_delta,
        resolve_prioritize_heads,
        resolve_roi_enabled,
        resolve_roi_fraction,
        resolve_burst_gap_sec,
        resolve_burst_shot_interval_sec,
        resolve_burst_size,
        resolve_hold_max_sec,
        resolve_hold_repress_gap_sec,
        resolve_hold_release_grace_sec,
        resolve_shoot_cooldown_sec,
        resolve_shoot_dead_zone,
        resolve_auto_team_enabled,
        resolve_auto_map_enabled,
        resolve_patrol_script_override,
        resolve_shoot_mode,
        resolve_smoothing,
        resolve_x360,
    )

    x360 = resolve_x360(X360)
    smoothing = resolve_smoothing(SMOOTHING)
    dead_zone = resolve_dead_zone(DEAD_ZONE)
    aim_high = resolve_aim_dead_zone_high(AIM_DEAD_ZONE_HIGH, dead_zone)
    aim_low = resolve_aim_dead_zone_low(AIM_DEAD_ZONE_LOW, aim_high)
    shoot_zone = resolve_shoot_dead_zone(SHOOT_DEAD_ZONE)
    confidence = resolve_confidence(CONFIDENCE_THRESHOLD)
    prioritize_heads = resolve_prioritize_heads(PRIORITIZE_HEADS)
    max_assist_distance = resolve_max_assist_distance(MAX_ASSIST_DISTANCE)
    lead_enabled = resolve_lead_enabled(LEAD_AIM_ENABLED)
    lead_ms = resolve_lead_ms(LEAD_MS)
    adaptive_smooth = resolve_adaptive_smoothing(ADAPTIVE_SMOOTHING)
    body_fallback_sec = resolve_body_fallback_sec(BODY_FALLBACK_SEC)

    # Create sub-configs
    obs_config = OBSConfig(
        device_index=OBS_DEVICE_INDEX,
        device_name=OBS_DEVICE_NAME,
    )

    fov_config = FOVConfig(
        horizontal=FOV_HORIZONTAL,
        vertical=FOV_VERTICAL,
        x360=x360,
    )

    detector_config = DetectorConfig(
        type=DetectorType.YOLOV8,
        weights_path=YOLO_WEIGHTS,
        confidence_threshold=confidence,
        iou_threshold=IOU_THRESHOLD,
        imgsz=YOLO_IMGSZ,
        device=DETECTOR_DEVICE,
        torch_num_threads=TORCH_NUM_THREADS,
        roi_enabled=resolve_roi_enabled(ROI_ZOOM_ENABLED),
        roi_fraction=resolve_roi_fraction(ROI_FRACTION),
    )

    aim_config = AimConfig(
        current_team=CURRENT_TEAM,
        prioritize_heads=prioritize_heads,
        head_aim_min_conf=resolve_head_aim_min_conf(HEAD_AIM_MIN_CONF),
        long_range_body_bias=resolve_long_range_body_bias(LONG_RANGE_BODY_BIAS),
        min_bbox_height_for_head=resolve_min_bbox_height_for_head(
            MIN_BBOX_HEIGHT_FOR_HEAD
        ),
        max_assist_distance=max_assist_distance,
        smoothing_factor=smoothing,
        adaptive_smoothing=adaptive_smooth,
        lead_aim_enabled=lead_enabled,
        lead_ms=lead_ms,
        lead_variance_gate=resolve_lead_variance_gate(LEAD_VARIANCE_GATE),
        lead_min_speed_px_s=resolve_lead_min_speed(LEAD_MIN_SPEED_PX_S),
        body_fallback_sec=body_fallback_sec,
        aim_dead_zone_high=aim_high,
        aim_dead_zone_low=aim_low,
        shoot_dead_zone=shoot_zone,
        aim_smooth_enabled=resolve_aim_smooth_enabled(AIM_SMOOTH_ENABLED),
        aim_smooth_alpha=resolve_aim_smooth_alpha(AIM_SMOOTH_ALPHA),
        aim_smooth_jump_reset_px=AIM_SMOOTH_JUMP_RESET_PX,
        mouse_max_delta=resolve_mouse_max_delta(MOUSE_MAX_DELTA),
        mouse_min_delta=resolve_mouse_min_delta(MOUSE_MIN_DELTA),
        head_confidence=HEAD_SHOOT_CONFIDENCE,
        body_confidence=BODY_SHOOT_CONFIDENCE,
        auto_shoot=AUTO_SHOOT,
        shoot_mode=resolve_shoot_mode(SHOOT_MODE),
        shoot_cooldown_sec=resolve_shoot_cooldown_sec(SHOOT_COOLDOWN_SEC),
        burst_size=resolve_burst_size(BURST_SIZE),
        burst_shot_interval_sec=resolve_burst_shot_interval_sec(
            BURST_SHOT_INTERVAL_SEC
        ),
        burst_gap_sec=resolve_burst_gap_sec(BURST_GAP_SEC),
        hold_max_sec=resolve_hold_max_sec(HOLD_MAX_SEC),
        hold_repress_gap_sec=resolve_hold_repress_gap_sec(HOLD_REPRESS_GAP_SEC),
        hold_release_grace_sec=resolve_hold_release_grace_sec(
            HOLD_RELEASE_GRACE_SEC
        ),
        auto_move=AUTO_MOVE,
        move_interval_sec=MOVE_INTERVAL_SEC,
        dead_zone=aim_high,
        one_shot=ONE_SHOT,
    )

    preview_config = PreviewConfig(
        enabled=SHOW_PREVIEW,
        size=(PREVIEW_WIDTH, PREVIEW_HEIGHT),
    )

    auto_activate = AUTO_ACTIVATE or os.environ.get(
        "CSGOBOT_AUTO_ACTIVATE", "",
    ).lower() in ("1", "true", "yes")

    hotkey_config = HotkeyConfig(
        activation=ACTIVATION_HOTKEY,
        change_team=TEAM_CHANGE_HOTKEY,
        exit=EXIT_HOTKEY,
        auto_activate=auto_activate,
    )

    patrol_config = PatrolConfig(
        enabled=PATROL_ENABLED,
        script_name=PATROL_SCRIPT,
        combat_clear_sec=PATROL_COMBAT_CLEAR_SEC,
        anti_stuck_enabled=ANTI_STUCK_ENABLED,
        stuck_sec=STUCK_SEC,
        stuck_motion_threshold=STUCK_MOTION_THRESHOLD,
        unstuck_cooldown_sec=UNSTUCK_COOLDOWN_SEC,
    )

    patrol_override = resolve_patrol_script_override()
    map_detect_enabled = resolve_auto_map_enabled(AUTO_MAP_DETECT) and not patrol_override
    if patrol_override:
        patrol_config = PatrolConfig(
            enabled=patrol_config.enabled,
            script_name=patrol_override,
            script_path=patrol_config.script_path,
            combat_clear_sec=patrol_config.combat_clear_sec,
            pause_on_combat=patrol_config.pause_on_combat,
            anti_stuck_enabled=patrol_config.anti_stuck_enabled,
            stuck_sec=patrol_config.stuck_sec,
            stuck_motion_threshold=patrol_config.stuck_motion_threshold,
            unstuck_cooldown_sec=patrol_config.unstuck_cooldown_sec,
        )
    elif map_detect_enabled:
        patrol_config = PatrolConfig(
            enabled=patrol_config.enabled,
            script_name="generic_dm",
            script_path=patrol_config.script_path,
            combat_clear_sec=patrol_config.combat_clear_sec,
            pause_on_combat=patrol_config.pause_on_combat,
            anti_stuck_enabled=patrol_config.anti_stuck_enabled,
            stuck_sec=patrol_config.stuck_sec,
            stuck_motion_threshold=patrol_config.stuck_motion_threshold,
            unstuck_cooldown_sec=patrol_config.unstuck_cooldown_sec,
        )

    map_detect_config = MapDetectConfig(
        enabled=map_detect_enabled,
        confirm_frames=MAP_DETECT_CONFIRM_FRAMES,
        lock_after_confirm=MAP_DETECT_LOCK,
    )

    from controls.autobuy import (
        resolve_autobuy_enabled,
        resolve_autobuy_interval,
        resolve_respawn_burst_cooldown,
        resolve_respawn_burst_delays,
        resolve_respawn_patrol_freeze,
        resolve_startup_patrol_freeze,
    )

    autobuy_config = AutoBuyConfig(
        enabled=resolve_autobuy_enabled(AUTO_BUY_RIFLE),
        interval_sec=resolve_autobuy_interval(AUTO_BUY_INTERVAL_SEC),
        buy_key=AUTO_BUY_KEY,
        ct_key=AUTO_BUY_KEY,
        t_key=AUTO_BUY_KEY,
        respawn_burst_delays_sec=resolve_respawn_burst_delays(
            AUTO_BUY_RESPAWN_DELAYS_SEC,
        ),
        respawn_burst_cooldown_sec=resolve_respawn_burst_cooldown(
            AUTO_BUY_RESPAWN_COOLDOWN_SEC,
        ),
        respawn_patrol_freeze_sec=resolve_respawn_patrol_freeze(
            AUTO_BUY_PATROL_FREEZE_SEC,
        ),
        startup_patrol_freeze_sec=resolve_startup_patrol_freeze(
            AUTO_BUY_STARTUP_FREEZE_SEC,
        ),
    )

    team_detect_config = TeamDetectConfig(
        enabled=resolve_auto_team_enabled(AUTO_TEAM_DETECT),
        confirm_frames=TEAM_DETECT_CONFIRM_FRAMES,
        manual_override_sec=TEAM_MANUAL_OVERRIDE_SEC,
    )

    # Build grabber options
    grabber_options = {}
    if GRABBER_TYPE == "obs_vc":
        grabber_options = {
            "device_index": OBS_DEVICE_INDEX,
            "device_name": OBS_DEVICE_NAME,
        }

    # Create main config
    config = AppConfig(
        window_title=WINDOW_TITLE,
        grabber_type=GRABBER_TYPE,
        grabber_options=grabber_options,
        obs=obs_config,
        fov=fov_config,
        detector=detector_config,
        aim=aim_config,
        patrol=patrol_config,
        team_detect=team_detect_config,
        map_detect=map_detect_config,
        autobuy=autobuy_config,
        preview=preview_config,
        hotkeys=hotkey_config,
    )

    return config


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("CS2Bot")

    # Create configuration
    config = create_config()

    # Capture region: OBS scene coords vs desktop window coords (mss/dxcam)
    if config.grabber_type == "obs_vc":
        config.capture_region = CaptureRegion(
            left=0,
            top=0,
            width=OBS_CANVAS_WIDTH,
            height=OBS_CANVAS_HEIGHT,
        )
        logger.info(f"Capture region (OBS canvas): {config.capture_region}")
    else:
        try:
            from utils.win32 import get_window_rect
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
            config.capture_region = adjust_region_to_multiple(
                config.capture_region, 32,
            )
            logger.info(f"Capture region: {config.capture_region}")
        except Exception as e:
            logger.warning(f"Could not get window rect: {e}")
            logger.info("Using default capture region (1920x1080)")
            config.capture_region = CaptureRegion()

    # Import and run
    from main import CS2Bot

    logger.info("=" * 50)
    logger.info("CS2 Bot Starting")
    logger.info("=" * 50)
    logger.info(f"Window: {config.window_title}")
    logger.info(f"Grabber: {config.grabber_type}")
    logger.info(f"FOV: {config.fov.horizontal}° x {config.fov.vertical}°")
    x360_env = os.environ.get("CSGOBOT_X360", "").strip()
    sens_env = os.environ.get("CS2_SENSITIVITY", "").strip()
    if x360_env:
        aim_source = f"CSGOBOT_X360={x360_env}"
    elif sens_env:
        aim_source = f"CS2_SENSITIVITY={sens_env}"
    else:
        aim_source = "run.py X360 default"
    logger.info(
        f"Aim: x360={config.fov.x360} ({aim_source}) "
        f"smoothing={config.aim.smoothing_factor} "
        f"adaptive={config.aim.adaptive_smoothing} "
        f"aim_hz={config.aim.aim_dead_zone_high}/{config.aim.aim_dead_zone_low} "
        f"shoot_dz={config.aim.shoot_dead_zone} "
        f"max_dist={config.aim.max_assist_distance} "
        f"conf={config.detector.confidence_threshold} heads={config.aim.prioritize_heads}"
    )
    logger.info(
        f"Detect: conf={config.detector.confidence_threshold} "
        f"max_dist={config.aim.max_assist_distance} "
        f"heads={config.aim.prioritize_heads} "
        f"head_aim_min_conf={config.aim.head_aim_min_conf} "
        f"min_bbox_h={config.aim.min_bbox_height_for_head} "
        f"roi={config.detector.roi_enabled} frac={config.detector.roi_fraction}"
    )
    logger.info(
        f"Aim advanced: lead={config.aim.lead_aim_enabled} "
        f"lead_ms={config.aim.lead_ms} lead_gate={config.aim.lead_variance_gate} "
        f"smooth={config.aim.aim_smooth_alpha} body_fallback={config.aim.body_fallback_sec}s "
        f"mouse_cap={config.aim.mouse_max_delta}"
    )
    logger.info(
        f"Shoot: mode={config.aim.shoot_mode} burst={config.aim.burst_size} "
        f"hold_max={config.aim.hold_max_sec}s hold_gap={config.aim.hold_repress_gap_sec}s "
        f"conf head/body={config.aim.head_confidence}/{config.aim.body_confidence}"
    )
    logger.info(f"Team: {config.aim.current_team.value.upper()} (initial)")
    from team.paths import resolve_team_probes_path
    from team.probes import load_team_probes

    if config.team_detect.enabled:
        try:
            probe_path = resolve_team_probes_path(config.team_detect.probes_path)
            probe_set = load_team_probes(probe_path)
            logger.info(
                "Team detect: enabled confirm_frames=%d override_sec=%.0fs "
                "probes=ct:%d t:%d path=%s",
                config.team_detect.confirm_frames,
                config.team_detect.manual_override_sec,
                len(probe_set.ct),
                len(probe_set.t),
                probe_path.name,
            )
        except Exception as exc:
            logger.warning("Team detect: failed to load probes (%s); disabled", exc)
            config.team_detect.enabled = False
    else:
        logger.info("Team detect: disabled (CSGOBOT_AUTO_TEAM=0 or run.py)")
    from map.paths import resolve_map_regions_path, resolve_map_templates_dir
    from map.regions import load_map_regions
    from map.template_match import load_map_templates

    if config.map_detect.enabled:
        try:
            regions_path = resolve_map_regions_path(config.map_detect.regions_path)
            templates_dir = resolve_map_templates_dir(config.map_detect.templates_path)
            load_map_regions(regions_path)
            templates = load_map_templates(templates_dir)
            logger.info(
                "Map detect: enabled confirm_frames=%d lock=%s templates=%d path=%s",
                config.map_detect.confirm_frames,
                config.map_detect.lock_after_confirm,
                len(templates),
                templates_dir.name,
            )
        except Exception as exc:
            logger.warning("Map detect: failed to load resources (%s); disabled", exc)
            config.map_detect.enabled = False
    else:
        logger.info("Map detect: disabled (CSGOBOT_AUTO_MAP=0 or CSGOBOT_PATROL_SCRIPT)")
    logger.info(
        f"Autobuy: enabled={config.autobuy.enabled} "
        f"interval={config.autobuy.interval_sec}s "
        f"key={config.autobuy.buy_key} burst={config.autobuy.burst_count}"
    )
    try:
        import torch
        if torch.cuda.is_available():
            logger.info(f"PyTorch: cuda ({torch.cuda.get_device_name(0)})")
        else:
            logger.info(
                "PyTorch: cpu — for 30+ FPS install CUDA torch "
                "(see docs/CSGOBOT_SETUP.md)"
            )
    except ImportError:
        pass
    logger.info(f"Preview: {'on' if config.preview.enabled else 'off'}")
    logger.info("=" * 50)
    if config.hotkeys.auto_activate:
        logger.info("Activation: auto (panel / CSGOBOT_AUTO_ACTIVATE)")
    else:
        logger.info("Activation: CAPS LOCK")
    logger.info(f"Change Team: Ctrl+T")
    logger.info(f"Exit: Ctrl+Q")
    logger.info("=" * 50)

    bot = CS2Bot(config)
    return bot.run()


if __name__ == "__main__":
    sys.exit(main())
