from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import math
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from PyQt6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QRect, QTimer, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGraphicsOpacityEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from optionsentry.config import (
    AppConfig,
    ActiveAlertsViewConfig,
    ConfigError,
    SUPPORTED_STRATEGY_TYPES,
    load_config,
    strategy_display_name,
    strategy_type_display_name,
)
from optionsentry.gui.config_store import data_to_config, save_config
from optionsentry.gui.credentials import CredentialResolution, load_and_validate_login
from optionsentry.gui.runner_adapter import GuiRunSignals, build_gui_runner
from optionsentry.models import AlertEvent, ConditionEvaluation, Universe
from optionsentry.runner import RunnerCycle
from optionsentry.strategies import (
    CALL_MONEYNESS_METRIC,
    PUT_MONEYNESS_METRIC,
    SPREAD_A_MONEYNESS_METRIC,
    SPREAD_AVG_MONEYNESS_METRIC,
    SPREAD_B_MONEYNESS_METRIC,
)


APP_NAME = "OptionSentry"
APP_ICON_PATH = Path(__file__).with_name("assets") / "app_icon.svg"
ALL_STRATEGIES_LABEL = "全部策略"
ACTIVE_REFRESH_OPTIONS = (
    ("10s", 10),
    ("30s", 30),
    ("1min", 60),
    ("3min", 180),
    ("5min", 300),
    ("10min", 600),
)
MANUAL_ACTIVE_REFRESH_TIMEOUT_MS = 3000
SORT_COLUMN_PROPERTY = "optionsentry_sort_column"
SORT_LABEL_PROPERTY = "optionsentry_sort_label"
SORT_ORDER_PROPERTY = "optionsentry_sort_order"
FILTERS_PROPERTY = "optionsentry_filters"
SORT_ROLE = Qt.ItemDataRole.UserRole
TOAST_DURATION_MS = 1500
TOAST_FADE_MS = 150
ALERT_SOUND_BEEP_INTERVAL_MS = 700
CP_NEGATIVE_VALUE_COLOR = "#d8ecdf"
CP_POSITIVE_VALUE_COLOR = "#f1d7d2"


def app_icon() -> QIcon:
    return QIcon(str(APP_ICON_PATH))


class LoginWorker(QObject):
    finished = pyqtSignal(object, object, object)
    failed = pyqtSignal(str)

    def __init__(self, config_path: Path, username: str, password: str) -> None:
        super().__init__()
        self.config_path = config_path
        self.username = username
        self.password = password

    def run(self) -> None:
        try:
            config, credentials = load_and_validate_login(
                self.config_path,
                self.username,
                self.password,
            )
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit(self.config_path, config, credentials)


