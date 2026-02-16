# 详细设计说明书 (Detailed Design Document)

## 1. 引言

### 1.1 目的

本文档为 **LOF 基金套利回测系统（lof-eins）** 提供详细设计说明，覆盖系统架构、模块设计、数据设计和接口定义，为开发和维护提供技术参考。

### 1.2 范围

对应《需求规格说明书》（`docs/requirements.md`）中定义的所有功能模块：

- 数据下载模块（REQ-001 ~ REQ-003）
- 数据加载模块（REQ-004 ~ REQ-005）
- PDF 处理模块（REQ-006 ~ REQ-007）
- 公告处理流水线（REQ-008 ~ REQ-009）
- 时间线集成模块（REQ-010，Phase 3 待实现）
- 回测引擎模块（REQ-011 ~ REQ-013）
- 策略框架模块（REQ-014 ~ REQ-015）
- Mock 数据生成模块（REQ-016）
- 配置管理模块（REQ-017）

### 1.3 术语与缩略语

| 术语 | 说明 |
|------|------|
| GBM | Geometric Brownian Motion，几何布朗运动 |
| T+2 | 买入后第 2 个交易日份额到账的结算机制 |
| Few-shot | LLM 提示工程技术，提供少量示例引导模型输出 |
| OHLCV | Open/High/Low/Close/Volume 日 K 线数据 |
| ffill | Forward Fill，前向填充缺失值策略 |

### 1.4 参考资料

- `docs/requirements.md` — 需求规格说明书
- `TECHNICAL_PROPOSAL.md` — 限购增强功能技术方案
- `README.md` — 项目快速入门

---

## 2. 系统架构

### 2.1 架构概览

系统采用**分层架构**，由下到上分为四层：

```
┌─────────────────────────────────────────────────────────┐
│                     表现层 (Presentation)                 │
│  CLI Scripts (download, parse, backtest, inspect)        │
│  run_backtest.py                                         │
├─────────────────────────────────────────────────────────┤
│                     业务逻辑层 (Business Logic)           │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ BacktestEng  │  │ Strategy     │  │ Announcement  │  │
│  │ Account      │  │ Framework    │  │ Processor     │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
├─────────────────────────────────────────────────────────┤
│                     数据访问层 (Data Access)               │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ DataLoader   │  │ Downloader   │  │ LLMClient     │  │
│  │              │  │ AnnounceDL   │  │ PDFExtractor  │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
├─────────────────────────────────────────────────────────┤
│                     存储层 (Storage)                      │
│  Parquet Files │ SQLite DB │ PDF Files │ CSV Config     │
└─────────────────────────────────────────────────────────┘
```

**核心设计原则**：

1. **配置驱动**：所有关键参数通过 YAML 配置，无硬编码
2. **策略模式**：交易策略与引擎解耦，支持热插拔
3. **依赖注入**：DataLoader 注入 BacktestEngine，便于测试
4. **错误隔离**：单个 PDF/ticker 处理失败不影响批量流程
5. **审计追踪**：解析结果和时间线变更均有完整审计记录

### 2.2 技术栈

| 层次 | 技术选型 | 版本要求 | 说明 |
|------|---------|---------|------|
| 语言 | Python | >= 3.10 | 类型注解、dataclass |
| 数值计算 | NumPy | 1.26.4 | 向量化运算 |
| 数据处理 | Pandas | (NumPy 依赖) | DataFrame 核心数据结构 |
| 列式存储 | PyArrow | >= 14.0.0 | Parquet 读写 |
| 嵌入式数据库 | SQLite3 | (标准库) | 限购事件、解析结果存储 |
| 配置管理 | PyYAML | >= 6.0 | YAML 配置解析 |
| 环境变量 | python-dotenv | >= 1.0.0 | .env 加载 |
| PDF 提取 | pdfplumber | >= 0.10.0 | 中文 PDF 文本提取 |
| 本地 LLM | ollama | >= 0.4.0 | Ollama API 客户端 |
| 云端 LLM | openai | >= 1.0.0 | OpenAI 兼容 API 客户端 |
| HTTP 客户端 | requests | >= 2.32.3 | 公告下载 |
| 可视化 | Plotly | >= 5.0.0 | 交互式数据验证图表 |
| 数据下载 | jqdatasdk | 1.9.8 | JoinQuant 数据 API |
| 测试 | unittest | (标准库) | 单元测试/集成测试 |

### 2.3 部署架构

系统为**单机本地部署**，无网络服务组件：

