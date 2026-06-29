from __future__ import annotations

import json
import smtplib
import tempfile
import unittest
from email.header import decode_header, make_header
from email import message_from_string
from pathlib import Path
from unittest.mock import patch

from kuaiqi.config import EmailConfig, parse_config
from kuaiqi.models import AlertEvent, ConditionEvaluation
from kuaiqi.notifiers import (
    CompositeNotifier,
    EmailNotifier,
    JsonlAlertRecorder,
    NotificationError,
    build_notifier,
)


class NotifierTests(unittest.TestCase):
    def test_email_batches_alerts_by_configured_interval(self) -> None:
        email = EmailNotifier(
            EmailConfig(
                smtp_host="smtp.example.com",
                from_addr="from@example.com",
                to_addrs=("to@example.com",),
                alert_interval_seconds=60,
            )
        )

        with (
            patch("kuaiqi.notifiers.smtplib.SMTP", _CapturingSMTP),
            patch("kuaiqi.notifiers.time.monotonic", side_effect=[0.0, 30.0, 59.0, 60.0]),
        ):
            _CapturingSMTP.calls = 0
            _CapturingSMTP.messages = []
            email.notify(
                _event(
                    timestamp="t1",
                    key="cp_combo:SHFE.au2608:2026-8:K=600:SHFE.au2608C600:SHFE.au2608P600",
                    strategy_name="cp_combo",
                    value=0.03559322,
                    threshold=0.01,
                    symbols=("SHFE.au2608C600", "SHFE.au2608P600", "SHFE.au2608"),
                )
            )
            email.notify(
                _event(
                    timestamp="t2",
                    key=(
                        "abs_spread:GFEX.lc2608:2026-7:PUT:"
                        "GFEX.lc2608-P-128000:GFEX.lc2608-P-130000"
                    ),
                    strategy_name="abs_spread",
                    value=0.08,
                    threshold=0.1,
                    symbols=("GFEX.lc2608-P-128000", "GFEX.lc2608-P-130000"),
                )
            )
            email.flush()
            self.assertEqual(_CapturingSMTP.calls, 0)

            email.flush()

        self.assertEqual(_CapturingSMTP.calls, 1)
        message = message_from_string(_CapturingSMTP.messages[0])
        plain_body = _message_part(message, "text/plain")
        html_body = _message_part(message, "text/html")
        self.assertEqual(_decoded_header(message["Subject"]), "KuaiQi 预警汇总: 2 条")
        self.assertIn("本次邮件包含 2 条新触发预警", plain_body)
        self.assertIn("触发时间 | 预警类型 | 监控对象 | 方向/结构", plain_body)
        self.assertIn("CP组合预警", plain_body)
        self.assertIn("价差预警", plain_body)
        self.assertIn("K=600", plain_body)
        self.assertIn("128000 / 130000", plain_body)
        self.assertNotIn("预警说明", plain_body)
        self.assertIn("<table", html_body)
        self.assertIn("触发时间", html_body)
        self.assertIn("预警类型", html_body)
        self.assertIn("当前指标值", html_body)
        self.assertNotIn("预警说明", html_body)
        self.assertIn("本次邮件包含 2 条新触发预警", html_body)
        self.assertIn("CP组合预警", html_body)
        self.assertIn("价差预警", html_body)
        self.assertIn("认购 + 认沽 + 标的", html_body)
        self.assertIn("认沽", html_body)
        self.assertIn("偏离率大于阈值（0.01）", plain_body)
        self.assertIn("价差比例小于阈值（0.1）", plain_body)
        self.assertIn("价差比例小于阈值（0.1）", html_body)

    def test_email_failure_enters_backoff_and_recorder_keeps_writing(self) -> None:
        event = _event()
        email = EmailNotifier(
            EmailConfig(
                smtp_host="smtp.example.com",
                from_addr="from@example.com",
                to_addrs=("to@example.com",),
                alert_interval_seconds=60,
                failure_backoff_seconds=300,
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            recorder_path = Path(tmpdir) / "alerts.jsonl"
            notifier = CompositeNotifier((email, JsonlAlertRecorder(recorder_path)))

            with patch("kuaiqi.notifiers.smtplib.SMTP", _FailingSMTP):
                _FailingSMTP.calls = 0
                notifier.notify(event)
                with self.assertRaises(NotificationError):
                    notifier.flush(force=True)
                notifier.notify(event)
                notifier.flush(force=True)

            self.assertEqual(_FailingSMTP.calls, 1)
            self.assertEqual(len(recorder_path.read_text(encoding="utf-8").splitlines()), 2)

    def test_build_notifier_scopes_alert_log_by_runtime_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = parse_config(
                {
                    "runtime": {"mode": "backtest"},
                    "backtest": {"start_dt": "2026-01-02", "end_dt": "2026-01-05"},
                    "notifier": {
                        "kind": "console",
                        "alert_log_path": str(Path(tmpdir) / "alerts.jsonl"),
                    },
                    "strategies": [{"type": "cp_combo", "threshold": 0.01}],
                }
            )
            notifier = build_notifier(config)

            notifier.notify(_event())

            recorder_path = Path(tmpdir) / "backtest" / "alerts.jsonl"
            payload = json.loads(recorder_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(payload["metadata"]["mode"], "backtest")


class _CapturingSMTP:
    calls = 0
    messages: list[str] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        type(self).calls += 1

    def __enter__(self) -> "_CapturingSMTP":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def starttls(self) -> None:
        return None

    def login(self, username: str, password: str) -> None:
        return None

    def sendmail(self, from_addr: str | None, to_addrs: list[str], message: str) -> None:
        type(self).messages.append(message)


class _FailingSMTP:
    calls = 0

    def __init__(self, *args: object, **kwargs: object) -> None:
        type(self).calls += 1
        raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")


def _decoded_header(value: str) -> str:
    return str(make_header(decode_header(value)))


def _message_part(message: object, content_type: str) -> str:
    for part in message.walk():
        if part.get_content_type() == content_type:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            return payload.decode(charset)
    raise AssertionError(f"Missing message part: {content_type}")


def _event(
    timestamp: str = "t1",
    key: str = "strategy:key",
    strategy_name: str = "strategy",
    value: float = 1.0,
    threshold: float = 0.1,
    symbols: tuple[str, ...] = ("A", "B"),
    message: str = "message",
) -> AlertEvent:
    return AlertEvent(
        timestamp=timestamp,
        evaluation=ConditionEvaluation(
            key=key,
            strategy_name=strategy_name,
            active=True,
            value=value,
            threshold=threshold,
            symbols=symbols,
            message=message,
        ),
    )


if __name__ == "__main__":
    unittest.main()
