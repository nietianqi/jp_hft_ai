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
class DualEngineConfig:
    """双引擎网格策略配置 - 参考VeighNa DualEngineGridStrategyOptimized"""
    # EMA参数
    ema_fast_window: int = 20
    ema_slow_window: int = 60

    # 核心仓位参数
    core_pos: int = 1000                 # 核心仓目标（股数）
    max_pos: int = 2000                  # 最大多头仓位

    # 网格参数
    grid_levels: int = 3                 # 网格层数（上下各几层）
    grid_step_pct: float = 0.3           # 网格每层间距（百分比）
    grid_volume: int = 100               # 每格下单数（股）
    active_grid_levels: int = 0          # 实际激活的网格层数（0=使用grid_levels）

    # 手续费参数
    fee_per_side: float = 80.0           # 预估单边手续费(JPY/100股)
    min_profit_multiple: float = 2.0     # 期望净利润 >= 手续费 * 倍数
    auto_adjust_step: bool = True        # 若步长不足覆盖手续费，是否自动放大步长

    # 止盈参数
    profit_take_pct: float = 0.5         # 止盈比例（%）
    enable_trailing_stop: bool = True    # 启用移动止盈
    trailing_activation_ticks: int = 3   # 盈利N ticks后启动移动止盈
    trailing_distance_ticks: int = 2     # 从最高点回撤N ticks触发止盈

    # 动态止盈参数
    enable_dynamic_exit: bool = True     # 启用动态止盈模式（有盈利方向反转才平仓）
    dynamic_profit_threshold_ticks: float = 0.5  # 盈利阈值
    dynamic_reversal_ticks: float = 0.3  # 方向反转阈值

    # 价格参数
    pricetick: float = 0.01              # 最小价格变动

@dataclass
class StrategyConfig:
    """策略模式配置 - 支持HFT和双引擎两种模式"""
    mode: str = 'dual_engine'  # 'hft' 或 'dual_engine'
    hft: HFTConfig = field(default_factory=HFTConfig)
    dual_engine: DualEngineConfig = field(default_factory=DualEngineConfig)
