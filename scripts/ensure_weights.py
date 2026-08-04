#!/usr/bin/env python3
"""Ensure production YOLO weights exist (farm-safe: ~50 MB, never the dataset)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "resources" / "csgobot" / "weights_registry.json"
CHUNK = 1024 * 1024


def load_registry(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "active" not in data or "artifacts" not in data:
        raise ValueError(f"invalid weights registry: {path}")
    return data


def resolve_artifact(registry: dict, version: str | None = None) -> tuple[str, dict]:
    ver = version or str(registry["active"])
    artifacts = registry["artifacts"]
    if ver not in artifacts:
        known = ", ".join(sorted(artifacts))
        raise KeyError(f"unknown weights version {ver!r}; known: {known}")
    return ver, artifacts[ver]


def target_path(registry: dict, artifact: dict, repo_root: Path) -> Path:
    install = str(registry.get("install_path") or "vendor/csgobot/yolov8")
    return repo_root / install / artifact["filename"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def verify(path: Path, artifact: dict) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"missing: {path}"]
    size = path.stat().st_size
    expected_size = int(artifact.get("size_bytes") or 0)
    if expected_size and size != expected_size:
        errors.append(f"size mismatch: got {size}, expected {expected_size}")
    expected_sha = str(artifact.get("sha256") or "").lower()
    if expected_sha:
        got = sha256_file(path).lower()
        if got != expected_sha:
            errors.append(f"sha256 mismatch: got {got}, expected {expected_sha}")
    if size == 0:
        errors.append("file is empty (0 bytes)")
    return errors


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    if tmp.exists():
        tmp.unlink()
    req = urllib.request.Request(url, headers={"User-Agent": "R.I.P-Panel-EnsureWeights/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
            total = resp.headers.get("Content-Length")
            total_n = int(total) if total and total.isdigit() else None
            done = 0
            while True:
                block = resp.read(CHUNK)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if total_n:
                    pct = 100.0 * done / total_n
                    print(f"\r  downloading… {done}/{total_n} ({pct:.1f}%)", end="", flush=True)
                else:
                    print(f"\r  downloading… {done} bytes", end="", flush=True)
        print()
    except urllib.error.URLError as exc:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"download failed: {exc}") from exc
    tmp.replace(dest)


def ensure(
    *,
    registry_path: Path,
    repo_root: Path,
    version: str | None,
    force: bool,
    check_only: bool,
) -> int:
    registry = load_registry(registry_path)
    ver, artifact = resolve_artifact(registry, version)
    dest = target_path(registry, artifact, repo_root)
    print(f"weights version: {ver}")
    print(f"target: {dest}")
    print(f"url: {artifact.get('url')}")

    if dest.is_file() and not force:
        errors = verify(dest, artifact)
        if not errors:
            print(f"OK: already present ({dest.stat().st_size} bytes)")
            return 0
        print("WARN: local file failed verification:")
        for e in errors:
            print(f"  - {e}")
        if check_only:
            return 1
        print("re-downloading…")
    elif check_only:
        print("ERROR: weights missing")
        print(f"  run: EnsureWeights.bat   (or python scripts/ensure_weights.py)")
        return 1

    url = str(artifact.get("url") or "")
    if not url:
        print("ERROR: artifact has no url")
        return 1
    download(url, dest)
    errors = verify(dest, artifact)
    if errors:
        print("ERROR: downloaded file failed verification:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: weights ready ({dest.stat().st_size} bytes)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download/verify production YOLO weights for farm PCs (~50 MB)."
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="path to weights_registry.json",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="farm-panel-prototype root",
    )
    parser.add_argument("--version", type=str, default=None, help="override active version")
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="verify only; do not download",
    )
    args = parser.parse_args(argv)
    try:
        return ensure(
            registry_path=args.registry,
            repo_root=args.repo_root,
            version=args.version,
            force=args.force,
            check_only=args.check_only,
        )
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
