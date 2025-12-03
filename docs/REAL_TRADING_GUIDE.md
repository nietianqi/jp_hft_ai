# 真实交易部署指南

## ⚠️ 重要警告

**这是真实交易系统，会使用真金白银！请务必谨慎操作！**

---

## 📋 部署前检查清单

### 1. Kabu Station配置

- [ ] ✅ Kabu Station已安装并启动
- [ ] ✅ API功能已启用（设定 > API设定 > API接続を有効化）
- [ ] ✅ API密码已设置并记录
- [ ] ✅ 确认API端口为18080（默认）

### 2. 系统配置检查

编辑 `config/system_config.py`：

```python
@dataclass
class SystemConfig:
    WS_URL: str = "ws://localhost:18080/kabusapi/websocket"
    REST_URL: str = "http://localhost:18080/kabusapi"
    API_PASSWORD: str = "your_actual_password"  # ⚠️ 修改为您的真实密码
    SYMBOLS: List[str] = None  # 默认["3697"]，可修改为其他股票代码
```

### 3. 策略配置检查

编辑 `config/strategy_config.py`：

#### 选择策略模式

```python
@dataclass
class StrategyConfig:
    mode: str = 'dual_engine'  # 'hft' 或 'dual_engine'
```

#### HFT策略配置（mode='hft'）

```python
@dataclass
class HFTConfig:
    total_capital: float = 15_000_000      # ⚠️ 总资金
    max_total_position: int = 400          # ⚠️ 最大仓位（股）
    daily_loss_limit: float = 500_000      # ⚠️ 日亏损限额
    take_profit_ticks: int = 2             # 止盈跳数
    stop_loss_ticks: int = 100             # 止损跳数
```

**建议初始配置（小仓位测试）：**

```python
max_total_position: int = 100              # 从100股开始
daily_loss_limit: float = 50_000           # 限制日亏损
```

#### 双引擎策略配置（mode='dual_engine'）

```python
@dataclass
class DualEngineConfig:
    core_pos: int = 1000                   # ⚠️ 核心仓位目标
    max_pos: int = 2000                    # ⚠️ 最大仓位
    grid_step_pct: float = 0.3             # 网格步长（%）
    grid_volume: int = 100                 # 每格交易量
    enable_dynamic_exit: bool = True       # 启用动态止盈
```

**建议初始配置（小仓位测试）：**

```python
core_pos: int = 100                        # 从100股开始
max_pos: int = 200                         # 最大200股
grid_volume: int = 100                     # 每格100股
```

---

## 🚀 启动流程

### 方式1: 模拟测试（推荐先测试）

```bash
# 使用随机数据测试策略逻辑
python main.py
```

**用途：**
- 验证策略逻辑
- 测试持仓控制
- 观察信号生成
- **不会连接真实API**

---

### 方式2: 真实交易

```bash
# 连接Kabu API进行真实交易
python main_kabu.py
```

**启动时会提示：**

```
⚠️  Kabu 真实交易系统 - 请谨慎操作！
================================================================================

模式: 双引擎网格策略
标的: ['3697']
配置:
  核心仓位: 1000 股
  最大仓位: 2000 股
  网格步长: 0.3%
  动态止盈: 启用

Kabu API:
  REST地址: http://localhost:18080/kabusapi
  WebSocket地址: ws://localhost:18080/kabusapi/websocket
================================================================================

⚠️  这是真实交易，会使用真金白银！
请确认您已:
  1. ✓ Kabu Station已启动
  2. ✓ 理解策略逻辑和风险
  3. ✓ 检查过所有配置参数
  4. ✓ 准备好承担可能的损失

输入 'YES' 继续，其他任意键取消:
```

**必须输入 `YES`（全大写）才能启动！**

---

## 📊 运行监控

### 实时日志

系统会同时输出到：
1. **终端** - 实时查看交易信号
2. **日志文件** - `kabu_trading_YYYYMMDD_HHMMSS.log`

### 日志示例

```
2025-12-03 14:30:15 [INFO] __main__: [core] BUY 1000股 @ 1500.00 (持仓=1000) ✓
2025-12-03 14:35:22 [INFO] __main__: [exit] SELL 1000股 @ 1505.50 (持仓=0, 盈亏=5500) ✓
2025-12-03 14:40:10 [INFO] __main__: [grid_buy] BUY 100股 @ 1498.00 (持仓=100) ✓
```

