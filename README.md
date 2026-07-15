# OptionSentry

OptionSentry 是基于 TqSdk 的期货期权行情监控与预警工具，提供命令行和 PyQt6 图形界面。它负责发现合约、编译策略条件、订阅行情、计算指标和发送预警，不包含自动下单、撤单或调仓。

## 主要功能

- 实盘监控与历史回测。
- 中文 GUI：登录、可视化配置、启停监控、活跃预警、历史预警和日志。
- 严格的版本化 TOML 配置；未知字段和旧格式直接报错。
- 元数据驱动的策略参数、GUI 表单和注册发现。
- 按策略执行单元精确订阅；回测按标的与到期组隔离执行。
- 内置 CP 组合预警和价差预警。
- 策略级期权筛选脚本。
- JSONL 文件、SMTP 邮件、GUI 弹窗和声音通知。
- Windows PyInstaller 打包。

## 环境要求

- Python 3.11 或更高版本。
- uv 包管理工具。
- 可用的 TqSdk 账号。
- GUI 需要 PyQt6 桌面环境；Windows 打包需要 PowerShell。

## 快速开始

1. 安装依赖。

~~~powershell
uv sync --dev
~~~

2. 从最新模板创建配置。

~~~powershell
Copy-Item config.example.toml config.toml
~~~

3. 设置 TqSdk 凭据。

~~~powershell
$env:TQSDK_USERNAME = "your-tqsdk-username"
$env:TQSDK_PASSWORD = "your-tqsdk-password"
~~~

4. 启动 GUI 或命令行。

~~~powershell
uv run optionsentry-gui
uv run optionsentry --config config.toml
~~~

GUI 登录页可以临时输入账号密码；凭据只在本次进程中使用，不会写入配置文件。登录字段留空时，程序读取配置指定的环境变量。

## 配置

配置以 [config.example.toml](config.example.toml) 为唯一模板。当前 schema_version 为 1，不兼容旧配置；升级后应从模板重新创建，不要继续使用 datasource、notifier、selected、threshold 或扁平策略参数等旧字段。

### 运行与合约范围

~~~toml
schema_version = 1

[runtime]
mode = "live"
alert_on_first_match = false

[universe]
mode = "include"
include = ["SHFE.au"]
exclude = []
exchanges = ["SHFE"]
min_volume = 0
min_open_interest = 0
~~~

- runtime.mode 的内部值为 live 或 backtest，GUI 显示“实盘”或“回测”。
- universe.mode 为 all 时可用 exchanges 限制交易所；为 include 时必须填写 include，并可用 exclude 排除。
- min_volume 和 min_open_interest 只影响实盘合约发现；0 表示不启用。
- alert_on_first_match 为 false 时只在“未触发 → 触发”的边沿预警。

### 数据源与凭据

~~~toml
[data_source]
provider = "tqsdk"

[data_source.tqsdk]
username_env = "TQSDK_USERNAME"
password_env = "TQSDK_PASSWORD"
symbol_info_batch_size = 500
quote_subscription_batch_size = 500
~~~

TOML 只保存环境变量名，不接受明文账号或密码。

### 策略

每条策略都有独立 id、共享实现 type、中文 name、enabled 开关和嵌套 parameters。

~~~toml
[[strategies]]
id = "cp_combo_positive"
type = "cp_combo"
name = "CP组合正向预警"
enabled = true

[strategies.parameters]
min_value = 0.01
max_value = inf

[[strategies]]
id = "abs_spread_default"
type = "abs_spread"
name = "价差预警"
enabled = true

[strategies.parameters]
min_value = -inf
max_value = 0.1
~~~

- id 是预警状态与键的稳定身份，必须唯一，格式为小写字母、数字、下划线或连字符。
- type 选择策略实现。当前内置 cp_combo 和 abs_spread。
- name 是 GUI、日志和通知中的中文显示名。
- parameters 由策略自己的 StrategyParameterSpec 声明并严格校验。
- 触发范围为开区间：min_value < value < max_value。
- 同一个 type 可以配置多次，只要 id 不同。

可选筛选脚本使用嵌套 filter：

~~~toml
[strategies.filter]
script = "user_filter_scripts/by_expire_rest_days.py"
entrypoint = "accept"
~~~

入口签名为 accept(option, ctx) -> bool。详细字段见 [策略筛选接口说明](docs/strategy_filter_accept.md)。

### 回测

~~~toml
[backtest]
start_date = 2026-01-02
end_date = 2026-01-05
kline_duration_seconds = 60
data_length = 2
initialization_timeout_seconds = 120
subscription_batch_size = 50
~~~

backtest 模式必须提供 start_date 和 end_date。当前只支持 60 秒 K 线。Runner 会根据策略编译出的 backtest_group 分组，只为当前执行组订阅 required_symbols。

### 通知与日志

~~~toml
[notifications.channels]
popup = false
sound = false
file = true
email = true

[notifications.file]
path = "logs/alerts.jsonl"

[notifications.email]
smtp_host = "smtp.example.com"
smtp_port = 587
aggregation_seconds = 60
username_env = "SMTP_USERNAME"
password_env = "SMTP_PASSWORD"
from_address = "alert@example.com"
to_addresses = ["receiver@example.com"]
use_tls = true
~~~

SMTP 凭据同样只从环境变量读取。预警文件和普通日志按 live、backtest 分目录。

## 策略扩展

新增策略使用项目级 [create-optionsentry-strategy Skill](.agents/skills/create-optionsentry-strategy/SKILL.md)。该流程要求：

- 参数通过 StrategyParameterSpec 声明，GUI 自动生成表单；
- 用户可见标签和选项使用中文，配置键与枚举值使用英文；
- compile() 生成 StrategyCompilation 和精确的 CompiledStrategy 执行单元；
- required_symbols 包含 evaluate() 读取的每个合约；
- 策略声明 DataRequirements，Runner 统一控制 live/backtest；
- 不在 config.py、GUI、Runner 或数据源中增加策略类型分支。

详细架构见 [开发文档](docs/期权预警系统开发文档.md)。

## 常用命令

~~~powershell
uv run pytest -q
uv run optionsentry --config config.toml
uv run optionsentry-gui
powershell -NoProfile -ExecutionPolicy Bypass -File .\package.ps1 -StopRunning
~~~

打包脚本运行测试后构建 dist/optionsentry-gui/optionsentry-gui.exe，并生成 Windows zip 与 SHA256 文件。

## 项目结构

~~~text
.
├── .agents/skills/                    # 项目级 Codex Skills
├── optionsentry/
│   ├── config.py                      # 严格配置模型与校验
│   ├── strategy_base.py               # 参数、编译、数据需求契约
│   ├── strategy_registry.py           # 自动发现与注册
│   ├── strategy_types/                # 内置策略
│   ├── runner.py                      # 运行与回测执行规划
│   ├── data_sources/                  # TqSdk 数据源
│   └── gui/                           # PyQt6 GUI
├── user_filter_scripts/               # 筛选脚本示例
├── docs/
├── tests/
├── config.example.toml
├── package.ps1
└── pyproject.toml
~~~

## 开发与发布

提交前运行完整测试、检查 git diff 和 git diff --check。版本发布由 package.ps1 与 GitHub Actions 完成；标签 vX.Y.Z 必须和 pyproject.toml 的版本一致。

配置、凭据、日志与打包产物均不应提交。本项目不提供交易执行能力，所有预警需人工核验。
