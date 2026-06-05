"""CS2 cfg directory resolution (B-STEAM-AUTH fix)."""

from __future__ import annotations

from pathlib import Path

from modules.launcher.cs2 import find_csgo_cfg_dir


def test_find_csgo_cfg_under_game_bin_win64(tmp_path: Path) -> None:
    root = tmp_path / "Counter-Strike Global Offensive" / "game"
    cfg = root / "csgo" / "cfg"
    cfg.mkdir(parents=True)
    exe = root / "bin" / "win64" / "cs2.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")

    found = find_csgo_cfg_dir(exe)
    assert found == cfg.resolve()


def test_find_csgo_cfg_creates_missing_cfg(tmp_path: Path) -> None:
    root = tmp_path / "CSGO" / "game"
    (root / "csgo").mkdir(parents=True)
    exe = root / "bin" / "win64" / "cs2.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")

    found = find_csgo_cfg_dir(exe)
    assert found.name == "cfg"
    assert found.parent.name == "csgo"
    assert found.is_dir()
