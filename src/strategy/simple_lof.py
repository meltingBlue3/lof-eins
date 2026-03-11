"""
Simple LOF arbitrage strategy implementation.

LOF简单套利策略实现。
"""

from typing import Dict, List

import pandas as pd

from src.config import BacktestConfig
from src.strategy.base import BaseStrategy, Signal


class SimpleLOFStrategy(BaseStrategy):
    """Simple LOF premium arbitrage strategy.

    简单LOF溢价套利策略。

    Strategy Logic:
    - SELL: If holding any position, sell all immediately (clearance ASAP).
    - BUY: If premium_rate > buy_threshold AND daily_limit > 0, buy maximum possible.

    策略逻辑：
    - 卖出：如果持有任何仓位，立即全部卖出（尽快清仓）
    - 买入：如果溢价率 > 买入阈值 且 申购限额 > 0，买入最大可能金额

    This strategy prioritizes position clearance over new entries.
    此策略优先清仓而非建仓。
    """

    def generate_signals(
        self, row: pd.Series, positions: Dict[str, float], config: BacktestConfig
    ) -> List[Signal]:
        """Generate buy/sell signals based on premium rate.

        根据溢价率生成买入/卖出信号。

        Args:
            row: Current bar data with ticker, premium_rate, daily_limit, etc.
                 当前K线数据，包含ticker、premium_rate、daily_limit等
            positions: Current holdings as {ticker: shares}. / 当前持仓 {基金代码: 份额}
            config: Backtest configuration containing buy_threshold. / 回测配置（包含买入阈值）

        Returns:
            List of Signal objects. SELL signals come first, then BUY signals.
            Signal对象列表。卖出信号优先，然后是买入信号。
        """
        signals: List[Signal] = []
        ticker = str(row["ticker"]) if "ticker" in row.index else row.name

        # SELL: If we have positions, sell all  # 卖出：如果有持仓，全部卖出
        current_shares = positions.get(ticker, 0.0)
        if current_shares > 0:
            signals.append(
                Signal(
                    action="sell",
                    ticker=ticker,
                    amount=float("inf"),  # Sell all  # 全部卖出
                )
            )

        # BUY: If premium_rate exceeds threshold and subscription is allowed
        # 买入：如果溢价率超过阈值且允许申购
        premium_rate = row["premium_rate"]
        daily_limit = row["daily_limit"]

        if premium_rate > config.buy_threshold and daily_limit > 0:
            signals.append(
                Signal(
                    action="buy",
                    ticker=ticker,
                    amount=float("inf"),  # Buy maximum possible  # 买入最大可能金额
                )
            )

        return signals
