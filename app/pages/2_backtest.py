"""Page 2: 回测参数调整 + 运行"""

import streamlit as st
import yaml

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
# YAML config loader
# ---------------------------------------------------------------------------
st.subheader("配置导入")

cfg_col1, cfg_col2 = st.columns(2)

with cfg_col1:
    uploaded_file = st.file_uploader("导入配置文件 (YAML)", type=["yaml", "yml"])
    if uploaded_file is not None:
        try:
            uploaded_data = yaml.safe_load(uploaded_file.read())
            if uploaded_data:
                for key in ["initial_cash", "buy_threshold", "liquidity_ratio",
                            "commission_rate", "risk_mode", "use_ma5_liquidity",
                            "risk_free_rate"]:
                    if key in uploaded_data:
                        st.session_state[f"param_{key}"] = uploaded_data[key]
                st.info(f"已加载上传配置: {', '.join(k for k in uploaded_data if not k.startswith('#'))}")
        except Exception as e:
            st.error(f"YAML 解析失败: {e}")

with cfg_col2:
    default_config_path = Path(_root) / "configs" / "backtest.yaml"
    if st.button("加载默认配置", disabled=not default_config_path.exists()):
        try:
            default_cfg = BacktestConfig.from_yaml(default_config_path)
            st.session_state["param_initial_cash"] = default_cfg.initial_cash
            st.session_state["param_buy_threshold"] = default_cfg.buy_threshold
            st.session_state["param_liquidity_ratio"] = default_cfg.liquidity_ratio
            st.session_state["param_commission_rate"] = default_cfg.commission_rate
            st.session_state["param_risk_mode"] = default_cfg.risk_mode
            st.session_state["param_use_ma5_liquidity"] = default_cfg.use_ma5_liquidity
            st.session_state["param_risk_free_rate"] = default_cfg.risk_free_rate
            st.info("已加载默认配置 (configs/backtest.yaml)")
        except Exception as e:
            st.error(f"加载默认配置失败: {e}")

# ---------------------------------------------------------------------------
# Parameter form
# ---------------------------------------------------------------------------
st.subheader("策略参数")

col_a, col_b = st.columns(2)

with col_a:
    initial_cash = st.number_input(
        "初始资金",
        value=st.session_state.get("param_initial_cash", 300_000.0),
        min_value=1.0,
        step=10_000.0,
        format="%.0f",
        help="回测起始资金，单位：人民币",
    )
    buy_threshold = st.slider(
        "买入溢价率阈值",
        min_value=0.00,
        max_value=0.10,
        value=st.session_state.get("param_buy_threshold", 0.02),
        step=0.001,
        format="%.3f",
        help="溢价率超过此值触发买入信号。例：0.02 = 2%",
    )
    liquidity_ratio = st.slider(
        "流动性比例",
        min_value=0.0,
        max_value=1.0,
        value=st.session_state.get("param_liquidity_ratio", 0.1),
        step=0.01,
        format="%.2f",
        help="每日可交易量占成交量的比例。越高=假设越好的流动性",
    )
    commission_rate = st.number_input(
        "佣金费率",
        value=st.session_state.get("param_commission_rate", 0.0003),
        min_value=0.0,
        step=0.0001,
        format="%.4f",
        help="卖出交易佣金费率。例：0.0003 = 万三",
    )

with col_b:
    risk_mode_options = ["fixed", "infinite"]
    risk_mode_default = st.session_state.get("param_risk_mode", "fixed")
    risk_mode_index = risk_mode_options.index(risk_mode_default) if risk_mode_default in risk_mode_options else 0
    risk_mode = st.selectbox(
        "风险模式",
        risk_mode_options,
        index=risk_mode_index,
        help="fixed=受资金约束, infinite=忽略资金限制(理想化测试)",
    )
    use_ma5_liquidity = st.checkbox(
        "使用 MA5 流动性",
        value=st.session_state.get("param_use_ma5_liquidity", True),
        help="勾选后使用5日均量作为流动性基准，更保守",
    )
    risk_free_rate = st.number_input(
        "无风险利率",
        value=st.session_state.get("param_risk_free_rate", 0.02),
        min_value=0.0,
        step=0.005,
        format="%.4f",
        help="夏普比率计算用的无风险利率",
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
    st.session_state["backtest_config"] = config

    st.success("回测完成！")

    # Summary metric cards
    st.subheader("回测概览")
    m_cols = st.columns(5)
    m_cols[0].metric("总收益率", f"{result.total_return:.2%}")
    m_cols[1].metric("年化收益率", f"{result.annualized_return:.2%}")
    m_cols[2].metric("最大回撤", f"{result.max_drawdown:.2%}")
    m_cols[3].metric("夏普比率", f"{result.sharpe_ratio:.2f}")
    m_cols[4].metric("交易次数", result.num_trades)

    st.info("切换到左侧 **回测结果分析** 页面查看详细图表和交易记录")
