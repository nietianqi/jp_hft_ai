#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_6_strategies.py - 测试6策略系统

测试新增的3个策略:
1. 微网格震荡剥头皮
2. 短周期动量跟随
3. 盘口统计订单流
"""

import asyncio
import sys
import random
from datetime import datetime

from integrated_trading_system_v2 import IntegratedTradingSystemV2


class DummyGateway:
    """模拟网关"""

    def __init__(self):
        self.orders = {}

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
        print(f"[网关][{strategy_name}] {side} {symbol}: {qty}股 @ {price:.1f} (订单ID: {order_id})")
        return order_id

    def cancel_order(self, order_id):
        if order_id in self.orders:
            self.orders[order_id]['status'] = 'CANCELLED'
            return True
        return False

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


async def main():
    """主程序"""
    print("\n" + "=" * 80)
    print("Kabu HFT交易系统 - 6策略版本测试")
    print("=" * 80)
    print()
    print("策略配置:")
    print("  1. 做市策略 (15%)")
    print("  2. 流动性抢占 (15%)")
    print("  3. 订单流策略 (10%)")
    print("  4. ✅ 微网格震荡剥头皮 (25%) - 新增")
    print("  5. ✅ 短周期动量跟随 (20%) - 新增")
    print("  6. ✅ 盘口统计订单流 (15%) - 新增")
    print("=" * 80)

    gateway = DummyGateway()
    system = IntegratedTradingSystemV2(
        gateway=gateway,
        symbol="4680",
        tick_size=0.1,
    )

    print("\n✓ 6策略系统初始化成功")
    print("\n开始模拟测试 (300 ticks)...\n")

    base_price = 1000.0
    tick_count = 0

    # 模拟震荡市 + 趋势市混合
    for i in range(300):
        # 前100 ticks: 震荡市（适合微网格）
        if i < 100:
            base_price += random.uniform(-0.5, 0.5)
            base_price = max(995.0, min(base_price, 1005.0))

        # 中间100 ticks: 上涨趋势（适合动量跟随）
        elif i < 200:
            base_price += random.uniform(-0.3, 1.0)
            base_price = max(1000.0, min(base_price, 1030.0))

        # 最后100 ticks: 下跌趋势
        else:
            base_price += random.uniform(-1.0, 0.3)
            base_price = max(980.0, min(base_price, 1020.0))

        spread = random.uniform(1.0, 3.0)
        bid_price = base_price - spread / 2
        ask_price = base_price + spread / 2

        board = {
            "symbol": "4680",
            "timestamp": datetime.now(),
            "best_bid": bid_price,
            "best_ask": ask_price,
            "last_price": base_price,
            "bids": [(bid_price - i * 0.1, random.randint(100, 500)) for i in range(5)],
            "asks": [(ask_price + i * 0.1, random.randint(100, 500)) for i in range(5)],
            "trading_volume": random.randint(10000, 50000),
            "buy_market_order": random.randint(100, 1000),
            "sell_market_order": random.randint(100, 1000),
        }

        system.on_board(board)
        tick_count += 1

        fills = gateway.simulate_fills(base_price)
        for fill in fills:
            system.on_fill(fill)

        await asyncio.sleep(0.01)

        # 定期打印状态
        if (i + 1) % 100 == 0:
            print(f"\n{'=' * 60}")
            if i < 100:
                print(f"阶段1 - 震荡市: {i + 1}/300 ticks  |  价格: {base_price:.1f}")
            elif i < 200:
                print(f"阶段2 - 上涨趋势: {i + 1}/300 ticks  |  价格: {base_price:.1f}")
            else:
                print(f"阶段3 - 下跌趋势: {i + 1}/300 ticks  |  价格: {base_price:.1f}")
            print(f"{'=' * 60}")
            system.print_status()

    print("\n\n" + "=" * 80)
    print("测试完成 - 最终状态")
    print("=" * 80)
    system.print_status()

    print("\n" + "=" * 80)
    print("测试总结")
    print("=" * 80)
    print(f"总Tick数: {tick_count}")
    print(f"挂单总数: {len([o for o in gateway.orders.values() if o['status'] == 'PENDING'])}")
    print(f"成交总数: {len([o for o in gateway.orders.values() if o['status'] == 'FILLED'])}")

    # 分析策略贡献
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
        filled_orders = [
            o for o in gateway.orders.values()
            if o['status'] == 'FILLED' and o.get('strategy_type') == strategy_type
        ]
        print(f"  {strategy_type.name}: {len(filled_orders)}笔成交")

    return 0


if __name__ == "__main__":
    print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n程序中断 (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n致命错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
