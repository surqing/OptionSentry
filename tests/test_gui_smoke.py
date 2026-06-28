from __future__ import annotations

import os
import unittest
from pathlib import Path

from kuaiqi.models import AlertEvent, ConditionEvaluation


class GuiSmokeTests(unittest.TestCase):
    def test_pyqt_login_window_constructs_offscreen(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication, QHeaderView, QToolBar
        from PyQt6.QtCore import Qt

        from kuaiqi.config import parse_config
        from kuaiqi.gui.app import (
            LoginWindow,
            MainWindow,
            _apply_style,
            _double_spin,
            _format_status_timestamp,
            _format_table_timestamp,
            _spin,
        )
        from kuaiqi.gui.credentials import CredentialResolution
        from kuaiqi.runner import RunnerCycle

        app = QApplication.instance() or QApplication([])
        _apply_style(app)
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
        main_window.show()
        app.processEvents()

        self.assertIsNotNone(app)
        self.assertEqual(window.windowTitle(), "KuaiQi 登录")
        self.assertEqual(main_window.config_editor.build_config().runtime.mode, "live")
        self.assertEqual(main_window.findChildren(QToolBar), [])
        self.assertIs(main_window.save_action, main_window.config_editor.save_button)
        self.assertIs(main_window.reload_action, main_window.config_editor.reload_button)
        self.assertEqual(main_window.config_editor.save_button.text(), "保存配置")
        self.assertEqual(main_window.config_editor.reload_button.text(), "重新加载")
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
        self.assertIn("QTableWidget::item:hover", app.styleSheet())
        self.assertEqual(
            _format_table_timestamp("2026-06-26 23:41:05.000000"),
            "2026-06-26 23:41:05",
        )
        self.assertEqual(
            _format_status_timestamp("2026-06-26 23:41:05.123456"),
            "2026-06-26 23:41:05.1",
        )
        self.assertEqual(
            _format_status_timestamp("2026-06-26 23:41:05"),
            "2026-06-26 23:41:05.0",
        )
        for table in (
            main_window.active_table,
            main_window.alert_table,
            main_window.config_editor.strategies,
        ):
            self.assertEqual(
                table.horizontalHeader().sectionResizeMode(0),
                QHeaderView.ResizeMode.Interactive,
            )

        main_window.tabs.setCurrentIndex(2)
        main_window._on_alert(_alert_event("2026-06-26 23:41:05.000000"))
        self.assertEqual(main_window.tabs.currentIndex(), 2)
        self.assertEqual(main_window.alert_table.item(0, 0).text(), "2026-06-26 23:41:05")

        main_window._on_cycle(
            RunnerCycle(
                cycle_count=1,
                timestamp="2026-06-26 23:41:05.987654",
                evaluations=(),
                total_conditions=0,
                active_count=0,
                alerts=(),
                total_alerts=0,
                changed_count=0,
                compute_ms=0.0,
            )
        )
        self.assertEqual(main_window.status_labels["timestamp"].text(), "2026-06-26 23:41:05.9")

        main_window.tabs.setCurrentIndex(1)
        for index in range(80):
            main_window._on_alert(_alert_event(f"t{index + 1}"))
        app.processEvents()
        scrollbar = main_window.alert_table.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        scrollbar.setValue(0)
        app.processEvents()
        history_position = scrollbar.value()
        main_window.tabs.setCurrentIndex(3)
        main_window._on_alert(_alert_event("later"))
        app.processEvents()
        self.assertEqual(main_window.tabs.currentIndex(), 3)
        self.assertEqual(scrollbar.value(), history_position)

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
        main_window.close()
        window.close()


def _alert_event(timestamp: str) -> AlertEvent:
    return AlertEvent(
        timestamp=timestamp,
        evaluation=ConditionEvaluation(
            key=f"key:{timestamp}",
            strategy_name="cp_combo",
            active=True,
            value=1.0,
            threshold=0.1,
            symbols=("SHFE.au2608C600", "SHFE.au2608P600", "SHFE.au2608"),
            message=f"message {timestamp}",
        ),
    )


class _FakeWheelEvent:
    ignored = False

    def ignore(self) -> None:
        self.ignored = True


if __name__ == "__main__":
    unittest.main()
