"""CS2 UI helpers, loaded independently from the panel lifecycle."""
from importlib import import_module

_EXPORTS = {
    "ArtifactStore": "artifacts",
    "NavCoords": "coords", "load_nav_coords": "coords",
    "InDmWaitResult": "detectors", "ScreenState": "detectors",
    "detect_state": "detectors", "wait_for_in_dm": "detectors",
    "wait_for_state": "detectors", "NavDriver": "driver", "create_driver": "driver",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module(f"{__name__}.{_EXPORTS[name]}"), name)
    globals()[name] = value
    return value
