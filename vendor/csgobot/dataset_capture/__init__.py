"""Runtime auto-capture for product CT dataset (farm collector PCs)."""

from .config import AutoCaptureConfig, resolve_auto_capture_config
from .controller import AutoCaptureController

__all__ = [
    "AutoCaptureConfig",
    "AutoCaptureController",
    "resolve_auto_capture_config",
]
