# Kabu HFT 交易系统 - 完整代码审查报告

生成时间: 2025-12-01
审查范围: 完整代码库

---

## 执行摘要

### 1. 代码可运行性 ✅

**结论**: 代码可以运行,但有严重逻辑错误

- ✅ Python语法正确
- ✅ 导入路径已修复
- ✅ 异步/同步接口统一
- ❌ 仓位管理存在致命缺陷

### 2. 策略逻辑 ⚠️

**结论**: 策略设计合理,但实现有重大缺陷

**已修复的问题:**
- ✅ Bid/Ask字段映射已修正(`kabu_data_converter_fixed.py`)
- ✅ 订单流策略已替换为不依赖缺失字段的版本
- ✅ 信用交易参数已修复
- ✅ `on_fill`字段不一致已修复

**新发现的致命问题:**
- ❌ **仓位管理完全失控** (最严重)
- ❌ 策略未正确遵守meta管理器的限制
- ❌ 模拟网关缺少仓位检查

### 3. 逻辑错误清单

#### 错误 #1: 仓位管理失效 🚨 CRITICAL

**症状:**
```
测试运行200 ticks后:
- 目标仓位: 400股
- 实际仓位: -296亿股 (!!!!)
- 盈亏: +134万亿日元 (虚假数据)
```

**根本原因:**

1. **策略侧**: 策略调用`meta.on_signal()`检查权限,但**忽略了返回值继续下单**
   ```python
   # market_making_strategy.py line 245-249
   can_exec, msg = self.meta.on_signal(...)
   if not can_exec:
       return  # 这里确实return了,但问题在于...
   ```

2. **Meta侧**: `can_execute_signal()`检查逻辑有BUG
   ```python
   # meta_strategy_manager.py line 134-141
   if side == "BUY":
       new_pos = state.position + quantity
       if new_pos > state.max_position:  # 检查单策略限制
           return False, f"{strategy_type.name} 多头仓位超限"

       new_total = self.total_position + quantity
       if new_total > self.cfg.max_total_position:  # 检查总限制
           return False, "总仓位超限"
   ```

   **问题**: 当position已经超限时,检查`new_pos > state.max_position`对**负数仓位无效**!

   例如:
   - 当前position = -1000万 (空头)
   - max_position = 100
   - 尝试SELL再开100股空单
   - new_pos = -1000万 - 100 = -1000.01万
   - 检查: -1000.01万 > 100 ? → False (检查失败!)
   - 结果: 允许继续开仓!

3. **根本缺陷**: 仓位限制检查**只检查单边**,没有检查`abs(position)`

**修复方案:**

```python
# 修复meta_strategy_manager.py中的can_execute_signal方法

def can_execute_signal(
    self,
    strategy_type: StrategyType,
    side: str,
    quantity: int,
) -> tuple[bool, str]:
    """判断是否可以执行某个策略的信号"""
    state = self.strategies[strategy_type]

    # ... 现有的enabled和loss检查 ...

    # ✅ 修复: 检查绝对仓位
    current_abs_pos = abs(state.position)
    if current_abs_pos >= state.max_position:
        # 只允许平仓方向的订单
        if (side == "BUY" and state.position >= 0) or \
           (side == "SELL" and state.position <= 0):
            return False, f"{strategy_type.name} 仓位已达上限,仅允许平仓"

    # 计算新仓位(考虑正负)
    if side == "BUY":
        new_pos = state.position + quantity
    else:
        new_pos = state.position - quantity

    # 检查新仓位的绝对值
    if abs(new_pos) > state.max_position:
        return False, f"{strategy_type.name} 新仓位{abs(new_pos)}超过限额{state.max_position}"

    # 检查总仓位
    new_total = self.total_position + (quantity if side == "BUY" else -quantity)
    if abs(new_total) > self.cfg.max_total_position:
        return False, f"总仓位{abs(new_total)}超限{self.cfg.max_total_position}"

    return True, "OK"
```

