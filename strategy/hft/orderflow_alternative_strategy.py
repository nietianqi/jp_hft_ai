# -*- coding: utf-8 -*-
"""
orderflow_alternative_strategy.py

替代订单流策略 - 不依赖is_buy_taker
改用Kabu提供的板情報数据
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any, Deque
from collections import deque
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class OrderFlowAlternativeConfig:
    symbol: str
    board_symbol: str
    tick_size: float = 0.1
    lot_size: int = 100
    
    board_window_seconds: int = 3
    min_board_samples: int = 5
    
    buy_pressure_threshold: float = 0.6
    sell_pressure_threshold: float = -0.6
    
    min_price_momentum_ticks: int = 2
    min_volume_increase: int = 1000
    
    depth_levels: int = 3
    depth_imbalance_long: float = 0.3
    depth_imbalance_short: float = -0.3
    
    max_ahead_volume: int = 2000
    max_queue_wait_seconds: int = 3
    
    max_position: int = 100

    # ✅修复: 改为动态止盈模式
    enable_dynamic_exit: bool = True
    dynamic_profit_threshold_ticks: float = 3.0
    dynamic_reversal_ticks: float = 1.5

    # 传统止盈止损
    take_profit_ticks: int = 5
    stop_loss_ticks: int = 10
    time_stop_seconds: int = 5
    
    signal_cooldown_seconds: float = 1.0
    log_prefix: str = "[OFA]"


@dataclass
class BoardSnapshot:
    ts: datetime
    price: float
    bid_qty: int
    ask_qty: int
    volume: int
    buy_market_order: int
    sell_market_order: int


class OrderFlowAlternativeStrategy:
    """替代订单流策略"""
    
    def __init__(self, gateway, config: OrderFlowAlternativeConfig, meta_manager=None):
        self.gateway = gateway
        self.cfg = config
        self.meta = meta_manager
        
        self.board_history: Deque[BoardSnapshot] = deque()

        self.position: int = 0
        self.avg_price: Optional[float] = None
        self.entry_time: Optional[datetime] = None

        self.active_order_id: Optional[str] = None
        self.last_signal_time: Optional[datetime] = None

        # ✅新增: 动态止盈状态追踪
        self.best_profit_price: Optional[float] = None
    
    def on_board(self, board: Dict[str, Any]) -> None:
        if board.get("symbol") != self.cfg.board_symbol:
            return
        
        now = board["timestamp"]
        
        snapshot = BoardSnapshot(
            ts=now,
            price=float(board.get("last_price", 0)),
            bid_qty=sum(q for _, q in board.get("bids", [])[:self.cfg.depth_levels]),
            ask_qty=sum(q for _, q in board.get("asks", [])[:self.cfg.depth_levels]),
            volume=int(board.get("trading_volume", 0)),
            buy_market_order=int(board.get("buy_market_order", 0)),
            sell_market_order=int(board.get("sell_market_order", 0)),
        )
        
        self._update_board_history(snapshot)
        self._manage_position(now, board)
        
        if self.position == 0:
            self._maybe_trade(now, board)
    
    def _update_board_history(self, snapshot: BoardSnapshot) -> None:
        self.board_history.append(snapshot)
        cutoff = snapshot.ts - timedelta(seconds=self.cfg.board_window_seconds)
        while self.board_history and self.board_history[0].ts < cutoff:
            self.board_history.popleft()
    
    def _calculate_order_flow_pressure(self) -> Dict[str, Any]:
        if len(self.board_history) < self.cfg.min_board_samples:
            return {"pressure": 0.0, "momentum_ticks": 0, "volume_increase": 0, "confidence": 0.0}
        
        first = self.board_history[0]
        last = self.board_history[-1]
        
        # 市价单压力
        buy_market_delta = last.buy_market_order - first.buy_market_order
        sell_market_delta = last.sell_market_order - first.sell_market_order
        
        market_pressure = 0.0
        if buy_market_delta + sell_market_delta > 0:
            market_pressure = (buy_market_delta - sell_market_delta) / (buy_market_delta + sell_market_delta)
        
        # 挂单量变化
        bid_delta = last.bid_qty - first.bid_qty
        ask_delta = last.ask_qty - first.ask_qty
        
        queue_pressure = 0.0
        if abs(bid_delta) + abs(ask_delta) > 0:
            queue_pressure = (bid_delta - ask_delta) / (abs(bid_delta) + abs(ask_delta))
        
        # 价格动量
        price_delta = last.price - first.price
        momentum_ticks = int(round(price_delta / self.cfg.tick_size))
        
        # 成交量增长
        volume_increase = last.volume - first.volume
        
        # 综合压力
        combined_pressure = (
            market_pressure * 0.5 +
            queue_pressure * 0.3 +
            (1 if momentum_ticks > 0 else -1 if momentum_ticks < 0 else 0) * 0.2
        )
        
        confidence = min(1.0, volume_increase / 10000.0)
        
        return {
            "pressure": combined_pressure,
            "momentum_ticks": momentum_ticks,
            "volume_increase": volume_increase,
            "confidence": confidence,
            "market_pressure": market_pressure,
            "queue_pressure": queue_pressure,
        }
    
    def _calc_depth_imbalance(self, board: Dict[str, Any]) -> float:
        bids = board.get("bids", [])
        asks = board.get("asks", [])
        
        b = sum(size for _, size in bids[:self.cfg.depth_levels])
        a = sum(size for _, size in asks[:self.cfg.depth_levels])
        
        total = b + a
        if total <= 0:
            return 0.0
        return (b - a) / total
    
    def _maybe_trade(self, now: datetime, board: Dict[str, Any]) -> None:
        if not board:
            return
        
        if self.last_signal_time is not None:
            dt = (now - self.last_signal_time).total_seconds()
            if dt < self.cfg.signal_cooldown_seconds:
                return
        
        flow_metrics = self._calculate_order_flow_pressure()
        pressure = flow_metrics["pressure"]
        momentum = flow_metrics["momentum_ticks"]
        volume_inc = flow_metrics["volume_increase"]
        confidence = flow_metrics["confidence"]
        
        depth_imb = self._calc_depth_imbalance(board)
        
        if volume_inc < self.cfg.min_volume_increase:
            return
        
        best_bid = float(board["best_bid"])
        best_ask = float(board["best_ask"])
        
        # ✅修复: 提升置信度阈值至0.6 (60%)
        if (
            pressure >= self.cfg.buy_pressure_threshold
            and momentum >= self.cfg.min_price_momentum_ticks
            and depth_imb >= self.cfg.depth_imbalance_long
            and confidence >= 0.6  # ← 从0.3提升到0.6
        ):
            self._enter_long(best_ask, now, flow_metrics)

        elif (
            pressure <= self.cfg.sell_pressure_threshold
            and momentum <= -self.cfg.min_price_momentum_ticks
            and depth_imb <= self.cfg.depth_imbalance_short
            and confidence >= 0.6  # ← 从0.3提升到0.6
        ):
            self._enter_short(best_bid, now, flow_metrics)
    
    def _enter_long(self, price: float, now: datetime, metrics: Dict) -> None:
        if abs(self.position) >= self.cfg.max_position:
            return
        
        qty = min(self.cfg.lot_size, self.cfg.max_position - abs(self.position))
        aggressive_price = price + self.cfg.tick_size
        
        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.ORDER_FLOW,
                "BUY",
                aggressive_price,
                qty,
                f"订单流做多(压力={metrics['pressure']:.2f})"
            )
            if not can_exec:
                return
        
        from engine.meta_strategy_manager import StrategyType
        order_id = self.gateway.send_order(
            symbol=self.cfg.symbol,
            side="BUY",
            price=aggressive_price,
            qty=qty,
            order_type="LIMIT",
            strategy_type=StrategyType.ORDER_FLOW,  # ← 新增：标识订单来源
        )

        self.active_order_id = order_id
        self.last_signal_time = now
        
        logger.info(f"{self.cfg.log_prefix} 做多 {qty}@{aggressive_price:.1f}")
    
    def _enter_short(self, price: float, now: datetime, metrics: Dict) -> None:
        if abs(self.position) >= self.cfg.max_position:
            return
        
        qty = min(self.cfg.lot_size, self.cfg.max_position - abs(self.position))
        aggressive_price = price - self.cfg.tick_size
        
        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.ORDER_FLOW,
                "SELL",
                aggressive_price,
                qty,
                f"订单流做空(压力={metrics['pressure']:.2f})"
            )
            if not can_exec:
                return
        
        from engine.meta_strategy_manager import StrategyType
        order_id = self.gateway.send_order(
            symbol=self.cfg.symbol,
            side="SELL",
            price=aggressive_price,
            qty=qty,
            order_type="LIMIT",
            strategy_type=StrategyType.ORDER_FLOW,  # ← 新增：标识订单来源
        )
        
        self.active_order_id = order_id
        self.last_signal_time = now
        
        logger.info(f"{self.cfg.log_prefix} 做空 {qty}@{aggressive_price:.1f}")
    
    def _manage_position(self, now: datetime, board: Dict[str, Any]) -> None:
        """✅新策略: 盈利立即锁定，亏损硬扛"""
        if self.position == 0 or not board or self.avg_price is None:
            return

        last_price = float(board["last_price"])
        pnl_ticks = (last_price - self.avg_price) / self.cfg.tick_size

        if self.position < 0:
            pnl_ticks = -pnl_ticks

        reason = None

        # ========== 新策略: 盈利≥1tick开始追踪，缩水立即平仓，亏损硬扛 ==========
        if self.cfg.enable_dynamic_exit:
            # ✅修改: 只有盈利≥1 tick才开始追踪止盈
            if pnl_ticks >= 1.0:
                # 初始化或更新最优价格
                if self.best_profit_price is None:
                    self.best_profit_price = last_price
                    logger.debug(f"{self.cfg.log_prefix} [锁定盈利] 盈利达到1T，开始追踪，当前盈利={pnl_ticks:.1f}T")
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
            self._close_position(reason, board)
    
    def _close_position(self, reason: str, board: Dict[str, Any]) -> None:
        if self.position == 0 or not board:
            return
        
        qty = abs(self.position)
        
        if self.position > 0:
            side = "SELL"
            price = float(board["best_bid"]) - self.cfg.tick_size
        else:
            side = "BUY"
            price = float(board["best_ask"]) + self.cfg.tick_size
        
        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.ORDER_FLOW, side, price, qty, reason
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
            strategy_type=StrategyType.ORDER_FLOW,  # ← 新增：标识订单来源
        )

        logger.info(f"{self.cfg.log_prefix} 平仓 {side} {qty}@{price:.1f}, reason={reason}")
    
    def on_fill(self, fill: Dict[str, Any]) -> None:
        if fill.get("symbol") != self.cfg.symbol:
            return

        # ← 新增：检查订单归属，只处理自己的订单
        from engine.meta_strategy_manager import StrategyType
        if fill.get("strategy_type") != StrategyType.ORDER_FLOW:
            return  # 不是订单流策略的订单，忽略

        side = fill["side"]
        size = int(fill.get("size", fill.get("quantity", 0)))
        price = float(fill["price"])
        
        prev_pos = self.position
        new_pos = prev_pos + size if side == "BUY" else prev_pos - size
        
        if prev_pos == 0 and new_pos != 0:
            self.avg_price = price
            self.entry_time = datetime.now()
            self.best_profit_price = None  # ✅重置动态止盈状态
        elif prev_pos * new_pos > 0:
            self.avg_price = (self.avg_price * abs(prev_pos) + price * size) / abs(new_pos)
        elif prev_pos != 0 and new_pos == 0:
            self.avg_price = None
            self.entry_time = None
            self.best_profit_price = None  # ✅重置动态止盈状态
        
        self.position = new_pos
        
        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            self.meta.on_fill(StrategyType.ORDER_FLOW, side, price, size)
    
    def on_order_update(self, order: Dict[str, Any]) -> None:
        if order.get("symbol") != self.cfg.symbol:
            return
        
        if order.get("order_id") == self.active_order_id:
            status = order.get("status", "")
            if status in ("CANCELLED", "REJECTED", "FILLED"):
                self.active_order_id = None
