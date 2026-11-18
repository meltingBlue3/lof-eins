"""Shared helpers for the Streamlit app: cached loaders and chart builders.

Streamlit 应用的共享辅助函数：缓存的数据加载器和图表构建器。
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# Ensure project root is on sys.path so `from src import ...` works  # 确保项目根目录在 sys.path 中，以便 `from src import ...` 正常工作
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src import DataLoader


# ---------------------------------------------------------------------------
# Cached data helpers  # 缓存数据辅助函数
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
    """Load ticker data bundle, returning only the DataFrame (for charts).

    加载标的代码数据包，仅返回 DataFrame（用于图表）。
    """
    loader = get_data_loader(data_dir)
    bundle = loader.load_bundle(ticker, start_date=start_date, end_date=end_date)
    return bundle.df


# ---------------------------------------------------------------------------
# Unified chart theme  # 统一图表主题
# ---------------------------------------------------------------------------


def _apply_chart_theme(fig: go.Figure) -> go.Figure:
    """Apply consistent theme to all charts for Chinese character support.
    为所有图表应用统一主题，以支持中文字符显示。
    """
    fig.update_layout(
        font_family="Microsoft YaHei, SimHei, sans-serif",
        margin=dict(l=60, r=30, t=50, b=40),
        hovermode="x unified",
    )
    return fig


# ---------------------------------------------------------------------------
# Chart builders  # 图表构建器
# ---------------------------------------------------------------------------


def nav_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["nav"],
            mode="lines",
            name="NAV",
        )
    )
    fig.update_layout(
        title=f"{ticker} — 净值走势",
        xaxis_title="日期",
        yaxis_title="净值",
        height=400,
    )
    return _apply_chart_theme(fig)


def ohlcv_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.03,
    )
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="K线",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["volume"],
            name="成交量",
            marker_color="rgba(100,100,200,0.5)",
        ),
        row=2,
        col=1,
    )
    fig.update_layout(
        title=f"{ticker} — K线 + 成交量",
        xaxis_rangeslider_visible=False,
        height=500,
    )
    return _apply_chart_theme(fig)


# Subscription status is a state, so it wears the status palette (never a series color),
# always with a text label in the legend and the hover.  # 申购状态是状态，用状态色，并始终配文字标签
STATUS_STYLE = {
    "open": ("可申购", "#0ca30c"),
    "limited": ("限额", "#fab219"),
    "closed": ("暂停", "#d03b3b"),
    "unknown": ("未知", "#c3c2b7"),
}
SOURCE_NAMES = {
    "change": "公告变更", "restatement": "公告重述", "overlay": "临时安排", "inferred_prior": "推断（首条公告之前）",
    "inferred_open": "推断开放（节假日公告）", "default": "无信息",
}


def status_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    """Daily subscription status as a band, and the stated limit below it (its own axis, log scale).

    每日申购状态色带，下方是公告写明的限额（单独的对数轴）。
    """
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.3, 0.7], vertical_spacing=0.08,
                        subplot_titles=("申购状态", "限额（元，对数轴；只画金额已知的限额日）"))
    source = df["status_source"].map(lambda s: SOURCE_NAMES.get(s, s))
    for status, (label, color) in STATUS_STYLE.items():
        mask = df["sub_status"] == status
        if not mask.any():
            continue
        fig.add_trace(
            go.Bar(
                x=df.index[mask],
                y=[1] * int(mask.sum()),
                name=label,
                marker_color=color,
                marker_line_width=0,
                customdata=source[mask],
                hovertemplate=f"{label}<br>来源：%{{customdata}}<extra></extra>",
            ),
            row=1,
            col=1,
        )
    limit = df["daily_limit"].where((df["sub_status"] == "limited") & (df["daily_limit"] > 0))
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=limit,
            mode="lines",
            line_shape="hv",
            line=dict(color="#6e6d66", width=2),
            name="限额",
            showlegend=False,
            hovertemplate="限额 %{y:,.0f} 元<extra></extra>",
        ),
        row=2,
        col=1,
    )
    fig.update_yaxes(visible=False, range=[0, 1], row=1, col=1)
    fig.update_yaxes(type="log", dtick=1, tickformat=",", title_text="元", row=2, col=1)
    # No weekend or holiday gaps, so the status band reads as one continuous strip  # 去掉周末和节假日空档，色带连续
    holidays = pd.bdate_range(df.index.min(), df.index.max()).difference(df.index) if len(df) else []
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]),
                                  dict(values=[d.strftime("%Y-%m-%d") for d in holidays])])
    _apply_chart_theme(fig)
    fig.update_layout(
        title=f"{ticker} — 申购状态（daily_status）",
        barmode="stack",
        bargap=0,
        height=440,
        margin=dict(t=90),
        legend=dict(orientation="h", yanchor="bottom", y=1.1, xanchor="right", x=1, traceorder="normal"),
    )
    return fig


def status_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Days per status and source, for the table view under the chart."""
    t = df.groupby(["sub_status", "status_source"]).size().rename("天数").reset_index()
    t["状态"] = t["sub_status"].map(lambda s: STATUS_STYLE.get(s, (s,))[0])
    t["来源"] = t["status_source"].map(lambda s: SOURCE_NAMES.get(s, s))
    return t[["状态", "来源", "天数"]].sort_values("天数", ascending=False).reset_index(drop=True)


