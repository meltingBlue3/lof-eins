"""
Configuration module for LOF Mock Data Generator.

LOF模拟数据生成器的配置模块。
"""

from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import List, Union

import yaml


@dataclass
class MockConfig:
    """Configuration class for mock data generation.

    模拟数据生成的配置类。

    Attributes:
        tickers: List of fund ticker symbols to generate data for. / 要生成数据的基金代码列表
        start_date: Start date for data generation (format: 'YYYY-MM-DD'). / 数据生成起始日期
        end_date: End date for data generation (format: 'YYYY-MM-DD'). / 数据生成结束日期
        initial_nav: Initial Net Asset Value for each fund. / 每只基金的初始净值
        premium_volatility: Volatility coefficient for premium rate fluctuations. / 溢价率波动系数
        limit_trigger_threshold: Premium rate threshold to trigger purchase limit (e.g., 0.15 = 15%). / 触发限购的溢价率阈值
        limit_release_threshold: Premium rate threshold to release purchase limit (e.g., 0.05 = 5%). / 解除限购的溢价率阈值
        consecutive_days: Number of consecutive days above threshold to trigger limit. / 触发限购的连续天数
        spike_probability: Probability of premium rate spike event occurring on any given day. / 溢价率突增事件概率
        nav_drift: Daily drift coefficient for NAV random walk (annualized return). / 净值随机游走的日漂移系数
        nav_volatility: Daily volatility for NAV random walk (annualized). / 净值随机游走的日波动率
        limit_max_amount: Maximum purchase amount during limit period (in CNY). / 限购期间最大申购金额
        normal_max_amount: Maximum purchase amount during normal period (in CNY, -1 for unlimited). / 正常期间最大申购金额
    """

    tickers: List[str] = field(
        default_factory=lambda: ["161005", "162411", "161725", "501018", "160216"]
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
        """Validate configuration parameters. / 验证配置参数"""
        if self.limit_trigger_threshold <= self.limit_release_threshold:
            raise ValueError(
                f"limit_trigger_threshold ({self.limit_trigger_threshold}) must be "
                f"greater than limit_release_threshold ({self.limit_release_threshold})"
            )

        if self.consecutive_days < 1:
            raise ValueError(
                f"consecutive_days must be >= 1, got {self.consecutive_days}"
            )

        if not self.tickers:
            raise ValueError("tickers list cannot be empty")

        if self.initial_nav <= 0:
            raise ValueError(f"initial_nav must be positive, got {self.initial_nav}")

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "MockConfig":
        """Load configuration from a YAML file.

        从YAML文件加载配置。

        Args:
            path: Path to the YAML configuration file. / YAML配置文件路径

        Returns:
            MockConfig instance with values from the file. / 包含文件值的MockConfig实例

        Raises:
            FileNotFoundError: If the file does not exist. / 文件不存在
            yaml.YAMLError: If the file is not valid YAML. / YAML格式无效
            ValueError: If configuration values are invalid. / 配置值无效
        """
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Filter to only valid MockConfig fields  # 仅过滤有效的MockConfig字段
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
