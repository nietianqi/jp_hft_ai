# 动态止盈策略使用指南

## 📖 策略理念

**核心思想**: 让利润奔跑，在方向反转时及时止盈，亏损时不止损等待反转。

### 传统止盈止损的问题

```
传统策略:
- 止盈: 盈利2 ticks就平仓 → 利润太小
- 止损: 亏损100 ticks才止损 → 亏损太大
- 移动止盈: 需要先盈利3 ticks才激活 → 错过小波动

问题: 赚小钱，亏大钱 ❌
```

### 动态止盈的优势

```
动态止盈策略:
✅ 有盈利时，方向对 → 继续持有，让利润奔跑
✅ 有盈利时，方向反转 → 立即平仓止盈
✅ 亏损时 → 不止损，等待反转

优势: 赚大钱，亏损可控 ✅
```

---

## ⚙️ 配置参数

### 1. 启用动态止盈

```python
from strategy.hft.market_making_strategy import MarketMakingConfig

config = MarketMakingConfig(
    symbol="4680",
    board_symbol="4680",
    tick_size=0.1,

    # ✅ 启用动态止盈
    enable_dynamic_exit=True,

    # 盈利阈值: 大于此值才算"有盈利"
    dynamic_profit_threshold_ticks=0.5,   # 0.5 tick = 0.05日元

    # 反转阈值: 从最高点回撤多少算"方向反转"
    dynamic_reversal_ticks=0.3,           # 0.3 tick = 0.03日元
)
```

### 2. 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable_dynamic_exit` | bool | True | 启用动态止盈模式 |
| `dynamic_profit_threshold_ticks` | float | 0.5 | 盈利阈值(ticks) |
| `dynamic_reversal_ticks` | float | 0.3 | 方向反转阈值(ticks) |

### 3. 参数调优建议

#### 保守配置 (适合波动小的股票)
```python
dynamic_profit_threshold_ticks=0.3   # 更小的盈利阈值
dynamic_reversal_ticks=0.2           # 更小的反转阈值 → 更快止盈
```

#### 激进配置 (适合波动大的股票)
```python
dynamic_profit_threshold_ticks=1.0   # 更大的盈利阈值
dynamic_reversal_ticks=0.5           # 更大的反转阈值 → 让利润更多奔跑
```

#### 日内交易推荐
```python
dynamic_profit_threshold_ticks=0.5   # 适中
dynamic_reversal_ticks=0.3           # 适中
```

---

## 📊 策略逻辑详解

### 场景1: 盈利后方向反转 → 平仓止盈 ✅

```
买入: 100股 @ 1000.0

Tick 1: 价格 = 1000.6  (盈利 0.6 ticks)
  → 盈利 > 阈值0.5 ✅ 有盈利
  → 价格上涨 ✅ 方向正确
  → 继续持有

Tick 2: 价格 = 1001.2  (盈利 1.2 ticks)
  → 更新最高价 = 1001.2
  → 方向正确，继续持有

Tick 3: 价格 = 1000.9  (盈利 0.9 ticks)
  → 从最高价1001.2回撤 0.3 ticks
  → 回撤 = 反转阈值 ❌ 方向反转!
  → 触发平仓 → 锁定0.9 ticks利润 ✅
```

### 场景2: 方向正确 → 让利润奔跑 🚀

```
买入: 100股 @ 1000.0

Tick 1: 价格 = 1000.6  (盈利 0.6 ticks)
  → 继续持有

Tick 2: 价格 = 1001.0  (盈利 1.0 ticks)
  → 继续持有

Tick 3: 价格 = 1001.5  (盈利 1.5 ticks)
  → 继续持有

Tick 4: 价格 = 1002.0  (盈利 2.0 ticks)
  → 继续持有
  → 只要方向正确，利润可以无限增长! 🚀
```

### 场景3: 亏损时不止损 → 等待反转 ⏳

```
买入: 100股 @ 1000.0

Tick 1: 价格 = 999.5  (亏损 0.5 ticks)
  → 亏损 < 盈利阈值 → 无盈利
  → 不止损，继续持有 ⏳

Tick 2: 价格 = 999.0  (亏损 1.0 ticks)
  → 继续持有，等待反转 ⏳

Tick 3: 价格 = 999.5  (亏损 0.5 ticks)
  → 价格在反弹 ✅
  → 继续持有

Tick 4: 价格 = 1000.6  (盈利 0.6 ticks)
  → 反转成功! 转为盈利状态 ✅
  → 开始监控方向反转
```

