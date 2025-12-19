#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
debug_no_orders.py - 调试为什么没有下单

检查所有策略的入场条件
"""

import asyncio
import random
from datetime import datetime

from integrated_trading_system_v2 import IntegratedTradingSystemV2


class DebugGateway:
    """调试网关 - 打印所有信号"""

    def __init__(self):
        self.orders = {}
        self.signal_count = 0

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
        self.signal_count += 1
        strategy_name = strategy_type.name if strategy_type is not None else "UNKNOWN"
        print(f"\n✅ [下单成功#{self.signal_count}] [{strategy_name}] {side} {symbol}: {qty}股 @ {price:.1f} (订单ID: {order_id})")
        return order_id

    def cancel_order(self, order_id):
        if order_id in self.orders:
            self.orders[order_id]['status'] = 'CANCELLED'
            return True
        return False

    def simulate_fills(self, current_price):
        fills = []
        for order_id, order in list(self.orders.items()):
            if order['status'] != 'PENDING':
                continue

            if random.random() < 0.3:
                if order['side'] == 'BUY' and current_price <= order['price']:
                    fills.append({
                        'order_id': order_id,
                        'symbol': order['symbol'],
                        'side': order['side'],
                        'quantity': order['quantity'],
                        'price': order['price'],
                        'strategy_type': order.get('strategy_type')
                    })
                    order['status'] = 'FILLED'
                    print(f"  💰 成交: {order_id}")

                elif order['side'] == 'SELL' and current_price >= order['price']:
                    fills.append({
                        'order_id': order_id,
                        'symbol': order['symbol'],
                        'side': order['side'],
                        'quantity': order['quantity'],
                        'price': order['price'],
                        'strategy_type': order.get('strategy_type')
                    })
                    order['status'] = 'FILLED'
                    print(f"  💰 成交: {order_id}")

        return fills


async def main():
    """调试主程序"""
    print("\n" + "=" * 80)
    print("调试脚本 - 检查为什么没有下单")
    print("=" * 80)

    gateway = DebugGateway()
    system = IntegratedTradingSystemV2(
        gateway=gateway,
        symbol="4680",
        tick_size=0.1,
    )

    print("\n✓ 系统初始化成功")
    print("开始模拟100 ticks...\n")

    base_price = 1000.0

    for i in range(100):
        # 模拟价格波动
        base_price += random.uniform(-1.0, 1.0)
        base_price = max(990.0, min(base_price, 1010.0))

        spread = random.uniform(0.5, 2.0)
        bid_price = base_price - spread / 2
        ask_price = base_price + spread / 2

        # 构造board数据
        board = {
            "symbol": "4680",
            "timestamp": datetime.now(),
            "best_bid": bid_price,
            "best_ask": ask_price,
            "last_price": base_price,
            "bids": [(bid_price - j * 0.1, random.randint(100, 1000)) for j in range(5)],
            "asks": [(ask_price + j * 0.1, random.randint(100, 1000)) for j in range(5)],
            "trading_volume": random.randint(5000, 50000),  # ✅ 确保有成交量
            "buy_market_order": random.randint(50, 1500),   # ✅ 确保有市价单
            "sell_market_order": random.randint(50, 1500),
        }

        # 喂给系统
        system.on_board(board)

        # 模拟成交
        fills = gateway.simulate_fills(base_price)
        for fill in fills:
            system.on_fill(fill)

        await asyncio.sleep(0.01)

        # 每20个tick打印进度
        if (i + 1) % 20 == 0:
            print(f"\n--- 进度: {i+1}/100 ticks, 当前价格: {base_price:.1f}, 信号数: {gateway.signal_count} ---")

    print("\n\n" + "=" * 80)
    print("调试结果汇总")
    print("=" * 80)
    print(f"总Tick数: 100")
    print(f"总信号数: {gateway.signal_count}")
    print(f"挂单总数: {len([o for o in gateway.orders.values() if o['status'] == 'PENDING'])}")
    print(f"成交总数: {len([o for o in gateway.orders.values() if o['status'] == 'FILLED'])}")

    if gateway.signal_count == 0:
        print("\n⚠️ 没有任何下单信号！")
        print("\n可能的原因:")
        print("1. ✅ 入场条件太严格（需要同时满足：压力≥0.6、动量≥2T、深度不平衡≥0.3、置信度≥0.6）")
        print("2. ✅ 成交量增长不足（需要≥1000）")
        print("3. ✅ 冷却期限制（每次下单后1秒内不能再下单）")
        print("4. ✅ 元策略管理器风控拒绝")
        print("\n建议:")
        print("- 降低入场条件阈值")
        print("- 增加市场波动")
        print("- 检查日志查看具体拒绝原因")
    else:
        print(f"\n✅ 成功产生 {gateway.signal_count} 个交易信号")

    print("=" * 80)

    # 打印各策略信号统计
    print("\n各策略信号统计:")
    from engine.meta_strategy_manager import StrategyType
    for strategy_type in [
        StrategyType.MARKET_MAKING,
        StrategyType.LIQUIDITY_TAKER,
        StrategyType.ORDER_FLOW,
        StrategyType.MICRO_GRID,
        StrategyType.SHORT_MOMENTUM,
        StrategyType.TAPE_READING,
    ]:
        count = len([
            o for o in gateway.orders.values()
            if o.get('strategy_type') == strategy_type
        ])
        print(f"  {strategy_type.name}: {count}笔")

    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
