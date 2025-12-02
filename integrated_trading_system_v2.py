# -*- coding: utf-8 -*-
"""
integrated_trading_system_v2.py - 6策略整合交易系统

新增策略:
1. MicroGridScalper - 微网格震荡剥头皮
2. ShortMomentumFollower - 短周期动量跟随
3. TapeReadingStrategy - 盘口统计订单流

原有策略:
4. MarketMakingStrategy - 做市策略
5. KabuLiquidityTakerScalper - 流动性抢占
6. OrderFlowAlternativeStrategy - 订单流策略
"""

from __future__ import annotations
import asyncio
from typing import Dict, Any
from datetime import datetime
import logging

from engine.meta_strategy_manager import MetaStrategyManager, MetaStrategyConfig, StrategyType

# 原有策略
from strategy.hft.market_making_strategy import MarketMakingStrategy, MarketMakingConfig
from strategy.hft.liquidity_taker_scalper import KabuLiquidityTakerScalper, LiquidityTakerConfig
from strategy.hft.orderflow_alternative_strategy import OrderFlowAlternativeStrategy, OrderFlowAlternativeConfig

# ✅新增策略
from strategy.hft.micro_grid_scalper import MicroGridScalper, MicroGridConfig
from strategy.hft.short_momentum_follower import ShortMomentumFollower, ShortMomentumConfig
from strategy.hft.tape_reading_strategy import TapeReadingStrategy, TapeReadingConfig

from utils.kabu_data_converter_fixed import convert_kabu_board_to_standard

logger = logging.getLogger(__name__)


class IntegratedTradingSystemV2:
    """6策略整合交易系统"""

    def __init__(
        self,
        gateway,
        symbol: str = "4680",
        tick_size: float = 0.1,
    ):
        self.gateway = gateway
        self.symbol = symbol
        self.tick_size = tick_size

        # 元策略管理器
        meta_config = MetaStrategyConfig(
            symbol=symbol,
            board_symbol=symbol,
            total_capital=15_000_000.0,
            max_total_position=600,  # ✅增加至600股 (6个策略)
            daily_loss_limit=500_000.0,
            strategy_loss_limit=100_000.0,
            profit_target=200_000.0,
            position_reduce_ratio=0.5,
        )

        self.meta_manager = MetaStrategyManager(meta_config)
        self._init_strategies()

        logger.info("6策略整合交易系统已初始化")

    def _init_strategies(self):
        """初始化6个子策略"""

        # 1. 做市策略
        mm_config = MarketMakingConfig(
            symbol=self.symbol,
            board_symbol=self.symbol,
            tick_size=self.tick_size,
            lot_size=100,
            max_long_position=100,
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
        )
        self.lt_strategy = KabuLiquidityTakerScalper(
            self.gateway, lt_config, self.meta_manager
        )

        # 3. 订单流策略
        of_config = OrderFlowAlternativeConfig(
            symbol=self.symbol,
            board_symbol=self.symbol,
            tick_size=self.tick_size,
            lot_size=100,
            max_position=100,
        )
        self.of_strategy = OrderFlowAlternativeStrategy(
            self.gateway, of_config, self.meta_manager
        )

        # ✅4. 微网格震荡剥头皮
        grid_config = MicroGridConfig(
            symbol=self.symbol,
            board_symbol=self.symbol,
            tick_size=self.tick_size,
            lot_size=100,
            max_position=300,  # 允许多个网格同时持仓
        )
        self.grid_strategy = MicroGridScalper(
            self.gateway, grid_config, self.meta_manager
        )

        # ✅5. 短周期动量跟随
        momentum_config = ShortMomentumConfig(
            symbol=self.symbol,
            board_symbol=self.symbol,
            tick_size=self.tick_size,
            lot_size=100,
            max_position=100,
        )
        self.momentum_strategy = ShortMomentumFollower(
            self.gateway, momentum_config, self.meta_manager
        )

        # ✅6. 盘口统计订单流
        tape_config = TapeReadingConfig(
            symbol=self.symbol,
            board_symbol=self.symbol,
            tick_size=self.tick_size,
            lot_size=100,
            max_position=100,
        )
        self.tape_strategy = TapeReadingStrategy(
            self.gateway, tape_config, self.meta_manager
        )

        logger.info("6个子策略已初始化完成")

    def on_board(self, board: Dict[str, Any]) -> None:
        """板行情回调"""
        if "last_price" in board:
            self.meta_manager.update_unrealized_pnl(board["last_price"])

        # 调用所有6个策略
        self.mm_strategy.on_board(board)
        self.lt_strategy.on_board(board)
        self.of_strategy.on_board(board)
        self.grid_strategy.on_board(board)         # ✅新增
        self.momentum_strategy.on_board(board)     # ✅新增
        self.tape_strategy.on_board(board)         # ✅新增

        self.meta_manager.reset_daily_stats()

    def on_fill(self, fill: Dict[str, Any]) -> None:
        """成交回报"""
        self.mm_strategy.on_fill(fill)
        self.lt_strategy.on_fill(fill)
        self.of_strategy.on_fill(fill)
        self.grid_strategy.on_fill(fill)           # ✅新增
        self.momentum_strategy.on_fill(fill)       # ✅新增
        self.tape_strategy.on_fill(fill)           # ✅新增

    def on_order_update(self, order: Dict[str, Any]) -> None:
        """订单状态更新"""
        self.mm_strategy.on_order_update(order)
        self.lt_strategy.on_order_update(order)
        self.of_strategy.on_order_update(order)
        self.grid_strategy.on_order_update(order)  # ✅新增
        self.momentum_strategy.on_order_update(order)  # ✅新增
        self.tape_strategy.on_order_update(order)  # ✅新增

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
        print("6策略整合交易系统状态")
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
