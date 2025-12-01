from dataclasses import dataclass
import time


@dataclass(slots=True, frozen=True)  # slots for memory efficiency
class MarketTick:
    """高性能市场行情数据"""
    symbol: str
    last_price: float
    bid_price: float
    ask_price: float
    bid_size: int
    ask_size: int
    volume: int
    timestamp_ns: int

    @property
    def spread(self) -> float:
        return max(0.0, self.ask_price - self.bid_price)

    @property
    def mid_price(self) -> float:
        return (self.bid_price + self.ask_price) * 0.5