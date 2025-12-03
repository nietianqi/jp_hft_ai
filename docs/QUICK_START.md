# 快速开始 - 策略切换指南

## 一、5分钟快速切换

### 场景1: 我想用高频策略做日内交易

**步骤:**

1. 打开 `config/strategy_config.py`

2. 确认配置:
```python
@dataclass
class StrategyConfig:
    mode: str = 'hft'  # ✅ 确保是 'hft'
```

3. 重启程序
```bash
python main.py
```

4. 观察日志
```
[HFT] 做市策略已启动
[HFT] 流动性抢占策略已启动
[HFT] 订单流策略已启动
```

---

### 场景2: 我想用双引擎策略做趋势交易

**步骤:**

1. 打开 `config/strategy_config.py`

2. 修改配置:
```python
@dataclass
class StrategyConfig:
    mode: str = 'dual_engine'  # ✅ 改为 'dual_engine'
```

3. 重启程序
```bash
python main.py
```

4. 观察日志
```
[DualEngine] 趋势引擎已启动
[DualEngine] 网格引擎已启动
[DualEngine][Trend] 震荡上行判定: score=65.0, trend_up=True
```

---

## 二、参数快速调优

### HFT策略（高频模式）

**保守配置（推荐新手）:**
```python
hft: HFTConfig = field(default_factory=lambda: HFTConfig(
    max_total_position=300,       # 最大仓位300股
    take_profit_ticks=3,          # 止盈3跳
    stop_loss_ticks=100,          # 止损100跳
    strategy_weights={
        'market_making': 0.4,     # 做市占40%（更稳健）
        'liquidity_taker': 0.3,
        'orderflow_queue': 0.3,
    }
))
```

**激进配置（适合高手）:**
```python
hft: HFTConfig = field(default_factory=lambda: HFTConfig(
    max_total_position=600,       # 最大仓位600股
    take_profit_ticks=2,          # 止盈2跳（快进快出）
    stop_loss_ticks=50,           # 止损50跳（快速止损）
    strategy_weights={
        'market_making': 0.2,
        'liquidity_taker': 0.5,   # 流动性抢占占50%（更激进）
        'orderflow_queue': 0.3,
    }
))
```

---

### 双引擎策略（趋势+网格模式）

**标准配置（震荡上行）:**
```python
dual_engine: DualEngineConfig = field(default_factory=lambda: DualEngineConfig(
    core_pos=1000,                # 核心仓1000股
    max_pos=2000,                 # 最大2000股
    grid_levels=3,                # 3层网格
    grid_step_pct=0.3,            # 步长0.3%
    enable_dynamic_exit=True,     # 启用动态止盈
))
```

**趋势强劲配置:**
```python
dual_engine: DualEngineConfig = field(default_factory=lambda: DualEngineConfig(
    ema_fast_window=10,           # 快速EMA 10周期（更敏感）
    ema_slow_window=30,           # 慢速EMA 30周期
    core_pos=1500,                # 增加核心仓
    max_pos=3000,
    grid_levels=5,                # 5层网格（更密集）
    grid_step_pct=0.2,            # 步长0.2%（更小）
    dynamic_reversal_ticks=0.2,   # 更灵敏止盈
))
```

**保守配置（震荡市）:**
```python
dual_engine: DualEngineConfig = field(default_factory=lambda: DualEngineConfig(
    core_pos=500,                 # 减少核心仓
    max_pos=1000,
    grid_levels=2,                # 只2层网格
    grid_step_pct=0.5,            # 步长0.5%（更大）
    enable_dynamic_exit=False,    # 关闭动态止盈，用移动止盈
    enable_trailing_stop=True,
    trailing_distance_ticks=3,
))
```

---

## 三、关键功能开关

### 动态止盈 vs 移动止盈

**动态止盈（让利润奔跑）:**
```python
enable_dynamic_exit=True          # ✅ 启用
dynamic_profit_threshold_ticks=0.5
dynamic_reversal_ticks=0.3

# 特点：
# ✓ 方向对不平仓
# ✓ 方向反转才平仓
# ✓ 适合趋势行情
```

**移动止盈（保护利润）:**
```python
enable_dynamic_exit=False         # ❌ 关闭动态止盈
enable_trailing_stop=True         # ✅ 启用移动止盈
trailing_activation_ticks=3       # 盈利3跳激活
trailing_distance_ticks=2         # 回撤2跳触发

# 特点：
# ✓ 达到阈值后跟踪最高价
# ✓ 回撤触发止盈
# ✓ 适合震荡行情
```

