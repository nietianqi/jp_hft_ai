# 策略使用指南

## 概述

本系统支持两种交易策略模式:

1. **HFT 高频交易策略组** - 适合高频剥头皮交易
2. **双引擎网格策略** - 适合震荡上行市场的趋势+网格复合策略

---

## 一、策略模式对比

### 1. HFT 高频交易策略组

**特点:**
- ✅ 三策略协同：做市、流动性抢占、订单流
- ✅ 元策略管理器动态权重分配
- ✅ tick级高频交易
- ✅ 微利快进快出
- ✅ 适合波动频繁的市场

**适用场景:**
- 日内高频交易
- 市场波动较大
- 流动性充足
- 有稳定的盘口数据

**核心参数:**
```python
total_capital: 15,000,000      # 总资金
max_total_position: 400        # 最大仓位
take_profit_ticks: 2           # 止盈2跳
stop_loss_ticks: 100           # 止损100跳
strategy_weights:              # 策略权重
    market_making: 0.3         # 做市 30%
    liquidity_taker: 0.4       # 流动性 40%
    orderflow_queue: 0.3       # 订单流 30%
```

---

### 2. 双引擎网格策略

**特点:**
- ✅ 趋势判断：EMA20/EMA60 双均线系统
- ✅ 核心仓：趋势成立时持有核心仓位
- ✅ 微网格：在趋势成立时维护网格
- ✅ 成本价跟踪：只在盈利时卖出
- ✅ 动态止盈：方向反转才平仓，让利润奔跑

**适用场景:**
- 震荡上行市场
- 趋势性行情
- 适合中长线持仓
- 降低交易频率，减少手续费

**核心参数:**
```python
ema_fast_window: 20            # 快速EMA周期
ema_slow_window: 60            # 慢速EMA周期
core_pos: 1000                 # 核心仓位目标
max_pos: 2000                  # 最大仓位
grid_levels: 3                 # 网格层数
grid_step_pct: 0.3             # 网格步长 0.3%
grid_volume: 100               # 每格交易量
enable_dynamic_exit: True      # 启用动态止盈
```

---

## 二、策略切换方法

### 方法1: 修改配置文件（推荐）

编辑 `config/strategy_config.py`:

```python
from dataclasses import dataclass, field
from config.strategy_config import HFTConfig, DualEngineConfig

@dataclass
class StrategyConfig:
    # ✅ 修改这里切换策略
    mode: str = 'hft'  # 'hft' 或 'dual_engine'

    hft: HFTConfig = field(default_factory=HFTConfig)
    dual_engine: DualEngineConfig = field(default_factory=DualEngineConfig)
```

**切换到双引擎策略:**
```python
mode: str = 'dual_engine'
```

**切换到HFT高频策略:**
```python
mode: str = 'hft'
```

---

### 方法2: 命令行参数（开发中）

```bash
# 使用HFT策略
python main.py --strategy=hft

# 使用双引擎策略
python main.py --strategy=dual_engine
```

---

### 方法3: 环境变量

```bash
# Linux/Mac
export STRATEGY_MODE=dual_engine
python main.py

# Windows
set STRATEGY_MODE=dual_engine
python main.py
```

---

## 三、双引擎策略详解

### 3.1 核心逻辑

