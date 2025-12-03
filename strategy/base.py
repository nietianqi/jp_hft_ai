# -*- coding: utf-8 -*-
"""
strategy/base.py

交易策略基类定义
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict
from models.market_data import MarketTick
from models.trading_models import TradingSignal


class TradingStrategy(ABC):
    """交易策略基类"""

    def __init__(self):
        """初始化策略"""
        pass

    @abstractmethod
    def update_indicators(self, tick: MarketTick) -> None:
        """
        更新技术指标

        Args:
            tick: 市场Tick数据
        """
        pass

    @abstractmethod
    def generate_signal(self, tick: MarketTick) -> Optional[TradingSignal]:
        """
        生成交易信号

        Args:
            tick: 市场Tick数据

        Returns:
            TradingSignal 或 None
        """
        pass

    def get_strategy_status(self, symbol: str) -> Dict[str, float]:
        """
        获取策略状态（可选实现）

        Args:
            symbol: 股票代码

        Returns:
            状态字典
        """
        return {}

    def get_performance_metrics(self) -> Dict[str, float]:
        """
        获取性能指标（可选实现）

        Returns:
            性能指标字典
        """
        return {}
