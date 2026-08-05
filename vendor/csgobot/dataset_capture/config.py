"""Auto-capture configuration (env-driven, farm collector mode)."""

from __future__ import annotations

import os
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return None
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(float(raw))


@dataclass
class AutoCaptureConfig:
    """Farm-side capture settings. Default OFF — enable on collector PCs only."""

    enabled: bool = False
    root_dir: str = "data/captures"
    interval_sec: float = 1.2
    min_interval_sec: float = 0.8
    max_per_hour: int = 400
    max_mb: int = 2048
    jpeg_quality: int = 90
    soft_ct_enabled: bool = True
    soft_ct_lo: float = 0.30
    soft_ct_hi: float = 0.55
    team_t_boost: bool = True
    team_t_interval_scale: float = 0.65
    save_soft_labels: bool = True
    label_conf_c: float = 0.35
    label_conf_ch: float = 0.38
    label_conf_t: float = 0.50
    label_conf_th: float = 0.50
    min_bbox_height: float = 12.0
    queue_size: int = 32
    dedup_hamming_max: int = 4
    pc_id: str = ""
    session_id: str = ""

    def label_conf_for(self, class_name: str) -> float:
        return {
            "c": self.label_conf_c,
            "ch": self.label_conf_ch,
            "t": self.label_conf_t,
            "th": self.label_conf_th,
        }.get(class_name, 0.5)


def resolve_auto_capture_config(default_enabled: bool = False) -> AutoCaptureConfig:
    enabled = _env_bool("CSGOBOT_AUTO_CAPTURE")
    soft = _env_bool("CSGOBOT_CAPTURE_SOFT_CT")
    boost = _env_bool("CSGOBOT_CAPTURE_WHEN_TEAM_T_BOOST")
    save_labels = _env_bool("CSGOBOT_CAPTURE_SOFT_LABELS")

    pc_id = os.environ.get("CSGOBOT_CAPTURE_PC_ID", "").strip()
    if not pc_id:
        pc_id = socket.gethostname().replace(" ", "_")[:48] or "pc"

    session_id = os.environ.get("CSGOBOT_CAPTURE_SESSION_ID", "").strip()
    if not session_id:
        session_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]

    root = os.environ.get("CSGOBOT_CAPTURE_DIR", "").strip() or "data/captures"

    return AutoCaptureConfig(
        enabled=default_enabled if enabled is None else enabled,
        root_dir=root,
        interval_sec=max(0.3, _env_float("CSGOBOT_CAPTURE_INTERVAL_SEC", 1.2)),
        min_interval_sec=max(0.2, _env_float("CSGOBOT_CAPTURE_MIN_INTERVAL_SEC", 0.8)),
        max_per_hour=max(10, _env_int("CSGOBOT_CAPTURE_MAX_PER_HOUR", 400)),
        max_mb=max(64, _env_int("CSGOBOT_CAPTURE_MAX_MB", 2048)),
        jpeg_quality=max(50, min(100, _env_int("CSGOBOT_CAPTURE_JPEG_QUALITY", 90))),
        soft_ct_enabled=True if soft is None else soft,
        soft_ct_lo=max(0.05, _env_float("CSGOBOT_CAPTURE_SOFT_CT_LO", 0.30)),
        soft_ct_hi=max(0.1, _env_float("CSGOBOT_CAPTURE_SOFT_CT_HI", 0.55)),
        team_t_boost=True if boost is None else boost,
        team_t_interval_scale=max(
            0.3, min(1.0, _env_float("CSGOBOT_CAPTURE_T_INTERVAL_SCALE", 0.65))
        ),
        save_soft_labels=True if save_labels is None else save_labels,
        label_conf_c=max(0.05, _env_float("CSGOBOT_CAPTURE_LABEL_CONF_C", 0.35)),
        label_conf_ch=max(0.05, _env_float("CSGOBOT_CAPTURE_LABEL_CONF_CH", 0.38)),
        label_conf_t=max(0.05, _env_float("CSGOBOT_CAPTURE_LABEL_CONF_T", 0.50)),
        label_conf_th=max(0.05, _env_float("CSGOBOT_CAPTURE_LABEL_CONF_TH", 0.50)),
        min_bbox_height=max(4.0, _env_float("CSGOBOT_CAPTURE_MIN_BBOX_H", 12.0)),
        queue_size=max(4, _env_int("CSGOBOT_CAPTURE_QUEUE_SIZE", 32)),
        dedup_hamming_max=max(0, _env_int("CSGOBOT_CAPTURE_DEDUP_HAMMING", 4)),
        pc_id=pc_id,
        session_id=session_id,
    )


def capture_session_dir(cfg: AutoCaptureConfig, base: Path | None = None) -> Path:
    root = Path(cfg.root_dir)
    if not root.is_absolute():
        root = (base or Path.cwd()) / root
    return root / cfg.pc_id / cfg.session_id
