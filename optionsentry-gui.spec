# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import shutil


a = Analysis(
    ["optionsentry_gui.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("optionsentry/gui/assets", "optionsentry/gui/assets"),
    ],
    hiddenimports=[
        "PyQt6.QtSvg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="optionsentry-gui",
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="optionsentry-gui",
)

dist_path = Path(DISTPATH) / "optionsentry-gui"
dist_path.mkdir(parents=True, exist_ok=True)
shutil.copyfile(
    Path("config.example.toml"),
    dist_path / "config.example.toml",
)
config_path = dist_path / "config.toml"
if not config_path.exists():
    shutil.copyfile(Path("config.example.toml"), config_path)
