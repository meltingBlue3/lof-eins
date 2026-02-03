import pandas as pd
import sqlite3
import os
from data_loader import DataLoader  # 假设你的类在 data_loader.py 中

# ================= 配置 =================
TICKER = '161005'  # 确保这个 ticker 在你的 mock 数据里存在
DATA_DIR = './data/mock'
# =======================================

def verify_dataloader():
    print(f"🔍 开始验证 Ticker: {TICKER} ...")
    
    # 1. 初始化 Loader
    loader = DataLoader(data_dir=DATA_DIR)
    
    # 2. 加载数据 (加载全部时间段)
    # 假设你的 mock 数据生成了 2020-2024 的数据
    try:
        df = loader.load_bundle(TICKER, start_date='2020-01-01', end_date='2025-01-01')
        print(f"✅ 数据加载成功! Shape: {df.shape}")
    except Exception as e:
        print(f"❌ 数据加载失败: {e}")
        return

    # 3. 验证基础列是否存在
    required_cols = ['open', 'close', 'nav', 'premium_rate', 'daily_limit']
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        print(f"❌ 缺失关键列: {missing_cols}")
    else:
        print("✅ 关键列检查通过")

    # 4. 【核心验证】限购逻辑 (SQLite -> DataFrame)
    # 我们先手动去 SQLite 查一条记录，看看 DataFrame 里对应日期是不是对的
    verify_limit_logic(df, TICKER)

    # 5. 【核心验证】费率逻辑 (CSV -> DataFrame/Attrs)
    verify_fee_logic(df, TICKER)

    # 6. 【核心验证】溢价率计算
    verify_premium_calc(df)

def verify_limit_logic(df, ticker):
    print("\n--- 验证限购逻辑 (Event -> Series) ---")
    db_path = os.path.join(DATA_DIR, 'config/fund_status.db')
    conn = sqlite3.connect(db_path)
    
    # 找一条该 ticker 的限购记录
    event = pd.read_sql(f"SELECT * FROM limit_events WHERE ticker='{ticker}' LIMIT 1", conn)
    conn.close()
    
    if event.empty:
        print("⚠️ 该 Ticker 在数据库中没有限购记录，跳过此项验证。")
        return

    # 获取记录中的信息
    start_str = event.iloc[0]['start_date']
    end_str = event.iloc[0]['end_date']
    limit_amount = event.iloc[0]['max_amount']
    
    print(f"数据库记录: {start_str} 到 {end_str} 限购 {limit_amount}")
    
    # 检查 DataFrame 中对应日期的 daily_limit 是否等于 limit_amount
    # 注意：我们要找这段时间内确实有行情的一天
    mask = (df.index >= pd.to_datetime(start_str)) & (df.index <= pd.to_datetime(end_str))
    target_rows = df.loc[mask]
    
    if target_rows.empty:
        print("⚠️ 限购期间没有行情数据（可能是假期），无法验证。")
    else:
        # 取第一天检查
        actual_limit = target_rows.iloc[0]['daily_limit']
        check_date = target_rows.index[0].date()
        
        if actual_limit == limit_amount:
            print(f"✅ 验证通过! 日期 {check_date} 的 daily_limit 准确为 {actual_limit}")
        else:
            print(f"❌ 验证失败! 日期 {check_date} 应该是 {limit_amount}, 但实际是 {actual_limit}")
            
    # 顺便检查一下非限购期是不是无限 (inf)
    # 找一天不在 start-end 范围内的
    outside_mask = (df.index < pd.to_datetime(start_str)) | (df.index > pd.to_datetime(end_str))
    if not df[outside_mask].empty:
        normal_limit = df[outside_mask].iloc[0]['daily_limit']
        if normal_limit == float('inf') or normal_limit == -1 or normal_limit > 1e10: # 兼容不同的无限表达
            print(f"✅ 非限购期验证通过 (Limit = {normal_limit})")
        else:
            print(f"❌ 非限购期验证异常: {normal_limit}")

def verify_fee_logic(df, ticker):
    print("\n--- 验证费率逻辑 (CSV -> DF) ---")
    # 检查是否作为列存在，或者作为 attrs 存在
    # 假设你的 Loader 是把费率加到了 columns 里（这是最常见做法）
    
    # 读取 CSV 核对
    csv_path = os.path.join(DATA_DIR, 'config/fees.csv')
    fees_csv = pd.read_csv(csv_path)
    target_fee = fees_csv[fees_csv['ticker'] == int(ticker)].iloc[0] # 注意 ticker 类型可能是 int 或 str
    
    expected_redeem = target_fee['redeem_fee_7d']
    
    # 检查 DataFrame
    if 'redeem_fee_7d' in df.columns:
        actual_val = df['redeem_fee_7d'].iloc[0]
        if abs(actual_val - expected_redeem) < 1e-6:
            print(f"✅ 费率列验证通过: {actual_val}")
        else:
            print(f"❌ 费率数值不匹配: 期望 {expected_redeem}, 实际 {actual_val}")
    elif hasattr(df, 'attrs') and 'redeem_fee_7d' in df.attrs: # 或者是属性
        actual_val = df.attrs['redeem_fee_7d']
        print(f"✅ 费率属性验证通过: {actual_val}")
    else:
        print("❌ 未在 DataFrame 列或 attrs 中找到费率信息")

def verify_premium_calc(df):
    print("\n--- 验证溢价率计算 ---")
    # 随机抽查一行
    sample = df.iloc[10]
    calc_premium = (sample['close'] - sample['nav']) / sample['nav']
    
    if abs(calc_premium - sample['premium_rate']) < 1e-6:
        print(f"✅ 计算公式正确: {sample['premium_rate']:.4f}")
    else:
        print(f"❌ 计算公式错误! 数据中: {sample['premium_rate']}, 重新计算: {calc_premium}")

if __name__ == "__main__":
    verify_dataloader()