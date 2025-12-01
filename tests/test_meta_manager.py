#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试元策略管理器的仓位控制逻辑
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.meta_strategy_manager import MetaStrategyManager, MetaStrategyConfig, StrategyType


def test_position_limit_basic():
    """测试基本仓位限制"""
    config = MetaStrategyConfig(
        symbol="4680",
        board_symbol="4680",
        max_total_position=100,
    )

    manager = MetaStrategyManager(config)

    # 测试1: 正常买入应该通过
    can_exec, msg = manager.can_execute_signal(
        StrategyType.MARKET_MAKING,
        "BUY",
        30
    )
    assert can_exec, f"正常买入应该通过: {msg}"
    print("✓ 测试1通过: 正常买入")

    # 测试2: 超限买入应该拒绝
    can_exec, msg = manager.can_execute_signal(
        StrategyType.MARKET_MAKING,
        "BUY",
        200
    )
    assert not can_exec, "超限买入应该拒绝"
    print("✓ 测试2通过: 超限拒绝")


def test_position_limit_with_existing():
    """测试已有仓位时的限制"""
    config = MetaStrategyConfig(
        symbol="4680",
        board_symbol="4680",
        max_total_position=100,
    )

    manager = MetaStrategyManager(config)

    # 模拟已有仓位
    state = manager.strategies[StrategyType.MARKET_MAKING]
    state.position = 80  # 已有80股多头
    manager.total_position = 80

    # 测试: 再买30股应该拒绝(总共110)
    can_exec, msg = manager.can_execute_signal(
        StrategyType.MARKET_MAKING,
        "BUY",
        30
    )
    assert not can_exec, f"超过总限额应该拒绝: {msg}"
    print("✓ 测试3通过: 有仓位时的限制")


def test_position_limit_short():
    """测试空头仓位限制"""
    config = MetaStrategyConfig(
        symbol="4680",
        board_symbol="4680",
        max_total_position=100,
    )

    manager = MetaStrategyManager(config)

    # 模拟空头仓位
    state = manager.strategies[StrategyType.MARKET_MAKING]
    state.position = -90  # 已有90股空头
    manager.total_position = -90

    # 测试: 再卖30股应该拒绝(总共-120)
    can_exec, msg = manager.can_execute_signal(
        StrategyType.MARKET_MAKING,
        "SELL",
        30
    )
    assert not can_exec, f"空头超限应该拒绝: {msg}"
    print("✓ 测试4通过: 空头仓位限制")

    # 测试: 买入平仓应该允许
    can_exec, msg = manager.can_execute_signal(
        StrategyType.MARKET_MAKING,
        "BUY",
        50
    )
    assert can_exec, f"平仓方向应该允许: {msg}"
    print("✓ 测试5通过: 平仓允许")


def test_abs_position_check():
    """测试绝对仓位检查"""
    config = MetaStrategyConfig(
        symbol="4680",
        board_symbol="4680",
        max_total_position=100,
    )

    manager = MetaStrategyManager(config)
    state = manager.strategies[StrategyType.MARKET_MAKING]

    # 测试多头限制
    state.position = 100
    state.max_position = 100
    manager.total_position = 100

    can_exec, msg = manager.can_execute_signal(
        StrategyType.MARKET_MAKING,
        "BUY",
        10
    )
    assert not can_exec, "达到上限后继续开仓应该拒绝"
    print("✓ 测试6通过: 绝对仓位上限检查")

    # 测试平仓应该允许
    can_exec, msg = manager.can_execute_signal(
        StrategyType.MARKET_MAKING,
        "SELL",
        50
    )
    assert can_exec, "平仓应该允许"
    print("✓ 测试7通过: 达限后平仓允许")


def test_overlimit_can_reduce():
    """测试超限后仍可减仓 - 修复bug后新增"""
    config = MetaStrategyConfig(
        symbol="4680",
        board_symbol="4680",
        max_total_position=400,
    )

    manager = MetaStrategyManager(config)
    state = manager.strategies[StrategyType.MARKET_MAKING]

    # 模拟仓位已超限（3000 > 400）
    state.position = 3000
    manager.total_position = 3000

    # 测试1: SELL 1000减到2000，虽然2000还超限，但在减仓应该允许
    can_exec, msg = manager.can_execute_signal(
        StrategyType.MARKET_MAKING,
        "SELL",
        1000
    )
    assert can_exec, f"超限后减仓应该允许: {msg}"
    print("✓ 测试8通过: 超限后可减仓(3000→2000)")

    # 测试2: 继续SELL 1000减到1000，还在减仓应该允许
    state.position = 2000
    manager.total_position = 2000
    can_exec, msg = manager.can_execute_signal(
        StrategyType.MARKET_MAKING,
        "SELL",
        1000
    )
    assert can_exec, f"继续减仓应该允许: {msg}"
    print("✓ 测试9通过: 继续减仓(2000→1000)")

    # 测试3: SELL 1000减到0，完全平仓应该允许
    state.position = 1000
    manager.total_position = 1000
    can_exec, msg = manager.can_execute_signal(
        StrategyType.MARKET_MAKING,
        "SELL",
        1000
    )
    assert can_exec, f"平仓应该允许: {msg}"
    print("✓ 测试10通过: 完全平仓(1000→0)")

    # 测试4: 从500想BUY 200到700，虽然还在限额内但是在增仓，应该拒绝（因为策略限额是120）
    state.position = 500
    state.max_position = 120  # 策略限额
    manager.total_position = 500
    can_exec, msg = manager.can_execute_signal(
        StrategyType.MARKET_MAKING,
        "BUY",
        200
    )
    assert not can_exec, f"超过策略限额应该拒绝: {msg}"
    print("✓ 测试11通过: 超策略限额拒绝增仓")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("运行仓位管理测试")
    print("=" * 60)

    try:
        test_position_limit_basic()
        test_position_limit_with_existing()
        test_position_limit_short()
        test_abs_position_check()
        test_overlimit_can_reduce()

        print("\n" + "=" * 60)
        print("✅ 所有测试通过!")
        print("=" * 60)
        return True

    except AssertionError as e:
        print("\n" + "=" * 60)
        print(f"❌ 测试失败: {e}")
        print("=" * 60)
        return False


if __name__ == "__main__":
    import sys
    success = run_all_tests()
    sys.exit(0 if success else 1)
