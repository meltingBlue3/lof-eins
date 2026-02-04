"""
Configuration module for LOF Mock Data Generator.
"""

from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import List, Union

import yaml


@dataclass
class MockConfig:
    """Configuration class for mock data generation.
    
    Attributes:
        tickers: List of fund ticker symbols to generate data for.
        start_date: Start date for data generation (format: 'YYYY-MM-DD').
        end_date: End date for data generation (format: 'YYYY-MM-DD').
        initial_nav: Initial Net Asset Value for each fund.
        premium_volatility: Volatility coefficient for premium rate fluctuations.
        limit_trigger_threshold: Premium rate threshold to trigger purchase limit (e.g., 0.15 = 15%).
        limit_release_threshold: Premium rate threshold to release purchase limit (e.g., 0.05 = 5%).
        consecutive_days: Number of consecutive days above threshold to trigger limit.
        spike_probability: Probability of premium rate spike event occurring on any given day.
        nav_drift: Daily drift coefficient for NAV random walk (annualized return).
        nav_volatility: Daily volatility for NAV random walk (annualized).
        limit_max_amount: Maximum purchase amount during limit period (in CNY).
        normal_max_amount: Maximum purchase amount during normal period (in CNY, -1 for unlimited).
    """
    
    tickers: List[str] = field(
        default_factory=lambda: ['161005', '162411', '161725', '501018', '160216']
    )
    start_date: str = "2024-01-01"
    end_date: str = "2024-12-31"
    initial_nav: float = 2.0
    premium_volatility: float = 0.01
    limit_trigger_threshold: float = 0.07
    limit_release_threshold: float = 0.03
    consecutive_days: int = 1
    spike_probability: float = 0.04
    nav_drift: float = -0.0005  # ~7.5% annualized
    nav_volatility: float = 0.015  # ~24% annualized
    limit_max_amount: float = 100.0
    normal_max_amount: float = 1_000_000.0
    
    def __post_init__(self):
        """Validate configuration parameters."""
        if self.limit_trigger_threshold <= self.limit_release_threshold:
            raise ValueError(
                f"limit_trigger_threshold ({self.limit_trigger_threshold}) must be "
                f"greater than limit_release_threshold ({self.limit_release_threshold})"
            )
        
        if self.consecutive_days < 1:
            raise ValueError(f"consecutive_days must be >= 1, got {self.consecutive_days}")
        
        if not self.tickers:
            raise ValueError("tickers list cannot be empty")
        
        if self.initial_nav <= 0:
            raise ValueError(f"initial_nav must be positive, got {self.initial_nav}")

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "MockConfig":
        """Load configuration from a YAML file.
        
        Args:
            path: Path to the YAML configuration file.
            
        Returns:
            MockConfig instance with values from the file.
            
        Raises:
            FileNotFoundError: If the file does not exist.
            yaml.YAMLError: If the file is not valid YAML.
            ValueError: If configuration values are invalid.
        """
        path = Path(path)
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        
        # Filter to only valid MockConfig fields
        valid_fields = {field.name for field in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        
        return cls(**filtered_data)

    def to_yaml(self, path: Union[str, Path]) -> None:
        """Save configuration to a YAML file.
        
        Args:
            path: Path to save the YAML configuration file.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(asdict(self), f, default_flow_style=False, allow_unicode=True, sort_keys=False)
