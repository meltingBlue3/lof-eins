"""
Mock Data Generator with YAML Configuration Support.

支持YAML配置的模拟数据生成器。

Usage:
    python scripts/generate_mock.py                          # Use default config (configs/mock.yaml)
    python scripts/generate_mock.py --config my_config.yaml  # Use custom config file

使用方法：
    python scripts/generate_mock.py                          # 使用默认配置 (configs/mock.yaml)
    python scripts/generate_mock.py --config my_config.yaml  # 使用自定义配置文件
"""

import argparse
import sys
from pathlib import Path

# Add project root to path / 将项目根目录添加到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.generator import MockConfig, generate_mock_data


DEFAULT_CONFIG_PATH = Path("configs/mock.yaml")


def main() -> None:
    """Main entry point for the mock data generator CLI.

    模拟数据生成器CLI的主入口。
    """
    parser = argparse.ArgumentParser(
        description="Generate LOF mock data with YAML configuration."
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to YAML config file (default: {DEFAULT_CONFIG_PATH})",
    )
    args = parser.parse_args()

    config_path: Path = args.config
    if config_path.exists():
        print(f"[INFO] Loading config from: {config_path}")
        config = MockConfig.from_yaml(config_path)
    else:
        print(f"[WARN] Config file not found: {config_path}, using defaults")
        config = MockConfig()

    # Print loaded configuration summary / 打印加载的配置摘要
    print(f"[INFO] Configuration:")
    print(f"       tickers: {config.tickers}")
    print(f"       date_range: {config.start_date} to {config.end_date}")
    print(f"       initial_nav: {config.initial_nav}")
    print(f"       limit_trigger_threshold: {config.limit_trigger_threshold:.1%}")

    generate_mock_data(config)


if __name__ == "__main__":
    main()
