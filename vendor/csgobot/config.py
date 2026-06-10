from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, Tuple, List


class Team(Enum):
    CT = "ct"
    T = "t"


class DetectorType(Enum):
    YOLOV8 = "yolov8"
    YOLOV7 = "yolov7"


@dataclass
class CaptureRegion:
    """Screen capture region configuration."""
    left: int = 0
    top: int = 0
    width: int = 1920
    height: int = 1080

    def to_dict(self) -> Dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.left, self.top, self.width, self.height)

    @property
    def center(self) -> Tuple[float, float]:
        return (self.width / 2, self.height / 2)


@dataclass
class OBSConfig:
    """OBS Virtual Camera grabber configuration."""
    device_index: int = -1
    device_name: str = "OBS Virtual Camera"


@dataclass
class FOVConfig:
    """Field of View and mouse sensitivity configuration."""
    horizontal: float = 106.26
    vertical: float = 73.74
    x360: int = 16364
    sensitivity: float = 1.0

    def __post_init__(self):
        if not (0.1 < self.horizontal < 179.9):
            raise ValueError(f"horizontal FOV must be between 0.1 and 179.9, got {self.horizontal}")
        if not (0.1 < self.vertical < 179.9):
            raise ValueError(f"vertical FOV must be between 0.1 and 179.9, got {self.vertical}")
        if self.x360 <= 0:
            raise ValueError(f"x360 must be positive, got {self.x360}")

    @property
    def pixels_per_degree(self) -> float:
        return self.x360 / 360.0


@dataclass
class DetectorConfig:
    """Object detection configuration."""
    type: DetectorType = DetectorType.YOLOV8
    weights_path: str = "./yolov8/best.pt"
    confidence_threshold: float = 0.7
    iou_threshold: float = 0.2
    imgsz: int = 640
    device: str = ""  # "" = auto (cuda if available else cpu)
    half_precision: Optional[bool] = None
    max_det: int = 20
    torch_num_threads: int = 0  # 0 = PyTorch default

    # Class names in order of class index
    class_names: List[str] = field(default_factory=lambda: ["c", "ch", "t", "th"])

    # Colors for visualization (BGR format)
    class_colors: List[Tuple[int, int, int]] = field(default_factory=lambda: [
        (245, 185, 115),  # c  - CT body (light blue)
        (255, 50, 0),     # ch - CT head (red-ish)
        (0, 208, 247),    # t  - T body (yellow-ish)
        (0, 82, 247),     # th - T head (orange)
    ])


@dataclass
class RecoilConfig:
    """Recoil compensation configuration."""
    enabled: bool = False
    multiplier: float = 1.0  # Compensation strength (adjust for sensitivity)
    patterns_dir: str = "./patterns"


@dataclass
class AimConfig:
    """Aiming behavior configuration."""
    # Team settings
    current_team: Team = Team.CT

    # Target priority
    prioritize_heads: bool = True

    # Distance thresholds (in pixels from screen center)
    max_assist_distance: int = 300  # Max distance to engage target
    min_shoot_distance: int = 50    # Min distance for auto-shoot

    # Confidence thresholds for auto-shoot
    head_confidence: float = 0.8
    body_confidence: float = 0.7

    # Smoothing (1.0 = instant, higher = slower)
    smoothing_factor: float = 1.0

    dead_zone: float = 5.0
    one_shot: bool = False

    # Auto-shoot settings
    auto_shoot: bool = False
    shoot_cooldown_sec: float = 0.1  # min seconds between LMB clicks (0.08–0.15)

    # WASD movement while bot is active (csgobot has no pathfinding)
    auto_move: bool = False
    move_interval_sec: float = 8.0

    # Recoil compensation
    recoil: RecoilConfig = field(default_factory=RecoilConfig)

    @property
    def enemy_classes(self) -> Tuple[str, str]:
        """Return enemy class names based on current team."""
        if self.current_team == Team.CT:
            return ("t", "th")
        return ("c", "ch")

    @property
    def enemy_team(self) -> Team:
        return Team.T if self.current_team == Team.CT else Team.CT


@dataclass
class PreviewConfig:
    """CV2 preview window configuration."""
    enabled: bool = True
    title: str = "CS2 AI Vision"
    size: Tuple[int, int] = (1280, 720)
    show_fps: bool = True
    show_team: bool = True
    paint_boxes: bool = True
    convert_rgb_to_bgr: bool = True


@dataclass
class PatrolConfig:
    """Relative WASD patrol (DM-safe: no map coordinates)."""
    enabled: bool = True
    script_name: str = "generic_dm"
    script_path: str = ""
    combat_clear_sec: float = 0.75
    pause_on_combat: bool = True
    anti_stuck_enabled: bool = True
    stuck_sec: float = 6.0
    stuck_motion_threshold: float = 2.0
    unstuck_cooldown_sec: float = 3.0


@dataclass
class HotkeyConfig:
    """Hotkey configuration."""
    activation: int = 58  # CAPS LOCK
    change_team: str = "ctrl+t"
    exit: str = "ctrl+q"


@dataclass
class AppConfig:
    """Main application configuration."""
    window_title: str = "Counter-Strike 2"

    # Grabber settings
    grabber_type: str = "obs_vc"  # or "mss", "dxcam", etc.
    grabber_options: Dict[str, Any] = field(default_factory=dict)

    # Sub-configurations
    capture_region: CaptureRegion = field(default_factory=CaptureRegion)
    border_offsets: Tuple[int, int, int, int] = (8, 30, 16, 39)  # CS2 window borders

    obs: Optional[OBSConfig] = field(default_factory=OBSConfig)
    fov: FOVConfig = field(default_factory=FOVConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    aim: AimConfig = field(default_factory=AimConfig)
    patrol: PatrolConfig = field(default_factory=PatrolConfig)
    preview: PreviewConfig = field(default_factory=PreviewConfig)
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)

    # Performance
    exit_on_error: bool = True


def round_to_multiple(number: int, multiple: int) -> int:
    """Round a number to the nearest multiple."""
    return multiple * round(number / multiple)


def adjust_region_to_multiple(region: CaptureRegion, multiple: int = 32) -> CaptureRegion:
    """Adjust capture region dimensions to be multiples of a value (for YOLO)."""
    return CaptureRegion(
        left=region.left,
        top=region.top,
        width=round_to_multiple(region.width, multiple),
        height=round_to_multiple(region.height, multiple),
    )


def create_default_config() -> AppConfig:
    """Create a default configuration for CS2."""
    config = AppConfig()

    # Set up OBS grabber options
    config.grabber_options = {
        "device_index": config.obs.device_index,
        "device_name": config.obs.device_name,
    }

    return config
