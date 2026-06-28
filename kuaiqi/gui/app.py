from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sys
from pathlib import Path
from typing import Any, Iterable

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
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

from kuaiqi.config import AppConfig, ConfigError, load_config
from kuaiqi.gui.config_store import data_to_config, save_config
from kuaiqi.gui.credentials import CredentialResolution, load_and_validate_login
from kuaiqi.gui.runner_adapter import GuiRunSignals, build_gui_runner
from kuaiqi.models import AlertEvent, ConditionEvaluation, Universe
from kuaiqi.runner import RunnerCycle


APP_NAME = "期权预警系统"
APP_ICON_PATH = Path(__file__).with_name("assets") / "app_icon.svg"
ALL_STRATEGIES_LABEL = "全部策略"
DIALOG_MESSAGE_LIMIT = 1200


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


class MonitorWorker(QObject):
    status = pyqtSignal(str)
    log = pyqtSignal(str)
    universe = pyqtSignal(object)
    compiled = pyqtSignal(int, int)
    cycle = pyqtSignal(object)
    alert = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
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
        self.config_path = QLineEdit(str(Path("config.toml")))
        browse = QToolButton()
        browse.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        browse.setToolTip("选择配置文件")
        browse.clicked.connect(self._browse_config)
        config_row = QHBoxLayout()
        config_row.addWidget(self.config_path, 1)
        config_row.addWidget(browse)
        form.addRow("配置文件", config_row)

        self.username = QLineEdit()
        self.username.setPlaceholderText("留空则读取 username_env")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("留空则读取 password_env")
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
        self.login_button.clicked.connect(self._login)
        row.addWidget(self.login_button)
        layout.addLayout(row)

    def _browse_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择配置文件", ".", "TOML (*.toml);;All Files (*)")
        if path:
            self.config_path.setText(path)

    def _login(self) -> None:
        self.error_label.setText("")
        path = Path(self.config_path.text().strip() or "config.toml")
        self.login_button.setEnabled(False)
        self.login_button.setText("登录中")
        self._thread = QThread(self)
        self._worker = LoginWorker(path, self.username.text(), self.password.text())
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
        self._main_window = MainWindow(config_path, config, credentials)
        self._main_window.show()
        self.close()

    def _on_login_failed(self, message: str) -> None:
        self.login_button.setEnabled(True)
        self.login_button.setText("登录")
        self.error_label.setText(message)


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
        self._running = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1180, 760)
        self._build_ui()
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
        self.config_editor.save_button.clicked.connect(self._save_config)
        self.config_editor.reload_button.clicked.connect(self._reload_config)
        self.tabs.addTab(self.config_editor, "配置")
        self.tabs.addTab(self._logs_tab(), "日志")
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)
        self.save_action = self.config_editor.save_button
        self.reload_action = self.config_editor.reload_button

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

        self.active_view = StrategyEvaluationTable("当前触发")
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
        self._set_status("mode", config.runtime.mode)
        self._set_status("config_path", str(self.config_path))
        self._set_status("credential_source", self.credentials.source)
        self._set_status("strategies", str(len(config.selected_strategies)))
        self._set_strategy_filters(config)

    def _start_monitor(self) -> None:
        if self._running:
            return
        try:
            self.config = self.config_editor.build_config()
        except Exception as exc:
            QMessageBox.warning(self, "配置错误", str(exc))
            return
        self._set_strategy_filters(self.config)
        self.alert_view.clear_records()
        self.active_view.clear_records()
        self._append_log("Starting monitor")
        self._set_running(True)
        self._monitor_thread = QThread(self)
        self._monitor_worker = MonitorWorker(self.config)
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
        if self._monitor_worker is not None:
            self._set_status("status", "stopping")
            self._monitor_worker.stop()
        self.stop_button.setEnabled(False)

    def _on_monitor_finished(self, alert_count: int) -> None:
        self._append_log(f"Monitor stopped, alerts={alert_count}")
        self._monitor_worker = None
        self._monitor_thread = None
        self._set_running(False)

    def _on_monitor_failed(self, message: str) -> None:
        self._append_log(message)
        QMessageBox.critical(self, "监控失败", _dialog_message(message))

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
        self._populate_active_table(cycle.timestamp, cycle.evaluations)

    def _on_alert(self, event: AlertEvent) -> None:
        follow_latest = _table_is_at_bottom(self.alert_table)
        self.alert_view.append_record(event.timestamp, event.evaluation, scroll_to_bottom=follow_latest)

    def _populate_active_table(
        self,
        timestamp: str,
        evaluations: tuple[ConditionEvaluation, ...],
    ) -> None:
        active = [evaluation for evaluation in evaluations if evaluation.active]
        self.active_view.set_records(_EvaluationRecord(timestamp, evaluation) for evaluation in active)

    def _set_strategy_filters(self, config: AppConfig) -> None:
        strategy_names = [strategy.name or strategy.type for strategy in config.selected_strategies]
        self.active_view.set_strategy_names(strategy_names)
        self.alert_view.set_strategy_names(strategy_names)

    def _save_config(self) -> None:
        try:
            config = self.config_editor.build_config()
            save_config(self.config_path, config)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.config = config
        self._set_strategy_filters(config)
        suffix = "；当前监控继续使用启动时的配置" if self._running else ""
        self._append_log(f"Saved config: {self.config_path}{suffix}")

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


