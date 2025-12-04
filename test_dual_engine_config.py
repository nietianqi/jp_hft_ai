#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试dual_engine配置是否正确加载
"""

from config.strategy_config import StrategyConfig

def test_dual_engine_config():
    """测试双引擎配置"""
    print("="*60)
    print("测试 dual_engine 配置加载")
    print("="*60)

    # 创建dual_engine模式配置
    config = StrategyConfig(mode='dual_engine')

    print(f"\n✓ 配置模式: {config.mode}")
    print("\n双引擎策略配置:")
    print(f"  EMA快线窗口: {config.dual_engine.ema_fast_window}")
    print(f"  EMA慢线窗口: {config.dual_engine.ema_slow_window}")
    print(f"  核心仓位: {config.dual_engine.core_pos} 股")
    print(f"  最大仓位: {config.dual_engine.max_pos} 股")
    print(f"  网格层数: {config.dual_engine.grid_levels} 层")
    print(f"  网格步长: {config.dual_engine.grid_step_pct}%")
    print(f"  每格下单量: {config.dual_engine.grid_volume} 股")
    print(f"  动态止盈: {'启用' if config.dual_engine.enable_dynamic_exit else '禁用'}")
    print(f"  盈利阈值: {config.dual_engine.dynamic_profit_threshold_ticks} ticks")
    print(f"  反转阈值: {config.dual_engine.dynamic_reversal_ticks} ticks")
    print(f"  移动止盈: {'启用' if config.dual_engine.enable_trailing_stop else '禁用'}")

    print("\n="*60)
    print("✓ 配置测试通过!")
    print("="*60)

if __name__ == "__main__":
    test_dual_engine_config()