#### 错误 #2: 缺少实际风控层

**问题**: 即使meta检查通过,也需要在gateway层再次验证

**修复**: 为DummyGateway添加最后防线
```python
# main.py 中的 DummyGateway

def __init__(self):
    self.orders = {}
    self.positions = {}  # ✅ 新增: 跟踪实际持仓

def send_order(self, symbol, side, price, qty, order_type="LIMIT"):
    # ✅ 新增: 最后的仓位检查
    current_pos = self.positions.get(symbol, 0)
    new_pos = current_pos + qty if side == "BUY" else current_pos - qty

    MAX_ALLOWED = 500  # 硬限制
    if abs(new_pos) > MAX_ALLOWED:
        print(f"[网关拒绝] {side} {symbol}: 超过网关最大仓位限制{MAX_ALLOWED}")
        return None

    # ... 原有的订单逻辑 ...
```

#### 错误 #3: 策略没有自检仓位

**问题**: 策略在生成信号前应该先检查自己的position

**修复建议**: 在每个策略的开仓方法中添加
```python
# 示例: market_making_strategy.py

def _quote_side(self, now: datetime, side: str, target_price: Optional[float]) -> None:
    # ✅ 新增: 策略自检
    if abs(self.position) >= self.cfg.max_long_position:
        # 不再开新仓
        return

    # ... 原有逻辑 ...
```

---

## 4. 真实kabuSTATION网关配置

### 当前配置 (模拟)

```python
# config/system_config.py
WS_URL: str = "ws://localhost:18080/kabusapi/websocket"
REST_URL: str = "http://localhost:18080/kabusapi"
API_PASSWORD: str = "japan202303"
```

### 接入真实API的步骤

#### 步骤 1: 启动kabuSTATION

1. 打开kabuSTATION应用
2. 进入 "设定" → "API设定"
3. 确认API功能已启用
4. 记录端口号(默认18080生产环境,18081测试环境)

#### 步骤 2: 获取API密码

1. 在kabuSTATION中生成API密码
2. 修改`config/system_config.py`:
   ```python
   API_PASSWORD: str = "你的真实密码"  # 替换japan202303
   ```

#### 步骤 3: 测试连接

```python
# 运行连接测试
python -c "
import asyncio
from config.system_config import SystemConfig
from market.kabu_feed import KabuMarketFeed

async def test():
    config = SystemConfig()
    feed = KabuMarketFeed(config)
    success = await feed.subscribe(['4680'])
    print(f'连接结果: {success}')

asyncio.run(test())
"
```

预期输出:
```
✓ 使用orjson加速JSON解析
✓ API认证成功, Token: xxxxxxxxx...
✓ 行情注册成功: ['4680']
连接结果: True
```

#### 步骤 4: 启动实盘系统

**⚠️ 重要**: 必须先完成仓位管理修复!

