from __future__ import annotations

import argparse
import sys
from pathlib import Path

from optionsentry.alerts import AlertEngine
from optionsentry.config import ConfigError, load_config
from optionsentry.data_sources import TqSdkDataSource
from optionsentry.logging_config import setup_logging
from optionsentry.notifiers import build_notifier
from optionsentry.runner import AlertRunner
from optionsentry.strategies import build_strategy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OptionSentry futures option alert system")
    parser.add_argument("--config", default="config.toml", help="Path to TOML config")
    args = parser.parse_args(argv)

    try:
        config_path = Path(args.config)
        config = load_config(config_path)
        logger = setup_logging(config.logging, config.runtime.mode)
        logger.info(
            "Starting OptionSentry mode=%s strategies=%s universe_mode=%s",
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
            config_dir=config_path.resolve().parent,
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