class StrategyEvaluationTable(QGroupBox):
    def __init__(self, title: str) -> None:
        super().__init__(title)
        self._configured_strategy_names: tuple[str, ...] = ()
        self._strategy_names: tuple[str, ...] = ()
        self._selected_strategy: str | None = None
        self._records: list[_EvaluationRecord] = []
        self._buttons: dict[str | None, QPushButton] = {}
        self._include_strategy_column: bool | None = None

        layout = QVBoxLayout(self)
        filter_row = QHBoxLayout()
        self._filter_layout = QHBoxLayout()
        filter_row.addLayout(self._filter_layout)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, 0)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self._rebuild_filter_buttons()
        self._render()

    def set_strategy_names(self, strategy_names: Iterable[str]) -> None:
        self._configured_strategy_names = _unique_names(strategy_names)
        self._sync_strategy_buttons()
        self._render()

    def filter_labels(self) -> tuple[str, ...]:
        return tuple(button.text() for button in self._buttons.values())

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
        self._ensure_table_shape(include_strategy)
        vertical_scroll = self.table.verticalScrollBar()
        horizontal_scroll = self.table.horizontalScrollBar()
        previous_vertical = vertical_scroll.value() if preserve_scroll else 0
        previous_horizontal = horizontal_scroll.value() if preserve_scroll else 0
        records = [
            record
            for record in self._records
            if include_strategy or record.evaluation.strategy_name == self._selected_strategy
        ]
        self.table.setRowCount(0)
        for record in records:
            self._append_row(record, include_strategy)
        if scroll_to_bottom:
            self.table.scrollToBottom()
        elif preserve_scroll:
            vertical_scroll.setValue(min(previous_vertical, vertical_scroll.maximum()))
            horizontal_scroll.setValue(min(previous_horizontal, horizontal_scroll.maximum()))

    def _ensure_table_shape(self, include_strategy: bool) -> None:
        if self._include_strategy_column == include_strategy:
            return
        self._include_strategy_column = include_strategy
        if include_strategy:
            headers = ("时间", "策略名", "值", "阈值", "合约", "消息")
            widths = (165, 130, 100, 100, 280, 420)
        else:
            headers = ("时间", "值", "阈值", "合约", "消息")
            widths = (165, 100, 100, 280, 420)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        _configure_resizable_columns(self.table, widths)

    def _append_row(self, record: _EvaluationRecord, include_strategy: bool) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        evaluation = record.evaluation
        values = [
            _format_table_timestamp(record.timestamp),
            f"{evaluation.value:.8f}",
            f"{evaluation.threshold:.8f}",
            ", ".join(evaluation.symbols),
            evaluation.message,
        ]
        numeric_columns = (1, 2)
        if include_strategy:
            values.insert(1, evaluation.strategy_name)
            numeric_columns = (2, 3)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column in numeric_columns:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, column, item)


