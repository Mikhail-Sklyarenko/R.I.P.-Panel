"""CARE_PACKAGE screen detector (color probes)."""

from __future__ import annotations

import os
import time

from PIL import Image

from modules.drop_picker.errors import CarePackageNotFoundError
from modules.drop_picker.slots import DropLayout, load_drop_layout
from modules.ui_nav.artifacts import ArtifactStore


def _probe_match(img: Image.Image, x: int, y: int, rgb: tuple[int, int, int], tol: int) -> bool:
    if x >= img.width or y >= img.height:
        return False
    r, g, b = img.getpixel((x, y))[:3]
    tr, tg, tb = rgb
    return abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol


def is_care_package_screen(image: Image.Image, layout: DropLayout) -> bool:
    if not layout.care_package_probes:
        return True
    matched = sum(
        1
        for x, y, rgb, tol in layout.care_package_probes
        if _probe_match(image, x, y, rgb, tol)
    )
    return matched >= max(1, len(layout.care_package_probes) - 1)


def _sim_care_package_image(layout: DropLayout) -> Image.Image:
    from PIL import ImageDraw

    w = int(layout.base_width * layout.scale_x)
    h = int(layout.base_height * layout.scale_y)
    img = Image.new("RGB", (max(w, 360), max(h, 270)), (35, 40, 48))
    draw = ImageDraw.Draw(img)
    for x, y, rgb, _tol in layout.care_package_probes:
        draw.rectangle((x - 2, y - 2, x + 2, y + 2), fill=rgb)
    return img


def capture_frame(ctx: dict, layout: DropLayout, artifacts: ArtifactStore) -> Image.Image:
    if os.environ.get("DROP_PICKER_SIM", "").lower() in ("1", "true", "yes"):
        img = _sim_care_package_image(layout)
        artifacts.save_image("drop_care_package_sim", img)
        return img

    import sys

    if sys.platform != "win32":
        return _sim_care_package_image(layout)

    from modules.ui_nav.capture import capture_client
    from modules.ui_nav.window import find_cs2_hwnd

    hwnd = ctx.get("hwnd")
    if hwnd is None:
        hwnd = find_cs2_hwnd()
        ctx["hwnd"] = hwnd
    img = capture_client(hwnd)
    artifacts.save_image("drop_care_package", img)
    return img


def wait_for_care_package(
    ctx: dict,
    *,
    layout: DropLayout | None = None,
    artifacts: ArtifactStore,
    timeout_sec: float = 30.0,
) -> Image.Image:
    layout = layout or load_drop_layout(
        getattr(ctx.get("config"), "cs_resolution", "360x270")
        if ctx.get("config")
        else "360x270"
    )
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        frame = capture_frame(ctx, layout, artifacts)
        if is_care_package_screen(frame, layout):
            artifacts.log_step("care_package_detected")
            return frame
        time.sleep(0.4)
    raise CarePackageNotFoundError("care package screen not detected")
