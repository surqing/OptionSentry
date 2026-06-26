from __future__ import annotations

import os
import unittest
from pathlib import Path


class GuiSmokeTests(unittest.TestCase):
    def test_pyqt_login_window_constructs_offscreen(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        from kuaiqi.config import parse_config
        from kuaiqi.gui.app import LoginWindow, MainWindow
        from kuaiqi.gui.credentials import CredentialResolution

        app = QApplication.instance() or QApplication([])
        window = LoginWindow()
        config = parse_config({"strategies": [{"type": "cp_combo", "threshold": 0.01}]})
        main_window = MainWindow(
            Path("config.toml"),
            config,
            CredentialResolution("u", "p", "TQSDK_USERNAME", "TQSDK_PASSWORD", "session"),
        )

        self.assertIsNotNone(app)
        self.assertEqual(window.windowTitle(), "KuaiQi 登录")
        self.assertEqual(main_window.config_editor.build_config().runtime.mode, "live")


if __name__ == "__main__":
    unittest.main()
