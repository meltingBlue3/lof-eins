# 需求规格说明书 (Software Requirements Specification)

## 1. 引言

### 1.1 目的

本文档为 **LOF 基金套利回测系统（lof-eins）** 提供完整的需求规格说明。目的在于：

- 明确系统的功能需求与非功能需求
- 为开发、测试和验收提供统一参考
- 作为需求追溯与变更管理的基准文档

### 1.2 范围

本系统是一个配置驱动的 LOF（Listed Open-Ended Fund，上市型开放式基金）套利回测平台，核心范围包括：

- 从 JoinQuant 下载 LOF 市场行情及净值数据
- 从 Eastmoney 下载基金公告 PDF
- 通过 PDF 提取 + LLM 解析自动识别限购事件
- 支持 T+2 结算、阶梯费率、流动性约束的回测引擎
- 可扩展的策略框架（Strategy Pattern）
- Mock 数据生成器，支持离线测试

**不在范围内的功能**：实盘交易、实时数据推送、多因子分析。

### 1.3 术语与缩略语

| 术语 | 说明 |
|------|------|
| LOF | Listed Open-Ended Fund，上市型开放式基金 |
| NAV | Net Asset Value，基金净值 |
| 溢价率 | Premium Rate，`(close - nav) / nav`，收盘价相对净值的偏离程度 |
| T+2 | 交易日 +2 结算，买入后第 2 个交易日份额到账 |
| 限购 | 基金暂停或限制大额申购的行为 |
| LLM | Large Language Model，大型语言模型 |
| Ollama | 本地 LLM 推理服务 |
| OHLCV | Open/High/Low/Close/Volume，日 K 线数据 |
| GBM | Geometric Brownian Motion，几何布朗运动（Mock 数据生成算法） |
| Parquet | Apache Parquet，列式存储文件格式 |

### 1.4 参考资料

- `TECHNICAL_PROPOSAL.md` — 限购增强功能技术方案
- `README.md` — 项目快速入门指南
- IEEE 830-1998 — 软件需求规格说明书推荐实践
- 中国证监会 LOF 基金相关法规

---

## 2. 总体描述

### 2.1 产品概述

lof-eins 是一套面向量化分析师的 LOF 基金套利回测系统。系统通过整合市场数据、净值数据和基金公告信息，模拟历史交易并评估策略绩效。其核心价值在于：**将基金公告中的限购信息自动化提取并集成到回测数据中**，从而显著提升回测结果的准确性。

### 2.2 产品功能概要

| 功能模块 | 说明 |
|---------|------|
| 数据下载 | 从 JoinQuant 下载 LOF 行情/净值，从 Eastmoney 下载公告 PDF |
| 数据加载 | 多源数据对齐、限购事件按日重采样、溢价率预计算 |
| PDF 处理 | 提取 PDF 文本（pdfplumber）→ LLM 解析限购信息（Ollama/OpenAI） |
| 公告流水线 | 端到端编排：提取 → 解析 → 存储 → （Phase 3）时间线集成 |
| 回测引擎 | T+2 结算、阶梯费率、流动性约束、多 ticker 统一资金池 |
| 策略框架 | BaseStrategy 抽象基类 + Signal 数据结构，支持自定义策略 |
| Mock 数据 | 基于 GBM 的 NAV 模拟，含溢价率波动和限购事件触发 |
| 配置管理 | YAML 驱动，支持 from_yaml/to_yaml API |

### 2.3 用户特征

| 用户类型 | 特征 | 使用场景 |
|---------|------|---------|
| 量化分析师 | 熟悉 Python，理解 LOF 套利机制 | 策略开发、回测验证 |
| 基金研究员 | 需要公告数据，关注限购信息 | 限购事件分析、数据审计 |
| 开发者 | 需要扩展系统功能 | 新策略开发、模块扩展 |

### 2.4 运行环境

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows / macOS / Linux |
| Python | >= 3.10 |
| LLM 服务 | Ollama（本地）或 OpenAI 兼容 API（云端） |
| 外部 API | JoinQuant（行情数据）、Eastmoney（公告 PDF） |
| 存储 | 本地文件系统（Parquet + SQLite + PDF） |

### 2.5 约束条件

1. **JoinQuant API 限制**：免费账户有每日查询次数限制
2. **Ollama 资源要求**：运行 qwen3:8b 模型需要约 6GB 内存
3. **Eastmoney API 稳定性**：公告下载接口可能变更，需适配
4. **T+2 结算规则**：严格遵循中国 A 股交易日历
5. **数据本地化**：所有数据存储在本地文件系统，不支持远程数据库

