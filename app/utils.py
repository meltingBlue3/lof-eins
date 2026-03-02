"""Shared helpers for the Streamlit app: cached loaders and chart builders."""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# Ensure project root is on sys.path so `from src import ...` works
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src import DataLoader


# ---------------------------------------------------------------------------
# Cached data helpers
# ---------------------------------------------------------------------------

@st.cache_resource
def get_data_loader(data_dir: str = "./data/mock") -> DataLoader:
    return DataLoader(data_dir=data_dir)


@st.cache_data(ttl=600)
def load_bundle_cached(
    data_dir: str,
    ticker: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Load ticker data bundle, returning only the DataFrame (for charts)."""
    loader = get_data_loader(data_dir)
    bundle = loader.load_bundle(ticker, start_date=start_date, end_date=end_date)
    return bundle.df


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def nav_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.index, y=df["nav"], mode="lines", name="NAV",
    ))
    fig.update_layout(
        title=f"{ticker} — 净值走势",
        xaxis_title="日期",
        yaxis_title="净值",
        height=400,
    )
    return fig


def ohlcv_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.7, 0.3], vertical_spacing=0.03,
    )
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        name="K线",
    ), row=1, col=1)
    fig.add_trace(go.Bar(
        x=df.index, y=df["volume"], name="成交量",
        marker_color="rgba(100,100,200,0.5)",
    ), row=2, col=1)
    fig.update_layout(
        title=f"{ticker} — K线 + 成交量",
        xaxis_rangeslider_visible=False,
        height=500,
    )
    return fig


def premium_chart(
    df: pd.DataFrame, ticker: str, buy_threshold: float = 0.02,
) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.index, y=df["premium_rate"], mode="lines", name="溢价率",
    ))
    fig.add_hline(
        y=buy_threshold, line_dash="dash", line_color="red",
        annotation_text=f"买入阈值 {buy_threshold:.2%}",
    )
    fig.update_layout(
        title=f"{ticker} — 溢价率",
        xaxis_title="日期",
        yaxis_title="溢价率",
        yaxis_tickformat=".2%",
        height=400,
    )
    return fig


def equity_curve_chart(daily_perf: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily_perf.index,
        y=daily_perf["total_assets"],
        mode="lines",
        name="总资产",
        line=dict(color="#1f77b4"),
    ))

    # Drawdown shading
    cummax = daily_perf["total_assets"].cummax()
    drawdown = (daily_perf["total_assets"] - cummax) / cummax
    fig.add_trace(go.Scatter(
        x=daily_perf.index,
        y=drawdown,
        mode="lines",
        name="回撤",
        yaxis="y2",
        fill="tozeroy",
        fillcolor="rgba(255,0,0,0.1)",
        line=dict(color="rgba(255,0,0,0.4)"),
    ))
    fig.update_layout(
        title="权益曲线 & 回撤",
        xaxis_title="日期",
        yaxis=dict(title="总资产 (¥)"),
        yaxis2=dict(
            title="回撤",
            overlaying="y",
            side="right",
            tickformat=".1%",
        ),
        height=500,
    )
    return fig


def trade_markers_chart(
    df: pd.DataFrame,
    trade_logs: pd.DataFrame,
    ticker: str,
) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        name="K线",
    ))

    ticker_trades = trade_logs[trade_logs["ticker"] == ticker] if not trade_logs.empty else trade_logs
    if not ticker_trades.empty:
        buys = ticker_trades[ticker_trades["action"] == "buy"]
        sells = ticker_trades[ticker_trades["action"] == "sell"]
        if not buys.empty:
            fig.add_trace(go.Scatter(
                x=buys["date"], y=buys["price"],
                mode="markers", name="买入",
                marker=dict(symbol="triangle-up", size=10, color="red"),
            ))
        if not sells.empty:
            fig.add_trace(go.Scatter(
                x=sells["date"], y=sells["price"],
                mode="markers", name="卖出",
                marker=dict(symbol="triangle-down", size=10, color="green"),
            ))
    fig.update_layout(
        title=f"{ticker} — 交易标记",
        xaxis_rangeslider_visible=False,
        height=500,
    )
    return fig


def pnl_by_ticker_chart(trade_logs: pd.DataFrame) -> go.Figure:
    if trade_logs.empty:
        fig = go.Figure()
        fig.update_layout(title="无交易记录")
        return fig

    pnl = trade_logs.groupby("ticker")["net_amount"].sum().sort_values()
    colors = ["green" if v >= 0 else "red" for v in pnl.values]
    fig = go.Figure(go.Bar(
        x=pnl.index, y=pnl.values,
        marker_color=colors,
    ))
    fig.update_layout(
        title="各标的盈亏汇总",
        xaxis_title="标的",
        yaxis_title="净金额 (¥)",
        height=400,
    )
    return fig
