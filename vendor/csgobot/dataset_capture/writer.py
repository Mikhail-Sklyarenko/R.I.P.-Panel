"""Async frame writer for auto-capture (never block detect/aim)."""

from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("AutoCapture")


@dataclass
class CaptureJob:
    stem: str
    image: np.ndarray
    meta: dict[str, Any]
    label_lines: list[str]
    jpeg_quality: int
    images_dir: Path
    meta_dir: Path
    labels_dir: Path | None


class CaptureWriter:
    """Background JPEG/meta/label writer with bounded queue."""

    def __init__(self, queue_size: int = 32) -> None:
        self._q: queue.Queue[CaptureJob | None] = queue.Queue(maxsize=queue_size)
        self._thread = threading.Thread(
            target=self._run, name="auto-capture-writer", daemon=True
        )
        self._dropped = 0
        self._written = 0
        self._bytes_written = 0
        self._started = False

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def written(self) -> int:
        return self._written

    @property
    def bytes_written(self) -> int:
        return self._bytes_written

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        if not self._started:
            return
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=timeout)

    def submit(self, job: CaptureJob) -> bool:
        try:
            self._q.put_nowait(job)
            return True
        except queue.Full:
            self._dropped += 1
            return False

    def _run(self) -> None:
        import cv2

        while True:
            job = self._q.get()
            if job is None:
                return
            try:
                job.images_dir.mkdir(parents=True, exist_ok=True)
                job.meta_dir.mkdir(parents=True, exist_ok=True)
                img_path = job.images_dir / f"{job.stem}.jpg"
                # Grabber frames are RGB; OpenCV expects BGR for imwrite.
                bgr = cv2.cvtColor(job.image, cv2.COLOR_RGB2BGR)
                ok = cv2.imwrite(
                    str(img_path),
                    bgr,
                    [int(cv2.IMWRITE_JPEG_QUALITY), int(job.jpeg_quality)],
                )
                if not ok:
                    logger.warning("capture write failed: %s", img_path)
                    continue
                self._bytes_written += img_path.stat().st_size
                meta_path = job.meta_dir / f"{job.stem}.json"
                meta_path.write_text(
                    json.dumps(job.meta, indent=2, ensure_ascii=True) + "\n",
                    encoding="utf-8",
                )
                if job.labels_dir is not None:
                    job.labels_dir.mkdir(parents=True, exist_ok=True)
                    (job.labels_dir / f"{job.stem}.txt").write_text(
                        "\n".join(job.label_lines) + ("\n" if job.label_lines else ""),
                        encoding="utf-8",
                    )
                self._written += 1
            except Exception as exc:  # noqa: BLE001 — never crash detect loop
                logger.warning("capture writer error: %s", exc)
