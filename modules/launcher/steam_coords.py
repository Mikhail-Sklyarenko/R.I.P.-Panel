"""Калибровка кликов Steam login UI (705×440 primary, 1920×1080 fallback)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from config.paths import get_app_root
from modules.ui_nav.coords import Point
from modules.ui_nav.errors import UiNavError

_log = logging.getLogger(__name__)

_PROFILE_705 = "705x440"
_PROFILE_1920 = "1920x1080"
_REF_W_705 = 705
_REF_H_705 = 440
_TOL_W_705 = 60
_TOL_H_705 = 40


def _path_705() -> Path:
    return get_app_root() / "resources" / "ui_nav" / "steam_login_705x440.yaml"


def _path_1920() -> Path:
    return get_app_root() / "resources" / "ui_nav" / "steam_login_1920x1080.yaml"


def resolve_steam_coords_profile(client_width: int, client_height: int) -> str:
    """Выбор yaml-профиля по client area окна входа Steam."""
    if (
        abs(client_width - _REF_W_705) <= _TOL_W_705
        and abs(client_height - _REF_H_705) <= _TOL_H_705
    ):
        return _PROFILE_705
    return _PROFILE_1920


def _profile_path(profile: str) -> Path:
    if profile == _PROFILE_705:
        return _path_705()
    return _path_1920()


@dataclass
class SteamLoginCoords:
    base_width: int
    base_height: int
    clicks: dict[str, Point]
    profile: str = _PROFILE_1920
    client_width: int = 0
    client_height: int = 0
    scale_x: float = 1.0
    scale_y: float = 1.0

    def click(self, name: str) -> Point:
        if name not in self.clicks:
            raise UiNavError(f"steam login coord missing: {name}")
        p = self.clicks[name]
        return Point(int(p.x * self.scale_x), int(p.y * self.scale_y))


def _load_yaml(src: Path) -> SteamLoginCoords:
    if not src.is_file():
        raise UiNavError(f"steam login coords file missing: {src}")
    data = yaml.safe_load(src.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    base_w = int(meta.get("base_width", 1920))
    base_h = int(meta.get("base_height", 1080))
    clicks: dict[str, Point] = {}
    for name, pt in data.get("clicks", {}).items():
        clicks[name] = Point(int(pt["x"]), int(pt["y"]))
    profile = f"{base_w}x{base_h}" if base_w != _REF_W_705 else _PROFILE_705
    return SteamLoginCoords(
        base_width=base_w,
        base_height=base_h,
        clicks=clicks,
        profile=profile,
    )


def load_steam_login_coords(
    client_width: int,
    client_height: int,
    path: Path | None = None,
) -> SteamLoginCoords:
    """
    705×440 (±tolerance) → steam_login_705x440.yaml, scale 1:1.
    Иначе → steam_login_1920x1080.yaml с пропорциональным scale.
    """
    if path is not None:
        coords = _load_yaml(path)
        coords.client_width = client_width
        coords.client_height = client_height
        if coords.base_width and coords.base_height:
            coords.scale_x = client_width / coords.base_width
            coords.scale_y = client_height / coords.base_height
        return coords

    profile = resolve_steam_coords_profile(client_width, client_height)
    src = _profile_path(profile)
    coords = _load_yaml(src)
    coords.profile = profile
    coords.client_width = client_width
    coords.client_height = client_height

    if profile == _PROFILE_705:
        coords.scale_x = 1.0
        coords.scale_y = 1.0
    else:
        coords.scale_x = client_width / coords.base_width if coords.base_width else 1.0
        coords.scale_y = client_height / coords.base_height if coords.base_height else 1.0

    _log.info(
        "steam coords profile: %s client=%sx%s",
        profile,
        client_width,
        client_height,
    )
    return coords
