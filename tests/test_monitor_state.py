from __future__ import annotations

import unittest

from optionsentry.monitor_state import (
    InvalidMonitorStateTransition,
    MonitorState,
    MonitorStateMachine,
    monitor_state_label,
)


class MonitorStateMachineTests(unittest.TestCase):
    def test_live_state_sequence_and_chinese_labels(self) -> None:
        machine = MonitorStateMachine()
        sequence = (
            MonitorState.STARTING,
            MonitorState.DISCOVERING,
            MonitorState.COMPILING,
            MonitorState.SUBSCRIBING,
            MonitorState.WAITING_DATA,
            MonitorState.RUNNING,
            MonitorState.STOPPING,
            MonitorState.STOPPED,
        )

        labels = []
        for state in sequence:
            machine.transition(state)
            labels.append(monitor_state_label(machine.state))

        self.assertEqual(
            labels,
            [
                "启动中",
                "发现合约",
                "编译策略",
                "订阅行情",
                "等待行情",
                "运行中",
                "停止中",
                "已停止",
            ],
        )
        self.assertTrue(machine.is_terminal)
        self.assertTrue(machine.can_restart)
        self.assertFalse(machine.is_active)

    def test_failure_and_empty_states_are_preserved_until_restart(self) -> None:
        for terminal_state in (
            MonitorState.FAILED,
            MonitorState.EMPTY_UNIVERSE,
            MonitorState.EMPTY_CONDITIONS,
        ):
            with self.subTest(terminal_state=terminal_state):
                machine = MonitorStateMachine()
                machine.transition(MonitorState.STARTING)
                if terminal_state is MonitorState.EMPTY_UNIVERSE:
                    machine.transition(MonitorState.DISCOVERING)
                elif terminal_state is MonitorState.EMPTY_CONDITIONS:
                    machine.transition(MonitorState.DISCOVERING)
                    machine.transition(MonitorState.COMPILING)
                machine.transition(terminal_state)

                with self.assertRaises(InvalidMonitorStateTransition):
                    machine.transition(MonitorState.STOPPED)

                machine.transition(MonitorState.STARTING)
                self.assertEqual(machine.state, MonitorState.STARTING)

    def test_invalid_phase_regression_is_rejected(self) -> None:
        machine = MonitorStateMachine()
        machine.transition(MonitorState.STARTING)
        machine.transition(MonitorState.DISCOVERING)
        machine.transition(MonitorState.COMPILING)
        machine.transition(MonitorState.SUBSCRIBING)
        machine.transition(MonitorState.WAITING_DATA)

        with self.assertRaisesRegex(
            InvalidMonitorStateTransition,
            "waiting_data -> compiling",
        ):
            machine.transition(MonitorState.COMPILING)


if __name__ == "__main__":
    unittest.main()
