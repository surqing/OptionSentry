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

标的期货对象也使用 `InstrumentMeta` 字段。当前实现先从 TqSdk `query_symbol_info` 读取合约元信息，再用期货 Quote 上可获取的静态元信息补齐部分字段，例如 `price_decs`、`position_limit`、`categories`。这些字段不是实时行情字段。

#### 标的期货合约身份

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `symbol` | `str` | 系统内部标准化期货合约代码，通常为大写，例如 `SHFE.AU2608`。 |
| `api_symbol` | `str` | TqSdk 原始风格期货合约代码，例如 `SHFE.au2608`。 |
| `instrument_id` | `str` | TqSdk 返回的合约代码，可能为完整代码或交易所内代码。 |
| `instrument_name` | `str` | 合约名称，例如 `沪金2608`，可能为空字符串。 |
| `exchange_id` | `str` | 交易所代码，例如 `SHFE`、`DCE`、`CZCE`。 |
| `product_id` | `str` | 期货品种代码，例如 `au`、`rb`。 |
| `ins_class` | `str` | 合约类型。标的期货通常为 `FUTURE`。 |
| `is_future` | `bool` | 是否为期货。标的期货通常为 `True`。 |
| `is_option` | `bool` | 是否为期权。标的期货通常为 `False`。 |
| `expired` | `Optional[bool]` | 合约是否已下市。`True` 表示该合约已经下市。 |
| `categories` | `tuple[CategoryMeta, ...]` | TqSdk 返回的品类标签，每个元素有 `id` 和 `name`，例如 `CategoryMeta(id="CHEMICAL", name="化工")`。没有时为空元组。 |

#### 标的期货交割和期限

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `delivery_year` | `Optional[int]` | 期货交割年份，例如 `2026`。 |
| `delivery_month` | `Optional[int]` | 期货交割月份，例如 `8`。 |
| `expire_datetime` | `Optional[float]` | 期货合约到期/摘牌相关 Unix 秒级时间戳。 |
| `expire_date` | `Optional[datetime.date]` | 系统由 `expire_datetime` 转换出的日期。 |
| `expire_rest_days` | `Optional[int]` | 距到期/摘牌剩余自然日天数。 |

#### 标的期货规格和下单限制

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `price_tick` | `Optional[float]` | 最小变动价位。 |
| `price_decs` | `Optional[int]` | 价格小数位数。 |
| `volume_multiple` | `Optional[float]` | 合约乘数。 |
| `open_limit` | `Optional[float]` | 日内开仓限额。 |
| `position_limit` | `Optional[int]` | 持仓限额。 |
| `max_limit_order_volume` | `Optional[float]` | 限价单最大下单手数。 |
| `max_market_order_volume` | `Optional[float]` | 市价单最大下单手数。 |
| `min_limit_order_volume` | `Optional[float]` | 限价单最小下单手数。 |
| `min_market_order_volume` | `Optional[float]` | 市价单最小下单手数。 |
| `open_max_limit_order_volume` | `Optional[float]` | 开仓限价单最大手数。 |
| `open_max_market_order_volume` | `Optional[float]` | 开仓市价单最大手数。 |
| `open_min_limit_order_volume` | `Optional[float]` | 开仓限价单最小手数。 |
| `open_min_market_order_volume` | `Optional[float]` | 开仓市价单最小手数。 |

#### 标的期货参考价格和持仓

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `upper_limit` | `Optional[float]` | 涨停价。 |
| `lower_limit` | `Optional[float]` | 跌停价。 |
| `pre_settlement` | `Optional[float]` | 昨结算。 |
| `pre_open_interest` | `Optional[float]` | 昨持仓。 |
| `pre_close` | `Optional[float]` | 昨收盘。 |
| `volume` | `Optional[float]` | 兼容字段；当前策略级筛选中通常不建议作为实时成交量使用。 |
| `open_interest` | `Optional[float]` | 兼容字段；当前策略级筛选中通常不建议作为实时持仓量使用。 |

#### 标的期货交易时段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `trading_time_day` | `tuple[tuple[str, str], ...]` | 日盘交易时段，例如 `(("09:00:00", "10:15:00"), ...)`。 |
| `trading_time_night` | `tuple[tuple[str, str], ...]` | 夜盘交易时段，例如 `(("21:00:00", "23:00:00"),)`；没有夜盘时为空元组。 |
| `trading_time` | `dict[str, tuple[tuple[str, str], ...]]` | 便捷属性，形如 `{"day": future.trading_time_day, "night": future.trading_time_night}`。 |

#### 标的期货中的期权兼容字段

期货和期权共用同一个 `InstrumentMeta` 类型，因此期货对象上也能访问下列字段，但它们通常为空、`None` 或 TqSdk 返回的占位值。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `underlying_symbol` | `str` | 期权标的字段。对普通期货通常为空字符串。 |
| `api_underlying_symbol` | `str` | TqSdk 原始风格的期权标的字段。对普通期货通常为空字符串。 |
| `strike_price` | `Optional[float]` | 行权价。对期货通常为 `None`。 |
| `option_class` | `str` | 期权方向。对期货通常为空字符串。 |
| `exercise_type` | `str` | 行权方式。对期货通常为空字符串。 |
| `exercise_year` | `Optional[int]` | 期权行权年份。对期货通常为 `0` 或 `None`。 |
| `exercise_month` | `Optional[int]` | 期权行权月份。对期货通常为 `0` 或 `None`。 |
| `last_exercise_datetime` | `Optional[float]` | 最后行权日 Unix 秒级时间戳。对期货通常为 `None`。 |
| `last_exercise_date` | `Optional[datetime.date]` | 系统由 `last_exercise_datetime` 转换出的最后行权日期。对期货通常为 `None`。 |

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