class ToastPopup(QWidget):
    def __init__(self, parent: QWidget, duration_ms: int = TOAST_DURATION_MS) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.ToolTip
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._duration_ms = duration_ms
        self._last_duration_ms = duration_ms
        self._fade_ms = min(TOAST_FADE_MS, max(duration_ms // 2, 0))
        self._sequence = 0
        self.setObjectName("toastPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("")
        self._label.setObjectName("toastLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setMinimumWidth(260)
        self._label.setMaximumWidth(440)
        layout.addWidget(self._label)

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._fade_in = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_in.setDuration(self._fade_ms)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._fade_out = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_out.setDuration(self._fade_ms)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self.hide)

    def show_message(self, message: str, duration_ms: int | None = None) -> None:
        message_duration_ms = max(0, int(duration_ms if duration_ms is not None else self._duration_ms))
        self._last_duration_ms = message_duration_ms
        fade_ms = min(TOAST_FADE_MS, max(message_duration_ms // 2, 0))
        self._fade_in.setDuration(fade_ms)
        self._fade_out.setDuration(fade_ms)
        self._sequence += 1
        sequence = self._sequence
        self._fade_in.stop()
        self._fade_out.stop()
        try:
            self._fade_in.finished.disconnect()
        except TypeError:
            pass
        self._label.setText(message)
        self.adjustSize()
        self._move_near_parent()
        self._opacity.setOpacity(0.0)
        self.show()
        self.raise_()
        self._fade_in.finished.connect(
            lambda sequence=sequence, duration_ms=message_duration_ms, fade_ms=fade_ms: self._hold_then_fade(
                sequence,
                duration_ms,
                fade_ms,
            )
        )
        self._fade_in.start()

    def _hold_then_fade(self, sequence: int, duration_ms: int, fade_ms: int) -> None:
        try:
            self._fade_in.finished.disconnect()
        except TypeError:
            pass
        hold_ms = max(0, duration_ms - (fade_ms * 2))
        QTimer.singleShot(hold_ms, lambda: self._fade_out_if_current(sequence))

    def _fade_out_if_current(self, sequence: int) -> None:
        if sequence != self._sequence:
            return
        self._fade_out.start()

    def _move_near_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        parent_top_left = parent.mapToGlobal(parent.rect().topLeft())
        x = parent_top_left.x() + max(12, (parent.width() - self.width()) // 2)
        y = parent_top_left.y() + min(88, max(24, parent.height() // 5))
        self.move(x, y)


def _friendly_login_error(message: str) -> str:
    detail = _strip_exception_name(message)
    lowered = detail.lower()
    if "username and password must be both filled or both empty" in lowered:
        return "账号和密码需要同时填写；如果都留空，将读取已记住的账号或环境变量。"
    if detail.startswith("TqSdk auth requires "):
        env_names = detail.removeprefix("TqSdk auth requires ").rstrip(".")
        env_names = env_names.replace(" and ", " / ")
        return f"请输入 TqSdk 账号和密码，或设置已记住的账号/环境变量 {env_names}。"
    if "不能为空" in detail:
        return "请输入 TqSdk 账号和密码。"
    if "用户权限认证失败" in detail or "认证失败" in detail:
        return "TqSdk 登录失败，请检查账号和密码。"
    if "auth" in lowered and ("password" in lowered or "username" in lowered):
        return "TqSdk 登录失败，请检查账号和密码。"
    return detail or "登录失败，请检查账号和密码。"


def _strip_exception_name(message: str) -> str:
    prefix, separator, suffix = message.strip().partition(": ")
    if separator and (prefix == "Exception" or prefix.endswith("Error")):
        return suffix.strip()
    return message.strip()


def _remember_tqsdk_credentials(
    config_path: Path,
    config: AppConfig,
    credentials: CredentialResolution,
) -> AppConfig:
    remembered = replace(
        config,
        tqsdk=replace(
            config.tqsdk,
            username=credentials.username,
            password=credentials.password,
        ),
    )
    save_config(config_path, remembered)
    return remembered


class MonitorWorker(QObject):
    status = pyqtSignal(str)
    log = pyqtSignal(str)
    universe = pyqtSignal(object)
    compiled = pyqtSignal(int, int)
    cycle = pyqtSignal(object)
    alert = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, config: AppConfig, config_path: Path) -> None:
        super().__init__()
        self.config = config
        self.config_path = config_path
        self._context = None
        self._stop_before_start = False

    def run(self) -> None:
        try:
            self._context = build_gui_runner(
                self.config,
                GuiRunSignals(
                    on_status=self.status.emit,
                    on_log=self.log.emit,
                    on_universe=self.universe.emit,
                    on_compiled=self.compiled.emit,
                    on_cycle=self.cycle.emit,
                    on_alert=self.alert.emit,
                ),
                self.config_path,
            )
            if self._stop_before_start:
                self._context.stop()
            alert_count = self._context.runner.run()
        except Exception as exc:
            if "stopped by user" not in str(exc).lower():
                self.failed.emit(f"{type(exc).__name__}: {exc}")
            alert_count = -1
        finally:
            context = self._context
            if context is not None and context.gui_log_handler is not None:
                context.logger.removeHandler(context.gui_log_handler)
            self.finished.emit(alert_count)

    def stop(self) -> None:
        self._stop_before_start = True
        if self._context is not None:
            self._context.stop()


class LoginWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(480)
        self._thread: QThread | None = None
        self._worker: LoginWorker | None = None
        self._main_window: MainWindow | None = None
        self._build_ui()
        self._toast = ToastPopup(self)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel(APP_NAME)
        title.setObjectName("windowTitle")
        subtitle = QLabel("TqSdk 登录")
        subtitle.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        form_box = QGroupBox("登录")
        form = QFormLayout(form_box)
        self.config_path = QLineEdit(str(_default_config_path()))
        browse = QToolButton()
        browse.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        browse.setToolTip("选择配置文件")
        browse.clicked.connect(self._browse_config)
        config_row = QHBoxLayout()
        config_row.addWidget(self.config_path, 1)
        config_row.addWidget(browse)
        form.addRow("配置文件", config_row)

        self.username = QLineEdit()
        self.username.setPlaceholderText("留空则读取配置或 username_env")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("留空则读取配置或 password_env")
        self.username.returnPressed.connect(self._submit_login)
        self.password.returnPressed.connect(self._submit_login)
        self.config_path.returnPressed.connect(self._submit_login)
        form.addRow("账号", self.username)
        form.addRow("密码", self.password)
        layout.addWidget(form_box)

        self.error_label = QLabel("")
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        row = QHBoxLayout()
        row.addStretch(1)
        self.login_button = QPushButton("登录")
        self.login_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        self.login_button.setDefault(True)
        self.login_button.setAutoDefault(True)
        self.login_button.clicked.connect(self._login)
        self.remember_me = QCheckBox("记住我")
        row.addWidget(self.remember_me)
        row.addWidget(self.login_button)
        layout.addLayout(row)
        self._fill_remembered_credentials()

    def _browse_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择配置文件", ".", "TOML (*.toml);;All Files (*)")
        if path:
            self.config_path.setText(path)
            self._fill_remembered_credentials()

    def _submit_login(self) -> None:
        if self.login_button.isEnabled():
            self._login()

    def _login(self) -> None:
        self.error_label.setText("")
        username = self.username.text()
        password = self.password.text()
        if bool(username.strip()) != bool(password.strip()):
            self._show_login_error("ConfigError: TqSdk username and password must be both filled or both empty.")
            return
        path = Path(self.config_path.text().strip() or _default_config_path())
        self.login_button.setEnabled(False)
        self.login_button.setText("登录中")
        self._thread = QThread(self)
        self._worker = LoginWorker(path, username, password)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_login_success)
        self._worker.failed.connect(self._on_login_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_login_success(
        self,
        config_path: Path,
        config: AppConfig,
        credentials: CredentialResolution,
    ) -> None:
        self.login_button.setEnabled(True)
        self.login_button.setText("登录")
        if self.remember_me.isChecked():
            try:
                config = _remember_tqsdk_credentials(config_path, config, credentials)
            except Exception as exc:
                self._show_login_error(f"保存账号密码失败: {exc}")
                return
        self._main_window = MainWindow(config_path, config, credentials)
        self._main_window.show()
        self._main_window.show_toast("登录成功")
        self.close()

    def _on_login_failed(self, message: str) -> None:
        self.login_button.setEnabled(True)
        self.login_button.setText("登录")
        self._show_login_error(message)

    def _show_login_error(self, message: str) -> None:
        friendly_message = _friendly_login_error(message)
        self.error_label.setText(friendly_message)
        self._toast.show_message(friendly_message)

    def _fill_remembered_credentials(self) -> None:
        try:
            config = load_config(Path(self.config_path.text().strip() or _default_config_path()))
        except Exception:
            return
        if config.tqsdk.username and config.tqsdk.password:
            self.username.setText(config.tqsdk.username)
            self.password.setText(config.tqsdk.password)
            self.remember_me.setChecked(True)


class MainWindow(QMainWindow):
    def __init__(
        self,
        config_path: Path,
        config: AppConfig,
        credentials: CredentialResolution,
    ) -> None:
        super().__init__()
        self.config_path = config_path
        self.config = config
        self.credentials = credentials
        self._monitor_thread: QThread | None = None
        self._monitor_worker: MonitorWorker | None = None
        self._monitor_config: AppConfig | None = None
        self._running = False
        self._active_records_by_key: dict[str, _EvaluationRecord] = {}
        self._latest_active_cycle_count = 0
        self._last_displayed_active_cycle_count = 0
        self._manual_active_refresh_pending = False
        self._applying_active_refresh_config = False
        self._active_auto_refresh_timer = QTimer(self)
        self._active_auto_refresh_timer.timeout.connect(self._refresh_active_table_from_cache)
        self._manual_active_refresh_timeout = QTimer(self)
        self._manual_active_refresh_timeout.setSingleShot(True)
        self._manual_active_refresh_timeout.timeout.connect(self._on_active_manual_refresh_timeout)
        self._alert_sound_until = 0.0
        self._alert_sound_timer = QTimer(self)
        self._alert_sound_timer.timeout.connect(self._on_alert_sound_timer)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1180, 760)
        self._build_ui()
        self._toast = ToastPopup(self)
        self._load_config_into_editor(config)
        self._set_running(False)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        top = QHBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("windowTitle")
        top.addWidget(title)
        top.addStretch(1)
        self.start_button = QPushButton("启动")
        self.start_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.start_button.clicked.connect(self._start_monitor)
        self.stop_button = QPushButton("停止")
        self.stop_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.stop_button.clicked.connect(self._stop_monitor)
        top.addWidget(self.start_button)
        top.addWidget(self.stop_button)
        layout.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._monitor_tab(), "监控")
        self.tabs.addTab(self._alerts_tab(), "预警")
        self.config_editor = ConfigEditor()
        self.config_editor.set_config_path(self.config_path)
        self.config_editor.save_button.clicked.connect(self._save_config)
        self.config_editor.reload_button.clicked.connect(self._reload_config)
        self.tabs.addTab(self.config_editor, "配置")
        self.tabs.addTab(self._logs_tab(), "日志")
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)
        self.save_action = self.config_editor.save_button
        self.reload_action = self.config_editor.reload_button

    def show_toast(self, message: str) -> None:
        self._toast.show_message(message)

    def _monitor_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        status_box = QGroupBox("状态")
        grid = QGridLayout(status_box)
        self.status_labels: dict[str, QLabel] = {}
        fields = (
            ("运行状态", "status"),
            ("模式", "mode"),
            ("配置", "config_path"),
            ("凭据来源", "credential_source"),
            ("期权数", "options"),
            ("期货数", "futures"),
            ("价格合约", "price_symbols"),
            ("策略", "strategies"),
            ("条件数", "conditions"),
            ("周期", "cycles"),
            ("活跃预警", "active"),
            ("累计预警", "alerts"),
            ("最新时间", "timestamp"),
        )
        for index, (label, key) in enumerate(fields):
            row = index // 3
            column = (index % 3) * 2
            grid.addWidget(QLabel(label), row, column)
            value = QLabel("-")
            value.setObjectName("statusValue")
            self.status_labels[key] = value
            grid.addWidget(value, row, column + 1)
        layout.addWidget(status_box)

        self.active_view = StrategyEvaluationTable("当前活跃预警记录", show_moneyness_columns=True)
        self.manual_active_refresh_button = QPushButton("手动刷新")
        self.manual_active_refresh_button.clicked.connect(self._request_active_manual_refresh)
        self.auto_active_refresh = QCheckBox("自动刷新")
        self.auto_active_refresh.stateChanged.connect(self._on_active_auto_refresh_changed)
        self.active_refresh_interval = NoWheelComboBox()
        for label, seconds in ACTIVE_REFRESH_OPTIONS:
            self.active_refresh_interval.addItem(label, seconds)
        self.active_refresh_interval.currentIndexChanged.connect(self._on_active_refresh_interval_changed)
        self.active_view.add_toolbar_widget(self.manual_active_refresh_button)
        self.active_view.add_toolbar_widget(self.auto_active_refresh)
        self.active_view.add_toolbar_widget(self.active_refresh_interval)
        self.active_table = self.active_view.table
        layout.addWidget(self.active_view, 1)
        return tab

    def _alerts_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.alert_view = StrategyEvaluationTable("预警记录")
        self.alert_table = self.alert_view.table
        layout.addWidget(self.alert_view)
        return tab

    def _logs_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.log_view)
        return tab

    def _load_config_into_editor(self, config: AppConfig) -> None:
        self.config_editor.set_config(config)
        self._set_active_refresh_config(config.gui.active_alerts)
        self._sync_config_summary(config)

    def _sync_config_summary(self, config: AppConfig) -> None:
        self._set_status("mode", config.runtime.mode)
        self._set_status("config_path", str(self.config_path))
        self._set_status("credential_source", self.credentials.source)
        self._set_status("strategies", str(len(config.selected_strategies)))
        self._set_strategy_filters(config)

    def _start_monitor(self) -> None:
        if self._running:
            return
        try:
            monitor_config = self._config_with_active_refresh(self.config_editor.build_config())
        except Exception as exc:
            QMessageBox.warning(self, "配置错误", str(exc))
            return
        self.config = monitor_config
        self._monitor_config = monitor_config
        self._sync_config_summary(self.config)
        self.alert_view.clear_records()
        self._reset_active_records()
        self.active_view.clear_records()
        self._append_log("Starting monitor")
        self._set_running(True)
        self._monitor_thread = QThread(self)
        self._monitor_worker = MonitorWorker(monitor_config, self.config_path)
        self._monitor_worker.moveToThread(self._monitor_thread)
        self._monitor_thread.started.connect(self._monitor_worker.run)
        self._monitor_worker.status.connect(lambda status: self._set_status("status", status))
        self._monitor_worker.log.connect(self._append_log)
        self._monitor_worker.universe.connect(self._on_universe)
        self._monitor_worker.compiled.connect(self._on_compiled)
        self._monitor_worker.cycle.connect(self._on_cycle)
        self._monitor_worker.alert.connect(self._on_alert)
        self._monitor_worker.failed.connect(self._on_monitor_failed)
        self._monitor_worker.finished.connect(self._on_monitor_finished)
        self._monitor_worker.finished.connect(self._monitor_thread.quit)
        self._monitor_thread.finished.connect(self._monitor_worker.deleteLater)
        self._monitor_thread.finished.connect(self._monitor_thread.deleteLater)
        self._monitor_thread.start()

    def _stop_monitor(self) -> None:
        self._cancel_active_manual_refresh()
        if self._monitor_worker is not None:
            self._set_status("status", "stopping")
            self._monitor_worker.stop()
        self.stop_button.setEnabled(False)

    def _on_monitor_finished(self, alert_count: int) -> None:
        self._append_log(f"Monitor stopped, alerts={alert_count}")
        self._monitor_worker = None
        self._monitor_thread = None
        self._monitor_config = None
        self._stop_alert_sound()
        self._cancel_active_manual_refresh()
        self._set_running(False)

    def _on_monitor_failed(self, message: str) -> None:
        self._append_log(message)
        QMessageBox.critical(self, "监控失败", message)

    def _on_universe(self, universe: Universe) -> None:
        self._set_status("options", str(len(universe.options)))
        self._set_status("futures", str(len(universe.futures)))
        self._set_status("price_symbols", str(len(universe.price_symbols())))

    def _on_compiled(self, strategy_count: int, total_conditions: int) -> None:
        self._set_status("strategies", str(strategy_count))
        self._set_status("conditions", str(total_conditions))

    def _on_cycle(self, cycle: RunnerCycle) -> None:
        self._set_status("cycles", str(cycle.cycle_count))
        self._set_status("active", str(cycle.active_count))
        self._set_status("alerts", str(cycle.total_alerts))
        self._set_status("timestamp", _format_status_timestamp(cycle.timestamp))
        self._cache_active_records(cycle)
        if self._manual_active_refresh_pending:
            self._complete_active_manual_refresh()
        elif self.auto_active_refresh.isChecked() and self._last_displayed_active_cycle_count == 0:
            self._refresh_active_table_from_cache()

    def _on_alert(self, event: AlertEvent) -> None:
        follow_latest = _table_is_at_bottom(self.alert_table)
        self.alert_view.append_record(event.timestamp, event.evaluation, scroll_to_bottom=follow_latest)
        self._emit_local_alert(event)

    def _emit_local_alert(self, event: AlertEvent) -> None:
        config = self._monitor_config or self.config
        if config.notifier.channels.popup:
            self._toast.show_message(
                event.evaluation.message,
                duration_ms=config.notifier.popup.duration_seconds * 1000,
            )
        if config.notifier.channels.sound:
            self._start_alert_sound(config.notifier.sound.duration_seconds)

    def _start_alert_sound(self, duration_seconds: int) -> None:
        now = time.monotonic()
        self._alert_sound_until = max(self._alert_sound_until, now + duration_seconds)
        QApplication.beep()
        self._alert_sound_timer.start(ALERT_SOUND_BEEP_INTERVAL_MS)

    def _on_alert_sound_timer(self) -> None:
        if time.monotonic() >= self._alert_sound_until:
            self._stop_alert_sound()
            return
        QApplication.beep()

    def _stop_alert_sound(self) -> None:
        self._alert_sound_timer.stop()
        self._alert_sound_until = 0.0

    def _cache_active_records(self, cycle: RunnerCycle) -> None:
        for evaluation in cycle.evaluations:
            if evaluation.active:
                self._active_records_by_key[evaluation.key] = _EvaluationRecord(cycle.timestamp, evaluation)
            else:
                self._active_records_by_key.pop(evaluation.key, None)
        self._latest_active_cycle_count = cycle.cycle_count

    def _reset_active_records(self) -> None:
        self._active_records_by_key.clear()
        self._latest_active_cycle_count = 0
        self._last_displayed_active_cycle_count = 0
        self._cancel_active_manual_refresh()

    def _refresh_active_table_from_cache(self) -> None:
        self.active_view.set_records(self._active_records_by_key.values())
        self._last_displayed_active_cycle_count = self._latest_active_cycle_count

    def _request_active_manual_refresh(self) -> None:
        if not self._running:
            QMessageBox.information(self, "无法刷新", "监控未运行，无法获取最新数据。")
            return
        if self._manual_active_refresh_pending:
            return
        self._manual_active_refresh_pending = True
        self.manual_active_refresh_button.setEnabled(False)
        self.manual_active_refresh_button.setText("刷新中...")
        self._manual_active_refresh_timeout.start(MANUAL_ACTIVE_REFRESH_TIMEOUT_MS)

    def _complete_active_manual_refresh(self) -> None:
        self._manual_active_refresh_timeout.stop()
        self._manual_active_refresh_pending = False
        self.manual_active_refresh_button.setEnabled(True)
        self.manual_active_refresh_button.setText("手动刷新")
        self._refresh_active_table_from_cache()

    def _cancel_active_manual_refresh(self) -> None:
        self._manual_active_refresh_timeout.stop()
        if not self._manual_active_refresh_pending:
            return
        self._manual_active_refresh_pending = False
        self.manual_active_refresh_button.setEnabled(True)
        self.manual_active_refresh_button.setText("手动刷新")

    def _on_active_manual_refresh_timeout(self) -> None:
        if not self._manual_active_refresh_pending:
            return
        self._manual_active_refresh_pending = False
        self.manual_active_refresh_button.setEnabled(True)
        self.manual_active_refresh_button.setText("手动刷新")
        QMessageBox.warning(self, "刷新失败", "3秒内未收到新的行情数据，无法刷新当前活跃预警记录。")

    def _on_active_auto_refresh_changed(self) -> None:
        if self._applying_active_refresh_config:
            return
        self._apply_active_auto_refresh_settings(refresh_now=True)

    def _on_active_refresh_interval_changed(self) -> None:
        if self._applying_active_refresh_config:
            return
        self._apply_active_auto_refresh_settings(refresh_now=True)

    def _apply_active_auto_refresh_settings(self, refresh_now: bool) -> None:
        if self.auto_active_refresh.isChecked():
            self._active_auto_refresh_timer.start(self._active_refresh_interval_seconds() * 1000)
            if refresh_now:
                self._refresh_active_table_from_cache()
        else:
            self._active_auto_refresh_timer.stop()

    def _set_active_refresh_config(self, config: ActiveAlertsViewConfig) -> None:
        self._applying_active_refresh_config = True
        try:
            self.auto_active_refresh.setChecked(config.auto_refresh)
            self._set_active_refresh_interval_seconds(config.refresh_interval_seconds)
        finally:
            self._applying_active_refresh_config = False
        self._apply_active_auto_refresh_settings(refresh_now=True)

    def _set_active_refresh_interval_seconds(self, seconds: int) -> None:
        for index in range(self.active_refresh_interval.count()):
            if int(self.active_refresh_interval.itemData(index)) == seconds:
                self.active_refresh_interval.setCurrentIndex(index)
                return
        self.active_refresh_interval.setCurrentIndex(0)

    def _active_refresh_interval_seconds(self) -> int:
        data = self.active_refresh_interval.currentData()
        return int(data) if data is not None else 10

    def _current_active_refresh_config(self) -> ActiveAlertsViewConfig:
        return ActiveAlertsViewConfig(
            auto_refresh=self.auto_active_refresh.isChecked(),
            refresh_interval_seconds=self._active_refresh_interval_seconds(),
        )

    def _config_with_active_refresh(self, config: AppConfig) -> AppConfig:
        return replace(
            config,
            gui=replace(config.gui, active_alerts=self._current_active_refresh_config()),
        )

    def _set_strategy_filters(self, config: AppConfig) -> None:
        strategy_names: list[str] = []
        strategy_types_by_name: dict[str, set[str]] = {}
        for strategy in config.selected_strategies:
            strategy_name = strategy_display_name(strategy)
            strategy_names.append(strategy_name)
            strategy_types_by_name.setdefault(strategy_name, set()).add(strategy.type)
        self.active_view.set_strategy_names(strategy_names, strategy_types_by_name)
        self.alert_view.set_strategy_names(strategy_names)

    def _save_config(self) -> None:
        try:
            config = self._config_with_active_refresh(self.config_editor.build_config())
            save_config(self.config_path, config)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.config = config
        self._sync_config_summary(config)
        suffix = "；当前监控继续使用启动时的配置" if self._running else ""
        self._append_log(f"Saved config: {self.config_path}{suffix}")
        self.show_toast("保存成功")

    def _reload_config(self) -> None:
        try:
            config = load_config(self.config_path)
        except Exception as exc:
            QMessageBox.warning(self, "加载失败", str(exc))
            return
        self.config = config
        self._load_config_into_editor(config)
        suffix = "；当前监控继续使用启动时的配置" if self._running else ""
        self._append_log(f"Reloaded config: {self.config_path}{suffix}")
        self.show_toast("加载成功")

    def _set_running(self, running: bool) -> None:
        self._running = running
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        if not running:
            self._set_status("status", "stopped")

    def _set_status(self, key: str, value: str) -> None:
        label = self.status_labels.get(key)
        if label is not None:
            label.setText(value or "-")

    def _append_log(self, message: str) -> None:
        self.log_view.append(message)

    def closeEvent(self, event: Any) -> None:
        if self._running:
            self._stop_monitor()
            event.ignore()
            return
        super().closeEvent(event)


@dataclass(frozen=True)
class _EvaluationRecord:
    timestamp: str
    evaluation: ConditionEvaluation


@dataclass(frozen=True)
class _RangeFilter:
    text: str
    lower: float
    upper: float


class SortableHeader(QHeaderView):
    filterRequested = pyqtSignal(int)

    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self._sort_column: int | None = None
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._filtered_columns: set[int] = set()
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setSortIndicatorShown(False)

    def set_sort_state(self, column: int | None, order: Qt.SortOrder) -> None:
        self._sort_column = column
        self._sort_order = order
        self.viewport().update()

    def set_filter_state(self, columns: set[int]) -> None:
        self._filtered_columns = set(columns)
        self.viewport().update()

    def paintSection(self, painter: Any, rect: QRect, logical_index: int) -> None:
        super().paintSection(painter, rect, logical_index)
        if rect.width() < 48:
            return
        symbol = "⇅"
        if self._sort_column == logical_index:
            symbol = "▲" if self._sort_order == Qt.SortOrder.AscendingOrder else "▼"
        painter.save()
        painter.setPen(Qt.GlobalColor.darkGray)
        painter.drawText(self._sort_button_rect(rect), Qt.AlignmentFlag.AlignCenter, symbol)
        painter.setPen(Qt.GlobalColor.blue if logical_index in self._filtered_columns else Qt.GlobalColor.darkGray)
        painter.drawText(self._filter_button_rect(rect), Qt.AlignmentFlag.AlignCenter, "筛")
        painter.restore()

    def mousePressEvent(self, event: Any) -> None:
        position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        logical_index = self.logicalIndexAt(position)
        if logical_index >= 0:
            rect = QRect(
                self.sectionViewportPosition(logical_index),
                0,
                self.sectionSize(logical_index),
                self.height(),
            )
            if self._filter_button_rect(rect).contains(position):
                self.filterRequested.emit(logical_index)
                return
        super().mousePressEvent(event)

    def _sort_button_rect(self, rect: QRect) -> QRect:
        return QRect(rect.right() - 48, rect.top() + 4, 20, max(12, rect.height() - 8))

    def _filter_button_rect(self, rect: QRect) -> QRect:
        return QRect(rect.right() - 24, rect.top() + 4, 20, max(12, rect.height() - 8))


class SortableTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(SORT_ROLE)
        right = other.data(SORT_ROLE) if other is not None else None
        if left is not None and right is not None:
            try:
                return left < right
            except TypeError:
                return str(left) < str(right)
        return self.text().casefold() < other.text().casefold()


class StrategyEvaluationTable(QGroupBox):
    def __init__(self, title: str, show_moneyness_columns: bool = False) -> None:
        super().__init__(title)
        self._show_moneyness_columns = show_moneyness_columns
        self._configured_strategy_names: tuple[str, ...] = ()
        self._strategy_names: tuple[str, ...] = ()
        self._selected_strategy: str | None = None
        self._strategy_types_by_name: dict[str, set[str]] = {}
        self._records: list[_EvaluationRecord] = []
        self._buttons: dict[str | None, QPushButton] = {}
        self._table_shape: tuple[bool, tuple[str, ...]] | None = None

        layout = QVBoxLayout(self)
        filter_row = QHBoxLayout()
        self._filter_layout = QHBoxLayout()
        filter_row.addLayout(self._filter_layout)
        filter_row.addStretch(1)
        self._toolbar_layout = QHBoxLayout()
        filter_row.addLayout(self._toolbar_layout)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, 0)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self._rebuild_filter_buttons()
        self._render()

    def set_strategy_names(
        self,
        strategy_names: Iterable[str],
        strategy_types_by_name: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        self._configured_strategy_names = _unique_names(strategy_names)
        self._strategy_types_by_name = {
            str(strategy_name): set(map(str, strategy_types))
            for strategy_name, strategy_types in (strategy_types_by_name or {}).items()
        }
        self._sync_strategy_buttons()
        self._render()

    def filter_labels(self) -> tuple[str, ...]:
        return tuple(button.text() for button in self._buttons.values())

    def add_toolbar_widget(self, widget: QWidget) -> None:
        self._toolbar_layout.addWidget(widget)

    def set_strategy_filter(self, strategy_name: str | None) -> None:
        if strategy_name is not None and strategy_name not in self._strategy_names:
            return
        self._selected_strategy = strategy_name
        for name, button in self._buttons.items():
            button.setChecked(name == strategy_name)
        self._render()

    def clear_records(self) -> None:
        self._records = []
        self._sync_strategy_buttons()
        self._render()

    def set_records(self, records: Iterable[_EvaluationRecord]) -> None:
        self._records = list(records)
        self._sync_strategy_buttons()
        self._render()

    def append_record(
        self,
        timestamp: str,
        evaluation: ConditionEvaluation,
        scroll_to_bottom: bool = True,
    ) -> None:
        self._records.append(_EvaluationRecord(timestamp, evaluation))
        self._sync_strategy_buttons()
        self._render(scroll_to_bottom=scroll_to_bottom, preserve_scroll=not scroll_to_bottom)

    def _sync_strategy_buttons(self) -> None:
        record_strategy_names = (record.evaluation.strategy_name for record in self._records)
        strategy_names = _unique_names((*self._configured_strategy_names, *record_strategy_names))
        if self._selected_strategy is not None and self._selected_strategy not in strategy_names:
            self._selected_strategy = None
        if strategy_names == self._strategy_names:
            return
        self._strategy_names = strategy_names
        self._rebuild_filter_buttons()

    def _rebuild_filter_buttons(self) -> None:
        while self._filter_layout.count():
            item = self._filter_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._buttons = {}
        self._add_filter_button(None, ALL_STRATEGIES_LABEL)
        for strategy_name in self._strategy_names:
            self._add_filter_button(strategy_name, strategy_name)

    def _add_filter_button(self, strategy_name: str | None, label: str) -> None:
        button = QPushButton(label)
        button.setCheckable(True)
        button.setChecked(strategy_name == self._selected_strategy)
        button.clicked.connect(lambda _checked=False, name=strategy_name: self.set_strategy_filter(name))
        self._filter_layout.addWidget(button)
        self._buttons[strategy_name] = button

    def _render(self, scroll_to_bottom: bool = False, preserve_scroll: bool = False) -> None:
        include_strategy = self._selected_strategy is None
        vertical_scroll = self.table.verticalScrollBar()
        horizontal_scroll = self.table.horizontalScrollBar()
        previous_vertical = vertical_scroll.value() if preserve_scroll else 0
        previous_horizontal = horizontal_scroll.value() if preserve_scroll else 0
        records = [
            record
            for record in self._records
            if include_strategy or record.evaluation.strategy_name == self._selected_strategy
        ]
        metric_columns = self._metric_columns(records, include_strategy)
        self._ensure_table_shape(include_strategy, metric_columns)
        self.table.setRowCount(0)
        for record in records:
            self._append_row(record, include_strategy, metric_columns)
        _restore_table_sort(self.table)
        _apply_table_filters(self.table)
        if scroll_to_bottom:
            self.table.scrollToBottom()
        elif preserve_scroll:
            vertical_scroll.setValue(min(previous_vertical, vertical_scroll.maximum()))
            horizontal_scroll.setValue(min(previous_horizontal, horizontal_scroll.maximum()))

    def _metric_columns(self, records: list[_EvaluationRecord], include_strategy: bool) -> tuple[str, ...]:
        if include_strategy or not self._show_moneyness_columns:
            return ()
        strategy_types = self._strategy_types_by_name.get(self._selected_strategy or "", set())
        if strategy_types == {"cp_combo"}:
            return (CALL_MONEYNESS_METRIC, PUT_MONEYNESS_METRIC)
        if strategy_types == {"abs_spread"}:
            return (
                SPREAD_A_MONEYNESS_METRIC,
                SPREAD_B_MONEYNESS_METRIC,
                SPREAD_AVG_MONEYNESS_METRIC,
            )
        metric_names = {
            metric_name
            for record in records
            for metric_name in record.evaluation.metrics
        }
        if any(metric_name in metric_names for metric_name in (CALL_MONEYNESS_METRIC, PUT_MONEYNESS_METRIC)):
            return (CALL_MONEYNESS_METRIC, PUT_MONEYNESS_METRIC)
        if any(
            metric_name in metric_names
            for metric_name in (
                SPREAD_A_MONEYNESS_METRIC,
                SPREAD_B_MONEYNESS_METRIC,
                SPREAD_AVG_MONEYNESS_METRIC,
            )
        ):
            return (
                SPREAD_A_MONEYNESS_METRIC,
                SPREAD_B_MONEYNESS_METRIC,
                SPREAD_AVG_MONEYNESS_METRIC,
            )
        return ()

    def _ensure_table_shape(self, include_strategy: bool, metric_columns: tuple[str, ...]) -> None:
        table_shape = (include_strategy, metric_columns)
        if self._table_shape == table_shape:
            return
        self._table_shape = table_shape
        if include_strategy:
            headers = ("时间", "策略名", "值", "预警范围", "合约")
            widths = (165, 130, 100, 150, 360)
        else:
            headers = ("时间", "值", "预警范围", "合约")
            widths = (165, 100, 150, 360)
        if metric_columns:
            metric_widths = tuple(
                115 if metric_name == SPREAD_AVG_MONEYNESS_METRIC else 105
                for metric_name in metric_columns
            )
            if include_strategy:
                headers = (*headers[:3], *metric_columns, *headers[3:])
                widths = (*widths[:3], *metric_widths, *widths[3:])
            else:
                headers = (*headers[:2], *metric_columns, *headers[2:])
                widths = (*widths[:2], *metric_widths, *widths[2:])
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        _configure_resizable_columns(self.table, widths, stretch_last=True)

    def _append_row(
        self,
        record: _EvaluationRecord,
        include_strategy: bool,
        metric_columns: tuple[str, ...],
    ) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        evaluation = record.evaluation
        formatted_timestamp = _format_table_timestamp(record.timestamp)
        background = _evaluation_row_background(evaluation)
        values: list[tuple[str, object | None]] = [
            (formatted_timestamp, formatted_timestamp),
            (f"{evaluation.value:.8f}", evaluation.value),
        ]
        if include_strategy:
            values.insert(1, (evaluation.strategy_name, evaluation.strategy_name.casefold()))
        if metric_columns:
            values.extend(_moneyness_cells(evaluation, metric_columns))
        values.extend(
            [
                (
                    _format_warning_range(evaluation.min_value, evaluation.max_value),
                    (evaluation.min_value, evaluation.max_value),
                ),
                (", ".join(evaluation.symbols), None),
            ]
        )
        for column, (value, sort_key) in enumerate(values):
            item = _table_item(value, sort_key=sort_key)
            if background is not None:
                item.setBackground(background)
            if _right_align_sort_key(sort_key):
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, column, item)


def _moneyness_cells(
    evaluation: ConditionEvaluation,
    metric_columns: tuple[str, ...],
) -> list[tuple[str, object | None]]:
    return [_moneyness_cell(evaluation, metric_name) for metric_name in metric_columns]


def _moneyness_cell(evaluation: ConditionEvaluation, metric_name: str) -> tuple[str, object | None]:
    value = evaluation.metrics.get(metric_name)
    if value is None:
        return "-", None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-", None
    if not math.isfinite(numeric):
        return "-", None
    return f"{numeric:.8f}", numeric


def _right_align_sort_key(sort_key: object | None) -> bool:
    if isinstance(sort_key, bool) or sort_key is None:
        return False
    return isinstance(sort_key, (int, float, tuple))


class ConfigEditor(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._tqsdk_username: str | None = None
        self._tqsdk_password: str | None = None
        self._config_dir = Path(".").resolve()
        outer = QVBoxLayout(self)
        actions = QHBoxLayout()
        self.save_button = QPushButton("保存配置")
        self.save_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.reload_button = QPushButton("重新加载")
        self.reload_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        actions.addStretch(1)
        actions.addWidget(self.save_button)
        actions.addWidget(self.reload_button)
        outer.addLayout(actions)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self._build_runtime()
        self._build_universe()
        self._build_strategies()
        self._build_backtest()
        self._build_tqsdk()
        self._build_notifier()
        self._build_logging()
        self.content_layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

    def set_config_path(self, config_path: Path) -> None:
        self._config_dir = config_path.resolve().parent

    def _build_runtime(self) -> None:
        box = QGroupBox("运行")
        form = QFormLayout(box)
        self.runtime_mode = NoWheelComboBox()
        self.runtime_mode.addItems(("live", "backtest"))
        self.price_basis = QLineEdit("last")
        self.price_basis.setReadOnly(True)
        self.alert_on_first_match = QCheckBox()
        form.addRow("模式", self.runtime_mode)
        form.addRow("价格字段", self.price_basis)
        form.addRow("首次匹配预警", self.alert_on_first_match)
        self.content_layout.addWidget(box)

    def _build_universe(self) -> None:
        box = QGroupBox("合约范围")
        form = QFormLayout(box)
        self._universe_form = form
        self.universe_mode = NoWheelComboBox()
        self.universe_mode.addItems(("all", "onlyDo", "excludeDo"))
        self.only_do = QTextEdit()
        self.only_do.setFixedHeight(70)
        self.exclude_do = QTextEdit()
        self.exclude_do.setFixedHeight(70)
        self.exchange_ids = QLineEdit()
        self.min_volume = _spin(0, 1_000_000_000)
        self.min_open_interest = _spin(0, 1_000_000_000)
        form.addRow("模式", self.universe_mode)
        form.addRow("指定合约", self.only_do)
        form.addRow("排除合约", self.exclude_do)
        form.addRow("交易所", self.exchange_ids)
        form.addRow("最小成交量", self.min_volume)
        form.addRow("最小持仓量", self.min_open_interest)
        self.universe_mode.currentTextChanged.connect(self._update_universe_inputs)
        self._update_universe_inputs()
        self.content_layout.addWidget(box)

    def _build_strategies(self) -> None:
        box = QGroupBox("策略")
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        self.strategy_type_to_add = NoWheelComboBox()
        for strategy_type in SUPPORTED_STRATEGY_TYPES:
            self.strategy_type_to_add.addItem(strategy_type_display_name(strategy_type), strategy_type)
        self.add_strategy_button = QPushButton("添加")
        self.add_strategy_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder))
        self.add_strategy_button.clicked.connect(self._add_selected_strategy_row)
        remove_button = QPushButton("删除")
        remove_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        remove_button.clicked.connect(self._remove_strategy_row)
        script_button = QPushButton("选择脚本")
        script_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        script_button.clicked.connect(self._browse_strategy_filter_script)
        row.addWidget(self.strategy_type_to_add)
        row.addWidget(self.add_strategy_button)
        row.addWidget(remove_button)
        row.addWidget(script_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.strategies = QTableWidget(0, 8)
        self.strategies.setHorizontalHeaderLabels(("选中", "类型", "最小值", "最大值", "名称", "筛选脚本", "函数", "范围"))
        self.strategies.setAlternatingRowColors(True)
        self.strategies.setMinimumHeight(180)
        self.strategies.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.strategies.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.strategies.verticalHeader().setDefaultSectionSize(36)
        self.strategies.verticalHeader().setMinimumSectionSize(32)
        self.strategies.verticalHeader().setVisible(False)
        _configure_resizable_columns(self.strategies, (70, 130, 110, 110, 180, 240, 110, 90))
        self.strategies.itemChanged.connect(self._on_strategy_item_changed)
        layout.addWidget(self.strategies)
        self.content_layout.addWidget(box)

    def _build_backtest(self) -> None:
        box = QGroupBox("回测")
        form = QFormLayout(box)
        self.backtest_start = QLineEdit()
        self.backtest_end = QLineEdit()
        self.duration_seconds = _spin(1, 86400)
        self.data_length = _spin(1, 10000)
        self.initial_price_timeout_seconds = _spin(1, 3600)
        self.subscription_batch_size = _spin(1, 1000)
        form.addRow("开始日期", self.backtest_start)
        form.addRow("结束日期", self.backtest_end)
        form.addRow("K线秒数", self.duration_seconds)
        form.addRow("数据长度", self.data_length)
        form.addRow("初始化超时", self.initial_price_timeout_seconds)
        form.addRow("订阅批量", self.subscription_batch_size)
        self.content_layout.addWidget(box)

    def _build_tqsdk(self) -> None:
        box = QGroupBox("TqSdk")
        form = QFormLayout(box)
        self.username_env = QLineEdit()
        self.password_env = QLineEdit()
        self.symbol_info_batch_size = _spin(1, 10000)
        self.quote_subscription_batch_size = _spin(1, 10000)
        form.addRow("账号环境变量", self.username_env)
        form.addRow("密码环境变量", self.password_env)
        form.addRow("合约信息批量", self.symbol_info_batch_size)
        form.addRow("行情订阅批量", self.quote_subscription_batch_size)
        self.content_layout.addWidget(box)

    def _build_notifier(self) -> None:
        box = QGroupBox("通知")
        form = QFormLayout(box)
        self.notify_popup = QCheckBox("弹窗")
        self.notify_sound = QCheckBox("声音")
        self.notify_file = QCheckBox("文件")
        self.notify_email = QCheckBox("邮件")
        channel_row = QHBoxLayout()
        channel_row.addWidget(self.notify_popup)
        channel_row.addWidget(self.notify_sound)
        channel_row.addWidget(self.notify_file)
        channel_row.addWidget(self.notify_email)
        channel_row.addStretch(1)
        self.popup_duration_seconds = _spin(1, 3600)
        self.sound_duration_seconds = _spin(1, 3600)
        self.alert_log_path = QLineEdit()
        self.smtp_host = QLineEdit()
        self.smtp_port = _spin(1, 65535)
        self.smtp_timeout_seconds = _spin(1, 300)
        self.alert_interval_seconds = _spin(0, 86400)
        self.email_username = QLineEdit()
        self.email_password = QLineEdit()
        self.email_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.email_password_env = QLineEdit()
        self.from_addr = QLineEdit()
        self.to_addrs = QLineEdit()
        self.use_tls = QCheckBox()
        self.failure_backoff_seconds = _spin(0, 86400)
        form.addRow("通知方式", channel_row)
        form.addRow("弹窗持续秒数", self.popup_duration_seconds)
        form.addRow("声音持续秒数", self.sound_duration_seconds)
        form.addRow("预警日志", self.alert_log_path)
        form.addRow("SMTP主机", self.smtp_host)
        form.addRow("SMTP端口", self.smtp_port)
        form.addRow("SMTP超时", self.smtp_timeout_seconds)
        form.addRow("邮件聚合秒数", self.alert_interval_seconds)
        form.addRow("邮箱账号", self.email_username)
        form.addRow("邮箱密码", self.email_password)
        form.addRow("邮箱密码变量", self.email_password_env)
        form.addRow("发件人", self.from_addr)
        form.addRow("收件人", self.to_addrs)
        form.addRow("TLS", self.use_tls)
        form.addRow("失败退避秒数", self.failure_backoff_seconds)
        self.content_layout.addWidget(box)

    def _build_logging(self) -> None:
        box = QGroupBox("日志")
        form = QFormLayout(box)
        self.log_level = NoWheelComboBox()
        self.log_level.addItems(("DEBUG", "INFO", "WARNING", "ERROR"))
        self.log_dir = QLineEdit()
        self.log_file = QLineEdit()
        self.max_bytes = _spin(1, 1_000_000_000)
        self.backup_count = _spin(0, 100)
        self.cycle_summary_interval_seconds = _spin(0, 86400)
        form.addRow("级别", self.log_level)
        form.addRow("目录", self.log_dir)
        form.addRow("文件", self.log_file)
        form.addRow("最大字节", self.max_bytes)
        form.addRow("备份数", self.backup_count)
        form.addRow("摘要间隔", self.cycle_summary_interval_seconds)
        self.content_layout.addWidget(box)

    def set_config(self, config: AppConfig) -> None:
        self.runtime_mode.setCurrentText(config.runtime.mode)
        self.price_basis.setText(config.runtime.price_basis)
        self.alert_on_first_match.setChecked(config.runtime.alert_on_first_match)
        self.universe_mode.setCurrentText(config.universe.mode)
        self.only_do.setPlainText("\n".join(config.universe.only_do))
        self.exclude_do.setPlainText("\n".join(config.universe.exclude_do))
        self.exchange_ids.setText(", ".join(config.universe.exchange_ids))
        self._update_universe_inputs()
        self.min_volume.setValue(config.universe.min_volume)
        self.min_open_interest.setValue(config.universe.min_open_interest)
        self.strategies.setRowCount(0)
        for strategy in config.strategies:
            self._add_strategy_row(
                strategy.type,
                strategy.min_value,
                strategy.max_value,
                strategy.name or "",
                strategy.selected,
                strategy.filter_script or "",
                strategy.filter_function,
                strategy.filter_scope,
                restore_sort=False,
            )
        _restore_table_sort(self.strategies)
        _apply_table_filters(self.strategies)
        if config.backtest.start_dt is not None:
            self.backtest_start.setText(config.backtest.start_dt.isoformat())
        else:
            self.backtest_start.setText("")
        if config.backtest.end_dt is not None:
            self.backtest_end.setText(config.backtest.end_dt.isoformat())
        else:
            self.backtest_end.setText("")
        self.duration_seconds.setValue(config.backtest.duration_seconds)
        self.data_length.setValue(config.backtest.data_length)
        self.initial_price_timeout_seconds.setValue(config.backtest.initial_price_timeout_seconds)
        self.subscription_batch_size.setValue(config.backtest.subscription_batch_size)
        self._tqsdk_username = config.tqsdk.username
        self._tqsdk_password = config.tqsdk.password
        self.username_env.setText(config.tqsdk.username_env)
        self.password_env.setText(config.tqsdk.password_env)
        self.symbol_info_batch_size.setValue(config.tqsdk.symbol_info_batch_size)
        self.quote_subscription_batch_size.setValue(config.tqsdk.quote_subscription_batch_size)
        self.notify_popup.setChecked(config.notifier.channels.popup)
        self.notify_sound.setChecked(config.notifier.channels.sound)
        self.notify_file.setChecked(config.notifier.channels.file)
        self.notify_email.setChecked(config.notifier.channels.email)
        self.popup_duration_seconds.setValue(config.notifier.popup.duration_seconds)
        self.sound_duration_seconds.setValue(config.notifier.sound.duration_seconds)
        self.alert_log_path.setText(config.notifier.alert_log_path)
        self.smtp_host.setText(config.notifier.email.smtp_host or "")
        self.smtp_port.setValue(config.notifier.email.smtp_port)
        self.smtp_timeout_seconds.setValue(config.notifier.email.smtp_timeout_seconds)
        self.alert_interval_seconds.setValue(config.notifier.email.alert_interval_seconds)
        self.email_username.setText(config.notifier.email.username or "")
        self.email_password.setText(config.notifier.email.password or "")
        self.email_password_env.setText(config.notifier.email.password_env)
        self.from_addr.setText(config.notifier.email.from_addr or "")
        self.to_addrs.setText(", ".join(config.notifier.email.to_addrs))
        self.use_tls.setChecked(config.notifier.email.use_tls)
        self.failure_backoff_seconds.setValue(config.notifier.email.failure_backoff_seconds)
        self.log_level.setCurrentText(config.logging.level.upper())
        self.log_dir.setText(config.logging.log_dir)
        self.log_file.setText(config.logging.log_file)
        self.max_bytes.setValue(config.logging.max_bytes)
        self.backup_count.setValue(config.logging.backup_count)
        self.cycle_summary_interval_seconds.setValue(config.logging.cycle_summary_interval_seconds)

    def build_config(self) -> AppConfig:
        return data_to_config(self._data())

    def _data(self) -> dict[str, Any]:
        return {
            "runtime": {
                "mode": self.runtime_mode.currentText(),
                "price_basis": "last",
                "alert_on_first_match": self.alert_on_first_match.isChecked(),
            },
            "universe": {
                "mode": self.universe_mode.currentText(),
                "only_do": _split_lines(self.only_do.toPlainText()),
                "exclude_do": _split_lines(self.exclude_do.toPlainText()),
                "exchange_ids": _split_csv(self.exchange_ids.text()),
                "min_volume": self.min_volume.value(),
                "min_open_interest": self.min_open_interest.value(),
            },
            "datasource": {
                "tqsdk": {
                    "username": self._tqsdk_username,
                    "password": self._tqsdk_password,
                    "username_env": self.username_env.text().strip() or "TQSDK_USERNAME",
                    "password_env": self.password_env.text().strip() or "TQSDK_PASSWORD",
                    "symbol_info_batch_size": self.symbol_info_batch_size.value(),
                    "quote_subscription_batch_size": self.quote_subscription_batch_size.value(),
                }
            },
            "strategies": self._strategy_data(),
            "backtest": {
                "start_dt": self.backtest_start.text().strip() or None,
                "end_dt": self.backtest_end.text().strip() or None,
                "duration_seconds": self.duration_seconds.value(),
                "data_length": self.data_length.value(),
                "initial_price_timeout_seconds": self.initial_price_timeout_seconds.value(),
                "subscription_batch_size": self.subscription_batch_size.value(),
            },
            "notifier": {
                "channels": {
                    "popup": self.notify_popup.isChecked(),
                    "sound": self.notify_sound.isChecked(),
                    "file": self.notify_file.isChecked(),
                    "email": self.notify_email.isChecked(),
                },
                "popup": {
                    "duration_seconds": self.popup_duration_seconds.value(),
                },
                "sound": {
                    "duration_seconds": self.sound_duration_seconds.value(),
                },
                "alert_log_path": self.alert_log_path.text().strip() or "logs/alerts.jsonl",
                "email": {
                    "smtp_host": self.smtp_host.text().strip() or None,
                    "smtp_port": self.smtp_port.value(),
                    "smtp_timeout_seconds": self.smtp_timeout_seconds.value(),
                    "alert_interval_seconds": self.alert_interval_seconds.value(),
                    "username": self.email_username.text().strip() or None,
                    "password": self.email_password.text() or None,
                    "password_env": self.email_password_env.text().strip() or "SMTP_PASSWORD",
                    "from_addr": self.from_addr.text().strip() or None,
                    "to_addrs": _split_csv(self.to_addrs.text()),
                    "use_tls": self.use_tls.isChecked(),
                    "failure_backoff_seconds": self.failure_backoff_seconds.value(),
                },
            },
            "logging": {
                "level": self.log_level.currentText(),
                "log_dir": self.log_dir.text().strip() or "logs",
                "log_file": self.log_file.text().strip() or "optionsentry.log",
                "max_bytes": self.max_bytes.value(),
                "backup_count": self.backup_count.value(),
                "cycle_summary_interval_seconds": self.cycle_summary_interval_seconds.value(),
            },
        }

    def _update_universe_inputs(self) -> None:
        mode = self.universe_mode.currentText()
        self._set_universe_row_visible(self.exchange_ids, mode == "all")
        self._set_universe_row_visible(self.only_do, mode == "onlyDo")
        self._set_universe_row_visible(self.exclude_do, mode == "excludeDo")

    def _set_universe_row_visible(self, widget: QWidget, visible: bool) -> None:
        label = self._universe_form.labelForField(widget)
        if label is not None:
            label.setVisible(visible)
        widget.setVisible(visible)

    def _strategy_data(self) -> list[dict[str, Any]]:
        rows = []
        for row in range(self.strategies.rowCount()):
            selected = _table_checked(self.strategies, row, 0)
            strategy_type = _table_text(self.strategies, row, 1) or "cp_combo"
            min_value = float(_table_text(self.strategies, row, 2) or "-inf")
            max_value = float(_table_text(self.strategies, row, 3) or "inf")
            name = _table_text(self.strategies, row, 4)
            filter_script = _table_text(self.strategies, row, 5)
            filter_function = _table_text(self.strategies, row, 6) or "accept"
            filter_scope = _table_text(self.strategies, row, 7) or "options"
            item = {
                "type": strategy_type,
                "min_value": min_value,
                "max_value": max_value,
                "selected": selected,
            }
            if name:
                item["name"] = name
            if filter_script:
                item["filter_script"] = filter_script
                item["filter_function"] = filter_function
                item["filter_scope"] = filter_scope
            rows.append(item)
        return rows

    def _add_strategy_row(
        self,
        strategy_type: str,
        min_value: float,
        max_value: float,
        name: str,
        selected: bool = True,
        filter_script: str = "",
        filter_function: str = "accept",
        filter_scope: str = "options",
        restore_sort: bool = True,
    ) -> None:
        row = self.strategies.rowCount()
        self.strategies.insertRow(row)
        selected_item = _table_item("", sort_key=1 if selected else 0)
        selected_item.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        selected_item.setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)
        selected_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.strategies.setItem(row, 0, selected_item)
        self.strategies.setItem(row, 1, _table_item(strategy_type, sort_key=strategy_type.casefold()))
        self.strategies.setItem(row, 2, _table_item(_format_bound(min_value), sort_key=min_value))
        self.strategies.setItem(row, 3, _table_item(_format_bound(max_value), sort_key=max_value))
        self.strategies.setItem(row, 4, _table_item(name, sort_key=name.casefold()))
        self.strategies.setItem(row, 5, _table_item(filter_script, sort_key=filter_script.casefold()))
        self.strategies.setItem(row, 6, _table_item(filter_function, sort_key=filter_function.casefold()))
        self.strategies.setItem(row, 7, _table_item(filter_scope, sort_key=filter_scope.casefold()))
        if restore_sort:
            _restore_table_sort(self.strategies)
            _apply_table_filters(self.strategies)

    def _add_selected_strategy_row(self) -> None:
        strategy_type = str(self.strategy_type_to_add.currentData() or self.strategy_type_to_add.currentText())
        min_value, max_value = _default_strategy_range(strategy_type)
        self._add_strategy_row(strategy_type, min_value, max_value, "", True)

    def _browse_strategy_filter_script(self) -> None:
        row = self.strategies.currentRow()
        if row < 0:
            row = 0 if self.strategies.rowCount() else -1
        if row < 0:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择策略筛选脚本",
            str(self._config_dir),
            "Python (*.py);;All Files (*)",
        )
        if not path:
            return
        display_path = str(Path(path).resolve())
        item = self.strategies.item(row, 5)
        if item is None:
            item = _table_item(display_path, sort_key=display_path.casefold())
            self.strategies.setItem(row, 5, item)
        else:
            item.setText(display_path)

    def _remove_strategy_row(self) -> None:
        row = self.strategies.currentRow()
        if row >= 0:
            self.strategies.removeRow(row)

    def _on_strategy_item_changed(self, item: QTableWidgetItem) -> None:
        sort_key: object | None
        if item.column() == 0:
            sort_key = 1 if item.checkState() == Qt.CheckState.Checked else 0
        elif item.column() in {2, 3}:
            try:
                sort_key = float(item.text().strip())
            except ValueError:
                sort_key = item.text().casefold()
        else:
            sort_key = item.text().casefold()
        if item.data(SORT_ROLE) != sort_key:
            item.setData(SORT_ROLE, sort_key)
        _apply_table_filters(self.strategies)


