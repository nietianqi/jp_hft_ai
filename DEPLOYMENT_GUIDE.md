# 部署指南

**仓库**: https://github.com/nietianqi/jp_hft_ai
**分支**: silly-curie
**最新提交**: a5326ab - 修复仓位控制逻辑并完善项目文档

---

## ✅ 已完成的工作

### 核心修复 (3个关键bug)

1. **仓位管理修复** ⭐⭐⭐
   - 文件: `engine/meta_strategy_manager.py:116-166`
   - 问题: 仓位检查逻辑有缺陷，超限后无法减仓
   - 修复: 使用绝对值判断，允许减仓操作
   - 测试: 11个单元测试全部通过

2. **订单执行修复**
   - 文件: `execution/kabu_executor.py:172-194`
   - 问题: 缺少同步send_order方法
   - 修复: 添加线程池async/sync转换
   - 验证: 真实API对接成功

3. **字段映射修复**
   - 文件: `strategy/hft/orderflow_alternative_strategy.py:189`
   - 问题: on_fill中size/quantity字段不一致
   - 修复: 兼容两种字段名

### 新增功能

1. **测试框架** (`tests/`)
   - `test_meta_manager.py`: 11个测试用例
   - 覆盖: 仓位限制、超限减仓、平仓逻辑
   - 结果: ✅ 全部通过

2. **真实环境支持**
   - `run_live.py`: kabuSTATION对接脚本
   - 安全限制: 100股/5万日元
   - `config/system_config.example.py`: API配置模板

3. **完整文档** (6个MD文件)
   - `QUICK_REFERENCE.md`: 快速上手指南 ⭐
   - `PROJECT_ANALYSIS.md`: 项目深度分析
   - `POSITION_CONTROL_FIX.md`: 修复详解
   - `CODE_REVIEW_AND_FIXES.md`: 代码审查
   - `FINAL_SUMMARY.md`: 全面总结
   - `LATEST_FIXES.md`: 修复记录

---

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/nietianqi/jp_hft_ai.git
cd jp_hft_ai
git checkout silly-curie
```

### 2. 模拟测试

```bash
python main.py
python tests/test_meta_manager.py
```

### 3. 真实环境

```bash
# 配置API密码
cp config/system_config.example.py config/system_config.py
# 编辑填写API密码后运行
python run_live.py
```

---

## 📊 代码统计

- 13个文件修改/新增
- +2510 行代码/文档
- 11个单元测试通过

---

**完整文档**: 查看 QUICK_REFERENCE.md

**GitHub**: https://github.com/nietianqi/jp_hft_ai/tree/silly-curie
