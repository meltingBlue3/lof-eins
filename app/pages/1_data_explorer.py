"""Page 1: LOF 数据看板 — 浏览基金行情、净值和溢价率"""

import streamlit as st

from utils import (
    get_data_loader,
    load_bundle_cached,
    nav_chart,
    ohlcv_chart,
    premium_chart,
)

st.header("LOF 数据看板")

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------
with st.sidebar:
    data_dir = st.text_input("数据目录", value="./data/mock")
    try:
        loader = get_data_loader(data_dir)
        available = loader.list_available_tickers()
    except FileNotFoundError:
        st.error(f"数据目录不存在或结构不完整: {data_dir}")
        st.stop()

    if not available:
        st.warning("该目录下未找到可用标的")
        st.stop()

    tickers = st.multiselect("选择标的", available, default=available[:1])
    col1, col2 = st.columns(2)
    start_date = col1.date_input("开始日期", value=None)
    end_date = col2.date_input("结束日期", value=None)

    buy_threshold = st.number_input(
        "溢价率买入阈值（参考线）", value=0.02, format="%.4f",
    )

if not tickers:
    st.info("请在左侧选择至少一个标的")
    st.stop()

# ---------------------------------------------------------------------------
# Render charts per ticker
# ---------------------------------------------------------------------------
for ticker in tickers:
    st.subheader(f"标的: {ticker}")
    try:
        df = load_bundle_cached(
            data_dir,
            ticker,
            start_date=str(start_date) if start_date else None,
            end_date=str(end_date) if end_date else None,
        )
    except FileNotFoundError as e:
        st.error(f"加载 {ticker} 失败: {e}")
        continue

    if df.empty:
        st.warning(f"{ticker}: 所选日期范围内无数据")
        continue

    st.plotly_chart(nav_chart(df, ticker), use_container_width=True)
    st.plotly_chart(ohlcv_chart(df, ticker), use_container_width=True)
    st.plotly_chart(premium_chart(df, ticker, buy_threshold), use_container_width=True)
    st.divider()
