"""
Strategy module for LOF Backtesting Engine.

Provides base strategy interface and concrete implementations.

LOF回测引擎策略模块。

提供基础策略接口和具体实现。
"""

from src.strategy.base import BaseStrategy, Signal
from src.strategy.simple_lof import SimpleLOFStrategy

__all__ = ["BaseStrategy", "Signal", "SimpleLOFStrategy"]