def premium_chart(
    df: pd.DataFrame,
    ticker: str,
    buy_threshold: float = 0.02,
) -> go.Figure:
    fig = go.Figure()

    # Zero reference line  # 零参考线  # 零参考线
    fig.add_hline(y=0, line_color="grey", line_width=1, opacity=0.5)

    # Premium line with fill to zero  # 溢价值曲线，填充到零基准线  # 溢价率折线并填充至零
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["premium_rate"],
            mode="lines",
            name="溢价率",
            fill="tozeroy",
            fillcolor="rgba(0,176,80,0.15)",
            line=dict(color="rgba(0,176,80,0.8)"),
        )
    )

    fig.add_hline(
        y=buy_threshold,
        line_dash="dash",
        line_color="red",
        annotation_text=f"买入阈值 {buy_threshold:.2%}",
    )
    fig.update_layout(
        title=f"{ticker} — 溢价率",
        xaxis_title="日期",
        yaxis_title="溢价率",
        yaxis_tickformat=".2%",
        height=400,
    )
    return _apply_chart_theme(fig)


def equity_curve_chart(daily_perf: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=daily_perf.index,
            y=daily_perf["total_assets"],
            mode="lines",
            name="总资产",
            line=dict(color="#1f77b4"),
            hovertemplate="%{x}<br>%{y:,.0f} CNY<extra></extra>",
        )
    )

    # Drawdown shading  # 回撤阴影  # 回撤阴影
    cummax = daily_perf["total_assets"].cummax()
    drawdown = (daily_perf["total_assets"] - cummax) / cummax
    fig.add_trace(
        go.Scatter(
            x=daily_perf.index,
            y=drawdown,
            mode="lines",
            name="回撤",
            yaxis="y2",
            fill="tozeroy",
            fillcolor="rgba(255,0,0,0.1)",
            line=dict(color="rgba(255,0,0,0.4)"),
        )
    )
    fig.update_layout(
        title="权益曲线 & 回撤",
        xaxis_title="日期",
        yaxis=dict(title="总资产 (CNY)"),
        yaxis2=dict(
            title="回撤",
            overlaying="y",
            side="right",
            tickformat=".1%",
        ),
        height=500,
    )
    return _apply_chart_theme(fig)


def trade_markers_chart(
    df: pd.DataFrame,
    trade_logs: pd.DataFrame,
    ticker: str,
) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="K线",
        )
    )

    ticker_trades = (
        trade_logs[trade_logs["ticker"] == ticker]
        if not trade_logs.empty
        else trade_logs
    )
    if not ticker_trades.empty:
        buys = ticker_trades[ticker_trades["action"] == "buy"]
        sells = ticker_trades[ticker_trades["action"] == "sell"]
        if not buys.empty:
            fig.add_trace(
                go.Scatter(
                    x=buys["date"],
                    y=buys["price"],
                    mode="markers",
                    name="买入",
                    marker=dict(symbol="triangle-up", size=10, color="red"),
                )
            )
        if not sells.empty:
            fig.add_trace(
                go.Scatter(
                    x=sells["date"],
                    y=sells["price"],
                    mode="markers",
                    name="卖出",
                    marker=dict(symbol="triangle-down", size=10, color="green"),
                )
            )
    fig.update_layout(
        title=f"{ticker} — 交易标记",
        xaxis_rangeslider_visible=False,
        height=500,
    )
    return _apply_chart_theme(fig)


def pnl_by_ticker_chart(trade_logs: pd.DataFrame) -> go.Figure:
    if trade_logs.empty:
        fig = go.Figure()
        fig.update_layout(title="无交易记录")
        return _apply_chart_theme(fig)

    pnl = trade_logs.groupby("ticker")["net_amount"].sum().sort_values()
    colors = ["green" if v >= 0 else "red" for v in pnl.values]
    fig = go.Figure(
        go.Bar(
            x=pnl.index,
            y=pnl.values,
            marker_color=colors,
        )
    )
    fig.update_layout(
        title="各标的盈亏汇总",
        xaxis_title="标的",
        yaxis_title="净金额 (CNY)",
        height=400,
    )
    return _apply_chart_theme(fig)
