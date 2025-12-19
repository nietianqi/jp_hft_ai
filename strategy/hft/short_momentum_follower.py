# -*- coding: utf-8 -*-
"""
short_momentum_follower.py - 短周期动量跟随策略

核心思路:
1. 基于1s/3s/5s K线识别短期趋势
2. 结合microVWAP判断方向
3. 短EMA交叉确认入场
4. 持仓几秒~几十秒
"""

from __future__ import annotations
from dataclasses import dataclass
from collections import deque
from typing import Deque, Optional, Dict, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class ShortMomentumConfig:
    symbol: str
    board_symbol: str
    tick_size: float = 0.1
    lot_size: int = 100

    # K线参数
    bar_period_seconds: int = 3         # 3秒K线
    min_bars: int = 10                  # 最少10根K线

    # EMA参数
    fast_ema_periods: int = 3           # 快线3周期
    slow_ema_periods: int = 8           # 慢线8周期
    ema_cross_threshold_ticks: float = 0.5  # EMA差距阈值

    # microVWAP参数
    vwap_window_seconds: int = 10       # 10秒microVWAP
    vwap_deviation_threshold: float = 0.0015  # 偏离0.15%确认趋势

    # 动量确认
    momentum_min_ticks: int = 2         # 最小动量2 ticks
    momentum_window_seconds: int = 5    # 5秒动量窗口

    # 风险控制
    max_position: int = 100
    enable_dynamic_exit: bool = True
    dynamic_profit_threshold_ticks: float = 3.0
    dynamic_reversal_ticks: float = 1.5

    take_profit_ticks: int = 5
    stop_loss_ticks: int = 10
    time_stop_seconds: int = 30         # 30秒时间止损

    signal_cooldown_seconds: float = 2.0

    log_prefix: str = "[MOMENTUM]"


@dataclass
class BarData:
    """K线数据"""
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float  # 该K线的VWAP


@dataclass
class Trade:
    """成交记录（用于计算microVWAP）"""
    ts: datetime
    price: float
    volume: int


