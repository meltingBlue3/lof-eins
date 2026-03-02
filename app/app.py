"""LOF 套利回测系统 — Streamlit 入口"""

import streamlit as st

st.set_page_config(
    page_title="LOF 套利回测系统",
    page_icon="📈",
    layout="wide",
)

st.title("LOF 套利回测系统")
st.markdown(
    """
    👈 使用左侧导航栏切换页面：

    - **LOF 数据看板** — 浏览基金行情、净值和溢价率
    - **回测参数调整 + 运行** — 配置策略参数并启动回测
    - **回测结果分析** — 查看回测绩效、交易记录和权益曲线
    """
)
