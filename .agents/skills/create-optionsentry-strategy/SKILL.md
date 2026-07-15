---
name: create-optionsentry-strategy
description: Create or modify OptionSentry option-alert strategies in this repository. Use when a user asks to add, create, or implement a strategy; expose strategy-specific parameters in config or GUI; declare strategy market-data requirements; compile conditions into execution units; or update strategy tests and documentation.
---

# Create an OptionSentry Strategy

Use the repository's metadata-driven strategy contract. A normal new strategy should require one new module plus tests and documentation; do not add type-specific branches to the config parser, GUI, runner, or data source.

Read references/implementation-guide.md before editing.

## Workflow

1. Translate the request into a precise strategy specification:
   - formula and units;
   - option grouping granularity, including exact date versus year/month;
   - deterministic leg-selection rules for duplicate or ambiguous contracts;
   - alert range semantics: min_value < value < max_value;
   - invalid, zero, negative, NaN, and infinite price behavior;
   - required quote fields, K-lines, Greeks, or other data;
   - an alert-key shape that remains parseable when id differs from type;
   - user-visible Chinese name, parameter labels, and metric labels.
2. Inspect optionsentry/strategy_base.py, optionsentry/strategy_registry.py, optionsentry/models.py, and the closest built-in module under optionsentry/strategy_types/.
3. Create a registered Strategy subclass in optionsentry/strategy_types/<type_name>.py.
4. Declare every configurable field with StrategyParameterSpec. Keep keys and enum values in English. Use Chinese label, choice_labels, and user-visible messages.
5. Validate cross-field rules in validate_parameters().
6. Compile conditions into one or more CompiledStrategy execution units:
   - use the configured strategy id in alert keys;
   - declare exact required_symbols;
   - use a stable backtest_group;
   - declare DataRequirements;
   - use add_condition() so incremental updates map to affected conditions.
7. Add presentation hooks only when needed: metric_columns, parse_key(), email_presentation(), and row_background_color().
8. Add strict config, formula, incremental-evaluation, compilation, runner, and GUI metadata tests as applicable.
9. Update config.example.toml and user/developer documentation when the strategy should appear in examples.
10. Run targeted tests, then uv run pytest -q. Follow the repository's AGENTS.md review and Git rules.

## Architecture Guardrails

- Do not add legacy config aliases or migration logic to production code.
- Do not hard-code the new strategy type in config.py, gui/app.py, runner.py, or data_sources/.
- Do not subscribe to the full universe when the compiled unit needs fewer symbols.
- Do not let strategy code open TqSdk APIs or control live/backtest iteration.
- Do not persist usernames, passwords, or tokens in TOML.
- Do not use display names as stable alert identities; use the strategy instance id.
- Do not silently overwrite duplicate legs during compilation. Reject them or apply a documented deterministic rule.
- Use decimal units consistently in config and examples, and state whether 0.05 means 5 percent.
- Prefer enabled = false for a newly added example unless the requested default behavior is explicitly safe.
- If the strategy needs data currently rejected by DataRequirements.unsupported_reasons(), treat data-pipeline support as a separate architecture change and test it end to end.

## Completion Checklist

- Strategy discovery works without an aggregator import.
- Invalid, missing, and unknown parameters fail during config parsing.
- Multiple instances of the same type work with distinct id values.
- GUI creates the parameter form from metadata and displays Chinese labels.
- required_symbols includes every symbol read by evaluate().
- Live incremental evaluation and backtest grouping are covered.
- Full tests pass and docs contain no obsolete config examples.
