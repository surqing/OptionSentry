from __future__ import annotations

import os
import tempfile
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
            APP_ICON_PATH,
            APP_NAME,
            LoginWindow,
            MainWindow,
            _apply_style,
            _double_spin,
            _format_status_timestamp,
            _format_table_timestamp,
            _spin,
            app_icon,
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
        self.assertTrue(APP_ICON_PATH.exists())
        self.assertFalse(app_icon().isNull())
        self.assertFalse(app_icon().pixmap(32, 32).isNull())
        self.assertEqual(window.windowTitle(), APP_NAME)
        self.assertEqual(main_window.windowTitle(), APP_NAME)
        self.assertFalse(window.windowIcon().isNull())
        self.assertFalse(main_window.windowIcon().isNull())
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
        for combo in (
            main_window.config_editor.runtime_mode,
            main_window.config_editor.universe_mode,
        ):
            combo.ensurePolished()
            combo.view().ensurePolished()
            self.assertGreater(combo.font().pointSize(), 0)
            self.assertEqual(combo.font().pixelSize(), -1)
            self.assertGreater(combo.view().font().pointSize(), 0)
            self.assertEqual(combo.view().font().pixelSize(), -1)

        self.assertEqual(main_window.alert_view.filter_labels(), ("全部策略", "cp_combo"))
        main_window.tabs.setCurrentIndex(2)
        main_window._on_alert(_alert_event("2026-06-26 23:41:05.000000"))
        self.assertEqual(main_window.tabs.currentIndex(), 2)
        self.assertEqual(main_window.alert_table.item(0, 0).text(), "2026-06-26 23:41:05")
        self.assertIn("策略名", _table_headers(main_window.alert_table))
        self.assertEqual(main_window.alert_table.item(0, 1).text(), "cp_combo")

        main_window._on_alert(_alert_event("2026-06-26 23:42:05", strategy_name="abs_spread"))
        self.assertEqual(main_window.alert_view.filter_labels(), ("全部策略", "cp_combo", "abs_spread"))
        self.assertEqual(main_window.alert_table.rowCount(), 2)
        main_window.alert_view.set_strategy_filter("cp_combo")
        self.assertNotIn("策略名", _table_headers(main_window.alert_table))
        self.assertEqual(main_window.alert_table.rowCount(), 1)
        self.assertEqual(main_window.alert_table.item(0, 1).text(), "1.00000000")
        main_window.alert_view.set_strategy_filter(None)
        self.assertIn("策略名", _table_headers(main_window.alert_table))
        self.assertEqual(main_window.alert_table.rowCount(), 2)

        main_window._on_cycle(
            RunnerCycle(
                cycle_count=1,
                timestamp="2026-06-26 23:41:05.987654",
                evaluations=(
                    _evaluation(strategy_name="cp_combo"),
                    _evaluation(strategy_name="abs_spread"),
                ),
                total_conditions=0,
                active_count=2,
                alerts=(),
                total_alerts=0,
                changed_count=0,
                compute_ms=0.0,
            )
        )
        self.assertEqual(main_window.status_labels["timestamp"].text(), "2026-06-26 23:41:05.9")
        self.assertIn("策略名", _table_headers(main_window.active_table))
        self.assertEqual(main_window.active_table.rowCount(), 2)
        main_window.active_view.set_strategy_filter("abs_spread")
        self.assertNotIn("策略名", _table_headers(main_window.active_table))
        self.assertEqual(main_window.active_table.rowCount(), 1)

        main_window.tabs.setCurrentIndex(1)
        for index in range(80):
            main_window._on_alert(_alert_event(f"t{index + 1}"))
        app.processEvents()
        scrollbar = main_window.alert_table.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 2)
        scrollbar.setValue(max(1, scrollbar.maximum() // 2))
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

        main_window.config_editor.runtime_mode.setCurrentText("live")
        event = _FakeWheelEvent()
        main_window.config_editor.runtime_mode.wheelEvent(event)
        self.assertEqual(main_window.config_editor.runtime_mode.currentText(), "live")
        self.assertTrue(event.ignored)

        main_window.config_editor.universe_mode.setCurrentText("all")
        event = _FakeWheelEvent()
        main_window.config_editor.universe_mode.wheelEvent(event)
        self.assertEqual(main_window.config_editor.universe_mode.currentText(), "all")
        self.assertTrue(event.ignored)

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

    def test_save_config_updates_monitor_config_status(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication

        from kuaiqi.config import load_config, parse_config
        from kuaiqi.gui.app import MainWindow
        from kuaiqi.gui.credentials import CredentialResolution

        app = QApplication.instance() or QApplication([])
        config = parse_config(
            {
                "strategies": [
                    {"type": "cp_combo", "threshold": 0.01},
                    {"type": "abs_spread", "threshold": 0.1, "selected": False},
                ]
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            main_window = MainWindow(
                config_path,
                config,
                CredentialResolution("u", "p", "TQSDK_USERNAME", "TQSDK_PASSWORD", "session"),
            )

            main_window.config_editor.runtime_mode.setCurrentText("backtest")
            main_window.config_editor.backtest_start.setText("2026-06-01")
            main_window.config_editor.backtest_end.setText("2026-06-02")
            main_window.config_editor.strategies.item(1, 0).setCheckState(Qt.CheckState.Checked)
            main_window._save_config()
            app.processEvents()

            self.assertEqual(main_window.config.runtime.mode, "backtest")
            self.assertEqual(load_config(config_path).runtime.mode, "backtest")
            self.assertEqual(main_window.status_labels["mode"].text(), "backtest")
            self.assertEqual(main_window.status_labels["strategies"].text(), "2")
            self.assertEqual(
                main_window.active_view.filter_labels(),
                ("全部策略", "cp_combo", "abs_spread"),
            )
            self.assertEqual(
                main_window.alert_view.filter_labels(),
                ("全部策略", "cp_combo", "abs_spread"),
            )
            main_window.close()


def _alert_event(timestamp: str, strategy_name: str = "cp_combo") -> AlertEvent:
    return AlertEvent(
        timestamp=timestamp,
        evaluation=_evaluation(strategy_name=strategy_name, suffix=timestamp),
    )


def _evaluation(strategy_name: str = "cp_combo", suffix: str = "eval") -> ConditionEvaluation:
    return ConditionEvaluation(
        key=f"key:{strategy_name}:{suffix}",
        strategy_name=strategy_name,
        active=True,
        value=1.0,
        threshold=0.1,
        symbols=("SHFE.au2608C600", "SHFE.au2608P600", "SHFE.au2608"),
        message=f"message {suffix}",
    )


def _table_headers(table) -> tuple[str, ...]:
    return tuple(
        table.horizontalHeaderItem(column).text()
        for column in range(table.columnCount())
    )


class _FakeWheelEvent:
    ignored = False

    def ignore(self) -> None:
        self.ignored = True


if __name__ == "__main__":
    unittest.main()
