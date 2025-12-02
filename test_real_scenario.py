#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_real_scenario.py - 模拟真实场景测试止盈

检查为什么实际运行时没有看到止盈
"""

import asyncio
import random
from datetime import datetime
from strategy.hft.market_making_strategy import MarketMakingStrategy, MarketMakingConfig
from engine.meta_strategy_manager import StrategyType


class RealGateway:
    """模拟真实网关"""
    def __init__(self):
        self.orders = {}
        self.order_count = 0

    def send_order(self, symbol, side, price, qty, order_type="LIMIT", strategy_type=None):
        import uuid
        order_id = str(uuid.uuid4())[:8]
        self.orders[order_id] = {
            'symbol': symbol,
            'side': side,
            'quantity': qty,
            'price': price,
            'status': 'PENDING',
            'strategy_type': strategy_type
        }
        strategy_name = strategy_type.name if strategy_type is not None else "UNKNOWN"

        # 区分做市报价和平仓单
        if qty == 100 and strategy_type == StrategyType.MARKET_MAKING:
            order_type_str = "做市报价" if side in ["BUY", "SELL"] else "未知"
        else:
            order_type_str = "平仓单"

        print(f"[网关][{strategy_name}] {order_type_str}: {side} {qty}股 @ {price:.1f} (ID: {order_id})")
        self.order_count += 1
        return order_id

    def cancel_order(self, order_id):
        if order_id in self.orders:
            self.orders[order_id]['status'] = 'CANCELLED'
        return True

    def simulate_fills(self, current_price):
        """模拟订单成交"""
        fills = []
        for order_id, order in list(self.orders.items()):
            if order['status'] != 'PENDING':
                continue

            # 30%概率成交
            if random.random() < 0.3:
                if order['side'] == 'BUY' and current_price <= order['price']:
                    strategy_type = order.get('strategy_type')
                    strategy_name = strategy_type.name if strategy_type is not None else "UNKNOWN"
                    fills.append({
                        'order_id': order_id,
                        'symbol': order['symbol'],
                        'side': order['side'],
                        'quantity': order['quantity'],
                        'price': order['price'],
                        'strategy_type': strategy_type
                    })
                    order['status'] = 'FILLED'
                    print(f"[网关][{strategy_name}] 成交: {order_id} - BUY {order['quantity']}@{order['price']:.1f}")

                elif order['side'] == 'SELL' and current_price >= order['price']:
                    strategy_type = order.get('strategy_type')
                    strategy_name = strategy_type.name if strategy_type is not None else "UNKNOWN"
                    fills.append({
                        'order_id': order_id,
                        'symbol': order['symbol'],
                        'side': order['side'],
                        'quantity': order['quantity'],
                        'price': order['price'],
                        'strategy_type': strategy_type
                    })
                    order['status'] = 'FILLED'
                    print(f"[网关][{strategy_name}] 成交: {order_id} - SELL {order['quantity']}@{order['price']:.1f}")

        return fills


async def test_real_scenario():
    """测试真实场景"""
    print("\n" + "="*80)
    print("真实场景测试 - 检查止盈是否触发")
    print("="*80)

    # 使用实际配置
    config = MarketMakingConfig(
        symbol="4680",
        board_symbol="4680",
        tick_size=0.1,
        lot_size=100,
        max_long_position=100,
        take_profit_ticks=2,
        stop_loss_ticks=100,
        # 动态止盈配置
        enable_dynamic_exit=True,
        dynamic_profit_threshold_ticks=0.5,
        dynamic_reversal_ticks=0.3,
    )

    print(f"\n配置:")
    print(f"  enable_dynamic_exit = {config.enable_dynamic_exit}")
    print(f"  dynamic_profit_threshold_ticks = {config.dynamic_profit_threshold_ticks}")
    print(f"  dynamic_reversal_ticks = {config.dynamic_reversal_ticks}")

    gateway = RealGateway()
    strategy = MarketMakingStrategy(gateway, config, meta_manager=None)

    # 场景: 价格从1000涨到1002，然后回撤
    prices = [
        1000.0,  # 起始价
        1000.2,  # +2 ticks
        1000.6,  # +6 ticks  ← 有盈利
        1001.0,  # +10 ticks
        1001.4,  # +14 ticks ← 更新最高价
        1001.1,  # +11 ticks, 回撤0.3 ticks ← 应该触发止盈
        1000.8,  # 继续跌
    ]

    print(f"\n开始模拟...")
    print(f"="*80)

    for i, price in enumerate(prices):
        print(f"\n--- Tick {i+1}: 价格 = {price:.1f} ---")

        board = {
            'symbol': '4680',
            'timestamp': datetime.now(),
            'last_price': price,
            'best_bid': price - 0.1,
            'best_ask': price + 0.1,
        }

        # 先处理行情
        strategy.on_board(board)

        # 第一个tick强制成交BUY订单，建立仓位
        if i == 0:
            print("  ✅ 强制成交BUY订单建立仓位")
            strategy.on_fill({
                'symbol': '4680',
                'side': 'BUY',
                'quantity': 100,
                'price': 1000.0,
                'strategy_type': StrategyType.MARKET_MAKING
            })

        # 显示当前状态
        if strategy.position != 0:
            pnl = (price - strategy.avg_price) / 0.1 if strategy.avg_price else 0
            print(f"  仓位: {strategy.position}股 @ {strategy.avg_price:.1f}, 盈亏: {pnl:.1f}T")
            if strategy.best_profit_price:
                if strategy.position > 0:
                    reversal = (strategy.best_profit_price - price) / 0.1
                else:
                    reversal = (price - strategy.best_profit_price) / 0.1
                print(f"  最优价: {strategy.best_profit_price:.1f}, 回撤: {reversal:.1f}T")

        # 模拟成交
        fills = gateway.simulate_fills(price)
        for fill in fills:
            strategy.on_fill(fill)

        await asyncio.sleep(0.01)

    print(f"\n{'='*80}")
    print(f"测试完成")
    print(f"{'='*80}")
    print(f"总订单数: {gateway.order_count}")
    print(f"最终仓位: {strategy.position}股")

    # 统计订单类型
    exit_orders = [o for o in gateway.orders.values() if o['quantity'] > 100 or (o['quantity'] == 100 and o['status'] == 'FILLED' and strategy.position == 0)]

    print(f"\n是否触发止盈: {'是' if strategy.position == 0 and gateway.order_count > 2 else '否'}")


if __name__ == "__main__":
    asyncio.run(test_real_scenario())