```
本地开发机
├── Python 3.10+ 环境
├── Ollama 服务 (localhost:11434)  ← 可选，本地 LLM
├── 项目代码 (lof-eins/)
│   ├── src/         ← 源代码
│   ├── data/        ← 数据目录 (gitignored)
│   │   ├── real_all_lof/   ← 真实数据
│   │   └── mock/           ← Mock 数据
│   └── configs/     ← YAML 配置
└── 外部依赖
    ├── JoinQuant API        ← 行情数据（需账号）
    ├── Eastmoney API        ← 公告下载（无需认证）
    └── Cloud LLM API        ← 可选，云端 LLM
```

---

## 3. 模块设计

### 3.1 配置模块 (`src/config.py`)

#### 3.1.1 职责描述

提供回测配置的数据类定义、YAML 序列化/反序列化和参数验证。

#### 3.1.2 类设计

```python
@dataclass
class BacktestConfig:
    initial_cash: float = 300_000.0
    liquidity_ratio: float = 0.1
    buy_threshold: float = 0.02
    commission_rate: float = 0.0003
    risk_mode: str = 'fixed'             # 'fixed' | 'infinite'
    use_ma5_liquidity: bool = True
    risk_free_rate: float = 0.02
    data_dir: str = './data/mock'
    tickers: Union[str, List[str]] = 'all'
```

**方法**：

| 方法 | 签名 | 说明 |
|------|------|------|
| `from_yaml` | `@classmethod (path: str) -> BacktestConfig` | 从 YAML 文件加载 |
| `to_yaml` | `(path: str) -> None` | 保存到 YAML 文件 |
| `__post_init__` | `() -> None` | 参数验证（范围、类型） |

#### 3.1.3 核心算法与流程

- `__post_init__` 验证规则：
  - `initial_cash > 0`
  - `0 < liquidity_ratio <= 1`
  - `buy_threshold >= 0`
  - `risk_mode in ('fixed', 'infinite')`

#### 3.1.4 接口定义

- **输入**：YAML 文件路径或关键字参数
- **输出**：BacktestConfig 实例

#### 3.1.5 异常处理

- `ValueError`：参数不在有效范围内
- `FileNotFoundError`：YAML 文件不存在
- `yaml.YAMLError`：YAML 格式错误

---

### 3.2 数据加载模块 (`src/data/loader.py`)

#### 3.2.1 职责描述

从本地文件系统加载多源数据（市场 + NAV + 限购事件），对齐为统一 DataFrame。

#### 3.2.2 类设计

```python
class DataLoader:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self._fee_cache: Optional[dict] = None
```

**方法**：

| 方法 | 签名 | 说明 |
|------|------|------|
| `load_bundle` | `(ticker, start_date?, end_date?) -> pd.DataFrame` | 加载并对齐完整数据 |
| `load_fees` | `() -> dict` | 加载费率配置（带缓存） |
| `_resample_limits_to_daily` | `(ticker, date_index) -> pd.Series` | 限购事件 → 每日序列 |
| `list_available_tickers` | `() -> List[str]` | 自动发现所有可用 ticker |

#### 3.2.3 核心算法与流程

**`_resample_limits_to_daily` 算法**（关键修复：NULL end_date 支持）：

```python
def _resample_limits_to_daily(self, ticker, date_index):
    daily_limits = pd.Series(float('inf'), index=date_index)
    
    for _, event in df_limits.iterrows():
        start = event['start_date']
        end = event['end_date']
        
        if pd.isna(end):  # 开放式限购
            mask = date_index >= start
        else:
            mask = (date_index >= start) & (date_index <= end)
        
        daily_limits.loc[mask] = event['max_amount']
    
    return daily_limits
```

**数据对齐流程**：
1. 读取 market Parquet → 设置 date 为索引
2. 读取 NAV Parquet → 按 date 合并
3. 查询 limit_events → 重采样为每日序列
4. 计算 `premium_rate = (close - nav) / nav`
5. `ffill()` 填充缺失值

#### 3.2.4 接口定义

- **输入**：数据目录路径、ticker、可选日期范围
- **输出**：DataFrame（columns: `open, high, low, close, volume, nav, premium_rate, daily_limit`）
- **DataFrame.attrs**：附加费率配置字段

#### 3.2.5 异常处理

- `FileNotFoundError`：市场数据文件缺失
- SQLite 连接失败时返回全 `inf` 限额

---

### 3.3 数据下载模块 (`src/data/downloader.py`)

#### 3.3.1 职责描述

通过 JoinQuant API 批量下载 LOF 基金市场数据和净值数据。

#### 3.3.2 类设计

```python
class RealDataDownloader:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
```

**方法**：

