"""
Simple LOF arbitrage strategy implementation.
"""

from typing import Dict, List

import pandas as pd

from src.config import BacktestConfig
from src.strategy.base import BaseStrategy, Signal


class SimpleLOFStrategy(BaseStrategy):
    """Simple LOF premium arbitrage strategy.
    
    Strategy Logic:
    - SELL: If holding any position, sell all immediately (clearance ASAP).
    - BUY: If premium_rate > buy_threshold AND daily_limit > 0, buy maximum possible.
    
    This strategy prioritizes position clearance over new entries.
    """
    
    def generate_signals(
        self,
        row: pd.Series,
        positions: Dict[str, float],
        config: BacktestConfig
    ) -> List[Signal]:
        """Generate buy/sell signals based on premium rate.
        
        Args:
            row: Current bar data with ticker, premium_rate, daily_limit, etc.
            positions: Current holdings as {ticker: shares}.
            config: Backtest configuration containing buy_threshold.
            
        Returns:
            List of Signal objects. SELL signals come first, then BUY signals.
        """
        signals: List[Signal] = []
        ticker = str(row['ticker']) if 'ticker' in row.index else row.name
        
        # SELL: If we have positions, sell all
        current_shares = positions.get(ticker, 0.0)
        if current_shares > 0:
            signals.append(Signal(
                action='sell',
                ticker=ticker,
                amount=float('inf')  # Sell all
            ))
        
        # BUY: If premium_rate exceeds threshold and subscription is allowed
        premium_rate = row['premium_rate']
        daily_limit = row['daily_limit']
        
        if premium_rate > config.buy_threshold and daily_limit > 0:
            signals.append(Signal(
                action='buy',
                ticker=ticker,
                amount=float('inf')  # Buy maximum possible
            ))
        
        return signals
