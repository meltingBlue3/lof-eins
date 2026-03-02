"""
Backtest execution engine and result analysis for LOF Backtesting.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from src.config import BacktestConfig
from src.data.loader import DataLoader, BundleResult
from src.engine.account import Account
from src.strategy.base import BaseStrategy, Signal

logger = logging.getLogger(__name__)


def calculate_subscription_fee(amount: float, attrs: Dict[str, Any]) -> float:
    """Calculate tiered subscription fee based on amount.
    
    Fee tiers (from df.attrs):
    - Tier 1: amount < fee_limit_1 -> fee_rate_tier_1
    - Tier 2: fee_limit_1 <= amount < fee_limit_2 -> fee_rate_tier_2
    - Tier 3: amount >= fee_limit_2 -> fee_fixed (flat fee)
    
    Args:
        amount: Subscription amount in CNY.
        attrs: DataFrame attrs containing fee configuration.
        
    Returns:
        Calculated fee in CNY.
    """
    fee_limit_1 = attrs.get('fee_limit_1', 500_000.0)
    fee_limit_2 = attrs.get('fee_limit_2', 2_000_000.0)
    fee_rate_tier_1 = attrs.get('fee_rate_tier_1', 0.015)
    fee_rate_tier_2 = attrs.get('fee_rate_tier_2', 0.01)
    fee_fixed = attrs.get('fee_fixed', 1000.0)
    
    if amount < fee_limit_1:
        return amount * fee_rate_tier_1
    elif amount < fee_limit_2:
        return amount * fee_rate_tier_2
    else:
        return fee_fixed


@dataclass
class BacktestResult:
    """Encapsulates backtest outputs with performance metrics.
    
    Supports both single-ticker and multi-ticker backtests.
    
    Attributes:
        daily_perf: Daily performance DataFrame with columns:
            - total_assets: Total account value (cash + all positions)
            - cash: Cash balance
            - positions_value: Value of all positions across all tickers
        trade_logs: DataFrame of all executed trades with columns:
            - date, action, ticker, shares, price, amount, fee, net_amount,
              premium_rate, cash_before, cash_after
            - BUY-only columns: daily_limit, limit_cap, liquid_cap, cash_cap,
              effective_cap
        config: The BacktestConfig used for this run.
        daily_snapshots: Per-ticker daily position snapshots with columns:
            - date, ticker, settled_shares, pending_shares, total_shares,
              last_price, position_value
    """
    
    daily_perf: pd.DataFrame
    trade_logs: pd.DataFrame
    config: BacktestConfig
    daily_snapshots: pd.DataFrame = field(default_factory=pd.DataFrame)
    _start_value: float = field(default=0.0, repr=False)
    _end_value: float = field(default=0.0, repr=False)
    
    def __post_init__(self) -> None:
        """Initialize start/end values for metric calculations."""
        if not self.daily_perf.empty:
            self._start_value = self.daily_perf['total_assets'].iloc[0]
            self._end_value = self.daily_perf['total_assets'].iloc[-1]
    
    @cached_property
    def total_return(self) -> float:
        """Calculate total return: (End / Start) - 1."""
        if self._start_value <= 0:
            return 0.0
        return (self._end_value / self._start_value) - 1.0
    
    @cached_property
    def annualized_return(self) -> float:
        """Calculate annualized return using geometric mean.
        
        Assumes 252 trading days per year.
        """
        if self.daily_perf.empty or self._start_value <= 0:
            return 0.0
        
        n_days = len(self.daily_perf)
        if n_days <= 1:
            return 0.0
        
        total_return_factor = self._end_value / self._start_value
        
        # Handle negative returns (can't take fractional power of negative)
        if total_return_factor <= 0:
            return -1.0
        
        # Annualize: (1 + R)^(252/n) - 1
        annualized = (total_return_factor ** (252.0 / n_days)) - 1.0
        return annualized
    
    @cached_property
    def max_drawdown(self) -> float:
        """Calculate maximum drawdown (peak-to-trough decline).
        
        Returns:
            Maximum drawdown as a positive decimal (e.g., 0.15 for 15% drawdown).
        """
        if self.daily_perf.empty:
            return 0.0
        
        total_assets = self.daily_perf['total_assets'].values
        
        # Calculate running maximum
        running_max = np.maximum.accumulate(total_assets)
        
        # Calculate drawdown at each point
        drawdowns = (running_max - total_assets) / running_max
        
        # Handle division by zero (shouldn't happen with positive values)
        drawdowns = np.nan_to_num(drawdowns, nan=0.0)
        
        max_dd = np.max(drawdowns)
        return float(max_dd)
    
    @cached_property
    def sharpe_ratio(self) -> float:
        """Calculate Sharpe ratio.
        
        Formula: (Annualized Return - Risk Free Rate) / Annualized Volatility
        
        Returns:
            Sharpe ratio. Returns 0.0 if volatility is zero.
        """
        if self.daily_perf.empty or len(self.daily_perf) < 2:
            return 0.0
        
        # Calculate daily returns
        total_assets = self.daily_perf['total_assets'].values
        daily_returns = np.diff(total_assets) / total_assets[:-1]
        
        # Handle edge cases
        daily_returns = np.nan_to_num(daily_returns, nan=0.0, posinf=0.0, neginf=0.0)
        
        # Annualized volatility
        daily_vol = np.std(daily_returns, ddof=1)
        if daily_vol < 1e-10:  # Essentially zero volatility
            return 0.0
        
        annualized_vol = daily_vol * np.sqrt(252)
        
        # Sharpe ratio
        excess_return = self.annualized_return - self.config.risk_free_rate
        sharpe = excess_return / annualized_vol
        
        return float(sharpe)
    
    @property
    def num_trades(self) -> int:
        """Total number of trades executed."""
        return len(self.trade_logs)
    
    @property
    def num_buy_trades(self) -> int:
        """Number of buy trades."""
        if self.trade_logs.empty:
            return 0
        return int((self.trade_logs['action'] == 'buy').sum())
    
    @property
    def num_sell_trades(self) -> int:
        """Number of sell trades."""
        if self.trade_logs.empty:
            return 0
        return int((self.trade_logs['action'] == 'sell').sum())
    
    def __str__(self) -> str:
        """Return formatted summary of backtest results."""
        lines = [
            "=" * 60,
            "BACKTEST RESULTS",
            "=" * 60,
            "",
            "Performance Metrics:",
            f"  Total Return:      {self.total_return:>10.2%}",
            f"  Annualized Return: {self.annualized_return:>10.2%}",
            f"  Max Drawdown:      {self.max_drawdown:>10.2%}",
            f"  Sharpe Ratio:      {self.sharpe_ratio:>10.2f}",
            "",
            "Trading Summary:",
            f"  Total Trades:      {self.num_trades:>10d}",
            f"  Buy Trades:        {self.num_buy_trades:>10d}",
            f"  Sell Trades:       {self.num_sell_trades:>10d}",
            "",
            "Account Summary:",
            f"  Initial Capital:   {self._start_value:>14,.2f} CNY",
            f"  Final Value:       {self._end_value:>14,.2f} CNY",
            f"  Profit/Loss:       {self._end_value - self._start_value:>14,.2f} CNY",
            "",
            "Configuration:",
            f"  Buy Threshold:     {self.config.buy_threshold:>10.2%}",
            f"  Liquidity Ratio:   {self.config.liquidity_ratio:>10.2%}",
            f"  Risk Mode:         {self.config.risk_mode:>10s}",
            "=" * 60,
        ]
        return "\n".join(lines)


class BacktestEngine:
    """Execution engine for LOF backtesting.
    
    Orchestrates the backtest loop: loading data, generating signals,
    executing trades with proper constraints, and recording performance.
    """
    
    def __init__(
        self,
        config: BacktestConfig,
        strategy: BaseStrategy,
        data_loader: Optional[DataLoader] = None
    ):
        """Initialize backtest engine.
        
        Args:
            config: Backtest configuration.
            strategy: Trading strategy instance.
            data_loader: DataLoader instance. If None, creates default.
        """
        self.config = config
        self.strategy = strategy
        self.data_loader = data_loader or DataLoader()
    
    def _load_multi_data(
        self,
        tickers: List[str],
        start_date: Optional[str],
        end_date: Optional[str]
    ) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Dict[str, Any]], pd.DatetimeIndex]:
        """Load data for multiple tickers and align dates.

        Args:
            tickers: List of fund ticker symbols.
            start_date: Optional start date filter (YYYY-MM-DD).
            end_date: Optional end date filter (YYYY-MM-DD).

        Returns:
            Tuple of:
            - Dict mapping ticker to DataFrame with market data
            - Dict mapping ticker to fee configuration
            - DatetimeIndex of aligned trading days (union of all tickers)
        """
        all_data: Dict[str, pd.DataFrame] = {}
        all_fees: Dict[str, Dict[str, Any]] = {}

        for ticker in tickers:
            bundle = self.data_loader.load_bundle(ticker, start_date, end_date)
            df = bundle.df
            all_fees[ticker] = bundle.fee_config

            # Pre-compute MA5 volume
            if self.config.use_ma5_liquidity:
                df['ma5_volume'] = df['volume'].rolling(5, min_periods=1).mean()
            else:
                df['ma5_volume'] = df['volume']

            # Add ticker column
            df['ticker'] = ticker

            all_data[ticker] = df
        
        # Find union of all trading days
        if not all_data:
            return {}, {}, pd.DatetimeIndex([])

        all_dates: set = set()
        for df in all_data.values():
            all_dates = all_dates.union(set(df.index))

        # Sort dates
        aligned_dates = pd.DatetimeIndex(sorted(all_dates))

        return all_data, all_fees, aligned_dates
    
    def run(
        self,
        tickers: Union[str, List[str]],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> BacktestResult:
        """Execute backtest for one or more tickers with unified capital pool.
        
        When multiple tickers are provided:
        - Uses a single shared account (unified capital pool)
        - Can hold positions in multiple funds simultaneously
        - Buy signals are sorted by premium_rate (descending) and executed greedily
        
        Args:
            tickers: Single ticker string or list of ticker symbols.
            start_date: Optional start date filter (YYYY-MM-DD).
            end_date: Optional end date filter (YYYY-MM-DD).
            
        Returns:
            BacktestResult with performance metrics and trade logs.
        """
        # Normalize tickers to list
        if isinstance(tickers, str):
            ticker_list = [tickers]
        else:
            ticker_list = list(tickers)
        
        # Load all data and align dates
        all_data, all_fees, aligned_dates = self._load_multi_data(ticker_list, start_date, end_date)
        
        if not all_data or len(aligned_dates) == 0:
            logger.warning("No data available for tickers: %s", ticker_list)
            return BacktestResult(
                daily_perf=pd.DataFrame(),
                trade_logs=pd.DataFrame(),
                config=self.config,
                daily_snapshots=pd.DataFrame(),
            )
        
        # Extract trading days as date objects
        trading_days: List[date] = [d.date() for d in aligned_dates]
        
        # Initialize account
        account = Account(cash=self.config.initial_cash)
        
        # Storage for results
        daily_records: List[Dict[str, Any]] = []
        trade_records: List[Dict[str, Any]] = []
        snapshot_records: List[Dict[str, Any]] = []
        last_known_prices: Dict[str, float] = {}
        
        # Main backtest loop
        for timestamp in aligned_dates:
            current_date = timestamp.date()
            
            # Step 1: Settle T+2 positions
            account.update_date(current_date)
            
            # Step 2: SELL Phase - sell all settled (T+2) shares immediately.
            # This is intentional: LOF arbitrage buys off-exchange at NAV on day T,
            # shares settle on T+2, then are sold on-exchange at market price on T+2.
            # Only settled shares are sold; shares bought on T+1 remain pending.
            for ticker in ticker_list:
                if ticker not in all_data or timestamp not in all_data[ticker].index:
                    continue
                
                row = all_data[ticker].loc[timestamp]
                available_shares = account.get_available_shares(ticker)
                
                if available_shares > 0:
                    signal = Signal(action='sell', ticker=ticker, amount=float('inf'))
                    trade = self._execute_sell(
                        account=account,
                        signal=signal,
                        row=row,
                        current_date=current_date
                    )
                    if trade:
                        trade_records.append(trade)
            
            # Step 3: BUY Phase - collect candidates, sort by premium_rate, buy greedily
            buy_candidates = []
            
            for ticker in ticker_list:
                if ticker not in all_data or timestamp not in all_data[ticker].index:
                    continue
                
                row = all_data[ticker].loc[timestamp]
                premium_rate = row['premium_rate']
                daily_limit = row['daily_limit']
                
                # Filter: must exceed threshold and have positive limit
                if premium_rate > self.config.buy_threshold and daily_limit > 0:
                    buy_candidates.append({
                        'ticker': ticker,
                        'premium_rate': premium_rate,
                        'row': row,
                        'fee_config': all_fees.get(ticker, {}),
                    })
            
            # Sort by premium_rate descending (highest first)
            buy_candidates.sort(key=lambda x: x['premium_rate'], reverse=True)
            
            # Greedy buy: iterate until cash exhausted
            for candidate in buy_candidates:
                if account.cash <= 0:
                    break
                
                signal = Signal(
                    action='buy',
                    ticker=candidate['ticker'],
                    amount=float('inf')
                )
                trade = self._execute_buy(
                    account=account,
                    signal=signal,
                    row=candidate['row'],
                    fee_config=candidate['fee_config'],
                    trading_days=trading_days,
                    current_date=current_date
                )
                if trade:
                    trade_records.append(trade)
            
            # Step 4: Record daily performance
            # Update forward-filled price cache with today's available closes
            for ticker in ticker_list:
                if ticker in all_data and timestamp in all_data[ticker].index:
                    last_known_prices[ticker] = all_data[ticker].loc[timestamp, 'close']
            
            daily_records.append({
                'date': timestamp,
                'total_assets': account.get_total_value(last_known_prices),
                'cash': account.cash,
                'positions_value': account.get_positions_value(last_known_prices),
            })
            
            # Record per-ticker position snapshots
            for ticker in ticker_list:
                settled = account.get_available_shares(ticker)
                pending = account.get_pending_shares(ticker)
                total = settled + pending
                price = last_known_prices.get(ticker, 0.0)
                snapshot_records.append({
                    'date': timestamp,
                    'ticker': ticker,
                    'settled_shares': settled,
                    'pending_shares': pending,
                    'total_shares': total,
                    'last_price': price,
                    'position_value': total * price,
                })
        
        # Build result DataFrames
        daily_perf = pd.DataFrame(daily_records)
        if not daily_perf.empty:
            daily_perf.set_index('date', inplace=True)
        
        trade_logs = pd.DataFrame(trade_records)
        daily_snapshots = pd.DataFrame(snapshot_records)
        
        return BacktestResult(
            daily_perf=daily_perf,
            trade_logs=trade_logs,
            config=self.config,
            daily_snapshots=daily_snapshots,
        )
    
    def _execute_sell(
        self,
        account: Account,
        signal: Signal,
        row: pd.Series,
        current_date: date
    ) -> Optional[Dict[str, Any]]:
        """Execute a sell order.
        
        Args:
            account: Account instance.
            signal: Sell signal.
            row: Current market data row.
            current_date: Current simulation date.
            
        Returns:
            Trade record dict, or None if no trade executed.
        """
        ticker = signal.ticker
        available_shares = account.get_available_shares(ticker)
        
        if available_shares <= 0:
            return None
        
        # Determine shares to sell
        if signal.amount == float('inf'):
            shares_to_sell = available_shares
        else:
            shares_to_sell = min(signal.amount / row['close'], available_shares)
        
        if shares_to_sell <= 0:
            return None
        
        # Execute sell
        price = row['close']
        premium_rate = row['premium_rate']
        cash_before = account.cash
        
        net_proceeds = account.sell(
            ticker=ticker,
            shares=shares_to_sell,
            price=price,
            commission_rate=self.config.commission_rate
        )
        
        commission = shares_to_sell * price * self.config.commission_rate
        
        return {
            'date': current_date,
            'action': 'sell',
            'ticker': ticker,
            'shares': shares_to_sell,
            'price': price,
            'amount': shares_to_sell * price,
            'fee': commission,
            'net_amount': net_proceeds,
            'premium_rate': premium_rate,
            'cash_before': cash_before,
            'cash_after': account.cash,
        }
    
    def _execute_buy(
        self,
        account: Account,
        signal: Signal,
        row: pd.Series,
        fee_config: Dict[str, Any],
        trading_days: List[date],
        current_date: date
    ) -> Optional[Dict[str, Any]]:
        """Execute a buy order with constraints.

        Constraints (take minimum):
        - limit_cap: row['daily_limit'] (SQLite limit event)
        - liquid_cap: min(volume, ma5_volume) * liquidity_ratio
        - cash_cap: account.cash (if risk_mode == 'fixed')

        Args:
            account: Account instance.
            signal: Buy signal.
            row: Current market data row.
            fee_config: Fee configuration dict for the ticker.
            trading_days: List of trading days for T+2 calculation.
            current_date: Current simulation date.

        Returns:
            Trade record dict, or None if no trade executed.
        """
        ticker = signal.ticker
        
        # Calculate constraints
        limit_cap = row['daily_limit']
        if np.isinf(limit_cap):
            limit_cap = float('inf')
        
        # Liquidity constraint
        volume = row['volume']
        ma5_volume = row.get('ma5_volume', volume)
        if self.config.use_ma5_liquidity:
            effective_volume = min(volume, ma5_volume)
        else:
            effective_volume = volume
        
        liquid_cap = effective_volume * self.config.liquidity_ratio * row['close']
        
        # Cash constraint
        if self.config.risk_mode == 'fixed':
            cash_cap = account.cash
        else:
            cash_cap = float('inf')
        
        # Signal amount constraint
        if signal.amount == float('inf'):
            signal_cap = float('inf')
        else:
            signal_cap = signal.amount
        
        # Take minimum of all constraints
        max_amount = min(limit_cap, liquid_cap, cash_cap, signal_cap)
        
        if max_amount <= 0 or account.cash <= 0:
            return None
        
        # Ensure we don't exceed available cash
        max_amount = min(max_amount, account.cash)
        
        # Calculate fee
        fee = calculate_subscription_fee(max_amount, fee_config)
        
        # Ensure amount covers fee
        if max_amount <= fee:
            logger.debug(
                "Buy skipped for %s: amount %.2f <= fee %.2f",
                ticker, max_amount, fee
            )
            return None
        
        # Execute buy
        nav = row['nav']
        premium_rate = row['premium_rate']
        daily_limit = row['daily_limit']
        cash_before = account.cash
        
        shares = account.buy(
            ticker=ticker,
            amount=max_amount,
            nav=nav,
            fee=fee,
            trading_days=trading_days
        )
        
        return {
            'date': current_date,
            'action': 'buy',
            'ticker': ticker,
            'shares': shares,
            'price': nav,  # Subscription is at NAV
            'amount': max_amount,
            'fee': fee,
            'net_amount': max_amount - fee,
            'premium_rate': premium_rate,
            'daily_limit': daily_limit,
            'limit_cap': limit_cap,
            'liquid_cap': liquid_cap,
            'cash_cap': cash_cap,
            'effective_cap': min(limit_cap, liquid_cap, cash_cap),
            'cash_before': cash_before,
            'cash_after': account.cash,
        }
