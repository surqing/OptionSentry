# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import shutil

from PyInstaller.utils.hooks import collect_submodules


def copy_user_filter_scripts(dist_path):
    source_path = Path("user_filter_scripts")
    target_path = dist_path / "user_filter_scripts"
    if target_path.exists():
        shutil.rmtree(target_path)
    if not source_path.exists():
        target_path.mkdir(parents=True, exist_ok=True)
        return
    shutil.copytree(
        source_path,
        target_path,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )


a = Analysis(
    ["optionsentry_gui.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("optionsentry/gui/assets", "optionsentry/gui/assets"),
    ],
    hiddenimports=["PyQt6.QtSvg", *collect_submodules("optionsentry.strategy_types")],
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
copy_user_filter_scripts(dist_path)
