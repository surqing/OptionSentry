from __future__ import annotations

from pathlib import Path


def mode_scoped_dir(path: str | Path, runtime_mode: str | None) -> Path:
    base_path = Path(path)
    if not runtime_mode or base_path.name == runtime_mode:
        return base_path
    return base_path / runtime_mode


def mode_scoped_file(path: str | Path, runtime_mode: str | None) -> Path:
    base_path = Path(path)
    if not runtime_mode or base_path.parent.name == runtime_mode:
        return base_path
    return base_path.parent / runtime_mode / base_path.name