class ShortMomentumFollower:
    """短周期动量跟随策略"""

    def __init__(self, gateway, config: ShortMomentumConfig, meta_manager=None):
        self.gateway = gateway
        self.cfg = config
        self.meta = meta_manager

        self.board: Optional[Dict[str, Any]] = None

        # K线数据
        self.bars: Deque[BarData] = deque()
        self.current_bar_start: Optional[datetime] = None
        self.current_bar_data: Dict[str, Any] = {}

        # 成交数据（用于microVWAP）
        self.trades: Deque[Trade] = deque()

        # EMA
        self.fast_ema: Optional[float] = None
        self.slow_ema: Optional[float] = None

        # 持仓
        self.position: int = 0
        self.avg_price: Optional[float] = None
        self.entry_time: Optional[datetime] = None

        self.active_order_id: Optional[str] = None
        self.last_signal_time: Optional[datetime] = None

        # 动态止盈
        self.best_profit_price: Optional[float] = None

    def on_board(self, board: Dict[str, Any]) -> None:
        if board.get("symbol") != self.cfg.board_symbol:
            return

        self.board = board
        now = board["timestamp"]
        last_price = float(board["last_price"])

        # 模拟成交（实际应从tick data获取）
        volume = int(board.get("trading_volume", 0))
        self._add_trade(now, last_price, volume)

        # 更新K线
        self._update_bar(now, last_price)

        # 计算EMA
        self._update_emas()

        # 检查入场信号
        if self.position == 0:
            self._check_entry_signal(now)

        # 检查出场
        self._check_exit(now, last_price)

    def _add_trade(self, ts: datetime, price: float, volume: int) -> None:
        """添加成交记录"""
        self.trades.append(Trade(ts=ts, price=price, volume=volume))

        # 保留窗口内的数据
        cutoff = ts - timedelta(seconds=self.cfg.vwap_window_seconds)
        while self.trades and self.trades[0].ts < cutoff:
            self.trades.popleft()

    def _update_bar(self, now: datetime, price: float) -> None:
        """更新K线"""
        # 初始化第一根K线
        if self.current_bar_start is None:
            self.current_bar_start = now
            self.current_bar_data = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0,
            }
            return

        # 检查是否需要生成新K线
        elapsed = (now - self.current_bar_start).total_seconds()

        if elapsed >= self.cfg.bar_period_seconds:
            # 完成当前K线
            bar = BarData(
                ts=self.current_bar_start,
                open=self.current_bar_data["open"],
                high=self.current_bar_data["high"],
                low=self.current_bar_data["low"],
                close=self.current_bar_data["close"],
                volume=self.current_bar_data["volume"],
                vwap=self._calculate_micro_vwap(),
            )
            self.bars.append(bar)

            # 保留最近的K线
            if len(self.bars) > self.cfg.min_bars * 2:
                self.bars.popleft()

            # 开始新K线
            self.current_bar_start = now
            self.current_bar_data = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0,
            }
        else:
            # 更新当前K线
            self.current_bar_data["high"] = max(self.current_bar_data["high"], price)
            self.current_bar_data["low"] = min(self.current_bar_data["low"], price)
            self.current_bar_data["close"] = price

    def _calculate_micro_vwap(self) -> float:
        """计算microVWAP"""
        if not self.trades:
            return 0.0

        total_volume = sum(t.volume for t in self.trades)
        if total_volume == 0:
            return 0.0

        vwap = sum(t.price * t.volume for t in self.trades) / total_volume
        return vwap

    def _update_emas(self) -> None:
        """更新EMA"""
        if len(self.bars) < self.cfg.slow_ema_periods:
            return

        closes = [bar.close for bar in self.bars]

        # 计算快线EMA
        self.fast_ema = self._calculate_ema(closes, self.cfg.fast_ema_periods)

        # 计算慢线EMA
        self.slow_ema = self._calculate_ema(closes, self.cfg.slow_ema_periods)

    def _calculate_ema(self, prices: list, periods: int) -> float:
        """计算EMA"""
        if len(prices) < periods:
            return sum(prices) / len(prices)

        # 使用最近periods个价格计算
        recent_prices = prices[-periods:]
        multiplier = 2 / (periods + 1)

        ema = recent_prices[0]
        for price in recent_prices[1:]:
            ema = (price - ema) * multiplier + ema

        return ema

    def _check_entry_signal(self, now: datetime) -> None:
        """检查入场信号"""
        if not self.board or not self.fast_ema or not self.slow_ema:
            return

        # 冷却期检查
        if self.last_signal_time:
            elapsed = (now - self.last_signal_time).total_seconds()
            if elapsed < self.cfg.signal_cooldown_seconds:
                return

        current_price = float(self.board["last_price"])
        micro_vwap = self._calculate_micro_vwap()

        if micro_vwap == 0:
            return

        # 计算EMA差距
        ema_diff = (self.fast_ema - self.slow_ema) / self.cfg.tick_size

        # 计算VWAP偏离
        vwap_deviation = (current_price - micro_vwap) / micro_vwap

        # 计算动量
        momentum_ticks = self._calculate_momentum()

        # 做多信号:
        # 1. 快线上穿慢线
        # 2. 价格高于VWAP
        # 3. 正动量
        if (
            ema_diff >= self.cfg.ema_cross_threshold_ticks
            and vwap_deviation >= self.cfg.vwap_deviation_threshold
            and momentum_ticks >= self.cfg.momentum_min_ticks
        ):
            self._enter_long(now)

        # 做空信号: (相反)
        elif (
            ema_diff <= -self.cfg.ema_cross_threshold_ticks
            and vwap_deviation <= -self.cfg.vwap_deviation_threshold
            and momentum_ticks <= -self.cfg.momentum_min_ticks
        ):
            self._enter_short(now)

    def _calculate_momentum(self) -> float:
        """计算动量（ticks）"""
        if len(self.bars) < 2:
            return 0.0

        # 计算窗口内的价格变化
        recent_bars = [bar for bar in self.bars if bar.ts >= (datetime.now() - timedelta(seconds=self.cfg.momentum_window_seconds))]

        if len(recent_bars) < 2:
            return 0.0

        first_close = recent_bars[0].close
        last_close = recent_bars[-1].close

        momentum = (last_close - first_close) / self.cfg.tick_size
        return momentum

    def _enter_long(self, now: datetime) -> None:
        """做多入场"""
        if not self.board or abs(self.position) >= self.cfg.max_position:
            return

        best_ask = float(self.board["best_ask"])
        qty = self.cfg.lot_size

        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.SHORT_MOMENTUM, "BUY", best_ask, qty, "动量做多"
            )
            if not can_exec:
                return

        from engine.meta_strategy_manager import StrategyType
        order_id = self.gateway.send_order(
            symbol=self.cfg.symbol,
            side="BUY",
            price=best_ask,
            qty=qty,
            order_type="LIMIT",
            strategy_type=StrategyType.SHORT_MOMENTUM,
        )

        self.active_order_id = order_id
        self.last_signal_time = now
        logger.info(f"{self.cfg.log_prefix} 动量做多 {qty}@{best_ask:.1f}")

    def _enter_short(self, now: datetime) -> None:
        """做空入场"""
        if not self.board or abs(self.position) >= self.cfg.max_position:
            return

        best_bid = float(self.board["best_bid"])
        qty = self.cfg.lot_size

        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.SHORT_MOMENTUM, "SELL", best_bid, qty, "动量做空"
            )
            if not can_exec:
                return

        from engine.meta_strategy_manager import StrategyType
        order_id = self.gateway.send_order(
            symbol=self.cfg.symbol,
            side="SELL",
            price=best_bid,
            qty=qty,
            order_type="LIMIT",
            strategy_type=StrategyType.SHORT_MOMENTUM,
        )

        self.active_order_id = order_id
        self.last_signal_time = now
        logger.info(f"{self.cfg.log_prefix} 动量做空 {qty}@{best_bid:.1f}")

    def _check_exit(self, now: datetime, current_price: float) -> None:
        """✅新策略: 盈利立即锁定，亏损硬扛"""
        if self.position == 0 or self.avg_price is None:
            return

        pnl_ticks = (current_price - self.avg_price) / self.cfg.tick_size
        if self.position < 0:
            pnl_ticks = -pnl_ticks

        reason = None

        # ========== 新策略: 盈利≥1tick开始追踪，缩水立即平仓，亏损硬扛 ==========
        if self.cfg.enable_dynamic_exit:
            # ✅修改: 只有盈利≥1 tick才开始追踪止盈
            if pnl_ticks >= 1.0:
                # 初始化或更新最优价格
                if self.best_profit_price is None:
                    self.best_profit_price = current_price
                    logger.debug(f"{self.cfg.log_prefix} [锁定盈利] 盈利达到1T，开始追踪，当前盈利={pnl_ticks:.1f}T")
                else:
                    # 做多：检查价格是否还在上涨
                    if self.position > 0:
                        if current_price > self.best_profit_price:
                            # 价格继续上涨，更新最高价
                            self.best_profit_price = current_price
                            logger.debug(f"{self.cfg.log_prefix} [锁定盈利] 价格创新高={current_price:.1f}，盈利={pnl_ticks:.1f}T")
                        else:
                            # 价格开始下跌！立即平仓锁定盈利
                            reversal_ticks = (self.best_profit_price - current_price) / self.cfg.tick_size
                            reason = "profit_lock"
                            print(f"💰 {self.cfg.log_prefix} [锁定盈利] 价格回落! 最高={self.best_profit_price:.1f}, 当前={current_price:.1f}, 回撤={reversal_ticks:.1f}T → 立即平仓锁定盈利={pnl_ticks:.1f}T")

                    # 做空：检查价格是否还在下跌
                    elif self.position < 0:
                        if current_price < self.best_profit_price:
                            # 价格继续下跌，更新最低价
                            self.best_profit_price = current_price
                            logger.debug(f"{self.cfg.log_prefix} [锁定盈利] 价格创新低={current_price:.1f}，盈利={pnl_ticks:.1f}T")
                        else:
                            # 价格开始上涨！立即平仓锁定盈利
                            reversal_ticks = (current_price - self.best_profit_price) / self.cfg.tick_size
                            reason = "profit_lock"
                            print(f"💰 {self.cfg.log_prefix} [锁定盈利] 价格回升! 最低={self.best_profit_price:.1f}, 当前={current_price:.1f}, 回撤={reversal_ticks:.1f}T → 立即平仓锁定盈利={pnl_ticks:.1f}T")
            else:
                # 亏损时：硬扛，不平仓
                logger.debug(f"{self.cfg.log_prefix} [硬扛亏损] 当前亏损={pnl_ticks:.1f}T，继续持有等待反转")

        # 时间止损（可选，防止长期持仓）
        if (
            self.entry_time
            and (now - self.entry_time).total_seconds() >= self.cfg.time_stop_seconds
        ):
            reason = "time_stop"

        if reason:
            self._exit_position(reason)

    def _exit_position(self, reason: str) -> None:
        """平仓"""
        if self.position == 0 or not self.board:
            return

        qty = abs(self.position)

        if self.position > 0:
            side = "SELL"
            price = float(self.board["best_bid"])
        else:
            side = "BUY"
            price = float(self.board["best_ask"])

        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.SHORT_MOMENTUM, side, price, qty, reason
            )
            if not can_exec:
                return

        from engine.meta_strategy_manager import StrategyType
        order_id = self.gateway.send_order(
            symbol=self.cfg.symbol,
            side=side,
            price=price,
            qty=qty,
            order_type="LIMIT",
            strategy_type=StrategyType.SHORT_MOMENTUM,
        )

        print(f"📤 {self.cfg.log_prefix} [平仓] {reason}: {side} {qty}@{price:.1f}")

    def on_fill(self, fill: Dict[str, Any]) -> None:
        if fill.get("symbol") != self.cfg.symbol:
            return

        from engine.meta_strategy_manager import StrategyType
        if fill.get("strategy_type") != StrategyType.SHORT_MOMENTUM:
            return

        side = fill["side"]
        size = int(fill.get("size", fill.get("quantity", 0)))
        price = float(fill["price"])

        prev_pos = self.position
        new_pos = prev_pos + size if side == "BUY" else prev_pos - size

        if prev_pos == 0 and new_pos != 0:
            self.avg_price = price
            self.entry_time = datetime.now()
            self.best_profit_price = None
        elif prev_pos != 0 and new_pos == 0:
            self.avg_price = None
            self.entry_time = None
            self.best_profit_price = None

        self.position = new_pos

        if self.meta:
            self.meta.on_fill(StrategyType.SHORT_MOMENTUM, side, price, size)

    def on_order_update(self, order: Dict[str, Any]) -> None:
        if order.get("symbol") != self.cfg.symbol:
            return

        if order.get("order_id") == self.active_order_id:
            status = order.get("status", "")
            if status in ("CANCELLED", "REJECTED", "FILLED"):
                self.active_order_id = None
