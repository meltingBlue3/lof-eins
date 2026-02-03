"""
Data module for LOF backtesting system.

Includes data loading and mock data generation capabilities.
"""

from .loader import DataLoader
from .generator import MockConfig, generate_mock_data

__all__ = ["DataLoader", "MockConfig", "generate_mock_data"]
