from abc import ABC, abstractmethod
from typing import Optional

class OrderExecutor(ABC):
    @abstractmethod
    async def submit_buy_order(self, signal) -> Optional[str]:
        pass

    @abstractmethod
    async def submit_sell_order(self, symbol: str, quantity: int, price: float, reason: str) -> Optional[str]:
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str) -> str:
        pass
    
    async def close(self):
        pass
