from dataclasses import dataclass
from typing import List

@dataclass
class SystemConfig:
    """系统配置示例 - 请复制为system_config.py并修改"""

    # ⚠️ API配置 - 请修改为你的真实密码
    WS_URL: str = "ws://localhost:18080/kabusapi/websocket"
    REST_URL: str = "http://localhost:18080/kabusapi"
    API_PASSWORD: str = "YOUR_PASSWORD_HERE"  # ⚠️ 在这里填写你的API密码

    # 交易标的
    SYMBOLS: List[str] = None
    TRADING_UNIT: int = 100

    # 性能配置
    TICK_QUEUE_SIZE: int = 65536
    BATCH_SIZE: int = 1
    HTTP_TIMEOUT: float = 1.0
    WS_PING_INTERVAL: float = 20.0
    MAX_CONNECTIONS: int = 8

    def __post_init__(self):
        if self.SYMBOLS is None:
            self.SYMBOLS = ["4680"]  # 默认标的

        # 验证API密码已配置
        if self.API_PASSWORD == "YOUR_PASSWORD_HERE":
            raise ValueError(
                "请先配置API密码!\n"
                "1. 复制 config/system_config.example.py 为 config/system_config.py\n"
                "2. 在system_config.py中填写你的真实API密码"
            )
