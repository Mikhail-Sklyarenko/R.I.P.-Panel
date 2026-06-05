"""Скриншоты и метаданные шагов: data/artifacts/{session_id}/."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from config.paths import get_artifacts_dir


class ArtifactStore:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.root = get_artifacts_dir(session_id)
        self.root.mkdir(parents=True, exist_ok=True)
        self._step = 0

    def save_image(self, name: str, image: Image.Image) -> Path:
        self._step += 1
        fname = f"{self._step:04d}_{name}.png"
        path = self.root / fname
        image.save(path)
        return path

    def save_json(self, name: str, payload: dict[str, Any]) -> Path:
        path = self.root / f"{name}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def log_step(self, action: str, detail: str = "", **extra: Any) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "detail": detail,
            **extra,
        }
        log_path = self.root / "steps.jsonl"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