| 方法 | 签名 | 说明 |
|------|------|------|
| `authenticate` | `() -> None` | JoinQuant 认证 |
| `fetch_all_lof_codes` | `() -> List[str]` | 获取全部 LOF 代码 |
| `download` | `(output_dir, start_date, end_date, batch_size=50) -> None` | 批量下载 |
| `_generate_fee_config` | `(output_dir) -> None` | 生成费率 CSV |
| `_generate_limit_db` | `(output_dir) -> None` | 生成含三表 schema 的 SQLite |

#### 3.3.3 核心算法与流程

**批量下载流程**：
1. 认证 → 获取 LOF 代码列表
2. 分批处理（默认 50 只/批）
3. 每批：下载行情 → 下载净值 → 保存 Parquet
4. 批次间延迟 0.5 秒
5. 最后生成 fees.csv 和 fund_status.db

**数据库初始化 SQL**：
```sql
CREATE TABLE limit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,
    max_amount REAL NOT NULL,
    reason TEXT,
    is_open_ended INT GENERATED ALWAYS AS (end_date IS NULL) STORED,
    source_announcement_ids TEXT
);
CREATE INDEX idx_limit_events_ticker ON limit_events(ticker);
CREATE INDEX idx_limit_events_dates ON limit_events(ticker, start_date, end_date);
```

#### 3.3.4 接口定义

- **外部依赖**：`jqdatasdk`（JoinQuant SDK）
- **输入**：用户凭据、日期范围、输出目录
- **输出**：完整数据目录结构

#### 3.3.5 异常处理

- JoinQuant 认证失败：抛出异常并提示检查凭据
- 网络超时：无自动重试（依赖 jqdatasdk 内部机制）

---

### 3.4 公告下载模块 (`src/data/announcement_downloader.py`)

#### 3.4.1 职责描述

从 Eastmoney API 下载基金公告 PDF 文件。

#### 3.4.2 类设计

```python
class AnnouncementDownloader:
    BASE_URL = "http://np-anotice-stock.eastmoney.com/api/security/ann"
    
    def __init__(self, data_dir: str, delay: float = 1.0):
        self.data_dir = Path(data_dir)
        self.delay = delay
```

**方法**：

| 方法 | 签名 | 说明 |
|------|------|------|
| `get_all_announcements` | `(ticker, start, end, page_size=50) -> List[dict]` | 获取公告列表（分页） |
| `download_pdf` | `(url, save_path, max_retries=3) -> bool` | 下载单个 PDF（含重试） |
| `download_fund_announcements` | `(ticker) -> dict` | 下载 ticker 全部公告 |
| `get_fund_date_range` | `(ticker) -> Tuple[str, str]` | 从行情数据推断日期范围 |

#### 3.4.3 核心算法与流程

**分页查询**：
1. 构建 Eastmoney API 请求（含 ticker、日期范围、分页参数）
2. 循环获取直到无更多数据
3. 解析 JSON 响应提取 PDF URL 和文件名

**重试逻辑**：
```python
for attempt in range(max_retries):
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            f.write(response.content)
        return True
    except requests.RequestException:
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # 指数退避
```

#### 3.4.4 接口定义

- **Eastmoney API 端点**：`http://np-anotice-stock.eastmoney.com/api/security/ann`
- **请求参数**：`sr=-1&page_size=50&page_index=1&ann_type=...&stock=<ticker>`

#### 3.4.5 异常处理

- HTTP 错误：记录日志并继续
- 文件写入失败：返回 `False`
- 已存在文件：跳过下载

---

### 3.5 PDF 提取模块 (`src/data/pdf_extractor.py`)

#### 3.5.1 职责描述

使用 pdfplumber 从 PDF 文件中提取纯文本，支持中文。

#### 3.5.2 类/组件设计

模块级函数（非类）：

| 函数 | 签名 | 说明 |
|------|------|------|
| `extract_pdf_text` | `(pdf_path: str) -> dict` | 主提取函数 |
| `_clean_text` | `(text: str) -> str` | 文本清洗 |

#### 3.5.3 核心算法与流程

```python
def extract_pdf_text(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        texts = []
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text()
            if text:
                texts.append(f"--- Page {i} ---\n{text}")
        
        full_text = _clean_text("\n".join(texts))
        return {"success": True, "text": full_text, "pages": len(pdf.pages), "error": None}
```

#### 3.5.4 接口定义

**返回结构**：
```python
{
    "success": bool,
    "text": str,       # 提取的文本（多页用 --- Page N --- 分隔）
    "pages": int,      # 总页数
    "error": str|None  # 错误信息
}
```

#### 3.5.5 异常处理

- `PDFException`：PDF 文件损坏
- `PermissionError`：文件权限不足
- 通用异常：捕获并返回错误信息

---

### 3.6 LLM 客户端模块 (`src/data/llm_client.py`)

#### 3.6.1 职责描述

通过 LLM（云端或本地 Ollama）解析公告文本，提取结构化限购信息。支持双提供商模式。

