"""Page 2: 回测参数调整 + 运行"""

import streamlit as st

from utils import get_data_loader

# Ensure project root is importable (already handled in utils, but be safe)
import sys
from pathlib import Path
_root = str(Path(__file__).resolve().parent.parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from src import BacktestConfig, BacktestEngine, SimpleLOFStrategy

st.header("回测参数调整 + 运行")

# ---------------------------------------------------------------------------
# Runtime controls
# ---------------------------------------------------------------------------
with st.sidebar:
    data_dir = st.text_input("数据目录", value="./data/mock", key="bt_data_dir")
    try:
        loader = get_data_loader(data_dir)
        available = loader.list_available_tickers()
    except FileNotFoundError:
        st.error(f"数据目录不存在或结构不完整: {data_dir}")
        st.stop()

    if not available:
        st.warning("该目录下未找到可用标的")
        st.stop()

    tickers = st.multiselect("选择标的", available, default=available, key="bt_tickers")
    col1, col2 = st.columns(2)
    start_date = col1.date_input("开始日期", value=None, key="bt_start")
    end_date = col2.date_input("结束日期", value=None, key="bt_end")

# ---------------------------------------------------------------------------
# Parameter form
# ---------------------------------------------------------------------------
st.subheader("策略参数")

col_a, col_b = st.columns(2)

with col_a:
    initial_cash = st.number_input(
        "初始资金", value=300_000.0, min_value=1.0, step=10_000.0, format="%.0f",
    )
    buy_threshold = st.slider(
        "买入溢价率阈值", min_value=0.00, max_value=0.10,
        value=0.02, step=0.001, format="%.3f",
    )
    liquidity_ratio = st.slider(
        "流动性比例", min_value=0.0, max_value=1.0,
        value=0.1, step=0.01, format="%.2f",
    )
    commission_rate = st.number_input(
        "佣金费率", value=0.0003, min_value=0.0, step=0.0001, format="%.4f",
    )

with col_b:
    risk_mode = st.selectbox("风险模式", ["fixed", "infinite"], index=0)
    use_ma5_liquidity = st.checkbox("使用 MA5 流动性", value=True)
    risk_free_rate = st.number_input(
        "无风险利率", value=0.02, min_value=0.0, step=0.005, format="%.4f",
    )

# ---------------------------------------------------------------------------
# Run button
# ---------------------------------------------------------------------------
st.divider()

if not tickers:
    st.info("请在左侧选择至少一个标的")
    st.stop()

if st.button("运行回测", type="primary", use_container_width=True):
    config = BacktestConfig(
        initial_cash=initial_cash,
        buy_threshold=buy_threshold,
        liquidity_ratio=liquidity_ratio,
        commission_rate=commission_rate,
        risk_mode=risk_mode,
        use_ma5_liquidity=use_ma5_liquidity,
        risk_free_rate=risk_free_rate,
    )
    engine = BacktestEngine(
        config=config,
        strategy=SimpleLOFStrategy(),
        data_loader=loader,
    )

    with st.spinner("回测运行中..."):
        result = engine.run(
            tickers=tickers,
            start_date=str(start_date) if start_date else None,
            end_date=str(end_date) if end_date else None,
        )

    st.session_state["backtest_result"] = result
    st.session_state["backtest_tickers"] = tickers
    st.session_state["backtest_data_dir"] = data_dir

    st.success("回测完成！请切换到 **回测结果分析** 页面查看结果。")
    st.markdown(f"```\n{result}\n```")
