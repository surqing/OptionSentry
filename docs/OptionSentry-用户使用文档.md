# OptionSentry 用户使用文档

OptionSentry 用于监控期货期权行情，在策略指标进入指定区间时记录并发送预警。它不会自动下单，预警结果需要人工核验。

## 一、安装与启动

### 1. 环境

- Python 3.11 或更高版本
- uv
- TqSdk 账号
- GUI 用户需要可用的桌面环境

### 2. 安装

~~~powershell
uv sync --dev
Copy-Item config.example.toml config.toml
~~~

当前配置格式为 schema_version = 1，不兼容旧配置。升级用户应重新复制 config.example.toml，不要把旧字段逐项搬入新文件。

### 3. 设置凭据

推荐使用环境变量：

~~~powershell
$env:TQSDK_USERNAME = "你的账号"
$env:TQSDK_PASSWORD = "你的密码"
~~~

配置文件只保存环境变量名，不保存账号密码。

### 4. 启动

~~~powershell
# GUI
uv run optionsentry-gui

# 命令行
uv run optionsentry --config config.toml
~~~

GUI 登录页：

1. 选择配置文件。
2. 可临时输入账号和密码，两者必须同时填写。
3. 两个输入框都留空时，读取配置指定的环境变量。
4. 登录凭据只在本次进程中使用，不会写回 TOML。

## 二、GUI 使用

界面面向中文用户设计，内部配置值仍使用英文，保存后可直接供命令行使用。

### 1. 监控

状态区域显示运行状态、实盘/回测、配置路径、凭据来源、合约数、策略数、条件数和预警数。

活跃预警表支持：

- 点击表头排序；
- 使用表头筛选数值或文本；
- 按策略名称过滤；
- 手动刷新或设置中文刷新间隔。

### 2. 预警

显示本次进程中已经触发的预警记录。文件渠道会另外写入 JSONL。

### 3. 配置

可编辑运行、合约范围、策略、回测、TqSdk、通知和日志。

策略表包含：

- 启用
- ID
- 类型
- 名称
- 参数
- 筛选脚本

“添加策略”先选择中文策略类型，再打开参数窗口。参数控件由策略定义自动生成；“编辑策略”可修改 ID、中文名称、启用状态、参数和筛选脚本。

保存配置只写文件。若监控正在运行，当前任务继续使用启动时的配置；停止后重新启动才会应用新配置。

### 4. 日志

显示启动、发现合约、编译条件、行情循环和通知错误。完整日志同时写入 logs/live 或 logs/backtest。

## 三、配置说明

完整模板见 [config.example.toml](../config.example.toml)。

### 1. 配置版本

~~~toml
schema_version = 1
~~~

缺少版本、版本不支持、未知字段或旧字段都会阻止启动。这样可以避免拼写错误被静默忽略。

### 2. 运行模式

~~~toml
[runtime]
mode = "live"
alert_on_first_match = false
~~~

- live：实盘行情。
- backtest：历史回测，必须配置回测起止日期。
- alert_on_first_match = false：首次发现已经触发的条件不立即预警，只在之后从未触发进入触发时预警。
- alert_on_first_match = true：首次触发状态也立即预警。

GUI 对应显示“实盘”和“回测”。

### 3. 合约范围

指定品种或合约：

~~~toml
[universe]
mode = "include"
include = ["SHFE.au"]
exclude = ["SHFE.au2607"]
exchanges = ["SHFE"]
min_volume = 0
min_open_interest = 0
~~~

全市场或指定交易所：

~~~toml
[universe]
mode = "all"
include = []
exclude = []
exchanges = ["SHFE", "DCE"]
min_volume = 0
min_open_interest = 0
~~~

- include 模式必须填写 include。
- exclude 从已纳入范围中排除品种或具体合约。
- exchanges 在 all 模式限制交易所；空数组表示不额外限制。
- min_volume、min_open_interest 大于 0 时在实盘发现阶段过滤低流动性合约。

GUI 对应显示“指定范围”和“全部合约”。

### 4. TqSdk

~~~toml
[data_source]
provider = "tqsdk"

[data_source.tqsdk]
username_env = "TQSDK_USERNAME"
password_env = "TQSDK_PASSWORD"
symbol_info_batch_size = 500
quote_subscription_batch_size = 500
~~~

username_env 和 password_env 是环境变量名称，不是账号和密码。

### 5. 策略

~~~toml
[[strategies]]
id = "cp_combo_positive"
type = "cp_combo"
name = "CP组合正向预警"
enabled = true

[strategies.parameters]
min_value = 0.01
max_value = inf
~~~

| 字段 | 说明 |
| --- | --- |
| id | 策略实例的唯一身份，使用小写英文、数字、下划线或连字符 |
| type | 策略实现类型 |
| name | GUI、日志和通知中显示的中文名称 |
| enabled | 是否启用 |
| parameters | 该 type 声明的专属参数 |