def _unique_names(names: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        clean_name = str(name).strip()
        if not clean_name or clean_name in seen:
            continue
        seen.add(clean_name)
        unique.append(clean_name)
    return tuple(unique)


def _configure_resizable_columns(
    table: QTableWidget,
    widths: tuple[int, ...],
    stretch_last: bool = False,
) -> None:
    header = _ensure_sortable_header(table)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setMinimumSectionSize(50)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    for column, width in enumerate(widths):
        table.setColumnWidth(column, width)
    if stretch_last and widths:
        header.setSectionResizeMode(len(widths) - 1, QHeaderView.ResizeMode.Stretch)


def _ensure_sortable_header(table: QTableWidget) -> SortableHeader:
    header = table.horizontalHeader()
    if not isinstance(header, SortableHeader):
        header = SortableHeader(Qt.Orientation.Horizontal, table)
        table.setHorizontalHeader(header)
    if not getattr(table, "_optionsentry_sort_connected", False):
        header.sectionClicked.connect(lambda column, current_table=table: _toggle_table_sort(current_table, column))
        header.filterRequested.connect(lambda column, current_table=table: _prompt_table_filter(current_table, column))
        setattr(table, "_optionsentry_sort_connected", True)
    table.setSortingEnabled(False)
    return header


def _prompt_table_filter(table: QTableWidget, column: int) -> None:
    label = _header_label(table, column)
    filters = _table_filters(table)
    current = filters[label].text if label in filters else ""
    text, ok = QInputDialog.getText(
        table,
        "筛选",
        f"{label} 范围（例：8 10、8-10、8,10、8，10、8~10；留空清除）",
        QLineEdit.EchoMode.Normal,
        current,
    )
    if not ok:
        return
    try:
        _set_table_filter_text(table, column, text)
    except ValueError as exc:
        QMessageBox.warning(table, "筛选条件无效", str(exc))


def _toggle_table_sort(table: QTableWidget, column: int) -> None:
    previous_label = table.property(SORT_LABEL_PROPERTY)
    previous_order = _sort_order_from_property(table.property(SORT_ORDER_PROPERTY))
    label = _header_label(table, column)
    order = Qt.SortOrder.AscendingOrder
    if previous_label == label and previous_order == Qt.SortOrder.AscendingOrder:
        order = Qt.SortOrder.DescendingOrder
    _apply_table_sort(table, column, order)


def _restore_table_sort(table: QTableWidget) -> None:
    label = table.property(SORT_LABEL_PROPERTY)
    if not label:
        header = table.horizontalHeader()
        if isinstance(header, SortableHeader):
            header.set_sort_state(None, Qt.SortOrder.AscendingOrder)
        return
    column = _column_for_header_label(table, str(label))
    if column is None:
        return
    _apply_table_sort(table, column, _sort_order_from_property(table.property(SORT_ORDER_PROPERTY)))


def _apply_table_sort(table: QTableWidget, column: int, order: Qt.SortOrder) -> None:
    table.setProperty(SORT_COLUMN_PROPERTY, column)
    table.setProperty(SORT_LABEL_PROPERTY, _header_label(table, column))
    table.setProperty(SORT_ORDER_PROPERTY, order.value)
    header = table.horizontalHeader()
    if isinstance(header, SortableHeader):
        header.set_sort_state(column, order)
    table.sortItems(column, order)


def _set_table_filter_text(table: QTableWidget, column: int, text: str) -> None:
    label = _header_label(table, column)
    filters = _table_filters(table)
    parsed = _parse_range_filter(text)
    if parsed is None:
        filters.pop(label, None)
    else:
        filters[label] = parsed
    table.setProperty(FILTERS_PROPERTY, filters)
    _apply_table_filters(table)


def _apply_table_filters(table: QTableWidget) -> None:
    filters = _table_filters(table)
    active_filters: list[tuple[int, _RangeFilter]] = []
    for label, range_filter in filters.items():
        column = _column_for_header_label(table, label)
        if column is not None:
            active_filters.append((column, range_filter))
    for row in range(table.rowCount()):
        visible = all(_cell_matches_range_filter(table.item(row, column), range_filter) for column, range_filter in active_filters)
        table.setRowHidden(row, not visible)
    header = table.horizontalHeader()
    if isinstance(header, SortableHeader):
        header.set_filter_state({column for column, _range_filter in active_filters})


def _table_filters(table: QTableWidget) -> dict[str, _RangeFilter]:
    filters = table.property(FILTERS_PROPERTY)
    if isinstance(filters, dict):
        return dict(filters)
    return {}


def _parse_range_filter(text: str) -> _RangeFilter | None:
    raw = str(text).strip()
    if not raw:
        return None
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    hyphen_match = re.fullmatch(rf"\s*({number})\s*-\s*({number})\s*", raw)
    if hyphen_match is not None:
        parts = [hyphen_match.group(1), hyphen_match.group(2)]
    else:
        parts = [part for part in re.split(r"[\s,，~～]+", raw) if part]
    if len(parts) == 1:
        parts = [parts[0], parts[0]]
    if len(parts) != 2:
        raise ValueError("请输入一个数字，或两个数字组成的范围，例如 8 10、8-10、8,10、8，10、8~10。")
    try:
        lower = float(parts[0])
        upper = float(parts[1])
    except ValueError as exc:
        raise ValueError("筛选范围只能包含数字。") from exc
    if lower > upper:
        lower, upper = upper, lower
    return _RangeFilter(text=raw, lower=lower, upper=upper)


def _cell_matches_range_filter(item: QTableWidgetItem | None, range_filter: _RangeFilter) -> bool:
    value = _cell_numeric_value(item)
    return value is not None and range_filter.lower <= value <= range_filter.upper


def _cell_numeric_value(item: QTableWidgetItem | None) -> float | None:
    if item is None:
        return None
    sort_key = item.data(SORT_ROLE)
    if isinstance(sort_key, (int, float)) and not isinstance(sort_key, bool):
        return float(sort_key)
    try:
        return float(item.text().strip())
    except ValueError:
        return None


def _sort_order_from_property(value: object) -> Qt.SortOrder:
    if value == Qt.SortOrder.DescendingOrder.value:
        return Qt.SortOrder.DescendingOrder
    return Qt.SortOrder.AscendingOrder


def _column_for_header_label(table: QTableWidget, label: str) -> int | None:
    for column in range(table.columnCount()):
        if _header_label(table, column) == label:
            return column
    return None


def _header_label(table: QTableWidget, column: int) -> str:
    item = table.horizontalHeaderItem(column)
    return item.text() if item is not None else str(column)


def _table_is_at_bottom(table: QTableWidget) -> bool:
    scrollbar = table.verticalScrollBar()
    return scrollbar.value() >= scrollbar.maximum()


def _format_table_timestamp(timestamp: str) -> str:
    value = str(timestamp).strip()
    if not value:
        return ""
    with_tz = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(with_tz).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    if len(value) >= 19 and value[10] in (" ", "T") and value[13] == ":" and value[16] == ":":
        return value[:19].replace("T", " ")
    return value


def _format_status_timestamp(timestamp: str) -> str:
    value = str(timestamp).strip()
    if not value:
        return ""
    with_tz = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(with_tz)
        return f"{parsed:%Y-%m-%d %H:%M:%S}.{parsed.microsecond // 100000}"
    except ValueError:
        pass
    if len(value) >= 19 and value[10] in (" ", "T") and value[13] == ":" and value[16] == ":":
        base = value[:19].replace("T", " ")
        fraction = value[20:21] if len(value) > 20 and value[19] == "." else "0"
        return f"{base}.{fraction}"
    return value


def _format_warning_range(min_value: float, max_value: float) -> str:
    return f"({_format_bound(min_value)}, {_format_bound(max_value)})"


def _format_bound(value: float) -> str:
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return f"{value:g}"


def _default_strategy_range(strategy_type: str) -> tuple[float, float]:
    if strategy_type == "abs_spread":
        return -math.inf, 0.1
    return 0.01, math.inf


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]


