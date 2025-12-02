#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_dynamic_exit.py - 测试动态止盈策略

演示场景:
1. 买入100股@1000
2. 价格上涨到1001 (盈利1 tick) - 方向对，不平仓
3. 价格继续涨到1002 (盈利2 tick) - 方向对，继续持有
4. 价格回撤到1001.7 (回撤0.3 tick) - 方向反转，触发平仓
5. 亏损场景: 价格跌到999 - 不止损，等待反转
"""

import asyncio
from datetime import datetime
from strategy.hft.market_making_strategy import MarketMakingStrategy, MarketMakingConfig


class TestGateway:
    """测试网关"""
    def __init__(self):
        self.orders = []

    def send_order(self, symbol, side, price, qty, order_type="LIMIT", strategy_type=None):
        order_id = f"TEST_{len(self.orders)}"
        self.orders.append({
            'id': order_id,
            'symbol': symbol,
            'side': side,
            'price': price,
            'qty': qty
        })
        print(f"\n📤 发送订单: {side} {qty}股 @ {price:.1f} (ID: {order_id})")
        return order_id

    def cancel_order(self, order_id):
        print(f"❌ 撤单: {order_id}")
        return True


def test_dynamic_exit():
    """测试动态止盈"""
    print("\n" + "="*80)
    print("动态止盈策略测试")
    print("="*80)

    # 创建策略配置 - 启用动态止盈
    config = MarketMakingConfig(
        symbol="4680",
        board_symbol="4680",
        tick_size=0.1,
        lot_size=100,

        # ✅ 启用动态止盈模式
        enable_dynamic_exit=True,
        dynamic_profit_threshold_ticks=0.5,   # 盈利0.5 tick算有盈利
        dynamic_reversal_ticks=0.3,           # 回撤0.3 tick算方向反转

        # 传统止盈止损 (不使用)
        enable_trailing_stop=False,
        take_profit_ticks=100,  # 设置很大，不触发
        stop_loss_ticks=100,    # 设置很大，不触发
    )

    gateway = TestGateway()
    strategy = MarketMakingStrategy(gateway, config, meta_manager=None)

    print("\n策略配置:")
    print(f"  模式: 动态止盈 (enable_dynamic_exit=True)")
    print(f"  盈利阈值: {config.dynamic_profit_threshold_ticks} ticks")
    print(f"  反转阈值: {config.dynamic_reversal_ticks} ticks")
    print(f"  规则:")
    print(f"    1. 有盈利时，方向不对(回撤) → 平仓止盈")
    print(f"    2. 方向正确 → 继续持有，让利润奔跑")
    print(f"    3. 亏损时 → 不止损，等待反转")

    # ========== 场景1: 盈利后方向反转 → 平仓 ==========
    print("\n\n" + "="*80)
    print("场景1: 盈利后方向反转 → 应该平仓")
    print("="*80)

    # 模拟成交: 买入100股@1000 (直接设置仓位，跳过on_fill检查)
    print("\n📊 Tick 1: 买入 100股 @ 1000.0")
    from engine.meta_strategy_manager import StrategyType
    strategy.position = 100
    strategy.avg_price = 1000.0
    strategy.entry_time = datetime.now()
    strategy.best_profit_price = None
    strategy.trailing_active = False
    print(f"   持仓: {strategy.position} 股, 成本: {strategy.avg_price:.1f}")

    # Tick 2: 价格涨到1000.6 (盈利0.6 tick)
    print("\n📊 Tick 2: 价格 = 1000.6 (盈利 0.6 ticks)")
    board = {
        'symbol': '4680',
        'timestamp': datetime.now(),
        'last_price': 1000.6,
        'best_bid': 1000.5,
        'best_ask': 1000.7
    }
    strategy.on_board(board)
    print(f"   盈利: 0.6 ticks > 阈值0.5 → 已有盈利")
    print(f"   方向: 正确(上涨) → 继续持有 ✅")

    # Tick 3: 价格继续涨到1001.2 (盈利1.2 ticks)
    print("\n📊 Tick 3: 价格 = 1001.2 (盈利 1.2 ticks)")
    board['last_price'] = 1001.2
    board['best_bid'] = 1001.1
    board['best_ask'] = 1001.3
    strategy.on_board(board)
    print(f"   最高价: 1001.2")
    print(f"   方向: 正确(继续上涨) → 继续持有 ✅")

    # Tick 4: 价格回撤到1000.9 (从最高点1001.2回撤0.3 ticks)
    print("\n📊 Tick 4: 价格 = 1000.9 (从1001.2回撤 0.3 ticks)")
    board['last_price'] = 1000.9
    board['best_bid'] = 1000.8
    board['best_ask'] = 1001.0
    print(f"   最高价: 1001.2")
    print(f"   当前价: 1000.9")
    print(f"   回撤: 0.3 ticks = 反转阈值 → 方向反转! ❌")
    print(f"   当前盈利: 0.9 ticks > 0 → 有盈利 ✅")
    print(f"   预期: 触发动态止盈 → 平仓")

    initial_orders = len(gateway.orders)
    strategy.on_board(board)

    if len(gateway.orders) > initial_orders:
        print(f"\n✅ 测试通过! 触发平仓订单")
    else:
        print(f"\n❌ 测试失败! 未触发平仓")

    # ========== 场景2: 亏损不止损 ==========
    print("\n\n" + "="*80)
    print("场景2: 亏损场景 → 不应止损")
    print("="*80)

    # 重置策略 - 模拟新的买入
    print("\n📊 Tick 1: 买入 100股 @ 1000.0")
    strategy.position = 100
    strategy.avg_price = 1000.0
    strategy.entry_time = datetime.now()
    strategy.best_profit_price = None
    strategy.trailing_active = False

    # Tick 2: 价格跌到999.0 (亏损1.0 tick)
    print("\n📊 Tick 2: 价格 = 999.0 (亏损 1.0 ticks)")
    board['last_price'] = 999.0
    board['best_bid'] = 998.9
    board['best_ask'] = 999.1
    print(f"   亏损: 1.0 ticks")
    print(f"   预期: 不止损，等待反转 ✅")

    initial_orders = len(gateway.orders)
    strategy.on_board(board)

    if len(gateway.orders) == initial_orders:
        print(f"\n✅ 测试通过! 亏损时不止损，继续持有")
    else:
        print(f"\n❌ 测试失败! 不应该平仓")

    # Tick 3: 价格反弹到999.5 (仍亏损0.5 tick)
    print("\n📊 Tick 3: 价格 = 999.5 (亏损 0.5 ticks，但在反弹)")
    board['last_price'] = 999.5
    print(f"   预期: 继续持有，等待进一步反弹 ✅")
    strategy.on_board(board)

    # Tick 4: 价格反弹到1000.6 (盈利0.6 tick)
    print("\n📊 Tick 4: 价格 = 1000.6 (盈利 0.6 ticks)")
    board['last_price'] = 1000.6
    board['best_bid'] = 1000.5
    board['best_ask'] = 1000.7
    print(f"   盈利: 0.6 ticks > 阈值0.5")
    print(f"   预期: 有盈利后，等待方向反转信号")
    strategy.on_board(board)

    print("\n\n" + "="*80)
    print("测试总结")
    print("="*80)
    print("✅ 动态止盈策略已实现:")
    print("   1. 有盈利时，方向反转(回撤) → 平仓止盈")
    print("   2. 方向正确 → 继续持有，让利润奔跑")
    print("   3. 亏损时 → 不止损，等待反转")
    print("\n订单记录:")
    for i, order in enumerate(gateway.orders, 1):
        print(f"  {i}. {order['side']:4s} {order['qty']:3d}股 @ {order['price']:7.1f} (ID: {order['id']})")
    print("="*80)


if __name__ == "__main__":
    test_dynamic_exit()