同一 type 可以配置多条。例如 CP 正向和负向各使用一个 id。

所有范围都使用开区间：

~~~text
min_value < 指标值 < max_value
~~~

#### CP 组合预警

同一标的、到期和执行价的认购 C、认沽 P、执行价 K 与标的 F：

~~~text
指标 = (C - P + K - F) / F
~~~

模板用两条 cp_combo 分别监控大于 1% 和小于 -1% 的偏离。

#### 价差预警

同一标的、到期和期权方向下，不同行权价期权两两组合：

~~~text
指标 = (期权A价格 - 期权B价格) / (执行价A - 执行价B)
~~~

腿顺序由策略统一处理。

### 6. 策略筛选脚本

~~~toml
[strategies.filter]
script = "user_filter_scripts/by_expire_rest_days.py"
entrypoint = "accept"
~~~

脚本示例：

~~~python
def accept(option, ctx) -> bool:
    if option.expire_rest_days is None:
        return False
    return 10 <= option.expire_rest_days <= 60
~~~

返回值必须是 bool。脚本使用静态合约信息，不提供实时行情。详细接口见 [筛选函数说明](strategy_filter_accept.md)。

### 7. 回测

~~~toml
[backtest]
start_date = 2026-01-02
end_date = 2026-01-05
kline_duration_seconds = 60
data_length = 2
initialization_timeout_seconds = 120
subscription_batch_size = 50
~~~

- backtest 模式必须提供 start_date 和 end_date。
- 当前 kline_duration_seconds 只能是 60。
- 系统按策略实际需要的标的与到期组回放，不会把全部候选合约一次性塞入一个回测订阅。

### 8. 通知

~~~toml
[notifications.channels]
popup = false
sound = false
file = true
email = true

[notifications.file]
path = "logs/alerts.jsonl"

[notifications.popup]
duration_seconds = 2

[notifications.sound]
duration_seconds = 2
~~~

- popup、sound 只在 GUI 中生效。
- file 写入 logs/live 或 logs/backtest 下的 JSONL。
- email 使用 SMTP。

邮件配置：

~~~toml
[notifications.email]
smtp_host = "smtp.example.com"
smtp_port = 587
smtp_timeout_seconds = 10
aggregation_seconds = 60
username_env = "SMTP_USERNAME"
password_env = "SMTP_PASSWORD"
from_address = "alert@example.com"
to_addresses = ["receiver@example.com"]
use_tls = true
failure_backoff_seconds = 300
~~~

设置环境变量：

~~~powershell
$env:SMTP_USERNAME = "alert@example.com"
$env:SMTP_PASSWORD = "你的邮箱授权码"
~~~

aggregation_seconds = 0 表示每条立即发送；大于 0 时先聚合。SMTP 账号和密码不能直接写进 TOML。

### 9. 日志

~~~toml
[logging]
level = "INFO"
directory = "logs"
filename = "optionsentry.log"
max_bytes = 5000000
backup_count = 5
summary_interval_seconds = 60
~~~

## 四、常见问题

### 1. 提示旧字段或未知字段

当前版本不兼容旧配置。请从最新 config.example.toml 复制新文件。常见已删除字段：

- price_basis
- datasource
- notifier
- only_do、not_do、exchange_ids
- threshold、selected
- 策略表中的扁平 min_value、max_value
- filter_script、filter_function、filter_scope

不要只删掉报错字段；应按新模板重建结构。

### 2. TqSdk 登录失败

- 账号和密码必须同时输入或同时留空。
- 留空时检查配置中的 username_env/password_env 及对应环境变量。
- GUI 不保存凭据，下次启动仍需环境变量或重新输入。
- 继续失败时检查账号、密码与行情权限。

### 3. include 模式报错

universe.mode = "include" 时 include 不能为空。GUI 中选择“指定范围”后填写品种或合约。

### 4. 回测无法初始化

- 确认起止日期有效。
- 适当增加 initialization_timeout_seconds。
- 缩小 universe 范围。
- 检查账号的历史行情权限。

### 5. 邮件未发送

- 检查 notifications.channels.email 是否为 true。
- 检查 SMTP 主机、端口、TLS、发件人与收件人。
- 检查 username_env/password_env 对应环境变量。
- aggregation_seconds 大于 0 时需要等待聚合窗口。
- 失败后会按 failure_backoff_seconds 暂停重试。

### 6. 保存配置后监控没有变化

停止当前监控，再重新启动。运行中的任务不会热切换配置。

### 7. 启动时大量预警

将 alert_on_first_match 设为 false。

### 8. 某些行情始终为空

通常是账号没有相应交易所或历史行情权限。缩小 exchanges/include，或使用具备权限的账户。

## 五、安全与风险提示

- config.toml、环境变量文件、日志和构建产物不要提交。
- GUI 输入的凭据不会落盘，但仍应保护运行中的本机进程。
- 预警不等同于交易信号，不构成投资建议。
- 回测结果只反映历史数据，不保证未来表现。
