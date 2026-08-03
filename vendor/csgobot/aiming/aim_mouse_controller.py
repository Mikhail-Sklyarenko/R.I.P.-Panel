"""High-rate aim mouse (PR-A1 / Aim L1.3-style).

Detection (YOLO) updates the tracked aim point; a dedicated mouse thread applies
FOV deltas at ``mouse_hz`` so motion is not bound to detection FPS.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Callable

from aiming.dead_zone import AimHysteresis, AimHysteresisConfig
from aiming.mouse_filter import filter_mouse_delta

if TYPE_CHECKING:
    from aiming.fov_mouse import FOVMouseMovement
    from config import AimConfig

logger = logging.getLogger("CS2Bot.aim")

ApplyMouseFn = Callable[[int, int], None]

# Cap coast velocity so a bad detection jump cannot fling the mouse.
_MAX_COAST_SPEED_PX_S = 2500.0


class AimMouseController:
    """
    Track screen-space aim point + apply mouse at high rate.

    L1.3 pattern (shared with Look): detection thread owns *what* to track;
    mouse thread owns *how* the cursor moves (capped steps @ ``mouse_hz``).
    """

    def __init__(
        self,
        *,
        config: AimConfig,
        fov_mouse: FOVMouseMovement,
    ) -> None:
        self._config = config
        self._fov_mouse = fov_mouse
        self._hysteresis = AimHysteresis(
            AimHysteresisConfig(
                high=config.aim_dead_zone_high,
                low=config.aim_dead_zone_low,
            )
        )
        self._lock = threading.Lock()
        self._apply_mouse: ApplyMouseFn | None = None
        self._thread: threading.Thread | None = None
        self._thread_stop = threading.Event()

        self._active = False
        self._target_x = 0.0
        self._target_y = 0.0
        self._target_t = 0.0
        self._smoothing = 1.0
        self._vx = 0.0
        self._vy = 0.0
        self._has_sample = False

        self._last_dx = 0
        self._last_dy = 0
        self._last_pixel_distance = 0.0
        self._applied_since_arm = False

    @property
    def enabled(self) -> bool:
        return float(self._config.mouse_hz) > 0

    @property
    def is_tracking(self) -> bool:
        with self._lock:
            return self._active

    @property
    def last_delta(self) -> tuple[int, int]:
        with self._lock:
            return self._last_dx, self._last_dy

    @property
    def last_pixel_distance(self) -> float:
        with self._lock:
            return self._last_pixel_distance

    def consume_applied(self) -> bool:
        """True once if the mouse thread applied a non-zero move since arm."""
        with self._lock:
            if not self._applied_since_arm:
                return False
            self._applied_since_arm = False
            return True

    def start(self, apply_mouse: ApplyMouseFn) -> None:
        self._apply_mouse = apply_mouse
        if not self.enabled:
            return
        self._stop_thread()
        self._thread_stop = threading.Event()
        t = threading.Thread(
            target=self._mouse_loop,
            name="csgobot-aim-mouse",
            daemon=True,
        )
        self._thread = t
        t.start()
        logger.info(
            "aim: mouse thread hz=%.0f step_max=%d coast=%s",
            float(self._config.mouse_hz),
            self._step_max_delta(),
            bool(self._config.mouse_coast),
        )

    def stop(self) -> None:
        self.clear()
        self._stop_thread()
        self._apply_mouse = None

    def set_target(
        self,
        aim_x: float,
        aim_y: float,
        *,
        smoothing: float,
        now: float,
    ) -> None:
        with self._lock:
            if self._has_sample:
                dt = now - self._target_t
                if 0.001 < dt < 0.5:
                    vx = (aim_x - self._target_x) / dt
                    vy = (aim_y - self._target_y) / dt
                    speed = (vx * vx + vy * vy) ** 0.5
                    if speed > _MAX_COAST_SPEED_PX_S:
                        scale = _MAX_COAST_SPEED_PX_S / speed
                        vx *= scale
                        vy *= scale
                    self._vx = vx
                    self._vy = vy
                else:
                    self._vx = 0.0
                    self._vy = 0.0
            else:
                self._vx = 0.0
                self._vy = 0.0

            self._target_x = float(aim_x)
            self._target_y = float(aim_y)
            self._target_t = float(now)
            self._smoothing = max(1.0, float(smoothing))
            self._active = True
            self._has_sample = True

    def clear(self) -> None:
        with self._lock:
            self._active = False
            self._has_sample = False
            self._vx = 0.0
            self._vy = 0.0
            self._last_dx = 0
            self._last_dy = 0
            self._applied_since_arm = False
            self._hysteresis.reset()

    def reset_track(self) -> None:
        """Target switch / body fallback — drop coast velocity, keep thread."""
        with self._lock:
            self._has_sample = False
            self._vx = 0.0
            self._vy = 0.0
            self._applied_since_arm = False
            self._hysteresis.reset()

    def _step_max_delta(self) -> int:
        step = int(self._config.mouse_step_max_delta)
        if step > 0:
            return step
        return max(1, int(self._config.mouse_max_delta))

    def _stop_thread(self) -> None:
        self._thread_stop.set()
        t = self._thread
        self._thread = None
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=0.75)

    def _mouse_loop(self) -> None:
        hz = max(30.0, float(self._config.mouse_hz))
        period = 1.0 / hz
        coast = bool(self._config.mouse_coast)
        coast_max = max(0.0, float(self._config.mouse_coast_max_sec))
        min_delta = max(0, int(self._config.mouse_min_delta))
        step_max = self._step_max_delta()

        while not self._thread_stop.wait(period):
            apply_fn: ApplyMouseFn | None = None
            tx = ty = 0.0
            smoothing = 1.0
            with self._lock:
                if not self._active or self._apply_mouse is None:
                    continue
                now = time.monotonic()
                age = now - self._target_t
                if coast and coast_max > 0 and 0.0 <= age <= coast_max:
                    tx = self._target_x + self._vx * age
                    ty = self._target_y + self._vy * age
                else:
                    tx = self._target_x
                    ty = self._target_y
                smoothing = self._smoothing
                apply_fn = self._apply_mouse

            aim_result = self._fov_mouse.get_move(tx, ty, smoothing=smoothing)
            dx, dy = filter_mouse_delta(
                aim_result.mouse_x,
                aim_result.mouse_y,
                max_delta=step_max,
                min_delta=min_delta,
            )

            with self._lock:
                if not self._active:
                    continue
                should_move = self._hysteresis.should_move(aim_result.pixel_distance)
                self._last_pixel_distance = aim_result.pixel_distance
                self._last_dx = dx if should_move else 0
                self._last_dy = dy if should_move else 0
                if not should_move or (dx == 0 and dy == 0):
                    continue

            if apply_fn is None:
                continue
            try:
                apply_fn(dx, dy)
                with self._lock:
                    self._applied_since_arm = True
            except Exception as exc:
                logger.debug("aim: mouse apply failed: %s", exc)
                self._thread_stop.set()
                return
