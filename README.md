# LOF 基金套利回测系统

## 概述

回测 LOF 基金的溢价套利：场内价格高于净值时按净值申购，份额到账后在场内卖出。

结论能不能信，取决于两件事：
- **每天到底能不能申购、能申购多少**：高溢价往往正是因为申购被关了。
- **成本和时序**：申购费、份额什么时候能卖、决策时能看到哪天的净值。

所以系统的核心是一条从基金公告构建**每日申购状态**的流水线：公告 PDF → 状态声明 → 每日状态。回测在这份状态上同时跑保守和乐观两个边界。

设计见 [docs/redesign-subscription-state.md](docs/redesign-subscription-state.md)，各阶段的评估和结果见 [docs/eval/README.md](docs/eval/README.md)。

### 当前结论（2022-01-04 ~ 2024-12-31，410 只基金，1 万元起步）

| | 保守边界 | 乐观边界 |
|---|---:|---:|
| 旧数据（限购数据有缺口） | +7,585%（不分边界） | |
| 新的每日状态，阶段 E 的假设（统一 1.5%、T+2、T 日净值） | +3.9% | +165% |
| **加上真实费率、真实可卖日、决策时可见的净值（阶段 F）** | **−46.0%** | **+64.6%** |
| 阶段 F，申购费打 1 折 | +381% | +1,239% |

- 按招募说明书的费率，这个策略没有可靠的超额收益：保守边界亏损，乐观边界剔除红旗日后每笔约为 0。
- 只有拿到大幅申购费折扣时结论才会变。详见 [phase-f-sensitivity.md](docs/eval/phase-f-sensitivity.md)。

## 项目结构

```
lof-eins/
├── src/
│   ├── config.py                    # BacktestConfig
│   ├── data/
│   │   ├── loader.py                # DataLoader：行情、净值、每日状态、交易条款
│   │   ├── downloader.py            # 行情和净值下载（JoinQuant）
│   │   ├── announcement_downloader.py  # 公告 PDF 下载
│   │   ├── fund_terms.py            # 申购费率、确认日、净值滞后（天天基金费率页）
│   │   └── generator/               # 模拟数据生成器（写 daily_status）
│   ├── pipeline/                    # 申购状态流水线
│   │   ├── db.py                    # subscription_state.db 的表结构
│   │   ├── registry.py              # 公告登记（sha256）
│   │   ├── triage.py                # 按标题分诊
│   │   ├── texts.py                 # PDF 正文缓存（pdfplumber，按字号调整容差）
│   │   ├── llm.py                   # OpenAI 兼容的 LLM 客户端（LOF_LLM_* 环境变量）
│   │   ├── extract.py               # 状态声明抽取（prompts/extract_v2.md）
│   │   └── timeline.py              # 状态声明 → daily_status
│   ├── evaluation/                  # 金标、对照、红旗、利润归因
│   ├── strategy/                    # BaseStrategy、SimpleLOFStrategy
│   └── engine/                      # Account（T+n 结算）、BacktestEngine、BacktestResult
├── scripts/                         # 每个流水线步骤一个脚本，见下文
├── app/                             # Streamlit 应用
├── prompts/extract_v2.md            # 抽取 prompt
├── data/gold/                       # 19 只基金的金标时间线（提交在仓库里）
├── data/real_all_lof/, data/mock/   # 数据目录（不提交）
├── configs/backtest.yaml, mock.yaml
├── docs/
├── tests/
└── run_backtest.py                  # 回测入口
```

数据目录的结构：

```
market/<代码>.parquet            date, open, high, low, close, volume
nav/<代码>.parquet               date, nav
announcements/<代码>/*.pdf       公告原文（实盘数据）
config/subscription_state.db     announcements, pdf_texts, extractions, state_assertions,
                                 anomalies, daily_status
config/fund_terms.csv            交易条款（可选）
config/fund_pages/               天天基金费率页的缓存
```

## 安装

```bash
pip install -r requirements.txt
```

复制 `.env.example` 为 `.env` 并填写：JoinQuant 账号用于下载行情，`LOF_LLM_*` 用于公告抽取，可以是任何 OpenAI 兼容的接口。`.env` 不要提交。

