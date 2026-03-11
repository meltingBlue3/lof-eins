"""
LOF Mock Data Generator

LOF模拟数据生成器

A high-fidelity test data generator for LOF fund arbitrage backtesting system.

用于LOF基金套利回测系统的高保真测试数据生成器。
"""

from .config import MockConfig
from .main import generate_mock_data

__all__ = ["MockConfig", "generate_mock_data"]