#### 3.6.2 类设计

```python
class LLMClient:
    def __init__(self,
                 url: Optional[str] = None,
                 api_key: Optional[str] = None,
                 model: Optional[str] = None):
        # 优先使用云端 API，降级到本地 Ollama
        self.mode = 'cloud' if (url and api_key) else 'local'
```

**方法**：

| 方法 | 签名 | 说明 |
|------|------|------|
| `parse_announcement` | `(text, ticker) -> List[dict]` | 主解析方法 |
| `_build_system_prompt` | `() -> str` | 构建 system prompt（含 few-shot 示例） |
| `_build_user_prompt` | `(text, ticker) -> str` | 构建 user prompt |
| `_extract_json_from_response` | `(response: str) -> Any` | 从自由文本提取 JSON |
| `_clean_output` | `(records, ticker) -> List[dict]` | 验证和规范化输出 |
| `_validate_date` | `(date_str) -> Optional[str]` | 日期格式验证 |

#### 3.6.3 核心算法与流程

**双模式调用**：
```
if mode == 'cloud':
    使用 openai.OpenAI(base_url=url, api_key=api_key)
    调用 chat.completions.create()
else:
    使用 ollama.chat(model=model, messages=[...])
```

**JSON 提取算法**：
1. 去除 thinking tokens（`<think>...</think>`）
2. 尝试匹配 markdown 代码块中的 JSON
3. 尝试直接解析整个响应
4. 查找第一个 `[` 或 `{` 并提取

**Few-shot Prompt 结构**：
- System prompt：定义角色、输出格式、4 种公告类型说明
- 3 个示例：complete、open-start、end-only
- User prompt：公告文本 + ticker

**输出规范化**：
```python
record = {
    "ticker": ticker,
    "limit_amount": float | None,
    "start_date": "YYYY-MM-DD" | None,
    "end_date": "YYYY-MM-DD" | None,
    "announcement_type": "complete"|"open-start"|"end-only"|"modify",
    "is_purchase_limit_announcement": bool,
    "confidence": float (0-1)
}
```

#### 3.6.4 接口定义

- **云端**：OpenAI 兼容 API（`POST /v1/chat/completions`）
- **本地**：Ollama API（`POST /api/chat`）
- **输入**：公告文本 + ticker
- **输出**：限购记录列表

#### 3.6.5 异常处理

- 网络错误：返回包含 `error` 字段的记录
- JSON 解析失败：多级降级策略
- 无效日期：设为 `None`
- Thinking tokens：自动剥离
- 空响应：返回错误记录

---

### 3.7 公告处理流水线 (`src/data/announcement_processor.py`)

#### 3.7.1 职责描述

编排 PDF 提取 → LLM 解析 → 数据库存储的端到端流程。

#### 3.7.2 类设计

```python
class AnnouncementProcessor:
    def __init__(self,
                 db_path: str,
                 announcements_dir: str,
                 llm_client: Optional[LLMClient] = None):
        self.db_path = db_path
        self.announcements_dir = Path(announcements_dir)
        self.llm_client = llm_client or LLMClient()
```

**方法**：

| 方法 | 签名 | 说明 |
|------|------|------|
| `process_pdf` | `(ticker, pdf_path) -> dict` | 处理单个 PDF |
| `process_ticker` | `(ticker) -> dict` | 批量处理 ticker |
| `_save_parse_result` | `(ticker, filename, text, result, confidence) -> None` | 存储到 SQLite |
| `_parse_date_from_filename` | `(filename) -> Optional[str]` | 从文件名提取日期 |

#### 3.7.3 核心算法与流程

**单 PDF 处理流程**：
```
process_pdf(ticker, pdf_path)
    ├─ 1. extract_pdf_text(pdf_path) → text
    │      └─ 失败 → return {success: false, error: ...}
    ├─ 2. llm_client.parse_announcement(text, ticker) → records
    │      └─ 失败 → return {success: false, error: ...}
    ├─ 3. _save_parse_result(ticker, filename, text, records, confidence)
    │      └─ INSERT OR REPLACE into announcement_parses
    └─ 4. return {success: true, stored: true, parse_result: records}
```

**批量处理流程**：
```
process_ticker(ticker)
    ├─ 1. 扫描 announcements/<ticker>/*.pdf
    ├─ 2. for each pdf:
    │      └─ process_pdf(ticker, pdf) → 累计统计
    └─ 3. return {total, extracted, parsed, stored, failed}
```

#### 3.7.4 接口定义

**单 PDF 返回结构**：
```python
{
    "success": bool,
    "stored": bool,
    "parse_result": List[dict] | None,
    "error": str | None
}
```

