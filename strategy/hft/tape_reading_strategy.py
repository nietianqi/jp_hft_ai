# -*- coding: utf-8 -*-
"""
tape_reading_strategy.py - 盘口统计订单流策略（增强版）

核心思路:
1. 深度分析挂单厚度变化
2. 主动买卖成交量统计
3. 大单检测（异常订单量）
4. 价格穿透力分析
5. 持仓几秒~几十秒
"""

from __future__ import annotations
from dataclasses import dataclass
from collections import deque
from typing import Deque, Optional, Dict, Any, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class TapeReadingConfig:
    symbol: str
    board_symbol: str
    tick_size: float = 0.1
    lot_size: int = 100

    # 盘口分析参数
    depth_levels: int = 5               # 分析5档深度
    tape_window_seconds: int = 10       # 10秒tape window

    # 挂单厚度阈值
    bid_ask_imbalance_threshold: float = 0.6  # 买卖挂单不平衡度60%
    depth_delta_threshold: int = 500    # 单档挂单变化500股

    # 大单检测
    large_order_threshold: int = 500    # 500股算大单
    large_order_window_seconds: int = 5 # 5秒内大单统计

    # 价格穿透力
    penetration_ratio_threshold: float = 0.7  # 穿透比例70%

    # 成交量分析
    volume_surge_ratio: float = 2.0     # 成交量激增2倍
    min_volume_for_signal: int = 1000   # 最小成交量1000股

    # 风险控制
    max_position: int = 100
    enable_dynamic_exit: bool = True
    dynamic_profit_threshold_ticks: float = 3.0
    dynamic_reversal_ticks: float = 1.5

    take_profit_ticks: int = 5
    stop_loss_ticks: int = 10
    time_stop_seconds: int = 20         # 20秒时间止损

    signal_cooldown_seconds: float = 1.5

    log_prefix: str = "[TAPE]"


@dataclass
class DepthSnapshot:
    """深度快照"""
    ts: datetime
    bid_levels: List[tuple[float, int]]  # (价格, 数量)
    ask_levels: List[tuple[float, int]]
    last_price: float


@dataclass
class LargeOrder:
    """大单记录"""
    ts: datetime
    side: str  # BUY/SELL
    price: float
    quantity: int


