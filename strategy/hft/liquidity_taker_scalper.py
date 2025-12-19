# -*- coding: utf-8 -*-
"""
liquidity_taker_scalper.py - 修复版
"""

from __future__ import annotations
from dataclasses import dataclass
from collections import deque
from typing import Deque, Optional, Dict, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class LiquidityTakerConfig:
    symbol: str
    board_symbol: str
    tick_size: float = 0.1
    order_volume: int = 100
    max_position: int = 100

    # ✅修复: 改为动态止盈模式，与做市策略一致
    enable_dynamic_exit: bool = True            # 启用动态止盈模式
    dynamic_profit_threshold_ticks: float = 3.0 # 盈利阈值3 ticks才启动追踪
    dynamic_reversal_ticks: float = 1.5         # 回撤1.5 ticks触发平仓

    # 传统止盈止损(当enable_dynamic_exit=False时使用)
    take_profit_ticks: int = 5      # 止盈5 ticks (0.5日元)
    stop_loss_ticks: int = 10       # 止损10 ticks (1.0日元)
    time_stop_seconds: int = 5

    max_slip_ticks: int = 1
    depth_levels: int = 5
    depth_imbalance_thresh_long: float = 0.4
    depth_imbalance_thresh_short: float = -0.4
    momentum_min_ticks: int = 1
    trade_window_seconds: int = 2
    
    cool_down_seconds: float = 1.0
    log_prefix: str = "[LT]"


@dataclass
class PricePoint:
    ts: datetime
    last_price: float


