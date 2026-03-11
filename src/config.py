"""
Central configuration management for LOF Backtesting Engine.

LOF回测引擎的中央配置管理模块。
"""

from dataclasses import dataclass, fields, asdict
from pathlib import Path
from typing import Literal, Union

import yaml


@dataclass
class BacktestConfig:
    """Configuration class for backtesting parameters.

    回测参数配置类。

    Attributes:
        initial_cash: Starting capital for the backtest. / 回测初始资金
        liquidity_ratio: Fraction of volume that can be traded without market impact. / 不影响市场的成交量比例
        buy_threshold: Minimum premium rate to trigger a buy signal. / 触发买入信号的最低溢价率
        commission_rate: Trading commission rate (applied to sell transactions). / 交易佣金率（应用于卖出）
        risk_mode: Position sizing mode - 'fixed' uses available cash, 'infinite' ignores cash constraints. / 仓位模式
        use_ma5_liquidity: If True, use min(volume, ma5_volume) for liquidity calculation. / 是否使用5日均量计算流动性
        risk_free_rate: Annual risk-free rate for Sharpe ratio calculation. / 年化无风险利率（用于夏普比率计算）
    """

    initial_cash: float = 300_000.0
    liquidity_ratio: float = 0.1
    buy_threshold: float = 0.02
    commission_rate: float = 0.0003
    risk_mode: Literal["fixed", "infinite"] = "fixed"
    use_ma5_liquidity: bool = True
    risk_free_rate: float = 0.02

    def __post_init__(self) -> None:
        """Validate configuration parameters. / 验证配置参数"""
        if self.initial_cash <= 0:
            raise ValueError(f"initial_cash must be positive, got {self.initial_cash}")

        if not 0 <= self.liquidity_ratio <= 1:
            raise ValueError(
                f"liquidity_ratio must be in [0, 1], got {self.liquidity_ratio}"
            )

        if self.commission_rate < 0:
            raise ValueError(
                f"commission_rate must be non-negative, got {self.commission_rate}"
            )

        if self.risk_mode not in ("fixed", "infinite"):
            raise ValueError(
                f"risk_mode must be 'fixed' or 'infinite', got {self.risk_mode}"
            )

        if self.risk_free_rate < 0:
            raise ValueError(
                f"risk_free_rate must be non-negative, got {self.risk_free_rate}"
            )

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "BacktestConfig":
        """Load configuration from a YAML file.

        从YAML文件加载配置。

        Args:
            path: Path to the YAML configuration file. / YAML配置文件路径

        Returns:
            BacktestConfig instance with values from the file. / 包含文件值的BacktestConfig实例

        Raises:
            FileNotFoundError: If the file does not exist. / 文件不存在
            yaml.YAMLError: If the file is not valid YAML. / YAML格式无效
            ValueError: If configuration values are invalid. / 配置值无效
        """
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Filter to only valid BacktestConfig fields
        valid_fields = {field.name for field in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}

        return cls(**filtered_data)

    def to_yaml(self, path: Union[str, Path]) -> None:
        """Save configuration to a YAML file.

        将配置保存到YAML文件。

        Args:
            path: Path to save the YAML configuration file. / YAML配置文件保存路径
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                asdict(self),
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