---

## 🔄 切换到传统模式

如果想使用传统的止盈止损模式:

```python
config = MarketMakingConfig(
    symbol="4680",

    # ❌ 禁用动态止盈
    enable_dynamic_exit=False,

    # 使用传统移动止盈
    enable_trailing_stop=True,
    trailing_activation_ticks=3,   # 盈利3 ticks后激活
    trailing_distance_ticks=2,     # 回撤2 ticks触发

    # 或使用固定止盈止损
    take_profit_ticks=2,           # 盈利2 ticks平仓
    stop_loss_ticks=100,           # 亏损100 ticks平仓
)
```

---

## 🧪 测试验证

### 运行测试脚本

```bash
python test_dynamic_exit.py
```

### 测试场景

1. **盈利后方向反转** → 应该平仓 ✅
2. **亏损场景** → 不应止损 ✅
3. **方向正确** → 继续持有 ✅

---

## 📈 实盘使用建议

### 1. 先在模拟环境测试

```bash
# 修改 main.py 中的配置
python main.py
```

### 2. 观察关键指标

- **平仓频率**: 太频繁 → 增大 `dynamic_reversal_ticks`
- **利润规模**: 太小 → 增大 `dynamic_reversal_ticks`
- **持仓时间**: 太长 → 减小 `dynamic_reversal_ticks`

### 3. 小仓位实盘测试

```bash
# 配置小仓位(100股)
python run_live.py
```

### 4. 监控日志

```
[MM] [动态止盈] 更新最高价: 1001.2 (盈利=1.2T)
[MM] [动态止盈] 方向反转! 盈利=0.9T, 回撤=0.3T → 平仓
```

---

## ⚠️ 风险提示

### 1. 亏损无止损

```
优势: 等待反转，可能扭亏为盈
风险: 如果股票持续下跌，亏损会不断扩大

建议:
- 设置最大持仓时间(如1小时)
- 设置最大亏损限额(如-50日元)
- 密切监控仓位
```

### 2. 方向判断

```
优势: 快速识别方向反转
风险: 正常波动也可能触发平仓

建议:
- 根据股票波动性调整参数
- 波动大的股票 → 增大反转阈值
- 波动小的股票 → 减小反转阈值
```

### 3. 参数敏感性

```
dynamic_reversal_ticks 太小 → 频繁平仓，利润太小
dynamic_reversal_ticks 太大 → 回撤太多，利润回吐

建议: 回测找最优参数
```

---

## 📚 完整示例

```python
from strategy.hft.market_making_strategy import MarketMakingStrategy, MarketMakingConfig

# 1. 创建配置
config = MarketMakingConfig(
    symbol="4680",
    board_symbol="4680",
    tick_size=0.1,
    lot_size=100,

    # 做市参数
    max_long_position=100,
    base_spread_ticks=2,

    # ✅ 动态止盈配置
    enable_dynamic_exit=True,
    dynamic_profit_threshold_ticks=0.5,   # 盈利0.5 tick算有盈利
    dynamic_reversal_ticks=0.3,           # 回撤0.3 tick算反转

    # 传统止盈止损(不使用)
    enable_trailing_stop=False,
    take_profit_ticks=100,
    stop_loss_ticks=100,
)

# 2. 创建策略
strategy = MarketMakingStrategy(gateway, config, meta_manager)

# 3. 策略会自动运行动态止盈逻辑
# 每个tick都会检查:
# - 是否有盈利?
# - 方向是否反转?
# - 是否需要平仓?
```

---

## 🎯 总结

### 适用场景

✅ **推荐使用**:
- 日内交易
- 波动较大的股票
- 希望让利润奔跑
- 能接受亏损等待反转

❌ **不推荐**:
- 趋势性很强的股票(单边下跌)
- 波动极小的股票
- 需要严格止损的场景

### 核心优势

1. **让利润奔跑** - 方向对时不设上限
2. **快速止盈** - 方向反转立即平仓
3. **等待反转** - 亏损不止损,给反转机会

### 关键参数

```python
enable_dynamic_exit=True             # 必须启用
dynamic_profit_threshold_ticks=0.5   # 根据股票调整
dynamic_reversal_ticks=0.3           # 核心参数,需要优化
```

---

**GitHub**: https://github.com/nietianqi/jp_hft_ai/tree/silly-curie

**最新提交**: e817556 - 实现动态止盈策略

**测试脚本**: `python test_dynamic_exit.py`
