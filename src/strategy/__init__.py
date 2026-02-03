"""
Strategy module for LOF Backtesting Engine.

Provides base strategy interface and concrete implementations.
"""

from src.strategy.base import BaseStrategy, Signal
from src.strategy.simple_lof import SimpleLOFStrategy

__all__ = ['BaseStrategy', 'Signal', 'SimpleLOFStrategy']
