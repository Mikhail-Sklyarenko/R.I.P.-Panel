"""Steam/CS2 executable picker (B-PATHS): validation + Windows filedialog."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

STEAM_EXE_NAMES = frozenset({"steam.exe"})
CS2_EXE_NAMES = frozenset({"cs2.exe", "csgo.exe"})

_DEFAULT_STEAM_DIR = Path(r"C:\Program Files (x86)\Steam")


def truncate_path(path: str, *, max_len: int = 48) -> str:
    p = (path or "").strip()
    if not p:
        return "(not set)"
    if len(p) <= max_len:
        return p
    head = (max_len - 3) // 2
    tail = max_len - 3 - head
    return f"{p[:head]}...{p[-tail:]}"


def _normalize_path(raw: str) -> Path:
    return Path(raw.strip().strip('"'))


def validate_executable(path: str, expected_basenames: frozenset[str]) -> str | None:
    """Return an error message, or None if the path is acceptable."""
    p = _normalize_path(path)
    if not p.is_file():
        return f"file not found: {p}"
    name = p.name
    if not name.lower().endswith(".exe"):
        return f"expected a .exe file, got: {name}"
    if name.lower() not in {n.lower() for n in expected_basenames}:
        expected = ", ".join(sorted(expected_basenames))
        return f"expected {expected}, got: {name}"
    return None


def _valid_file_parent(raw: str) -> str | None:
    p = _normalize_path(raw)
    if p.is_file():
        return str(p.parent)
    return None


def default_steam_initialdir(current_steam_path: str) -> str:
    parent = _valid_file_parent(current_steam_path)
    if parent:
        return parent
    env = os.environ.get("ProgramFiles(x86)", "")
    if env:
        candidate = Path(env) / "Steam"
        if candidate.is_dir():
            return str(candidate)
    if _DEFAULT_STEAM_DIR.is_dir():
        return str(_DEFAULT_STEAM_DIR)
    return env or str(_DEFAULT_STEAM_DIR.parent)


def default_cs2_initialdir(current_cs2_path: str, steam_path: str) -> str:
    parent = _valid_file_parent(current_cs2_path)
    if parent:
        return parent
    steam_parent = _valid_file_parent(steam_path)
    if steam_parent:
        steam_dir = Path(steam_parent)
        cs2_dir = (
            steam_dir
            / "steamapps"
            / "common"
            / "Counter-Strike Global Offensive"
            / "game"
            / "bin"
            / "win64"
        )
        if cs2_dir.is_dir():
            return str(cs2_dir)
    env = os.environ.get("ProgramFiles(x86)", "")
    return env or str(_DEFAULT_STEAM_DIR.parent)


def pick_executable(
    *,
    parent: Any,
    title: str,
    initialdir: str,
    expected_basenames: frozenset[str],
) -> str | None:
    """Open filedialog on Windows; return normalized path or None if cancelled/invalid."""
    if sys.platform != "win32":
        return None
    from tkinter import filedialog, messagebox

    root = parent
    if root is not None and hasattr(root, "winfo_toplevel"):
        root = root.winfo_toplevel()

    start = initialdir if initialdir and Path(initialdir).is_dir() else None
    selected = filedialog.askopenfilename(
        parent=root,
        title=title,
        initialdir=start,
        filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
    )
    if not selected:
        return None
    err = validate_executable(selected, expected_basenames)
    if err:
        messagebox.showerror("Invalid executable", err, parent=root)
        return None
    return str(_normalize_path(selected).resolve())


def path_picker_available() -> bool:
    return sys.platform == "win32"