def _split_lines(value: str) -> list[str]:
    result = []
    for line in value.replace(",", "\n").splitlines():
        item = line.strip()
        if item:
            result.append(item)
    return result


def _default_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().with_name("config.toml")
    return Path("config.toml")


def _evaluation_row_background(evaluation: ConditionEvaluation) -> QBrush | None:
    if not _is_cp_combo_evaluation(evaluation):
        return None
    if evaluation.value < 0:
        return QBrush(QColor(CP_NEGATIVE_VALUE_COLOR))
    if evaluation.value > 0:
        return QBrush(QColor(CP_POSITIVE_VALUE_COLOR))
    return None


def _is_cp_combo_evaluation(evaluation: ConditionEvaluation) -> bool:
    if evaluation.strategy_name == "cp_combo":
        return True
    parts = evaluation.key.split(":")
    # Strategy names can be localized, so the CP key shape is the stable marker.
    return len(parts) >= 6 and parts[3].startswith("K=")


def _table_item(text: str, sort_key: object | None = None) -> SortableTableWidgetItem:
    item = SortableTableWidgetItem(str(text))
    if sort_key is not None:
        item.setData(SORT_ROLE, sort_key)
    return item


def _table_text(table: QTableWidget, row: int, column: int) -> str:
    item = table.item(row, column)
    return item.text().strip() if item is not None else ""