```python
# 创建 run_live.py
import asyncio
from config.system_config import SystemConfig
from config.trading_config import TradingConfig
from config.strategy_config import StrategyConfig
from market.kabu_feed import KabuMarketFeed
from execution.kabu_executor import KabuOrderExecutor
from integrated_trading_system import IntegratedTradingSystem

async def main():
    sys_config = SystemConfig()
    trading_config = TradingConfig()
    strategy_config = StrategyConfig(mode='hft')

    # 真实组件
    executor = KabuOrderExecutor(sys_config)
    feed = KabuMarketFeed(sys_config)

    # ⚠️ 从小仓位开始!
    system = IntegratedTradingSystem(
        gateway=executor,
        symbol="4680",
        tick_size=0.1,
    )
    system.meta_manager.cfg.max_total_position = 100  # 先用100股!

    # 订阅行情
    success = await feed.subscribe([sys_config.SYMBOLS[0]])
    if not success:
        print("订阅失败")
        return

    # 启动行情流
    tick_queue = asyncio.Queue(maxsize=65536)

    async def process_ticks():
        while True:
            tick = await tick_queue.get()
            # 转换为board格式
            board = {
                "symbol": tick.symbol,
                "timestamp": datetime.now(),
                "best_bid": tick.bid_price,
                "best_ask": tick.ask_price,
                "last_price": tick.last_price,
                # ... 其他字段 ...
            }
            system.on_board(board)

    await asyncio.gather(
        feed.start_streaming(tick_queue),
        process_ticks()
    )

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 5. 代码完善建议

### 5.1 必须修复项 (阻塞上线)

- [ ] 修复仓位管理逻辑(meta_strategy_manager.py)
- [ ] 为DummyGateway添加硬限制
- [ ] 为真实executor添加安全检查
- [ ] 编写完整的单元测试

### 5.2 强烈建议项

- [ ] 添加日志记录(使用logging模块)
- [ ] 添加性能监控(订单延迟,成交率)
- [ ] 实现WebSocket断线重连逻辑测试
- [ ] 添加异常情况的告警机制

### 5.3 优化项

- [ ] 优化盘口数据解析性能
- [ ] 缓存tick_size计算结果
- [ ] 批量处理订单状态查询
- [ ] 添加策略参数动态调整

---

## 6. 风险评估

### 高风险项 🔴

1. **仓位管理缺陷** - 可能导致无限开仓
   - 风险等级: CRITICAL
   - 修复优先级: P0
   - 预计影响: 可能在数秒内亏损全部资金

2. **止损逻辑未经验证** - 可能无法及时止损
   - 风险等级: HIGH
   - 修复优先级: P0
   - 预计影响: 单日亏损可能超过限额

3. **网络异常处理不完善** - 断线可能导致仓位无法平仓
   - 风险等级: HIGH
   - 修复优先级: P1
   - 预计影响: 需要手动介入平仓

### 中风险项 🟡

1. **策略参数未经回测** - 可能不适应真实市场
2. **成交假设过于乐观** - 可能出现成交不足
3. **tick数据可能缺失** - WebSocket断连后数据丢失

### 低风险项 🟢

1. API认证token可能过期(可自动重连)
2. 价格精度可能不够(已使用float处理)

---

## 7. 上线检查清单

### 代码层面
- [ ] 所有P0问题已修复
- [ ] 仓位管理通过压力测试
- [ ] 止损逻辑通过测试
- [ ] WebSocket重连通过测试
- [ ] 模拟环境运行24小时无异常

### 配置层面
- [ ] API密码已正确配置
- [ ] 初始仓位限制设为100股
- [ ] 日亏损限额设为5万日元
- [ ] 止损设为10 ticks

### 运维层面
- [ ] 准备好手动平仓预案
- [ ] 设置实时监控告警
- [ ] 准备紧急停止脚本
- [ ] 与券商确认API调用限额

---

## 8. 附录: 关键文件修复清单

| 文件 | 修复内容 | 状态 |
|------|---------|------|
| `strategy/hft/orderflow_alternative_strategy.py` | 修复on_fill字段不一致 | ✅ 已完成 |
| `engine/meta_strategy_manager.py` | 修复仓位检查逻辑 | ❌ 待修复 |
| `main.py` | 为DummyGateway添加仓位跟踪 | ❌ 待修复 |
| `config/system_config.py` | 配置真实API密码 | ⚠️ 需用户操作 |

---

## 9. 总结

### 好消息 ✅
- 核心架构设计合理
- Bid/Ask映射问题已解决
- 代码可以运行

### 坏消息 ❌
- **仓位管理有致命缺陷,绝对不能直接上线**
- 需要完整的测试才能进入真实环境

### 下一步行动
1. **立即修复** meta_strategy_manager.py中的仓位检查逻辑
2. **充分测试** 修复后运行至少1000个tick的压力测试
3. **小额试运行** 从100股开始,观察1天
4. **逐步放大** 确认稳定后逐步增加到400股

**风险提示**: 高频交易可能快速亏损,请务必做好风险控制!