### 2.6 假设与依赖

1. JoinQuant 数据源可用且数据准确
2. Eastmoney 公告 API 接口格式稳定
3. LLM 模型能准确提取中文限购信息（置信度 > 0.8）
4. 交易日历覆盖回测所需的全部时间段
5. PDF 公告格式为标准文本 PDF（非扫描件）

---

## 3. 功能需求

### 3.1 数据下载模块

#### REQ-001 市场数据下载

- **描述**：从 JoinQuant API 批量下载 LOF 基金的 OHLCV 日 K 线数据
- **输入**：
  - JoinQuant 账户凭据（通过 `.env` 配置）
  - 日期范围（`--start`、`--end` CLI 参数）
- **处理逻辑**：
  1. 认证 JoinQuant API
  2. 获取所有 LOF 基金代码
  3. 分批下载（默认 50 只/批），批次间延迟 0.5 秒
  4. 保存为 Parquet 文件（按 ticker 分文件）
  5. 自动生成费率配置 CSV 和空的 fund_status.db
- **输出**：`data/<data_dir>/market/<ticker>.parquet`，`data/<data_dir>/nav/<ticker>.parquet`
- **验收标准**：
  - 所有活跃 LOF 基金的行情和净值数据成功下载
  - Parquet 文件包含 `date, ticker, open, high, low, close, volume` 列
  - 费率 CSV 和 SQLite 数据库自动生成

#### REQ-002 净值数据下载

- **描述**：从 JoinQuant API 下载基金净值（NAV）数据
- **输入**：基金代码列表、日期范围
- **处理逻辑**：与市场数据同批次下载，存储为独立 Parquet 文件
- **输出**：`data/<data_dir>/nav/<ticker>.parquet`
- **验收标准**：NAV 数据与市场数据日期对齐

#### REQ-003 公告 PDF 下载

- **描述**：从 Eastmoney API 下载基金公告 PDF 文件
- **输入**：
  - 基金代码（`--ticker` 或自动发现）
  - 日期范围（基于市场数据自动推断）
  - 公告类型（默认全部类型）
- **处理逻辑**：
  1. 调用 Eastmoney 公告 API 获取公告列表（分页）
  2. 逐个下载 PDF，失败时重试（最多 3 次）
  3. 按 ticker 分目录存储
- **输出**：`data/<data_dir>/announcements/<ticker>/<filename>.pdf`
- **验收标准**：
  - PDF 下载成功率 > 95%
  - 支持断点续传（已存在文件跳过）
  - 请求间有速率限制（默认 1 秒延迟）

### 3.2 数据加载模块

#### REQ-004 多源数据加载与对齐

- **描述**：从本地文件系统加载市场数据、净值数据和限购事件，按日期索引对齐
- **输入**：
  - 数据目录路径
  - Ticker 代码
  - 可选日期范围过滤
- **处理逻辑**：
  1. 读取 Parquet 文件（市场 + NAV）
  2. 从 SQLite 查询限购事件，重采样为每日序列
  3. 按日期索引合并，`ffill()` 填充缺失值
  4. 计算溢价率 `premium_rate = (close - nav) / nav`
  5. 加载并缓存费率配置
- **输出**：DataFrame，包含 `open, high, low, close, volume, nav, premium_rate, daily_limit`
- **验收标准**：
  - NULL end_date 的限购事件正确应用到所有未来日期
  - 溢价率正确计算
  - 费率配置附加到 `DataFrame.attrs`

#### REQ-005 Ticker 自动发现

- **描述**：扫描数据目录，自动发现所有可用 ticker
- **输入**：数据目录路径
- **处理逻辑**：扫描 `market/` 子目录中的 Parquet 文件名提取 ticker 列表
- **输出**：ticker 字符串列表
- **验收标准**：返回所有有效 ticker，忽略无效文件

### 3.3 PDF 处理模块

#### REQ-006 PDF 文本提取

- **描述**：从基金公告 PDF 中提取纯文本内容
- **输入**：PDF 文件路径
- **处理逻辑**：
  1. 使用 pdfplumber 逐页提取文本
  2. 多页 PDF 使用 `--- Page N ---` 标记分页
  3. 清洗文本（规范化空白字符）
