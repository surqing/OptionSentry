# OptionSentry

OptionSentry 是一个基于 TqSdk 的期货期权行情监控与预警工具。项目提供命令行和 PyQt6 图形界面，用于发现期货期权合约、编译监控条件、订阅行情、计算策略指标，并在指标进入预设区间时输出预警。

当前项目只做行情分析和告警，不包含自动下单、撤单或调仓逻辑。

## 主要功能

- 支持实盘行情监控和历史回测两种运行模式。
- 支持通过图形界面登录、编辑配置、启动/停止监控、查看活跃预警、查看预警记录和运行日志。
- 支持命令行运行，便于服务器、脚本或计划任务集成。
- 内置 `CP组合预警` 和 `价差预警` 两类策略。
- 支持为单个策略配置用户自定义期权筛选脚本。
- 支持文件告警、邮件告警，以及 GUI 内的弹窗和声音提示。
- 支持 Windows PyInstaller 打包，并输出 zip 包和 SHA256 校验文件。

## 环境要求

- Python 3.11 或更高版本。
- `uv` 包管理工具。
- 可用的 TqSdk 账号。
- Windows 打包需要 PowerShell；GUI 运行需要当前系统支持 PyQt6 桌面环境。

项目依赖在 [pyproject.toml](pyproject.toml) 中声明，主要包括：

- `tqsdk`
- `pyqt6`
- `tomlkit`
- `pytest`
- `pyinstaller`

## 快速开始

1. 安装依赖：

   ```powershell
   uv sync --dev
   ```

2. 准备配置文件：

   ```powershell
   Copy-Item config.example.toml config.toml
   ```

3. 设置 TqSdk 登录凭据：

   ```powershell
   $env:TQSDK_USERNAME = "your-tqsdk-username"
   $env:TQSDK_PASSWORD = "your-tqsdk-password"
   ```

4. 启动 GUI：

   ```powershell
   uv run optionsentry-gui
   ```

5. 或者使用命令行运行：

   ```powershell
   uv run optionsentry --config config.toml
   ```

GUI 登录页也可以输入 TqSdk 账号密码。勾选“记住我”后，账号密码会写入当前配置文件；请不要把包含真实凭据的 `config.toml` 提交到版本库。

## 配置说明

配置文件采用 TOML 格式，推荐从 [config.example.toml](config.example.toml) 复制后修改。

### 运行模式

```toml
[runtime]
mode = "live"
price_basis = "last"
alert_on_first_match = false
```

- `mode`：支持 `live` 和 `backtest`。
- `price_basis`：当前版本仅支持 `last`。
- `alert_on_first_match`：为 `false` 时，首次发现条件已经处于触发状态不会立即告警；后续从未触发变为触发时才告警。为 `true` 时，首次匹配也会告警。

### 合约范围

```toml
[universe]
mode = "指定模式"
only_do = ["AU"]
not_do = []
min_volume = 0
min_open_interest = 0
```

- `mode = "all"`：扫描指定交易所或全部交易所的活跃期权。
- `mode = "指定模式"`：先用 `only_do` 纳入匹配的品种或合约，再用 `not_do` 排除。
- `exchange_ids`：在 `all` 模式下可限制交易所，例如 `["SHFE", "DCE"]`。
- `min_volume`、`min_open_interest`：实盘模式下的流动性过滤条件；`0` 表示不启用。

### TqSdk 数据源

```toml
[datasource.tqsdk]
username_env = "TQSDK_USERNAME"
password_env = "TQSDK_PASSWORD"
symbol_info_batch_size = 1000
quote_subscription_batch_size = 1000
```

运行时默认从 `username_env` 和 `password_env` 指定的环境变量读取账号密码。GUI 中输入或记住的账号密码会在启动监控前注入这些环境变量。

### 策略

策略以 `[[strategies]]` 数组配置：

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

字段说明：

- `type`：支持 `cp_combo` 和 `abs_spread`。
- `min_value`、`max_value`：触发区间，实际判断为 `min_value < value < max_value`。
- `name`：展示在日志、GUI 和邮件中的策略名称。
- `selected`：是否启用该策略。
- `filter_script`：可选的用户筛选脚本路径。相对路径以配置文件所在目录为基准。
- `filter_function`：筛选函数名，默认 `accept`。
- `filter_scope`：当前仅支持 `options`。

内置策略含义：

