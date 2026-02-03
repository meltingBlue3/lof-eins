"""
Simple script to run the mock data generator.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.generator import MockConfig, generate_mock_data

if __name__ == "__main__":
    # Use default configuration
    config = MockConfig()
    
    # Or customize configuration
    # config = MockConfig(
    #     tickers=['161005', '162411', '161725'],
    #     start_date="2024-01-01",
    #     end_date="2024-06-30",
    #     limit_trigger_threshold=0.15,
    #     consecutive_days=2
    # )
    
    generate_mock_data(config)