- **输出**：`{"success": bool, "text": str, "pages": int, "error": str|None}`
- **验收标准**：
  - 中文 PDF 正确提取
  - 多页 PDF 保留分页上下文
  - 损坏/加密 PDF 返回错误信息而非崩溃

#### REQ-007 LLM 限购信息解析

- **描述**：使用 LLM 从公告文本中提取限购事件的结构化信息
- **输入**：
  - 公告文本（来自 REQ-006）
  - 基金代码
- **处理逻辑**：
  1. 构建 system prompt（含限购类型定义和 few-shot 示例）
  2. 调用 LLM（优先云端 API，降级到本地 Ollama）
  3. 从 LLM 响应中提取 JSON（处理 thinking tokens 和 markdown 代码块）
  4. 验证并规范化输出（日期格式、字段完整性）
- **输出**：限购记录列表，每条包含：
  - `ticker`：基金代码
  - `limit_amount`：限购金额（元）
  - `start_date`：限购开始日期（可为 null）
  - `end_date`：限购结束日期（可为 null）
  - `announcement_type`：公告类型（complete/open-start/end-only/modify）
  - `is_purchase_limit_announcement`：是否为限购公告
  - `confidence`：置信度分数（0-1）
- **验收标准**：
  - 支持四种公告类型（complete、open-start、end-only、modify）
  - 非限购公告正确标记为 `is_purchase_limit_announcement=false`
  - 日期格式统一为 YYYY-MM-DD
  - 解析失败返回错误记录而非抛异常

### 3.4 公告处理流水线

#### REQ-008 单 PDF 端到端处理

- **描述**：编排单个 PDF 从提取到存储的完整流程
- **输入**：ticker、PDF 文件路径
- **处理逻辑**：
  1. 调用 PDF 提取（REQ-006）
  2. 调用 LLM 解析（REQ-007）
  3. 将解析结果存入 `announcement_parses` 表
- **输出**：`{"success": bool, "stored": bool, "parse_result": dict, "error": str|None}`
- **验收标准**：
  - 成功处理的结果持久化到数据库
  - 失败不影响后续处理
  - 支持 INSERT OR REPLACE 重新处理

#### REQ-009 批量 Ticker 处理

- **描述**：批量处理某 ticker 下所有 PDF 公告
- **输入**：ticker、可选 `--all` 处理所有 ticker
- **处理逻辑**：
  1. 扫描 announcements 目录下指定 ticker 的所有 PDF
  2. 逐个调用 REQ-008
  3. 汇总统计（total/extracted/parsed/stored/failed）
- **输出**：批量处理统计字典
- **验收标准**：
  - 单个 PDF 失败不中断整批处理
  - 提供详细进度和错误汇总
  - CLI 支持 `--verbose` 调试模式

### 3.5 时间线集成模块（Phase 3 — 待实现）

#### REQ-010 限购时间线整合

- **描述**：将 `announcement_parses` 中的原始解析结果整合为 `limit_events` 中的完整时间线
- **输入**：某 ticker 的所有解析记录
- **处理逻辑**：
  1. 按公告日期排序
  2. 按类型处理：complete 直接创建、open-start 创建开放事件、end-only 关闭/延长
  3. 合并重叠区间（O(n log n)）
  4. 写入 `limit_events` 表，记录审计日志
- **输出**：合并后的限购事件列表
- **验收标准**：
  - 重叠区间正确合并
  - open-ended 事件（NULL end_date）正确处理
  - 审计日志完整记录所有变更

### 3.6 回测引擎模块

#### REQ-011 T+2 结算账户管理

- **描述**：模拟中国 A 股 T+2 结算机制
- **输入**：买卖交易指令
- **处理逻辑**：
  - **买入**：资金立即扣除，份额进入 T+2 待结算队列
  - **卖出**：资金 T+0 到账（立即可用），仅能卖出已结算份额
  - **日更新**：每个交易日推进结算队列，到期份额转入持仓
- **输出**：账户状态（现金、持仓、待结算份额、总市值）
- **验收标准**：
  - 结算日基于实际交易日历（非自然日）
  - 余额不足时抛出 `ValueError`
  - 浮点运算容差 `1e-9`

#### REQ-012 多 Ticker 回测执行

- **描述**：在统一资金池下执行多 ticker 并行回测
- **输入**：
  - BacktestConfig 配置
  - 策略实例
  - DataLoader 实例
  - Ticker 列表
