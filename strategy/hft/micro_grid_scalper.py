# -*- coding: utf-8 -*-
"""
micro_grid_scalper.py - 微网格震荡剥头皮策略

核心思路:
1. 识别震荡区间（支撑/阻力）
2. 在区间内设置密集网格
3. 低买高卖，吃1-5个tick
4. 持仓时间: 几秒~几分钟
"""

from __future__ import annotations
from dataclasses import dataclass
from collections import deque
from typing import Deque, Optional, Dict, Any, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class MicroGridConfig:
    symbol: str
    board_symbol: str
    tick_size: float = 0.1
    lot_size: int = 100

    # 网格参数
    grid_spacing_ticks: int = 2         # 网格间距2 ticks
    grid_levels: int = 5                # 上下各5档网格
    grid_profit_target_ticks: int = 2   # 每格利润2 ticks

    # 区间识别
    range_detect_window_seconds: int = 60  # 60秒识别区间
    range_volatility_threshold: float = 0.003  # 波动率<0.3%认为震荡
    min_price_samples: int = 30

    # 风险控制
    max_position: int = 300             # 最大持仓（允许多个网格同时持仓）
    max_grid_position: int = 100        # 单个网格最大持仓
    enable_dynamic_exit: bool = True    # 使用动态止盈
    dynamic_profit_threshold_ticks: float = 3.0
    dynamic_reversal_ticks: float = 1.5

    # 传统止盈止损
    take_profit_ticks: int = 5
    stop_loss_ticks: int = 10

    log_prefix: str = "[GRID]"


@dataclass
class PricePoint:
    ts: datetime
    price: float


@dataclass
class GridLevel:
    """网格档位"""
    level: int              # 档位编号 (0为中心，正数向上，负数向下)
    buy_price: float        # 买入价
    sell_price: float       # 卖出价
    position: int = 0       # 该档位持仓
    avg_price: float = 0.0  # 该档位平均成本
    order_id: Optional[str] = None


