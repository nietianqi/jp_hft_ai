from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass(slots=True)
class TradingSignal:
    symbol: str
    action: int
    price: float
    quantity: int
    confidence: float
    reason_code: int = 0
    timestamp_ns: int = 0

@dataclass(slots=True)
class Position:
    symbol: str
    quantity: int
    avg_price: float
    entry_time: datetime
    is_margin: bool = True
    unrealized_pnl: float = 0.0
    margin_debt: float = 0.0
