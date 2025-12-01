from enum import IntEnum

class TradingState(IntEnum):
    IDLE = 0
    PENDING_BUY = 1
    LONG = 2
    FLATTENING = 3
    COOLDOWN = 4

class OrderSide(IntEnum):
    BUY = 0
    SELL = 1