- `cp_combo`：在同一标的期货、同一行权年月、同一执行价下，使用认购期权、认沽期权和标的期货计算 CP 组合偏离率。
- `abs_spread`：在同一标的期货、同一行权年月、同一期权方向下，对不同行权价期权两两组合计算价差比例。

### 策略筛选脚本

策略筛选脚本需要提供 `accept(option, ctx) -> bool`：

```python
def accept(option, ctx) -> bool:
    if option.expire_rest_days is None:
        return False
    return 10 <= option.expire_rest_days <= 60
```

项目内置了两个示例：

- [user_filter_scripts/by_expire_rest_days.py](user_filter_scripts/by_expire_rest_days.py)
- [user_filter_scripts/by_expiry.py](user_filter_scripts/by_expiry.py)

更完整的字段说明见 [docs/strategy_filter_accept.md](docs/strategy_filter_accept.md)。

### 回测

```toml
[backtest]
start_dt = "2026-01-02"
end_dt = "2026-01-05"
duration_seconds = 60
data_length = 2
initial_price_timeout_seconds = 120
subscription_batch_size = 50
```

回测模式需要设置 `runtime.mode = "backtest"`，并提供 `start_dt` 与 `end_dt`。当前回测只支持 `duration_seconds = 60` 的 K 线。

### 告警与日志

```toml
[notifier.channels]
popup = false
sound = false
file = true
email = true
```

- `file`：写入 JSONL 预警日志。路径会按运行模式分目录，例如 `logs/live/alerts.jsonl`。
- `email`：通过 SMTP 发送邮件，支持按 `alert_interval_seconds` 聚合。
- `popup`、`sound`：GUI 本地弹窗和声音提示。

普通运行日志由 `[logging]` 配置，默认写入 `logs/<mode>/optionsentry.log`，并启用滚动日志。

## 常用命令

运行测试：

```powershell
uv run pytest
```

运行命令行监控：

```powershell
uv run optionsentry --config config.toml
```

运行 GUI：

```powershell
uv run optionsentry-gui
```

打包 Windows GUI：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\package.ps1 -StopRunning
```

打包脚本默认会先运行测试，再构建 `dist/optionsentry-gui/optionsentry-gui.exe`，并生成 `dist/OptionSentry-v<version>-windows-x64.zip` 和对应的 SHA256 文件。

如果只是本地调试打包流程，可以使用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\package.ps1 -SkipTests -NoClean
```

## 项目结构

```text
.
├── optionsentry/                 # 应用主包
│   ├── cli.py                    # 命令行入口
│   ├── config.py                 # TOML 配置解析与校验
│   ├── runner.py                 # 监控运行循环
│   ├── strategies.py             # 策略兼容导出与构造入口
│   ├── strategy_base.py          # 策略基类与展示元数据
│   ├── strategy_registry.py      # 内置策略自动发现与注册表
│   ├── strategy_types/           # 自注册的内置策略实现
│   ├── notifiers.py              # 文件和邮件告警
│   ├── data_sources/             # TqSdk 数据源
│   └── gui/                      # PyQt6 图形界面
├── user_filter_scripts/          # 用户筛选脚本示例
├── docs/                         # 补充文档
├── tests/                        # 自动化测试
├── config.example.toml           # 配置模板
├── package.ps1                   # Windows 打包脚本
├── optionsentry-gui.spec         # PyInstaller 配置
└── pyproject.toml                # 项目元数据与依赖
```

## 开发流程

1. 修改代码或文档前先确认当前工作区状态：

   ```powershell
   git status --short
   ```

2. 安装并同步依赖：

   ```powershell
   uv sync --dev
   ```

3. 提交前运行测试：

   ```powershell
   uv run pytest
   ```

4. 检查变更：

   ```powershell
   git diff
   ```

5. 提交时使用清晰、简洁的提交信息。

## 发布

GitHub Actions 中的 [release.yml](.github/workflows/release.yml) 会在推送 `v*.*.*` 标签或手动触发时构建 Windows 包。发布标签需要和 [pyproject.toml](pyproject.toml) 中的 `version` 保持一致，例如 `version = "0.1.3"` 对应标签 `v0.1.3`。

## 注意事项

- `config.toml`、`.env`、日志和打包产物属于本地文件，默认不应提交。
- 邮件告警需要配置 SMTP 服务、发件人、收件人和密码环境变量。
- 实盘和回测都依赖 TqSdk 账号权限及行情可用性。
- GUI 记住账号密码会把凭据写入配置文件，只建议在可信本机使用。
- 项目当前不提供交易执行能力，预警结果需要人工核验后再决策。
