"""Запуск FSM-like UI (CustomTkinter)."""

from __future__ import annotations

import customtkinter as ctk

from modules import fake as fake_modules
from panel.controller import PanelController
from panel.ui import PanelView


def run_panel(*, test_mode: bool = False) -> None:
    if test_mode:
        fake_modules.enable()
    else:
        fake_modules.disable()

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    controller = PanelController(root, test_mode=test_mode)
    view = PanelView(root, controller)
    view.build()
    controller.start()

    def _on_close() -> None:
        view.on_close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()
