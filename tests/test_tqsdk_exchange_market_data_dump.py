from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "test_ouput"
DEFAULT_EXCHANGES = ("CFFEX", "SHFE", "DCE", "CZCE", "INE", "GFEX")

SUMMARY_FIELDS = (
    "collected_at",
    "exchange_id",
    "symbol",
    "instrument_id",
    "product_id",
    "ins_class",
    "instrument_name",
    "quote_datetime",
    "snapshot_ready",
    "last_price",
    "bid_price1",
    "ask_price1",
    "volume",
    "open_interest",
    "price_tick",
    "volume_multiple",
    "delivery_year",
    "delivery_month",
    "delivery_date",
    "underlying_symbol",
    "option_class",
    "strike_price",
    "exercise_year",
    "exercise_month",
    "last_exercise_datetime",
    "expire_datetime",
    "expire_rest_days",
    "expired",
)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    exchange_id = args.exchange_id.upper()
    username = os.environ.get(args.username_env)
    password = os.environ.get(args.password_env)
    if not username or not password:
        print(
            f"Missing TqSdk credentials. Set {args.username_env} and {args.password_env}.",
            file=sys.stderr,
        )
        return 2

    output_dir = resolve_output_dir(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    from tqsdk import TqApi, TqAuth

    api = TqApi(auth=TqAuth(username, password))
    try:
        symbols_by_class = discover_symbols(api, exchange_id)
        symbols = sorted(set().union(*symbols_by_class.values()))
        if not symbols:
            print(f"No active futures or options found for exchange {exchange_id}.")
            return 0

        print(
            f"Discovered {len(symbols)} active symbols for {exchange_id}: "
            f"{len(symbols_by_class['FUTURE'])} futures, "
            f"{len(symbols_by_class['OPTION'])} options."
        )
        symbol_info = query_symbol_info(api, symbols, args.symbol_info_batch_size)
        quotes = subscribe_quotes(api, symbols, args.quote_batch_size)
        ready_count = wait_for_snapshots(api, quotes, args.snapshot_timeout_seconds)
        rows = build_rows(symbols, symbol_info, quotes)
        written = write_outputs(output_dir, exchange_id, rows, ready_count, len(symbols), args)
    finally:
        api.close()

    print(f"Received snapshots for {ready_count}/{len(symbols)} symbols.")
    print(f"Wrote CSV: {written['csv']}")
    print(f"Wrote JSON: {written['json']}")
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Subscribe live TqSdk futures and option quotes for one futures exchange "
            "and dump a snapshot to ./test_ouput/."
        )
    )
    parser.add_argument(
        "exchange_id",
        choices=DEFAULT_EXCHANGES,
        type=str.upper,
        help="Futures exchange id, for example SHFE, DCE, CZCE, CFFEX, INE, or GFEX.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory. Relative paths are resolved from the project root.",
    )
    parser.add_argument(
        "--username-env",
        default="TQSDK_USERNAME",
        help="Environment variable containing the TqSdk username.",
    )
    parser.add_argument(
        "--password-env",
        default="TQSDK_PASSWORD",
        help="Environment variable containing the TqSdk password.",
    )
    parser.add_argument(
        "--snapshot-timeout-seconds",
        type=float,
        default=30.0,
        help="Maximum seconds to wait for live quote snapshots after subscribing.",
    )
    parser.add_argument(
        "--quote-batch-size",
        type=int,
        default=500,
        help="Number of symbols per get_quote_list subscription batch.",
    )
    parser.add_argument(
        "--symbol-info-batch-size",
        type=int,
        default=500,
        help="Number of symbols per query_symbol_info batch.",
    )
    return parser.parse_args(argv)


def resolve_output_dir(output_dir: Path) -> Path:
    if output_dir.is_absolute():
        return output_dir
    return PROJECT_ROOT / output_dir


def discover_symbols(api: Any, exchange_id: str) -> dict[str, list[str]]:
    return {
        "FUTURE": list(api.query_quotes(ins_class="FUTURE", exchange_id=exchange_id, expired=False)),
        "OPTION": list(api.query_quotes(ins_class="OPTION", exchange_id=exchange_id, expired=False)),
    }


