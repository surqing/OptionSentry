# 策略期权筛选脚本 accept 函数说明

本文说明如何为单个预警策略编写期权筛选脚本。当前版本的策略筛选只支持 `filter_scope = "options"`：系统只把期权对象传给用户的 `accept(option, ctx)` 函数，用户决定哪些期权进入该策略；期权对应的标的期货由系统自动补齐，用于 CP 组合等策略计算。

## 配置方式

在需要筛选的某个 `[[strategies]]` 配置块里添加：

```toml
[[strategies]]
type = "cp_combo"
min_value = 0.002
max_value = inf
name = "黄金近月CP"
selected = true
filter_script = "filter_scripts/by_expiry.py"
filter_function = "accept"
filter_scope = "options"
```

说明：

- `filter_script` 是 Python 脚本路径。最保险的写法是使用绝对路径，例如 `H:/Project/KuaiQi/configure/filter_scripts/by_expiry.py`。
- GUI 的“选择脚本”按钮会自动写入绝对路径，脚本不需要位于配置文件所在目录或其子目录。
- 手工编辑配置时也可以写相对路径；相对路径按当前配置文件所在目录解析，不按启动命令所在目录解析。
- `filter_function` 是脚本里的函数名，默认是 `accept`。
- `filter_scope` 当前只支持 `options`。
- 不配置 `filter_script` 的策略不会执行用户筛选脚本。
- GUI 中可以在“配置 -> 策略”表格里选中某一行，然后点击“选择脚本”，只给这一行策略设置脚本。

## 函数签名

筛选脚本中需要定义：

```python
def accept(option, ctx) -> bool:
    return True
```

`accept` 会在策略编译前被调用。每个经过全局合约范围筛选后的期权都会调用一次。返回 `True` 表示保留该期权，返回 `False` 表示从当前策略中排除该期权。

必须注意：

- 返回值必须是 `bool` 类型，不能返回 `"yes"`、`1`、`None`、列表等。
- 函数异常会导致监控启动失败，并在错误信息中显示策略名、期权代码和异常类型。
- 该函数只用于启动阶段的合约范围筛选，不会在每个行情 tick 中反复调用。
- `option` 不是 TqSdk 的实时 `Quote` 对象，而是系统整理出的只读合约基础信息对象。

## option 对象字段

`option` 是 `InstrumentMeta` 对象。下列字段以真实 TqSdk API 调用为准：先调用 `query_quotes(ins_class="OPTION", exchange_id="SHFE", expired=False)` 获取未下市期权，再对样例期权调用 `query_symbol_info([symbol])` 打印返回列和值。打印验证时使用的 TqSdk 版本是 `3.10.1`，样例期权是 `SHFE.au2610C1088`。

类型中的 `| None` 表示这个字段在某些合约、交易所、回测模式或数据返回场景下可能缺失，脚本中要先判空；这不是字段含义为 `None`。例如 `option.strike_price is not None` 表示“这个期权有行权价数据”。

