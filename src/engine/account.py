"""
Account management with T+2 settlement for LOF Backtesting Engine.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PendingSettlement:
    """Represents a pending share settlement.
    
    Attributes:
        settle_date: Date when shares become available.
        ticker: Fund ticker symbol.
        shares: Number of shares to settle.
    """
    
    settle_date: date
    ticker: str
    shares: float


@dataclass
class Account:
    """Account management with T+2 settlement support.
    
    Handles cash, positions, and pending settlements. Shares purchased
    are not available until T+2 settlement completes.
    
    Attributes:
        cash: Available cash balance.
        positions: Settled positions as {ticker: shares}.
        pending: List of pending settlements awaiting T+2.
        _current_date: Current simulation date.
    """
    
    cash: float
    positions: Dict[str, float] = field(default_factory=dict)
    pending: List[PendingSettlement] = field(default_factory=list)
    _current_date: Optional[date] = None
    
    def update_date(self, current_date: date) -> None:
        """Advance to a new date and settle any matured positions.
        
        Processes all pending settlements where settle_date <= current_date.
        
        Args:
            current_date: The new simulation date.
        """
        self._current_date = current_date
        
        # Separate matured and still-pending settlements
        matured = []
        still_pending = []
        
        for settlement in self.pending:
            if settlement.settle_date <= current_date:
                matured.append(settlement)
            else:
                still_pending.append(settlement)
        
        # Process matured settlements
        for settlement in matured:
            ticker = settlement.ticker
            shares = settlement.shares
            
            if ticker not in self.positions:
                self.positions[ticker] = 0.0
            self.positions[ticker] += shares
            
            logger.debug(
                "T+2 Settlement: %s +%.2f shares on %s",
                ticker, shares, current_date
            )
        
        self.pending = still_pending
    
    def sell(
        self,
        ticker: str,
        shares: float,
        price: float,
        commission_rate: float
    ) -> float:
        """Execute a sell order. Cash is immediately available (T+0).
        
        Args:
            ticker: Fund ticker symbol.
            shares: Number of shares to sell.
            price: Execution price per share.
            commission_rate: Commission rate to apply.
            
        Returns:
            Net proceeds after commission.
            
        Raises:
            ValueError: If insufficient shares available.
        """
        available = self.get_available_shares(ticker)
        
        if shares > available + 1e-9:  # Small tolerance for floating point
            raise ValueError(
                f"Insufficient shares for {ticker}: "
                f"requested {shares}, available {available}"
            )
        
        # Calculate proceeds
        gross_proceeds = shares * price
        commission = gross_proceeds * commission_rate
        net_proceeds = gross_proceeds - commission
        
        # Update positions
        self.positions[ticker] -= shares
        if self.positions[ticker] < 1e-9:
            self.positions[ticker] = 0.0
        
        # Credit cash immediately (T+0)
        self.cash += net_proceeds
        
        logger.info(
            "SELL %s: %.2f shares @ %.4f = %.2f (comm: %.2f)",
            ticker, shares, price, net_proceeds, commission
        )
        
        return net_proceeds
    
    def buy(
        self,
        ticker: str,
        amount: float,
        nav: float,
        fee: float,
        trading_days: List[date]
    ) -> float:
        """Execute a buy order with T+2 settlement.
        
        Shares are added to pending queue and settle after T+2.
        
        Args:
            ticker: Fund ticker symbol.
            amount: Total amount to invest (including fee).
            nav: NAV for share calculation.
            fee: Subscription fee (already calculated).
            trading_days: List of trading days for T+2 calculation.
            
        Returns:
            Number of shares purchased.
            
        Raises:
            ValueError: If insufficient cash.
        """
        if amount > self.cash + 1e-9:
            raise ValueError(
                f"Insufficient cash: requested {amount}, available {self.cash}"
            )
        
        # Calculate shares
        net_amount = amount - fee
        shares = net_amount / nav
        
        # Deduct cash
        self.cash -= amount
        
        # Calculate T+2 settlement date
        settle_date = self._calculate_t2_date(trading_days)
        
        # Add to pending queue
        self.pending.append(PendingSettlement(
            settle_date=settle_date,
            ticker=ticker,
            shares=shares
        ))
        
        logger.info(
            "BUY %s: %.2f CNY -> %.2f shares @ NAV %.4f (fee: %.2f, settle: %s)",
            ticker, amount, shares, nav, fee, settle_date
        )
        
        return shares
    
    def _calculate_t2_date(self, trading_days: List[date]) -> date:
        """Calculate T+2 settlement date based on trading calendar.
        
        Args:
            trading_days: Sorted list of trading days.
            
        Returns:
            Settlement date (T+2 trading days from current date).
        """
        if self._current_date is None:
            raise ValueError("Current date not set. Call update_date first.")
        
        # Find current date index in trading days
        try:
            current_idx = trading_days.index(self._current_date)
        except ValueError:
            # Current date not in trading days, use fallback
            return self._current_date + timedelta(days=2)
        
        # T+2 means 2 trading days after current
        settle_idx = current_idx + 2
        
        if settle_idx < len(trading_days):
            return trading_days[settle_idx]
        else:
            # Beyond available trading days, estimate
            return self._current_date + timedelta(days=4)  # Conservative estimate
    
    def get_available_shares(self, ticker: str) -> float:
        """Get available (settled) shares for a ticker.
        
        Args:
            ticker: Fund ticker symbol.
            
        Returns:
            Number of settled shares available for trading.
        """
        return self.positions.get(ticker, 0.0)
    
    def get_pending_shares(self, ticker: str) -> float:
        """Get pending (unsettled) shares for a ticker.
        
        Args:
            ticker: Fund ticker symbol.
            
        Returns:
            Number of shares awaiting settlement.
        """
        return sum(
            p.shares for p in self.pending 
            if p.ticker == ticker
        )
    
    def get_total_shares(self, ticker: str) -> float:
        """Get total shares (settled + pending) for a ticker.
        
        Args:
            ticker: Fund ticker symbol.
            
        Returns:
            Total number of shares including pending settlements.
        """
        return self.get_available_shares(ticker) + self.get_pending_shares(ticker)
    
    def get_total_value(self, prices: Dict[str, float]) -> float:
        """Calculate total account value (cash + positions).
        
        Args:
            prices: Current prices as {ticker: price}.
            
        Returns:
            Total account value in CNY.
        """
        positions_value = sum(
            shares * prices.get(ticker, 0.0)
            for ticker, shares in self.positions.items()
        )
        
        # Include pending settlements at current prices
        pending_value = sum(
            p.shares * prices.get(p.ticker, 0.0)
            for p in self.pending
        )
        
        return self.cash + positions_value + pending_value
    
    def get_positions_value(self, prices: Dict[str, float]) -> float:
        """Calculate value of all positions (settled + pending).
        
        Args:
            prices: Current prices as {ticker: price}.
            
        Returns:
            Total positions value in CNY.
        """
        settled_value = sum(
            shares * prices.get(ticker, 0.0)
            for ticker, shares in self.positions.items()
        )
        
        pending_value = sum(
            p.shares * prices.get(p.ticker, 0.0)
            for p in self.pending
        )
        
        return settled_value + pending_value