class ConfigEditor(QWidget):
    def __init__(self) -> None:
        super().__init__()
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
        self.universe_mode = NoWheelComboBox()
        self.universe_mode.addItems(("all", "underlyings", "symbols"))
        self.underlyings = QTextEdit()
        self.underlyings.setFixedHeight(70)
        self.symbols = QTextEdit()
        self.symbols.setFixedHeight(70)
        self.exchange_ids = QLineEdit()
        self.min_volume = _double_spin()
        self.min_open_interest = _double_spin()
        form.addRow("模式", self.universe_mode)
        form.addRow("标的", self.underlyings)
        form.addRow("指定合约", self.symbols)
        form.addRow("交易所", self.exchange_ids)
        form.addRow("最小成交量", self.min_volume)
        form.addRow("最小持仓量", self.min_open_interest)
        self.content_layout.addWidget(box)

    def _build_strategies(self) -> None:
        box = QGroupBox("策略")
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        add_button = QPushButton("添加")
        add_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder))
        add_button.clicked.connect(lambda: self._add_strategy_row("cp_combo", 0.01, "", True))
        remove_button = QPushButton("删除")
        remove_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        remove_button.clicked.connect(self._remove_strategy_row)
        row.addWidget(add_button)
        row.addWidget(remove_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.strategies = QTableWidget(0, 4)
        self.strategies.setHorizontalHeaderLabels(("选中", "类型", "阈值", "名称"))
        self.strategies.setAlternatingRowColors(True)
        self.strategies.setMinimumHeight(180)
        self.strategies.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.strategies.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.strategies.verticalHeader().setDefaultSectionSize(36)
        self.strategies.verticalHeader().setMinimumSectionSize(32)
        self.strategies.verticalHeader().setVisible(False)
        _configure_resizable_columns(self.strategies, (70, 130, 110, 180))
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
        self.notifier_kind = NoWheelComboBox()
        self.notifier_kind.addItems(("", "console", "email"))
        self.alert_log_path = QLineEdit()
        self.smtp_host = QLineEdit()
        self.smtp_port = _spin(1, 65535)
        self.smtp_timeout_seconds = _spin(1, 300)
        self.alert_interval_seconds = _spin(0, 86400)
        self.email_username = QLineEdit()
        self.email_password_env = QLineEdit()
        self.from_addr = QLineEdit()
        self.to_addrs = QLineEdit()
        self.use_tls = QCheckBox()
        self.failure_backoff_seconds = _spin(0, 86400)
        form.addRow("通知方式", self.notifier_kind)
        form.addRow("预警日志", self.alert_log_path)
        form.addRow("SMTP主机", self.smtp_host)
        form.addRow("SMTP端口", self.smtp_port)
        form.addRow("SMTP超时", self.smtp_timeout_seconds)
        form.addRow("邮件聚合秒数", self.alert_interval_seconds)
        form.addRow("邮箱账号", self.email_username)
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
        self.underlyings.setPlainText("\n".join(config.universe.underlyings))
        self.symbols.setPlainText("\n".join(config.universe.symbols))
        self.exchange_ids.setText(", ".join(config.universe.exchange_ids))
        self.min_volume.setValue(config.universe.min_volume)
        self.min_open_interest.setValue(config.universe.min_open_interest)
        self.strategies.setRowCount(0)
        for strategy in config.strategies:
            self._add_strategy_row(strategy.type, strategy.threshold, strategy.name or "", strategy.selected)
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
        self.username_env.setText(config.tqsdk.username_env)
        self.password_env.setText(config.tqsdk.password_env)
        self.symbol_info_batch_size.setValue(config.tqsdk.symbol_info_batch_size)
        self.quote_subscription_batch_size.setValue(config.tqsdk.quote_subscription_batch_size)
        self.notifier_kind.setCurrentText(config.notifier.kind or "")
        self.alert_log_path.setText(config.notifier.alert_log_path)
        self.smtp_host.setText(config.notifier.email.smtp_host or "")
        self.smtp_port.setValue(config.notifier.email.smtp_port)
        self.smtp_timeout_seconds.setValue(config.notifier.email.smtp_timeout_seconds)
        self.alert_interval_seconds.setValue(config.notifier.email.alert_interval_seconds)
        self.email_username.setText(config.notifier.email.username or "")
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
                "underlyings": _split_lines(self.underlyings.toPlainText()),
                "symbols": _split_lines(self.symbols.toPlainText()),
                "exchange_ids": _split_csv(self.exchange_ids.text()),
                "min_volume": self.min_volume.value(),
                "min_open_interest": self.min_open_interest.value(),
            },
            "datasource": {
                "tqsdk": {
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
                "kind": self.notifier_kind.currentText() or None,
                "alert_log_path": self.alert_log_path.text().strip() or "logs/alerts.jsonl",
                "email": {
                    "smtp_host": self.smtp_host.text().strip() or None,
                    "smtp_port": self.smtp_port.value(),
                    "smtp_timeout_seconds": self.smtp_timeout_seconds.value(),
                    "alert_interval_seconds": self.alert_interval_seconds.value(),
                    "username": self.email_username.text().strip() or None,
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
                "log_file": self.log_file.text().strip() or "kuaiqi.log",
                "max_bytes": self.max_bytes.value(),
                "backup_count": self.backup_count.value(),
                "cycle_summary_interval_seconds": self.cycle_summary_interval_seconds.value(),
            },
        }

    def _strategy_data(self) -> list[dict[str, Any]]:
        rows = []
        for row in range(self.strategies.rowCount()):
            selected = _table_checked(self.strategies, row, 0)
            strategy_type = _table_text(self.strategies, row, 1) or "cp_combo"
            threshold = float(_table_text(self.strategies, row, 2) or "0")
            name = _table_text(self.strategies, row, 3)
            item = {"type": strategy_type, "threshold": threshold, "selected": selected}
            if name:
                item["name"] = name
            rows.append(item)
        return rows

    def _add_strategy_row(self, strategy_type: str, threshold: float, name: str, selected: bool = True) -> None:
        row = self.strategies.rowCount()
        self.strategies.insertRow(row)
        selected_item = QTableWidgetItem()
        selected_item.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        selected_item.setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)
        selected_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.strategies.setItem(row, 0, selected_item)
        self.strategies.setItem(row, 1, QTableWidgetItem(strategy_type))
        self.strategies.setItem(row, 2, QTableWidgetItem(str(threshold)))
        self.strategies.setItem(row, 3, QTableWidgetItem(name))

    def _remove_strategy_row(self) -> None:
        row = self.strategies.currentRow()
        if row >= 0:
            self.strategies.removeRow(row)


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


def _dialog_message(message: str) -> str:
    if len(message) <= DIALOG_MESSAGE_LIMIT:
        return message
    return (
        f"{message[:DIALOG_MESSAGE_LIMIT]}\n\n"
        "……消息过长，已截断；完整内容请查看日志面板或日志文件。"
    )


def _configure_resizable_columns(table: QTableWidget, widths: tuple[int, ...]) -> None:
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setMinimumSectionSize(50)
    for column, width in enumerate(widths):
        table.setColumnWidth(column, width)


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


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]


def _split_lines(value: str) -> list[str]:
    result = []
    for line in value.replace(",", "\n").splitlines():
        item = line.strip()
        if item:
            result.append(item)
    return result


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
            padding: 6px;
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
