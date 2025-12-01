from dataclasses import dataclass

@dataclass
class TradingConfig:
    ORDER_UPDATE_THRESHOLD_TICKS: int = 1
    MIN_UPDATE_INTERVAL: float = 0.05
    ORDER_TIMEOUT_SECONDS: int = 5
    MIN_PROFIT_TICKS: int = 5
    TRAIL_TICKS: int = 1
    EXTREME_STOP_LOSS_TICKS: int = 100
    MAX_DAILY_TRADES: int = 500
    MAX_POSITION_SIZE: int = 100