def query_symbol_info(api: Any, symbols: list[str], batch_size: int) -> dict[str, dict[str, Any]]:
    info: dict[str, dict[str, Any]] = {}
    for batch in batches(symbols, batch_size):
        df = api.query_symbol_info(batch)
        for position, (_, row) in enumerate(df.iterrows()):
            fallback_symbol = batch[position] if position < len(batch) else ""
            row_dict = row.to_dict()
            symbol = full_symbol(
                clean_str(row_dict.get("instrument_id")),
                clean_str(row_dict.get("exchange_id")),
                fallback_symbol,
            )
            if symbol:
                info[symbol] = row_dict
    return info


def subscribe_quotes(api: Any, symbols: list[str], batch_size: int) -> dict[str, Any]:
    quotes: dict[str, Any] = {}
    for batch in batches(symbols, batch_size):
        quote_list = api.get_quote_list(batch)
        quotes.update(dict(zip(batch, quote_list, strict=True)))
        api.wait_update(deadline=time.time() + 5)
    return quotes


def wait_for_snapshots(api: Any, quotes: dict[str, Any], timeout_seconds: float) -> int:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        ready_count = sum(1 for quote in quotes.values() if quote_has_snapshot(quote))
        if ready_count == len(quotes):
            return ready_count
        api.wait_update(deadline=min(deadline, time.time() + 2))
    return sum(1 for quote in quotes.values() if quote_has_snapshot(quote))


def build_rows(
    symbols: list[str],
    symbol_info: dict[str, dict[str, Any]],
    quotes: dict[str, Any],
) -> list[dict[str, Any]]:
    collected_at = datetime.now().isoformat(timespec="seconds")
    rows = []
    for symbol in symbols:
        row = symbol_info.get(symbol, {})
        quote = quotes.get(symbol)
        summary = {
            "collected_at": collected_at,
            "exchange_id": first_value(quote, row, "exchange_id"),
            "symbol": symbol,
            "instrument_id": first_value(quote, row, "instrument_id") or symbol,
            "product_id": first_value(quote, row, "product_id"),
            "ins_class": first_value(quote, row, "ins_class"),
            "instrument_name": first_value(quote, row, "instrument_name"),
            "quote_datetime": first_value(quote, row, "datetime"),
            "snapshot_ready": quote_has_snapshot(quote),
            "last_price": normalize_number(first_value(quote, row, "last_price")),
            "bid_price1": normalize_number(first_value(quote, row, "bid_price1")),
            "ask_price1": normalize_number(first_value(quote, row, "ask_price1")),
            "volume": normalize_number(first_value(quote, row, "volume")),
            "open_interest": normalize_number(first_value(quote, row, "open_interest")),
            "price_tick": normalize_number(first_value(quote, row, "price_tick")),
            "volume_multiple": normalize_number(first_value(quote, row, "volume_multiple")),
            "delivery_year": normalize_number(first_value(quote, row, "delivery_year")),
            "delivery_month": normalize_number(first_value(quote, row, "delivery_month")),
            "delivery_date": format_year_month(
                first_value(quote, row, "delivery_year"),
                first_value(quote, row, "delivery_month"),
            ),
            "underlying_symbol": first_value(quote, row, "underlying_symbol"),
            "option_class": first_value(quote, row, "option_class"),
            "strike_price": normalize_number(first_value(quote, row, "strike_price")),
            "exercise_year": normalize_number(first_value(quote, row, "exercise_year")),
            "exercise_month": normalize_number(first_value(quote, row, "exercise_month")),
            "last_exercise_datetime": format_timestamp(first_value(quote, row, "last_exercise_datetime")),
            "expire_datetime": format_timestamp(first_value(quote, row, "expire_datetime")),
            "expire_rest_days": normalize_number(first_value(quote, row, "expire_rest_days")),
            "expired": normalize_bool(first_value(quote, row, "expired")),
        }
        rows.append(
            {
                **{key: sanitize_value(value) for key, value in summary.items()},
                "symbol_info": sanitize_mapping(row),
                "quote": public_fields(quote),
            }
        )
    return rows


def write_outputs(
    output_dir: Path,
    exchange_id: str,
    rows: list[dict[str, Any]],
    ready_count: int,
    total_count: int,
    args: argparse.Namespace,
) -> dict[str, Path]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"{exchange_id.lower()}_futures_options_live_{stamp}.csv"
    json_path = output_dir / f"{exchange_id.lower()}_futures_options_live_{stamp}.json"
    fieldnames, csv_rows = flatten_rows(rows)

    with csv_path.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    payload = {
        "exchange_id": exchange_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "snapshot_ready": ready_count,
        "symbol_count": total_count,
        "quote_batch_size": args.quote_batch_size,
        "snapshot_timeout_seconds": args.snapshot_timeout_seconds,
        "rows": rows,
    }
    with json_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)

    return {"csv": csv_path, "json": json_path}


