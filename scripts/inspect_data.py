import sys
from pathlib import Path

# Add project root to path  # 将项目根目录添加到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import sqlite3
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os

# ================= 配置项 / Configuration =================
# 随便选一个你生成了数据的 Ticker / Choose any ticker you have generated data for
TICKER = "162411"
DATA_DIR = "./data/mock"
# ==========================================================/ ========================================


def load_data(ticker):
    """Load market and NAV data for a ticker.

    加载指定基金代码的行情和净值数据。

    Args:
        ticker: Fund ticker symbol / 基金代码

    Returns:
        DataFrame with merged market and NAV data, plus premium_rate
        包含合并的行情和净值数据以及溢价率的DataFrame
    """
    # 1. 读取行情 (Price) / 1. Read market data
    price_path = f"{DATA_DIR}/market/{ticker}.parquet"
    if not os.path.exists(price_path):
        raise FileNotFoundError(f"找不到行情文件: {price_path}")
    df_price = pd.read_parquet(price_path)
    print(f"行情数据样例:\n{df_price}\n")

    # 2. 读取净值 (NAV) / 2. Read NAV data
    nav_path = f"{DATA_DIR}/nav/{ticker}.parquet"
    if not os.path.exists(nav_path):
        raise FileNotFoundError(f"找不到净值文件: {nav_path}")
    df_nav = pd.read_parquet(nav_path)
    print(f"净值数据样例:\n{df_nav}\n")

    # 合并数据
    df = pd.merge(df_price, df_nav, left_index=True, right_index=True, how="inner")

    # 计算溢价率
    df["premium_rate"] = (df["close"] - df["nav"]) / df["nav"]
    return df


def load_limits(ticker):
    """Load purchase limit events from SQLite database.

    从SQLite数据库加载申购限额事件。

    Args:
        ticker: Fund ticker symbol / 基金代码

    Returns:
        DataFrame with limit events, or empty DataFrame if no limits found
        包含限额事件的DataFrame，如未找到则返回空DataFrame
    """
    # 3. 读取限购事件 (SQLite) / 3. Read limit events from SQLite
    db_path = f"{DATA_DIR}/config/fund_status.db"
    if not os.path.exists(db_path):
        print("警告: 找不到限购数据库")
        return pd.DataFrame()

    conn = sqlite3.connect(db_path)
    query = "SELECT * FROM limit_events WHERE ticker = ?"
    df_limits = pd.read_sql(query, conn, params=(str(ticker),))
    conn.close()

    # 转换日期格式 / Convert date format
    if not df_limits.empty:
        df_limits["start_date"] = pd.to_datetime(df_limits["start_date"])
        df_limits["end_date"] = pd.to_datetime(df_limits["end_date"])

    return df_limits


def plot_dashboard(ticker):
    """Create interactive visualization dashboard for a ticker.

    为指定基金创建交互式可视化仪表板。

    Args:
        ticker: Fund ticker symbol to visualize / 要可视化的基金代码
    """
    df = load_data(ticker)
    df_limits = load_limits(ticker)

    # 创建子图: 3行1列
    # Row 1: 价格 vs 净值
    # Row 2: 溢价率
    # Row 3: 成交量
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=(f"Price vs NAV ({ticker})", "Premium Rate", "Volume"),
        row_heights=[0.5, 0.3, 0.2],
    )

    # --- Plot 1: Price & NAV ---
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["close"],
            name="Close Price",
            line=dict(color="blue", width=1),
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["nav"],
            name="NAV",
            line=dict(color="orange", width=2, dash="dash"),
        ),
        row=1,
        col=1,
    )

    # --- Plot 2: Premium Rate ---
    # 溢价部分用红色，折价部分用绿色
    colors = ["red" if v > 0 else "green" for v in df["premium_rate"]]
    fig.add_trace(
        go.Bar(
            x=df.index, y=df["premium_rate"], name="Premium Rate", marker_color=colors
        ),
        row=2,
        col=1,
    )

    # 添加 15% 阈值线 (我们之前设定的触发限购线)
    fig.add_hline(
        y=0.15, line_dash="dot", annotation_text="Trigger Threshold (15%)", row=2, col=1
    )

    # --- Plot 3: Volume ---
    fig.add_trace(
        go.Bar(x=df.index, y=df["volume"], name="Volume", marker_color="grey"),
        row=3,
        col=1,
    )

    # --- Highlight Limits (限购区域) --- / Highlight limit regions
    # 在所有子图上把限购的时间段标红 / Highlight limit periods on all subplots
    if not df_limits.empty:
        for _, row in df_limits.iterrows():
            # 只有当限购额很小（比如<1000）时才高亮，过滤掉正常的限额 / Only highlight when limit is small (e.g., <1000), filter out normal limits
            if row["max_amount"] < 5000:
                # 在第一个子图添加红色背景区域 / Add red background region to first subplot
                fig.add_vrect(
                    x0=row["start_date"],
                    x1=row["end_date"],
                    fillcolor="red",
                    opacity=0.15,
                    layer="below",
                    line_width=0,
                    annotation_text=f"Limit: {row['max_amount']}",
                    annotation_position="top left",
                )

    # --- Layout ---
    fig.update_layout(
        height=900, title_text=f"LOF Simulation Check: {ticker}", hovermode="x unified"
    )
    fig.show()


if __name__ == "__main__":
    try:
        # 如果不知道生成了哪些ticker，可以先列出文件夹看看 / List files if you don't know which tickers were generated
        files = os.listdir(f"{DATA_DIR}/market")
        print(f"检测到的 Mock 数据文件: {files}")

        # 默认画第一个 / Default to first one
        first_ticker = "161005"
        print(f"正在绘图: {first_ticker} ...")  # Plotting: {first_ticker} ...
        plot_dashboard(first_ticker)
    except Exception as e:
        print(f"发生错误: {e}")
