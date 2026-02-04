"""
Data module for LOF backtesting system.

Includes data loading, mock data generation, and real data download capabilities.
"""

from .loader import DataLoader
from .generator import MockConfig, generate_mock_data

# Conditional import for downloader (requires jqdatasdk)
try:
    from .downloader import RealDataDownloader, download_all_lof
    _DOWNLOADER_AVAILABLE = True
except ImportError:
    _DOWNLOADER_AVAILABLE = False
    RealDataDownloader = None  # type: ignore
    download_all_lof = None  # type: ignore

__all__ = ["DataLoader", "MockConfig", "generate_mock_data"]

if _DOWNLOADER_AVAILABLE:
    __all__.extend(["RealDataDownloader", "download_all_lof"])
