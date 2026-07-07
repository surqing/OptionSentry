# accept 筛选函数说明

本文只说明策略筛选脚本里的 `accept(option, ctx)` 函数如何编写，以及 `option` 和 `ctx` 参数能提供哪些信息。

## 函数签名

```python
def accept(option, ctx) -> bool:
    return True
```

含义：

- `option`：当前待判断的期权合约基础信息对象。
- `ctx`：筛选上下文，可通过它读取该期权对应的标的期货信息。
- 返回 `True`：保留该期权。
- 返回 `False`：排除该期权。

要求：

- 返回值必须是 `bool` 类型，不能返回 `1`、`0`、`None`、字符串或列表。
- `accept` 只会收到期权，不会收到期货。
- `accept` 在启动阶段执行，用于决定策略的期权范围，不会在每个行情 tick 中执行。
- `option` 不是实时行情对象，不包含可靠的最新价、盘口、成交量、持仓量等实时行情字段。

## option 字段

`option` 是只读 `InstrumentMeta` 对象。类型中的 `Optional[...]` 表示字段可能缺失，使用前应先判空。

### 合约身份

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `symbol` | `str` | 系统内部标准化合约代码，通常为大写，例如 `SHFE.AU2608C600`。 |
| `api_symbol` | `str` | TqSdk 原始风格合约代码，可能保留品种大小写，例如 `SHFE.au2608C600`。 |
| `instrument_id` | `str` | TqSdk 返回的合约代码。 |
| `instrument_name` | `str` | 合约名称，可能为空字符串。 |
| `exchange_id` | `str` | 交易所代码，例如 `SHFE`、`DCE`、`CZCE`。 |
| `product_id` | `str` | 品种代码。部分期权可能为空，不建议作为唯一品种判断依据。 |
| `ins_class` | `str` | 合约类型。传入 `accept` 的对象通常为 `OPTION`。 |
| `is_option` | `bool` | 是否为期权。当前通常为 `True`。 |
| `is_future` | `bool` | 是否为期货。传入 `accept` 的 `option` 通常为 `False`。 |
| `expired` | `Optional[bool]` | 合约是否已下市。`True` 表示该合约已经下市。 |

### 期权属性

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `underlying_symbol` | `str` | 标的期货的系统内部代码，例如 `SHFE.AU2608`。 |
| `api_underlying_symbol` | `str` | 标的期货的 TqSdk 原始风格代码，例如 `SHFE.au2608`。 |
| `strike_price` | `Optional[float]` | 行权价。 |
| `option_class` | `str` | 期权方向，通常为 `CALL` 或 `PUT`。 |

### 到期和行权

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `exercise_year` | `Optional[int]` | 期权最后行权日年份，例如 `2026`。 |
| `exercise_month` | `Optional[int]` | 期权最后行权日月份，例如 `8`。 |
| `expiry_key` | `str` | 系统派生的行权年月文本，例如 `2026-8`；缺失时对应部分显示为 `NA`。 |
| `expire_datetime` | `Optional[float]` | 到期日 Unix 秒级时间戳。 |
| `expire_date` | `Optional[datetime.date]` | 系统由 `expire_datetime` 转换出的到期日期。 |
| `expire_rest_days` | `Optional[int]` | 距到期日剩余自然日天数。 |
| `last_exercise_datetime` | `Optional[float]` | 最后行权日 Unix 秒级时间戳。 |
| `last_exercise_date` | `Optional[datetime.date]` | 系统由 `last_exercise_datetime` 转换出的最后行权日期。 |
| `delivery_year` | `Optional[int]` | 期货交割日年份。对期权筛选通常优先使用 `exercise_year`。 |
| `delivery_month` | `Optional[int]` | 期货交割日月份。对期权筛选通常优先使用 `exercise_month`。 |

### 合约规格和下单限制

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `price_tick` | `Optional[float]` | 最小变动价位。 |
| `volume_multiple` | `Optional[float]` | 合约乘数。 |
| `open_limit` | `Optional[float]` | 日内开仓限额。 |
| `max_limit_order_volume` | `Optional[float]` | 限价单最大下单手数。 |
| `max_market_order_volume` | `Optional[float]` | 市价单最大下单手数。 |
| `min_limit_order_volume` | `Optional[float]` | 限价单最小下单手数。 |
| `min_market_order_volume` | `Optional[float]` | 市价单最小下单手数。 |
| `open_max_limit_order_volume` | `Optional[float]` | 开仓限价单最大手数。 |
| `open_max_market_order_volume` | `Optional[float]` | 开仓市价单最大手数。 |
| `open_min_limit_order_volume` | `Optional[float]` | 开仓限价单最小手数。 |
| `open_min_market_order_volume` | `Optional[float]` | 开仓市价单最小手数。 |

### 参考价格

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `upper_limit` | `Optional[float]` | 涨停价。 |
| `lower_limit` | `Optional[float]` | 跌停价。 |
| `pre_settlement` | `Optional[float]` | 昨结算。 |
| `pre_open_interest` | `Optional[float]` | 昨持仓。 |
| `pre_close` | `Optional[float]` | 昨收盘。 |

### 交易时段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `trading_time_day` | `tuple[tuple[str, str], ...]` | 日盘交易时段，例如 `(("09:00:00", "10:15:00"), ...)`。 |
| `trading_time_night` | `tuple[tuple[str, str], ...]` | 夜盘交易时段，例如 `(("21:00:00", "26:30:00"),)`。 |

### 不建议使用的兼容字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `volume` | `Optional[float]` | 兼容字段，当前策略级 `accept` 中通常为空，不建议用于筛选。 |
| `open_interest` | `Optional[float]` | 兼容字段，当前策略级 `accept` 中通常为空，不建议用于筛选。 |

## ctx 方法

### `ctx.underlying(option)`

```python
future = ctx.underlying(option)
```

返回该期权对应的标的期货 `InstrumentMeta`；找不到时返回 `None`。

标的期货对象也使用 `InstrumentMeta` 字段，但期权专属字段通常为空，例如 `strike_price`、`option_class`、`exercise_year`、`exercise_month`。

## 最小示例

```python
def accept(option, ctx) -> bool:
    if option.expire_rest_days is None:
        return False
    return 10 <= option.expire_rest_days <= 60
```

## 当前不提供的字段

`accept` 当前不提供实时行情字段，例如：

- `last_price`
- `bid_price1`
- `ask_price1`
- `bid_volume1`
- `ask_volume1`
- `highest`
- `lowest`
- `open`
- `close`
- `amount`

这些字段不能在当前 `accept(option, ctx)` 中使用。