def flatten_rows(rows: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    dynamic_fields: set[str] = set()
    flattened = []
    for row in rows:
        flat_row = {field: csv_value(row.get(field, "")) for field in SUMMARY_FIELDS}
        for prefix in ("symbol_info", "quote"):
            nested = row.get(prefix, {})
            if not isinstance(nested, dict):
                continue
            for key, value in nested.items():
                column = f"{prefix}_{key}"
                flat_row[column] = csv_value(value)
                dynamic_fields.add(column)
        flattened.append(flat_row)
    fieldnames = list(SUMMARY_FIELDS) + sorted(dynamic_fields)
    return fieldnames, flattened


def batches(items: list[str], size: int) -> Iterable[list[str]]:
    if size <= 0:
        raise ValueError("batch size must be positive")
    for index in range(0, len(items), size):
        yield items[index:index + size]


def first_value(quote: Any, row: dict[str, Any], key: str) -> Any:
    if quote is not None and hasattr(quote, key):
        value = getattr(quote, key)
        if is_present(value):
            return value
    value = row.get(key)
    return value if is_present(value) else ""


def public_fields(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    fields = {}
    for key, item in vars(value).items():
        if key.startswith("_") or callable(item):
            continue
        fields[key] = sanitize_value(item)
    return fields


def sanitize_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {str(key): sanitize_value(item) for key, item in value.items()}


def sanitize_value(value: Any, max_depth: int = 3) -> Any:
    if not is_present(value):
        return ""
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else ""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if max_depth <= 0:
        return str(value)

    item_method = getattr(value, "item", None)
    if callable(item_method):
        with suppress(TypeError, ValueError):
            return sanitize_value(item_method(), max_depth=max_depth - 1)

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        with suppress(TypeError, ValueError):
            return sanitize_value(to_dict(), max_depth=max_depth - 1)

    if isinstance(value, dict):
        return {
            str(key): sanitize_value(item, max_depth=max_depth - 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_value(item, max_depth=max_depth - 1) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): sanitize_value(item, max_depth=max_depth - 1)
            for key, item in vars(value).items()
            if not key.startswith("_") and not callable(item)
        }
    return str(value)


def csv_value(value: Any) -> Any:
    value = sanitize_value(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def quote_has_snapshot(quote: Any) -> bool:
    return bool(quote is not None and getattr(quote, "datetime", ""))


def is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    with suppress(Exception):
        if value != value:
            return False
    return True


def normalize_number(value: Any) -> int | float | str:
    if not is_present(value):
        return ""
    with suppress(TypeError, ValueError):
        numeric = float(value)
        if not math.isfinite(numeric):
            return ""
        if numeric.is_integer():
            return int(numeric)
        return numeric
    return value


def normalize_bool(value: Any) -> bool | str:
    if value in (True, False):
        return value
    if not is_present(value):
        return ""
    return str(value)


def format_year_month(year: Any, month: Any) -> str:
    year_value = normalize_number(year)
    month_value = normalize_number(month)
    if not isinstance(year_value, int) or not isinstance(month_value, int):
        return ""
    if year_value <= 0 or month_value <= 0:
        return ""
    return f"{year_value:04d}-{month_value:02d}"


def format_timestamp(value: Any) -> str:
    numeric = normalize_number(value)
    if not isinstance(numeric, (int, float)) or numeric <= 0:
        return ""
    with suppress(OSError, OverflowError, ValueError):
        return datetime.fromtimestamp(float(numeric)).isoformat(timespec="seconds")
    return ""


def clean_str(value: Any) -> str:
    if not is_present(value):
        return ""
    return str(value)


def full_symbol(raw_symbol: str, exchange_id: str, fallback_symbol: str) -> str:
    if raw_symbol and "." in raw_symbol:
        return raw_symbol
    if raw_symbol and exchange_id:
        return f"{exchange_id}.{raw_symbol}"
    if fallback_symbol and "." in fallback_symbol:
        return fallback_symbol
    return raw_symbol or fallback_symbol


if __name__ == "__main__":
    raise SystemExit(main())