## 快速开始：模拟数据

```bash
python scripts/generate_mock.py
```

```bash
python run_backtest.py -c configs/mock_backtest.yaml
```

`configs/backtest.yaml` 默认指向实盘数据目录；用模拟数据时，复制一份并把 `data_dir` 改成 `./data/mock`（上面的 `mock_backtest.yaml` 就是这样一份副本）。

模拟数据在溢价过高时生成限额期，其余日子开放，所有日子的来源都是 `change`，所以两个边界的结果相同。模拟基金没有交易条款文件，使用默认条款。

## 实盘数据流水线

每一步都可以重跑，只做缺的部分。只有第 1 步需要 JoinQuant 账号，只有第 4 步和 `llm-triage` 调用模型。

1. **行情和净值**

   ```bash
   python scripts/download_lof.py --start 2021-01-01
   ```

2. **公告 PDF**

   ```bash
   python scripts/download_announcements.py
   ```

3. **公告登记、分诊、正文缓存**（阶段 B）

   ```bash
   python scripts/build_corpus.py all
   ```

   ```bash
   python scripts/build_corpus.py llm-triage
   ```

4. **抽取状态声明**（阶段 C）。只对还没用当前 prompt 版本和模型抽取过的公告调用模型。

   ```bash
   python scripts/extract_v2.py run
   ```

   ```bash
   python scripts/extract_v2.py report --out docs/eval/extract-v2-report.md
   ```

5. **构建每日状态**（阶段 D）

   ```bash
   python scripts/build_timeline.py build
   ```

   ```bash
   python scripts/build_timeline.py report --out docs/eval/timeline-report.md
   ```

6. **交易条款**（阶段 F）。`fetch` 访问天天基金的公开页面，已缓存的不会重抓。

   ```bash
   python scripts/fund_terms.py fetch
   ```

   ```bash
   python scripts/fund_terms.py build
   ```

7. **回测**

   ```bash
   python run_backtest.py --bounds
   ```

   ```bash
   python run_backtest.py --sensitivity
   ```

   `--bounds` 同时跑保守和乐观两个边界，并按买入日的状态来源和红旗区间做利润归因；`--sensitivity` 依次叠加阶段 F 的各项修正。两者默认从状态库里的第一份公告开始。

8. **评估**：对照金标，以及扫描红旗。

   ```bash
   python scripts/eval_timeline.py --out docs/eval/v2-timeline.md
   ```

   ```bash
   python scripts/red_flags.py --start 2022-01-01 --out docs/eval/v2-red-flags.md
   ```

### 每日状态

`daily_status` 每只基金每个交易日一行：

| 列 | 取值 |
|---|---|
| `status` | `open`、`limited`、`closed`、`unknown` |
| `amount` | 限额（元），金额不明时为空 |
| `source` | `change`、`restatement`、`overlay`（临时安排，如节假日暂停）、`inferred_prior`（首条公告之前，由公告里的"原状态"推断）、`inferred_open`（由节假日公告推断为平时开放）、`default`（没有任何信息，即 unknown） |

冲突（同日矛盾、跨越、重述不一致）一律取更严的状态，并记入 `anomalies` 表。规则见重构方案 §7。

## 回测引擎

### BacktestConfig

| 参数 | 默认值 | 说明 |
|---|---|---|
| `initial_cash` | 300,000 | 初始资金（`configs/backtest.yaml` 里是 1 万） |
| `buy_threshold` | 0.02 | 买入溢价阈值 |
| `liquidity_ratio` | 0.1 | 可成交量占成交量的比例 |
| `commission_rate` | 0.0003 | 卖出佣金 |
| `risk_mode` | `fixed` | `fixed` 受现金约束，`infinite` 不受 |
| `use_ma5_liquidity` | True | 流动性用 min(当日成交量, 5 日均量) |
| `max_premium_rate` | None | 溢价超过它就不买 |
| `risk_free_rate` | 0.02 | 夏普比率用 |
| `unknown_policy` | `closed` | 无法证明可申购的日子（unknown、金额不明的限额、只是推断出来的开放）：`closed` 不买（保守边界），`open` 当作不限购（乐观边界） |
| `n_accounts` | 1 | 限额乘以账户数 |
| `premium_basis` | `published` | 决策溢价：`published` 用决策时可见的最新净值（境内 T-1，境外和 FOF T-2）；`same_day` 用 T 日净值，有前视偏差 |
| `fees` | `fund` | `fund` 用各基金自己的费率表（外扣法），没有的用默认费率；`default` 统一用默认费率 |
| `settlement` | `fund` | `fund` 用各基金自己的可卖日（确认日 + 1，QDII T+3）；`t2` 统一 T+2 |
| `fee_discount` | 1.0 | 乘在比例费率上，每笔固定费用不打折 |

