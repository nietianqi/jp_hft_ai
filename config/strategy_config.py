# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
from typing import Dict

@dataclass  
class HFTConfig:
    """高频交易策略配置"""
    total_capital: float = 15_000_000
    max_total_position: int = 400
    daily_loss_limit: float = 500_000
    strategy_loss_limit: float = 100_000
    profit_target: float = 200_000
    position_reduce_ratio: float = 0.5
    take_profit_ticks: int = 2
    stop_loss_ticks: int = 100
    time_stop_seconds: int = 5
    strategy_weights: Dict[str, float] = field(default_factory=lambda: {
        'market_making': 0.3,
        'liquidity_taker': 0.4,
        'orderflow_queue': 0.3,
    })

@dataclass
class StrategyConfig:
    mode: str = 'hft'
    hft: HFTConfig = field(default_factory=HFTConfig)
