from __future__ import annotations

import json
import os
import smtplib
from dataclasses import dataclass
from email.mime.text import MIMEText
from pathlib import Path
from typing import Protocol

from kuaiqi.config import AppConfig, ConfigError, EmailConfig
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

    def __post_init__(self) -> None:
        if not self.config.smtp_host:
            raise ConfigError("Email notifier requires smtp_host or SMTP_HOST.")
        if not self.config.from_addr:
            raise ConfigError("Email notifier requires from_addr or ALERT_EMAIL_FROM.")
        if not self.config.to_addrs:
            raise ConfigError("Email notifier requires to_addrs or ALERT_EMAIL_TO.")

    def notify(self, event: AlertEvent) -> None:
        subject = f"KuaiQi alert: {event.evaluation.strategy_name}"
        body = _event_text(event)
        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = subject
        message["From"] = self.config.from_addr or ""
        message["To"] = ",".join(self.config.to_addrs)

        password = os.environ.get(self.config.password_env)
        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=20) as smtp:
            if self.config.use_tls:
                smtp.starttls()
            if self.config.username:
                smtp.login(self.config.username, password or "")
            smtp.sendmail(self.config.from_addr, list(self.config.to_addrs), message.as_string())


@dataclass
class JsonlAlertRecorder:
    path: Path

    def notify(self, event: AlertEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(_event_payload(event), ensure_ascii=False, sort_keys=True))
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
            raise NotificationError(f"{len(errors)} notifier(s) failed") from errors[0]


def build_notifier(config: AppConfig) -> Notifier:
    kind = config.notifier.kind or ("email" if config.runtime.mode == "live" else "console")
    if kind == "email":
        primary: Notifier = EmailNotifier(config.notifier.email)
    elif kind == "console":
        primary = ConsoleNotifier()
    else:
        raise ConfigError(f"Unsupported notifier kind: {kind}")
    recorder = JsonlAlertRecorder(Path(config.notifier.alert_log_path))
    return CompositeNotifier((primary, recorder))


def _event_text(event: AlertEvent) -> str:
    return f"[{event.timestamp}] {event.evaluation.message}"


def _event_payload(event: AlertEvent) -> dict[str, object]:
    evaluation = event.evaluation
    return {
        "timestamp": event.timestamp,
        "strategy": evaluation.strategy_name,
        "key": evaluation.key,
        "value": evaluation.value,
        "threshold": evaluation.threshold,
        "symbols": list(evaluation.symbols),
        "message": evaluation.message,
        "metadata": event.metadata,
    }
