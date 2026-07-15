from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from optionsentry.config import parse_config
from optionsentry.gui.credentials import CredentialResolution


class GuiFilterValidationTests(unittest.TestCase):
    def test_start_rejects_missing_filter_script_before_starting_worker(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        from optionsentry.gui.app import MainWindow

        app = QApplication.instance() or QApplication([])
        config = parse_config(
            {
                "schema_version": 1,
                "strategies": [
                    {
                        "id": "cp",
                        "type": "cp_combo",
                        "name": "CP",
                        "enabled": True,
                        "parameters": {"min_value": 0.01, "max_value": float("inf")},
                        "filter": {"script": "missing.py", "entrypoint": "accept"},
                    }
                ]
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            window = MainWindow(
                Path(tmpdir) / "config.toml",
                config,
                CredentialResolution("u", "p", "TQSDK_USERNAME", "TQSDK_PASSWORD", "session"),
            )
            with patch("optionsentry.gui.app.QMessageBox.warning") as warning:
                window._start_monitor()

            warning.assert_called_once()
            self.assertIn("Strategy filter script not found", warning.call_args.args[2])
            self.assertFalse(window._running)
            self.assertIsNone(window._monitor_worker)
            self.assertIsNone(window._monitor_thread)
            window.close()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
