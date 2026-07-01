from __future__ import annotations

from dataclasses import dataclass, field

from optionsentry.models import AlertEvent, ConditionEvaluation


@dataclass
class AlertEngine:
    alert_on_first_match: bool = False
    _states: dict[str, bool] = field(default_factory=dict)

    def process(self, evaluations: list[ConditionEvaluation], timestamp: str) -> list[AlertEvent]:
        events: list[AlertEvent] = []
        for evaluation in evaluations:
            previous = self._states.get(evaluation.key)
            self._states[evaluation.key] = evaluation.active
            if self._should_alert(previous, evaluation.active):
                events.append(AlertEvent(timestamp=timestamp, evaluation=evaluation))
        return events

    def active_count(self) -> int:
        return sum(1 for active in self._states.values() if active)

    def _should_alert(self, previous: bool | None, current: bool) -> bool:
        if not current:
            return False
        if previous is False:
            return True
        if previous is None and self.alert_on_first_match:
            return True
        return False
