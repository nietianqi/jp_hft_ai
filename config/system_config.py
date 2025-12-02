from dataclasses import dataclass
from typing import List

@dataclass
class SystemConfig:
    WS_URL: str = "ws://localhost:18080/kabusapi/websocket"
    REST_URL: str = "http://localhost:18080/kabusapi"
    API_PASSWORD: str = "japan202303"
    SYMBOLS: List[str] = None
    TRADING_UNIT: int = 100
    TICK_QUEUE_SIZE: int = 65536
    BATCH_SIZE: int = 1
    HTTP_TIMEOUT: float = 1.0
    WS_PING_INTERVAL: float = 20.0
    MAX_CONNECTIONS: int = 8
    
    def __post_init__(self):
        if self.SYMBOLS is None:
            self.SYMBOLS = ["6425"]
