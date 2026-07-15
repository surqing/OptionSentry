from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MonitorState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    DISCOVERING = "discovering"
    COMPILING = "compiling"
    SUBSCRIBING = "subscribing"
    WAITING_DATA = "waiting_data"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"
    EMPTY_UNIVERSE = "empty_universe"
    EMPTY_CONDITIONS = "empty_conditions"


MONITOR_STATE_LABELS: dict[MonitorState, str] = {
    MonitorState.STOPPED: "已停止",
    MonitorState.STARTING: "启动中",
    MonitorState.DISCOVERING: "发现合约",
    MonitorState.COMPILING: "编译策略",
    MonitorState.SUBSCRIBING: "订阅行情",
    MonitorState.WAITING_DATA: "等待行情",
    MonitorState.RUNNING: "运行中",
    MonitorState.STOPPING: "停止中",
    MonitorState.FAILED: "运行失败",
    MonitorState.EMPTY_UNIVERSE: "没有可监控合约",
    MonitorState.EMPTY_CONDITIONS: "没有可执行条件",
}

TERMINAL_MONITOR_STATES = frozenset(
    {
        MonitorState.STOPPED,
        MonitorState.FAILED,
        MonitorState.EMPTY_UNIVERSE,
        MonitorState.EMPTY_CONDITIONS,
    }
)

_RESTARTABLE_STATES = TERMINAL_MONITOR_STATES
_ACTIVE_STATES = frozenset(
    {
        MonitorState.STARTING,
        MonitorState.DISCOVERING,
        MonitorState.COMPILING,
        MonitorState.SUBSCRIBING,
        MonitorState.WAITING_DATA,
        MonitorState.RUNNING,
        MonitorState.STOPPING,
    }
)
_ALLOWED_TRANSITIONS: dict[MonitorState, frozenset[MonitorState]] = {
    MonitorState.STOPPED: frozenset({MonitorState.STARTING, MonitorState.FAILED}),
    MonitorState.FAILED: frozenset({MonitorState.STARTING}),
    MonitorState.EMPTY_UNIVERSE: frozenset({MonitorState.STARTING, MonitorState.FAILED}),
    MonitorState.EMPTY_CONDITIONS: frozenset({MonitorState.STARTING, MonitorState.FAILED}),
    MonitorState.STARTING: frozenset(
        {
            MonitorState.DISCOVERING,
            MonitorState.STOPPING,
            MonitorState.STOPPED,
            MonitorState.FAILED,
        }
    ),
    MonitorState.DISCOVERING: frozenset(
        {
            MonitorState.COMPILING,
            MonitorState.EMPTY_UNIVERSE,
            MonitorState.STOPPING,
            MonitorState.STOPPED,
            MonitorState.FAILED,
        }
    ),
    MonitorState.COMPILING: frozenset(
        {
            MonitorState.SUBSCRIBING,
            MonitorState.EMPTY_CONDITIONS,
            MonitorState.STOPPING,
            MonitorState.STOPPED,
            MonitorState.FAILED,
        }
    ),
    MonitorState.SUBSCRIBING: frozenset(
        {
            MonitorState.WAITING_DATA,
            MonitorState.RUNNING,
            MonitorState.STOPPING,
            MonitorState.STOPPED,
            MonitorState.FAILED,
        }
    ),
    MonitorState.WAITING_DATA: frozenset(
        {
            MonitorState.RUNNING,
            MonitorState.STOPPING,
            MonitorState.STOPPED,
            MonitorState.FAILED,
        }
    ),
    MonitorState.RUNNING: frozenset(
        {
            MonitorState.SUBSCRIBING,
            MonitorState.STOPPING,
            MonitorState.STOPPED,
            MonitorState.FAILED,
        }
    ),
    MonitorState.STOPPING: frozenset(
        {
            MonitorState.STOPPED,
            MonitorState.FAILED,
        }
    ),
}


class InvalidMonitorStateTransition(ValueError):
    pass


@dataclass(slots=True)
class MonitorStateMachine:
    state: MonitorState = MonitorState.STOPPED

    def transition(self, target: MonitorState | str) -> bool:
        next_state = MonitorState(target)
        if next_state == self.state:
            return False
        if next_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise InvalidMonitorStateTransition(
                f"Invalid monitor state transition: {self.state.value} -> {next_state.value}"
            )
        self.state = next_state
        return True

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_MONITOR_STATES

    @property
    def can_restart(self) -> bool:
        return self.state in _RESTARTABLE_STATES

    @property
    def is_active(self) -> bool:
        return self.state in _ACTIVE_STATES


def monitor_state_label(state: MonitorState | str) -> str:
    return MONITOR_STATE_LABELS[MonitorState(state)]