class TapeReadingStrategy:
    """盘口统计订单流策略"""

    def __init__(self, gateway, config: TapeReadingConfig, meta_manager=None):
        self.gateway = gateway
        self.cfg = config
        self.meta = meta_manager

        self.board: Optional[Dict[str, Any]] = None

        # 深度历史
        self.depth_history: Deque[DepthSnapshot] = deque()

        # 大单记录
        self.large_orders: Deque[LargeOrder] = deque()

        # 持仓
        self.position: int = 0
        self.avg_price: Optional[float] = None
        self.entry_time: Optional[datetime] = None

        self.active_order_id: Optional[str] = None
        self.last_signal_time: Optional[datetime] = None

        # 动态止盈
        self.best_profit_price: Optional[float] = None

        # 上一次深度（用于检测挂单变化）
        self.prev_depth: Optional[DepthSnapshot] = None

    def on_board(self, board: Dict[str, Any]) -> None:
        if board.get("symbol") != self.cfg.board_symbol:
            return

        self.board = board
        now = board["timestamp"]

        # 记录深度快照
        snapshot = self._capture_depth_snapshot(now, board)
        if snapshot:
            self.depth_history.append(snapshot)

            # 保留窗口内数据
            cutoff = now - timedelta(seconds=self.cfg.tape_window_seconds)
            while self.depth_history and self.depth_history[0].ts < cutoff:
                self.depth_history.popleft()

        # 检测大单
        self._detect_large_orders(now, board)

        # 检查入场信号
        if self.position == 0:
            self._check_entry_signal(now)

        # 检查出场
        last_price = float(board["last_price"])
        self._check_exit(now, last_price)

        # 更新前一次深度
        self.prev_depth = snapshot

    def _capture_depth_snapshot(self, ts: datetime, board: Dict[str, Any]) -> Optional[DepthSnapshot]:
        """捕获深度快照"""
        bids = board.get("bids", [])
        asks = board.get("asks", [])

        if not bids or not asks:
            return None

        return DepthSnapshot(
            ts=ts,
            bid_levels=bids[:self.cfg.depth_levels],
            ask_levels=asks[:self.cfg.depth_levels],
            last_price=float(board["last_price"]),
        )

    def _detect_large_orders(self, now: datetime, board: Dict[str, Any]) -> None:
        """检测大单"""
        buy_market = int(board.get("buy_market_order", 0))
        sell_market = int(board.get("sell_market_order", 0))

        # 检测买方大单
        if buy_market >= self.cfg.large_order_threshold:
            self.large_orders.append(LargeOrder(
                ts=now,
                side="BUY",
                price=float(board["best_ask"]),
                quantity=buy_market,
            ))

        # 检测卖方大单
        if sell_market >= self.cfg.large_order_threshold:
            self.large_orders.append(LargeOrder(
                ts=now,
                side="SELL",
                price=float(board["best_bid"]),
                quantity=sell_market,
            ))

        # 保留窗口内数据
        cutoff = now - timedelta(seconds=self.cfg.large_order_window_seconds)
        while self.large_orders and self.large_orders[0].ts < cutoff:
            self.large_orders.popleft()

    def _check_entry_signal(self, now: datetime) -> None:
        """检查入场信号"""
        if not self.board or len(self.depth_history) < 2:
            return

        # 冷却期检查
        if self.last_signal_time:
            elapsed = (now - self.last_signal_time).total_seconds()
            if elapsed < self.cfg.signal_cooldown_seconds:
                return

        # 分析盘口
        tape_metrics = self._analyze_tape()

        # 做多信号:
        # 1. 买盘厚度优势
        # 2. 买方大单多
        # 3. 价格向上穿透力强
        if (
            tape_metrics["bid_ask_imbalance"] >= self.cfg.bid_ask_imbalance_threshold
            and tape_metrics["buy_large_orders"] > tape_metrics["sell_large_orders"]
            and tape_metrics["upward_penetration"] >= self.cfg.penetration_ratio_threshold
            and tape_metrics["total_volume"] >= self.cfg.min_volume_for_signal
        ):
            self._enter_long(now, tape_metrics)

        # 做空信号: (相反)
        elif (
            tape_metrics["bid_ask_imbalance"] <= -self.cfg.bid_ask_imbalance_threshold
            and tape_metrics["sell_large_orders"] > tape_metrics["buy_large_orders"]
            and tape_metrics["downward_penetration"] >= self.cfg.penetration_ratio_threshold
            and tape_metrics["total_volume"] >= self.cfg.min_volume_for_signal
        ):
            self._enter_short(now, tape_metrics)

    def _analyze_tape(self) -> Dict[str, Any]:
        """分析盘口tape"""
        if not self.depth_history:
            return {}

        latest = self.depth_history[-1]

        # 1. 计算买卖挂单不平衡度
        total_bid_qty = sum(qty for _, qty in latest.bid_levels)
        total_ask_qty = sum(qty for _, qty in latest.ask_levels)

        if total_bid_qty + total_ask_qty > 0:
            imbalance = (total_bid_qty - total_ask_qty) / (total_bid_qty + total_ask_qty)
        else:
            imbalance = 0.0

        # 2. 统计大单
        buy_large = sum(1 for order in self.large_orders if order.side == "BUY")
        sell_large = sum(1 for order in self.large_orders if order.side == "SELL")

        # 3. 计算价格穿透力
        upward_pen, downward_pen = self._calculate_penetration()

        # 4. 成交量统计
        total_volume = sum(order.quantity for order in self.large_orders)

        return {
            "bid_ask_imbalance": imbalance,
            "buy_large_orders": buy_large,
            "sell_large_orders": sell_large,
            "upward_penetration": upward_pen,
            "downward_penetration": downward_pen,
            "total_volume": total_volume,
        }

    def _calculate_penetration(self) -> tuple[float, float]:
        """计算价格穿透力"""
        if len(self.depth_history) < 2:
            return 0.0, 0.0

        # 统计价格上穿和下穿的次数
        upward_count = 0
        downward_count = 0
        total_moves = 0

        for i in range(1, len(self.depth_history)):
            prev = self.depth_history[i-1]
            curr = self.depth_history[i]

            if curr.last_price > prev.last_price:
                upward_count += 1
                total_moves += 1
            elif curr.last_price < prev.last_price:
                downward_count += 1
                total_moves += 1

        if total_moves == 0:
            return 0.0, 0.0

        upward_ratio = upward_count / total_moves
        downward_ratio = downward_count / total_moves

        return upward_ratio, downward_ratio

    def _enter_long(self, now: datetime, metrics: Dict) -> None:
        """做多入场"""
        if not self.board or abs(self.position) >= self.cfg.max_position:
            return

        best_ask = float(self.board["best_ask"])
        qty = self.cfg.lot_size

        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.TAPE_READING,
                "BUY",
                best_ask,
                qty,
                f"盘口做多(不平衡={metrics['bid_ask_imbalance']:.2f})",
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
            strategy_type=StrategyType.TAPE_READING,
        )

        self.active_order_id = order_id
        self.last_signal_time = now
        logger.info(f"{self.cfg.log_prefix} 盘口做多 {qty}@{best_ask:.1f}")

    def _enter_short(self, now: datetime, metrics: Dict) -> None:
        """做空入场"""
        if not self.board or abs(self.position) >= self.cfg.max_position:
            return

        best_bid = float(self.board["best_bid"])
        qty = self.cfg.lot_size

        if self.meta:
            from engine.meta_strategy_manager import StrategyType
            can_exec, msg = self.meta.on_signal(
                StrategyType.TAPE_READING,
                "SELL",
                best_bid,
                qty,
                f"盘口做空(不平衡={metrics['bid_ask_imbalance']:.2f})",
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
            strategy_type=StrategyType.TAPE_READING,
        )

        self.active_order_id = order_id
        self.last_signal_time = now
        logger.info(f"{self.cfg.log_prefix} 盘口做空 {qty}@{best_bid:.1f}")

    def _check_exit(self, now: datetime, current_price: float) -> None:
        """✅新策略: 盈利立即锁定，亏损硬扛"""
        if self.position == 0 or self.avg_price is None:
            return

        pnl_ticks = (current_price - self.avg_price) / self.cfg.tick_size
        if self.position < 0:
            pnl_ticks = -pnl_ticks

        reason = None

        # ========== 新策略: 盈利缩水立即平仓，亏损硬扛 ==========
        if self.cfg.enable_dynamic_exit:
            # 只要有盈利（哪怕0.1 tick），就开始追踪
            if pnl_ticks > 0:
                # 初始化或更新最优价格
                if self.best_profit_price is None:
                    self.best_profit_price = current_price
                    logger.debug(f"{self.cfg.log_prefix} [锁定盈利] 开始追踪，当前盈利={pnl_ticks:.1f}T")
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
                StrategyType.TAPE_READING, side, price, qty, reason
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
            strategy_type=StrategyType.TAPE_READING,
        )

        print(f"📤 {self.cfg.log_prefix} [平仓] {reason}: {side} {qty}@{price:.1f}")

    def on_fill(self, fill: Dict[str, Any]) -> None:
        if fill.get("symbol") != self.cfg.symbol:
            return

        from engine.meta_strategy_manager import StrategyType
        if fill.get("strategy_type") != StrategyType.TAPE_READING:
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
            self.meta.on_fill(StrategyType.TAPE_READING, side, price, size)

    def on_order_update(self, order: Dict[str, Any]) -> None:
        if order.get("symbol") != self.cfg.symbol:
            return

        if order.get("order_id") == self.active_order_id:
            status = order.get("status", "")
            if status in ("CANCELLED", "REJECTED", "FILLED"):
                self.active_order_id = None
