# -*- coding: utf-8 -*-
"""
market_making_strategy.py - 修复版
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any, Deque
from collections import deque
from datetime import datetime, timedelta
import math
import logging

logger = logging.getLogger(__name__)


@dataclass
class MarketMakingConfig:
    symbol: str
    board_symbol: str
    tick_size: float = 0.1
    lot_size: int = 100
    
    max_long_position: int = 100
    max_short_position: int = 0
    inventory_target: int = 0
    inventory_soft_limit: int = 100
    
    base_spread_ticks: int = 2
    min_spread_ticks: int = 1
    max_spread_ticks: int = 6
    
    vola_window_seconds: int = 10
    vola_to_spread_factor: float = 0.5
    
    inventory_skew_factor_ticks: float = 1.0
    
    quote_refresh_interval: float = 0.5
    price_change_requote_threshold_ticks: int = 1
    
    take_profit_ticks: int = 2
    stop_loss_ticks: int = 100
    panic_spread_multiplier: float = 2.0
    
    log_prefix: str = "[MM]"


@dataclass
class PricePoint:
    ts: datetime
    last_price: float


class MarketMakingStrategy:
    """做市策略"""
    
    def __init__(self, gateway, config: MarketMakingConfig, meta_manager=None):
        self.gateway = gateway
        self.cfg = config
        self.meta = meta_manager
        
        self.board: Optional[Dict[str, Any]] = None
        self.price_window: Deque[PricePoint] = deque()
        
        self.position: int = 0
        self.avg_price: Optional[float] = None
        
        self.bid_order_id: Optional[str] = None
        self.ask_order_id: Optional[str] = None
        self.current_bid_price: Optional[float] = None
        self.current_ask_price: Optional[float] = None
        
        self.last_quote_time: Optional[datetime] = None
        self.entry_time: Optional[datetime] = None
    
    def on_board(self, board: Dict[str, Any]) -> None:
        if board.get("symbol") != self.cfg.board_symbol:
            return
        
        self.board = board
        now: datetime = board["timestamp"]
        last_price: float = float(board["last_price"])
        
        self._update_price_window(now, last_price)
        self._check_exit(now, last_price)
        self._update_quotes(now)
    
    def _update_price_window(self, ts: datetime, last_price: float) -> None:
        self.price_window.append(PricePoint(ts=ts, last_price=last_price))
        cutoff = ts - timedelta(seconds=self.cfg.vola_window_seconds)
        while self.price_window and self.price_window[0].ts < cutoff:
            self.price_window.popleft()
    
    def _estimate_volatility_ticks(self) -> float:
        if len(self.price_window) < 2:
            return 0.0
        
        prices = [p.last_price for p in self.price_window]
        mean_p = sum(prices) / len(prices)
        var = sum((p - mean_p) ** 2 for p in prices) / (len(prices) - 1)
        std = math.sqrt(var)
        return std / self.cfg.tick_size
    
    def _check_exit(self, now: datetime, current_price: float) -> None:
        if self.position == 0 or self.avg_price is None:
            return
        
        pnl_ticks = (current_price - self.avg_price) / self.cfg.tick_size
        if self.position < 0:
            pnl_ticks = -pnl_ticks
        
        reason = None
        if pnl_ticks >= self.cfg.take_profit_ticks:
            reason = "take_profit"
        elif pnl_ticks <= -self.cfg.stop_loss_ticks:
            reason = "stop_loss"
        
        if reason and self.board:
            self._exit_position(reason)
    
    def _exit_position(self, reason: str) -> None:
        if self.position == 0 or not self.board:
            return
        
        qty = abs(self.position)
        if self.position > 0:
            side = "SELL"
            price = float(self.board["best_bid"])
        else:
            side = "BUY"
            price = float(self.board["best_ask"])
        
        # ✅修复:正确的import路径
        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.MARKET_MAKING, side, price, qty, reason
            )
            if not can_exec:
                return
        
        oid = self.gateway.send_order(
            symbol=self.cfg.symbol,
            side=side,
            price=price,
            qty=qty,
            order_type="LIMIT",
        )
    
    def _update_quotes(self, now: datetime) -> None:
        if not self.board:
            return
        
        if self.last_quote_time is not None:
            dt = (now - self.last_quote_time).total_seconds()
            if dt < self.cfg.quote_refresh_interval:
                return
        
        best_bid = float(self.board["best_bid"])
        best_ask = float(self.board["best_ask"])
        
        if best_bid <= 0 or best_ask <= 0 or best_bid >= best_ask:
            self._cancel_all_quotes("abnormal_spread")
            return
        
        mid = (best_bid + best_ask) / 2
        vola_ticks = self._estimate_volatility_ticks()
        
        spread_ticks = self.cfg.base_spread_ticks + int(
            self.cfg.vola_to_spread_factor * vola_ticks
        )
        spread_ticks = max(self.cfg.min_spread_ticks, spread_ticks)
        spread_ticks = min(self.cfg.max_spread_ticks, spread_ticks)
        
        Q = self.position
        Q_max = max(1, self.cfg.inventory_soft_limit)
        inv_ratio = max(-1.0, min(1.0, Q / float(Q_max)))
        
        skew_price = inv_ratio * self.cfg.inventory_skew_factor_ticks * self.cfg.tick_size
        mid_skewed = mid - skew_price
        
        half_spread = spread_ticks * self.cfg.tick_size / 2.0
        bid_target = mid_skewed - half_spread
        ask_target = mid_skewed + half_spread
        
        bid_target = min(bid_target, best_bid)
        ask_target = max(ask_target, best_ask)
        
        bid_target = self._round_down_to_tick(bid_target)
        ask_target = self._round_up_to_tick(ask_target)
        
        if bid_target >= ask_target:
            self._cancel_all_quotes("bid>=ask")
            return
        
        if self.position >= self.cfg.max_long_position:
            bid_target = None
        if self.position <= -self.cfg.max_short_position:
            ask_target = None
        
        self._quote_side(now, "BUY", bid_target)
        self._quote_side(now, "SELL", ask_target)
        
        self.last_quote_time = now
    
    def _round_down_to_tick(self, price: float) -> float:
        ts = self.cfg.tick_size
        return math.floor(price / ts + 1e-9) * ts
    
    def _round_up_to_tick(self, price: float) -> float:
        ts = self.cfg.tick_size
        return math.ceil(price / ts - 1e-9) * ts
    
    def _quote_side(self, now: datetime, side: str, target_price: Optional[float]) -> None:
        if side == "BUY":
            order_id_attr = "bid_order_id"
            price_attr = "current_bid_price"
        else:
            order_id_attr = "ask_order_id"
            price_attr = "current_ask_price"
        
        order_id = getattr(self, order_id_attr)
        current_price = getattr(self, price_attr)
        
        if target_price is None:
            if order_id is not None:
                self.gateway.cancel_order(order_id)
            setattr(self, order_id_attr, None)
            setattr(self, price_attr, None)
            return
        
        if order_id is not None and current_price is not None:
            diff_ticks = abs(target_price - current_price) / self.cfg.tick_size
            if diff_ticks < self.cfg.price_change_requote_threshold_ticks:
                return
            self.gateway.cancel_order(order_id)
            setattr(self, order_id_attr, None)
            setattr(self, price_attr, None)
        
        if getattr(self, order_id_attr) is None:
            qty = self.cfg.lot_size
            
            if self.meta:
                from engine.meta_strategy_manager import StrategyType
                can_exec, msg = self.meta.on_signal(
                    StrategyType.MARKET_MAKING, side, target_price, qty, "做市报价"
                )
                if not can_exec:
                    return
            
            new_order_id = self.gateway.send_order(
                symbol=self.cfg.symbol,
                side=side,
                price=target_price,
                qty=qty,
                order_type="LIMIT",
            )
            setattr(self, order_id_attr, new_order_id)
            setattr(self, price_attr, target_price)
    
    def _cancel_all_quotes(self, reason: str = "") -> None:
        if self.bid_order_id is not None:
            self.gateway.cancel_order(self.bid_order_id)
            self.bid_order_id = None
            self.current_bid_price = None
        
        if self.ask_order_id is not None:
            self.gateway.cancel_order(self.ask_order_id)
            self.ask_order_id = None
            self.current_ask_price = None
    
    def on_fill(self, fill: Dict[str, Any]) -> None:
        if fill.get("symbol") != self.cfg.symbol:
            return
        
        side = fill["side"]
        size = int(fill["size"]) if "size" in fill else int(fill["quantity"])
        price = float(fill["price"])
        
        prev_pos = self.position
        new_pos = prev_pos + size if side == "BUY" else prev_pos - size
        
        if prev_pos == 0 and new_pos != 0:
            self.avg_price = price
            self.entry_time = datetime.now()
        elif prev_pos * new_pos > 0:
            self.avg_price = (self.avg_price * abs(prev_pos) + price * size) / abs(new_pos)
        elif prev_pos != 0 and new_pos == 0:
            self.avg_price = None
            self.entry_time = None
        
        self.position = new_pos
        
        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            self.meta.on_fill(StrategyType.MARKET_MAKING, side, price, size)
    
    def on_order_update(self, order: Dict[str, Any]) -> None:
        if order.get("symbol") != self.cfg.symbol:
            return
        
        oid = order.get("order_id")
        status = order.get("status", "")
        
        if status in ("CANCELLED", "REJECTED", "FILLED"):
            if oid == self.bid_order_id:
                self.bid_order_id = None
                self.current_bid_price = None
            elif oid == self.ask_order_id:
                self.ask_order_id = None
                self.current_ask_price = None
