from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from kuaiqi.config import LoggingConfig
from kuaiqi.log_paths import mode_scoped_dir


def setup_logging(config: LoggingConfig, runtime_mode: str | None = None) -> logging.Logger:
    log_dir = mode_scoped_dir(Path(config.log_dir), runtime_mode)
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("kuaiqi")
    logger.setLevel(getattr(logging, config.level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_dir / config.log_file,
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger
