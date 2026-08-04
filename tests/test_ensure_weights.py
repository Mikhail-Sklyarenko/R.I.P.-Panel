"""Unit tests for scripts/ensure_weights.py (no network)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import scripts.ensure_weights as ew


def _registry(tmp: Path, *, sha: str, size: int, url: str = "http://example.test/w.pt") -> Path:
    reg = {
        "schema_version": 1,
        "active": "v-test",
        "install_path": "vendor/csgobot/yolov8",
        "artifacts": {
            "v-test": {
                "filename": "test_weights.pt",
                "url": url,
                "sha256": sha,
                "size_bytes": size,
            }
        },
    }
    path = tmp / "weights_registry.json"
    path.write_text(json.dumps(reg), encoding="utf-8")
    return path


def test_verify_ok(tmp_path: Path) -> None:
    payload = b"fake-weights-bytes"
    sha = hashlib.sha256(payload).hexdigest()
    dest = tmp_path / "vendor" / "csgobot" / "yolov8" / "test_weights.pt"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(payload)
    reg_path = _registry(tmp_path, sha=sha, size=len(payload))
    registry = ew.load_registry(reg_path)
    _, art = ew.resolve_artifact(registry)
    assert ew.verify(dest, art) == []


def test_check_only_missing(tmp_path: Path) -> None:
    reg_path = _registry(tmp_path, sha="abc", size=3)
    code = ew.ensure(
        registry_path=reg_path,
        repo_root=tmp_path,
        version=None,
        force=False,
        check_only=True,
    )
    assert code == 1


def test_ensure_download_and_verify(tmp_path: Path, monkeypatch) -> None:
    payload = b"downloaded-pt-content-xx"
    sha = hashlib.sha256(payload).hexdigest()
    reg_path = _registry(tmp_path, sha=sha, size=len(payload))

    def fake_download(url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)

    monkeypatch.setattr(ew, "download", fake_download)
    code = ew.ensure(
        registry_path=reg_path,
        repo_root=tmp_path,
        version=None,
        force=False,
        check_only=False,
    )
    assert code == 0
    out = tmp_path / "vendor" / "csgobot" / "yolov8" / "test_weights.pt"
    assert out.read_bytes() == payload
