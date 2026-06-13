"""
Detection module for CS2 bot.

Supports YOLOv8 (and can be extended for YOLOv7).
"""

from .base import BaseDetector

__all__ = [
    "BaseDetector",
    "YOLOv8Detector",
    "get_detector",
]


def __getattr__(name: str):
    if name == "YOLOv8Detector":
        from .yolov8 import YOLOv8Detector

        return YOLOv8Detector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_detector(detector_type: str, **kwargs) -> BaseDetector:
    """
    Factory function to get a detector by type.

    Args:
        detector_type: "yolov8" or "yolov7"
        **kwargs: Passed to detector constructor

    Returns:
        Detector instance
    """
    from .yolov8 import YOLOv8Detector

    detectors = {
        "yolov8": YOLOv8Detector,
    }

    if detector_type not in detectors:
        raise ValueError(f"Unknown detector type: {detector_type}. Available: {list(detectors.keys())}")

    return detectors[detector_type](**kwargs)
