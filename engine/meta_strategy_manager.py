# -*- coding: utf-8 -*-
"""
meta_strategy_manager.py

元策略管理器 - 综合三个策略的信号并智能分配仓位
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from enum import IntEnum
import logging

logger = logging.getLogger(__name__)


class StrategyType(IntEnum):
    """策略类型枚举"""
    MARKET_MAKING = 0
    LIQUIDITY_TAKER = 1
    ORDER_FLOW = 2


@dataclass
class MetaStrategyConfig:
    """元策略配置"""
    symbol: str
    board_symbol: str
    total_capital: float = 15_000_000.0
    max_total_position: int = 400
    strategy_weights: Dict[StrategyType, float] = None
    daily_loss_limit: float = 500_000.0
    strategy_loss_limit: float = 100_000.0
    profit_target: float = 200_000.0
    position_reduce_ratio: float = 0.5
    performance_window: int = 100
    rebalance_interval: int = 50
    
    def __post_init__(self):
        if self.strategy_weights is None:
            self.strategy_weights = {
                StrategyType.MARKET_MAKING: 0.3,
                StrategyType.LIQUIDITY_TAKER: 0.4,
                StrategyType.ORDER_FLOW: 0.3,
            }


@dataclass
class StrategyState:
    """单个策略的状态"""
    strategy_type: StrategyType
    enabled: bool = True
    position: int = 0
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    weight: float = 0.33
    max_position: int = 100
    trade_count: int = 0
    win_count: int = 0
    total_profit: float = 0.0
    total_loss: float = 0.0
    recent_pnls: List[float] = None
    
    def __post_init__(self):
        if self.recent_pnls is None:
            self.recent_pnls = []


class MetaStrategyManager:
    """元策略管理器"""
    
    def __init__(self, config: MetaStrategyConfig):
        self.cfg = config
        
        self.strategies: Dict[StrategyType, StrategyState] = {
            StrategyType.MARKET_MAKING: StrategyState(
                strategy_type=StrategyType.MARKET_MAKING,
                weight=config.strategy_weights[StrategyType.MARKET_MAKING],
            ),
            StrategyType.LIQUIDITY_TAKER: StrategyState(
                strategy_type=StrategyType.LIQUIDITY_TAKER,
                weight=config.strategy_weights[StrategyType.LIQUIDITY_TAKER],
            ),
            StrategyType.ORDER_FLOW: StrategyState(
                strategy_type=StrategyType.ORDER_FLOW,
                weight=config.strategy_weights[StrategyType.ORDER_FLOW],
            ),
        }
        
        self.total_position: int = 0
        self.total_realized_pnl: float = 0.0
        self.total_unrealized_pnl: float = 0.0
        self.global_trade_count: int = 0
        self.daily_pnl: float = 0.0
        self.last_trade_date = datetime.now().date()
        self.position_reduced: bool = False
        
        self._update_position_limits()
    
    def _update_position_limits(self):
        """根据权重更新各策略的仓位限制"""
        for stype, state in self.strategies.items():
            if self.position_reduced:
                max_pos = int(
                    self.cfg.max_total_position 
                    * state.weight 
                    * self.cfg.position_reduce_ratio
                )
            else:
                max_pos = int(self.cfg.max_total_position * state.weight)
            
            state.max_position = max(100, max_pos)
    
    def can_execute_signal(
        self,
        strategy_type: StrategyType,
        side: str,
        quantity: int,
    ) -> tuple[bool, str]:
        """判断是否可以执行某个策略的信号 - 修复版"""
        state = self.strategies[strategy_type]

        if not state.enabled:
            return False, f"{strategy_type.name} 已禁用"

        if state.realized_pnl <= -self.cfg.strategy_loss_limit:
            return False, f"{strategy_type.name} 达到日亏损限额"

        if self.daily_pnl <= -self.cfg.daily_loss_limit:
            return False, "全局达到日亏损限额"

        # ✅ 修复: 先检查当前仓位绝对值是否已达上限
        current_abs_pos = abs(state.position)
        if current_abs_pos >= state.max_position:
            # 只允许平仓方向的订单
            is_closing = (side == "SELL" and state.position > 0) or \
                         (side == "BUY" and state.position < 0)
            if not is_closing:
                return False, f"{strategy_type.name} 仓位已达上限{state.max_position},仅允许平仓"

        # ✅ 修复: 计算新仓位并检查绝对值
        if side == "BUY":
            new_pos = state.position + quantity
        else:
            new_pos = state.position - quantity

        # ✅ 修复: 检查新仓位的绝对值 - 允许减仓
        if abs(new_pos) > state.max_position:
            # 允许减仓：如果新仓位的绝对值 < 当前仓位的绝对值
            is_reducing = abs(new_pos) < abs(state.position)
            if not is_reducing:
                return False, f"{strategy_type.name} 新仓位{abs(new_pos)}超过限额{state.max_position}"

        # ✅ 修复: 检查总仓位的绝对值 - 允许减仓
        new_total = self.total_position + (quantity if side == "BUY" else -quantity)

        # 如果新仓位超限，检查是否为减仓方向
        if abs(new_total) > self.cfg.max_total_position:
            # 允许减仓：如果新仓位的绝对值 < 当前仓位的绝对值
            is_reducing = abs(new_total) < abs(self.total_position)
            if not is_reducing:
                return False, f"总仓位{abs(new_total)}超限{self.cfg.max_total_position}"

        return True, "OK"
    
    def on_signal(
        self,
        strategy_type: StrategyType,
        side: str,
        price: float,
        quantity: int,
        reason: str = "",
    ) -> tuple[bool, str]:
        """接收策略信号，决定是否执行"""
        can_exec, msg = self.can_execute_signal(strategy_type, side, quantity)
        
        if can_exec:
            logger.info(
                f"[META] 允许执行 {strategy_type.name} {side} {quantity}@{price:.1f} - {reason}"
            )
        else:
            logger.warning(
                f"[META] 拒绝执行 {strategy_type.name} {side} {quantity}@{price:.1f} - {msg}"
            )
        
        return can_exec, msg
    
    def on_fill(
        self,
        strategy_type: StrategyType,
        side: str,
        price: float,
        quantity: int,
    ):
        """更新策略持仓和盈亏"""
        state = self.strategies[strategy_type]
        
        prev_pos = state.position
        
        if side == "BUY":
            new_pos = prev_pos + quantity
        else:
            new_pos = prev_pos - quantity
        
        if prev_pos == 0 and new_pos != 0:
            state.avg_price = price
        elif prev_pos * new_pos > 0:
            state.avg_price = (
                state.avg_price * abs(prev_pos) + price * quantity
            ) / abs(new_pos)
        elif prev_pos != 0 and new_pos == 0:
            direction = 1 if prev_pos > 0 else -1
            pnl = (price - state.avg_price) * abs(prev_pos) * direction
            
            state.realized_pnl += pnl
            state.recent_pnls.append(pnl)
            
            if len(state.recent_pnls) > self.cfg.performance_window:
                state.recent_pnls.pop(0)
            
            state.trade_count += 1
            if pnl > 0:
                state.win_count += 1
                state.total_profit += pnl
            else:
                state.total_loss += abs(pnl)
            
            self.daily_pnl += pnl
            self.total_realized_pnl += pnl
            self.global_trade_count += 1
            
            logger.info(
                f"[META] {strategy_type.name} 平仓 pnl={pnl:.0f}, "
                f"累计={state.realized_pnl:.0f}, "
                f"胜率={state.win_count}/{state.trade_count}"
            )
            
            if state.realized_pnl <= -self.cfg.strategy_loss_limit:
                state.enabled = False
                logger.warning(
                    f"[META] {strategy_type.name} 达到亏损限额，已禁用"
                )
            
            if self.daily_pnl >= self.cfg.profit_target and not self.position_reduced:
                self.position_reduced = True
                self._update_position_limits()
                logger.info(
                    f"[META] 达到盈利目标 {self.daily_pnl:.0f}，缩减仓位至50%"
                )
            
            state.avg_price = 0.0
        
        state.position = new_pos
        self.total_position = sum(s.position for s in self.strategies.values())
        
        if self.global_trade_count % self.cfg.rebalance_interval == 0:
            self._rebalance_weights()
    
    def _rebalance_weights(self):
        """根据策略表现重新平衡权重"""
        sharpes = {}
        total_sharpe = 0.0
        
        for stype, state in self.strategies.items():
            if not state.enabled or len(state.recent_pnls) < 10:
                sharpes[stype] = 0.0
                continue
            
            avg_pnl = sum(state.recent_pnls) / len(state.recent_pnls)
            std_pnl = (
                sum((x - avg_pnl) ** 2 for x in state.recent_pnls) 
                / len(state.recent_pnls)
            ) ** 0.5
            
            if std_pnl > 0:
                sharpe = avg_pnl / std_pnl
                sharpes[stype] = max(0, sharpe)
                total_sharpe += sharpes[stype]
            else:
                sharpes[stype] = 0.0
        
        if total_sharpe > 0:
            for stype, state in self.strategies.items():
                old_weight = state.weight
                new_weight = sharpes[stype] / total_sharpe
                state.weight = old_weight * 0.7 + new_weight * 0.3
                state.weight = max(0.1, min(0.6, state.weight))
            
            total_w = sum(s.weight for s in self.strategies.values())
            for state in self.strategies.values():
                state.weight /= total_w
            
            self._update_position_limits()
    
    def update_unrealized_pnl(self, current_price: float):
        """更新未实现盈亏"""
        total_unrealized = 0.0
        
        for state in self.strategies.values():
            if state.position != 0 and state.avg_price > 0:
                direction = 1 if state.position > 0 else -1
                pnl = (current_price - state.avg_price) * abs(state.position) * direction
                state.unrealized_pnl = pnl
                total_unrealized += pnl
        
        self.total_unrealized_pnl = total_unrealized
    
    def get_status(self) -> Dict[str, Any]:
        """获取元策略状态"""
        return {
            "total_position": self.total_position,
            "total_realized_pnl": self.total_realized_pnl,
            "total_unrealized_pnl": self.total_unrealized_pnl,
            "daily_pnl": self.daily_pnl,
            "position_reduced": self.position_reduced,
            "strategies": {
                stype.name: {
                    "enabled": state.enabled,
                    "position": state.position,
                    "weight": state.weight,
                    "max_position": state.max_position,
                    "realized_pnl": state.realized_pnl,
                    "unrealized_pnl": state.unrealized_pnl,
                    "win_rate": state.win_count / state.trade_count if state.trade_count > 0 else 0,
                    "trade_count": state.trade_count,
                }
                for stype, state in self.strategies.items()
            }
        }
    
    def reset_daily_stats(self):
        """重置每日统计"""
        today = datetime.now().date()
        if today != self.last_trade_date:
            self.daily_pnl = 0.0
            self.position_reduced = False
            self.last_trade_date = today
            
            for state in self.strategies.values():
                state.enabled = True
            
            logger.info("[META] 新交易日开始，统计已重置")
