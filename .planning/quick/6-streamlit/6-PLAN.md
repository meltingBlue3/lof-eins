---
phase: quick-6
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - app/app.py
  - app/pages/1_data_explorer.py
  - app/pages/2_backtest.py
  - app/pages/3_backtest_results.py
  - app/utils.py
autonomous: true
requirements: [QUICK-6]

must_haves:
  truths:
    - "Home page clearly describes the system purpose and guides users through the 3-step workflow"
    - "Data explorer sidebar controls are logically grouped and labeled with helpful defaults"
    - "Backtest page shows parameter descriptions so users understand what each value controls"
    - "Backtest results page displays metrics with color-coded positive/negative indicators"
    - "Navigation between pages follows a clear 1-2-3 workflow progression"
  artifacts:
    - path: "app/app.py"
      provides: "Redesigned home page with workflow guidance"
    - path: "app/pages/2_backtest.py"
      provides: "Improved parameter form with descriptions and YAML load option"
    - path: "app/pages/3_backtest_results.py"
      provides: "Enhanced results page with better metric presentation"
    - path: "app/utils.py"
      provides: "Updated chart builders with consistent Chinese formatting"
  key_links:
    - from: "app/pages/2_backtest.py"
      to: "st.session_state"
      via: "backtest_result stored after run"
      pattern: "session_state.*backtest_result"
    - from: "app/pages/3_backtest_results.py"
      to: "st.session_state"
      via: "reads backtest_result"
      pattern: "session_state.*backtest_result"
---

<objective>
Improve the Streamlit frontend for better usability and clarity.

Purpose: The current UI is functional but bare-bones. Users need clearer workflow guidance, better parameter descriptions, and more polished visual presentation to effectively use the backtesting system.

Output: Redesigned Streamlit app with improved home page, better-organized controls, parameter descriptions, and enhanced result visualization.
</objective>

<execution_context>
@C:/Users/zhang/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/zhang/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@app/app.py
@app/pages/1_data_explorer.py
@app/pages/2_backtest.py
@app/pages/3_backtest_results.py
@app/utils.py
@src/config.py
@configs/backtest.yaml

<interfaces>
From src/config.py:
```python
@dataclass
class BacktestConfig:
    initial_cash: float = 300_000.0
    liquidity_ratio: float = 0.1
    buy_threshold: float = 0.02
    commission_rate: float = 0.0003
    risk_mode: Literal['fixed', 'infinite'] = 'fixed'
    use_ma5_liquidity: bool = True
    risk_free_rate: float = 0.02

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "BacktestConfig":
```

From src/__init__.py (used by backtest page):
```python
from src.config import BacktestConfig
from src.engine.backtest import BacktestEngine
from src.strategy.simple_lof import SimpleLOFStrategy
from src.data.loader import DataLoader
```

BacktestEngine.run() returns a result object with attributes:
- result.total_return (float)
- result.annualized_return (float)
- result.max_drawdown (float)
- result.sharpe_ratio (float)
- result.num_trades (int)
- result.daily_perf (pd.DataFrame with "total_assets" column)
- result.trade_logs (pd.DataFrame with "ticker", "action", "date", "price", "net_amount" columns)
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Redesign home page and data explorer with workflow guidance</name>
  <files>app/app.py, app/pages/1_data_explorer.py</files>
  <action>
**app/app.py** - Redesign as a proper landing page:
- Replace the plain text with a structured layout using st.columns for a 3-step workflow overview:
  - Step 1: "浏览数据" (explore data) with brief description
  - Step 2: "配置回测" (configure backtest) with brief description
  - Step 3: "分析结果" (analyze results) with brief description
- Add a "快速开始" (quick start) section below that explains:
  - Default data directory is `./data/mock` with mock data for testing
  - For real data, use `./data/real_all_lof` (if available)
- Add a system status section showing whether data directories exist using Path.exists()
- Keep page_config as-is (wide layout, page_title, page_icon)

**app/pages/1_data_explorer.py** - Improve sidebar organization:
- Group sidebar controls with st.expander or clear section headers using st.markdown("**数据源**") etc.
- Add help text to the data_dir text_input: help="mock数据: ./data/mock, 实盘数据: ./data/real_all_lof"
- Add help parameter to multiselect: help="可多选查看对比"
- Add help parameter to buy_threshold: help="红色虚线参考线位置"
- For date inputs, set sensible labels: "开始日期 (留空=全部)" and "结束日期 (留空=全部)"
- After the charts for each ticker, add a small st.expander("原始数据") containing st.dataframe(df.tail(20)) so users can inspect raw values
  </action>
  <verify>cd C:/Users/zhang/Desktop/Projects/Python/lof-eins && python -c "import ast; ast.parse(open('app/app.py').read()); ast.parse(open('app/pages/1_data_explorer.py').read()); print('OK')"</verify>
  <done>Home page shows 3-step workflow overview with quick-start guidance; data explorer has help text on all controls and raw data expander per ticker</done>
</task>

<task type="auto">
  <name>Task 2: Improve backtest parameter page with descriptions and YAML loading</name>
  <files>app/pages/2_backtest.py</files>
  <action>
Redesign the backtest parameter page for clarity:

1. **Add YAML config loader** at the top of the parameter section:
   - Add a st.file_uploader("导入配置文件 (YAML)", type=["yaml", "yml"])
   - When a file is uploaded, parse it with yaml.safe_load and populate st.session_state defaults
   - Also add a button "加载默认配置" that reads from configs/backtest.yaml using BacktestConfig.from_yaml()
   - Show the loaded config values as st.info() briefly

2. **Add help text to every parameter input:**
   - initial_cash: help="回测起始资金，单位：人民币"
   - buy_threshold: help="溢价率超过此值触发买入信号。例：0.02 = 2%"
   - liquidity_ratio: help="每日可交易量占成交量的比例。越高=假设越好的流动性"
   - commission_rate: help="卖出交易佣金费率。例：0.0003 = 万三"
   - risk_mode: help="fixed=受资金约束, infinite=忽略资金限制(理想化测试)"
   - use_ma5_liquidity: help="勾选后使用5日均量作为流动性基准，更保守"
   - risk_free_rate: help="夏普比率计算用的无风险利率"

3. **Improve post-run feedback:**
   - Replace the raw `st.markdown(f"```\n{result}\n```")` with a summary using st.metric cards (same as results page) showing total_return, annualized_return, max_drawdown, sharpe_ratio, num_trades
   - Add a clear call-to-action: st.info("切换到左侧 **回测结果分析** 页面查看详细图表和交易记录") with a page_link if possible
   - Store the backtest config in session_state too: st.session_state["backtest_config"] = config

4. **Keep all existing sidebar controls** (data_dir, tickers, dates) unchanged in functionality.
  </action>
  <verify>cd C:/Users/zhang/Desktop/Projects/Python/lof-eins && python -c "import ast; ast.parse(open('app/pages/2_backtest.py').read()); print('OK')"</verify>
  <done>Backtest page has help text on all parameters, YAML config loading, and metric-card summary after running backtest instead of raw text dump</done>
</task>

<task type="auto">
  <name>Task 3: Enhance results page and chart formatting</name>
  <files>app/pages/3_backtest_results.py, app/utils.py</files>
  <action>
**app/pages/3_backtest_results.py** - Polish the results presentation:

1. **Color-coded metrics:** Use the delta parameter on st.metric to show positive/negative:
   - total_return: delta=f"{result.total_return:.2%}" with delta_color="normal" (green if positive)
   - annualized_return: delta=f"{result.annualized_return:.2%}" with delta_color="normal"
   - max_drawdown: delta=f"{result.max_drawdown:.2%}" with delta_color="inverse" (red = bad drawdown)
   - sharpe_ratio: show label "夏普比率" with delta based on whether > 1.0 ("良好" if > 1, "偏低" if <= 1)
   - num_trades: no delta needed, just the count

2. **Show backtest config used** (if stored in session_state by Task 2):
   - Add a st.expander("回测参数") at the top that shows the config as a clean table using st.table() with parameter name and value columns

3. **Trade log improvements:**
   - Format the trade_logs dataframe columns before display: rename English column names to Chinese (ticker->标的, action->操作, date->日期, price->价格, net_amount->净金额)
   - Add column_config to st.dataframe for number formatting (price 2 decimals, net_amount 2 decimals)
   - Add a download button: st.download_button("导出交易记录 CSV", trade_logs.to_csv(index=False), "trades.csv", "text/csv")

**app/utils.py** - Improve chart formatting consistency:

1. **Unified chart theme:** Add a helper function `_apply_chart_theme(fig)` that sets:
   - font family: "Microsoft YaHei, SimHei, sans-serif" (for Chinese character rendering)
   - consistent margins: dict(l=60, r=30, t=50, b=40)
   - hovermode="x unified" for all time-series charts
   - Apply this function at the end of every chart builder before returning

2. **Premium chart enhancement:**
   - Add a zero line (fig.add_hline y=0) in grey for reference
   - Color the premium line: green when positive, red when negative using conditional coloring (simplest: just add fill="tozeroy" with fillcolor rgba green)

3. **Equity curve chart:** Add hover template showing date and formatted CNY amount: hovertemplate="%{x}<br>%{y:,.0f} CNY"
  </action>
  <verify>cd C:/Users/zhang/Desktop/Projects/Python/lof-eins && python -c "import ast; ast.parse(open('app/pages/3_backtest_results.py').read()); ast.parse(open('app/utils.py').read()); print('OK')"</verify>
  <done>Results page shows color-coded metrics with deltas, Chinese column names in trade log with CSV export, and all charts use consistent Chinese-friendly theme with unified hover</done>
</task>

</tasks>

<verification>
All 5 app files parse without syntax errors:
```bash
cd C:/Users/zhang/Desktop/Projects/Python/lof-eins && python -c "
import ast
for f in ['app/app.py', 'app/pages/1_data_explorer.py', 'app/pages/2_backtest.py', 'app/pages/3_backtest_results.py', 'app/utils.py']:
    ast.parse(open(f).read())
    print(f'{f}: OK')
print('All files valid')
"
```
</verification>

<success_criteria>
- All 5 Streamlit files parse without errors
- Home page provides clear 3-step workflow guidance
- Every parameter input has Chinese help text
- Backtest results show color-coded metric cards (not raw text)
- Trade log has Chinese column names and CSV export
- All charts use consistent font and hover formatting
</success_criteria>

<output>
After completion, create `.planning/quick/6-streamlit/6-SUMMARY.md`
</output>