---

### 手续费过滤

**启用手续费过滤（推荐）:**
```python
auto_adjust_step=True             # ✅ 自动调整步长
min_profit_multiple=2.0           # 利润 >= 手续费 × 2

# 效果：
# ✓ 自动跳过无利润网格
# ✓ 步长不足时自动放大
# ✓ 避免"赚了价差亏了手续费"
```

**关闭手续费过滤:**
```python
auto_adjust_step=False            # ❌ 不调整
min_profit_multiple=1.0

# 注意：
# ⚠️ 可能频繁交易但不盈利
# ⚠️ 适合手续费极低的环境
```

---

## 四、常见配置组合

### 组合1: 日内高频剥头皮

```python
mode: str = 'hft'
hft: HFTConfig(
    max_total_position=400,
    take_profit_ticks=2,           # 快速止盈
    stop_loss_ticks=100,
    time_stop_seconds=5,           # 5秒未成交撤单
)
```

**预期:**
- 日内交易次数: 100-500次
- 单笔盈利: 2-5跳
- 胜率: 60-70%

---

### 组合2: 震荡上行趋势网格

```python
mode: str = 'dual_engine'
dual_engine: DualEngineConfig(
    core_pos=1000,
    grid_levels=3,
    grid_step_pct=0.3,
    enable_dynamic_exit=True,      # 动态止盈
)
```

**预期:**
- 日内交易次数: 10-50次
- 持仓周期: 数分钟到数小时
- 核心仓收益 + 网格收益双重来源

---

### 组合3: 强趋势追涨

```python
mode: str = 'dual_engine'
dual_engine: DualEngineConfig(
    ema_fast_window=10,            # 快速响应
    core_pos=1500,                 # 大核心仓
    grid_levels=5,                 # 密集网格
    grid_step_pct=0.2,
    dynamic_reversal_ticks=0.15,   # 极敏感止盈
)
```

**预期:**
- 趋势启动快速建仓
- 网格密集吃波动
- 反转快速止盈

---

## 五、监控与调试

### 日志关键字

**HFT策略:**
```
[META] 允许执行              ← 策略信号通过
[MM] 做市报价                ← 做市策略挂单
[LT] 流动性抢占做多          ← 流动性策略开仓
[OFA] 订单流做多             ← 订单流策略开仓
```

**双引擎策略:**
```
[DualEngine][Trend] 震荡上行判定  ← 趋势判断
[DualEngine][Core] 核心补仓信号   ← 核心仓调整
[DualEngine][Grid] 初始化网格     ← 网格建立
[DualEngine][Exit] 动态止盈触发   ← 止盈执行
```

---

### 性能指标

```python
# 查看策略状态（示例代码）
status = strategy.get_strategy_status(symbol)

# 关键指标
status['position']          # 当前仓位
status['avg_cost_price']    # 平均成本价
status['trend_up']          # 趋势方向
status['grid_center']       # 网格中心
```

---

## 六、故障排查

### 问题1: 切换策略后没反应

**解决:**
```bash
# 1. 检查配置文件
cat config/strategy_config.py | grep "mode"

# 2. 确认已重启
ps aux | grep python  # 查看进程
kill -9 <PID>         # 杀掉旧进程
python main.py        # 重新启动

# 3. 查看日志
tail -f log/main.log
```

---

### 问题2: 双引擎策略不生成信号

**检查项:**
```
✓ 数据是否充足？至少需要60根K线（ema_slow_window=60）
✓ 趋势是否成立？查看日志 [Trend] trend_up=True
✓ 仓位是否已满？position >= max_pos
✓ 是否在冷却期？last_trade_ts 间隔 < 5秒
```

---

### 问题3: HFT策略交易频率过低

**调整:**
```python
# 降低阈值
depth_imbalance_thresh_long=0.3  # 原0.4，降低买入门槛
momentum_min_ticks=1             # 原2，降低动量要求

# 增加仓位
max_total_position=600           # 原400
```

---

## 七、下一步

- 📖 阅读完整文档: [STRATEGY_GUIDE.md](./STRATEGY_GUIDE.md)
- 🔧 参数调优: 根据实盘数据优化参数
- 📊 回测验证: 使用历史数据测试策略
- 🚀 实盘监控: 密切关注首日表现

---

**提示:** 新策略上线建议从小仓位开始测试，逐步加仓！

**支持:** 如有问题请查看 `log/` 目录下的日志文件
