# OptionSentry Strategy Implementation Guide

## Contract Map

| Concern | Contract |
| --- | --- |
| Registration and discovery | @register_strategy("type_name") in a module under optionsentry.strategy_types |
| Config and GUI fields | Strategy.parameter_specs |
| Parameter validation | Strategy.validate_parameters() |
| Compile result | StrategyCompilation containing CompiledStrategy units |
| Exact subscriptions | CompiledStrategy.required_symbols |
| Incremental evaluation | condition_ids_by_symbol, add_condition(), affected_condition_ids() |
| Backtest isolation | CompiledStrategy.backtest_group |
| Market data | CompiledStrategy.data_requirements |
| GUI metric columns | Strategy.metric_columns |
| Alert and email presentation | parse_key(), email_presentation(), row_background_color() |

The registry scans optionsentry.strategy_types. A new module does not need to be imported by optionsentry/strategies.py.

## Identity Rules

- type is the implementation type shared by all instances, for example cp_combo.
- id is the stable config identity for one strategy instance, for example cp_combo_positive.
- name is the Chinese user-visible display name.
- Alert keys must start with id, not name.

This permits several configurations of the same strategy class without key collisions.

## Parameter Metadata

Supported kinds are float, int, bool, string, and enum.

    parameter_specs: ClassVar[tuple[StrategyParameterSpec, ...]] = (
        StrategyParameterSpec(
            key="lookback",
            label="回看周期",
            kind="int",
            default=20,
            minimum=1,
            maximum=500,
            help_text="用于计算信号的周期数",
        ),
        StrategyParameterSpec(
            key="direction",
            label="方向",
            kind="enum",
            default="both",
            choices=("both", "call", "put"),
            choice_labels=("双向", "认购", "认沽"),
        ),
    )

Keep keys and values English because they are code and config contracts. Use Chinese labels for visible GUI text. Registration validates defaults, key shapes, enum choices, and label counts.

Override validate_parameters() for relationships such as min_value < max_value. First call normalize_strategy_parameters() and then apply domain rules.

## Strategy Skeleton

    from __future__ import annotations

    from dataclasses import dataclass
    from typing import Any, ClassVar, Mapping

    from optionsentry.models import Universe
    from optionsentry.strategy_base import (
        CompiledStrategy,
        Strategy,
        StrategyCompilation,
        StrategyParameterSpec,
        normalize_strategy_parameters,
    )
    from optionsentry.strategy_registry import register_strategy


    @register_strategy("example")
    @dataclass
    class ExampleStrategy(Strategy):
        display_name: ClassVar[str] = "示例预警"
        display_order: ClassVar[int] = 100
        parameter_specs: ClassVar[tuple[StrategyParameterSpec, ...]] = (
            StrategyParameterSpec("limit", "阈值", "float", default=1.0),
        )

        limit: float
        id: str = "example"
        name: str = "示例预警"
        filter_script: str | None = None
        filter_function: str = "accept"
        filter_scope: str = "options"

        @classmethod
        def validate_parameters(cls, parameters: Mapping[str, Any]) -> dict[str, Any]:
            normalized = normalize_strategy_parameters(
                cls.type_name, cls.parameter_specs, parameters
            )
            if normalized["limit"] <= 0:
                raise ValueError(
                    "Strategy example parameter limit must be positive."
                )
            return normalized

        def compile(self, universe: Universe) -> StrategyCompilation:
            units: tuple[CompiledStrategy, ...] = ()
            return StrategyCompilation(self.id, self.type_name, self.name, units)

Define a concrete compiled-unit dataclass with condition_count, required_symbols, and evaluate(). Prefer one unit per option underlying and expiry group when this prevents unrelated backtest subscriptions.

## Compilation Rules

1. Apply grouping and leg matching during compile(), not on every quote update.
2. Define whether expiry means exact expire_date or exercise year and month.
3. Reject duplicate legs or select them with a documented deterministic rule; never rely on dict overwrite order.
4. Store normalized symbols in conditions.
5. Pass every symbol read by evaluate() to add_condition().
6. Derive required_symbols from the condition index.
7. Set backtest_group to a deterministic semantic group such as group_key.as_text().
8. Keep evaluate() pure: read the snapshot, calculate values, and return ConditionEvaluation objects.
9. Define behavior for zero, negative, missing, NaN, and infinite prices.
10. Put the strategy id, an unambiguous type marker, and state-affecting parameters in keys so alert state is stable and parse_key() can recognize custom instance IDs.

DataRequirements currently supports last_price. A strategy declaring other quote fields, K-line durations, or Greeks will be rejected clearly until the data pipeline is extended.

## Strict TOML Shape

    [[strategies]]
    id = "example_default"
    type = "example"
    name = "示例预警"
    enabled = true

    [strategies.parameters]
    limit = 1.0

    # Optional
    [strategies.filter]
    script = "user_filter_scripts/example.py"
    entrypoint = "accept"

Do not add flat strategy parameters, threshold, selected, filter_script, or other retired fields.

## Test Matrix

- Registry discovery and duplicate, type, and metadata validation.
- Defaults, unknown keys, missing keys, types, bounds, enums, and cross-field validation.
- Formula results on active, inactive, missing-price, and invalid-price inputs.
- Compilation condition count, stable keys, exact required_symbols, and backtest_group.
- Incremental evaluation only for changed relevant symbols.
- Multiple instances of the same type with unique IDs.
- Backtest streams are split by execution group.
- Dynamic GUI labels and enum value and label round trip when new metadata kinds are used.
- Full suite: uv run pytest -q.
