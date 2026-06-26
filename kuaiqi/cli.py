from __future__ import annotations

import argparse
import sys

from kuaiqi.alerts import AlertEngine
from kuaiqi.config import ConfigError, load_config
from kuaiqi.data_sources import TqSdkDataSource
from kuaiqi.logging_config import setup_logging
from kuaiqi.notifiers import build_notifier
from kuaiqi.runner import AlertRunner
from kuaiqi.strategies import build_strategy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KuaiQi futures option alert system")
    parser.add_argument("--config", default="config.toml", help="Path to TOML config")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        logger = setup_logging(config.logging, config.runtime.mode)
        logger.info(
            "Starting KuaiQi mode=%s strategies=%s universe_mode=%s",
            config.runtime.mode,
            [strategy.type for strategy in config.selected_strategies],
            config.universe.mode,
        )
        data_source = TqSdkDataSource(config=config, logger=logger)
        strategies = tuple(build_strategy(strategy) for strategy in config.selected_strategies)
        runner = AlertRunner(
            data_source=data_source,
            strategies=strategies,
            alert_engine=AlertEngine(alert_on_first_match=config.runtime.alert_on_first_match),
            notifier=build_notifier(config),
            logger=logger,
            cycle_summary_interval_seconds=config.logging.cycle_summary_interval_seconds,
        )
        runner.run()
        return 0
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
