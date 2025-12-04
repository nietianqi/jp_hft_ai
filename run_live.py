#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_live.py - 真实环境运行脚本

⚠️ 使用前必读:
1. 确保已完成仓位管理修复
2. 首次运行从最小仓位开始(100股)
3. 确保kabuSTATION已启动且API已启用
4. 设置好config/system_config.py中的API密码
"""

import asyncio
import sys
from datetime import datetime
from typing import Dict, Any

from config.system_config import SystemConfig
from config.trading_config import TradingConfig
from config.strategy_config import StrategyConfig
from market.kabu_feed import KabuMarketFeed
from execution.kabu_executor import KabuOrderExecutor
from integrated_trading_system import IntegratedTradingSystem


async def main():
    """真实环境主程序"""
    print("\n" + "=" * 80)
    print("Kabu HFT交易系统 - 真实环境")
    print("=" * 80)

    # 加载配置
    sys_config = SystemConfig()
    trading_config = TradingConfig()
    strategy_config = StrategyConfig(mode='dual_engine')

    print(f"正在连接: {sys_config.REST_URL}")
    print(f"标的: {sys_config.SYMBOLS[0]}")
    print("=" * 80)

    # 创建真实组件
    executor = KabuOrderExecutor(sys_config)
    feed = KabuMarketFeed(sys_config)

    try:
        # 订阅行情
        print("\n正在订阅行情...")
        success = await feed.subscribe(sys_config.SYMBOLS)
        if not success:
            print("✗ 行情订阅失败")
            return 1

        print("✓ 行情订阅成功")

        # 创建交易系统
        system = IntegratedTradingSystem(
            gateway=executor,
            symbol=sys_config.SYMBOLS[0],
            tick_size=0.1,
        )

        # ⚠️ 安全设置: 从小仓位开始!
        if strategy_config.mode == 'dual_engine':
            dual_cfg = strategy_config.dual_engine
            system.meta_manager.cfg.max_total_position = 100  # ⚠️ 首次运行仅100股!
            system.meta_manager.cfg.daily_loss_limit = 50_000  # ⚠️ 首次运行限制5万日元

            print("\n系统配置:")
            print(f"  模式: 双引擎网格策略")
            print(f"  核心仓位: {dual_cfg.core_pos} 股")
            print(f"  最大仓位: {system.meta_manager.cfg.max_total_position} 股 (⚠️ 小仓位测试)")
            print(f"  日亏损限额: {system.meta_manager.cfg.daily_loss_limit:,.0f} 日元")
            print(f"  网格层数: {dual_cfg.grid_levels} 层")
            print(f"  网格步长: {dual_cfg.grid_step_pct}%")
            print(f"  动态止盈: {'启用' if dual_cfg.enable_dynamic_exit else '禁用'}")
        else:
            hft_cfg = strategy_config.hft
            system.meta_manager.cfg.total_capital = hft_cfg.total_capital
            system.meta_manager.cfg.max_total_position = 100  # ⚠️ 首次运行仅100股!
            system.meta_manager.cfg.daily_loss_limit = 50_000  # ⚠️ 首次运行限制5万日元

            print("\n系统配置:")
            print(f"  模式: 高频交易策略")
            print(f"  最大仓位: {system.meta_manager.cfg.max_total_position} 股 (⚠️ 小仓位测试)")
            print(f"  日亏损限额: {system.meta_manager.cfg.daily_loss_limit:,.0f} 日元")
            print(f"  止盈/止损: {hft_cfg.take_profit_ticks}/{hft_cfg.stop_loss_ticks} ticks")
        print("=" * 80)

        # 创建行情队列
        tick_queue = asyncio.Queue(maxsize=sys_config.TICK_QUEUE_SIZE)

        # 行情处理任务
        async def process_ticks():
            tick_count = 0
            last_status_time = datetime.now()

            while True:
                try:
                    tick = await tick_queue.get()
                    tick_count += 1

                    # 转换为board格式
                    board = {
                        "symbol": tick.symbol,
                        "timestamp": datetime.now(),
                        "best_bid": tick.bid_price,
                        "best_ask": tick.ask_price,
                        "last_price": tick.last_price,
                        "bids": [(tick.bid_price, tick.bid_size)],
                        "asks": [(tick.ask_price, tick.ask_size)],
                        "trading_volume": tick.volume,
                        "buy_market_order": 0,  # 可选
                        "sell_market_order": 0,  # 可选
                    }

                    # 处理行情
                    system.on_board(board)

                    # 每30秒打印一次状态
                    now = datetime.now()
                    if (now - last_status_time).total_seconds() >= 30:
                        print(f"\n[{now.strftime('%H:%M:%S')}] Tick计数: {tick_count}")
                        system.print_status()
                        last_status_time = now

                except Exception as e:
                    print(f"✗ 行情处理异常: {e}")
                    import traceback
                    traceback.print_exc()

        # 启动系统
        print("\n✓ 系统启动中...")
        print("按 Ctrl+C 停止交易\n")

        await asyncio.gather(
            feed.start_streaming(tick_queue),
            process_ticks()
        )

    except KeyboardInterrupt:
        print("\n\n用户中断 (Ctrl+C)")
        print("正在清理资源...")

    except Exception as e:
        print(f"\n✗ 系统异常: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # 清理资源
        await executor.close()
        print("✓ 资源已清理")

    return 0


if __name__ == "__main__":
    print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n程序已停止")
        sys.exit(0)
    except Exception as e:
        print(f"\n致命错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