### 每日流程

1. 到期的份额结算入账，已结算份额全部按收盘价卖出。
2. 决策溢价超过阈值、且当天的申购上限大于 0 的基金按溢价从高到低排序，依次买入。每笔取以下几项中的最小值：
   - 申购上限（每日状态按 `unknown_policy` 换算，乘以账户数）；
   - 流动性上限；
   - 可用现金；
   - 单笔 10 万元。
3. 申购按 T 日净值成交，扣除申购费；份额在 T+`sell_days` 个交易日后可卖。

默认费率：50 万以下 1.5%，200 万以下 1.0%，以上每笔 1000 元。

**注意**：买卖规则写在 `BacktestEngine.run` 里，`SimpleLOFStrategy` 和 `BaseStrategy.generate_signals` 目前并没有被引擎调用。只实现一个新的策略类不会改变回测结果，要换策略得同时改引擎。

### 使用示例

```python
from src import BacktestConfig, BacktestEngine, DataLoader, SimpleLOFStrategy

loader = DataLoader("./data/real_all_lof")            # terms="default" 可忽略 fund_terms.csv
config = BacktestConfig(initial_cash=10_000, buy_threshold=0.017, unknown_policy="closed")
result = BacktestEngine(config, SimpleLOFStrategy(), loader).run(["161005", "162411"], start_date="2022-01-04")
print(result.total_return, result.max_drawdown, result.sharpe_ratio)
result.trade_logs        # 每笔成交：价格、金额、申购费、决策溢价、买入日状态和来源、可卖日
result.daily_perf        # 每日总资产、现金、持仓市值
```

`DataLoader.load_bundle(code).df` 的列：`open/high/low/close/volume`、`nav`、`premium_rate`（T 日净值）、`nav_published`、`premium_published`（决策时可见的净值）、`daily_limit`（公告写明的上限：开放为 inf，暂停为 0，限额为金额，未知或金额不明为 NaN）、`sub_status`、`status_source`。

## Streamlit 应用

```bash
streamlit run app/app.py
```

- **数据看板**：行情、净值、溢价率，以及每日申购状态色带、限额走势和按来源统计的天数。
- **回测**：参数表单，包括 `unknown_policy`、决策溢价、费率、可卖日和费率折扣。
- **回测结果**：资产曲线、交易标记、分基金盈亏。

## 测试

```bash
python -m pytest tests/
```

| 文件 | 内容 |
|---|---|
| `test_pipeline.py` | 公告登记、分诊、正文缓存、LLM 客户端 |
| `test_extract_v2.py` | 状态声明抽取、缓存、原文校验 |
| `test_timeline.py` | 状态声明 → 每日状态的解析规则 |
| `test_evaluation.py` | 金标对照、红旗、利润归因 |
| `test_backtest_status.py` | 加载器、两个边界、模拟数据端到端 |
| `test_phase_f.py` | 交易条款、申购费、可卖日、无前视的决策溢价 |
| `test_architecture_fixes.py` | 加载器返回值、T+2 结算、成交记录 |

## 旧链路

旧的"公告 → `subscription_restrictions` → `postprocess.py` → `limit_events`"链路、Kimi 客户端、`fees.csv` 都在阶段 G 删除了，最后一个包含它们的提交是 `17a5bfd`。实盘数据目录里如果还有 `config/fund_status.db` 和 `config/fees.csv`，现在已经不再读取，可以自行删除。`docs/eval/legacy-*.md` 是旧数据的评估记录。

## License

MIT
