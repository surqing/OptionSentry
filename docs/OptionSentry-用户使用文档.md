# OptionSentry 用户使用文档

> 适用版本：0.1.1
> 本文档面向最终用户，介绍 OptionSentry 是什么、如何安装部署、如何配置与运行，以及各类功能的使用方法。

---

## 一、项目简介

**OptionSentry** 是一个基于 [TqSdk](https://www.shinnytech.com/tqsdk/) 的**期货期权行情监控与预警工具**。

它做的事情很简单：接入期货期权实时行情，自动发现合约、按你设定的策略计算指标，当指标进入你关心的区间时，及时给出预警。

- 支持**实盘行情监控**和**历史回测**两种运行模式。
- 提供**图形界面（GUI）**和**命令行**两种操作方式。
- 内置两类策略：`CP组合预警` 和 `价差预警`。
- 预警可通过**文件、邮件、GUI 弹窗、声音**四种渠道送达。

**重要边界（请务必了解）：**

- 本项目**只做行情分析和告警，不包含任何自动下单、撤单或调仓逻辑**。预警结果需要你自行核验后再做决策。
- 当前版本仅使用行情的**最新价（last）**作为计算基准。
- 项目本身不提供交易能力，也不持有任何资金账户的操作权限。

---

## 二、环境要求

| 项目 | 要求 |
| --- | --- |
| 编程语言 | Python **3.11 或更高版本** |
| 包管理工具 | `uv`（推荐，用于安装依赖与运行） |
| 行情数据源 | 一个可用的 **TqSdk 账号**（提供行情与合约元数据）。尚无账号可前往 [https://www.shinnytech.com/](https://www.shinnytech.com/) 注册 |
| 图形界面 | 当前系统需支持 PyQt6 桌面环境（Windows / Linux / macOS 均可，只要能显示窗口） |
| Windows 打包 | 需要 PowerShell（仅当你要自行打包 Windows 安装包时） |

**主要依赖库**（已在 `pyproject.toml` 中声明，安装时自动处理）：

- `tqsdk`（行情接入，版本 ≥ 3.10.1）
- `pyqt6`（图形界面，版本 ≥ 6.11.0）
- `tomlkit`（配置文件读写，版本 ≥ 0.15.0）
- 开发/打包用：`pytest`、`pyinstaller`

---

## 三、安装部署

### 3.1 首次安装

在项目的根目录下，打开终端（PowerShell / Bash 均可），执行：

```powershell
# 1. 安装项目依赖（含开发依赖）
uv sync --dev

# 2. 从模板复制出你的配置文件
Copy-Item config.example.toml config.toml
```

> 说明：`config.example.toml` 是配置模板（内含占位符，不含真实信息），请始终基于它复制出 `config.toml` 后再修改。

### 3.2 准备 TqSdk 登录凭据

OptionSentry 在运行时需要 TqSdk 账号密码。尚无账号可前往 [https://www.shinnytech.com/](https://www.shinnytech.com/) 注册。推荐通过**环境变量**注入（最安全）：

```powershell
$env:TQSDK_USERNAME = "your-tqsdk-username"
$env:TQSDK_PASSWORD = "your-tqsdk-password"
```

> 如果你使用图形界面，也可以直接在登录页输入账号密码，勾选「记住我」后账号密码会写入当前 `config.toml`（见下方 3.3）。**请勿把包含真实凭据的 `config.toml` 提交到版本库。**

### 3.3 图形界面登录（可选）

直接启动 GUI 后，会出现登录窗口：

1. **配置文件**：默认指向当前目录的 `config.toml`，可点「浏览」选择其他配置文件。
2. **账号 / 密码**：留空则读取配置文件里已「记住」的账号或环境变量；填写则使用你输入的账号。账号和密码**必须同时填写或同时留空**。
3. **记住我**：勾选后，登录成功会把账号密码写入所选的 `config.toml`（明文保存，仅建议在本机可信环境使用）。
4. 点击「登录」，校验通过后进入主窗口。

### 3.4 启动方式

- **图形界面**：`uv run optionsentry-gui`
- **命令行**：`uv run optionsentry --config config.toml`

---

## 四、快速开始

只需四步即可体验核心功能（以实盘监控为例）：

```powershell
# 1. 安装依赖
uv sync --dev

# 2. 生成配置文件
Copy-Item config.example.toml config.toml

# 3. 设置 TqSdk 凭据
$env:TQSDK_USERNAME = "你的账号"
$env:TQSDK_PASSWORD = "你的密码"

# 4. 启动图形界面（推荐新手）
uv run optionsentry-gui
```

进入主窗口后：

1. 默认配置已经启用了两条策略（`CP组合正向预警`、`CP组合负向预警`、`价差预警`），合约范围限定在黄金（AU）。
2. 点击右上角「**启动**」，程序会先登录并发现合约，再开始持续监控行情。
3. 当某个合约的指标进入预警区间时，会在「**预警**」标签页看到记录，邮件/文件等渠道也会按配置发出通知。
4. 需要停止时，点击「**停止**」。

> 想快速改配置？直接点主窗口的「**配置**」标签页，所有设置都能在界面里完成，点「保存配置」即可生效（保存后重新点「启动」会用新配置运行）。

---

## 五、详细功能使用说明

### 5.1 运行模式（实盘 / 回测）

在配置文件的 `[runtime]` 段设置：

```toml
[runtime]
mode = "live"                 # live = 实盘监控；backtest = 历史回测
price_basis = "last"          # 当前仅支持 last（最新价）
alert_on_first_match = false   # 见下方说明
```

- **live（实盘）**：连接 TqSdk 实时行情，持续监控。适合日常盯盘预警。
- **backtest（回测）**：用 TqSdk 历史行情回放，检验策略在历史时间段的表现。需要同时配置 `[backtest]` 段的起止日期（见 5.5）。
- **alert_on_first_match**：
  - `false`（默认）：只在指标「从非触发变为触发」的**那一刻**告警，避免启动即被已有触发状态刷屏。
  - `true`：首次匹配到区间就立即告警（包括启动瞬间已经处于区间内的情形）。

### 5.2 合约范围（监控哪些期权）

在配置文件的 `[universe]` 段设置：

```toml
[universe]
mode = "指定模式"              # all = 全市场；指定模式 = 按名单筛选
only_do = ["AU"]              # 指定模式：先纳入匹配的品种/合约
not_do = []                   # 再从上面结果中排除
min_volume = 0                # 实盘流动性过滤，0 = 不启用
min_open_interest = 0          # 实盘持仓量过滤，0 = 不启用
```

- **all 模式**：扫描全部交易所的活跃期权。可配合 `exchange_ids` 限定交易所，例如 `["SHFE", "DCE", "CZCE", "INE", "GFEX", "CFFEX"]`。
- **指定模式**：先按 `only_do` 纳入匹配的品种或合约，再用 `not_do` 排除。
  - 匹配规则：品种代码（如 `AU`）、具体合约代码（如 `AU2607`）都能作为筛选词。
  - 例：`only_do = ["AG"]` 只监控白银；`only_do = ["AU"]`、`not_do = ["AU2607"]` 监控黄金但排除 2607 合约。
- **流动性过滤**（仅实盘生效）：`min_volume` 和 `min_open_interest` 设为大于 0 时，会过滤掉成交量/持仓量不达标的合约。`0` 表示不启用该过滤。

> 提示：当订阅的合约总数超过约 13000 个时，程序会拒绝启动并给出压缩范围的建议。请优先使用「指定模式」并缩小范围。

### 5.3 策略配置

策略在配置文件中以 `[[strategies]]` 数组配置，每条策略一个表：

```toml
[[strategies]]
type = "cp_combo"
min_value = 0.01
max_value = inf
name = "CP组合正向预警"
selected = true

[[strategies]]
type = "abs_spread"
min_value = -inf
max_value = 0.1
name = "价差预警"
selected = true
```

字段含义：

| 字段 | 说明 |
| --- | --- |
| `type` | 策略类型，支持 `cp_combo`（CP组合）或 `abs_spread`（价差） |
| `min_value` / `max_value` | 触发区间，**判断条件为 `min_value < 指标值 < max_value`**（开区间，不含端点） |
| `name` | 展示在日志、GUI、邮件中的名称，建议取易懂的中文名 |
| `selected` | 是否启用该策略（`true` / `false`） |
| `filter_script` | 可选，自定义期权筛选脚本路径（相对路径以配置文件所在目录为基准） |
| `filter_function` | 筛选函数名，默认 `accept` |
| `filter_scope` | 当前仅支持 `options` |

#### CP组合预警（cp_combo）

对**同一标的期货、同一行权年月、同一执行价**下的认购期权（C）、认沽期权（P）和标的期货（F），计算 **CP 组合偏离率**：

```
偏离率 = (C 最新价 - P 最新价 + 执行价 K - 期货最新价) / 期货最新价
```

当偏离率落入你设定的 `(min_value, max_value)` 区间时触发预警。

> 例：模板中 `CP组合正向预警` 设为 `(0.01, +inf)`，即偏离率超过 1% 才预警；`CP组合负向预警` 设为 `(-inf, -0.01)`，即偏离率低于 -1% 才预警。这样把正负两个方向拆成两条独立可开关的策略。

#### 价差预警（abs_spread）

对**同一标的期货、同一行权年月、同一期权方向（同为认购或同为认沽）**下的不同行权价期权，两两组合，计算**价差比例**：

```
价差比例 = (期权A最新价 - 期权B最新价) / |执行价A - 执行价B|
```

当价差比例落入设定区间时触发预警。常用于发现相邻行权价之间的定价异常。

> 例：模板中 `价差预警` 设为 `(-inf, 0.1)`，即价差比例小于 0.1 时预警。

### 5.4 策略级自定义筛选脚本（进阶）

每条策略都可挂一个 Python 脚本，在监控启动阶段按你的规则**只保留关心的期权**。脚本需提供如下函数：

```python
def accept(option, ctx) -> bool:
    """返回 True 保留该期权；返回 False 排除它。"""
    if option.expire_rest_days is None:
        return False
    return 10 <= option.expire_rest_days <= 60
```

- 返回值**必须是 `bool`**（`True`/`False`），不能返回 `1`、`0`、`None`、字符串或列表。
- `option` 是期权的基础信息对象（含标的、行权价、期权方向、到期剩余天数等），**不是实时行情对象**，不含最新价、成交量等实时字段。
- `ctx.underlying(option)` 可获取该期权对应的标的期货信息。
- 在配置中启用：

```toml
[[strategies]]
type = "cp_combo"
min_value = 0.01
max_value = inf
name = "CP组合正向预警"
selected = true
filter_script = "user_filter_scripts/by_expire_rest_days.py"
filter_function = "accept"
filter_scope = "options"
```

项目内置两个示例脚本（位于 `user_filter_scripts/`）：

- `by_expire_rest_days.py`：按「到期剩余天数」区间筛选。
- `by_expiry.py`：按「到期日期」区间筛选。

> 编写脚本时如需查看 `option` 和 `ctx` 支持的全部字段，见项目 `docs/策略特定的合约范围筛选函数说明文档.md`。

### 5.5 回测模式配置

回测模式需要 `runtime.mode = "backtest"`，并在 `[backtest]` 段配置时间范围：

```toml
[backtest]
start_dt = "2026-01-02"
end_dt = "2026-01-05"
duration_seconds = 60
data_length = 2
initial_price_timeout_seconds = 120
subscription_batch_size = 50
```

| 字段 | 说明 |
| --- | --- |
| `start_dt` / `end_dt` | 回测起止日期，必填 |
| `duration_seconds` | K 线周期，**当前仅支持 60（秒）** |
| `data_length` | 每次回放保留的 K 线根数 |
| `initial_price_timeout_seconds` | 等待初始行情的时间上限（秒） |
| `subscription_batch_size` | 每批订阅的合约数 |

> 回测会按策略涉及的「标的 + 到期月」分组回放，结果同样写入预警记录、文件与邮件。回测不影响任何真实账户。

### 5.6 预警渠道（通知方式）

在配置文件的 `[notifier]` 段设置：

```toml
[notifier]
alert_log_path = "logs/alerts.jsonl"   # 文件告警的日志路径

[notifier.channels]
popup = false     # GUI 本地弹窗
sound = false     # GUI 声音提示
file = true       # 写入 JSONL 预警日志
email = true      # 发送邮件

[notifier.popup]
duration_seconds = 2

[notifier.sound]
duration_seconds = 2
```

| 渠道 | 说明 |
| --- | --- |
| `file` | 把每条预警写入 JSONL 日志文件。路径会按运行模式分目录，例如 `logs/live/alerts.jsonl`（实盘）或 `logs/backtest/alerts.jsonl`（回测） |
| `email` | 通过 SMTP 发送邮件，支持按 `alert_interval_seconds` 聚合多条预警后批量发送（设为 `0` 则每条立即发） |
| `popup` | GUI 内弹出提示气泡（仅 GUI 运行时有效） |
| `sound` | GUI 内蜂鸣声提示（仅 GUI 运行时有效） |

**邮件渠道的完整配置**（SMTP 信息）：

```toml
[notifier.email]
smtp_host = "smtp.example.com"
smtp_port = 587
smtp_timeout_seconds = 10
alert_interval_seconds = 60
username = "alert@example.com"
password_env = "SMTP_PASSWORD"      # 密码建议走环境变量；也可直接写 password
from_addr = "alert@example.com"
to_addrs = ["receiver@example.com"]
use_tls = true
failure_backoff_seconds = 300
```

> 邮件密码推荐使用环境变量 `SMTP_PASSWORD`。若直接写在配置里，请妥善保管该 `config.toml`。

### 5.7 图形界面（GUI）使用

启动 `uv run optionsentry-gui` 并登录后，主窗口包含四个标签页：

#### 监控 标签页

- 顶部「**状态**」面板展示：运行状态、模式、配置文件、凭据来源、期权数、期货数、价格合约数、策略数、条件数、活跃预警数、累计预警数、最新行情时间。
- 「**当前活跃预警记录**」表格：实时展示当前处于触发状态的条件（指标仍在区间内即持续显示）。支持的表格交互：
  - **排序**：点击列标题切换升序/降序。
  - **筛选**：点击列标题右侧的「筛」按钮，按数值范围（如 `8 10`、`8-10`、`8,10`）过滤行。
  - **按策略过滤**：表格上方的策略按钮（如「全部策略」「CP组合正向预警」）可只看某一策略的记录。
  - **刷新**：「手动刷新」按钮立即刷新；勾选「自动刷新」后按设定的间隔（10 秒 / 30 秒 / 1 分钟 / 3 分钟 / 5 分钟 / 10 分钟）自动刷新。

#### 预警 标签页

- 展示**所有触发过的预警记录**（滚动列表），新记录自动追加在底部。同样支持排序与筛选。

#### 配置 标签页

- 提供可视化配置编辑器，覆盖运行、合约范围、策略、回测、TqSdk、通知、日志等全部设置。
- 策略表格支持「**添加策略**」「**删除**」「**选择脚本**」（挂筛选脚本）。
- 改完点「**保存配置**」即可写回 `config.toml`；「**重新加载**」可从文件重新读入。
- 注意：保存配置后，**当前正在运行的监控仍使用启动时的配置**，需停止后再「启动」才会应用新配置。

#### 日志 标签页

- 实时显示运行日志，便于排查问题。

### 5.8 命令行运行

```powershell
# 使用指定配置文件运行监控
uv run optionsentry --config config.toml
```

命令行模式会把日志同时输出到控制台和滚动日志文件（见 5.9），预警按 `[notifier]` 配置发出（GUI 弹窗/声音在命令行模式下不生效）。

### 5.9 日志

运行日志由 `[logging]` 配置，默认写入 `logs/<模式>/optionsentry.log`，并启用滚动日志（控制单个文件体积与备份数）：

```toml
[logging]
level = "INFO"
log_dir = "logs"
log_file = "optionsentry.log"
max_bytes = 5000000
backup_count = 5
cycle_summary_interval_seconds = 60   # 周期性汇总间隔（秒），0 = 每个周期都记
```

---

## 六、常见问题（FAQ）

### Q1. 启动时提示 TqSdk 登录失败 / 需要账号密码？

- 还没有 TqSdk 账号？前往 [https://www.shinnytech.com/](https://www.shinnytech.com/) 注册一个。
- 确认已设置环境变量 `TQSDK_USERNAME` 和 `TQSDK_PASSWORD`，或在 GUI 登录页填写了账号密码。
- 账号和密码必须**同时填写或同时留空**，只填一个会报错。
- 若在 GUI 勾选了「记住我」，账号密码已写入 `config.toml`，可直接复用；如失效请重新填写。
- 仍失败多为账号或密码错误，请到 TqSdk 核对凭据。

### Q2. 提示「需要订阅的合约数量过多，已停止启动」？

订阅合约数超过约 13000 个上限。请压缩范围：

- 把 `[universe]` 的 `mode` 从 `all` 改为「指定模式」，只填写要监控的品种（如 `only_do = ["AU"]`）。
- 缩小 `exchange_ids`，只扫描必要交易所。
- 提高 `min_volume` 或 `min_open_interest`，过滤掉低流动性期权。
- 减少要监控的到期月份或标的范围。

### Q3. 回测时提示「未能在限定时间内收到初始 K 线行情」？

通常是候选合约过多或网络较慢，导致初始化超时。可：

- 调大 `initial_price_timeout_seconds`。
- 缩小 `[universe]` 范围，减少需要订阅的合约数量。

### Q4. 邮件预警没收到？

- 检查 `[notifier.email]` 的 `smtp_host`、`smtp_port`、`use_tls` 是否正确。
- 确认 `from_addr`、`to_addrs` 已填写，`username` 与密码（`password` 或 `password_env` 对应的环境变量）正确。
- 若设置了 `alert_interval_seconds > 0`，系统会先聚合一段时间再发送，请稍等或临时设为 `0` 测试。
- 邮件发送失败后会按 `failure_backoff_seconds` 退避一段时间，期间不再尝试。

### Q5. 某些期权订阅成功但行情一直为空（NaN）？

这是**账号行情权限**问题：免费 TqSdk 账号对部分交易所（如 SSE/SZSE 期权）无访问权限，其行情字段会全部为 `NaN`，表现为订阅成功但始终无数据。解决方向：

- 升级为具备相应权限的付费行情账户；或
- 在 `[universe]` 中过滤掉无权限的交易所/品种。

### Q6. 配置保存后监控没有用上新配置？

保存配置只写文件。**当前正在运行的监控继续使用启动时的配置**。请先点「停止」，再点「启动」以应用新配置。

### Q7. 「记住我」保存的账号密码安全吗？

GUI 的「记住我」会把 TqSdk / 邮箱密码**以明文写入本地 `config.toml`**（该文件已被 gitignore，不会上传仓库），但属于本机明文风险。建议：

- 仅在可信本机使用「记住我」；
- 或对本地 `config.toml` 做好文件权限保护；
- 长期方案可改为使用环境变量注入凭据。

### Q8. 启动就收到大量预警，很吵？

把 `[runtime]` 的 `alert_on_first_match` 设为 `false`（默认即此值）。这样仅在指标「从未触发变为触发」的瞬间告警，不会在启动瞬间把已处于区间内的状态全部报一遍。

### Q9. 为什么有的策略字段会报错（配置校验失败）？

程序在启动前会严格校验配置，常见问题包括：

- `runtime.mode` 必须是 `live` 或 `backtest`。
- 回测模式必须填写 `start_dt` 与 `end_dt`，且 `duration_seconds` 只能为 `60`。
- `universe.mode` 为「指定模式」时必须填写 `only_do`。
- 每条策略必须有 `min_value` 和 `max_value`，且 `min_value < max_value`。
- 策略 `type` 仅支持 `cp_combo`、`abs_spread`。
- 筛选脚本路径必须存在、函数必须可加载且返回 `bool`。

出错时控制台/GUI 会给出具体的中文错误信息，按提示修正即可。

---

## 七、目录结构参考

```
.
├── optionsentry/                 # 应用主包
│   ├── cli.py                    # 命令行入口
│   ├── config.py                 # 配置解析与校验
│   ├── runner.py                 # 监控运行主循环
│   ├── strategies.py             # 内置策略
│   ├── notifiers.py              # 文件 / 邮件通知
│   ├── data_sources/             # TqSdk 数据源（发现/订阅/回测）
│   └── gui/                      # PyQt6 图形界面
├── user_filter_scripts/          # 用户筛选脚本示例
├── docs/                         # 补充文档（含筛选函数字段说明）
├── config.example.toml           # 配置模板（请复制后修改）
├── package.ps1                   # Windows 打包脚本（可选）
└── pyproject.toml                # 项目元数据与依赖
```

---

## 八、注意事项

- `config.toml`、`.env`、日志与打包产物属于本地文件，默认不应提交到版本库。
- 邮件告警需要配置可用的 SMTP 服务、发件人、收件人及密码（或密码环境变量）。
- 实盘与回测都依赖 TqSdk 账号权限及对应行情的可用性。
- 本项目**不提供交易执行能力**，所有预警结果都需你人工核验后再做决策。
- 回测结果仅反映历史行情下的策略表现，不构成任何投资建议。
