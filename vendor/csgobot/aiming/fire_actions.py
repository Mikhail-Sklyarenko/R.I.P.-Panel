"""Apply fire actions to mouse backends."""

from __future__ import annotations

from aiming.fire_controller import FireAction
from controls.mouse.base import BaseMouseControls


def apply_fire_action(mouse: BaseMouseControls, action: FireAction) -> None:
    if not (action.click or action.press or action.release):
        return
    try:
        if action.release:
            mouse.release("left")
        if action.press:
            mouse.press("left")
        if action.click:
            mouse.click("left")
    except Exception:
        import pydirectinput

        if action.release:
            pydirectinput.mouseUp(button="left")
        if action.press:
            pydirectinput.mouseDown(button="left")
        if action.click:
            pydirectinput.click(button="left")
