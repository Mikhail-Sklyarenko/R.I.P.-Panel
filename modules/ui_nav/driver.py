"""Абстракция захвата/кликов: Win32Driver и SimDriver."""

from __future__ import annotations

import os
import sys
import time
from abc import ABC, abstractmethod

from PIL import Image, ImageDraw

from modules.ui_nav.artifacts import ArtifactStore
from modules.ui_nav.coords import NavCoords, Point
from modules.ui_nav.errors import UiNavError


class NavDriver(ABC):
    @abstractmethod
    def capture(self) -> Image.Image: ...

    @abstractmethod
    def click(self, point: Point) -> None: ...

    @abstractmethod
    def press(self, key: str) -> None: ...

    @property
    @abstractmethod
    def sim(self) -> bool: ...


class Win32Driver(NavDriver):
    def __init__(self, hwnd: int) -> None:
        self.hwnd = hwnd
        self._sim = False

    @property
    def sim(self) -> bool:
        return False

    def capture(self) -> Image.Image:
        from modules.ui_nav.capture import capture_client

        return capture_client(self.hwnd)

    def click(self, point: Point) -> None:
        from modules.ui_nav.actions import click_client

        click_client(self.hwnd, point)

    def press(self, key: str) -> None:
        from modules.ui_nav.actions import press_key

        press_key(self.hwnd, key)


class SimDriver(NavDriver):
    """Симуляция без CS2: фаза задаётся navigator (для детекторов)."""

    def __init__(self, coords: NavCoords, artifacts: ArtifactStore) -> None:
        self.coords = coords
        self.artifacts = artifacts
        self._sim = True
        self._phase = "main_menu"

    @property
    def sim(self) -> bool:
        return True

    def set_phase(self, phase: str) -> None:
        self._phase = phase

    def _fake_image(self, label: str) -> Image.Image:
        w = int(self.coords.base_width * self.coords.scale_x)
        h = int(self.coords.base_height * self.coords.scale_y)
        img = Image.new("RGB", (max(w, 360), max(h, 270)), (20, 22, 28))
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), f"SIM:{label}", fill=(220, 200, 80))
        for probe in self.coords.probes(label):
            draw.rectangle(
                (probe.x - 2, probe.y - 2, probe.x + 2, probe.y + 2),
                fill=probe.rgb,
            )
        return img

    def capture(self) -> Image.Image:
        img = self._fake_image(self._phase)
        self.artifacts.save_image(f"sim_capture_{self._phase}", img)
        return img

    def click(self, point: Point) -> None:
        self.artifacts.log_step(
            "sim_click", x=point.x, y=point.y, phase=self._phase
        )
        time.sleep(0.05)

    def press(self, key: str) -> None:
        self.artifacts.log_step("sim_key", key=key)
        time.sleep(0.05)


def use_sim_driver() -> bool:
    return os.environ.get("DM_NAV_SIM", "").lower() in ("1", "true", "yes")


def create_driver(
    coords: NavCoords,
    artifacts: ArtifactStore,
    *,
    hwnd: int | None = None,
) -> NavDriver:
    if use_sim_driver():
        return SimDriver(coords, artifacts)
    if sys.platform != "win32":
        raise UiNavError("real dm_nav requires Windows or DM_NAV_SIM=1")
    if hwnd is None:
        from modules.ui_nav.window import find_cs2_hwnd

        hwnd = find_cs2_hwnd()
    return Win32Driver(hwnd)
