#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py - Kabu真实交易系统（6策略版本）

策略列表:
1. 做市策略 (15%)
2. 流动性抢占 (15%)
3. 订单流策略 (10%)
4. 微网格震荡剥头皮 (25%)
5. 短周期动量跟随 (20%)
6. 盘口统计订单流 (15%)

⚠️ 警告：这是真实交易脚本，会使用真金白银！
使用前请确保：
1. Kabu Station已启动
2. API功能已启用
3. 配置文件中的参数已正确设置
4. 已充分理解策略逻辑和风险
"""

import asyncio
import logging
from datetime import datetime

from config.system_config import SystemConfig
from market.kabu_feed import KabuMarketFeed
from execution.kabu_executor import KabuOrderExecutor
from integrated_trading_system_v2 import IntegratedTradingSystemV2
from models.market_data import MarketTick

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(f'kabu_6strategies_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def main():
    """真实Kabu API交易主函数 - 6策略版本"""

    print("\n" + "=" * 80)
    print("⚠️  Kabu 真实交易系统 - 6策略版本 - 请谨慎操作！")
    print("=" * 80)

    # 加载配置
    system_config = SystemConfig()

    print(f"\n模式: HFT六策略系统")
    print(f"标的: {system_config.SYMBOLS}")
    print("\n策略配置:")
    print("  1. 做市策略 (15%)")
    print("  2. 流动性抢占 (15%)")
    print("  3. 订单流策略 (10%)")
    print("  4. 微网格震荡剥头皮 (25%)")
    print("  5. 短周期动量跟随 (20%)")
    print("  6. 盘口统计订单流 (15%)")

    print(f"\nKabu API:")
    print(f"  REST地址: {system_config.REST_URL}")
    print(f"  WebSocket地址: {system_config.WS_URL}")
    print("=" * 80)

    # ⚠️ 安全确认
    print("\n⚠️  这是真实交易，会使用真金白银！")
    print("请确认您已:")
    print("  1. ✓ Kabu Station已启动")
    print("  2. ✓ 理解策略逻辑和风险")
    print("  3. ✓ 检查过所有配置参数")
    print("  4. ✓ 准备好承担可能的损失")

    confirm = input("\n输入 'YES' 继续，其他任意键取消: ")
    if confirm != 'YES':
        print("\n✗ 已取消启动")
        return

    print("\n正在初始化系统...\n")

    try:
        # 初始化行情订阅
        market_feed = KabuMarketFeed(system_config)

        # 订阅行情
        subscribe_success = await market_feed.subscribe(system_config.SYMBOLS)
        if not subscribe_success:
            print("\n✗ 行情订阅失败，请检查Kabu Station是否运行")
            return

        # 初始化订单执行器
        executor = KabuOrderExecutor(config=system_config)
        executor.api_token = market_feed.api_token  # 复用market_feed的token

        # 初始化6策略交易系统
        system = IntegratedTradingSystemV2(
            gateway=executor,
            symbol=system_config.SYMBOLS[0],
            tick_size=0.1,
        )

        print("\n✓ 6策略系统初始化成功")
        print("\n开始实时交易...\n")

        # 创建队列用于接收行情tick
        tick_queue: asyncio.Queue = asyncio.Queue()

        async def convert_tick_to_board(tick: MarketTick) -> dict:
            """将 MarketTick 对象转换为 board 格式"""
            bids = [(tick.bid_price, tick.bid_size)] if tick.bid_price is not None else []
            asks = [(tick.ask_price, tick.ask_size)] if tick.ask_price is not None else []
            board = {
                'symbol': tick.symbol,
                'timestamp': datetime.fromtimestamp(tick.timestamp_ns / 1e9),
                'last_price': tick.last_price,
                'best_bid': tick.bid_price,
                'best_ask': tick.ask_price,
                'bids': bids,
                'asks': asks,
                'trading_volume': tick.volume,
                'buy_market_order': 0,  # Kabu API可能不提供，设为0
                'sell_market_order': 0,
            }
            return board

        # 消费行情的协程
        async def process_tick_queue():
            tick_count = 0
            while True:
                tick = await tick_queue.get()
                try:
                    # 转换为 board 供系统使用
                    board = await convert_tick_to_board(tick)
                    system.on_board(board)

                    # 处理成交回报（真实环境会通过API回调）
                    if hasattr(executor, 'get_pending_fills'):
                        fills = executor.get_pending_fills() or []
                        for fill in fills:
                            system.on_fill(fill)

                    tick_count += 1
                    # 每100个tick打印一次状态
                    if tick_count % 100 == 0:
                        print(f"\n{'='*60}")
                        print(f"Tick数: {tick_count}  |  时间: {datetime.now().strftime('%H:%M:%S')}")
                        print(f"{'='*60}")
                        if hasattr(system, 'print_status'):
                            system.print_status()

                except KeyboardInterrupt:
                    print("\n\n收到中断信号，正在安全退出...")
                    break
                except Exception as e:
                    logger.error(f"处理行情失败: {e}", exc_info=True)

        # 并发启动行情流和消费协程
        await asyncio.gather(
            market_feed.start_streaming(tick_queue),
            process_tick_queue(),
        )

    except KeyboardInterrupt:
        print("\n\n收到中断信号，正在安全退出...")
    except Exception as e:
        logger.error(f"系统错误: {e}", exc_info=True)
    finally:
        print("\n\n" + "=" * 80)
        print("交易系统已停止")
        print("=" * 80)
        if 'system' in locals() and hasattr(system, 'print_status'):
            system.print_status()

        # 打印策略贡献分析
        if 'system' in locals() and hasattr(system, 'meta_manager'):
            print("\n策略贡献分析:")
            from engine.meta_strategy_manager import StrategyType
            for strategy_type in [
                StrategyType.MARKET_MAKING,
                StrategyType.LIQUIDITY_TAKER,
                StrategyType.ORDER_FLOW,
                StrategyType.MICRO_GRID,
                StrategyType.SHORT_MOMENTUM,
                StrategyType.TAPE_READING,
            ]:
                # 可以从meta_manager获取统计信息
                print(f"  {strategy_type.name}: 详见日志")


if __name__ == "__main__":
    asyncio.run(main())
