import logging

# 在运行回测前，加上这一段
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("backtest_execution.log", mode='w', encoding='utf-8'), # 写入文件
        logging.StreamHandler() # 同时打印到控制台
    ]
)
from src import BacktestConfig, BacktestEngine, SimpleLOFStrategy, DataLoader

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'  # 简化格式
)

print("=" * 60)
print("开始回测...")
print("=" * 60)

config = BacktestConfig(
    initial_cash=300_000.0,
    buy_threshold=0.02,
    liquidity_ratio=0.1
)

engine = BacktestEngine(
    config=config,
    strategy=SimpleLOFStrategy(),
    data_loader=DataLoader()
)

# # 单标的回测（向后兼容）
# print("\n--- 单标的回测 (161005) ---")
# result_single = engine.run(tickers='161005')
# print(result_single)

# 多标的回测（新功能）
print("\n--- 多标的回测 (统一资金池 + 溢价率排序买入) ---")
all_tickers = ['161005', '162411', '161725', '501018', '160216']
result_multi = engine.run(tickers=all_tickers)
print(result_multi)

# 显示交易日志概览
if not result_multi.trade_logs.empty:
    print("\n--- 交易日志 (前 20 条) ---")
    print(result_multi.trade_logs.head(20).to_string())
    
    # 统计每个标的的交易次数
    print("\n--- 各标的交易统计 ---")
    trade_summary = result_multi.trade_logs.groupby(['ticker', 'action']).size().unstack(fill_value=0)
    print(trade_summary)