- **处理逻辑**：
  1. 加载并对齐所有 ticker 数据
  2. 对每个交易日：
     a. 推进结算队列
     b. 执行卖出阶段（卖出所有可用持仓）
     c. 执行买入阶段（按溢价率排序，贪心分配资金）
     d. 记录每日绩效
  3. 计算绩效指标
- **输出**：BacktestResult（总收益率、年化收益率、最大回撤、夏普比率、交易日志）
- **验收标准**：
  - 买入约束正确应用：`min(限购, 流动性, 资金, 信号金额)`
  - 阶梯费率正确计算
  - 绩效指标计算准确

#### REQ-013 阶梯费率计算

- **描述**：按申购金额区间收取差异化费率
- **输入**：申购金额
- **处理逻辑**：

  | 申购金额 | 费率 |
  |---------|------|
  | < 50 万 | 1.5% |
  | 50 万 ~ 200 万 | 1.0% |
  | ≥ 200 万 | 固定 1000 元/笔 |
- **输出**：费用金额
- **验收标准**：边界值（50 万、200 万）准确切换费率档位

### 3.7 策略框架模块

#### REQ-014 策略抽象接口

- **描述**：提供可扩展的策略基类，支持自定义交易策略
- **输入**：当前行数据 (pd.Series)、当前持仓 (Dict)、配置 (BacktestConfig)
- **处理逻辑**：子类实现 `generate_signals()` 方法，返回 Signal 列表
- **输出**：`List[Signal]`，每个 Signal 包含 `action`（buy/sell）、`ticker`、`amount`
- **验收标准**：
  - BaseStrategy 为抽象基类，不可直接实例化
  - Signal 数据结构完整且类型安全

#### REQ-015 SimpleLOFStrategy 默认策略

- **描述**：简单 LOF 套利策略实现
- **输入**：行数据、持仓、配置
- **处理逻辑**：
  1. 卖出：如有持仓则全部卖出（快速止盈）
  2. 买入：如 `premium_rate > buy_threshold` 且 `daily_limit > 0` 则买入
- **输出**：买/卖信号列表
- **验收标准**：策略逻辑与文档描述一致

### 3.8 Mock 数据生成模块

#### REQ-016 Mock 数据生成

- **描述**：生成合成的 LOF 数据用于测试，与真实数据格式完全兼容
- **输入**：MockConfig（ticker 列表、日期范围、波动率参数等）
- **处理逻辑**：
  1. NAV 生成：GBM（几何布朗运动），含可配置漂移和波动率
  2. 价格生成：基于 NAV + 溢价率波动，含随机尖峰事件
  3. 限购生成：溢价率连续 N 天超阈值时触发限购
  4. 费率生成：标准阶梯费率配置
- **输出**：与真实数据相同的目录结构（Parquet + CSV + SQLite）
- **验收标准**：
  - 生成数据可直接被 DataLoader 加载
  - 溢价率分布合理
  - 限购事件触发逻辑可配置

### 3.9 配置管理模块

#### REQ-017 YAML 配置管理

- **描述**：通过 YAML 文件管理回测和数据生成参数
- **输入**：YAML 配置文件路径
- **处理逻辑**：
  1. 解析 YAML 文件为 Python 数据类
  2. 参数验证（`__post_init__`）
  3. 支持序列化回 YAML
- **输出**：`BacktestConfig` 或 `MockConfig` 实例
- **验收标准**：
  - 无效参数触发 `ValueError` 并提供明确错误信息
  - 支持 `from_yaml()` / `to_yaml()` 双向转换

---

## 4. 非功能需求

### 4.1 性能需求

| 指标 | 要求 |
|------|------|
| 单 ticker 数据加载 | < 1 秒（包含 Parquet 读取 + SQLite 查询） |
| 限购事件日查询 | < 100 毫秒 |
| 单日回测处理 | < 10 毫秒/ticker |
| 单 PDF LLM 解析 | < 30 秒（本地 Ollama） |
| 批量数据下载 | 50 只基金/批，含速率限制 |

### 4.2 安全性需求

| 项目 | 要求 |
|------|------|
| API 凭据 | 通过 `.env` 文件管理，不得提交到版本控制 |
| LLM API Key | 通过环境变量注入，支持 `.env` 加载 |
| 数据存储 | 本地文件系统，无网络暴露 |
| 输入校验 | 所有外部输入（YAML、CLI 参数、API 响应）需校验 |

### 4.3 可用性需求

