"""
Central configuration management for LOF Backtesting Engine.
"""

from dataclasses import dataclass, fields, asdict
from pathlib import Path
from typing import Literal, Union

import yaml


@dataclass
class BacktestConfig:
    """Configuration class for backtesting parameters.
    
    Attributes:
        initial_cash: Starting capital for the backtest.
        liquidity_ratio: Fraction of volume that can be traded without market impact.
        buy_threshold: Minimum premium rate to trigger a buy signal.
        commission_rate: Trading commission rate (applied to sell transactions).
        risk_mode: Position sizing mode - 'fixed' uses available cash, 'infinite' ignores cash constraints.
        use_ma5_liquidity: If True, use min(volume, ma5_volume) for liquidity calculation.
        risk_free_rate: Annual risk-free rate for Sharpe ratio calculation.
    """
    
    initial_cash: float = 300_000.0
    liquidity_ratio: float = 0.1
    buy_threshold: float = 0.02
    commission_rate: float = 0.0003
    risk_mode: Literal['fixed', 'infinite'] = 'fixed'
    use_ma5_liquidity: bool = True
    risk_free_rate: float = 0.02
    
    def __post_init__(self) -> None:
        """Validate configuration parameters."""
        if self.initial_cash <= 0:
            raise ValueError(f"initial_cash must be positive, got {self.initial_cash}")
        
        if not 0 <= self.liquidity_ratio <= 1:
            raise ValueError(f"liquidity_ratio must be in [0, 1], got {self.liquidity_ratio}")
        
        if self.commission_rate < 0:
            raise ValueError(f"commission_rate must be non-negative, got {self.commission_rate}")
        
        if self.risk_mode not in ('fixed', 'infinite'):
            raise ValueError(f"risk_mode must be 'fixed' or 'infinite', got {self.risk_mode}")
        
        if self.risk_free_rate < 0:
            raise ValueError(f"risk_free_rate must be non-negative, got {self.risk_free_rate}")

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "BacktestConfig":
        """Load configuration from a YAML file.
        
        Args:
            path: Path to the YAML configuration file.
            
        Returns:
            BacktestConfig instance with values from the file.
            
        Raises:
            FileNotFoundError: If the file does not exist.
            yaml.YAMLError: If the file is not valid YAML.
            ValueError: If configuration values are invalid.
        """
        path = Path(path)
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        
        # Filter to only valid BacktestConfig fields
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
