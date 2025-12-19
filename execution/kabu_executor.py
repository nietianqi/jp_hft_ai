# -*- coding: utf-8 -*-
"""
kabu_executor.py - 修复版Kabu订单执行器
"""

import asyncio
import time
from typing import Optional
import httpx

from config.system_config import SystemConfig
from models.trading_models import TradingSignal
from utils.math_utils import fast_round_tick
from .base import OrderExecutor

try:
    import orjson as json
    JSON_DUMPS = json.dumps
    JSON_LOADS = json.loads
except ImportError:
    import json
    JSON_DUMPS = lambda x: json.dumps(x, separators=(',', ':')).encode()
    JSON_LOADS = json.loads


class KabuOrderExecutor(OrderExecutor):
    """修复版Kabu订单执行器"""

    def __init__(self, config: SystemConfig):
        self.config = config
        self.http_client: Optional[httpx.AsyncClient] = None
        self.api_token: Optional[str] = None
        self.order_cache = {}
        self.rate_limiter = asyncio.Semaphore(10)
        self.recent_orders = {}
        self.failed_orders = set()

    async def _ensure_client(self):
        if self.http_client is None:
            timeout = httpx.Timeout(self.config.HTTP_TIMEOUT)
            async with httpx.AsyncClient(timeout=timeout) as temp_client:
                auth_payload = {"APIPassword": self.config.API_PASSWORD}
                response = await temp_client.post(
                    f"{self.config.REST_URL}/token",
                    content=JSON_DUMPS(auth_payload),
                    headers={"Content-Type": "application/json"}
                )

                if response.status_code != 200:
                    raise Exception(f"认证失败: {response.status_code}")

                result = JSON_LOADS(response.content)
                self.api_token = result["Token"]

            limits = httpx.Limits(
                max_connections=self.config.MAX_CONNECTIONS,
                max_keepalive_connections=self.config.MAX_CONNECTIONS // 2
            )

            self.http_client = httpx.AsyncClient(
                base_url=self.config.REST_URL,
                timeout=httpx.Timeout(self.config.HTTP_TIMEOUT),
                headers={
                    "X-API-KEY": self.api_token,
                    "Content-Type": "application/json"
                },
                limits=limits
            )

            print("✓ Kabu API客户端已初始化")

    async def submit_buy_order(self, signal: TradingSignal) -> Optional[str]:
        """修复版:正确的信用交易参数"""
        async with self.rate_limiter:
            await self._ensure_client()

            if signal.symbol in self.failed_orders:
                return None

            payload = {
                "Symbol": signal.symbol,
                "Exchange": 1,
                "SecurityType": 1,
                "Side": "2",  # ✅修复:字符串
                "CashMargin": 2,
                "MarginTradeType": 2,  # ✅修复:一般信用
                "DelivType": 0,
                "FundType": "AA",  # ✅修复:日计り
                "AccountType": 4,
                "Qty": signal.quantity,
                "Price": int(fast_round_tick(signal.price)),
                "ExpireDay": 0,
                "FrontOrderType": 20,
                "ClosePositionOrder": 0  # ✅修复:新建仓
            }

            start_time = time.perf_counter_ns()

            try:
                response = await self.http_client.post(
                    "/sendorder",
                    content=JSON_DUMPS(payload)
                )

                latency = time.perf_counter_ns() - start_time

                if response.status_code == 200:
                    result = JSON_LOADS(response.content)
                    order_id = result.get("OrderId")

                    if order_id:
                        self.recent_orders[order_id] = time.time()
                        self.order_cache[order_id] = {
                            'symbol': signal.symbol,
                            'side': 'BUY',
                            'quantity': signal.quantity,
                            'price': signal.price,
                            'submit_time': time.time(),
                            'latency_ns': latency
                        }

                        print(f"[{signal.symbol}] 买入: {order_id} @ {signal.price:.1f}")
                        return order_id
                else:
                    # ✅新增:打印详细错误信息
                    error_body = response.content.decode('utf-8') if response.content else 'No response body'
                    print(f"❌ 买入订单失败 [{signal.symbol}]:")
                    print(f"  HTTP状态码: {response.status_code}")
                    print(f"  错误响应: {error_body}")
                    print(f"  订单参数: {payload}")
                    self.failed_orders.add(signal.symbol)
                    return None

            except Exception as e:
                self.failed_orders.add(signal.symbol)
                print(f"买入异常: {e}")
                return None

    async def submit_sell_order(self, symbol: str, quantity: int, price: float, reason: str) -> Optional[str]:
        """修复版:平仓订单"""
        async with self.rate_limiter:
            await self._ensure_client()

            payload = {
                "Symbol": symbol,
                "Exchange": 1,
                "SecurityType": 1,
                "Side": "1",  # ✅修复:字符串
                "CashMargin": 2,
                "MarginTradeType": 2,
                "DelivType": 0,
                "FundType": "AA",
                "AccountType": 4,
                "Qty": quantity,
                "Price": int(fast_round_tick(price)),
                "ExpireDay": 0,
                "FrontOrderType": 20,
                "ClosePositionOrder": 1  # ✅修复:平仓
            }

            try:
                response = await self.http_client.post(
                    "/sendorder",
                    content=JSON_DUMPS(payload)
                )

                if response.status_code == 200:
                    result = JSON_LOADS(response.content)
                    order_id = result.get("OrderId")

                    if order_id:
                        self.order_cache[order_id] = {
                            'symbol': symbol,
                            'side': 'SELL',
                            'quantity': quantity,
                            'price': price,
                            'submit_time': time.time(),
                            'reason': reason
                        }

                        print(f"[{symbol}] 卖出: {order_id} @ {price:.1f} - {reason}")
                        return order_id
                else:
                    # ✅新增:打印详细错误信息
                    error_body = response.content.decode('utf-8') if response.content else 'No response body'
                    print(f"❌ 卖出订单失败 [{symbol}]:")
                    print(f"  HTTP状态码: {response.status_code}")
                    print(f"  错误响应: {error_body}")
                    print(f"  订单参数: {payload}")

                return None

            except Exception as e:
                print(f"卖出异常: {e}")
                return None

    async def cancel_order(self, order_id: str) -> bool:
        async with self.rate_limiter:
            await self._ensure_client()

            try:
                cached = self.order_cache.get(order_id)
                if not cached:
                    return False

                payload = {
                    "OrderID": order_id,
                    "Symbol": cached['symbol'],
                    "Exchange": 1,
                    "SecurityType": 1,
                }

                response = await self.http_client.put(
                    "/cancelorder",
                    content=JSON_DUMPS(payload)
                )

                success = response.status_code == 200
                if success:
                    self.order_cache.pop(order_id, None)

                return success

            except Exception as e:
                return False

    async def get_order_status(self, order_id: str) -> str:
        submit_time = self.recent_orders.get(order_id)
        if submit_time and time.time() - submit_time < 2.0:
            return 'PENDING'

        async with self.rate_limiter:
            await self._ensure_client()

            try:
                response = await self.http_client.get(f"/orders/{order_id}")

                if response.status_code == 200:
                    result = JSON_LOADS(response.content)
                    state = result.get('State', 0)

                    if state == 1 or state == 2:
                        return 'PENDING'
                    elif state == 3:
                        exec_qty = int(result.get('CumQty', 0))
                        order_qty = int(result.get('OrderQty', 0))
                        if exec_qty == 0:
                            return 'NEW'
                        elif exec_qty < order_qty:
                            return 'PARTIALLY_FILLED'
                        else:
                            return 'FILLED'
                    elif state == 4:
                        return 'PENDING_CANCEL'
                    elif state == 5:
                        return 'CANCELLED'
                    else:
                        return 'UNKNOWN'

                elif response.status_code == 404:
                    return 'NOT_FOUND'
                else:
                    return 'ERROR'

            except Exception as e:
                return 'ERROR'

    def send_order(self, symbol: str, side: str, price: float, qty: int, order_type: str = "LIMIT", strategy_type=None) -> Optional[str]:
        """同步接口:发送订单(兼容策略调用) - 使用线程池处理

        Args:
            strategy_type: 策略类型标识(用于订单归属追踪)
        """
        import asyncio
        import concurrent.futures
        import threading

        # 在新线程中运行异步任务
        result = [None]
        exception = [None]

        def run_async():
            try:
                # 创建新的事件循环
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                if side == "BUY":
                    from models.trading_models import TradingSignal
                    signal = TradingSignal(
                        symbol=symbol,
                        action=1,  # BUY action
                        quantity=qty,
                        price=price,
                        confidence=1.0
                    )
                    result[0] = loop.run_until_complete(self.submit_buy_order(signal))
                else:
                    result[0] = loop.run_until_complete(
                        self.submit_sell_order(symbol, qty, price, "strategy_exit")
                    )

                loop.close()
            except Exception as e:
                exception[0] = e

        thread = threading.Thread(target=run_async)
        thread.start()
        thread.join(timeout=5.0)  # 5秒超时

        if exception[0]:
            print(f"[Executor] 下单异常: {exception[0]}")
            return None

        return result[0]

    def cancel_order(self, order_id: str) -> bool:
        """同步接口:撤单(兼容策略调用)"""
        # 简化版本:直接返回False,真实环境需要实现
        print(f"[Executor] 撤单请求: {order_id} (当前为简化实现)")
        return False

    async def close(self):
        if self.http_client:
            await self.http_client.aclose()
            self.http_client = None
