from __future__ import annotations

import json
import os
import smtplib
import time
from collections import Counter
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from pathlib import Path
from typing import Protocol

from kuaiqi.config import AppConfig, ConfigError, EmailConfig
from kuaiqi.log_paths import mode_scoped_file
from kuaiqi.models import AlertEvent


class NotificationError(RuntimeError):
    pass


class Notifier(Protocol):
    def notify(self, event: AlertEvent) -> None:
        ...


@dataclass
class ConsoleNotifier:
    def notify(self, event: AlertEvent) -> None:
        print(_event_text(event), flush=True)


@dataclass
class EmailNotifier:
    config: EmailConfig
    _disabled_until: float = field(default=0.0, init=False)
    _pending_events: list[AlertEvent] = field(default_factory=list, init=False)
    _next_send_at: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not self.config.smtp_host:
            raise ConfigError("Email notifier requires smtp_host or SMTP_HOST.")
        if not self.config.from_addr:
            raise ConfigError("Email notifier requires from_addr or ALERT_EMAIL_FROM.")
        if not self.config.to_addrs:
            raise ConfigError("Email notifier requires to_addrs or ALERT_EMAIL_TO.")

    def notify(self, event: AlertEvent) -> None:
        now = time.monotonic()
        self._pending_events.append(event)
        if self._next_send_at is None:
            self._next_send_at = now + self.config.alert_interval_seconds
        self._flush_due(force=self.config.alert_interval_seconds == 0, now=now)

    def flush(self, force: bool = False) -> None:
        self._flush_due(force=force, now=time.monotonic())

    def _flush_due(self, force: bool, now: float) -> None:
        if not self._pending_events:
            return
        if now < self._disabled_until:
            return
        if not force and self._next_send_at is not None and now < self._next_send_at:
            return
        events = tuple(self._pending_events)
        try:
            self._send(events)
        except Exception:
            if self.config.failure_backoff_seconds > 0:
                self._disabled_until = time.monotonic() + self.config.failure_backoff_seconds
            raise
        self._pending_events.clear()
        self._next_send_at = None

    def _send(self, events: tuple[AlertEvent, ...]) -> None:
        subject = _email_subject(events)
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = self.config.from_addr or ""
        message["To"] = ",".join(self.config.to_addrs)
        message.attach(MIMEText(_email_plain_body(events), "plain", "utf-8"))
        message.attach(MIMEText(_email_html_body(events), "html", "utf-8"))

        password = os.environ.get(self.config.password_env)
        with smtplib.SMTP(
            self.config.smtp_host,
            self.config.smtp_port,
            timeout=self.config.smtp_timeout_seconds,
        ) as smtp:
            if self.config.use_tls:
                smtp.starttls()
            if self.config.username:
                smtp.login(self.config.username, password or "")
            smtp.sendmail(self.config.from_addr, list(self.config.to_addrs), message.as_string())


@dataclass(frozen=True)
class _EmailAlertRow:
    timestamp: str
    strategy_label: str
    monitor: str
    structure: str
    strike: str
    value: str
    threshold: str
    trigger_condition: str
    symbols: str