def _table_checked(table: QTableWidget, row: int, column: int) -> bool:
    item = table.item(row, column)
    return item is None or item.checkState() == Qt.CheckState.Checked


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event: Any) -> None:
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event: Any) -> None:
        event.ignore()


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event: Any) -> None:
        event.ignore()

    def showPopup(self) -> None:
        _ensure_point_size_font(self)
        _ensure_point_size_font(self.view())
        super().showPopup()


def _spin(minimum: int, maximum: int) -> QSpinBox:
    spin = NoWheelSpinBox()
    spin.setRange(minimum, maximum)
    return spin


def _double_spin() -> QDoubleSpinBox:
    spin = NoWheelDoubleSpinBox()
    spin.setRange(0, 1_000_000_000)
    spin.setDecimals(4)
    return spin


def _ensure_point_size_font(widget: QWidget) -> None:
    font = widget.font()
    if font.pointSize() > 0:
        return
    app = QApplication.instance()
    app_font = app.font() if app is not None else QApplication.font()
    point_size = app_font.pointSize()
    if point_size <= 0:
        point_size = 10
    font.setPointSize(point_size)
    widget.setFont(font)


def _apply_style(app: QApplication) -> None:
    app.setStyleSheet(
        """
        QWidget {
            font-size: 10pt;
        }
        QMainWindow, QWidget {
            background: #f7f8fa;
            color: #24292f;
        }
        QGroupBox {
            background: #ffffff;
            border: 1px solid #d8dee4;
            border-radius: 6px;
            margin-top: 12px;
            padding: 12px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
            color: #57606a;
        }
        QPushButton, QToolButton {
            background: #ffffff;
            border: 1px solid #d0d7de;
            border-radius: 6px;
            padding: 6px 10px;
        }
        QPushButton:hover, QToolButton:hover {
            background: #f3f4f6;
        }
        QPushButton:disabled {
            color: #8c959f;
            background: #f6f8fa;
        }
        QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            background: #ffffff;
            border: 1px solid #d0d7de;
            border-radius: 5px;
            padding: 4px;
        }
        QTableWidget {
            background: #ffffff;
            alternate-background-color: #f6f8fa;
            color: #24292f;
            gridline-color: #d8dee4;
            selection-background-color: #eaeef2;
            selection-color: #24292f;
        }
        QTableWidget::item:hover {
            background: #eaeef2;
            color: #24292f;
        }
        QTableWidget::item:selected {
            background: #eaeef2;
            color: #24292f;
        }
        QHeaderView::section {
            background: #eef2f5;
            border: 0;
            border-right: 1px solid #d8dee4;
            padding: 6px 52px 6px 6px;
            font-weight: 600;
        }
        QLabel#windowTitle {
            font-size: 16pt;
            font-weight: 700;
        }
        QLabel#muted {
            color: #6e7781;
        }
        QLabel#error {
            color: #b42318;
        }
        QWidget#toastPopup {
            background: transparent;
        }
        QLabel#toastLabel {
            background: rgba(36, 41, 47, 230);
            color: #ffffff;
            border-radius: 6px;
            padding: 12px 16px;
            font-weight: 600;
        }
        QLabel#statusValue {
            font-weight: 600;
        }
        """
    )


def main(argv: list[str] | None = None) -> int:
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    _apply_style(app)
    window = LoginWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
