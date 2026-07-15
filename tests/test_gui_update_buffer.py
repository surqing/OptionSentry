from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from optionsentry.gui.app import (
    GUI_ALERT_MAX_PENDING_EVENTS,
    GUI_LOG_MAX_PENDING_MESSAGES,
    MonitorWorker,
    StrategyEvaluationTable,
    _EvaluationRecord,
)
from optionsentry.models import AlertEvent, ConditionEvaluation
from optionsentry.runner import RunnerCycle


class GuiUpdateBufferTests(unittest.TestCase):
    def test_high_frequency_cycles_are_coalesced_to_latest(self) -> None:
        worker = MonitorWorker(None, Path("config.toml"))  # type: ignore[arg-type]

        for cycle_count in range(10_000):
            worker._store_latest_cycle(_cycle(cycle_count))

        cycle, logs, dropped_logs, alerts, dropped_alerts = worker.take_pending_updates()

        self.assertIsNotNone(cycle)
        self.assertEqual(cycle.cycle_count, 9_999)
        self.assertEqual(logs, ())
        self.assertEqual(dropped_logs, 0)
        self.assertEqual(alerts, ())
        self.assertEqual(dropped_alerts, 0)
        self.assertEqual(worker.take_pending_updates()[0], None)

    def test_log_and_alert_buffers_are_bounded_and_keep_newest_items(self) -> None:
        worker = MonitorWorker(None, Path("config.toml"))  # type: ignore[arg-type]
        overflow = 25
        for index in range(GUI_LOG_MAX_PENDING_MESSAGES + overflow):
            worker._buffer_log(f"log-{index}")
        for index in range(GUI_ALERT_MAX_PENDING_EVENTS + overflow):
            worker._buffer_alert(_alert(index))

        _, logs, dropped_logs, alerts, dropped_alerts = worker.take_pending_updates(
            log_limit=GUI_LOG_MAX_PENDING_MESSAGES,
            alert_limit=GUI_ALERT_MAX_PENDING_EVENTS,
        )

        self.assertEqual(len(logs), GUI_LOG_MAX_PENDING_MESSAGES)
        self.assertEqual(logs[0], f"log-{overflow}")
        self.assertEqual(logs[-1], f"log-{GUI_LOG_MAX_PENDING_MESSAGES + overflow - 1}")
        self.assertEqual(dropped_logs, overflow)
        self.assertEqual(len(alerts), GUI_ALERT_MAX_PENDING_EVENTS)
        self.assertEqual(alerts[0].evaluation.value, float(overflow))
        self.assertEqual(
            alerts[-1].evaluation.value,
            float(GUI_ALERT_MAX_PENDING_EVENTS + overflow - 1),
        )
        self.assertEqual(dropped_alerts, overflow)

    def test_alert_table_batches_updates_and_keeps_a_bounded_history(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        table = StrategyEvaluationTable("alerts", max_records=3)

        with patch.object(table, "_render", wraps=table._render) as render:
            table.append_records(
                (_EvaluationRecord(str(index), _alert(index).evaluation) for index in range(5))
            )
            render.assert_not_called()
        app.processEvents()

        self.assertEqual(len(table._records), 3)
        self.assertEqual([record.evaluation.value for record in table._records], [2.0, 3.0, 4.0])
        self.assertEqual(table.table.rowCount(), 3)
        table.deleteLater()


def _cycle(cycle_count: int) -> RunnerCycle:
    return RunnerCycle(
        cycle_count=cycle_count,
        timestamp=str(cycle_count),
        evaluations=(),
        total_conditions=0,
        active_count=0,
        alerts=(),
        total_alerts=0,
        changed_count=0,
        compute_ms=0.0,
    )


def _alert(index: int) -> AlertEvent:
    return AlertEvent(
        timestamp=str(index),
        evaluation=ConditionEvaluation(
            key=f"key-{index}",
            strategy_name="strategy",
            active=True,
            value=float(index),
            min_value=0.0,
            max_value=1.0,
            symbols=("SHFE.au2608",),
            message=f"alert-{index}",
        ),
    )


if __name__ == "__main__":
    unittest.main()