| 项目 | 要求 |
|------|------|
| CLI 接口 | 所有脚本支持 `--help` 和明确的参数说明 |
| 错误提示 | 错误信息包含上下文（ticker、文件名、操作类型） |
| 回测输出 | 格式化的绩效摘要，包含关键指标 |
| 数据验证 | 提供 Plotly 可视化工具验证数据质量 |

### 4.4 可维护性需求

| 项目 | 要求 |
|------|------|
| 代码规范 | 全面使用 Python type hints |
| 文档 | 所有公开方法有 docstring |
| 测试覆盖 | 核心模块 103+ 测试用例 |
| 配置分离 | 策略参数通过 YAML 配置，不硬编码 |
| 模块化 | 数据层 / 策略层 / 引擎层清晰分离 |

### 4.5 兼容性需求

| 项目 | 要求 |
|------|------|
| Python 版本 | >= 3.10 |
| 操作系统 | Windows / macOS / Linux |
| LLM 双模式 | 云端 API（OpenAI 兼容）+ 本地 Ollama，自动降级 |
| 数据格式 | Parquet（时序数据）、SQLite（事件数据）、CSV（配置） |

---

## 5. 接口需求

### 5.1 用户接口

系统通过 CLI（命令行接口）和 Python API 提供用户交互。

#### 5.1.1 CLI 脚本

| 脚本 | 命令 | 主要参数 |
|------|------|---------|
| `scripts/download_lof.py` | 下载市场/NAV 数据 | `--start`, `--end` |
| `scripts/download_announcements.py` | 下载公告 PDF | `--ticker`, `--start`, `--end`, `--data-dir`, `--type`, `--delay` |
| `scripts/parse_announcements.py` | 解析公告 | `--ticker`, `--all`, `--data-dir`, `--db-path`, `--verbose` |
| `scripts/generate_mock.py` | 生成 Mock 数据 | `--config` |
| `scripts/inspect_data.py` | 可视化数据 | （无参数，硬编码 ticker） |
| `run_backtest.py` | 运行回测 | `--config` |

#### 5.1.2 Python API

| 模块 | 主要 API | 用途 |
|------|---------|------|
| `BacktestConfig` | `from_yaml()`, `to_yaml()` | 配置管理 |
| `DataLoader` | `load_bundle()`, `list_available_tickers()` | 数据加载 |
| `BacktestEngine` | `run()` | 回测执行 |
| `AnnouncementProcessor` | `process_pdf()`, `process_ticker()` | 公告处理 |
| `LLMClient` | `parse_announcement()` | LLM 解析 |

### 5.2 外部系统接口

| 外部系统 | 接口类型 | 用途 | 认证方式 |
|---------|---------|------|---------|
| JoinQuant | Python SDK (`jqdatasdk`) | 行情/NAV 数据下载 | 用户名/密码 |
| Eastmoney | REST API (HTTP GET) | 公告列表查询 + PDF 下载 | 无需认证 |
| Ollama | REST API (`localhost:11434`) | 本地 LLM 推理 | 无需认证 |
| OpenAI-compatible | REST API | 云端 LLM 推理 | API Key (Bearer Token) |

### 5.3 数据接口

| 数据类型 | 格式 | 方向 | 说明 |
|---------|------|------|------|
| 市场行情 | Parquet | 读/写 | OHLCV 日 K 线 |
| 基金净值 | Parquet | 读/写 | 日净值数据 |
| 费率配置 | CSV | 读/写 | 阶梯费率参数 |
| 限购事件 | SQLite | 读/写 | fund_status.db |
| 公告 PDF | Binary (PDF) | 读/写 | 原始公告文件 |
| 回测配置 | YAML | 读 | 回测参数 |
| Mock 配置 | YAML | 读 | 数据生成参数 |
| 环境变量 | .env | 读 | API 凭据和 LLM 配置 |

---

## 6. 数据需求

### 6.1 数据模型

```
┌─────────────────────┐     ┌──────────────────────┐
│  market/<ticker>.pq  │     │   nav/<ticker>.pq    │
│  (OHLCV 日 K 线)     │     │   (日净值)            │
└────────┬────────────┘     └────────┬─────────────┘
         │                           │
         └──────────┬────────────────┘
                    │ DataLoader.load_bundle()
                    ▼
         ┌──────────────────────┐
         │  Aligned DataFrame   │
         │  (market + nav +     │
         │   premium_rate +     │
         │   daily_limit)       │
         └──────────────────────┘
                    ▲
                    │ _resample_limits_to_daily()
         ┌──────────────────────┐
         │  fund_status.db      │
         │  ├─ limit_events     │
         │  ├─ announcement_    │
         │  │  parses            │
         │  └─ limit_event_log  │
         └──────────────────────┘
                    ▲
                    │ AnnouncementProcessor
         ┌──────────────────────┐
         │  announcements/      │
         │  └─ <ticker>/        │
         │     └─ *.pdf         │
         └──────────────────────┘
```

