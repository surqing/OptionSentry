from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from optionsentry.config import parse_config
from optionsentry.gui.credentials import CredentialResolution
from optionsentry.monitor_state import MonitorState


class _PendingWorker:
    def take_pending_updates(
        self,
        log_limit: int,
        alert_limit: int,
    ) -> tuple[None, tuple[()], int, tuple[()], int]:
        return None, (), 0, (), 0


class GuiMonitorStateTests(unittest.TestCase):
    def test_monitor_page_renders_states_in_chinese_and_preserves_failure(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        from optionsentry.gui.app import MainWindow

        app = QApplication.instance() or QApplication([])
        window = MainWindow(
            Path("config.toml"),
            parse_config(
                {
                    "schema_version": 1,
                    "strategies": [
                        {
                            "id": "cp",
                            "type": "cp_combo",
                            "name": "CP",
                            "enabled": True,
                            "parameters": {"min_value": 0.01, "max_value": float("inf")},
                        }
                    ],
                }
            ),
            CredentialResolution("u", "p", "TQSDK_USERNAME", "TQSDK_PASSWORD", "session"),
        )

        self.assertEqual(window.status_labels["status"].text(), "已停止")
        window._transition_monitor_state(MonitorState.STARTING)
        for state, label in (
            ("discovering", "发现合约"),
            ("compiling", "编译策略"),
            ("subscribing", "订阅行情"),
            ("waiting_data", "等待行情"),
            ("running", "运行中"),
        ):
            window._on_monitor_status(state)
            self.assertEqual(window.status_labels["status"].text(), label)

        with patch("optionsentry.gui.app.QMessageBox.critical") as critical:
            window._on_monitor_failed("boom")
        critical.assert_called_once()
        self.assertEqual(window.status_labels["status"].text(), "运行失败")

        window._on_monitor_thread_finished()
        self.assertEqual(window.status_labels["status"].text(), "运行失败")
        self.assertFalse(window._running)
        self.assertTrue(window.start_button.isEnabled())
        window.close()
        app.processEvents()

    def test_worker_completion_keeps_references_until_thread_really_finishes(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        from optionsentry.gui.app import MainWindow

        app = QApplication.instance() or QApplication([])
        window = MainWindow(
            Path("config.toml"),
            parse_config(
                {
                    "schema_version": 1,
                    "strategies": [
                        {
                            "id": "cp",
                            "type": "cp_combo",
                            "name": "CP",
                            "enabled": True,
                            "parameters": {"min_value": 0.01, "max_value": float("inf")},
                        }
                    ],
                }
            ),
            CredentialResolution("u", "p", "TQSDK_USERNAME", "TQSDK_PASSWORD", "session"),
        )
        worker = _PendingWorker()
        thread = object()
        window._monitor_worker = worker  # type: ignore[assignment]
        window._monitor_thread = thread  # type: ignore[assignment]
        window._transition_monitor_state(MonitorState.STARTING)
        window._set_running(True)

        window._on_monitor_finished(0)

        self.assertIs(window._monitor_worker, worker)
        self.assertIs(window._monitor_thread, thread)
        self.assertTrue(window._running)
        self.assertFalse(window.start_button.isEnabled())

        window._on_monitor_thread_finished()

        self.assertIsNone(window._monitor_worker)
        self.assertIsNone(window._monitor_thread)
        self.assertFalse(window._running)
        self.assertEqual(window.status_labels["status"].text(), "已停止")
        window.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