**批量返回结构**：
```python
{
    "total": int,       # PDF 总数
    "extracted": int,   # 文本提取成功数
    "parsed": int,      # LLM 解析成功数
    "stored": int,      # 数据库存储成功数
    "failed": int       # 失败数
}
```

#### 3.7.5 异常处理

- 单 PDF 失败不中断批量处理
- 使用 `INSERT OR REPLACE` 支持重新处理
- 所有错误记录到返回结果中

---

### 3.8 策略模块 (`src/strategy/`)

#### 3.8.1 职责描述

提供可扩展的策略框架，定义信号数据结构和策略基类。

#### 3.8.2 类设计

**Signal 数据类**：
```python
@dataclass
class Signal:
    action: str     # 'buy' | 'sell'
    ticker: str     # 基金代码
    amount: float   # 交易金额（CNY）
```

**BaseStrategy 抽象基类**：
```python
class BaseStrategy(ABC):
    @abstractmethod
    def generate_signals(
        self,
        row: pd.Series,
        positions: Dict[str, float],
        config: BacktestConfig
    ) -> List[Signal]:
        pass
```

**SimpleLOFStrategy**：
```python
class SimpleLOFStrategy(BaseStrategy):
    def generate_signals(self, row, positions, config):
        signals = []
        ticker = row['ticker']
        
        # 卖出逻辑：持仓 > 0 → 全部卖出（快速止盈）
        if positions.get(ticker, 0) > 0:
            signals.append(Signal('sell', ticker, float('inf')))
        
        # 买入逻辑：溢价率 > 阈值 且 限购允许
        if row['premium_rate'] > config.buy_threshold and row['daily_limit'] > 0:
            signals.append(Signal('buy', ticker, float('inf')))
        
        return signals
```

#### 3.8.3 核心算法与流程

SimpleLOFStrategy 决策流程：
1. **卖出优先**：如果有已结算持仓，生成 sell 信号（全量卖出）
2. **买入判断**：`premium_rate > buy_threshold` 且 `daily_limit > 0`
3. **金额**：买入使用 `float('inf')` 表示"尽可能多"，由引擎约束

#### 3.8.4 接口定义

- **输入**：`row`（当日行数据）、`positions`（当前持仓）、`config`
- **输出**：`List[Signal]`

#### 3.8.5 异常处理

- 策略层不抛异常，由引擎层处理边界条件

---

### 3.9 回测引擎模块 (`src/engine/`)

#### 3.9.1 职责描述

执行多 ticker 回测，管理 T+2 结算、费率计算和绩效评估。

#### 3.9.2 类设计

**Account 类**：
```python
@dataclass
class PendingSettlement:
    ticker: str
    shares: float
    settlement_date: date

class Account:
    def __init__(self, initial_cash: float):
        self.cash: float = initial_cash
        self.positions: Dict[str, float] = {}     # 已结算持仓
        self.pending: List[PendingSettlement] = [] # T+2 待结算
```

| 方法 | 签名 | 说明 |
|------|------|------|
| `buy` | `(ticker, shares, cost, settlement_date)` | 买入（扣资金，加待结算） |
| `sell` | `(ticker, shares, revenue)` | 卖出（加资金，减持仓） |
| `update_date` | `(current_date)` | 推进结算队列 |
| `get_available_shares` | `(ticker) -> float` | 查询可卖份额 |
| `get_pending_shares` | `(ticker) -> float` | 查询待结算份额 |
| `get_total_value` | `(prices: Dict) -> float` | 计算总市值 |

**BacktestEngine 类**：
```python
class BacktestEngine:
    def __init__(self, config: BacktestConfig, strategy: BaseStrategy,
                 data_loader: Optional[DataLoader] = None):
        self.config = config
        self.strategy = strategy
        self.data_loader = data_loader
```

| 方法 | 签名 | 说明 |
|------|------|------|
| `run` | `(tickers, start_date?, end_date?) -> BacktestResult` | 主回测循环 |
| `_load_multi_data` | `(tickers) -> pd.DataFrame` | 加载多 ticker 数据 |
| `_execute_buy` | `(signal, row, account) -> Optional[dict]` | 执行买入 |
| `_execute_sell` | `(signal, row, account) -> Optional[dict]` | 执行卖出 |

**BacktestResult 类**：
```python
@dataclass
class BacktestResult:
    daily_perf: pd.DataFrame       # 每日绩效
    trade_logs: pd.DataFrame       # 交易日志
    daily_snapshots: List[dict]    # 每日快照
    config: BacktestConfig
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    num_trades: int
    num_buy_trades: int
    num_sell_trades: int
```

#### 3.9.3 核心算法与流程

