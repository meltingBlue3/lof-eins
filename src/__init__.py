"""
LOF Fund Arbitrage Backtesting System

A high-fidelity test data generator and backtesting framework for LOF fund arbitrage.
"""

__version__ = "0.1.0"

from src.config import BacktestConfig
from src.data.loader import DataLoader
from src.engine import Account, BacktestEngine, BacktestResult
from src.strategy import BaseStrategy, Signal, SimpleLOFStrategy

__all__ = [
    'BacktestConfig',
    'DataLoader',
    'Account',
    'BacktestEngine',
    'BacktestResult',
    'BaseStrategy',
    'Signal',
    'SimpleLOFStrategy',
]