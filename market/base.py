from abc import ABC, abstractmethod
from typing import List
import asyncio


class MarketDataFeed(ABC):
    """市场数据抽象接口"""

    @abstractmethod
    async def subscribe(self, symbols: List[str]) -> bool:
        """订阅行情"""
        pass

    @abstractmethod
    async def start_streaming(self, tick_queue: asyncio.Queue) -> None:
        """开始行情流"""
        pass
