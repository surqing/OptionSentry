# Strategy Requirement Clarification Guide

Use this guide when a strategy request omits material behavior, contains conflicting statements, or may need capabilities outside the current architecture. The objective is a small, testable specification—not a long questionnaire.

## Contents

- Specification template
- Classification rules
- Blocking ambiguity catalog
- Question protocol
- Architecture boundaries
- Worked examples
- Definition of Ready

## Specification Template

Capture these fields internally before implementation. Keep the record compact and preserve the user's terminology where it is unambiguous.

| Area | Required decision |
| --- | --- |
| Goal | What market condition the strategy detects and why |
| Formula | Exact operands, operators, normalization, aggregation, and output |
| Units | Decimal, percentage, price, ratio, contracts, or time |
| Grouping | Underlying, exact expiry date or year/month, strike, option class, and exchange |
| Legs | Required call/put/underlying legs and deterministic duplicate selection |
| Trigger | Direction, boundaries, boolean/range behavior, crossing versus level, and first-match behavior |
| Invalid data | Missing, zero, negative, NaN, infinity, stale values, and partial groups |
| Parameters | Key, kind, default, bounds, choices, dependencies, and Chinese labels |
| Data | Quote fields, K-line duration, Greeks, account data, and subscription scope |
| Identity | English type/id, Chinese name, stable alert-key shape, and metric labels |
| Delivery | Code, config example, GUI exposure, tests, docs, backtest, and live support |

## Classification Rules

Classify every unresolved item before touching files:

- **Explicit**: directly stated by the user or unambiguously established by an existing project contract.
- **Safe assumption**: reversible and unable to change evaluation results, subscriptions, alert state, or the public config contract.
- **Blocking ambiguity**: different plausible answers change signals, user-visible semantics, subscriptions, identities, or validation.
- **Architecture limitation**: the desired behavior is clear, but the repository does not currently support the required data or lifecycle.

Safe assumptions may include an English module/type name, a reasonable initial Chinese display name, display order, test-file placement, a unique example id, or `enabled = false` in examples. Report any material safe assumption.

Never silently infer a formula, unit, grouping boundary, required leg, trigger rule, invalid-data policy, market-data field, or outcome-changing default.

## Blocking Ambiguity Catalog

### Formula and units

Clarify operands and normalization when terms such as “价差”, “比率”, “波动率”, “偏离度”, or “强弱” have multiple standard interpretations. Confirm whether `0.05` means decimal 0.05, five percentage points, or a price amount.

### Contract grouping and leg selection

Clarify exact expiry date versus exercise year/month, same-strike versus nearest-strike pairing, underlying mapping, and duplicate-contract selection. Reject duplicates or apply an explicit deterministic rule; never depend on iteration or dictionary overwrite order.

### Trigger and alert lifecycle

Clarify whether activation is above, below, inside, outside, boolean, or based on a crossing event. Confirm inclusive versus exclusive boundaries when equality matters. Determine whether repeated level matches remain active, emit repeatedly, or require a reset before a new alert.

### Invalid and incomplete data

Clarify whether incomplete groups are skipped, reported, or considered inactive. Define zero and negative denominators, non-finite inputs, stale values, and partially available legs.

### Parameters and defaults

Clarify which values users may configure and which are fixed strategy semantics. A parameter needs a stable English key, supported kind, default, constraints, dependency rules, Chinese GUI label, and unit. Defaults that change signals are blocking unless the user states them or an authoritative project convention fixes them.

### Data and delivery scope

Clarify quote fields, K-line durations, Greeks, account or position inputs, and live/backtest expectations. Confirm whether the request includes config examples, GUI exposure, documentation, or migration. Do not add legacy compatibility unless explicitly requested and authorized.

## Question Protocol

1. Inspect the closest built-in strategy, base contracts, configuration schema, and data capability before asking anything.
2. Ask only questions whose answers cannot be discovered locally and would change the implementation outcome.
3. Ask the 1-3 highest-impact blocking questions together. Start with formula/data feasibility, then grouping/legs, trigger behavior, invalid data, and presentation.
4. For each question, state briefly what decision it controls. Offer a recommended option only when repository conventions or domain evidence support it.
5. Do not edit code or config while semantic blockers remain. Incorporate answers, remove resolved questions, and repeat only if new blockers emerge.
6. When the request is already complete, proceed directly without asking for confirmation or restating it as a questionnaire.

Use concise natural-language questions. Avoid presenting every optional detail at once. Do not ask the user to choose implementation details that are already fixed by repository contracts.

## Architecture Boundaries

The current `DataRequirements` path supports `last_price`. Requests for other quote fields, K-lines, Greeks, account state, or stateful event semantics may require a separate data-pipeline or execution-lifecycle change.

When a limitation appears:

1. Confirm the requested semantic behavior is otherwise clear.
2. Identify the unsupported capability and the affected layers.
3. Separate the strategy implementation from the architecture extension.
4. Ask for authorization before broadening the task.
5. If authorized, test the new capability end to end in live/backtest or the applicable execution modes.

Do not disguise an unsupported requirement by substituting `last_price`, using a fixed constant, or weakening the requested semantics.

## Worked Examples

### Vague pairing request

Request: “新增一个跨式机会策略。”

Inspect existing grouping and data contracts, then ask up to three questions covering the exact metric/formula, contract grouping and leg selection, and trigger behavior. Do not invent a min/max range or default threshold.

### Ambiguous ratio request

Request: “认购认沽比率超过阈值就报警。”

Clarify whether the ratio uses prices, volume, open interest, or another field; define numerator/denominator orientation; then confirm the threshold value/unit and zero-denominator behavior. The data field choice also determines whether an architecture extension is required.

### Unsupported data request

Request: “用 Delta 和五分钟 K 线做一个中性策略。”

Do not approximate the inputs with last price. State that Greeks and K-line requirements cross the current data boundary, identify the likely data-pipeline scope, and obtain authorization before extending it.

### Complete request

Request: “同一标的、同一到期日和同一行权价配对认购认沽；指标为 `(call.last_price + put.last_price) / underlying.last_price`；任一价格缺失、非有限或小于等于零时跳过；指标严格大于参数 `upper_threshold` 时激活；默认值为十进制 `0.05`；只使用 last_price；示例默认禁用。”

This request is ready if the identity and delivery details can be derived safely from repository conventions. Proceed without asking the user to reconfirm stated behavior.

## Definition of Ready

Implementation may begin only when all of the following are true:

- The formula, operands, output, and units are testable.
- Grouping and deterministic leg selection are defined.
- Trigger boundaries and alert lifecycle are defined.
- Invalid, missing, and non-finite data behavior is defined.
- Every configurable parameter has a key, kind, default, constraints, label, and unit where applicable.
- Required data is known and supported, or the user has authorized the separate architecture change.
- Stable identity and Chinese presentation can be produced without changing semantics.
- Delivery scope is explicit or safely implied by the repository's standard strategy workflow.
- No blocking ambiguity remains.
