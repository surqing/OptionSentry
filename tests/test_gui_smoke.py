from __future__ import annotations

import os
import unittest
from pathlib import Path


class GuiSmokeTests(unittest.TestCase):
    def test_pyqt_login_window_constructs_offscreen(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt

        from kuaiqi.config import parse_config
        from kuaiqi.gui.app import LoginWindow, MainWindow, _double_spin, _spin
        from kuaiqi.gui.credentials import CredentialResolution

        app = QApplication.instance() or QApplication([])
        window = LoginWindow()
        config = parse_config(
            {
                "strategies": [
                    {"type": "cp_combo", "threshold": 0.01},
                    {"type": "abs_spread", "threshold": 0.1, "selected": False},
                ]
            }
        )
        main_window = MainWindow(
            Path("config.toml"),
            config,
            CredentialResolution("u", "p", "TQSDK_USERNAME", "TQSDK_PASSWORD", "session"),
        )

        self.assertIsNotNone(app)
        self.assertEqual(window.windowTitle(), "KuaiQi 登录")
        self.assertEqual(main_window.config_editor.build_config().runtime.mode, "live")
        self.assertEqual(main_window.config_editor.strategies.columnCount(), 4)
        self.assertGreaterEqual(main_window.config_editor.strategies.minimumHeight(), 180)
        self.assertEqual(
            main_window.config_editor.strategies.item(0, 0).checkState(),
            Qt.CheckState.Checked,
        )
        self.assertEqual(
            main_window.config_editor.strategies.item(1, 0).checkState(),
            Qt.CheckState.Unchecked,
        )
        self.assertEqual(
            [strategy.type for strategy in main_window.config_editor.build_config().selected_strategies],
            ["cp_combo"],
        )
        main_window._set_running(True)
        self.assertTrue(main_window.config_editor.isEnabled())
        self.assertTrue(main_window.save_action.isEnabled())
        self.assertTrue(main_window.reload_action.isEnabled())
        self.assertFalse(main_window.start_button.isEnabled())
        self.assertTrue(main_window.stop_button.isEnabled())

        spin = _spin(0, 10)
        spin.setValue(5)
        event = _FakeWheelEvent()
        spin.wheelEvent(event)
        self.assertEqual(spin.value(), 5)
        self.assertTrue(event.ignored)

        double_spin = _double_spin()
        double_spin.setValue(5.5)
        event = _FakeWheelEvent()
        double_spin.wheelEvent(event)
        self.assertEqual(double_spin.value(), 5.5)
        self.assertTrue(event.ignored)


class _FakeWheelEvent:
    ignored = False

    def ignore(self) -> None:
        self.ignored = True


if __name__ == "__main__":
    unittest.main()