class MicroGridScalper:
    """微网格剥头皮策略"""

    def __init__(self, gateway, config: MicroGridConfig, meta_manager=None):
        self.gateway = gateway
        self.cfg = config
        self.meta = meta_manager

        self.board: Optional[Dict[str, Any]] = None
        self.price_history: Deque[PricePoint] = deque()

        # 网格状态
        self.grid_center: Optional[float] = None
        self.grid_range_top: Optional[float] = None
        self.grid_range_bottom: Optional[float] = None
        self.grid_levels: Dict[int, GridLevel] = {}

        # 总持仓
        self.total_position: int = 0

        # 动态止盈状态
        self.best_profit_price: Optional[float] = None

        # 区间检测
        self.last_range_update: Optional[datetime] = None
        self.is_ranging: bool = False

    def on_board(self, board: Dict[str, Any]) -> None:
        if board.get("symbol") != self.cfg.board_symbol:
            return

        self.board = board
        now = board["timestamp"]
        last_price = float(board["last_price"])

        # 更新价格历史
        self._update_price_history(now, last_price)

        # 检测震荡区间
        self._detect_ranging_market(now)

        if self.is_ranging:
            # 更新网格
            self._update_grid_levels()

            # 检查网格交易机会
            self._check_grid_trades()

        # 检查止盈
        self._check_exit(now, last_price)

    def _update_price_history(self, ts: datetime, price: float) -> None:
        self.price_history.append(PricePoint(ts=ts, price=price))
        cutoff = ts - timedelta(seconds=self.cfg.range_detect_window_seconds)
        while self.price_history and self.price_history[0].ts < cutoff:
            self.price_history.popleft()

    def _detect_ranging_market(self, now: datetime) -> None:
        """检测是否处于震荡市"""
        if len(self.price_history) < self.cfg.min_price_samples:
            self.is_ranging = False
            return

        # 每10秒更新一次区间判断
        if self.last_range_update and (now - self.last_range_update).total_seconds() < 10:
            return

        self.last_range_update = now

        prices = [p.price for p in self.price_history]
        mean_price = sum(prices) / len(prices)
        std_dev = (sum((p - mean_price) ** 2 for p in prices) / len(prices)) ** 0.5

        # 计算波动率
        volatility = std_dev / mean_price if mean_price > 0 else 0

        # 判断是否震荡
        if volatility < self.cfg.range_volatility_threshold:
            self.is_ranging = True

            # 更新区间
            self.grid_range_top = max(prices)
            self.grid_range_bottom = min(prices)
            self.grid_center = mean_price

            logger.info(
                f"{self.cfg.log_prefix} 检测到震荡市场 "
                f"[{self.grid_range_bottom:.1f} - {self.grid_range_top:.1f}] "
                f"波动率={volatility:.4f}"
            )
        else:
            self.is_ranging = False
            logger.debug(f"{self.cfg.log_prefix} 非震荡市场，波动率={volatility:.4f}")

    def _update_grid_levels(self) -> None:
        """更新网格档位"""
        if not self.grid_center:
            return

        # 清空旧网格
        self.grid_levels.clear()

        grid_spacing = self.cfg.grid_spacing_ticks * self.cfg.tick_size
        profit_target = self.cfg.grid_profit_target_ticks * self.cfg.tick_size

        # 创建上下网格
        for i in range(-self.cfg.grid_levels, self.cfg.grid_levels + 1):
            buy_price = self.grid_center + i * grid_spacing
            sell_price = buy_price + profit_target

            # 确保在区间内
            if (self.grid_range_bottom <= buy_price <= self.grid_range_top):
                self.grid_levels[i] = GridLevel(
                    level=i,
                    buy_price=self._round_to_tick(buy_price),
                    sell_price=self._round_to_tick(sell_price),
                )

    def _round_to_tick(self, price: float) -> float:
        """取整到tick"""
        import math
        return round(price / self.cfg.tick_size) * self.cfg.tick_size

    def _check_grid_trades(self) -> None:
        """检查网格交易机会"""
        if not self.board:
            return

        best_bid = float(self.board["best_bid"])
        best_ask = float(self.board["best_ask"])

        # 遍历网格档位
        for level, grid in self.grid_levels.items():
            # 买入信号: 当前价格接近网格买入价
            if abs(best_bid - grid.buy_price) <= self.cfg.tick_size:
                if grid.position == 0 and self.total_position < self.cfg.max_position:
                    self._place_grid_buy(grid)

            # 卖出信号: 该档位有持仓且价格达到目标
            if grid.position > 0 and best_ask >= grid.sell_price:
                self._place_grid_sell(grid)

    def _place_grid_buy(self, grid: GridLevel) -> None:
        """在网格档位买入"""
        qty = self.cfg.lot_size

        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.MICRO_GRID, "BUY", grid.buy_price, qty, f"网格{grid.level}买入"
            )
            if not can_exec:
                return

        from engine.meta_strategy_manager import StrategyType
        order_id = self.gateway.send_order(
            symbol=self.cfg.symbol,
            side="BUY",
            price=grid.buy_price,
            qty=qty,
            order_type="LIMIT",
            strategy_type=StrategyType.MICRO_GRID,
        )

        grid.order_id = order_id
        logger.info(f"{self.cfg.log_prefix} 网格{grid.level} BUY {qty}@{grid.buy_price:.1f}")

    def _place_grid_sell(self, grid: GridLevel) -> None:
        """在网格档位卖出"""
        qty = grid.position

        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.MICRO_GRID, "SELL", grid.sell_price, qty, f"网格{grid.level}止盈"
            )
            if not can_exec:
                return

        from engine.meta_strategy_manager import StrategyType
        order_id = self.gateway.send_order(
            symbol=self.cfg.symbol,
            side="SELL",
            price=grid.sell_price,
            qty=qty,
            order_type="LIMIT",
            strategy_type=StrategyType.MICRO_GRID,
        )

        grid.order_id = order_id
        print(f"✅ {self.cfg.log_prefix} 网格{grid.level} SELL {qty}@{grid.sell_price:.1f} (止盈)")

    def _check_exit(self, now: datetime, current_price: float) -> None:
        """检查整体止盈（当脱离区间时）"""
        if self.total_position == 0:
            return

        # 如果不再震荡，清仓离场
        if not self.is_ranging and self.total_position != 0:
            logger.warning(f"{self.cfg.log_prefix} 脱离震荡区间，清仓离场")
            self._close_all_positions("range_break")

    def _close_all_positions(self, reason: str) -> None:
        """平掉所有网格持仓"""
        if not self.board:
            return

        for grid in self.grid_levels.values():
            if grid.position > 0:
                qty = grid.position
                price = float(self.board["best_bid"])

                from engine.meta_strategy_manager import StrategyType
                order_id = self.gateway.send_order(
                    symbol=self.cfg.symbol,
                    side="SELL",
                    price=price,
                    qty=qty,
                    order_type="LIMIT",
                    strategy_type=StrategyType.MICRO_GRID,
                )

                print(f"📤 {self.cfg.log_prefix} 清仓网格{grid.level}: SELL {qty}@{price:.1f} ({reason})")

    def on_fill(self, fill: Dict[str, Any]) -> None:
        if fill.get("symbol") != self.cfg.symbol:
            return

        from engine.meta_strategy_manager import StrategyType
        if fill.get("strategy_type") != StrategyType.MICRO_GRID:
            return

        side = fill["side"]
        size = int(fill.get("size", fill.get("quantity", 0)))
        price = float(fill["price"])

        # 更新对应网格的持仓
        for grid in self.grid_levels.values():
            if abs(price - grid.buy_price) < self.cfg.tick_size * 0.5:
                if side == "BUY":
                    grid.position += size
                    grid.avg_price = price
                    self.total_position += size
                    logger.info(f"{self.cfg.log_prefix} 网格{grid.level}成交 +{size}@{price:.1f}")
                break

            if abs(price - grid.sell_price) < self.cfg.tick_size * 0.5:
                if side == "SELL":
                    grid.position -= size
                    self.total_position -= size

                    # 计算盈亏
                    pnl = (price - grid.avg_price) * size
                    print(f"💰 {self.cfg.log_prefix} 网格{grid.level}平仓 盈利={pnl:.0f}日元")
                break

        if self.meta:
            self.meta.on_fill(StrategyType.MICRO_GRID, side, price, size)

    def on_order_update(self, order: Dict[str, Any]) -> None:
        if order.get("symbol") != self.cfg.symbol:
            return

        oid = order.get("order_id")
        status = order.get("status", "")

        if status in ("CANCELLED", "REJECTED", "FILLED"):
            # 清除对应网格的订单ID
            for grid in self.grid_levels.values():
                if grid.order_id == oid:
                    grid.order_id = None
                    break
