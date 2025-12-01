# -*- coding: utf-8 -*-
"""
integrated_trading_system.py - 修复版

主要修复:
1. 使用修复后的数据转换器
2. 统一gateway为同步接口
3. 使用替代订单流策略
"""

from __future__ import annotations
import asyncio
from typing import Dict, Any
from datetime import datetime
import logging

from engine.meta_strategy_manager import MetaStrategyManager, MetaStrategyConfig, StrategyType
from strategy.hft.market_making_strategy import MarketMakingStrategy, MarketMakingConfig
from strategy.hft.liquidity_taker_scalper import KabuLiquidityTakerScalper, LiquidityTakerConfig
from strategy.hft.orderflow_alternative_strategy import OrderFlowAlternativeStrategy, OrderFlowAlternativeConfig
from utils.kabu_data_converter_fixed import convert_kabu_board_to_standard

logger = logging.getLogger(__name__)


class IntegratedTradingSystem:
    """整合交易系统 - 修复版"""
    
    def __init__(
        self,
        gateway,
        symbol: str = "4680",
        tick_size: float = 0.1,
    ):
        self.gateway = gateway
        self.symbol = symbol
        self.tick_size = tick_size
        
        meta_config = MetaStrategyConfig(
            symbol=symbol,
            board_symbol=symbol,
            total_capital=15_000_000.0,
            max_total_position=400,
            daily_loss_limit=500_000.0,
            strategy_loss_limit=100_000.0,
            profit_target=200_000.0,
            position_reduce_ratio=0.5,
        )
        
        self.meta_manager = MetaStrategyManager(meta_config)
        self._init_strategies()
        
        logger.info("整合交易系统已初始化")
    
    def _init_strategies(self):
        """初始化三个子策略"""
        
        # 1. 做市策略
        mm_config = MarketMakingConfig(
            symbol=self.symbol,
            board_symbol=self.symbol,
            tick_size=self.tick_size,
            lot_size=100,
            max_long_position=100,
            take_profit_ticks=2,
            stop_loss_ticks=100,
        )
        self.mm_strategy = MarketMakingStrategy(
            self.gateway, mm_config, self.meta_manager
        )
        
        # 2. 流动性抢占策略
        lt_config = LiquidityTakerConfig(
            symbol=self.symbol,
            board_symbol=self.symbol,
            tick_size=self.tick_size,
            order_volume=100,
            max_position=100,
            take_profit_ticks=2,
            stop_loss_ticks=100,
            time_stop_seconds=5,
        )
        self.lt_strategy = KabuLiquidityTakerScalper(
            self.gateway, lt_config, self.meta_manager
        )
        
        # 3. ✅修复:使用替代订单流策略
        of_config = OrderFlowAlternativeConfig(
            symbol=self.symbol,
            board_symbol=self.symbol,
            tick_size=self.tick_size,
            lot_size=100,
            max_position=100,
            take_profit_ticks=2,
            stop_loss_ticks=100,
            time_stop_seconds=5,
        )
        self.of_strategy = OrderFlowAlternativeStrategy(
            self.gateway, of_config, self.meta_manager
        )
        
        logger.info("三个子策略已初始化完成")
    
    def on_board(self, board: Dict[str, Any]) -> None:
        """板行情回调"""
        if "last_price" in board:
            self.meta_manager.update_unrealized_pnl(board["last_price"])
        
        self.mm_strategy.on_board(board)
        self.lt_strategy.on_board(board)
        self.of_strategy.on_board(board)
        
        self.meta_manager.reset_daily_stats()
    
    def on_fill(self, fill: Dict[str, Any]) -> None:
        """成交回报"""
        self.mm_strategy.on_fill(fill)
        self.lt_strategy.on_fill(fill)
        self.of_strategy.on_fill(fill)
    
    def on_order_update(self, order: Dict[str, Any]) -> None:
        """订单状态更新"""
        self.mm_strategy.on_order_update(order)
        self.lt_strategy.on_order_update(order)
        self.of_strategy.on_order_update(order)
    
    def get_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        meta_status = self.meta_manager.get_status()
        
        return {
            "timestamp": datetime.now().isoformat(),
            "symbol": self.symbol,
            **meta_status,
        }
    
    def print_status(self) -> None:
        """打印系统状态"""
        status = self.get_status()
        
        print("\n" + "=" * 80)
        print("整合交易系统状态")
        print("=" * 80)
        
        print(f"标的: {status['symbol']}")
        print(f"时间: {status['timestamp']}")
        print()
        
        print("全局状态:")
        print(f"  总仓位: {status['total_position']} 股")
        print(f"  已实现盈亏: {status['total_realized_pnl']:+,.0f} 日元")
        print(f"  未实现盈亏: {status['total_unrealized_pnl']:+,.0f} 日元")
        print(f"  当日盈亏: {status['daily_pnl']:+,.0f} 日元")
        print(f"  仓位缩减: {'是' if status['position_reduced'] else '否'}")
        print()
        
        print("各策略状态:")
        for name, sdata in status['strategies'].items():
            enabled_str = "✓" if sdata['enabled'] else "✗"
            print(f"\n  {name} {enabled_str}")
            print(f"    仓位: {sdata['position']} / {sdata['max_position']} 股")
            print(f"    权重: {sdata['weight']:.1%}")
            print(f"    已实现: {sdata['realized_pnl']:+,.0f} 日元")
            print(f"    未实现: {sdata['unrealized_pnl']:+,.0f} 日元")
            print(f"    胜率: {sdata['win_rate']:.1%} ({sdata['trade_count']}笔)")
        
        print("=" * 80)
