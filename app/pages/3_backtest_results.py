"""Page 3: 回测结果分析"""

import streamlit as st

from utils import (
    equity_curve_chart,
    load_bundle_cached,
    pnl_by_ticker_chart,
    trade_markers_chart,
)

st.header("回测结果分析")

# ---------------------------------------------------------------------------
# Guard: result must exist in session state
# ---------------------------------------------------------------------------
if "backtest_result" not in st.session_state:
    st.info("尚无回测结果。请先在 **回测参数调整 + 运行** 页面执行回测。")
    st.stop()

result = st.session_state["backtest_result"]
tickers = st.session_state.get("backtest_tickers", [])
data_dir = st.session_state.get("backtest_data_dir", "./data/mock")

# ---------------------------------------------------------------------------
# Metrics cards
# ---------------------------------------------------------------------------
st.subheader("核心指标")
cols = st.columns(5)
cols[0].metric("总收益率", f"{result.total_return:.2%}")
cols[1].metric("年化收益率", f"{result.annualized_return:.2%}")
cols[2].metric("最大回撤", f"{result.max_drawdown:.2%}")
cols[3].metric("夏普比率", f"{result.sharpe_ratio:.2f}")
cols[4].metric("交易次数", result.num_trades)

# ---------------------------------------------------------------------------
# Equity curve
# ---------------------------------------------------------------------------
st.subheader("权益曲线")
if not result.daily_perf.empty:
    st.plotly_chart(equity_curve_chart(result.daily_perf), use_container_width=True)
else:
    st.warning("无每日绩效数据")

# ---------------------------------------------------------------------------
# Trade markers on OHLC per ticker
# ---------------------------------------------------------------------------
st.subheader("交易标记")
for ticker in tickers:
    try:
        df = load_bundle_cached(data_dir, ticker)
    except FileNotFoundError:
        st.warning(f"无法加载 {ticker} 的行情数据")
        continue
    if df.empty:
        continue
    st.plotly_chart(
        trade_markers_chart(df, result.trade_logs, ticker),
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Per-ticker PnL summary
# ---------------------------------------------------------------------------
st.subheader("各标的盈亏")
st.plotly_chart(pnl_by_ticker_chart(result.trade_logs), use_container_width=True)

# ---------------------------------------------------------------------------
# Trade log table
# ---------------------------------------------------------------------------
st.subheader("交易明细")
if not result.trade_logs.empty:
    st.dataframe(
        result.trade_logs,
        use_container_width=True,
        height=400,
    )
else:
    st.info("无交易记录")