**主回测循环**：
```
run(tickers):
    1. 加载多 ticker 数据 → 合并 DataFrame
    2. 创建 Account(initial_cash)
    3. for each trading_day:
        a. account.update_date(day)  # 推进 T+2 结算
        b. SELL PHASE:
           for each ticker with available shares:
               strategy.generate_signals() → sell signals
               _execute_sell(signal, row, account)
        c. BUY PHASE:
           candidates = [rows where premium_rate > threshold]
           sort by premium_rate DESC  # 贪心：优先买溢价率最高的
           for each candidate:
               strategy.generate_signals() → buy signals
               _execute_buy(signal, row, account)
        d. 记录每日绩效（NAV、总市值、现金、持仓）
    4. 计算绩效指标 → return BacktestResult
```

**买入约束计算**：
```python
def _execute_buy(self, signal, row, account):
    # 四重约束取最小值
    limit_cap = row['daily_limit']
    liquid_cap = min(row['volume'], row.get('ma5_volume', row['volume'])) \
                 * self.config.liquidity_ratio * row['close']
    cash_cap = account.cash if self.config.risk_mode == 'fixed' else float('inf')
    signal_cap = signal.amount
    
    max_amount = min(limit_cap, liquid_cap, cash_cap, signal_cap)
    
    if max_amount <= 0:
        return None
    
    # 扣除申购费
    fee = self._calc_fee(max_amount)
    net_amount = max_amount - fee
    shares = net_amount / row['nav']
    
    # T+2 结算日
    settlement_date = self._calc_settlement_date(current_date, trading_days, offset=2)
    
    account.buy(ticker, shares, max_amount, settlement_date)
    return trade_log
```

**阶梯费率计算**：
```python
def _calc_fee(self, amount):
    if amount < fee_limit_1:        # < 500,000
        return amount * 0.015
    elif amount < fee_limit_2:      # < 2,000,000
        return amount * 0.01
    else:
        return 1000.0               # 固定费用
```

**绩效指标计算**：
```python
total_return = (final_value - initial_cash) / initial_cash
annualized_return = (1 + total_return) ** (252 / trading_days) - 1
max_drawdown = max((peak - trough) / peak for peak, trough in drawdown_periods)
sharpe_ratio = (annualized_return - risk_free_rate) / annualized_volatility
```

#### 3.9.4 接口定义

- **输入**：BacktestConfig + BaseStrategy + DataLoader + tickers
- **输出**：BacktestResult

#### 3.9.5 异常处理

- `ValueError`：现金不足 / 持仓不足
- 浮点容差：`1e-9`
- 空数据：跳过 ticker 并记录警告
- 日志：所有交易记录到 `backtest_execution.log`

---

### 3.10 Mock 数据生成模块 (`src/data/generator/`)

#### 3.10.1 职责描述

生成与真实数据格式完全兼容的合成 LOF 数据，用于测试和开发。

#### 3.10.2 类设计

**MockConfig**（`generator/config.py`）：
```python
@dataclass
class MockConfig:
    tickers: List[str]
    start_date: str
    end_date: str
    initial_nav: float = 2.0
    premium_volatility: float = 0.01
    limit_trigger_threshold: float = 0.07
    limit_release_threshold: float = 0.03
    consecutive_days: int = 1
    spike_probability: float = 0.04
    nav_drift: float = -0.0005
    nav_volatility: float = 0.015
    limit_max_amount: float = 100.0
    normal_max_amount: float = 1_000_000.0
```

**生成器类**（`generator/generators.py`）：

| 类 | 职责 |
|------|------|
| `NAVGenerator` | GBM 模拟净值路径 |
| `PriceGenerator` | 基于 NAV + 溢价率生成 OHLCV |
| `FeeConfigGenerator` | 生成标准阶梯费率 CSV |
| `FundStatusGenerator` | 基于溢价率阈值生成限购事件 |

#### 3.10.3 核心算法与流程

**NAV 生成（GBM）**：
```python
for t in range(1, n_days):
    dW = np.random.normal(0, 1) * sqrt(dt)
    nav[t] = nav[t-1] * exp((drift - 0.5 * vol^2) * dt + vol * dW)
```

**限购事件触发逻辑**：
```
for each day:
    if premium_rate > trigger_threshold:
        consecutive_count += 1
        if consecutive_count >= consecutive_days:
            START_LIMIT_EVENT
    else:
        consecutive_count = 0
    
    if in_limit and premium_rate < release_threshold:
        END_LIMIT_EVENT
```

#### 3.10.4 接口定义

