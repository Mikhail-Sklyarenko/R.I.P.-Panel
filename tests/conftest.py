"""Pytest hooks and shared fixtures for mixed panel + csgobot imports."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CSGOBOT = _ROOT / "vendor" / "csgobot"


def _pin_project_root() -> None:
    root = str(_ROOT)
    while root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)


_pin_project_root()


def pytest_configure(config) -> None:
    _pin_project_root()


@contextmanager
def csgobot_import_path():
    """Load vendor/csgobot modules without shadowing panel `config` permanently."""
    inserted = str(_CSGOBOT)
    saved_config = sys.modules.get("config")
    saved_run = sys.modules.pop("run", None)
    if inserted in sys.path:
        sys.path.remove(inserted)
    sys.path.insert(0, inserted)
    sys.modules.pop("config", None)
    try:
        yield _CSGOBOT
    finally:
        if sys.path and sys.path[0] == inserted:
            sys.path.pop(0)
        sys.modules.pop("config", None)
        if saved_config is not None:
            sys.modules["config"] = saved_config
        if saved_run is not None:
            sys.modules["run"] = saved_run
        _pin_project_root()


@pytest.fixture
def csgobot_path():
    with csgobot_import_path():
        yield


@pytest.fixture(scope="module")
def csgobot_module_path():
    with csgobot_import_path():
        yield
