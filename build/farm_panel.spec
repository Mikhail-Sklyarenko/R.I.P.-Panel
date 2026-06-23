# -*- mode: python ; coding: utf-8 -*-
# B-PACKAGE: PyInstaller onedir → dist/FarmPanel/FarmPanel.exe
# Post-copy resources/ + vendor/ via build_windows.ps1

import sys
from pathlib import Path

block_cipher = None
SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "customtkinter",
        "PIL",
        "PIL._imagingtk",
        "pydantic",
        "yaml",
        "cryptography",
        "win32timezone",
        "win32api",
        "win32con",
        "win32gui",
        "pythoncom",
        "pywintypes",
        "panel",
        "panel.ui",
        "panel.controller",
        "core",
        "core.orchestrator",
        "core.session_fsm",
        "core.conveyor",
        "core.startup_checks",
        "config",
        "config.loader",
        "config.schema",
        "modules",
        "modules.launcher",
        "modules.dm_runner",
        "modules.combat",
        "modules.combat.phase",
        "modules.combat.factory",
        "modules.combat.simple",
        "modules.combat.csgobot_ai",
        "modules.drop_picker",
        "modules.level_detector",
        "modules.looter",
        "modules.telegram",
        "modules.utils",
        "modules.vault",
        "modules.vault.cli",
        "modules.ui_nav",
        "tkinter",
        "tkinter.messagebox",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FarmPanel",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "resources" / "app" / "farm_panel.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FarmPanel",
)
