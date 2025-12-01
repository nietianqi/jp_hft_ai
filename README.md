# Kabu HFT交易系统 - 修复版

## 🚨 重要修复

此版本包含以下关键修复:

### 1. ✅ Bid/Ask定义修复 (CRITICAL)
- **问题**: 原代码将Kabu的BidPrice/AskPrice理解反了
- **影响**: 会导致所有策略反向下单
- **修复**: 使用`kabu_data_converter_fixed.py`正确转换
  - Kabu Buy1 = 买方报价 (Bid)
  - Kabu Sell1 = 卖方报价 (Ask)

### 2. ✅ 订单流策略替换
- **问题**: 原策略依赖Kabu不提供的is_buy_taker字段
- **修复**: 使用`orderflow_alternative_strategy.py`
  - 改用MarketOrderBuyQty/SellQty推断市场压力
  - 结合盘口变化和价格动量

### 3. ✅ 信用交易参数修复
- **问题**: Side应为字符串,MarginTradeType不适合日内交易
- **修复**: `kabu_executor.py`
  - Side="2" (字符串格式)
  - MarginTradeType=2 (一般信用)
  - FundType="AA" (日计り)
  - ClosePositionOrder=0/1 (新建仓/平仓)

### 4. ✅ Import路径修复
- **问题**: 多处import路径错误
- **修复**: 统一为相对导入

### 5. ✅ Async/Await统一
- **问题**: DummyGateway方法定义与调用不一致
- **修复**: 统一为同步接口

### 6. ✅ 止损逻辑修复
- **问题**: 空头仓位pnl计算可能错误
- **修复**: 正确处理负数仓位

## ⚡ 快速开始

```bash
# 运行模拟测试
python main.py
```

## 📦 项目结构

```
jp_hft_fixed/
├── config/                  # 配置模块
├── engine/                  # 元策略管理器
├── strategy/hft/            # HFT策略
│   ├── market_making_strategy.py
│   ├── liquidity_taker_scalper.py
│   └── orderflow_alternative_strategy.py  # ✅新策略
├── execution/               # 订单执行
│   └── kabu_executor.py     # ✅已修复
├── utils/                   # 工具
│   └── kabu_data_converter_fixed.py  # ✅关键修复
├── integrated_trading_system.py  # ✅已修复
└── main.py                  # ✅已修复
```

## 🔧 配置参数

| 参数 | 数值 |
|------|------|
| 总仓位 | 400股 |
| 止盈 | 2 tick |
| 止损 | 100 tick |
| 日亏损限额 | 50万日元 |

### 策略权重
- 做市: 30%
- 流动性抢占: 40%
- 订单流: 30%

## 🚀 部署流程

### 阶段1: 模拟测试 (当前)
```bash
python main.py
```

### 阶段2: 接入真实API

1. 修改`config/system_config.py`:
```python
API_PASSWORD: str = "your_real_password"
```

2. 在`integrated_trading_system.py`中替换DummyGateway为真实executor

3. **必须从小仓位开始**:
```python
max_total_position = 100  # 先用100股测试
```

## ⚠️ 风险警告

### 必须检查项
- [ ] Bid/Ask转换正确
- [ ] 订单方向正确
- [ ] 信用交易参数正确
- [ ] 止损止盈触发正常
- [ ] 仓位控制有效

### 实盘前
1. **充分模拟测试** - 至少运行1周
2. **小仓位开始** - 从100股开始
3. **持续监控** - 前3天每小时检查
4. **做好止损准备** - 前期可能亏损

### 关键风险
- 高频交易可能快速亏损
- Kabu API可能不稳定
- 市场剧烈波动时可能失控
- 某些市场环境策略可能失效

## 📝 修复文件清单

| 文件 | 修复内容 |
|------|---------|
| `utils/kabu_data_converter_fixed.py` | Bid/Ask正确转换 |
| `execution/kabu_executor.py` | 信用交易参数修复 |
| `strategy/hft/orderflow_alternative_strategy.py` | 替代订单流策略 |
| `integrated_trading_system.py` | 使用修复后的组件 |
| `main.py` | 统一同步接口 |

## 🆘 紧急处理

### 异常大量下单
1. 立即在kabuステーション中撤销所有订单
2. 平掉所有持仓
3. 停止程序

### 无法平仓
- 手动在kabuステーション中平仓
- 不要依赖程序

## 📚 详细文档

见`/mnt/user-data/outputs/CODE_REVIEW_REPORT.md`获取:
- 完整错误分析
- 修复方案详解
- 部署指南
- 风险评估

## ⭐ 核心改进

1. **数据转换**: 使用`convert_kabu_board_to_standard()`确保正确映射
2. **订单执行**: kabu_executor正确处理信用交易参数
3. **策略替换**: orderflow_alternative不依赖不存在的字段
4. **统一接口**: 所有gateway调用统一为同步方法

## 📞 支持

所有技术细节在代码注释中。关键文件:
- `utils/kabu_data_converter_fixed.py` - Bid/Ask转换逻辑
- `execution/kabu_executor.py` - 订单参数示例
- `strategy/hft/orderflow_alternative_strategy.py` - 替代实现

---

**请务必先充分测试，再接入实盘！** 🚨
