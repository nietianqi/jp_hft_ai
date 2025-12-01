import asyncio
import time
from typing import List, Optional, Dict
from config.system_config import SystemConfig
from models.market_data import MarketTick
from utils.math_utils import fast_tick_size
from .base import MarketDataFeed

try:
    import orjson as json

    JSON_LOADS = json.loads
    print("✓ 使用orjson加速JSON解析")
except ImportError:
    import json

    JSON_LOADS = json.loads
    print("! 使用标准json库")


class KabuMarketFeed(MarketDataFeed):
    """Kabu Station行情订阅 - 修复买卖价版本"""

    def __init__(self, config: SystemConfig):
        self.config = config
        self.message_count = 0
        self.reconnect_count = 0
        self.api_token: Optional[str] = None
        self.last_ticks: Dict[str, MarketTick] = {}
        self.connection_lost_time = None
        self.debug_mode = getattr(config, 'DEBUG_MODE', True)

    async def subscribe(self, symbols: List[str]) -> bool:
        """订阅行情 - 增强错误处理"""
        """股票注册,注册后返回对应的数据"""
        try:
            import httpx

            timeout = httpx.Timeout(self.config.HTTP_TIMEOUT)
            limits = httpx.Limits(max_connections=self.config.MAX_CONNECTIONS)

            if self.debug_mode:
                print(f"尝试连接API: {self.config.REST_URL}")
                print(f"超时设置: {self.config.HTTP_TIMEOUT}s")

            async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
                # Step 1: 认证
                auth_payload = {"APIPassword": self.config.API_PASSWORD}

                try:
                    auth_response = await client.post(
                        f"{self.config.REST_URL}/token",
                        json=auth_payload
                    )

                    if self.debug_mode:
                        print(f"认证响应状态: {auth_response.status_code}")

                    if auth_response.status_code != 200:
                        print(f"✗ 认证失败: HTTP {auth_response.status_code}")
                        try:
                            error_text = auth_response.text
                            print(f"错误详情: {error_text}")
                        except:
                            pass
                        return False

                    auth_result = auth_response.json()
                    self.api_token = auth_result.get("Token")
                    print("token是--------------------",self.api_token)
                    if not self.api_token:
                        print("✗ 认证响应中未找到Token")
                        return False

                    print(f"✓ API认证成功, Token: {self.api_token[:10]}...")

                except httpx.ConnectError as e:
                    print(f"✗ 无法连接到API服务器: {e}")
                    print("请确认:")
                    print("  1. Kabu Station已启动")
                    print("  2. API功能已启用")
                    print(f"  3. API地址正确: {self.config.REST_URL}")
                    return False

                except httpx.TimeoutException:
                    print(f"✗ 连接超时 (>{self.config.HTTP_TIMEOUT}s)")
                    return False

                # Step 2: 注册行情
                symbols_payload = {"Symbols": [{"Symbol": s, "Exchange": 1} for s in symbols]}

                try:
                    register_response = await client.put(
                        f"{self.config.REST_URL}/register",
                        json=symbols_payload,
                        headers={"X-API-KEY": self.api_token}
                    )

                    if self.debug_mode:
                        print(f"注册响应状态: {register_response.status_code}")

                    if register_response.status_code == 200:
                        print(f"✓ 行情注册成功: {symbols}")
                        return True
                    else:
                        print(f"✗ 行情注册失败: HTTP {register_response.status_code}")
                        try:
                            error_text = register_response.text
                            print(f"注册错误详情: {error_text}")
                        except:
                            pass
                        return False

                except Exception as e:
                    print(f"✗ 行情注册异常: {e}")
                    return False

        except ImportError:
            print("✗ 缺少httpx库，请安装: pip install httpx")
            return False
        except Exception as e:
            print(f"✗ 订阅过程异常: {e}")
            return False

    async def start_streaming(self, tick_queue: asyncio.Queue) -> None:
        """开始行情流 - 完全修复WebSocket连接"""
        try:
            import websockets
            websockets_version = websockets.__version__
            print(f"WebSocket库版本: {websockets_version}")
        except ImportError:
            print("✗ 缺少websockets库，请安装: pip install websockets")
            return

        if not self.api_token:
            print("✗ 没有有效的API Token,无法建立WebSocket连接")
            return

        backoff = 1.0
        batch_buffer = []
        last_batch_time = time.perf_counter()

        while True:
            try:
                # 构建连接参数 - 移除所有可能不兼容的参数
                connect_kwargs = {
                    "uri": self.config.WS_URL,
                    "additional_headers": {"X-API-KEY": self.api_token},
                }

                # 只添加确定支持的参数
                try:
                    # 检测websockets版本并添加支持的参数
                    version_parts = websockets_version.split('.')
                    major_version = int(version_parts[0])

                    if major_version >= 9:
                        connect_kwargs.update({
                            "ping_interval": self.config.WS_PING_INTERVAL,
                            "close_timeout": 5.0,
                        })

                        # 只在较新版本中添加大小限制
                        if major_version >= 10:
                            connect_kwargs.update({
                                "max_size": 2 ** 20,  # 1MB
                            })

                except (ValueError, IndexError):
                    # 版本解析失败，使用最基本的参数
                    print("! WebSocket版本解析失败，使用基础连接参数")

                if self.debug_mode:
                    print(f"WebSocket连接参数: {list(connect_kwargs.keys())}")
                    print(f"正在连接: {self.config.WS_URL}")

                # 建立WebSocket连接
                async with websockets.connect(**connect_kwargs) as websocket:

                    print("✓ WebSocket连接成功")
                    print(f"连接状态: {websocket.state.name}")

                    self.reconnect_count = 0
                    backoff = 1.0
                    self.connection_lost_time = None

                    # 等待并处理消息
                    try:
                        async for message in websocket:
                            await self._process_websocket_message(
                                message, batch_buffer, last_batch_time, tick_queue
                            )

                    except websockets.exceptions.ConnectionClosed as e:
                        print(f"WebSocket连接正常关闭: {e.code} - {e.reason}")

                    except asyncio.CancelledError:
                        print("WebSocket任务被取消")
                        break

            except websockets.exceptions.InvalidURI as e:
                print(f"✗ WebSocket URI无效: {e}")
                print(f"请检查WebSocket地址: {self.config.WS_URL}")
                print("标准格式应该是: ws://localhost:18080/kabusapi/websocket")
                break

            except websockets.exceptions.InvalidHandshake as e:
                print(f"✗ WebSocket握手失败: {e}")
                print("可能原因:")
                print("  1. API Token无效或过期")
                print("  2. Kabu Station API服务未启动")
                await asyncio.sleep(5)

            except OSError as e:
                print(f"✗ 网络连接错误: {e}")
                print("请检查:")
                print("  1. Kabu Station是否正在运行")
                print("  2. 网络连接是否正常")
                print("  3. 端口18080是否被占用")

            except Exception as e:
                print(f"✗ WebSocket连接异常: {type(e).__name__}: {e}")
                if self.debug_mode:
                    import traceback
                    traceback.print_exc()

            # 重连逻辑
            self.reconnect_count += 1

            if self.reconnect_count > 10:
                print("✗ 达到最大重连次数，停止尝试")
                break

            print(f"第{self.reconnect_count}次重连，等待 {backoff:.1f} 秒...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.2, 30)  # 最大30秒间隔

    async def _process_websocket_message(self, message, batch_buffer, last_batch_time, tick_queue):
        """处理WebSocket消息 - 增强调试版"""
        try:
            # 消息类型处理
            if isinstance(message, bytes):
                message = message.decode('utf-8')

            # JSON解析
            try:
                data = JSON_LOADS(message)
            except (json.JSONDecodeError, ValueError) as e:
                if self.debug_mode and self.message_count < 5:
                    print(f"[WebSocket] JSON解析失败: {e}")
                    print(f"  原始消息前100字符: {str(message)[:100]}")
                return

            # 调试：显示消息结构
            if self.message_count < 3:
                print(f"[WebSocket] 消息 #{self.message_count + 1} 结构:")
                if isinstance(data, dict):
                    print(f"  字段: {list(data.keys())}")
                    symbol = data.get('Symbol', 'N/A')
                    price = data.get('CurrentPrice', 'N/A')
                    volume = data.get('TradingVolume', 'N/A')
                    # 🔥 新增：打印原始买卖价
                    bid = data.get('BidPrice', 'N/A')
                    ask = data.get('AskPrice', 'N/A')
                    print(f"  Symbol: {symbol}, CurrentPrice: {price}, Volume: {volume}")
                    print(f"  原始BidPrice: {bid}, 原始AskPrice: {ask}")

            # 解析为Tick对象 - 关键步骤
            tick = self._parse_tick_data(data)

            if tick:
                batch_buffer.append(tick)
                self.message_count += 1

                # 批量处理或时间触发
                current_time = time.perf_counter()
                should_flush = (
                        len(batch_buffer) >= self.config.BATCH_SIZE or
                        current_time - last_batch_time > 0.001
                )

                if should_flush and batch_buffer:
                    # 入队前打印确认
                    print(f"[WebSocket] 准备入队 {len(batch_buffer)} 个tick")

                    # 批量放入队列
                    for tick_item in batch_buffer:
                        try:
                            tick_queue.put_nowait(tick_item)
                            print(f"[WebSocket] ✓ Tick已入队: {tick_item.symbol} @ {tick_item.last_price}")
                        except asyncio.QueueFull:
                            try:
                                tick_queue.get_nowait()  # 丢弃最老的
                                tick_queue.put_nowait(tick_item)
                                print(f"[WebSocket] 队列满，替换旧数据")
                            except asyncio.QueueEmpty:
                                pass

                    batch_buffer.clear()
                    last_batch_time = current_time

            else:
                # 未生成tick时显示原因
                if self.debug_mode and self.message_count < 10:
                    symbol = data.get('Symbol', 'Unknown') if isinstance(data, dict) else 'N/A'
                    print(f"[WebSocket] 消息 #{self.message_count + 1} 未生成tick - Symbol: {symbol}")

            # 定期统计
            if self.message_count > 0 and self.message_count % 50 == 0:
                print(f"[WebSocket] 已处理 {self.message_count} 条消息，生成 {len(self.last_ticks)} 个有效tick")

        except Exception as e:
            print(f"[WebSocket] 处理消息异常: {e}")
            if self.debug_mode:
                import traceback
                traceback.print_exc()

    def _parse_tick_data(self, data: Dict) -> Optional[MarketTick]:
        """解析行情数据 - 🔥 修复买卖价字段映射"""
        try:
            # 必须是字典类型
            if not isinstance(data, dict):
                if self.debug_mode:
                    print(f"[行情解析] 丢弃原因: 数据类型错误 {type(data)}")
                return None

            # 获取股票代码
            symbol = data.get("Symbol")
            if not symbol:
                if self.debug_mode:
                    print(f"[行情解析] 丢弃原因: 缺少Symbol字段")
                return None

            # 检查是否为关注的标的
            if symbol not in self.config.SYMBOLS:
                if self.debug_mode and self.message_count < 20:
                    print(f"[行情解析] 丢弃原因: 跳过非关注标的 {symbol}")
                return None

            # 获取当前价格
            current_price = data.get("CurrentPrice")
            if current_price is None:
                print(f"[行情解析] {symbol} 丢弃原因: 缺少CurrentPrice字段")
                return None

            try:
                current_price = float(current_price)
                if current_price <= 0:
                    print(f"[行情解析] {symbol} 丢弃原因: CurrentPrice无效 {current_price}")
                    return None
            except (ValueError, TypeError):
                print(f"[行情解析] {symbol} 丢弃原因: CurrentPrice转换失败 {current_price}")
                return None

            # 🔥🔥🔥 关键修复：正确映射Kabu字段
            # Kabu Station使用日本术语，与国际标准相反：
            # - Kabu的BidPrice(売気配) = 卖方报价 = 国际标准的Ask
            # - Kabu的AskPrice(買気配) = 买方报价 = 国际标准的Bid
            try:
                # 正确的字段映射（交换）
                raw_bid = data.get("AskPrice")  # Kabu的AskPrice = 买方价格
                raw_ask = data.get("BidPrice")  # Kabu的BidPrice = 卖方价格

                # 🔥 DEBUG：打印原始值用于诊断
                if self.message_count < 10:
                    print(
                        f"[行情解析DEBUG] {symbol} 原始数据: BidPrice={raw_bid}, AskPrice={raw_ask}, CurrentPrice={current_price}")

                # 根据实际情况选择解析策略
                # 如果原始数据中BidPrice和AskPrice都存在且合理
                if raw_bid and raw_ask:
                    bid_price = float(raw_bid)
                    ask_price = float(raw_ask)

                    # 检查是否需要交换（如果发现BidPrice > AskPrice，说明字段定义相反）
                    if bid_price > ask_price:
                        print(f"[行情解析] {symbol} 检测到字段反转：交换买卖价")
                        bid_price, ask_price = ask_price, bid_price

                    # 再次验证：买价应该 <= 成交价 <= 卖价（允许小偏差）
                    if bid_price > current_price + 10 or ask_price < current_price - 10:
                        print(f"[行情解析] {symbol} 买卖价异常，使用计算值")
                        tick = fast_tick_size(current_price)
                        bid_price = current_price - tick
                        ask_price = current_price + tick

                else:
                    # 如果缺少买卖价，根据成交价和tick_size计算
                    tick = fast_tick_size(current_price)
                    bid_price = current_price - tick
                    ask_price = current_price + tick
                    print(f"[行情解析] {symbol} 缺少买卖价，使用计算值: bid={bid_price}, ask={ask_price}")

                # 获取买卖量
                bid_qty = int(data.get("BidQty", 100))
                ask_qty = int(data.get("AskQty", 100))

                # 获取成交量
                raw_volume = data.get("TradingVolume", 0)
                volume = int(raw_volume) if raw_volume is not None else 0

            except (ValueError, TypeError) as e:
                print(f"[行情解析] {symbol} 买卖盘数据转换失败: {e}")
                # 使用安全的默认值
                tick = fast_tick_size(current_price)
                bid_price = current_price - tick
                ask_price = current_price + tick
                bid_qty = 100
                ask_qty = 100
                volume = 0

            # 最终数据校验
            if bid_price <= 0:
                bid_price = current_price - fast_tick_size(current_price)
                print(f"[行情解析] {symbol} 修正买价: {bid_price}")

            if ask_price <= 0:
                ask_price = current_price + fast_tick_size(current_price)
                print(f"[行情解析] {symbol} 修正卖价: {ask_price}")

            # 确保买价 < 卖价（保持合理价差）
            if ask_price <= bid_price:
                spread = fast_tick_size(current_price)
                mid_price = (bid_price + ask_price) / 2
                bid_price = mid_price - spread / 2
                ask_price = mid_price + spread / 2
                print(f"[行情解析] {symbol} 修正价差: 买={bid_price:.1f}, 卖={ask_price:.1f}")

            # 创建Tick对象
            tick = MarketTick(
                symbol=symbol,
                last_price=current_price,
                bid_price=bid_price,
                ask_price=ask_price,
                bid_size=max(bid_qty, 0),
                ask_size=max(ask_qty, 0),
                volume=max(volume, 0),
                timestamp_ns=time.perf_counter_ns()
            )

            # 更新缓存
            self.last_ticks[symbol] = tick

            # 成功生成tick的日志
            if self.debug_mode and len(self.last_ticks) <= 3:
                print(
                    f"[行情解析] ✓ 生成tick [{symbol}]: 价格={current_price}, 买={bid_price:.1f}, 卖={ask_price:.1f}, 量={volume}")

            return tick

        except Exception as e:
            print(f"[行情解析] Tick解析异常: {e}")
            if self.debug_mode:
                import traceback
                traceback.print_exc()
            return None

    def get_connection_stats(self) -> Dict:
        """获取连接统计信息"""
        return {
            'message_count': self.message_count,
            'reconnect_count': self.reconnect_count,
            'cached_symbols': len(self.last_ticks),
            'api_token_available': self.api_token is not None,
            'connection_lost_time': self.connection_lost_time
        }