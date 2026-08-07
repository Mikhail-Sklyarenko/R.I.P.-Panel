"""Decide when to capture farm frames for CT dataset bootstrap."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from dataset_capture.config import AutoCaptureConfig, capture_session_dir
from dataset_capture.writer import CaptureJob, CaptureWriter

logger = logging.getLogger("AutoCapture")

CLASS_IDS = {"c": 0, "ch": 1, "t": 2, "th": 3}


def average_hash64(image: np.ndarray) -> int:
    """Tiny aHash for near-duplicate rejection (numpy-only, no OpenCV required)."""
    if image is None or image.size == 0:
        return 0
    if image.ndim == 3:
        # Rec. 601 luma approximation
        gray = (
            0.299 * image[:, :, 0].astype(np.float32)
            + 0.587 * image[:, :, 1].astype(np.float32)
            + 0.114 * image[:, :, 2].astype(np.float32)
        )
    else:
        gray = image.astype(np.float32)
    # Nearest-neighbor downsample to 8x8
    ys = (np.linspace(0, gray.shape[0] - 1, 8)).astype(np.int32)
    xs = (np.linspace(0, gray.shape[1] - 1, 8)).astype(np.int32)
    small = gray[ys][:, xs]
    bits = 0
    flat = small.flatten()
    mean = float(flat.mean())
    # Strict > avoids all-bits-set on perfectly flat frames.
    for i, px in enumerate(flat):
        if float(px) > mean:
            bits |= 1 << i
    return bits


def hamming64(a: int, b: int) -> int:
    x = a ^ b
    try:
        return int(x.bit_count())
    except AttributeError:  # pragma: no cover
        return bin(x).count("1")


def xyxy_to_yolo_line(
    class_id: int,
    xyxy: list[float],
    width: int,
    height: int,
) -> str | None:
    if width <= 0 or height <= 0:
        return None
    x1, y1, x2, y2 = [float(v) for v in xyxy]
    bw = max(0.0, x2 - x1)
    bh = max(0.0, y2 - y1)
    if bw < 1.0 or bh < 1.0:
        return None
    cx = (x1 + x2) / 2.0 / width
    cy = (y1 + y2) / 2.0 / height
    nw = bw / width
    nh = bh / height
    cx = min(1.0, max(0.0, cx))
    cy = min(1.0, max(0.0, cy))
    nw = min(1.0, max(0.0, nw))
    nh = min(1.0, max(0.0, nh))
    return f"{class_id} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}"


def build_soft_labels(
    detections: dict[str, list[dict[str, Any]]],
    *,
    width: int,
    height: int,
    cfg: AutoCaptureConfig,
) -> list[str]:
    lines: list[str] = []
    for class_name, boxes in detections.items():
        class_id = CLASS_IDS.get(class_name)
        if class_id is None:
            continue
        min_conf = cfg.label_conf_for(class_name)
        for box in boxes:
            conf = float(box.get("conf", 0.0))
            if conf < min_conf:
                continue
            xyxy = box.get("xyxy")
            if not xyxy or len(xyxy) != 4:
                continue
            x1, y1, x2, y2 = [float(v) for v in xyxy]
            if (y2 - y1) < cfg.min_bbox_height:
                continue
            line = xyxy_to_yolo_line(class_id, xyxy, width, height)
            if line:
                lines.append(line)
    return lines


def has_soft_ct(
    detections: dict[str, list[dict[str, Any]]],
    *,
    lo: float,
    hi: float,
) -> bool:
    for class_name in ("c", "ch"):
        for box in detections.get(class_name, []):
            conf = float(box.get("conf", 0.0))
            if lo <= conf < hi:
                return True
    return False


def count_all_boxes(
    detections: dict[str, list[dict[str, Any]]],
) -> int:
    return sum(len(boxes) for boxes in detections.values())


def count_enemy_boxes(
    detections: dict[str, list[dict[str, Any]]],
    enemy_classes: tuple[str, ...],
) -> int:
    return sum(len(detections.get(c, [])) for c in enemy_classes)


# Triggers that must never carry soft labels (texture / empty hard negatives).
FORCE_EMPTY_TRIGGERS = frozenset({"empty_scene", "texture_fp", "hard_neg_timer"})


class AutoCaptureController:
    """Non-blocking capture scheduler for collector farm PCs."""

    def __init__(
        self,
        cfg: AutoCaptureConfig,
        *,
        cwd: Path | None = None,
        weights_name: str = "",
    ) -> None:
        self.cfg = cfg
        self.cwd = cwd or Path.cwd()
        self.weights_name = weights_name
        self.session_dir = capture_session_dir(cfg, self.cwd)
        self.images_dir = self.session_dir / "images"
        self.meta_dir = self.session_dir / "meta"
        self.labels_dir = self.session_dir / "labels_soft"
        self._writer = CaptureWriter(queue_size=cfg.queue_size)
        self._last_save = 0.0
        self._last_empty_scene = 0.0
        self._hour_start = time.time()
        self._hour_count = 0
        self._recent_hashes: list[int] = []
        self._had_enemy = False
        self._stopped = False
        if cfg.enabled:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                "auto_capture: ON dir=%s interval=%.2fs max/h=%d "
                "empty_scene=%s hard_neg=%s",
                self.session_dir,
                cfg.interval_sec,
                cfg.max_per_hour,
                cfg.empty_scene_enabled,
                cfg.hard_neg_mode,
            )

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._writer.stop()
        if self.cfg.enabled:
            logger.info(
                "auto_capture: stop written=%d dropped=%d bytes=%d",
                self._writer.written,
                self._writer.dropped,
                self._writer.bytes_written,
            )

    def _budget_ok(self, now: float) -> bool:
        if now - self._hour_start >= 3600.0:
            self._hour_start = now
            self._hour_count = 0
        if self._hour_count >= self.cfg.max_per_hour:
            return False
        if self._writer.bytes_written >= self.cfg.max_mb * 1024 * 1024:
            return False
        return True

    def _interval(self, team: str) -> float:
        if self.cfg.hard_neg_mode:
            return max(self.cfg.min_interval_sec, self.cfg.hard_neg_interval_sec)
        interval = self.cfg.interval_sec
        if self.cfg.team_t_boost and team.lower() == "t":
            interval *= self.cfg.team_t_interval_scale
        return max(self.cfg.min_interval_sec, interval)

    def _is_duplicate(self, image: np.ndarray) -> bool:
        h = average_hash64(image)
        for prev in self._recent_hashes:
            if hamming64(h, prev) <= self.cfg.dedup_hamming_max:
                return True
        self._recent_hashes.append(h)
        if len(self._recent_hashes) > 64:
            self._recent_hashes = self._recent_hashes[-64:]
        return False

    def maybe_capture(
        self,
        image: np.ndarray,
        *,
        detections: dict[str, list[dict[str, Any]]],
        team: str,
        activated: bool,
        roi_used: bool,
        enemy_classes: tuple[str, ...],
        now: float | None = None,
        combat_conf: float | None = None,
        class_conf: dict[str, float] | None = None,
    ) -> str | None:
        """
        Possibly enqueue a frame. Returns trigger name if queued, else None.
        Never raises into the detect loop.
        """
        if not self.cfg.enabled or self._stopped:
            return None
        if image is None or image.size == 0:
            return None
        if not activated:
            self._had_enemy = False
            return None

        now = time.time() if now is None else now
        if not self._budget_ok(now):
            return None
        if now - self._last_save < self.cfg.min_interval_sec:
            return None

        enemy_n = count_enemy_boxes(detections, enemy_classes)
        total_n = count_all_boxes(detections)
        trigger: str | None = None

        if self.cfg.hard_neg_mode:
            # Dedicated walk-around: save map textures as empty labels even if
            # YOLO hallucinates players on crates/walls.
            if total_n > 0 and now - self._last_save >= self._interval(team):
                trigger = "texture_fp"
            elif now - self._last_save >= self._interval(team):
                trigger = "hard_neg_timer"
        else:
            if roi_used and enemy_n == 0:
                trigger = "roi_miss"
            elif self.cfg.soft_ct_enabled and has_soft_ct(
                detections, lo=self.cfg.soft_ct_lo, hi=self.cfg.soft_ct_hi
            ):
                trigger = "soft_ct"
            elif enemy_n > 0 and not self._had_enemy:
                trigger = "enemy_appear"
            elif (
                self.cfg.empty_scene_enabled
                and total_n == 0
                and now - self._last_empty_scene >= self.cfg.empty_scene_interval_sec
                and now - self._last_save >= self.cfg.min_interval_sec
            ):
                trigger = "empty_scene"
            elif now - self._last_save >= self._interval(team):
                trigger = "timer_t" if team.lower() == "t" else "timer"

        self._had_enemy = enemy_n > 0
        if trigger is None:
            return None
        if self._is_duplicate(image):
            return None

        h, w = image.shape[:2]
        force_empty = (
            self.cfg.hard_neg_mode
            or trigger in FORCE_EMPTY_TRIGGERS
        )
        label_lines: list[str] = []
        if self.cfg.save_soft_labels and not force_empty:
            label_lines = build_soft_labels(
                detections, width=w, height=h, cfg=self.cfg
            )

        stem = time.strftime("%Y%m%d_%H%M%S") + f"_{int((now % 1) * 1000):03d}"
        stem = f"{stem}__{team.lower()}__{trigger}"

        det_summary = []
        for cls_name, boxes in detections.items():
            for box in boxes[:8]:
                det_summary.append(
                    {
                        "cls": cls_name,
                        "conf": round(float(box.get("conf", 0.0)), 4),
                        "xyxy": [round(float(v), 1) for v in box.get("xyxy", [])],
                    }
                )

        meta = {
            "ts": now,
            "team": team.lower(),
            "trigger": trigger,
            "force_empty": force_empty,
            "hard_neg_mode": self.cfg.hard_neg_mode,
            "roi_used": bool(roi_used),
            "resolution": [int(w), int(h)],
            "weights": self.weights_name,
            "combat_conf": combat_conf,
            "class_conf": class_conf or {},
            "enemy_classes": list(enemy_classes),
            "soft_label_count": len(label_lines),
            "detections": det_summary,
            "pc_id": self.cfg.pc_id,
            "session_id": self.cfg.session_id,
        }

        # Copy image so detect loop can mutate/reuse buffers safely.
        job = CaptureJob(
            stem=stem,
            image=np.ascontiguousarray(image.copy()),
            meta=meta,
            label_lines=label_lines,
            jpeg_quality=self.cfg.jpeg_quality,
            images_dir=self.images_dir,
            meta_dir=self.meta_dir,
            labels_dir=self.labels_dir if self.cfg.save_soft_labels else None,
        )
        self._writer.start()
        if not self._writer.submit(job):
            return None
        self._last_save = now
        if trigger == "empty_scene":
            self._last_empty_scene = now
        self._hour_count += 1
        return trigger
