import sys
from pathlib import Path

# Add project root to path  # 将项目根目录添加到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import sqlite3
import os
from src.data.loader import DataLoader

# ================= 配置 =================  # ================= Configuration =================
TICKER = "161725"  # 使用 fees.csv 中存在的 ticker
DATA_DIR = "./data/mock"
# =======================================


def verify_dataloader():
    """Verify DataLoader functionality.
    验证 DataLoader 功能。
    """
    print(f"[CHECK] Starting verification for Ticker: {TICKER} ...")

    # 1. 初始化 Loader  # 1. Initialize Loader
    loader = DataLoader(data_dir=DATA_DIR)

    # 2. 加载数据 (加载全部时间段)  # 2. Load data (load all time periods)
    # 假设你的 mock 数据生成了 2020-2024 的数据  # Assuming your mock data generated 2020-2024 data
    try:
        df = loader.load_bundle(TICKER, start_date="2020-01-01", end_date="2025-01-01")
        print(f"[OK] Data loaded successfully! Shape: {df.shape}")
    except Exception as e:
        print(f"[ERROR] Data loading failed: {e}")
        return

    # 3. 验证基础列是否存在  # 3. Verify basic columns exist
    required_cols = ["open", "close", "nav", "premium_rate", "daily_limit"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        print(f"[ERROR] Missing key columns: {missing_cols}")
    else:
        print("[OK] Key columns check passed")

    # 4. 【核心验证】限购逻辑 (SQLite -> DataFrame)  # 4. [Core Verification] Limit logic (SQLite -> DataFrame)
    # 我们先手动去 SQLite 查一条记录，看看 DataFrame 里对应日期是不是对的  # First manually query SQLite for a record, check if DataFrame date matches
    verify_limit_logic(df, TICKER)

    # 5. 【核心验证】费率逻辑 (CSV -> DataFrame/Attrs)  # 5. [Core Verification] Fee logic (CSV -> DataFrame/Attrs)
    verify_fee_logic(df, TICKER)

    # 6. 【核心验证】溢价率计算  # 6. [Core Verification] Premium rate calculation
    verify_premium_calc(df)


def verify_limit_logic(df, ticker):
    """Verify limit event logic.
    验证限购事件逻辑。
    """
    print("\n--- 验证限购逻辑 (Event -> Series) ---")
    db_path = os.path.join(DATA_DIR, "config/fund_status.db")
    conn = sqlite3.connect(db_path)

    # 找一条该 ticker 的限购记录  # Find a limit record for this ticker
    event = pd.read_sql(
        "SELECT * FROM limit_events WHERE ticker=? LIMIT 1", conn, params=(ticker,)
    )
    conn.close()

    if event.empty:
        print("[WARN] No limit events found for this ticker, skipping verification.")
        return

    # 获取记录中的信息  # Get info from the record
    start_str = event.iloc[0]["start_date"]
    end_str = event.iloc[0]["end_date"]
    limit_amount = event.iloc[0]["max_amount"]

    print(f"数据库记录: {start_str} 到 {end_str} 限购 {limit_amount}")

    # 检查 DataFrame 中对应日期的 daily_limit 是否等于 limit_amount  # Check if daily_limit in DataFrame matches limit_amount
    # 注意：我们要找这段时间内确实有行情的一天  # Note: we need to find a day with actual trading data
    mask = (df.index >= pd.to_datetime(start_str)) & (
        df.index <= pd.to_datetime(end_str)
    )
    target_rows = df.loc[mask]

    if target_rows.empty:
        print(
            "[WARN] No market data during limit period (possible holiday), cannot verify."
        )
    else:
        # 取第一天检查  # Check the first day
        actual_limit = target_rows.iloc[0]["daily_limit"]
        check_date = target_rows.index[0].date()

        if actual_limit == limit_amount:
            print(
                f"[OK] Verification passed! Date {check_date} daily_limit = {actual_limit}"
            )
        else:
            print(
                f"[ERROR] Verification failed! Date {check_date} expected {limit_amount}, got {actual_limit}"
            )

    # 顺便检查一下非限购期是不是无限 (inf)  # Also check if non-limit period is infinite (inf)
    # 找一天不在 start-end 范围内的  # Find a day outside the start-end range
    outside_mask = (df.index < pd.to_datetime(start_str)) | (
        df.index > pd.to_datetime(end_str)
    )
    if not df[outside_mask].empty:
        normal_limit = df[outside_mask].iloc[0]["daily_limit"]
        if (
            normal_limit == float("inf") or normal_limit == -1 or normal_limit > 1e10
        ):  # 兼容不同的无限表达  # Compatible with different infinity representations
            print(f"[OK] Non-limit period verification passed (Limit = {normal_limit})")
        else:
            print(f"[ERROR] Non-limit period verification failed: {normal_limit}")


def verify_fee_logic(df, ticker):
    """Verify fee logic.
    验证费率逻辑。
    """
    print("\n--- 验证费率逻辑 (CSV -> DF) ---")
    # 检查是否作为列存在，或者作为 attrs 存在  # Check if exists as column or attrs
    # 假设你的 Loader 是把费率加到了 columns 里（这是最常见做法）  # Assuming your Loader added fees to columns (most common approach)

    # 读取 CSV 核对  # Read CSV to verify
    csv_path = os.path.join(DATA_DIR, "config/fees.csv")
    fees_csv = pd.read_csv(csv_path)
    target_fee = fees_csv[fees_csv["ticker"] == int(ticker)].iloc[
        0
    ]  # 注意 ticker 类型可能是 int 或 str  # Note: ticker type might be int or str

    expected_redeem = target_fee["redeem_fee_7d"]

    # 检查 DataFrame  # Check DataFrame
    if "redeem_fee_7d" in df.columns:
        actual_val = df["redeem_fee_7d"].iloc[0]
        if abs(actual_val - expected_redeem) < 1e-6:
            print(f"[OK] Fee column verification passed: {actual_val}")
        else:
            print(
                f"[ERROR] Fee value mismatch: expected {expected_redeem}, got {actual_val}"
            )
    elif (
        hasattr(df, "attrs") and "redeem_fee_7d" in df.attrs
    ):  # 或者是属性  # Or as attribute
        actual_val = df.attrs["redeem_fee_7d"]
        if abs(actual_val - expected_redeem) < 1e-6:
            print(f"[OK] Fee attrs verification passed: {actual_val}")
        else:
            print(
                f"[ERROR] Fee value mismatch: expected {expected_redeem}, got {actual_val}"
            )
    else:
        print("[ERROR] Fee info not found in DataFrame columns or attrs")


def verify_premium_calc(df):
    """Verify premium rate calculation.
    验证溢价率计算。
    """
    print("\n--- 验证溢价率计算 ---")
    # 随机抽查一行  # Randomly check a row
    sample = df.iloc[10]
    calc_premium = (sample["close"] - sample["nav"]) / sample["nav"]

    if abs(calc_premium - sample["premium_rate"]) < 1e-6:
        print(f"[OK] Calculation formula correct: {sample['premium_rate']:.4f}")
    else:
        print(
            f"[ERROR] Calculation formula wrong! Data: {sample['premium_rate']}, Recalculated: {calc_premium}"
        )


if __name__ == "__main__":
    verify_dataloader()
