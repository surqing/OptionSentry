from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            TOAST_DURATION_MS,
            LoginWindow,
            MainWindow,
            SortableHeader,
            _apply_style,
            _double_spin,
            _friendly_login_error,
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
        window.show()
        self.assertTrue(window.login_button.isDefault())
        self.assertEqual(window.remember_me.text(), "记住我")
        window._show_login_error("ConfigError: TqSdk username and password must be both filled or both empty.")
        app.processEvents()
        self.assertEqual(window.error_label.text(), "账号和密码需要同时填写；如果都留空，将读取已记住的账号或环境变量。")
        self.assertEqual(window._toast._duration_ms, TOAST_DURATION_MS)
        self.assertEqual(window._toast._label.text(), window.error_label.text())
        self.assertTrue(bool(window._toast.windowFlags() & Qt.WindowType.FramelessWindowHint))
        self.assertIsNotNone(window._toast.graphicsEffect())
        self.assertEqual(
            _friendly_login_error("Exception: 用户权限认证失败 (401,{'error': 'invalid_grant'})"),
            "TqSdk 登录失败，请检查账号和密码。",
        )
        window.username.setText("alice")
        window.password.clear()
        window.username.returnPressed.emit()
        app.processEvents()
        self.assertEqual(window.error_label.text(), "账号和密码需要同时填写；如果都留空，将读取已记住的账号或环境变量。")
        window.username.clear()
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
        self.assertEqual(main_window.active_view.title(), "当前活跃预警记录")
        self.assertEqual(main_window.manual_active_refresh_button.text(), "手动刷新")
        self.assertEqual(main_window.auto_active_refresh.text(), "自动刷新")
        self.assertTrue(main_window.auto_active_refresh.isChecked())
        self.assertEqual(main_window.active_refresh_interval.currentData(), 10)
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
            self.assertIsInstance(table.horizontalHeader(), SortableHeader)
            self.assertTrue(table.horizontalHeader().sectionsClickable())
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
        self.assertEqual(main_window.active_table.item(0, 2).text(), "1.00000000")
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

    def test_table_headers_sort_rows_by_column_content(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        from kuaiqi.config import parse_config
        from kuaiqi.gui.app import MainWindow
        from kuaiqi.gui.credentials import CredentialResolution

        app = QApplication.instance() or QApplication([])
        config = parse_config(
            {
                "strategies": [
                    {"type": "cp_combo", "threshold": 0.01},
                    {"type": "abs_spread", "threshold": 0.1},
                ]
            }
        )
        main_window = MainWindow(
            Path("config.toml"),
            config,
            CredentialResolution("u", "p", "TQSDK_USERNAME", "TQSDK_PASSWORD", "session"),
        )
        main_window._on_alert(_alert_event("t1", value=10.0))
        main_window._on_alert(_alert_event("t2", value=2.0))
        main_window._on_alert(_alert_event("t3", value=-1.0))

        main_window.alert_table.horizontalHeader().sectionClicked.emit(2)
        self.assertEqual(
            _column_texts(main_window.alert_table, 2),
            ("-1.00000000", "2.00000000", "10.00000000"),
        )

        main_window.alert_table.horizontalHeader().sectionClicked.emit(2)
        self.assertEqual(
            _column_texts(main_window.alert_table, 2),
            ("10.00000000", "2.00000000", "-1.00000000"),
        )

        main_window.config_editor.strategies.horizontalHeader().sectionClicked.emit(2)
        self.assertEqual(_column_texts(main_window.config_editor.strategies, 2), ("0.01", "0.1"))
        main_window.config_editor.strategies.horizontalHeader().sectionClicked.emit(2)
        self.assertEqual(_column_texts(main_window.config_editor.strategies, 2), ("0.1", "0.01"))
        app.processEvents()
        main_window.close()

    def test_table_headers_filter_rows_by_numeric_range(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        from kuaiqi.config import parse_config
        from kuaiqi.gui.app import MainWindow, _set_table_filter_text
        from kuaiqi.gui.credentials import CredentialResolution

        app = QApplication.instance() or QApplication([])
        config = parse_config({"strategies": [{"type": "cp_combo", "threshold": 0.01}]})
        main_window = MainWindow(
            Path("config.toml"),
            config,
            CredentialResolution("u", "p", "TQSDK_USERNAME", "TQSDK_PASSWORD", "session"),
        )
        for value in (7.0, 8.0, 9.0, 10.0, 11.0):
            main_window._on_alert(_alert_event(f"t{value}", value=value))

        for expression in ("8 10", "8-10", "8,10", "8，10", "8~10"):
            _set_table_filter_text(main_window.alert_table, 2, expression)
            self.assertEqual(
                _visible_column_texts(main_window.alert_table, 2),
                ("8.00000000", "9.00000000", "10.00000000"),
            )

        main_window._on_alert(_alert_event("inside", value=9.5))
        main_window._on_alert(_alert_event("outside", value=12.0))
        self.assertEqual(
            _visible_column_texts(main_window.alert_table, 2),
            ("8.00000000", "9.00000000", "10.00000000", "9.50000000"),
        )

        _set_table_filter_text(main_window.alert_table, 2, "")
        self.assertEqual(main_window.alert_table.rowCount(), 7)
        self.assertEqual(len(_visible_column_texts(main_window.alert_table, 2)), 7)
        app.processEvents()
        main_window.close()

    def test_active_table_auto_refresh_uses_cached_cycles(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        from kuaiqi.config import parse_config
        from kuaiqi.gui.app import MainWindow
        from kuaiqi.gui.credentials import CredentialResolution

        app = QApplication.instance() or QApplication([])
        config = parse_config(
            {
                "gui": {
                    "active_alerts": {
                        "auto_refresh": False,
                        "refresh_interval_seconds": 180,
                    }
                },
                "strategies": [{"type": "cp_combo", "threshold": 0.01}],
            }
        )
        main_window = MainWindow(
            Path("config.toml"),
            config,
            CredentialResolution("u", "p", "TQSDK_USERNAME", "TQSDK_PASSWORD", "session"),
        )

        self.assertFalse(main_window.auto_active_refresh.isChecked())
        self.assertEqual(main_window.active_refresh_interval.currentData(), 180)
        self.assertFalse(main_window._active_auto_refresh_timer.isActive())

        main_window._on_cycle(_cycle(1, value=1.0))
        self.assertEqual(main_window.active_table.rowCount(), 0)

        main_window.auto_active_refresh.setChecked(True)
        self.assertTrue(main_window._active_auto_refresh_timer.isActive())
        self.assertEqual(main_window._active_auto_refresh_timer.interval(), 180000)
        self.assertEqual(main_window.active_table.item(0, 2).text(), "1.00000000")

        main_window._on_cycle(_cycle(2, value=2.0))
        self.assertEqual(main_window.active_table.item(0, 2).text(), "1.00000000")

        main_window.active_refresh_interval.setCurrentIndex(0)
        self.assertEqual(main_window._active_auto_refresh_timer.interval(), 10000)
        self.assertEqual(main_window.active_table.item(0, 2).text(), "2.00000000")

        main_window.auto_active_refresh.setChecked(False)
        self.assertFalse(main_window._active_auto_refresh_timer.isActive())
        main_window._on_cycle(_cycle(3, value=3.0))
        self.assertEqual(main_window.active_table.item(0, 2).text(), "2.00000000")
        app.processEvents()
        main_window.close()

    def test_active_table_manual_refresh_waits_for_next_cycle_and_times_out(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        from kuaiqi.config import parse_config
        from kuaiqi.gui.app import MainWindow
        from kuaiqi.gui.credentials import CredentialResolution

        app = QApplication.instance() or QApplication([])
        config = parse_config(
            {
                "gui": {"active_alerts": {"auto_refresh": False}},
                "strategies": [{"type": "cp_combo", "threshold": 0.01}],
            }
        )
        main_window = MainWindow(
            Path("config.toml"),
            config,
            CredentialResolution("u", "p", "TQSDK_USERNAME", "TQSDK_PASSWORD", "session"),
        )

        with patch("kuaiqi.gui.app.QMessageBox.information") as information:
            main_window._request_active_manual_refresh()
        information.assert_called_once()
        self.assertFalse(main_window._manual_active_refresh_pending)

        main_window._set_running(True)
        main_window._on_cycle(_cycle(1, value=1.0))
        self.assertEqual(main_window.active_table.rowCount(), 0)
        main_window._request_active_manual_refresh()
        self.assertTrue(main_window._manual_active_refresh_pending)
        self.assertFalse(main_window.manual_active_refresh_button.isEnabled())
        self.assertTrue(main_window._manual_active_refresh_timeout.isActive())

        main_window._on_cycle(_cycle(2, value=4.0))
        self.assertFalse(main_window._manual_active_refresh_pending)
        self.assertTrue(main_window.manual_active_refresh_button.isEnabled())
        self.assertEqual(main_window.manual_active_refresh_button.text(), "手动刷新")
        self.assertEqual(main_window.active_table.item(0, 2).text(), "4.00000000")

        main_window._request_active_manual_refresh()
        with patch("kuaiqi.gui.app.QMessageBox.warning") as warning:
            main_window._on_active_manual_refresh_timeout()
        warning.assert_called_once()
        self.assertFalse(main_window._manual_active_refresh_pending)
        self.assertTrue(main_window.manual_active_refresh_button.isEnabled())
        main_window._set_running(False)
        app.processEvents()
        main_window.close()

    def test_login_success_remembers_credentials_and_shows_toast(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        from kuaiqi.config import load_config, parse_config
        from kuaiqi.gui.app import LoginWindow, _apply_style
        from kuaiqi.gui.credentials import CredentialResolution

        app = QApplication.instance() or QApplication([])
        _apply_style(app)
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                "[[strategies]]\n"
                'type = "cp_combo"\n'
                "threshold = 0.01\n",
                encoding="utf-8",
            )
            config = parse_config({"strategies": [{"type": "cp_combo", "threshold": 0.01}]})
            window = LoginWindow()
            window.config_path.setText(str(config_path))
            window.username.setText("alice")
            window.password.setText("secret")
            window.remember_me.setChecked(True)

            window._on_login_success(
                config_path,
                config,
                CredentialResolution("alice", "secret", "TQSDK_USERNAME", "TQSDK_PASSWORD", "session"),
            )
            app.processEvents()

            saved = load_config(config_path)
            self.assertEqual(saved.tqsdk.username, "alice")
            self.assertEqual(saved.tqsdk.password, "secret")
            self.assertIsNotNone(window._main_window)
            self.assertEqual(window._main_window._toast._label.text(), "登录成功")
            self.assertEqual(window._main_window.config_editor.build_config().tqsdk.username, "alice")
            self.assertEqual(window._main_window.config_editor.build_config().tqsdk.password, "secret")

            next_window = LoginWindow()
            next_window.config_path.setText(str(config_path))
            next_window._fill_remembered_credentials()
            self.assertEqual(next_window.username.text(), "alice")
            self.assertEqual(next_window.password.text(), "secret")
            self.assertTrue(next_window.remember_me.isChecked())

            window._main_window.close()
            next_window.close()

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

            self.assertEqual(main_window._toast._label.text(), "保存成功")
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

            config_path.write_text(
                "[runtime]\n"
                'mode = "live"\n'
                'price_basis = "last"\n\n'
                "[[strategies]]\n"
                'type = "cp_combo"\n'
                "threshold = 0.01\n",
                encoding="utf-8",
            )
            main_window._reload_config()
            app.processEvents()

            self.assertEqual(main_window._toast._label.text(), "加载成功")
            self.assertEqual(main_window.config.runtime.mode, "live")
            self.assertEqual(main_window.status_labels["mode"].text(), "live")
            self.assertEqual(main_window.status_labels["strategies"].text(), "1")
            self.assertEqual(main_window.active_view.filter_labels(), ("全部策略", "cp_combo"))
            self.assertEqual(main_window.alert_view.filter_labels(), ("全部策略", "cp_combo"))
            main_window.close()


def _alert_event(timestamp: str, strategy_name: str = "cp_combo", value: float = 1.0) -> AlertEvent:
    return AlertEvent(
        timestamp=timestamp,
        evaluation=_evaluation(strategy_name=strategy_name, suffix=timestamp, value=value),
    )


def _evaluation(strategy_name: str = "cp_combo", suffix: str = "eval", value: float = 1.0) -> ConditionEvaluation:
    return ConditionEvaluation(
        key=f"key:{strategy_name}:{suffix}",
        strategy_name=strategy_name,
        active=True,
        value=value,
        threshold=0.1,
        symbols=("SHFE.au2608C600", "SHFE.au2608P600", "SHFE.au2608"),
        message=f"message {suffix}",
    )


def _cycle(cycle_count: int, value: float = 1.0, strategy_name: str = "cp_combo") -> object:
    from kuaiqi.runner import RunnerCycle

    return RunnerCycle(
        cycle_count=cycle_count,
        timestamp=f"t{cycle_count}",
        evaluations=(_evaluation(strategy_name=strategy_name, suffix=f"cycle{cycle_count}", value=value),),
        total_conditions=1,
        active_count=1,
        alerts=(),
        total_alerts=0,
        changed_count=1,
        compute_ms=0.0,
    )


def _table_headers(table) -> tuple[str, ...]:
    return tuple(
        table.horizontalHeaderItem(column).text()
        for column in range(table.columnCount())
    )


def _column_texts(table, column: int) -> tuple[str, ...]:
    return tuple(table.item(row, column).text() for row in range(table.rowCount()))


def _visible_column_texts(table, column: int) -> tuple[str, ...]:
    return tuple(
        table.item(row, column).text()
        for row in range(table.rowCount())
        if not table.isRowHidden(row)
    )


class _FakeWheelEvent:
    ignored = False

    def ignore(self) -> None:
        self.ignored = True


if __name__ == "__main__":
    unittest.main()