### 状态输出

每100个tick自动打印一次：

```
============================================================
Tick数: 100  |  时间: 14:30:45
============================================================

双引擎策略状态:
  持仓: 1200 股
  成本价: 1502.34
  累计盈亏: 2340 JPY
  趋势状态: 震荡上行✓
  网格中心: 1505.20
  网格层数: 3
```

---

## 🛑 紧急停止

### 正常停止

按 `Ctrl+C`，系统会安全退出并打印最终状态。

### 强制停止

1. **终止程序**：再次按 `Ctrl+C`
2. **登录Kabu Station**：手动撤单和平仓
3. **检查持仓**：确认所有仓位已清空

---

## ⚙️ 配置文件位置

| 配置项 | 文件路径 | 说明 |
|--------|---------|------|
| 策略模式 | `config/strategy_config.py` | mode='hft' 或 'dual_engine' |
| HFT参数 | `config/strategy_config.py` | HFTConfig类 |
| 双引擎参数 | `config/strategy_config.py` | DualEngineConfig类 |
| Kabu API | `config/system_config.py` | API密码、地址、标的 |

---

## 🎯 两种策略模式对比

### HFT 高频交易策略

**适用场景：**
- 日内高频剥头皮
- 快速进出
- 波动较小的市场

**特点：**
- 三策略并行（做市、流动性抢占、订单流）
- 快速止盈（2 ticks）
- 快速止损（100 ticks）
- 高频交易

**配置：** `mode: str = 'hft'`

---

### 双引擎网格策略

**适用场景：**
- 震荡上行市场
- 趋势性行情
- 中长期持仓

**特点：**
- 趋势引擎 + 网格引擎
- 核心仓位持有
- 动态止盈（让利润奔跑）
- 手续费过滤

**配置：** `mode: str = 'dual_engine'`

---

## 📈 风险控制建议

### 初次部署（第1天）

```python
# 双引擎模式
core_pos: int = 100           # 最小仓位
max_pos: int = 200
grid_volume: int = 100

# 或 HFT模式
max_total_position: int = 100
daily_loss_limit: float = 10_000  # 严格止损
```

**操作：**
- ✅ 持续监控2-4小时
- ✅ 观察信号准确性
- ✅ 验证止盈止损
- ✅ 记录所有异常

---

### 稳定运行后（第2-7天）

```python
# 逐步提高仓位
core_pos: int = 500
max_pos: int = 1000
daily_loss_limit: float = 50_000
```

**操作：**
- ✅ 每天检查盈亏
- ✅ 调整参数优化
- ✅ 监控异常交易

---

### 正式运行（1周后）

```python
# 使用正常配置
core_pos: int = 1000
max_pos: int = 2000
daily_loss_limit: float = 100_000
```

---

## ⚠️ 常见问题

### 1. 连接失败

**错误：** `✗ 无法连接到API服务器`

**解决：**
1. 检查Kabu Station是否启动
2. 确认API功能已启用
3. 检查端口18080是否被占用
4. 验证API密码是否正确

---

### 2. 订单失败

**错误：** `[core] BUY 100股 @ 1500.00 失败`

**解决：**
1. 检查账户余额是否充足
2. 确认股票代码正确
3. 检查是否在交易时间
4. 查看Kabu Station订单记录

---

### 3. 持仓失控

**现象：** 持仓远超max_pos配置

**解决：**
1. 立即停止程序（Ctrl+C）
2. 登录Kabu Station手动平仓
3. 检查日志找出原因
4. 降低仓位重新测试

---

## 📞 支持

如遇到问题：
1. 查看日志文件 `kabu_trading_*.log`
2. 检查配置文件是否正确
3. 参考文档：`docs/STRATEGY_GUIDE.md`
4. GitHub Issues: https://github.com/nietianqi/jp_hft_ai/issues

---

## 🔒 安全建议

1. **✅ 不要**在未充分测试前使用大仓位
2. **✅ 不要**在波动剧烈时启动系统
3. **✅ 不要**修改核心代码后立即实盘
4. **✅ 务必**先用模拟测试验证逻辑
5. **✅ 务必**设置合理的止损限额
6. **✅ 务必**定期检查日志和持仓

---

**文档版本:** v1.0
**更新时间:** 2025-12-03
**相关文件:** `main_kabu.py`, `config/system_config.py`, `config/strategy_config.py`
