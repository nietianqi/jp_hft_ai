# -*- coding: utf-8 -*-
"""
测试网格中心初始化修复

验证：
1. 网格中心使用EMA慢线初始化（避免在价格高点初始化）
2. 买入发生在价格低于中心时
3. 卖出发生在价格高于中心且盈利时
"""

from config.strategy_config import StrategyConfig
from strategy.original.dual_engine_strategy import DualEngineTradingStrategy
from models.market_data import MarketTick


def test_grid_center_initialization():
    """测试网格中心初始化逻辑"""

    # 初始化策略
    cfg = StrategyConfig().dual_engine
    strategy = DualEngineTradingStrategy(config=cfg)
    symbol = "3697"

    # 模拟价格序列：先建立趋势（价格逐步上升），然后在高点触发网格
    test_prices = [
        # 阶段1: 建立上升趋势 (60个tick，用于计算EMA60)
        *[1000 + i * 0.5 for i in range(60)],  # 1000 → 1029.5

        # 阶段2: 趋势确认（继续上升）
        *[1030 + i * 0.3 for i in range(20)],  # 1030 → 1035.7

        # 阶段3: 价格冲高（这是我们要避免用作网格中心的高点）
        1050, 1055, 1060,  # 价格冲到高点

        # 阶段4: 价格回落（应该在回落时买入，因为网格中心是EMA慢线）
        1055, 1050, 1045, 1040, 1035, 1030,
    ]

    print("=" * 80)
    print("测试网格中心初始化修复")
    print("=" * 80)
    print("\n预期行为：")
    print("1. 网格中心应该基于EMA慢线（稳定的均线），而不是当前价格")
    print("2. 当价格冲高到1060然后回落时，应该在回落过程中买入")
    print("3. 不应该在价格高点（1060）初始化网格中心\n")

    trades = []
    grid_center_initialized = False

    for i, price in enumerate(test_prices):
        # 构造MarketTick
        tick = MarketTick(
            symbol=symbol,
            timestamp_ns=i * 1_000_000_000,
            last_price=price,
            bid_price=price - 0.1,
            ask_price=price + 0.1,
            bid_size=1000,
            ask_size=1000,
            volume=1000 + i
        )

        # 更新指标
        strategy.update_indicators(tick)

        # 获取状态
        st = strategy.symbol_states.get(symbol)
        if not st:
            continue

        # 记录网格中心初始化时刻
        if st.grid_center > 0 and not grid_center_initialized:
            grid_center_initialized = True
            print(f"\n✓ 网格中心已初始化:")
            print(f"  当前价格: {price:.2f}")
            print(f"  网格中心: {st.grid_center:.2f}")
            print(f"  EMA快线: {st.ema_fast:.2f}")
            print(f"  EMA慢线: {st.ema_slow:.2f}")
            print(f"  趋势状态: {'震荡上行✓' if st.trend_up else '趋势失效✗'}")

            # ✅ 验证：网格中心应该接近EMA慢线，而不是当前价格
            if st.ema_slow > 0:
                center_ema_diff = abs(st.grid_center - st.ema_slow)
                center_price_diff = abs(st.grid_center - price)
                print(f"\n  网格中心与EMA慢线差距: {center_ema_diff:.2f}")
                print(f"  网格中心与当前价差距: {center_price_diff:.2f}")

                if center_ema_diff < 1.0:
                    print(f"  ✓ 修复成功：网格中心基于EMA慢线初始化")
                else:
                    print(f"  ✗ 问题：网格中心未使用EMA慢线")

        # 生成信号
        signal = strategy.generate_signal(tick)

        if signal:
            action_str = "BUY" if signal.action == 0 else "SELL"
            reason_map = {1: 'core', 2: 'grid_buy', 3: 'grid_sell',
                         4: 'exit', 5: 'trailing', 6: 'profit'}
            reason = reason_map.get(signal.reason_code, f'code_{signal.reason_code}')

            trades.append({
                'tick': i,
                'price': price,
                'action': action_str,
                'qty': signal.quantity,
                'reason': reason,
                'grid_center': st.grid_center
            })

            print(f"\n[Tick {i:3d}] {action_str} {signal.quantity}股 @ {price:.2f} ({reason})")
            print(f"  网格中心: {st.grid_center:.2f}")
            print(f"  持仓: {st.position} → ", end="")

            # 模拟成交
            strategy.on_fill(symbol, action_str, price, signal.quantity)
            st = strategy.symbol_states[symbol]
            print(f"{st.position}")
            print(f"  成本价: {st.avg_cost_price:.2f}")

    # 总结
    print("\n" + "=" * 80)
    print("测试总结")
    print("=" * 80)
    print(f"总交易数: {len(trades)}")

    if trades:
        print("\n交易详情:")
        for t in trades:
            print(f"  Tick {t['tick']:3d}: {t['action']:4s} {t['qty']:3d}股 @ "
                  f"{t['price']:.2f} ({t['reason']:10s}) [中心={t['grid_center']:.2f}]")

        # 验证买入逻辑
        buys = [t for t in trades if t['action'] == 'BUY' and t['reason'] != 'core']
        if buys:
            print("\n✓ 买入验证:")
            for b in buys:
                if b['price'] < b['grid_center']:
                    print(f"  ✓ Tick {b['tick']}: 价格 {b['price']:.2f} < 中心 {b['grid_center']:.2f} (正确)")
                else:
                    print(f"  ✗ Tick {b['tick']}: 价格 {b['price']:.2f} >= 中心 {b['grid_center']:.2f} (错误！)")

        # 验证卖出逻辑
        sells = [t for t in trades if t['action'] == 'SELL']
        if sells:
            print("\n✓ 卖出验证:")
            for s in sells:
                if s['price'] > s['grid_center']:
                    print(f"  ✓ Tick {s['tick']}: 价格 {s['price']:.2f} > 中心 {s['grid_center']:.2f} (正确)")
                else:
                    print(f"  ✗ Tick {s['tick']}: 价格 {s['price']:.2f} <= 中心 {s['grid_center']:.2f} (错误！)")
    else:
        print("\n⚠️  未产生任何交易（可能趋势未成立或持仓已满）")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    test_grid_center_initialization()
