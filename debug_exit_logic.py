#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
debug_exit_logic.py - 调试止盈逻辑

检查为什么止盈没有生效
"""

import asyncio
from datetime import datetime
from strategy.hft.market_making_strategy import MarketMakingStrategy, MarketMakingConfig

class DebugGateway:
    """调试网关 - 记录所有调用"""
    def __init__(self):
        self.orders = []
        self.exit_orders = []

    def send_order(self, symbol, side, price, qty, order_type="LIMIT", strategy_type=None):
        order_id = f"ORDER_{len(self.orders)}"
        order = {
            'id': order_id,
            'symbol': symbol,
            'side': side,
            'price': price,
            'qty': qty,
            'type': 'exit' if side == 'SELL' and len(self.orders) > 0 else 'entry'
        }
        self.orders.append(order)

        if order['type'] == 'exit':
            self.exit_orders.append(order)
            print(f"✅ 平仓订单: {side} {qty}股 @ {price:.1f}")
        else:
            print(f"📤 做市订单: {side} {qty}股 @ {price:.1f}")

        return order_id

    def cancel_order(self, order_id):
        return True


def test_exit_logic():
    """测试止盈逻辑"""
    print("\n" + "="*80)
    print("调试止盈逻辑")
    print("="*80)

    # 创建配置 - 查看实际使用的参数
    config = MarketMakingConfig(
        symbol="4680",
        board_symbol="4680",
        tick_size=0.1,
        lot_size=100,
        max_long_position=100,
        take_profit_ticks=2,
        stop_loss_ticks=100,
    )

    print("\n当前配置:")
    print(f"  enable_dynamic_exit = {config.enable_dynamic_exit}")
    print(f"  dynamic_profit_threshold_ticks = {config.dynamic_profit_threshold_ticks}")
    print(f"  dynamic_reversal_ticks = {config.dynamic_reversal_ticks}")
    print(f"  enable_trailing_stop = {config.enable_trailing_stop}")
    print(f"  trailing_activation_ticks = {config.trailing_activation_ticks}")
    print(f"  trailing_distance_ticks = {config.trailing_distance_ticks}")
    print(f"  take_profit_ticks = {config.take_profit_ticks}")
    print(f"  stop_loss_ticks = {config.stop_loss_ticks}")

    gateway = DebugGateway()
    strategy = MarketMakingStrategy(gateway, config, meta_manager=None)

    # 模拟持仓
    print("\n" + "="*80)
    print("模拟场景: 买入100股@1000，价格上涨到1000.6，然后回撤到1000.3")
    print("="*80)

    # 开仓
    strategy.position = 100
    strategy.avg_price = 1000.0
    strategy.entry_time = datetime.now()
    strategy.best_profit_price = None
    strategy.trailing_active = False

    print(f"\n✅ 持仓: {strategy.position}股 @ {strategy.avg_price:.1f}")

    # Tick 1: 价格涨到1000.6 (盈利0.6 ticks)
    print(f"\n{'='*80}")
    print("Tick 1: 价格 = 1000.6")
    pnl = (1000.6 - 1000.0) / 0.1
    print(f"  盈利: {pnl:.1f} ticks")
    print(f"  检查: {pnl:.1f} >= {config.dynamic_profit_threshold_ticks} ? {pnl >= config.dynamic_profit_threshold_ticks}")

    board = {
        'symbol': '4680',
        'timestamp': datetime.now(),
        'last_price': 1000.6,
        'best_bid': 1000.5,
        'best_ask': 1000.7
    }

    initial_exit_orders = len(gateway.exit_orders)
    strategy.on_board(board)

    if len(gateway.exit_orders) > initial_exit_orders:
        print(f"  ❌ 错误: 不应该平仓 (方向正确)")
    else:
        print(f"  ✅ 正确: 方向正确，继续持有")

    # Tick 2: 价格继续涨到1001.2 (盈利1.2 ticks)
    print(f"\n{'='*80}")
    print("Tick 2: 价格 = 1001.2")
    pnl = (1001.2 - 1000.0) / 0.1
    print(f"  盈利: {pnl:.1f} ticks")
    best_price_str = f"{strategy.best_profit_price:.1f}" if strategy.best_profit_price is not None else "None"
    print(f"  最优价: {best_price_str}")

    board['last_price'] = 1001.2
    board['best_bid'] = 1001.1
    board['best_ask'] = 1001.3
    board['timestamp'] = datetime.now()

    initial_exit_orders = len(gateway.exit_orders)
    strategy.on_board(board)

    if len(gateway.exit_orders) > initial_exit_orders:
        print(f"  ❌ 错误: 不应该平仓")
    else:
        print(f"  ✅ 正确: 继续持有")

    # Tick 3: 价格回撤到1000.9 (从1001.2回撤0.3 ticks)
    print(f"\n{'='*80}")
    print("Tick 3: 价格 = 1000.9")
    pnl = (1000.9 - 1000.0) / 0.1
    reversal = (1001.2 - 1000.9) / 0.1
    print(f"  当前盈利: {pnl:.1f} ticks")
    best_price_str = f"{strategy.best_profit_price:.1f}" if strategy.best_profit_price is not None else "None"
    print(f"  最优价: {best_price_str}")
    print(f"  回撤: {reversal:.1f} ticks")
    print(f"  检查: {reversal:.1f} >= {config.dynamic_reversal_ticks} ? {reversal >= config.dynamic_reversal_ticks}")

    board['last_price'] = 1000.9
    board['best_bid'] = 1000.8
    board['best_ask'] = 1001.0
    board['timestamp'] = datetime.now()

    initial_exit_orders = len(gateway.exit_orders)
    strategy.on_board(board)

    if len(gateway.exit_orders) > initial_exit_orders:
        print(f"  ✅ 正确: 触发动态止盈，平仓!")
    else:
        print(f"  ❌ 问题: 应该触发平仓但没有")
        print(f"     - 盈利充足: {pnl} >= {config.dynamic_profit_threshold_ticks} = {pnl >= config.dynamic_profit_threshold_ticks}")
        print(f"     - 回撤充足: {reversal} >= {config.dynamic_reversal_ticks} = {reversal >= config.dynamic_reversal_ticks}")
        print(f"     - position: {strategy.position}")
        print(f"     - avg_price: {strategy.avg_price}")
        print(f"     - best_profit_price: {strategy.best_profit_price}")

    print(f"\n{'='*80}")
    print("测试总结")
    print(f"{'='*80}")
    print(f"总订单数: {len(gateway.orders)}")
    print(f"平仓订单数: {len(gateway.exit_orders)}")

    if len(gateway.exit_orders) > 0:
        print(f"\n✅ 止盈逻辑正常工作")
    else:
        print(f"\n❌ 止盈逻辑有问题，没有触发平仓")
        print(f"\n可能原因:")
        print(f"  1. _check_exit() 没有被调用")
        print(f"  2. 参数配置不正确")
        print(f"  3. position 或 avg_price 为空")
        print(f"  4. board 对象缺少字段")

    print("\n所有订单:")
    for i, order in enumerate(gateway.orders, 1):
        print(f"  {i}. [{order['type']:5s}] {order['side']:4s} {order['qty']:3d}股 @ {order['price']:7.1f}")


if __name__ == "__main__":
    test_exit_logic()