### 6.2 数据字典

#### 6.2.1 market/<ticker>.parquet

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| date | DATE | 交易日期 | NOT NULL, 索引列 |
| ticker | TEXT | 基金代码 | NOT NULL |
| open | FLOAT | 开盘价 | NOT NULL, > 0 |
| high | FLOAT | 最高价 | NOT NULL, >= open |
| low | FLOAT | 最低价 | NOT NULL, <= open |
| close | FLOAT | 收盘价 | NOT NULL, > 0 |
| volume | INT | 成交量 | NOT NULL, >= 0 |

#### 6.2.2 nav/<ticker>.parquet

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| date | DATE | 交易日期 | NOT NULL, 索引列 |
| ticker | TEXT | 基金代码 | NOT NULL |
| nav | FLOAT | 单位净值 | NOT NULL, > 0 |

#### 6.2.3 limit_events 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | INTEGER | 自增主键 | PRIMARY KEY AUTOINCREMENT |
| ticker | TEXT | 基金代码 | NOT NULL |
| start_date | DATE | 限购开始日期 | NOT NULL |
| end_date | DATE | 限购结束日期 | NULLABLE（NULL = 开放式限购） |
| max_amount | REAL | 最大申购金额（元） | NOT NULL |
| reason | TEXT | 限购原因 | NULLABLE |
| is_open_ended | INT | 是否为开放式限购 | GENERATED：`end_date IS NULL → 1` |
| source_announcement_ids | TEXT | 关联公告 ID | NULLABLE, JSON 数组 |

**索引**：
- `idx_limit_events_ticker (ticker)`
- `idx_limit_events_dates (ticker, start_date, end_date)`

#### 6.2.4 announcement_parses 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | INTEGER | 自增主键 | PRIMARY KEY AUTOINCREMENT |
| ticker | TEXT | 基金代码 | NOT NULL |
| pdf_filename | TEXT | PDF 文件名 | NOT NULL |
| extracted_text | TEXT | 提取的原始文本 | NULLABLE |
| parse_result | TEXT | LLM 解析结果 | NULLABLE, JSON 格式 |
| confidence | REAL | 置信度 | NULLABLE, 0-1 |
| parsed_at | TIMESTAMP | 解析时间 | DEFAULT CURRENT_TIMESTAMP |

**约束**：`UNIQUE(ticker, pdf_filename)`

#### 6.2.5 limit_event_log 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | INTEGER | 自增主键 | PRIMARY KEY AUTOINCREMENT |
| ticker | TEXT | 基金代码 | NOT NULL |
| operation | TEXT | 操作类型 | NOT NULL (INSERT/UPDATE/DELETE) |
| old_start_date | DATE | 变更前开始日期 | NULLABLE |
| old_end_date | DATE | 变更前结束日期 | NULLABLE |
| new_start_date | DATE | 变更后开始日期 | NULLABLE |
| new_end_date | DATE | 变更后结束日期 | NULLABLE |
| source | TEXT | 来源标识 | NULLABLE |
| reason | TEXT | 变更原因 | NULLABLE |
| logged_at | TIMESTAMP | 记录时间 | DEFAULT CURRENT_TIMESTAMP |

#### 6.2.6 config/fees.csv

| 字段 | 类型 | 说明 |
|------|------|------|
| fee_limit_1 | FLOAT | 一档金额上限（默认 500000） |
| fee_rate_tier_1 | FLOAT | 一档费率（默认 0.015） |
| fee_limit_2 | FLOAT | 二档金额上限（默认 2000000） |
| fee_rate_tier_2 | FLOAT | 二档费率（默认 0.01） |
| fee_fixed | FLOAT | 三档固定费用（默认 1000） |
| redeem_fee_7d | FLOAT | 7 日内赎回费率（默认 0.015） |

---

## 7. 附录

### 7.1 变更记录

| 日期 | 版本 | 变更说明 |
|------|------|---------|
| 2026-02-16 | 1.0 | 初始版本，基于当前代码库（Phase 1 ✅、Phase 2 ✅）创建完整需求规格 |