```
┌─────────────────────────────────────────┐
│         双引擎交易策略架构              │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────────────────────┐   │
│  │   趋势引擎（CoreTrend）         │   │
│  │   - EMA20/EMA60判断趋势        │   │
│  │   - 趋势成立 → 持有核心仓       │   │
│  │   - 趋势失效 → 撤单不平仓       │   │
│  └─────────────────────────────────┘   │
│              ↓                          │
│       趋势成立?                         │
│              ↓ Yes                      │
│  ┌─────────────────────────────────┐   │
│  │   网格引擎（MicroGrid）         │   │
│  │   - 下方挂买单（补仓）          │   │
│  │   - 上方挂卖单（只盈利卖）      │   │
│  │   - 价格爬坡 → 重建网格         │   │
│  └─────────────────────────────────┘   │
│              ↓                          │
│  ┌─────────────────────────────────┐   │
│  │   止盈引擎（Exit）              │   │
│  │   - 动态止盈：方向反转平仓      │   │
│  │   - 移动止盈：回撤触发          │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

---

### 3.2 趋势判定规则

**震荡上行条件（需同时满足）:**

| 指标 | 条件 | 权重 |
|------|------|------|
| EMA多头排列 | EMA20 > EMA60 且 价格 > EMA60 | 30分 |
| 价格未爆拉 | \|价格 - EMA60\| / EMA60 < 3% | 20分 |
| 波动率适中 | ATR% 在 0.3% ~ 2% 区间 | 20分 |
| RSI健康 | RSI 在 40-70 区间 | 10分 |

**判定阈值:** 总分 >= 40分 → 趋势成立

---

### 3.3 成本价跟踪系统

**买入时:**
```python
总买入金额 += 成交价 × 成交量
总买入数量 += 成交量
平均成本价 = 总买入金额 / 总买入数量
```

**卖出时:**
```python
总买入金额 -= 平均成本价 × 卖出量
总买入数量 -= 卖出量
平均成本价 = 总买入金额 / 总买入数量  # 重新计算
```

**最低卖价计算:**
```python
手续费成本 = (单边手续费 × 2) × 利润倍数 / 每格数量
最低卖价 = 平均成本价 + 手续费成本
```

---

### 3.4 动态止盈机制

**核心理念:** 有盈利方向对不平仓，有盈利方向反转才平仓

```python
# 伪代码逻辑
if 盈利 >= 阈值:
    if 价格从最高点回撤 >= 反转阈值:
        平仓止盈  # 方向反转
    else:
        继续持有  # 让利润奔跑
else:
    等待反转  # 亏损不止损
```

**参数说明:**
- `dynamic_profit_threshold_ticks`: 0.5跳（盈利阈值）
- `dynamic_reversal_ticks`: 0.3跳（反转阈值）

**示例:**
```
成本价: 1500
当前价: 1502 → 盈利 20跳 ✓
最高价: 1502
当前价: 1501.7 → 回撤 3跳 ✓
触发动态止盈 → 平仓
```

---

### 3.5 网格运行逻辑

**初始化网格:**
```python
网格中心 = 当前价格
网格步长 = 中心价 × 步长百分比
每层买价 = 中心 × (1 - 步长% × 层数)
每层卖价 = 中心 × (1 + 步长% × 层数)
```

**爬坡重建:**
```python
if abs(当前价 - 网格中心) / 网格中心 >= 2 × 步长:
    撤销所有网格单
    网格中心 = 当前价
    重建网格
```

**示例（3层网格，步长0.3%）:**
```
中心价: 1500

买单层级:
L1: 1500 × (1 - 0.3%) = 1495.5  ← 买入100股
L2: 1500 × (1 - 0.6%) = 1491.0  ← 买入100股
L3: 1500 × (1 - 0.9%) = 1486.5  ← 买入100股

