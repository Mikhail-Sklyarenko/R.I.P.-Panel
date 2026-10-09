"""High-rate aim mouse (PR-A1 / A1.1 settle / A1.2 dual-phase / A1.2.1 hold).

Detection updates the tracked aim point; a dedicated mouse thread applies FOV
deltas at ``mouse_hz``. Soft-settle stops on-target bbox hunt; dual-phase
gain snaps fast when far and tightens only near the crosshair. A1.2.1 adds
near-zone Y damp and expects hard-retarget only on real target switches.
"""

from __future__ import annotations

import logging
import threading
import time
from math import hypot, radians, tan
from collections import deque
from typing import TYPE_CHECKING, Callable

from aiming.dead_zone import AimHysteresis, AimHysteresisConfig
from aiming.mouse_filter import filter_mouse_delta
from aim_tuning import acquisition_smoothing

if TYPE_CHECKING:
    from aiming.fov_mouse import FOVMouseMovement
    from config import AimConfig

logger = logging.getLogger("CS2Bot.aim")

ApplyMouseFn = Callable[[int, int], bool | None]

# Cap coast velocity so a bad detection jump cannot fling the mouse.
_MAX_COAST_SPEED_PX_S = 2500.0


class AimMouseController:
    """
    Track screen-space aim point + apply mouse at high rate.

    A1 — detection owns *what* to track; mouse thread owns *how* it moves.
    A1.1 — soft-settle: freeze aim point when on target; coast only for real speed.
    A1.2 — dual-phase: low smoothing + large step when far; precision near settle.
    A1.2.1 — near Y damp + calmer defaults; hard-retarget owned by main loop.
    """

    def __init__(
        self,
        *,
        config: AimConfig,
        fov_mouse: FOVMouseMovement,
        command_history=None,
    ) -> None:
        self._command_history = command_history
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

        self._sent = deque(maxlen=256)
        self._revision = 0
        self._active = False
        self._target_x = 0.0
        self._target_y = 0.0
        self._target_t = 0.0
        self._smoothing = 1.0
        self._vx = 0.0
        self._vy = 0.0
        self._has_sample = False

        # Soft-settle: hold a locked aim point while crosshair is on target.
        self._settled = False
        self._lock_x = 0.0
        self._lock_y = 0.0

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
    def is_settled(self) -> bool:
        with self._lock:
            return self._settled

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
            "aim: mouse thread hz=%.0f step_max=%d near_step=%d "
            "settle=%.0f unlock=%.0f snap=%.0f acquire_scale=%.2f "
            "y_scale=%.2f coast=%s coast_min_v=%.0f (A1.2.1)",
            float(self._config.mouse_hz),
            self._step_max_delta(),
            max(1, int(self._config.aim_near_step_max_delta)),
            float(self._config.aim_settle_px),
            float(self._config.aim_unlock_px),
            float(self._config.aim_snap_px),
            float(self._config.aim_acquire_smooth_scale),
            float(self._config.aim_near_y_scale),
            bool(self._config.mouse_coast),
            float(self._config.mouse_coast_min_speed_px_s),
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
            if self._has_sample and now < self._target_t:
                return
            self._revision += 1
            # Transport the previous observation into this capture's camera frame.
            previous_x, previous_y = self._remaining_screen_point(
                self._target_x, self._target_y, self._target_t, until=now)
            if self._settled:
                self._lock_x, self._lock_y = self._remaining_screen_point(
                    self._lock_x, self._lock_y, self._target_t, until=now)
            raw_x = float(aim_x)
            raw_y = float(aim_y)

            if self._settled and bool(self._config.aim_settle_enabled):
                unlock = max(1.0, float(self._config.aim_unlock_px))
                if hypot(raw_x - self._lock_x, raw_y - self._lock_y) < unlock:
                    # Hold locked point — ignore bbox jitter; no coast from noise.
                    self._target_x = self._lock_x
                    self._target_y = self._lock_y
                    self._target_t = float(now)
                    self._smoothing = max(1.0, float(smoothing))
                    self._vx = 0.0
                    self._vy = 0.0
                    self._active = True
                    self._has_sample = True
                    return
                # Real target motion — leave settle and track again.
                self._settled = False

            if self._has_sample:
                dt = now - self._target_t
                if 0.001 < dt < 0.5:
                    vx = (raw_x - previous_x) / dt
                    vy = (raw_y - previous_y) / dt
                    speed = hypot(vx, vy)
                    if speed > _MAX_COAST_SPEED_PX_S:
                        scale = _MAX_COAST_SPEED_PX_S / speed
                        vx *= scale
                        vy *= scale
                    min_coast = max(0.0, float(self._config.mouse_coast_min_speed_px_s))
                    if speed < min_coast:
                        vx = 0.0
                        vy = 0.0
                    self._vx = vx
                    self._vy = vy
                else:
                    self._vx = 0.0
                    self._vy = 0.0
            else:
                self._vx = 0.0
                self._vy = 0.0

            self._target_x = raw_x
            self._target_y = raw_y
            self._target_t = float(now)
            self._smoothing = max(1.0, float(smoothing))
            self._active = True
            self._has_sample = True

    def clear(self) -> None:
        with self._lock:
            self._clear_locked()

    def reset_track(self) -> None:
        """Target switch / body fallback — drop settle + coast, keep thread."""
        with self._lock:
            self._revision += 1
            self._has_sample = False
            self._vx = 0.0
            self._vy = 0.0
            self._settled = False
            self._applied_since_arm = False
            self._hysteresis.reset()

    def _clear_locked(self) -> None:
        self._revision += 1
        self._active = False
        self._has_sample = False
        self._vx = 0.0
        self._vy = 0.0
        self._settled = False
        self._last_dx = 0
        self._last_dy = 0
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

    def _enter_settle_locked(self, lock_x: float, lock_y: float) -> None:
        self._settled = True
        self._lock_x = lock_x
        self._lock_y = lock_y
        self._target_x = lock_x
        self._target_y = lock_y
        self._vx = 0.0
        self._vy = 0.0
        self._hysteresis.reset()

    def project_point(self, x, y, observed_at, until=None):
        """Reproject a measured point using accepted mouse output only."""
        with self._lock:
            return self._remaining_screen_point(x, y, observed_at, until=until)

    def _remaining_screen_point(self,x,y,observed_at,until=None):
        """Subtract only mouse commands already sent after this capture."""
        ax,ay=self._fov_mouse.screen_to_angle(x,y)
        history = (self._command_history(observed_at,until) if self._command_history is not None
                   else self._sent)
        dx=sum(dx for stamp,dx,dy in history if stamp>=observed_at and (until is None or stamp<until))
        dy=sum(dy for stamp,dx,dy in history if stamp>=observed_at and (until is None or stamp<until))
        unit=360./self._fov_mouse.fov.x360
        ax=max(-80.,min(80.,ax-dx*unit));ay=max(-80.,min(80.,ay-dy*unit))
        return (self._fov_mouse._center_x+self._fov_mouse._focal_x*tan(radians(ax)),
                self._fov_mouse._center_y+self._fov_mouse._focal_y*tan(radians(ay)))

    def _mouse_loop(self) -> None:
        hz = max(30.0, float(self._config.mouse_hz))
        period = 1.0 / hz
        coast = bool(self._config.mouse_coast)
        coast_max = max(0.0, float(self._config.mouse_coast_max_sec))
        min_delta = max(0, int(self._config.mouse_min_delta))
        far_step = self._step_max_delta()
        near_step = max(1, int(self._config.aim_near_step_max_delta))
        near_px = max(0.0, float(self._config.aim_near_px))
        snap_px = max(near_px + 1.0, float(self._config.aim_snap_px))
        acquire_scale = float(self._config.aim_acquire_smooth_scale)
        near_y_scale = float(self._config.aim_near_y_scale)
        settle_px = max(0.0, float(self._config.aim_settle_px))
        settle_on = bool(self._config.aim_settle_enabled)
        min_coast_speed = max(0.0, float(self._config.mouse_coast_min_speed_px_s))

        while not self._thread_stop.wait(period):
            apply_fn: ApplyMouseFn | None = None
            tx = ty = 0.0
            base_x = base_y = 0.0
            smoothing = 1.0
            with self._lock:
                if not self._active or self._apply_mouse is None:
                    continue
                now = time.monotonic()
                age = now - self._target_t
                if not 0<=age<=.25:
                    self._clear_locked()
                    continue
                while self._sent and self._sent[0][0]<now-.5:
                    self._sent.popleft()
                revision = self._revision
                speed = hypot(self._vx, self._vy)
                base_x = self._target_x
                base_y = self._target_y
                # Coast only for real motion, never while soft-settled.
                use_coast = (
                    coast
                    and not self._settled
                    and coast_max > 0
                    and 0.0 <= age <= coast_max
                    and speed >= min_coast_speed
                )
                if use_coast:
                    tx = base_x + self._vx * age
                    ty = base_y + self._vy * age
                else:
                    tx = base_x
                    ty = base_y
                tx,ty=self._remaining_screen_point(tx,ty,self._target_t)
                base_x,base_y=self._remaining_screen_point(base_x,base_y,self._target_t)
                smoothing = self._smoothing
                apply_fn = self._apply_mouse

            # Settle against the locked/raw aim point (not coasted ghost).
            settle_dist = self._fov_mouse.get_move(
                base_x, base_y, smoothing=1.0
            ).pixel_distance

            with self._lock:
                if not self._active or revision != self._revision:
                    continue
                if settle_on and settle_px > 0 and settle_dist <= settle_px:
                    self._enter_settle_locked(self._target_x, self._target_y)
                    self._last_pixel_distance = settle_dist
                    self._last_dx = 0
                    self._last_dy = 0
                    continue

            # Dual-phase: measure raw error, then snap hard when far.
            raw_dist = self._fov_mouse.get_move(tx, ty, smoothing=1.0).pixel_distance
            eff_smooth = acquisition_smoothing(
                smoothing,
                raw_dist,
                near_px=near_px,
                snap_px=snap_px,
                far_scale=acquire_scale,
            )
            aim_result = self._fov_mouse.get_move(tx, ty, smoothing=eff_smooth)
            dist = aim_result.pixel_distance

            # Blend the speed limit instead of changing it abruptly at near_px.
            blend = max(0.0, min(1.0, (dist - near_px) / (snap_px - near_px)))
            step_max = round(min(far_step, near_step) +
                             (far_step - min(far_step, near_step)) * blend)

            dx, dy = filter_mouse_delta(
                aim_result.mouse_x,
                aim_result.mouse_y,
                max_delta=step_max,
                min_delta=min_delta,
            )

            # A1.2.1: bbox head/chest flicker is mostly vertical — damp near target.
            if (
                near_px > 0
                and dist <= near_px
                and 0.0 < near_y_scale < 1.0
                and dy != 0
            ):
                dy = int(round(dy * near_y_scale))

            with self._lock:
                if not self._active or revision != self._revision:
                    continue

                if self._settled and dist > max(
                    settle_px, float(self._config.aim_dead_zone_high)
                ):
                    self._settled = False

                should_move = self._hysteresis.should_move(dist)
                self._last_pixel_distance = dist
                self._last_dx = dx if should_move else 0
                self._last_dy = dy if should_move else 0
                if not should_move or (dx == 0 and dy == 0):
                    continue

            if apply_fn is None:
                continue
            try:
                with self._lock:
                    if not self._active or revision != self._revision:
                        continue
                    accepted = apply_fn(dx, dy)
                    if accepted is not False:
                        self._sent.append((time.monotonic(), dx, dy))
                        self._applied_since_arm = True
            except Exception as exc:
                logger.debug("aim: mouse apply failed: %s", exc)
                self._thread_stop.set()
                return
