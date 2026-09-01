"""Visual radar overlay editor widget (PR-N9)."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Any

import customtkinter as ctk
from PIL import ImageTk

from modules.nav_pack.radar_overlay import (
    build_overlay_state,
    pixel_to_norm,
    render_overlay_image,
)


class NavRadarEditor(ctk.CTkFrame):
    """Clickable radar map for tuning nav pack goal coordinates."""

    def __init__(
        self,
        master: Any,
        *,
        display_size: int = 300,
        on_coords_changed: Callable[[str, float, float], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self._display_size = display_size
        self._on_coords_changed = on_coords_changed
        self._pack_id = ""
        self._photo: ImageTk.PhotoImage | None = None

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=4, pady=(4, 2))
        ctk.CTkLabel(controls, text="Click target:").pack(side="left", padx=(0, 6))
        self._target_var = ctk.StringVar(value="goal1")
        ctk.CTkRadioButton(
            controls,
            text="Goal 1",
            variable=self._target_var,
            value="goal1",
        ).pack(side="left", padx=4)
        ctk.CTkRadioButton(
            controls,
            text="Goal 2",
            variable=self._target_var,
            value="goal2",
        ).pack(side="left", padx=4)

        self._canvas = tk.Canvas(
            self,
            width=display_size,
            height=display_size,
            highlightthickness=1,
            highlightbackground="#334155",
            bg="#1e293b",
        )
        self._canvas.pack(padx=4, pady=4)
        self._canvas.bind("<Button-1>", self._on_click)

        self._hint = ctk.CTkLabel(
            self,
            text="Green=goal1  Orange=goal2  Blue=entries  Gray=landmarks",
            font=ctk.CTkFont(size=11),
            text_color="gray60",
        )
        self._hint.pack(anchor="w", padx=6, pady=(0, 4))

    def set_pack(
        self,
        pack_id: str,
        *,
        goal_x: float,
        goal_y: float,
        goal2_x: float,
        goal2_y: float,
    ) -> None:
        self._pack_id = pack_id.strip()
        self.refresh(goal_x=goal_x, goal_y=goal_y, goal2_x=goal2_x, goal2_y=goal2_y)

    def refresh(
        self,
        *,
        goal_x: float,
        goal_y: float,
        goal2_x: float,
        goal2_y: float,
    ) -> None:
        if not self._pack_id:
            return
        try:
            state = build_overlay_state(
                self._pack_id,
                goal_x=goal_x,
                goal_y=goal_y,
                goal2_x=goal2_x,
                goal2_y=goal2_y,
            )
            img = render_overlay_image(state, display_size=self._display_size)
        except Exception as exc:
            self._canvas.delete("all")
            self._canvas.create_text(
                self._display_size // 2,
                self._display_size // 2,
                text=str(exc)[:80],
                fill="#f87171",
                width=self._display_size - 20,
            )
            return

        self._photo = ImageTk.PhotoImage(img)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._photo)

    def _on_click(self, event: tk.Event) -> None:
        if not self._pack_id or self._on_coords_changed is None:
            return
        x, y = pixel_to_norm(
            int(event.x),
            int(event.y),
            self._display_size,
            self._display_size,
        )
        target = self._target_var.get()
        self._on_coords_changed(target, x, y)
