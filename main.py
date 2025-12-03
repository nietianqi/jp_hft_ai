#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py - 修复版主程序

修复:统一gateway为同步接口
"""

import asyncio
import sys
import random
from datetime import datetime

from config.system_config import SystemConfig
from config.trading_config import TradingConfig
from config.strategy_config import StrategyConfig


class DummyGateway:
    """模拟网关 - 修复版(同步接口)"""
    
    def __init__(self):
        self.orders = {}
    
    def send_order(self, symbol, side, price, qty, order_type="LIMIT", strategy_type=None):
        """✅修复:改为同步方法，添加策略类型标识"""
        import uuid
        order_id = str(uuid.uuid4())[:8]
        self.orders[order_id] = {
            'symbol': symbol,
            'side': side,
            'quantity': qty,
            'price': price,
            'status': 'PENDING',
            'strategy_type': strategy_type  # ← 新增：记录订单来自哪个策略
        }
        strategy_name = strategy_type.name if strategy_type is not None else "UNKNOWN"
        print(f"[网关][{strategy_name}] {side} {symbol}: {qty}股 @ {price:.1f} (订单ID: {order_id})")
        return order_id
    
    def cancel_order(self, order_id):
        """✅修复:改为同步方法"""
        if order_id in self.orders:
            self.orders[order_id]['status'] = 'CANCELLED'
            print(f"[网关] 撤单: {order_id}")
            return True
        return False
    
    def simulate_fills(self, current_price):
        """模拟订单成交"""
        fills = []
        for order_id, order in list(self.orders.items()):
            if order['status'] != 'PENDING':
                continue

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
                        'strategy_type': strategy_type  # ← 新增：成交回报包含策略类型
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
                        'strategy_type': strategy_type  # ← 新增：成交回报包含策略类型
                    })
                    order['status'] = 'FILLED'
                    print(f"[网关][{strategy_name}] 成交: {order_id} - SELL {order['quantity']}@{order['price']:.1f}")

        return fills


async def main():
    """主程序"""
    print("\n" + "=" * 80)
    print("Kabu HFT交易系统 - 修复版")
    print("=" * 80)
    
    system_config = SystemConfig()
    trading_config = TradingConfig()
    strategy_config = StrategyConfig()  # ✅ Use mode from config file

    # Display current mode
    if strategy_config.mode == 'hft':
        print(f"模式: HFT三策略系统")
        print(f"标的: {system_config.SYMBOLS[0]}")

        hft_cfg = strategy_config.hft
        print(f"配置:")
        print(f"  最大仓位: {hft_cfg.max_total_position} 股")
        print(f"  止盈/止损: {hft_cfg.take_profit_ticks}/{hft_cfg.stop_loss_ticks} ticks")
        print(f"  日亏损限额: {hft_cfg.daily_loss_limit:,.0f} 日元")
        print(f"  策略权重: 做市{hft_cfg.strategy_weights['market_making']:.0%} + "
              f"流动性{hft_cfg.strategy_weights['liquidity_taker']:.0%} + "
              f"订单流{hft_cfg.strategy_weights['orderflow_queue']:.0%}")
    else:  # dual_engine
        print(f"模式: 双引擎网格策略")
        print(f"标的: {system_config.SYMBOLS[0]}")

        de_cfg = strategy_config.dual_engine
        print(f"配置:")
        print(f"  核心仓位: {de_cfg.core_pos} 股")
        print(f"  最大仓位: {de_cfg.max_pos} 股")
        print(f"  网格步长: {de_cfg.grid_step_pct}%")
        print(f"  动态止盈: {'启用' if de_cfg.enable_dynamic_exit else '禁用'}")
    print("=" * 80)

    try:
        gateway = DummyGateway()

        # Initialize system based on mode
        if strategy_config.mode == 'hft':
            from integrated_trading_system import IntegratedTradingSystem

            system = IntegratedTradingSystem(
                gateway=gateway,
                symbol=system_config.SYMBOLS[0],
                tick_size=0.1,
            )

            hft_cfg = strategy_config.hft
            system.meta_manager.cfg.total_capital = hft_cfg.total_capital
            system.meta_manager.cfg.max_total_position = hft_cfg.max_total_position
            system.meta_manager.cfg.daily_loss_limit = hft_cfg.daily_loss_limit

            print("\n✓ HFT系统初始化成功")
        else:  # dual_engine
            from strategy.original.dual_engine_strategy import DualEngineTradingStrategy
            from models.market_data import MarketTick

            de_cfg = strategy_config.dual_engine
            strategy = DualEngineTradingStrategy(config=de_cfg)

            # Simple position tracker for dual-engine
            class DualEngineSystem:
                def __init__(self, strategy, symbol):
                    self.strategy = strategy
                    self.symbol = symbol
                    self.position = 0
                    self.avg_cost = 0.0
                    self.total_pnl = 0.0
                    self.trades = []

                def on_board(self, board):
                    """Process market data"""
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

                    self.strategy.update_indicators(tick)
                    signal = self.strategy.generate_signal(tick)

                    if signal:
                        self._execute_signal(signal, tick.last_price)

                def _execute_signal(self, signal, price):
                    """Execute trading signal"""
                    qty = signal.quantity
                    reason_map = {1: 'core', 2: 'grid_buy', 3: 'grid_sell',
                                  4: 'exit', 5: 'trailing', 6: 'profit'}
                    reason = reason_map.get(signal.reason_code, f'code_{signal.reason_code}')

                    if signal.action == 0:  # BUY
                        cost = self.position * self.avg_cost + qty * price
                        self.position += qty
                        self.avg_cost = cost / self.position if self.position > 0 else 0
                        self.trades.append(('BUY', qty, price, reason))
                        print(f"[{reason}] BUY {qty}股 @ {price:.2f} (持仓={self.position})")

                        # ✅ 关键：通知策略持仓变化
                        self.strategy.on_fill(self.symbol, "BUY", price, qty)

                    elif signal.action == 1:  # SELL
                        if self.position >= qty:
                            pnl = (price - self.avg_cost) * qty
                            self.total_pnl += pnl
                            self.position -= qty
                            self.trades.append(('SELL', qty, price, reason, pnl))
                            print(f"[{reason}] SELL {qty}股 @ {price:.2f} (持仓={self.position}, 盈亏={pnl:.0f})")

                            # ✅ 关键：通知策略持仓变化
                            self.strategy.on_fill(self.symbol, "SELL", price, qty)

                def print_status(self):
                    """Print system status"""
                    status = self.strategy.get_strategy_status(self.symbol)
                    print(f"\n双引擎策略状态:")
                    print(f"  持仓: {self.position} 股")
                    print(f"  成本价: {self.avg_cost:.2f}")
                    print(f"  累计盈亏: {self.total_pnl:.0f} JPY")
                    print(f"  趋势状态: {'震荡上行✓' if status.get('trend_up') else '趋势失效✗'}")
                    print(f"  网格中心: {status.get('grid_center', 0):.2f}")
                    print(f"  网格层数: {status.get('active_grid_levels', 0)}")

            system = DualEngineSystem(strategy, system_config.SYMBOLS[0])
            print("\n✓ 双引擎策略初始化成功")

        print("\n开始模拟测试...\n")
        
        base_price = 1000.0
        tick_count = 0
        
        for i in range(200):
            base_price += random.uniform(-2.0, 2.0)
            base_price = max(950.0, min(base_price, 1050.0))
            
            spread = random.uniform(1.0, 3.0)
            bid_price = base_price - spread/2
            ask_price = base_price + spread/2
            
            board = {
                "symbol": system_config.SYMBOLS[0],
                "timestamp": datetime.now(),
                "best_bid": bid_price,
                "best_ask": ask_price,
                "last_price": base_price,
                "bids": [(bid_price - i, random.randint(100, 500)) for i in range(5)],
                "asks": [(ask_price + i, random.randint(100, 500)) for i in range(5)],
                "trading_volume": random.randint(10000, 50000),
                "buy_market_order": random.randint(100, 1000),
                "sell_market_order": random.randint(100, 1000),
            }
            
            system.on_board(board)
            tick_count += 1

            # HFT mode needs fill simulation
            if strategy_config.mode == 'hft':
                fills = gateway.simulate_fills(base_price)
                for fill in fills:
                    system.on_fill(fill)

            await asyncio.sleep(0.01)
            
            if (i + 1) % 100 == 0:
                print(f"\n{'='*60}")
                print(f"进度: {i+1}/200 ticks  |  当前价格: {base_price:.1f}")
                print(f"{'='*60}")
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
        
    except Exception as e:
        print(f"\n✗ 系统错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
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
