"""
Entry point for configuring and running the bot.
"""

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
CONFIDENCE_THRESHOLD = 0.7
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
X360 = 7792  # Default for CS2 at sensitivity 1.0

# Aim settings
CURRENT_TEAM = Team.CT  # Your starting team
PRIORITIZE_HEADS = True  # Prefer headshots
MAX_ASSIST_DISTANCE = 300  # Max pixel distance to engage
SMOOTHING = 3.0  # higher = smoother aim; raise if mouse overshoots at high FPS
AUTO_SHOOT = True  # LMB when crosshair on target; False = aim only
SHOOT_COOLDOWN_SEC = 0.1  # 80–150 ms between shots
PATROL_ENABLED = True
PATROL_SCRIPT = "generic_dm"  # resources/patrol/{name}.yaml — relative macro, any DM spawn
PATROL_COMBAT_CLEAR_SEC = 0.75  # resume patrol after enemy gone (seconds)
AUTO_MOVE = False  # legacy random tap; use PATROL when enabled
MOVE_INTERVAL_SEC = 8.0
DEAD_ZONE = 12.0  # stop micro-corrections near crosshair (reduces circular jitter)
ONE_SHOT = False  # Only move once per activation

# Hotkeys
ACTIVATION_HOTKEY = 58  # CAPS LOCK
TEAM_CHANGE_HOTKEY = "ctrl+t"
EXIT_HOTKEY = "ctrl+q"

# Preview window (False = max FPS for farming; True = debug boxes on enemies)
SHOW_PREVIEW = True
PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 360


# ===========================
# DON'T TOUCH BELOW THIS LINE
# ===========================

def create_config() -> AppConfig:
    """Create application configuration from settings above."""

    # Create sub-configs
    obs_config = OBSConfig(
        device_index=OBS_DEVICE_INDEX,
        device_name=OBS_DEVICE_NAME,
    )

    fov_config = FOVConfig(
        horizontal=FOV_HORIZONTAL,
        vertical=FOV_VERTICAL,
        x360=X360,
    )

    detector_config = DetectorConfig(
        type=DetectorType.YOLOV8,
        weights_path=YOLO_WEIGHTS,
        confidence_threshold=CONFIDENCE_THRESHOLD,
        iou_threshold=IOU_THRESHOLD,
        imgsz=YOLO_IMGSZ,
        device=DETECTOR_DEVICE,
        torch_num_threads=TORCH_NUM_THREADS,
    )

    aim_config = AimConfig(
        current_team=CURRENT_TEAM,
        prioritize_heads=PRIORITIZE_HEADS,
        max_assist_distance=MAX_ASSIST_DISTANCE,
        smoothing_factor=SMOOTHING,
        auto_shoot=AUTO_SHOOT,
        shoot_cooldown_sec=SHOOT_COOLDOWN_SEC,
        auto_move=AUTO_MOVE,
        move_interval_sec=MOVE_INTERVAL_SEC,
        dead_zone=DEAD_ZONE,
        one_shot=ONE_SHOT,
    )

    preview_config = PreviewConfig(
        enabled=SHOW_PREVIEW,
        size=(PREVIEW_WIDTH, PREVIEW_HEIGHT),
    )

    hotkey_config = HotkeyConfig(
        activation=ACTIVATION_HOTKEY,
        change_team=TEAM_CHANGE_HOTKEY,
        exit=EXIT_HOTKEY,
    )

    patrol_config = PatrolConfig(
        enabled=PATROL_ENABLED,
        script_name=PATROL_SCRIPT,
        combat_clear_sec=PATROL_COMBAT_CLEAR_SEC,
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
    logger.info(f"x360: {config.fov.x360}")
    logger.info(f"Team: {config.aim.current_team.value.upper()}")
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
    logger.info(f"Activation: CAPS LOCK")
    logger.info(f"Change Team: Ctrl+T")
    logger.info(f"Exit: Ctrl+Q")
    logger.info("=" * 50)

    bot = CS2Bot(config)
    return bot.run()


if __name__ == "__main__":
    sys.exit(main())
