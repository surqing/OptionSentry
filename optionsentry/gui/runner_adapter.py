from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable

from optionsentry.alerts import AlertEngine
from optionsentry.config import AppConfig
from optionsentry.data_sources import TqSdkDataSource
from optionsentry.logging_config import setup_logging
from optionsentry.models import AlertEvent
from optionsentry.notifiers import build_notifier
from optionsentry.runner import AlertRunner, RunnerCallbacks, RunnerCycle
from optionsentry.strategies import build_strategy


@dataclass
class GuiRunSignals:
    on_status: Callable[[str], None] | None = None
    on_log: Callable[[str], None] | None = None
    on_universe: Callable[[object], None] | None = None
    on_compiled: Callable[[int, int], None] | None = None
    on_cycle: Callable[[RunnerCycle], None] | None = None
    on_alert: Callable[[AlertEvent], None] | None = None


@dataclass
class GuiRunContext:
    runner: AlertRunner
    stop_event: Event
    logger: logging.Logger
    gui_log_handler: logging.Handler | None = None

    def stop(self) -> None:
        self.stop_event.set()
        self.runner.data_source.close()


def build_gui_runner(config: AppConfig, signals: GuiRunSignals, config_path: str | Path = "config.toml") -> GuiRunContext:
    stop_event = Event()
    logger = setup_logging(config.logging, config.runtime.mode)
    gui_log_handler = None
    if signals.on_log is not None:
        gui_log_handler = _CallbackLogHandler(signals.on_log)
        gui_log_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(gui_log_handler)
    data_source = TqSdkDataSource(
        config=config,
        logger=logger,
        stop_requested=stop_event.is_set,
        status_callback=signals.on_status,
    )
    runner = AlertRunner(
        data_source=data_source,
        strategies=tuple(build_strategy(strategy) for strategy in config.enabled_strategies),
        alert_engine=AlertEngine(alert_on_first_match=config.runtime.alert_on_first_match),
        notifier=build_notifier(config),
        logger=logger,
        config_dir=Path(config_path).resolve().parent,
        cycle_summary_interval_seconds=config.logging.cycle_summary_interval_seconds,
        stop_requested=stop_event.is_set,
        callbacks=RunnerCallbacks(
            on_status=signals.on_status,
            on_universe=signals.on_universe,
            on_compiled=signals.on_compiled,
            on_cycle=signals.on_cycle,
            on_alert=signals.on_alert,
        ),
    )
    return GuiRunContext(
        runner=runner,
        stop_event=stop_event,
        logger=logger,
        gui_log_handler=gui_log_handler,
    )


class _CallbackLogHandler(logging.Handler):
    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self.callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        self.callback(self.format(record))