@dataclass
class JsonlAlertRecorder:
    path: Path
    metadata: dict[str, object] = field(default_factory=dict)

    def notify(self, event: AlertEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fp:
            fp.write(
                json.dumps(
                    _event_payload(event, extra_metadata=self.metadata),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            fp.write("\n")


@dataclass
class CompositeNotifier:
    notifiers: tuple[Notifier, ...]

    def notify(self, event: AlertEvent) -> None:
        errors: list[Exception] = []
        for notifier in self.notifiers:
            try:
                notifier.notify(event)
            except Exception as exc:
                errors.append(exc)
        if errors:
            first = errors[0]
            raise NotificationError(
                f"{len(errors)} notifier(s) failed: {type(first).__name__}: {first}"
            ) from first

    def flush(self, force: bool = False) -> None:
        errors: list[Exception] = []
        for notifier in self.notifiers:
            flush = getattr(notifier, "flush", None)
            if flush is None:
                continue
            try:
                flush(force=force)
            except Exception as exc:
                errors.append(exc)
        if errors:
            first = errors[0]
            raise NotificationError(
                f"{len(errors)} notifier(s) failed during flush: {type(first).__name__}: {first}"
            ) from first


def build_notifier(config: AppConfig) -> Notifier:
    kind = config.notifier.kind or ("email" if config.runtime.mode == "live" else "console")
    if kind == "email":
        primary: Notifier = EmailNotifier(config.notifier.email)
    elif kind == "console":
        primary = ConsoleNotifier()
    else:
        raise ConfigError(f"Unsupported notifier kind: {kind}")
    recorder = JsonlAlertRecorder(
        mode_scoped_file(Path(config.notifier.alert_log_path), config.runtime.mode),
        metadata={"mode": config.runtime.mode},
    )
    return CompositeNotifier((primary, recorder))


def _event_text(event: AlertEvent) -> str:
    return f"[{event.timestamp}] {event.evaluation.message}"


def _email_subject(events: tuple[AlertEvent, ...]) -> str:
    if len(events) == 1:
        return f"KuaiQi 预警: {events[0].evaluation.strategy_name}"
    return f"KuaiQi 预警汇总: {len(events)} 条"


def _email_plain_body(events: tuple[AlertEvent, ...]) -> str:
    rows = _email_rows(events)
    lines = [
        "KuaiQi 预警汇总",
        _email_summary_text(events),
        "",
        "触发时间 | 预警类型 | 监控对象 | 方向/结构 | 执行价 | 当前指标值 | 阈值 | 触发条件 | 相关合约",
        "--- | --- | --- | --- | --- | --- | --- | --- | ---",
    ]
    for row in rows:
        lines.append(
            " | ".join(
                (
                    row.timestamp,
                    row.strategy_label,
                    row.monitor,
                    row.structure,
                    row.strike,
                    row.value,
                    row.threshold,
                    row.trigger_condition,
                    row.symbols,
                )
            )
        )
    return "\n".join(lines)


def _email_html_body(events: tuple[AlertEvent, ...]) -> str:
    rows = "\n".join(
        _email_table_row(index, row) for index, row in enumerate(_email_rows(events), 1)
    )
    return f"""<!doctype html>
<html>
<body style="margin:0;padding:24px;background:#f6f8fa;color:#1f2328;font-family:Arial,'Microsoft YaHei',sans-serif;">
  <div style="max-width:1200px;margin:0 auto;background:#ffffff;border:1px solid #d8dee4;border-radius:8px;overflow:hidden;">
    <div style="padding:20px 24px;border-bottom:1px solid #d8dee4;background:#f0f6ff;">
      <h2 style="margin:0 0 8px;font-size:20px;line-height:1.35;color:#0969da;">KuaiQi 实盘预警</h2>
      <p style="margin:0;font-size:14px;line-height:1.7;color:#57606a;">{escape(_email_summary_text(events))}</p>
    </div>
    <div style="padding:20px 24px;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;line-height:1.5;">
        <thead>
          <tr>
            <th style="{_TH_STYLE}">序号</th>
            <th style="{_TH_STYLE}">触发时间</th>
            <th style="{_TH_STYLE}">预警类型</th>
            <th style="{_TH_STYLE}">监控对象</th>
            <th style="{_TH_STYLE}">方向/结构</th>
            <th style="{_TH_STYLE}">执行价</th>
            <th style="{_TH_STYLE}">当前指标值</th>
            <th style="{_TH_STYLE}">阈值</th>
            <th style="{_TH_STYLE}">触发条件</th>
            <th style="{_TH_STYLE}">相关合约</th>
          </tr>
        </thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>"""


def _email_summary_text(events: tuple[AlertEvent, ...]) -> str:
    strategy_counts = Counter(_strategy_label(event.evaluation.strategy_name) for event in events)
    strategies = "，".join(
        f"{strategy} {count} 条" for strategy, count in sorted(strategy_counts.items())
    )
    symbols = {
        symbol
        for event in events
        for symbol in event.evaluation.symbols
    }
    lines = [
        f"本次邮件包含 {len(events)} 条新触发预警",
        f"时间范围：{events[0].timestamp} 至 {events[-1].timestamp}",
        f"策略分布：{strategies}",
        f"涉及合约：{len(symbols)} 个",
    ]
    return "；".join(lines) + "。"


def _email_rows(events: tuple[AlertEvent, ...]) -> tuple[_EmailAlertRow, ...]:
    return tuple(_email_row(event) for event in events)


def _email_row(event: AlertEvent) -> _EmailAlertRow:
    evaluation = event.evaluation
    strategy_label = _strategy_label(evaluation.strategy_name)
    parsed = _parse_alert_key(evaluation.key)
    if evaluation.strategy_name == "cp_combo" and parsed:
        monitor = f"{parsed.get('underlying', '')} {parsed.get('expiry', '')}".strip()
        strike = parsed.get("strike", "-")
        value = _format_number(evaluation.value)
        threshold = _format_number(evaluation.threshold)
        return _EmailAlertRow(
            timestamp=str(event.timestamp),
            strategy_label=strategy_label,
            monitor=monitor or "-",
            structure="认购 + 认沽 + 标的",
            strike=f"K={strike}" if strike else "-",
            value=value,
            threshold=threshold,
            trigger_condition=_threshold_condition("偏离率", "大于", threshold),
            symbols=", ".join(evaluation.symbols),
        )
    if evaluation.strategy_name == "abs_spread" and parsed:
        direction = _option_class_label(parsed.get("option_class", ""))
        first_strike = parsed.get("first_strike", "")
        second_strike = parsed.get("second_strike", "")
        value = _format_number(evaluation.value)
        threshold = _format_number(evaluation.threshold)
        return _EmailAlertRow(
            timestamp=str(event.timestamp),
            strategy_label=strategy_label,
            monitor=f"{parsed.get('underlying', '')} {parsed.get('expiry', '')}".strip() or "-",
            structure=direction,
            strike=f"{first_strike} / {second_strike}" if first_strike and second_strike else "-",
            value=value,
            threshold=threshold,
            trigger_condition=_threshold_condition("价差比例", "小于", threshold),
            symbols=", ".join(evaluation.symbols),
        )
    return _EmailAlertRow(
        timestamp=str(event.timestamp),
        strategy_label=strategy_label,
        monitor="-",
        structure="-",
        strike="-",
        value=_format_number(evaluation.value),
        threshold=_format_number(evaluation.threshold),
        trigger_condition=_generic_threshold_condition(evaluation.value, evaluation.threshold),
        symbols=", ".join(evaluation.symbols),
    )


def _email_table_row(index: int, row: _EmailAlertRow) -> str:
    return f"""          <tr>
            <td style="{_TD_STYLE};text-align:center;">{index}</td>
            <td style="{_TD_STYLE};white-space:nowrap;">{escape(row.timestamp)}</td>
            <td style="{_TD_STYLE};white-space:nowrap;">{escape(row.strategy_label)}</td>
            <td style="{_TD_STYLE};white-space:nowrap;">{escape(row.monitor)}</td>
            <td style="{_TD_STYLE};white-space:nowrap;">{escape(row.structure)}</td>
            <td style="{_TD_STYLE};white-space:nowrap;">{escape(row.strike)}</td>
            <td style="{_TD_STYLE};text-align:right;white-space:nowrap;">{escape(row.value)}</td>
            <td style="{_TD_STYLE};text-align:right;white-space:nowrap;">{escape(row.threshold)}</td>
            <td style="{_TD_STYLE};white-space:nowrap;">{escape(row.trigger_condition)}</td>
            <td style="{_TD_STYLE};word-break:break-all;">{escape(row.symbols)}</td>
          </tr>"""


def _threshold_condition(metric_label: str, relation: str, threshold: str) -> str:
    return f"{metric_label}{relation}阈值（{threshold}）"


def _generic_threshold_condition(value: float, threshold: float) -> str:
    if value > threshold:
        relation = "大于"
    elif value < threshold:
        relation = "小于"
    else:
        relation = "等于"
    return _threshold_condition("当前指标值", relation, _format_number(threshold))


def _strategy_label(strategy_name: str) -> str:
    return {
        "abs_spread": "价差预警",
        "cp_combo": "CP组合预警",
    }.get(strategy_name, strategy_name)


def _option_class_label(option_class: str) -> str:
    return {
        "CALL": "认购",
        "PUT": "认沽",
    }.get(option_class, option_class or "-")


def _parse_alert_key(key: str) -> dict[str, str]:
    parts = key.split(":")
    if len(parts) >= 6 and parts[0] == "cp_combo":
        return {
            "strategy": parts[0],
            "underlying": parts[1],
            "expiry": parts[2],
            "strike": parts[3].removeprefix("K="),
        }
    if len(parts) >= 6 and parts[0] == "abs_spread":
        first_strike, second_strike = _extract_spread_strikes(parts[4], parts[5])
        return {
            "strategy": parts[0],
            "underlying": parts[1],
            "expiry": parts[2],
            "option_class": parts[3],
            "first_strike": first_strike,
            "second_strike": second_strike,
        }
    return {}


def _extract_spread_strikes(first_symbol: str, second_symbol: str) -> tuple[str, str]:
    return _symbol_tail_number(first_symbol), _symbol_tail_number(second_symbol)


def _symbol_tail_number(symbol: str) -> str:
    tail = ""
    for character in reversed(symbol):
        if not character.isdigit() and character != ".":
            break
        tail = character + tail
    return tail


def _format_number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


_TH_STYLE = (
    "padding:10px 8px;border:1px solid #d8dee4;background:#f6f8fa;"
    "text-align:left;font-weight:600;color:#24292f;white-space:nowrap"
)
_TD_STYLE = "padding:9px 8px;border:1px solid #d8dee4;color:#24292f;vertical-align:top"


def _event_payload(
    event: AlertEvent,
    extra_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    evaluation = event.evaluation
    metadata = dict(extra_metadata or {})
    metadata.update(event.metadata)
    return {
        "timestamp": event.timestamp,
        "strategy": evaluation.strategy_name,
        "key": evaluation.key,
        "value": evaluation.value,
        "threshold": evaluation.threshold,
        "symbols": list(evaluation.symbols),
        "message": evaluation.message,
        "metadata": metadata,
    }
