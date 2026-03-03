"""LOF 套利回测系统 — Streamlit 入口"""

import streamlit as st
from pathlib import Path

st.set_page_config(
    page_title="LOF 套利回测系统",
    page_icon="📈",
    layout="wide",
)

st.title("LOF 套利回测系统")
st.markdown("基于溢价率的 LOF 基金套利策略回测与分析平台")

st.divider()

# ---------------------------------------------------------------------------
# 3-step workflow overview
# ---------------------------------------------------------------------------
st.subheader("使用流程")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### Step 1: 浏览数据")
    st.markdown(
        "查看基金行情、净值走势和溢价率变化。"
        "了解标的的历史表现，为回测参数选择提供依据。"
    )
    st.page_link("pages/1_data_explorer.py", label="前往数据看板", icon="📊")

with col2:
    st.markdown("### Step 2: 配置回测")
    st.markdown(
        "设置回测参数（资金、阈值、佣金等），"
        "选择标的和日期范围，一键运行回测。"
    )
    st.page_link("pages/2_backtest.py", label="前往回测配置", icon="⚙️")

with col3:
    st.markdown("### Step 3: 分析结果")
    st.markdown(
        "查看回测绩效指标、权益曲线、交易标记和逐笔交易记录，"
        "评估策略表现。"
    )
    st.page_link("pages/3_backtest_results.py", label="前往结果分析", icon="📈")

st.divider()

# ---------------------------------------------------------------------------
# Quick start guide
# ---------------------------------------------------------------------------
st.subheader("快速开始")

st.markdown(
    """
- **Mock 数据测试：** 默认数据目录为 `./data/mock`，包含模拟数据，可直接体验完整流程。
- **实盘数据回测：** 如已下载实盘数据，将数据目录切换为 `./data/real_all_lof`。
- **自定义配置：** 可在回测页面上传 YAML 配置文件，或加载 `configs/backtest.yaml` 默认配置。
"""
)

# ---------------------------------------------------------------------------
# System status
# ---------------------------------------------------------------------------
st.subheader("系统状态")

mock_path = Path("./data/mock")
real_path = Path("./data/real_all_lof")
config_path = Path("./configs/backtest.yaml")

status_col1, status_col2, status_col3 = st.columns(3)

with status_col1:
    if mock_path.exists():
        st.success("Mock 数据目录: 可用")
    else:
        st.warning("Mock 数据目录: 未找到")

with status_col2:
    if real_path.exists():
        st.success("实盘数据目录: 可用")
    else:
        st.info("实盘数据目录: 未找到")

with status_col3:
    if config_path.exists():
        st.success("默认配置文件: 可用")
    else:
        st.warning("默认配置文件: 未找到")