卖单层级:
L1: 1500 × (1 + 0.3%) = 1504.5  ← 卖出100股（需>最低卖价）
L2: 1500 × (1 + 0.6%) = 1509.0  ← 卖出100股
L3: 1500 × (1 + 0.9%) = 1513.5  ← 卖出100股
```

---

## 四、参数调优建议

### 4.1 HFT策略调优

| 参数 | 激进配置 | 稳健配置 | 说明 |
|------|----------|----------|------|
| take_profit_ticks | 1-2 | 3-5 | 止盈越小越激进 |
| stop_loss_ticks | 50 | 100-200 | 止损越大容错越高 |
| max_total_position | 600 | 300-400 | 仓位越大风险越高 |

---

### 4.2 双引擎策略调优

| 参数 | 激进配置 | 稳健配置 | 说明 |
|------|----------|----------|------|
| grid_step_pct | 0.2% | 0.5% | 步长越小交易越频繁 |
| grid_levels | 5 | 2-3 | 层数越多资金占用越大 |
| core_pos | 1500 | 500-1000 | 核心仓越大趋势收益越高 |
| dynamic_reversal_ticks | 0.2 | 0.5 | 反转阈值越小止盈越灵敏 |

---

## 五、风险提示

### 5.1 HFT策略风险

⚠️ **高频交易风险:**
- 手续费累积（建议月度统计）
- 滑点风险（流动性不足时）
- 网络延迟（需要低延迟网络）

### 5.2 双引擎策略风险

⚠️ **趋势判断风险:**
- 假突破风险（EMA金叉后快速死叉）
- 震荡市陷阱（频繁趋势切换）
- 单边下跌风险（只做多策略）

⚠️ **网格风险:**
- 资金占用（多层网格同时成交）
- 爬坡被套（快速上涨后回落）

---

## 六、监控指标

### 关键指标监控

```python
# HFT策略
- 日内交易次数
- 胜率
- 平均持仓时间
- 手续费占比

# 双引擎策略
- 趋势判定准确率
- 平均成本价
- 网格利用率
- 最大回撤
```

---

## 七、使用示例

### 示例1: 启动HFT策略

```python
# config/strategy_config.py
@dataclass
class StrategyConfig:
    mode: str = 'hft'
    hft: HFTConfig = field(default_factory=lambda: HFTConfig(
        max_total_position=400,
        take_profit_ticks=2,
        stop_loss_ticks=100,
    ))
```

### 示例2: 启动双引擎策略（震荡上行）

```python
# config/strategy_config.py
@dataclass
class StrategyConfig:
    mode: str = 'dual_engine'
    dual_engine: DualEngineConfig = field(default_factory=lambda: DualEngineConfig(
        core_pos=1000,
        grid_levels=3,
        grid_step_pct=0.3,
        enable_dynamic_exit=True,
    ))
```

### 示例3: 双引擎激进配置

```python
# 适合强趋势市场
dual_engine: DualEngineConfig = field(default_factory=lambda: DualEngineConfig(
    ema_fast_window=10,          # 加快EMA响应
    ema_slow_window=30,
    core_pos=1500,               # 增加核心仓
    grid_levels=5,               # 增加网格层数
    grid_step_pct=0.2,           # 缩小步长
    dynamic_reversal_ticks=0.2,  # 更灵敏止盈
))
```

---

## 八、常见问题

**Q1: 如何在两种策略间切换？**
A: 修改 `config/strategy_config.py` 中的 `mode` 字段，然后重启程序。

**Q2: 双引擎策略为什么趋势失效不平仓？**
A: 采用"只盈利平仓"理念，趋势失效时撤单但保留仓位，等待价格反弹，避免在成本价以下止损。

**Q3: 动态止盈和移动止盈有什么区别？**
A:
- **动态止盈**: 方向对不平仓，方向反转才平仓（让利润奔跑）
- **移动止盈**: 达到激活阈值后，从最高点回撤触发止盈

**Q4: 手续费过滤是如何工作的？**
A: 计算每格交易的毛利润，如果小于 `往返手续费 × 利润倍数`，则跳过该网格挂单。

**Q5: 如何监控策略运行状态？**
A: 查看日志文件 `log/cta_strategies/` 或实时监控控制台输出。

---

## 九、下一步优化方向

- [ ] 添加策略热切换（无需重启）
- [ ] Web界面实时监控
- [ ] 策略回测模块
- [ ] 参数自动优化
- [ ] 多标的支持

---

**文档版本:** v1.0
**更新时间:** 2025-12-03
**维护者:** Claude Code