class KabuLiquidityTakerScalper:
    """流动性抢占策略 - 修复版"""
    
    def __init__(self, gateway, config: LiquidityTakerConfig, meta_manager=None):
        self.gateway = gateway
        self.cfg = config
        self.meta = meta_manager
        
        self.position: int = 0
        self.avg_price: Optional[float] = None
        self.entry_time: Optional[datetime] = None

        self.board: Optional[Dict[str, Any]] = None
        self.price_window: Deque[PricePoint] = deque()

        self.last_signal_time: Optional[datetime] = None
        self.active_order_id: Optional[str] = None

        # ✅新增: 动态止盈状态追踪
        self.best_profit_price: Optional[float] = None
    
    def on_board(self, board: Dict[str, Any]) -> None:
        if board.get("symbol") != self.cfg.board_symbol:
            return
        
        self.board = board
        now: datetime = board["timestamp"]
        
        # ✅修复:使用best_bid/best_ask计算中间价作为last_price的替代
        last_price = float(board.get("last_price", 0))
        if last_price <= 0:
            best_bid = float(board.get("best_bid", 0))
            best_ask = float(board.get("best_ask", 0))
            if best_bid > 0 and best_ask > 0:
                last_price = (best_bid + best_ask) / 2
        
        if last_price > 0:
            self._update_price_window(now, last_price)
        
        self._check_exit(now)
        
        if self.position == 0:
            self._maybe_open(now)
    
    def _update_price_window(self, ts: datetime, last_price: float) -> None:
        self.price_window.append(PricePoint(ts=ts, last_price=last_price))
        cutoff = ts - timedelta(seconds=self.cfg.trade_window_seconds)
        while self.price_window and self.price_window[0].ts < cutoff:
            self.price_window.popleft()
    
    def _calc_momentum_ticks(self) -> int:
        if len(self.price_window) < 2:
            return 0
        first = self.price_window[0].last_price
        last = self.price_window[-1].last_price
        diff = last - first
        return int(round(diff / self.cfg.tick_size))
    
    def _calc_depth_imbalance(self) -> float:
        if not self.board:
            return 0.0
        
        bids = self.board.get("bids") or []
        asks = self.board.get("asks") or []
        
        b = sum(size for _, size in bids[: self.cfg.depth_levels])
        a = sum(size for _, size in asks[: self.cfg.depth_levels])
        
        total = b + a
        if total <= 0:
            return 0.0
        return (b - a) / total
    
    def _cool_down_ok(self, now: datetime) -> bool:
        if self.last_signal_time is None:
            return True
        dt = (now - self.last_signal_time).total_seconds()
        return dt >= self.cfg.cool_down_seconds
    
    def _maybe_open(self, now: datetime) -> None:
        if not self.board or not self._cool_down_ok(now):
            return
        
        momentum = self._calc_momentum_ticks()
        depth_imb = self._calc_depth_imbalance()
        
        best_bid = float(self.board.get("best_bid", 0))
        best_ask = float(self.board.get("best_ask", 0))
        
        if best_bid <= 0 or best_ask <= 0:
            return
        
        if (
            momentum >= self.cfg.momentum_min_ticks
            and depth_imb >= self.cfg.depth_imbalance_thresh_long
        ):
            self._open_long(best_ask, now)
        elif (
            momentum <= -self.cfg.momentum_min_ticks
            and depth_imb <= self.cfg.depth_imbalance_thresh_short
        ):
            self._open_short(best_bid, now)
    
    def _open_long(self, best_ask: float, now: datetime) -> None:
        if self.position >= self.cfg.max_position:
            return

        qty = min(self.cfg.order_volume, self.cfg.max_position - self.position)
        # ✅修复: 做多应该在ask价买入,不应该加滑点(否则价格更差)
        price = best_ask
        
        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.LIQUIDITY_TAKER, "BUY", price, qty, "流动性抢占做多"
            )
            if not can_exec:
                return
        
        order_id = self.gateway.send_order(
            symbol=self.cfg.symbol,
            side="BUY",
            price=price,
            qty=qty,
            order_type="LIMIT",
            strategy_type=StrategyType.LIQUIDITY_TAKER,  # ← 新增：标识订单来源
        )

        self.active_order_id = order_id
        self.last_signal_time = now
    
    def _open_short(self, best_bid: float, now: datetime) -> None:
        if abs(self.position) >= self.cfg.max_position:
            return

        qty = min(self.cfg.order_volume, self.cfg.max_position - abs(self.position))
        # ✅修复: 做空应该在bid价卖出,不应该减滑点(否则价格更差)
        price = best_bid
        
        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.LIQUIDITY_TAKER, "SELL", price, qty, "流动性抢占做空"
            )
            if not can_exec:
                return
        
        order_id = self.gateway.send_order(
            symbol=self.cfg.symbol,
            side="SELL",
            price=price,
            qty=qty,
            order_type="LIMIT",
            strategy_type=StrategyType.LIQUIDITY_TAKER,  # ← 新增：标识订单来源
        )

        self.active_order_id = order_id
        self.last_signal_time = now
    
    def _check_exit(self, now: datetime) -> None:
        """✅新策略: 盈利立即锁定，亏损硬扛"""
        if self.position == 0 or not self.board or self.avg_price is None:
            return

        best_bid = float(self.board.get("best_bid", 0))
        best_ask = float(self.board.get("best_ask", 0))

        if best_bid <= 0 or best_ask <= 0:
            return

        last_price = (best_bid + best_ask) / 2
        pnl_ticks = (last_price - self.avg_price) / self.cfg.tick_size

        if self.position < 0:
            pnl_ticks = -pnl_ticks

        reason = None

        # ========== 新策略: 盈利缩水立即平仓，亏损硬扛 ==========
        if self.cfg.enable_dynamic_exit:
            # 只要有盈利（哪怕0.1 tick），就开始追踪
            if pnl_ticks > 0:
                # 初始化或更新最优价格
                if self.best_profit_price is None:
                    self.best_profit_price = last_price
                    logger.debug(f"{self.cfg.log_prefix} [锁定盈利] 开始追踪，当前盈利={pnl_ticks:.1f}T")
                else:
                    # 做多：检查价格是否还在上涨
                    if self.position > 0:
                        if last_price > self.best_profit_price:
                            # 价格继续上涨，更新最高价
                            self.best_profit_price = last_price
                            logger.debug(f"{self.cfg.log_prefix} [锁定盈利] 价格创新高={last_price:.1f}，盈利={pnl_ticks:.1f}T")
                        else:
                            # 价格开始下跌！立即平仓锁定盈利
                            reversal_ticks = (self.best_profit_price - last_price) / self.cfg.tick_size
                            reason = "profit_lock"
                            print(f"💰 {self.cfg.log_prefix} [锁定盈利] 价格回落! 最高={self.best_profit_price:.1f}, 当前={last_price:.1f}, 回撤={reversal_ticks:.1f}T → 立即平仓锁定盈利={pnl_ticks:.1f}T")

                    # 做空：检查价格是否还在下跌
                    elif self.position < 0:
                        if last_price < self.best_profit_price:
                            # 价格继续下跌，更新最低价
                            self.best_profit_price = last_price
                            logger.debug(f"{self.cfg.log_prefix} [锁定盈利] 价格创新低={last_price:.1f}，盈利={pnl_ticks:.1f}T")
                        else:
                            # 价格开始上涨！立即平仓锁定盈利
                            reversal_ticks = (last_price - self.best_profit_price) / self.cfg.tick_size
                            reason = "profit_lock"
                            print(f"💰 {self.cfg.log_prefix} [锁定盈利] 价格回升! 最低={self.best_profit_price:.1f}, 当前={last_price:.1f}, 回撤={reversal_ticks:.1f}T → 立即平仓锁定盈利={pnl_ticks:.1f}T")
            else:
                # 亏损时：硬扛，不平仓
                logger.debug(f"{self.cfg.log_prefix} [硬扛亏损] 当前亏损={pnl_ticks:.1f}T，继续持有等待反转")

        # ========== 传统止盈止损（备用） ==========
        else:
            if pnl_ticks >= self.cfg.take_profit_ticks:
                reason = "take_profit"
            elif pnl_ticks <= -self.cfg.stop_loss_ticks:
                reason = "stop_loss"
            elif (
                self.entry_time
                and (now - self.entry_time).total_seconds() >= self.cfg.time_stop_seconds
            ):
                reason = "time_stop"

        if reason:
            self._exit_position(reason)
    
    def _exit_position(self, reason: str) -> None:
        if self.position == 0 or not self.board:
            return
        
        qty = abs(self.position)
        
        if self.position > 0:
            side = "SELL"
            price = self.board["best_bid"] - self.cfg.max_slip_ticks * self.cfg.tick_size
        else:
            side = "BUY"
            price = self.board["best_ask"] + self.cfg.max_slip_ticks * self.cfg.tick_size
        
        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.LIQUIDITY_TAKER, side, price, qty, reason
            )
            if not can_exec:
                return
        
        order_id = self.gateway.send_order(
            symbol=self.cfg.symbol,
            side=side,
            price=price,
            qty=qty,
            order_type="LIMIT",
            strategy_type=StrategyType.LIQUIDITY_TAKER,  # ← 新增：标识订单来源
        )

        self.active_order_id = order_id
    
    def on_fill(self, fill: Dict[str, Any]) -> None:
        if fill.get("symbol") != self.cfg.symbol:
            return

        # ← 新增：检查订单归属，只处理自己的订单
        from engine.meta_strategy_manager import StrategyType
        if fill.get("strategy_type") != StrategyType.LIQUIDITY_TAKER:
            return  # 不是流动性抢占策略的订单，忽略

        side = fill["side"]
        size = int(fill.get("size", fill.get("quantity", 0)))
        price = float(fill["price"])
        
        prev_pos = self.position
        new_pos = prev_pos + size if side == "BUY" else prev_pos - size
        
        if prev_pos == 0 and new_pos != 0:
            self.entry_time = datetime.now()
            self.avg_price = price
            self.best_profit_price = None  # ✅重置动态止盈状态
        elif prev_pos != 0 and new_pos != 0 and prev_pos * new_pos > 0:
            self.avg_price = (self.avg_price * abs(prev_pos) + price * size) / abs(new_pos)
        elif prev_pos != 0 and new_pos == 0:
            self.entry_time = None
            self.avg_price = None
            self.best_profit_price = None  # ✅重置动态止盈状态
        
        self.position = new_pos
        
        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            self.meta.on_fill(StrategyType.LIQUIDITY_TAKER, side, price, size)
    
    def on_order_update(self, order: Dict[str, Any]) -> None:
        if order.get("symbol") != self.cfg.symbol:
            return
        if order.get("order_id") != self.active_order_id:
            return
        
        status = order.get("status", "")
        if status in ("CANCELLED", "REJECTED", "FILLED"):
            self.active_order_id = None
