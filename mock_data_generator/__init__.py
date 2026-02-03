"""
LOF Mock Data Generator

A high-fidelity test data generator for LOF fund arbitrage backtesting system.
"""

from .config import MockConfig
from .main import generate_mock_data

__all__ = ["MockConfig", "generate_mock_data"]
