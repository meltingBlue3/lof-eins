"""
Account management with T+2 settlement for LOF Backtesting Engine.

LOF回测引擎的账户管理模块（含T+2结算）。
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PendingSettlement:
    """Represents a pending share settlement.

    表示待结算的份额。

    Attributes:
        settle_date: Date when shares become available. / 份额可用日期
        ticker: Fund ticker symbol. / 基金代码
        shares: Number of shares to settle. / 待结算份额数量
    """

    settle_date: date
    ticker: str
    shares: float


@dataclass
class Account:
    """Account management with T+2 settlement support.

    支持T+2结算的账户管理。

    Handles cash, positions, and pending settlements. Shares purchased
    are not available until T+2 settlement completes.

    处理现金、持仓和待结算份额。购买的份额在T+2结算完成前不可用。

    Attributes:
        cash: Available cash balance. / 可用现金余额
        positions: Settled positions as {ticker: shares}. / 已结算持仓 {基金代码: 份额}
        pending: List of pending settlements awaiting T+2. / 等待T+2结算的待结算列表
        _current_date: Current simulation date. / 当前模拟日期
    """

    cash: float
    positions: Dict[str, float] = field(default_factory=dict)
    pending: List[PendingSettlement] = field(default_factory=list)
    _current_date: Optional[date] = None

    def update_date(self, current_date: date) -> None:
        """Advance to a new date and settle any matured positions.

        推进到新日期并结算任何已到期的持仓。

        Processes all pending settlements where settle_date <= current_date.

        处理所有settle_date <= current_date的待结算项。

        Args:
            current_date: The new simulation date. / 新的模拟日期
        """
        self._current_date = current_date

        # Separate matured and still-pending settlements  # 分离已到期和仍待结算的项
        matured = []
        still_pending = []

        for settlement in self.pending:
            if settlement.settle_date <= current_date:
                matured.append(settlement)
            else:
                still_pending.append(settlement)

        # Process matured settlements  # 处理已到期的结算
        for settlement in matured:
            ticker = settlement.ticker
            shares = settlement.shares

            if ticker not in self.positions:
                self.positions[ticker] = 0.0
            self.positions[ticker] += shares

            logger.debug(
                "T+2 Settlement: %s +%.2f shares on %s", ticker, shares, current_date
            )

        self.pending = still_pending

    def sell(
        self, ticker: str, shares: float, price: float, commission_rate: float
    ) -> float:
        """Execute a sell order. Cash is immediately available (T+0).

        执行卖出订单。现金立即可用（T+0）。

        Args:
            ticker: Fund ticker symbol. / 基金代码
            shares: Number of shares to sell. / 卖出份额数量
            price: Execution price per share. / 执行价格（每股）
            commission_rate: Commission rate to apply. / 佣金率

        Returns:
            Net proceeds after commission. / 扣除佣金后的净收入

        Raises:
            ValueError: If insufficient shares available. / 份额不足
        """
        available = self.get_available_shares(ticker)

        if (
            shares > available + 1e-9
        ):  # Small tolerance for floating point  # 浮点数容差
            raise ValueError(
                f"Insufficient shares for {ticker}: "
                f"requested {shares}, available {available}"
            )

        # Calculate proceeds  # 计算收入
        gross_proceeds = shares * price
        commission = gross_proceeds * commission_rate
        net_proceeds = gross_proceeds - commission

        # Update positions  # 更新持仓
        self.positions[ticker] -= shares
        if self.positions[ticker] < 1e-9:
            self.positions[ticker] = 0.0

        # Credit cash immediately (T+0)  # 立即入账现金（T+0）
        self.cash += net_proceeds

        logger.info(
            "SELL %s: %.2f shares @ %.4f = %.2f (comm: %.2f)",
            ticker,
            shares,
            price,
            net_proceeds,
            commission,
        )

        return net_proceeds

    def buy(
        self,
        ticker: str,
        amount: float,
        nav: float,
        fee: float,
        trading_days: List[date],
    ) -> float:
        """Execute a buy order with T+2 settlement.

        执行买入订单（T+2结算）。

        Shares are added to pending queue and settle after T+2.

        份额加入待结算队列，T+2后结算。

        Args:
            ticker: Fund ticker symbol. / 基金代码
            amount: Total amount to invest (including fee). / 投资金额（含费用）
            nav: NAV for share calculation. / 用于计算份额的净值
            fee: Subscription fee (already calculated). / 申购费（已计算）
            trading_days: List of trading days for T+2 calculation. / 交易日列表（用于T+2计算）

        Returns:
            Number of shares purchased. / 购买的份额数量

        Raises:
            ValueError: If insufficient cash. / 现金不足
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
        self.pending.append(
            PendingSettlement(settle_date=settle_date, ticker=ticker, shares=shares)
        )

        logger.info(
            "BUY %s: %.2f CNY -> %.2f shares @ NAV %.4f (fee: %.2f, settle: %s)",
            ticker,
            amount,
            shares,
            nav,
            fee,
            settle_date,
        )

        return shares

    def _calculate_t2_date(self, trading_days: List[date]) -> date:
        """Calculate T+2 settlement date based on trading calendar.

        基于交易日历计算T+2结算日期。

        Args:
            trading_days: Sorted list of trading days. / 排序后的交易日列表

        Returns:
            Settlement date (T+2 trading days from current date). / 结算日期（当前日期后2个交易日）
        """
        if self._current_date is None:
            raise ValueError("Current date not set. Call update_date first.")

        # Find current date index in trading days  # 在交易日列表中查找当前日期索引
        try:
            current_idx = trading_days.index(self._current_date)
        except ValueError:
            # Current date not in trading days, use fallback  # 当前日期不在交易日列表中，使用回退方案
            return self._current_date + timedelta(days=2)

        # T+2 means 2 trading days after current  # T+2表示当前日期后2个交易日
        settle_idx = current_idx + 2

        if settle_idx < len(trading_days):
            return trading_days[settle_idx]
        else:
            # Beyond available trading days, estimate  # 超出可用交易日，估算
            return self._current_date + timedelta(
                days=4
            )  # Conservative estimate  # 保守估计

    def get_available_shares(self, ticker: str) -> float:
        """Get available (settled) shares for a ticker.

        获取某基金代码的可用（已结算）份额。

        Args:
            ticker: Fund ticker symbol. / 基金代码

        Returns:
            Number of settled shares available for trading. / 可用于交易的已结算份额
        """
        return self.positions.get(ticker, 0.0)

    def get_pending_shares(self, ticker: str) -> float:
        """Get pending (unsettled) shares for a ticker.

        获取某基金代码的待结算份额。

        Args:
            ticker: Fund ticker symbol. / 基金代码

        Returns:
            Number of shares awaiting settlement. / 等待结算的份额
        """
        return sum(p.shares for p in self.pending if p.ticker == ticker)

    def get_total_shares(self, ticker: str) -> float:
        """Get total shares (settled + pending) for a ticker.

        获取某基金代码的总份额（已结算 + 待结算）。

        Args:
            ticker: Fund ticker symbol. / 基金代码

        Returns:
            Total number of shares including pending settlements. / 包含待结算的总份额
        """
        return self.get_available_shares(ticker) + self.get_pending_shares(ticker)

    def get_total_value(self, prices: Dict[str, float]) -> float:
        """Calculate total account value (cash + positions).

        计算账户总价值（现金 + 持仓）。

        Args:
            prices: Current prices as {ticker: price}. / 当前价格 {基金代码: 价格}

        Returns:
            Total account value in CNY. / 账户总价值（人民币）
        """
        positions_value = sum(
            shares * prices.get(ticker, 0.0)
            for ticker, shares in self.positions.items()
        )

        # Include pending settlements at current prices  # 以当前价格计入待结算份额
        pending_value = sum(p.shares * prices.get(p.ticker, 0.0) for p in self.pending)

        return self.cash + positions_value + pending_value

    def get_positions_value(self, prices: Dict[str, float]) -> float:
        """Calculate value of all positions (settled + pending).

        计算所有持仓的价值（已结算 + 待结算）。

        Args:
            prices: Current prices as {ticker: price}. / 当前价格 {基金代码: 价格}

        Returns:
            Total positions value in CNY. / 持仓总价值（人民币）
        """
        settled_value = sum(
            shares * prices.get(ticker, 0.0)
            for ticker, shares in self.positions.items()
        )

        pending_value = sum(p.shares * prices.get(p.ticker, 0.0) for p in self.pending)

        return settled_value + pending_value