除特别说明外，字段含义按 [TqSdk 3.10.1 官方 `query_symbol_info()` 文档](https://doc.shinnytech.com/tqsdk/latest/reference/tqsdk.api.html)和本地 skill 中对返回列的说明填写；官方文档说明该接口返回 `pandas.DataFrame`，且返回值不会再更新。`symbol`、`api_symbol`、`api_underlying_symbol`、`is_option`、`is_future`、`expiry_key`、`expire_date`、`last_exercise_date` 是本系统基于 TqSdk 字段做的标准化或便捷派生字段。

### API 验证记录

实际验证脚本调用的是：

```python
symbols = list(api.query_quotes(ins_class="OPTION", exchange_id="SHFE", expired=False))
symbol = [item for item in symbols if ".au" in item.lower()][0]
df = api.query_symbol_info([symbol])
print(list(df.columns))
print(df.iloc[0])
quote = api.get_quote(symbol)
api.wait_update(deadline=3)
```

2026-07-03 验证结果：

- `query_quotes(...)` 返回上期所未下市期权数量：`6468`。
- 选中样例期权：`SHFE.au2610C1088`。
- `query_symbol_info([symbol])` 返回字段：

```text
ins_class, instrument_id, instrument_name, price_tick, volume_multiple,
open_limit, max_limit_order_volume, max_market_order_volume,
min_limit_order_volume, min_market_order_volume,
open_max_market_order_volume, open_max_limit_order_volume,
open_min_market_order_volume, open_min_limit_order_volume,
underlying_symbol, strike_price, exchange_id, product_id, expired,
expire_datetime, expire_rest_days, delivery_year, delivery_month,
last_exercise_datetime, exercise_year, exercise_month, option_class,
upper_limit, lower_limit, pre_settlement, pre_open_interest, pre_close,
trading_time_day, trading_time_night
```

样例值节选：

| 字段 | API 返回示例 |
| --- | --- |
| `ins_class` | `OPTION` |
| `instrument_id` | `SHFE.au2610C1088` |
| `instrument_name` | `au2610C1088` |
| `underlying_symbol` | `SHFE.au2610` |
| `strike_price` | `1088.0` |
| `option_class` | `CALL` |
| `expire_datetime` | `1790146800.0` |
| `expire_rest_days` | `82` |
| `delivery_year` / `delivery_month` | `2026` / `10` |
| `exercise_year` / `exercise_month` | `2026` / `9` |
| `last_exercise_datetime` | `1790146800.0` |
| `price_tick` | `0.02` |
| `volume_multiple` | `1000.0` |
| `pre_settlement` | `4.68` |
| `pre_open_interest` | `286.0` |
| `pre_close` | `4.6` |
| `trading_time_day` | `[['09:00:00', '10:15:00'], ['10:30:00', '11:30:00'], ['13:30:00', '15:00:00']]` |
| `trading_time_night` | `[['21:00:00', '26:30:00']]` |

同一个期权再调用 `get_quote(symbol)` 可以拿到 `volume=0`、`open_interest=143`、`last_price=nan`、`bid_price1=nan`、`ask_price1=nan` 等实时行情字段。但这些字段不属于 `query_symbol_info()` 的基础信息返回列，当前也不会默认接入策略级 `accept(option, ctx)`。

### 合约身份字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `symbol` | `str` | 系统内部标准化合约代码，通常为大写，例如 `SHFE.AU2608C600`。 |
| `api_symbol` | `str` | 传给 TqSdk 或从 TqSdk 得到的原始风格合约代码，可能保留品种大小写。 |
| `instrument_id` | `str` | TqSdk 返回的合约代码。 |
| `instrument_name` | `str` | 合约名称，可能为空字符串。 |
| `exchange_id` | `str` | 交易所代码，例如 `SHFE`。 |
| `product_id` | `str` | 品种代码。实际验证中商品期权返回空字符串；不要假设期权一定能用这个字段区分品种。 |
| `ins_class` | `str` | 合约类型。传入 `accept` 的对象通常为 `OPTION`。 |
| `is_option` | `bool` | 是否为期权。当前 `accept` 默认只接收期权，因此一般为 `True`。 |
| `is_future` | `bool` | 是否为期货。传入 `accept` 的 `option` 一般为 `False`。 |
| `expired` | `bool | None` | TqSdk 返回的是否已到期标记。 |

### 期权属性字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `underlying_symbol` | `str` | 标的期货的系统内部代码，例如 `SHFE.AU2608`。 |
| `api_underlying_symbol` | `str` | 标的期货的 TqSdk 原始风格代码。 |
| `strike_price` | `float | None` | 行权价。缺失时为 `None`。 |
| `option_class` | `str` | 期权方向，通常为 `CALL` 或 `PUT`。 |

### 到期、行权、交割字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `exercise_year` | `int | None` | 行权年份，例如 `2026`。缺失时为 `None`。 |
| `exercise_month` | `int | None` | 行权月份，例如 `8`。缺失时为 `None`。 |
| `expiry_key` | `str` | 行权年月文本，例如 `2026-8`；缺失字段会显示为 `NA`。 |
| `expire_datetime` | `float | None` | TqSdk 返回的到期时间戳，通常是 Unix 秒级时间戳。 |
| `expire_date` | `datetime.date | None` | 由 `expire_datetime` 转出的到期日期，便于在脚本里按日期筛选。 |
| `expire_rest_days` | `int | None` | 距到期剩余天数，可能为 `None`。 |
| `last_exercise_datetime` | `float | None` | TqSdk 返回的最后行权时间戳，通常是 Unix 秒级时间戳。 |
| `last_exercise_date` | `datetime.date | None` | 由 `last_exercise_datetime` 转出的最后行权日期。 |
| `delivery_year` | `int | None` | 期货交割日年份。TqSdk 文档说明该字段只对期货品种有效，期权建议使用 `exercise_year`。实际样例期权返回了 `2026`，不要把它作为期权到期筛选的首选字段。 |
| `delivery_month` | `int | None` | 期货交割日月份。TqSdk 文档说明该字段只对期货品种有效，期权建议使用 `exercise_month`。实际样例期权返回了 `10`，不要把它作为期权到期筛选的首选字段。 |

### 合约规格和下单限制字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `price_tick` | `float | None` | 最小变动价位。 |
| `volume_multiple` | `float | None` | 合约乘数。 |
| `open_limit` | `float | None` | 日内开仓限制，表示交易所同一交易日买开和卖开的数量限制；TqSdk 文档说明目前主要针对期货。 |
| `max_limit_order_volume` | `float | None` | 限价单最大下单手数。 |
| `max_market_order_volume` | `float | None` | 市价单最大下单手数。 |
| `min_limit_order_volume` | `float | None` | 限价单最小下单手数。 |
| `min_market_order_volume` | `float | None` | 市价单最小下单手数。 |
| `open_max_limit_order_volume` | `float | None` | 开仓限价单最大手数。 |
| `open_max_market_order_volume` | `float | None` | 开仓市价单最大手数。 |
| `open_min_limit_order_volume` | `float | None` | 开仓限价单最小手数。 |
| `open_min_market_order_volume` | `float | None` | 开仓市价单最小手数。 |

### 涨跌停和昨日参考字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `upper_limit` | `float | None` | 涨停价。`query_symbol_info()` 中可能返回 `0` 或缺失；实时准确值更适合从 `get_quote()` 获取。 |
| `lower_limit` | `float | None` | 跌停价。`query_symbol_info()` 中可能返回 `nan`，系统会转换为 `None`；实时准确值更适合从 `get_quote()` 获取。 |
| `pre_settlement` | `float | None` | 昨结算。 |
| `pre_open_interest` | `float | None` | 昨持仓。 |
| `pre_close` | `float | None` | 昨收盘。 |

### 交易时段字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `trading_time_day` | `tuple[tuple[str, str], ...]` | 日盘交易时段，例如 `(("09:00:00", "10:15:00"), ...)`。 |
| `trading_time_night` | `tuple[tuple[str, str], ...]` | 夜盘交易时段，例如 `(("21:00:00", "26:30:00"),)`。 |

当前字段覆盖范围以 TqSdk `query_symbol_info()` 实际返回的合约基础信息为准。已经通过 API 调用验证过，TqSdk `get_quote()` 可以拿到 `volume`、`open_interest`、`last_price`、`ask_price1`、`bid_price1`、`ask_volume1`、`bid_volume1`、`highest`、`lowest`、`open`、`close`、`average`、`amount` 等实时行情快照字段，但这些字段目前没有作为可靠筛选数据接入 `option` 参数。原因是 `accept` 在策略编译前执行，用来决定合约范围；如果在这里整合实时盘口和价格，就需要启动阶段额外订阅全量候选合约，可能明显增加启动耗时和超时风险。

因此，当前不要在 `accept` 中写：

```python
def accept(option, ctx) -> bool:
    return option.last_price > 10  # 当前不支持
```

如果后续需要“按实时价格、盘口、价差先筛一遍合约”，建议增加一个独立的 quote snapshot enrichment 开关和对应字段，而不是默认混入静态合约筛选。

`option` 对象上保留了 `volume` 和 `open_interest` 两个兼容属性，但本次直接调用 `query_symbol_info()` 打印出的返回列不包含这两个字段，因此它们通常会是 `None`，不建议在 `accept` 里把它们当作可靠筛选依据：

```python
def accept(option, ctx) -> bool:
    return option.volume is not None and option.volume >= 100  # 不推荐，通常为 None
```

如果只是想做全局流动性过滤，优先使用配置里的 `universe.min_volume` 和 `universe.min_open_interest`。策略脚本更适合表达“某个策略自己的到期月、标的、行权价、CALL/PUT 范围”。

## ctx 对象

`ctx` 是筛选上下文，当前提供：

```python
future = ctx.underlying(option)
```

返回值是该期权对应的标的期货 `InstrumentMeta`，找不到时返回 `None`。期货对象也使用同一套字段，但期权专属字段通常为空或 `None`，例如 `strike_price`、`option_class`、`exercise_year`、`exercise_month`。

示例：

```python
def accept(option, ctx) -> bool:
    future = ctx.underlying(option)
    return future is not None and future.product_id.upper() == "AU"
```

系统行为：

- 如果 `accept` 返回 `True`，但系统找不到该期权的标的期货，这个期权会被丢弃，并写 warning 日志。
- 保留下来的期权对应期货会自动加入该策略的监控范围，用户不需要手动保留期货。

## 常用示例

### 按行权年月筛选

```python
MIN_EXERCISE_YYYYMM = 202608
MAX_EXERCISE_YYYYMM = 202612


def accept(option, ctx) -> bool:
    if option.exercise_year is None or option.exercise_month is None:
        return False
    exercise_yyyymm = option.exercise_year * 100 + option.exercise_month
    return MIN_EXERCISE_YYYYMM <= exercise_yyyymm <= MAX_EXERCISE_YYYYMM
```

`exercise_year/month` 表示期权行权年月。对于期权来说，它可能早于标的期货的交割年月。例如某些 `au2609` 期权的 `exercise_year/month` 可能是 `2026/8`，而 `delivery_year/month` 是 `2026/9`。

### 按具体到期日筛选

```python
from datetime import date


MIN_EXPIRE_DATE = date(2026, 8, 1)
MAX_EXPIRE_DATE = date(2026, 8, 31)


def accept(option, ctx) -> bool:
    return (
        option.expire_date is not None
        and MIN_EXPIRE_DATE <= option.expire_date <= MAX_EXPIRE_DATE
    )
```

### 按剩余到期天数筛选

```python
def accept(option, ctx) -> bool:
    return option.expire_rest_days is not None and 10 <= option.expire_rest_days <= 60
```

### 只保留某个标的品种

```python
def accept(option, ctx) -> bool:
    future = ctx.underlying(option)
    return future is not None and future.product_id.upper() == "AU"
```

### 只保留 CALL

```python
def accept(option, ctx) -> bool:
    return option.option_class == "CALL"
```

注意：对 CP 组合策略来说，只保留 CALL 会导致缺少 PUT 配对，通常会让该策略编译不出 CP 条件。系统会记录 warning 并跳过该策略。

### 按行权价范围筛选

```python
def accept(option, ctx) -> bool:
    return option.strike_price is not None and 560 <= option.strike_price <= 680
```

### 按标的和到期月组合筛选

```python
ALLOWED_UNDERLYINGS = {"SHFE.AU2608", "SHFE.AU2610"}
ALLOWED_MONTHS = {8, 10}


def accept(option, ctx) -> bool:
    return (
        option.underlying_symbol in ALLOWED_UNDERLYINGS
        and option.exercise_month in ALLOWED_MONTHS
    )
```

### 不要在 accept 中按实时流动性筛选

```python
MIN_VOLUME = 100
MIN_OPEN_INTEREST = 100


def accept(option, ctx) -> bool:
    # 不推荐：当前 accept 的 option 默认不接入 get_quote() 实时字段。
    return (
        option.volume is not None
        and option.open_interest is not None
        and option.volume >= MIN_VOLUME
        and option.open_interest >= MIN_OPEN_INTEREST
    )
```

如果想按成交量或持仓量做第一层过滤，建议把流动性条件放到全局配置；这部分由系统在发现 universe 时用行情快照处理，而不是由策略级 `accept` 处理：

```toml
[universe]
min_volume = 100
min_open_interest = 100
```

## 对不同策略的影响

### CP 组合策略

CP 组合需要同一标的、同一到期月、同行权价下同时存在 CALL 和 PUT，还需要标的期货价格参与计算。

因此：

- `accept` 只决定哪些期权进入策略。
- 标的期货由系统自动补齐。
- 如果筛选后某个行权价只剩 CALL 或只剩 PUT，该行权价不会生成 CP 条件。
- 如果整个策略最终没有任何可编译条件，系统会记录 warning 并跳过该策略。

### 价差策略

价差策略会在同一标的、同一到期月、同一方向的期权之间生成价差条件。

因此：

- 如果只保留一个 CALL 或一个 PUT，可能无法形成价差组合。
- 如果按行权价范围筛得太窄，也可能导致条件数为 0。

## 日志怎么看

启用脚本后，启动日志会显示筛选造成的范围变化：

```text
Applied strategy filter: strategy=黄金近月CP script=... function=accept scope=options options=120->24 futures=6->2 price_symbols=126->26
Strategy compiled after filter: strategy=黄金近月CP script=... conditions=12 options=24 futures=2 price_symbols=26
Monitoring universe after strategy filters: strategies=2 options=40 futures=3 price_symbols=43
```

含义：

- `options=120->24`：该策略筛选前有 120 个期权，筛选后保留 24 个。
- `futures=6->2`：系统自动补齐后，该策略需要 2 个标的期货。
- `price_symbols=126->26`：该策略最终需要订阅或回测取价的合约数。
- 最后一行是所有未跳过策略合并后的实际监控范围。

如果某个策略没有配置脚本，会看到：

```text
Strategy filter skipped: strategy=价差预警 script=<none> function=accept scope=options options=120 futures=6 price_symbols=126
```

## 编写注意事项

- 始终返回 `True` 或 `False`。
- 对可能缺失的字段先判断 `None`，尤其是 `strike_price`、`exercise_year`、`exercise_month`、`expire_date`、`expire_rest_days`、`lower_limit`。
- 不要依赖 `option.volume` 和 `option.open_interest` 做策略级筛选；当前它们不是 `query_symbol_info()` 基础字段，通常为空。
- 不要在 `accept` 里请求网络、登录 TqSdk、订阅行情或做很慢的计算；它会对每个期权调用一次。
- 不要依赖实时价格，`accept` 阶段没有行情快照。
- 不要修改 `option` 或 `ctx`，它们应当只读使用。
- 脚本是本机可信代码，系统不会做安全沙箱；不要运行来源不明的脚本。
- 同一个脚本可以配置给多个策略，但每个策略会独立筛选和编译。
- 如果要按“每个到期月成交量前 N 名”这类需要全局排序的规则筛选，当前 V1 的逐个 `accept` 接口不适合，需要后续扩展批量筛选接口。