- **输入**：MockConfig
- **输出**：完整数据目录（market/*.parquet, nav/*.parquet, config/fees.csv, config/fund_status.db）

#### 3.10.5 异常处理

- 无效日期范围：`ValueError`
- 空 ticker 列表：`ValueError`

---

## 4. 数据设计

### 4.1 数据库设计

系统使用 **SQLite** 嵌入式数据库（`config/fund_status.db`），包含三张表：

```
┌─────────────────────────┐
│      fund_status.db     │
├─────────────────────────┤
│  limit_events           │  ← 限购事件（核心表）
│  announcement_parses    │  ← 公告解析结果（审计用）
│  limit_event_log        │  ← 变更日志（审计用）
└─────────────────────────┘
```

**ER 关系**：

```
announcement_parses (1) ──▶ (N) limit_events
    通过 source_announcement_ids JSON 数组关联

limit_events (1) ──▶ (N) limit_event_log
    通过 ticker + 时间范围隐式关联
```

**表结构详见**：需求文档 `docs/requirements.md` 第 6.2 节。

**索引设计**：

| 表 | 索引 | 列 | 用途 |
|----|------|-----|------|
| limit_events | idx_limit_events_ticker | (ticker) | 按 ticker 查询限购 |
| limit_events | idx_limit_events_dates | (ticker, start_date, end_date) | 日期范围查询 |
| announcement_parses | UNIQUE | (ticker, pdf_filename) | 防止重复、支持 REPLACE |

### 4.2 数据流设计

```
[外部数据源]
    │
    ├── JoinQuant API ──────► market/*.parquet, nav/*.parquet
    │                          (RealDataDownloader)
    │
    ├── Eastmoney API ──────► announcements/<ticker>/*.pdf
    │                          (AnnouncementDownloader)
    │
    └── LLM (Ollama/Cloud) ─► announcement_parses 表
                                (LLMClient → AnnouncementProcessor)

[数据处理]
    │
    ├── PDF → Text ─────────► (pdfplumber)
    ├── Text → JSON ────────► (LLM)
    ├── JSON → DB ──────────► (AnnouncementProcessor._save_parse_result)
    └── (Phase 3) ──────────► limit_events 表
                                (TimelineBuilder.integrate_timeline)

[数据消费]
    │
    ├── DataLoader.load_bundle() ──► Aligned DataFrame
    │     ├── Parquet (market + nav)
    │     ├── SQLite (limit_events → daily_limit)
    │     └── CSV (fees → DataFrame.attrs)
    │
    └── BacktestEngine.run() ──────► BacktestResult
          ├── Strategy signals
          ├── Account management
          └── Performance metrics
```

### 4.3 缓存策略

| 缓存项 | 实现 | 失效策略 |
|--------|------|---------|
| 费率配置 | `DataLoader._fee_cache` (dict) | 生命周期内不失效（只读数据） |
| 公告解析 | SQLite `announcement_parses` + UNIQUE 约束 | `INSERT OR REPLACE`（重新处理时覆盖） |

---

## 5. 接口设计

### 5.1 API 接口清单

| # | 接口名 | 模块 | 方法 | 说明 |
|---|--------|------|------|------|
| 1 | `BacktestConfig.from_yaml` | config | classmethod | 从 YAML 加载配置 |
| 2 | `DataLoader.load_bundle` | data/loader | instance | 加载对齐的完整数据 |
| 3 | `DataLoader.list_available_tickers` | data/loader | instance | 自动发现 ticker |
| 4 | `BacktestEngine.run` | engine/backtest | instance | 执行回测 |
| 5 | `AnnouncementProcessor.process_pdf` | data/announcement_processor | instance | 处理单 PDF |
| 6 | `AnnouncementProcessor.process_ticker` | data/announcement_processor | instance | 批量处理 ticker |
| 7 | `LLMClient.parse_announcement` | data/llm_client | instance | LLM 解析公告 |
| 8 | `extract_pdf_text` | data/pdf_extractor | function | PDF 文本提取 |

### 5.2 接口详细定义

#### API-1: `BacktestConfig.from_yaml`

```python
@classmethod
def from_yaml(cls, path: str) -> 'BacktestConfig':
    """
    从 YAML 文件加载回测配置。
    
    Args:
        path: YAML 文件路径
    Returns:
        BacktestConfig 实例
    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 参数验证失败
        yaml.YAMLError: YAML 格式错误
    """
```

#### API-2: `DataLoader.load_bundle`

```python
def load_bundle(
    self,
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> pd.DataFrame:
    """
    加载并对齐 ticker 的完整数据。
    
    Args:
        ticker: 基金代码
        start_date: 起始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
    Returns:
        DataFrame with columns: open, high, low, close, volume,
                                nav, premium_rate, daily_limit
        DataFrame.attrs: 费率配置字段
    Raises:
        FileNotFoundError: 市场数据文件缺失
    """
```

#### API-3: `BacktestEngine.run`

```python
def run(
    self,
    tickers: Union[str, List[str]],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> BacktestResult:
    """
    执行多 ticker 回测。
    
    Args:
        tickers: 单个或多个基金代码
        start_date: 起始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
    Returns:
        BacktestResult 包含绩效指标和交易日志
    """
```

#### API-4: `AnnouncementProcessor.process_pdf`

```python
def process_pdf(
    self,
    ticker: str,
    pdf_path: Path
) -> dict:
    """
    端到端处理单个 PDF 公告。
    
    Args:
        ticker: 基金代码
        pdf_path: PDF 文件路径
    Returns:
        {
            "success": bool,
            "stored": bool,
            "parse_result": List[dict] | None,
            "error": str | None
        }
    """
```

#### API-5: `LLMClient.parse_announcement`

```python
def parse_announcement(
    self,
    text: str,
    ticker: str
) -> List[dict]:
    """
    使用 LLM 解析公告文本中的限购信息。
    
    Args:
        text: 公告纯文本
        ticker: 基金代码
    Returns:
        限购记录列表，每条包含：
        ticker, limit_amount, start_date, end_date,
        announcement_type, is_purchase_limit_announcement, confidence
    """
```

### 5.3 认证与鉴权

| 服务 | 认证方式 | 凭据来源 |
|------|---------|---------|
| JoinQuant | 用户名 + 密码 | `.env` → `JQ_USERNAME`, `JQ_PASSWORD` |
| Cloud LLM | API Key (Bearer) | `.env` → `LLM_API_KEY` |
| Ollama | 无需认证 | — |
| Eastmoney | 无需认证 | — |

---

## 6. 安全设计

### 6.1 认证机制

- API 凭据通过 `python-dotenv` 从 `.env` 文件加载
- `.env` 文件在 `.gitignore` 中排除，不提交版本控制
- 提供 `.env.example` 作为配置模板

### 6.2 数据加密

- 当前无数据加密需求（纯本地存储，无网络暴露）
- LLM API Key 在传输中使用 HTTPS 加密（云端模式）

### 6.3 输入校验

| 校验点 | 校验内容 | 处理方式 |
|--------|---------|---------|
| YAML 配置 | 参数范围、类型 | `__post_init__` 验证，抛 `ValueError` |
| CLI 参数 | `argparse` 类型限制 | 自动错误提示 |
| LLM 输出 | JSON 格式、日期格式、字段完整性 | 多级降级解析 |
| PDF 文件 | 文件存在性、格式有效性 | 异常捕获，返回错误信息 |
| API 响应 | HTTP 状态码、JSON 格式 | 异常处理 + 重试 |

---

## 7. 错误处理与日志

### 7.1 错误码定义

系统使用异常类 + 返回字典两种错误处理模式：

**异常类模式**（严重错误，中断执行）：

| 异常 | 触发场景 | 处理建议 |
|------|---------|---------|
| `ValueError` | 配置参数无效、余额不足 | 修正参数后重试 |
| `FileNotFoundError` | 数据文件缺失 | 确认数据目录和文件 |
| `sqlite3.IntegrityError` | 数据库约束违反 | 检查数据一致性 |

**返回字典模式**（可恢复错误，不中断执行）：

| 字段 | 说明 |
|------|------|
| `success: False` | 操作失败 |
| `error: str` | 错误描述 |
| `stored: False` | 未存储到数据库 |

**CLI 退出码**（`scripts/parse_announcements.py`）：

| 退出码 | 含义 |
|--------|------|
| 0 | 成功 |
| 1 | 配置错误 |
| 2 | 处理错误 |

### 7.2 日志规范

**日志框架**：Python 标准 `logging` 模块

**日志格式**：
```
%(asctime)s - %(levelname)s - %(message)s
```

**日志级别使用规范**：

| 级别 | 使用场景 | 示例 |
|------|---------|------|
| DEBUG | 调试信息 | `Extracted 5432 characters from PDF` |
| INFO | 正常流程 | `Processing PDF for 161005: ann_2024.pdf` |
| WARNING | 可恢复异常 | `Text extraction failed, skipping` |
| ERROR | 不可恢复异常 | `Database storage failed: UNIQUE constraint` |

**日志输出**：

| 目标 | 用途 |
|------|------|
| `backtest_execution.log` | 回测执行日志（文件） |
| `stderr` | 实时控制台输出 |

**日志配置**：
```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("backtest_execution.log", mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
```

---

## 8. 附录

### 8.1 变更记录

| 日期 | 版本 | 变更说明 |
|------|------|---------|
| 2026-02-16 | 1.0 | 初始版本，基于当前代码库（Phase 1 ✅、Phase 2 ✅）创建完整详细设计 |
