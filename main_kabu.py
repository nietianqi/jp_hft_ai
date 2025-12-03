# -*- coding: utf-8 -*-
"""
main_kabu.py - 真实Kabu API交易启动脚本

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
from config.trading_config import TradingConfig
from config.strategy_config import StrategyConfig
from market.kabu_feed import KabuMarketFeed
from execution.kabu_executor import KabuExecutor
from models.market_data import MarketTick

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(f'kabu_trading_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def main():
    """真实Kabu API交易主函数"""

    print("\n" + "=" * 80)
    print("⚠️  Kabu 真实交易系统 - 请谨慎操作！")
    print("=" * 80)

    # 加载配置
    system_config = SystemConfig()
    trading_config = TradingConfig()
    strategy_config = StrategyConfig()  # 使用配置文件中的mode设置

    # 显示配置信息
    if strategy_config.mode == 'hft':
        print(f"\n模式: HFT三策略系统")
        print(f"标的: {system_config.SYMBOLS}")
        hft_cfg = strategy_config.hft
        print(f"配置:")
        print(f"  最大仓位: {hft_cfg.max_total_position} 股")
        print(f"  止盈/止损: {hft_cfg.take_profit_ticks}/{hft_cfg.stop_loss_ticks} ticks")
        print(f"  日亏损限额: {hft_cfg.daily_loss_limit:,.0f} 日元")
    else:  # dual_engine
        print(f"\n模式: 双引擎网格策略")
        print(f"标的: {system_config.SYMBOLS}")
        de_cfg = strategy_config.dual_engine
        print(f"配置:")
        print(f"  核心仓位: {de_cfg.core_pos} 股")
        print(f"  最大仓位: {de_cfg.max_pos} 股")
        print(f"  网格步长: {de_cfg.grid_step_pct}%")
        print(f"  动态止盈: {'启用' if de_cfg.enable_dynamic_exit else '禁用'}")

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
        executor = KabuExecutor(
            rest_url=system_config.REST_URL,
            api_token=market_feed.api_token,
            symbol=system_config.SYMBOLS[0]
        )

        # 根据模式初始化不同的交易系统
        if strategy_config.mode == 'hft':
            # HFT模式
            from integrated_trading_system import IntegratedTradingSystem

            system = IntegratedTradingSystem(
                gateway=executor,
                symbol=system_config.SYMBOLS[0],
                tick_size=0.1,
            )

            hft_cfg = strategy_config.hft
            system.meta_manager.cfg.total_capital = hft_cfg.total_capital
            system.meta_manager.cfg.max_total_position = hft_cfg.max_total_position
            system.meta_manager.cfg.daily_loss_limit = hft_cfg.daily_loss_limit

            print("\n✓ HFT系统初始化成功")

        else:
            # 双引擎模式
            from strategy.original.dual_engine_strategy import DualEngineTradingStrategy

            de_cfg = strategy_config.dual_engine
            strategy = DualEngineTradingStrategy(config=de_cfg)

            # 双引擎系统包装类
            class DualEngineSystem:
                def __init__(self, strategy, executor, symbol):
                    self.strategy = strategy
                    self.executor = executor
                    self.symbol = symbol
                    self.position = 0
                    self.avg_cost = 0.0
                    self.total_pnl = 0.0
                    self.trades = []

                async def on_tick(self, tick: MarketTick):
                    """处理行情tick"""
                    self.strategy.update_indicators(tick)
                    signal = self.strategy.generate_signal(tick)

                    if signal:
                        await self._execute_signal(signal, tick.last_price)

                async def _execute_signal(self, signal, price):
                    """执行交易信号"""
                    qty = signal.quantity
                    reason_map = {1: 'core', 2: 'grid_buy', 3: 'grid_sell',
                                  4: 'exit', 5: 'trailing', 6: 'profit'}
                    reason = reason_map.get(signal.reason_code, f'code_{signal.reason_code}')

                    try:
                        if signal.action == 0:  # BUY
                            # 调用真实API下单
                            order_result = await self.executor.send_order(
                                side="buy",
                                price=price,
                                quantity=qty
                            )

                            if order_result.get('success'):
                                cost = self.position * self.avg_cost + qty * price
                                self.position += qty
                                self.avg_cost = cost / self.position if self.position > 0 else 0
                                self.trades.append(('BUY', qty, price, reason))
                                logger.info(f"[{reason}] BUY {qty}股 @ {price:.2f} (持仓={self.position}) ✓")

                                # 通知策略持仓变化
                                self.strategy.on_fill(self.symbol, "BUY", price, qty)
                            else:
                                logger.error(f"[{reason}] BUY {qty}股 @ {price:.2f} 失败: {order_result.get('error')}")

                        elif signal.action == 1:  # SELL
                            if self.position >= qty:
                                # 调用真实API下单
                                order_result = await self.executor.send_order(
                                    side="sell",
                                    price=price,
                                    quantity=qty
                                )

                                if order_result.get('success'):
                                    pnl = (price - self.avg_cost) * qty
                                    self.total_pnl += pnl
                                    self.position -= qty
                                    self.trades.append(('SELL', qty, price, reason, pnl))
                                    logger.info(f"[{reason}] SELL {qty}股 @ {price:.2f} (持仓={self.position}, 盈亏={pnl:.0f}) ✓")

                                    # 通知策略持仓变化
                                    self.strategy.on_fill(self.symbol, "SELL", price, qty)
                                else:
                                    logger.error(f"[{reason}] SELL {qty}股 @ {price:.2f} 失败: {order_result.get('error')}")

                    except Exception as e:
                        logger.error(f"执行信号失败: {e}", exc_info=True)

                def print_status(self):
                    """打印系统状态"""
                    status = self.strategy.get_strategy_status(self.symbol)
                    print(f"\n双引擎策略状态:")
                    print(f"  持仓: {self.position} 股")
                    print(f"  成本价: {self.avg_cost:.2f}")
                    print(f"  累计盈亏: {self.total_pnl:.0f} JPY")
                    print(f"  趋势状态: {'震荡上行✓' if status.get('trend_up') else '趋势失效✗'}")
                    print(f"  网格中心: {status.get('grid_center', 0):.2f}")
                    print(f"  网格层数: {status.get('active_grid_levels', 0)}")

            system = DualEngineSystem(strategy, executor, system_config.SYMBOLS[0])
            print("\n✓ 双引擎策略初始化成功")

        print("\n开始实时交易...\n")

        # 启动WebSocket行情监听
        tick_count = 0
        async for board in market_feed.listen():
            try:
                if strategy_config.mode == 'hft':
                    # HFT模式处理
                    system.on_board(board)

                    # 模拟成交（真实环境会通过API回调）
                    # TODO: 在真实环境需要监听成交回调
                    fills = executor.get_pending_fills()  # 需要实现
                    for fill in fills:
                        system.on_fill(fill)
                else:
                    # 双引擎模式处理
                    tick = MarketTick(
                        symbol=board['symbol'],
                        timestamp_ns=int(board['timestamp'].timestamp() * 1e9),
                        last_price=board['last_price'],
                        bid_price=board['best_bid'],
                        ask_price=board['best_ask'],
                        volume=board.get('trading_volume', 0),
                        bid_size=board['bids'][0][1] if board['bids'] else 0,
                        ask_size=board['asks'][0][1] if board['asks'] else 0,
                    )
                    await system.on_tick(tick)

                tick_count += 1

                # 每100个tick打印一次状态
                if tick_count % 100 == 0:
                    print(f"\n{'='*60}")
                    print(f"Tick数: {tick_count}  |  时间: {datetime.now().strftime('%H:%M:%S')}")
                    print(f"{'='*60}")
                    system.print_status()

            except KeyboardInterrupt:
                print("\n\n收到中断信号，正在安全退出...")
                break
            except Exception as e:
                logger.error(f"处理行情失败: {e}", exc_info=True)

    except KeyboardInterrupt:
        print("\n\n收到中断信号，正在安全退出...")
    except Exception as e:
        logger.error(f"系统错误: {e}", exc_info=True)
    finally:
        print("\n\n" + "=" * 80)
        print("交易系统已停止")
        print("=" * 80)
        if hasattr(system, 'print_status'):
            system.print_status()


if __name__ == "__main__":
    asyncio.run(main())
