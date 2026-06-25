from __future__ import annotations

import unittest

from kuaiqi.alerts import AlertEngine
from kuaiqi.models import ConditionEvaluation


def evaluation(active: bool) -> ConditionEvaluation:
    return ConditionEvaluation(
        key="strategy:key",
        strategy_name="strategy",
        active=active,
        value=1.0,
        threshold=0.1,
        symbols=("A", "B"),
        message="message",
    )


class AlertEngineTests(unittest.TestCase):
    def test_first_active_does_not_alert_by_default(self) -> None:
        engine = AlertEngine()

        events = engine.process([evaluation(True)], "t1")

        self.assertEqual(events, [])

    def test_false_to_true_alerts_once(self) -> None:
        engine = AlertEngine()

        self.assertEqual(engine.process([evaluation(False)], "t1"), [])
        events = engine.process([evaluation(True)], "t2")
        self.assertEqual(len(events), 1)
        self.assertEqual(engine.process([evaluation(True)], "t3"), [])

    def test_true_false_true_alerts_again(self) -> None:
        engine = AlertEngine(alert_on_first_match=True)

        self.assertEqual(len(engine.process([evaluation(True)], "t1")), 1)
        self.assertEqual(engine.process([evaluation(False)], "t2"), [])
        self.assertEqual(len(engine.process([evaluation(True)], "t3")), 1)


if __name__ == "__main__":
    unittest.main()
