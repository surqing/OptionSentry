from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from optionsentry.config import LoggingConfig
from optionsentry.log_paths import mode_scoped_dir, mode_scoped_file
from optionsentry.logging_config import setup_logging


class LoggingPathTests(unittest.TestCase):
    def test_mode_scoped_paths_insert_runtime_mode_once(self) -> None:
        self.assertEqual(mode_scoped_dir("logs", "live"), Path("logs") / "live")
        self.assertEqual(mode_scoped_dir(Path("logs") / "live", "live"), Path("logs") / "live")
        self.assertEqual(
            mode_scoped_file(Path("logs") / "alerts.jsonl", "backtest"),
            Path("logs") / "backtest" / "alerts.jsonl",
        )
        self.assertEqual(
            mode_scoped_file(Path("logs") / "backtest" / "alerts.jsonl", "backtest"),
            Path("logs") / "backtest" / "alerts.jsonl",
        )

    def test_setup_logging_writes_to_runtime_mode_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = setup_logging(
                LoggingConfig(
                    log_dir=tmpdir,
                    log_file="optionsentry.log",
                    max_bytes=100_000,
                    backup_count=1,
                ),
                runtime_mode="backtest",
            )
            try:
                logger.info("mode scoped log")
                for handler in logger.handlers:
                    handler.flush()

                log_path = Path(tmpdir) / "backtest" / "optionsentry.log"
                self.assertTrue(log_path.exists())
                self.assertIn("mode scoped log", log_path.read_text(encoding="utf-8"))
            finally:
                for handler in logger.handlers:
                    handler.close()
                logger.handlers.clear()
                logger.addHandler(logging.NullHandler())


if __name__ == "__main__":
    unittest.main()
