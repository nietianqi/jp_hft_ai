# -*- coding: utf-8 -*-
"""
dual_engine_strategy.py

双引擎微网格策略（优化版 - 只做多，只盈利平仓）
参考 VeighNa DualEngineGridStrategyOptimized 的核心逻辑
"""

from __future__ import annotations

import time
import math
from dataclasses import dataclass
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple
import logging

from models.market_data import MarketTick
from models.trading_models import TradingSignal
from strategy.base import TradingStrategy

logger = logging.getLogger(__name__)


@dataclass
class DualEngineConfig:
    """双引擎策略配置"""
    # EMA参数
    ema_fast_window: int = 20
    ema_slow_window: int = 60

    # 核心仓位参数
    core_pos: int = 1000
    max_pos: int = 2000

    # 网格参数
    grid_levels: int = 3
    grid_step_pct: float = 0.3
    grid_volume: int = 100
    active_grid_levels: int = 0  # 0=使用grid_levels

    # 手续费参数
    fee_per_side: float = 80.0
    min_profit_multiple: float = 2.0
    auto_adjust_step: bool = True

    # 止盈参数
    profit_take_pct: float = 0.5
    enable_trailing_stop: bool = True
    trailing_activation_ticks: int = 3
    trailing_distance_ticks: int = 2

    # 动态止盈参数
    enable_dynamic_exit: bool = True
    dynamic_profit_threshold_ticks: float = 0.5
    dynamic_reversal_ticks: float = 0.3

    # 价格参数
    pricetick: float = 0.01


@dataclass
class SymbolState:
    """单只股票的状态"""
    # 价格序列
    prices: Deque[float]
    highs: Deque[float]
    lows: Deque[float]
    volumes: Deque[int]
    timestamps: Deque[float]

    # 技术指标
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    atr: float = 0.0
    rsi: float = 50.0

    # 趋势判定
    trend_up: bool = False
    osc_up_score: float = 0.0

    # 网格状态
    grid_center: float = 0.0
    last_price: float = 0.0

    # 仓位与成本
    position: int = 0
    avg_cost_price: float = 0.0
    total_buy_amount: float = 0.0
    total_buy_volume: int = 0

    # 止盈跟踪
    best_profit_price: Optional[float] = None
    trailing_active: bool = False

    # 时间控制
    last_update_ts: float = 0.0
    last_trade_ts: float = 0.0


class DualEngineTradingStrategy(TradingStrategy):
    """
    双引擎交易策略：趋势核心仓 + 微网格

    核心逻辑：
    1. 趋势引擎：通过 EMA20/EMA60 + 收盘价判断"震荡上行"
       - 趋势成立：保持核心仓 core_pos
       - 趋势失效：只撤单，不平仓（等待反弹）

    2. 网格引擎：在趋势成立时维护微网格
       - 下方挂买单（不突破 max_pos）
       - 上方挂卖单（必须 >= 成本价 + 手续费 + 最小利润）

    3. 成本价跟踪：
       - 记录平均持仓成本
       - 卖单只在盈利时执行

    4. 动态止盈：
       - 有盈利时，方向反转才平仓
       - 方向对时，继续持有
       - 亏损时不止损，等待反转
    """

    def __init__(self, config: DualEngineConfig):
        super().__init__()
        self.cfg = config

        # 每个 symbol 的状态
        self.symbol_states: Dict[str, SymbolState] = {}

        # 性能统计
        self.total_updates: int = 0
        self.total_signals: int = 0

        # 指标窗口长度
        self.price_window = max(200, self.cfg.ema_slow_window * 3)
        self.rsi_period = 14

    # ----------------------------------------------------------------------
    # 对外接口
    # ----------------------------------------------------------------------
    def register_symbol(self, symbol: str) -> None:
        """初始化某只股票的状态"""
        if symbol in self.symbol_states:
            return

        self.symbol_states[symbol] = SymbolState(
            prices=deque(maxlen=self.price_window),
            highs=deque(maxlen=self.price_window),
            lows=deque(maxlen=self.price_window),
            volumes=deque(maxlen=self.price_window),
            timestamps=deque(maxlen=self.price_window),
        )

    def update_indicators(self, tick: MarketTick) -> None:
        """更新技术指标"""
        symbol = tick.symbol
        if symbol not in self.symbol_states:
            self.register_symbol(symbol)

        st = self.symbol_states[symbol]
        now = time.time()

        # 更新原始数据
        st.prices.append(tick.last_price)
        st.highs.append(tick.last_price)
        st.lows.append(tick.last_price)
        st.volumes.append(tick.volume)
        st.timestamps.append(now)
        st.last_update_ts = now
        st.last_price = tick.last_price

        self.total_updates += 1

        # 数据不足时跳过指标计算
        if len(st.prices) < max(self.cfg.ema_slow_window, self.rsi_period) + 2:
            return

        prices_list = list(st.prices)
        highs_list = list(st.highs)
        lows_list = list(st.lows)

        # 计算技术指标
        st.ema_fast = self._calc_ema(prices_list, period=self.cfg.ema_fast_window)
        st.ema_slow = self._calc_ema(prices_list, period=self.cfg.ema_slow_window)
        st.atr = self._calc_atr(highs_list, lows_list)
        st.rsi = self._calc_rsi(prices_list, period=self.rsi_period)

        # 趋势判定
        st.trend_up, st.osc_up_score = self._detect_trend_up(tick, st)

    def generate_signal(self, tick: MarketTick) -> Optional[TradingSignal]:
        """
        生成交易信号

        双引擎逻辑：
        1. 趋势引擎：判断是否应持有核心仓
        2. 网格引擎：在趋势成立时生成网格买卖信号
        """
        symbol = tick.symbol
        if symbol not in self.symbol_states:
            return None

        st = self.symbol_states[symbol]

        # 数据不足
        if len(st.prices) < max(self.cfg.ema_slow_window, self.rsi_period) + 2:
            return None

        # 检查止盈条件
        exit_signal = self._check_exit_conditions(tick, st)
        if exit_signal:
            return exit_signal

        # 趋势失效：不生成新信号
        if not st.trend_up:
            return None

        # 核心仓引擎：检查是否需要补仓到核心仓位
        core_signal = self._check_core_position(tick, st)
        if core_signal:
            return core_signal

        # 网格引擎：生成网格信号
        grid_signal = self._check_grid_signal(tick, st)
        if grid_signal:
            return grid_signal

        return None

    def on_fill(
        self,
        symbol: str,
        side: str,
        price: float,
        volume: int,
        trade_time: Optional[float] = None
    ) -> None:
        """
        成交回调：更新仓位和成本价

        Args:
            symbol: 股票代码
            side: "BUY" 或 "SELL"
            price: 成交价
            volume: 成交数量
            trade_time: 成交时间（时间戳）
        """
        if symbol not in self.symbol_states:
            return

        st = self.symbol_states[symbol]

        # 更新成本价
        if side.upper() == "BUY":
            self._update_cost_on_buy(st, price, volume)
        elif side.upper() == "SELL":
            self._update_cost_on_sell(st, price, volume)

        # 更新成交时间
        if trade_time:
            st.last_trade_ts = trade_time
        else:
            st.last_trade_ts = time.time()

    # ----------------------------------------------------------------------
    # 成本价跟踪系统
    # ----------------------------------------------------------------------
    def _update_cost_on_buy(self, st: SymbolState, price: float, volume: int) -> None:
        """买入时更新成本价"""
        st.total_buy_amount += price * volume
        st.total_buy_volume += volume
        st.position += volume

        if st.total_buy_volume > 0:
            st.avg_cost_price = st.total_buy_amount / st.total_buy_volume
        else:
            st.avg_cost_price = 0.0

        # 重置止盈跟踪
        st.best_profit_price = None
        st.trailing_active = False

        logger.info(
            f"[DualEngine] 买入成交更新成本：price={price:.2f}, vol={volume}, "
            f"新成本价={st.avg_cost_price:.2f}, 总持仓={st.position}"
        )

    def _update_cost_on_sell(self, st: SymbolState, price: float, volume: int) -> None:
        """卖出时更新成本价"""
        if st.total_buy_volume <= 0 or st.avg_cost_price <= 0:
            logger.warning(
                f"[DualEngine] 卖出时成本异常：avg_cost={st.avg_cost_price}, "
                f"total_vol={st.total_buy_volume}"
            )
            return

        # 按成本价减少金额
        st.total_buy_amount -= st.avg_cost_price * volume
        st.total_buy_volume -= volume
        st.position -= volume

        # 防止负数
        st.total_buy_amount = max(st.total_buy_amount, 0.0)
        st.total_buy_volume = max(st.total_buy_volume, 0)
        st.position = max(st.position, 0)

        # 重新计算成本价
        if st.total_buy_volume > 0:
            st.avg_cost_price = st.total_buy_amount / st.total_buy_volume
        else:
            st.avg_cost_price = 0.0
            st.total_buy_amount = 0.0

        profit = (price - st.avg_cost_price) * volume if st.avg_cost_price > 0 else 0.0

        logger.info(
            f"[DualEngine] 卖出成交更新成本：price={price:.2f}, vol={volume}, "
            f"新成本价={st.avg_cost_price:.2f}, 剩余持仓={st.position}, 本次盈亏={profit:.2f}"
        )

        # 平仓后重置止盈跟踪
        if st.position == 0:
            st.best_profit_price = None
            st.trailing_active = False

    def _calculate_min_sell_price(self, st: SymbolState) -> float:
        """计算最低卖出价 = 成本价 + 手续费覆盖 + 最小利润"""
        if st.avg_cost_price <= 0 or self.cfg.grid_volume <= 0:
            return 0.0

        roundtrip_fee = self.cfg.fee_per_side * 2.0
        fee_cost_per_share = (
            roundtrip_fee * self.cfg.min_profit_multiple
        ) / self.cfg.grid_volume

        return st.avg_cost_price + fee_cost_per_share

    # ----------------------------------------------------------------------
    # 趋势判定
    # ----------------------------------------------------------------------
    def _detect_trend_up(
        self,
        tick: MarketTick,
        st: SymbolState,
    ) -> Tuple[bool, float]:
        """
        震荡上行判定：
        - 快 EMA > 慢 EMA
        - 价格在慢 EMA 上方不远（偏离 < 3%）
        - ATR 百分比适中（0.3% - 2%）
        - RSI 在 40–70 区间

        返回：(是否震荡上行, 得分 0–80)
        """
        price = tick.last_price
        if price <= 0:
            return False, 0.0

        ema_fast = st.ema_fast
        ema_slow = st.ema_slow
        atr = st.atr
        rsi = st.rsi

        if ema_slow <= 0:
            return False, 0.0

        score = 0.0

        # 1) 均线多头排列 + 价格在慢 EMA 上方
        if ema_fast > ema_slow and price > ema_slow:
            score += 30.0

        # 2) 价格离慢 EMA 不太远（非爆拉）
        ema_dist = abs(price - ema_slow) / ema_slow
        if ema_dist < 0.03:
            score += 20.0

        # 3) 波动率适中
        atr_pct = atr / price
        if 0.003 <= atr_pct <= 0.02:
            score += 20.0

        # 4) RSI 在 40–70 区间
        if 40 <= rsi <= 70:
            score += 10.0

        is_trend_up = score >= 40.0
        return is_trend_up, score

    # ----------------------------------------------------------------------
    # 核心仓引擎
    # ----------------------------------------------------------------------
    def _check_core_position(
        self,
        tick: MarketTick,
        st: SymbolState,
    ) -> Optional[TradingSignal]:
        """检查核心仓位，如不足则生成补仓信号"""
        target_core = min(self.cfg.core_pos, self.cfg.max_pos)

        if st.position >= target_core:
            return None

        buy_volume = target_core - st.position
        if buy_volume <= 0:
            return None

        # 控制交易频率：5秒内不重复交易
        now = time.time()
        if now - st.last_trade_ts < 5.0:
            return None

        signal = TradingSignal(
            symbol=tick.symbol,
            action=0,  # BUY
            price=tick.last_price,
            quantity=buy_volume,
            confidence=0.8,
            reason="core_position"
        )

        logger.info(
            f"[DualEngine][Core] 核心补仓信号：pos={st.position} → target={target_core}, "
            f"buy_vol={buy_volume}, price={tick.last_price:.2f}"
        )

        return signal

    # ----------------------------------------------------------------------
    # 网格引擎
    # ----------------------------------------------------------------------
    def _check_grid_signal(
        self,
        tick: MarketTick,
        st: SymbolState,
    ) -> Optional[TradingSignal]:
        """
        检查网格信号

        逻辑：
        1. 若无网格中心，初始化为当前价格
        2. 若价格偏离中心超过2格，重建网格中心
        3. 生成网格买卖信号
        """
        if self.cfg.grid_levels <= 0 or self.cfg.grid_volume <= 0:
            return None

        price = tick.last_price
        step_pct = self.cfg.grid_step_pct / 100.0

        # 初始化网格中心
        if st.grid_center <= 0:
            st.grid_center = price
            logger.info(
                f"[DualEngine][Grid] 初始化网格中心：center={st.grid_center:.2f}"
            )

        # 检查是否需要重建网格
        center = st.grid_center
        deviation = abs(price - center) / center if center > 0 else 0.0

        if deviation >= 2 * step_pct:
            old_center = st.grid_center
            st.grid_center = price
            logger.info(
                f"[DualEngine][Grid] 爬坡重建网格：old_center={old_center:.2f}, "
                f"new_center={price:.2f}, deviation={deviation*100:.2f}%"
            )

        # 生成网格信号（这里简化为只生成最近的一层信号）
        return self._generate_nearest_grid_signal(tick, st)

    def _generate_nearest_grid_signal(
        self,
        tick: MarketTick,
        st: SymbolState,
    ) -> Optional[TradingSignal]:
        """生成最近的网格信号"""
        price = tick.last_price
        center = st.grid_center
        step = self.cfg.grid_step_pct / 100.0

        # 判断价格在网格的哪个位置
        if price < center:
            # 价格低于中心 → 考虑买入
            available_space = self.cfg.max_pos - st.position
            if available_space < self.cfg.grid_volume:
                return None

            # 计算最近的买入价格
            grid_idx = int((center - price) / (center * step)) + 1
            buy_price = center * (1.0 - step * grid_idx)

            # 检查是否接近目标价格
            if abs(price - buy_price) / price > step * 0.5:
                return None

            signal = TradingSignal(
                symbol=tick.symbol,
                action=0,  # BUY
                price=price,
                quantity=self.cfg.grid_volume,
                confidence=0.6,
                reason=f"grid_buy_L{grid_idx}"
            )

            return signal

        else:
            # 价格高于中心 → 考虑卖出
            if st.position < self.cfg.grid_volume:
                return None

            # 检查是否达到最低卖价
            min_sell_price = self._calculate_min_sell_price(st)
            if min_sell_price > 0 and price < min_sell_price:
                return None

            # 计算最近的卖出价格
            grid_idx = int((price - center) / (center * step)) + 1
            sell_price = center * (1.0 + step * grid_idx)

            # 检查是否接近目标价格
            if abs(price - sell_price) / price > step * 0.5:
                return None

            signal = TradingSignal(
                symbol=tick.symbol,
                action=1,  # SELL
                price=price,
                quantity=self.cfg.grid_volume,
                confidence=0.6,
                reason=f"grid_sell_L{grid_idx}"
            )

            return signal

    # ----------------------------------------------------------------------
    # 止盈检查
    # ----------------------------------------------------------------------
    def _check_exit_conditions(
        self,
        tick: MarketTick,
        st: SymbolState,
    ) -> Optional[TradingSignal]:
        """
        检查止盈条件

        支持两种模式：
        1. 动态止盈：有盈利方向反转才平仓
        2. 传统止盈：固定止盈/移动止盈
        """
        if st.position <= 0 or st.avg_cost_price <= 0:
            return None

        price = tick.last_price
        pnl_ticks = (price - st.avg_cost_price) / self.cfg.pricetick

        # 动态止盈模式
        if self.cfg.enable_dynamic_exit:
            return self._check_dynamic_exit(tick, st, pnl_ticks)

        # 传统止盈模式
        return self._check_traditional_exit(tick, st, pnl_ticks)

    def _check_dynamic_exit(
        self,
        tick: MarketTick,
        st: SymbolState,
        pnl_ticks: float,
    ) -> Optional[TradingSignal]:
        """动态止盈逻辑"""
        price = tick.last_price

        # 更新最优价格
        if st.best_profit_price is None:
            st.best_profit_price = price
        elif price > st.best_profit_price:
            st.best_profit_price = price

        # 判断是否有盈利
        has_profit = pnl_ticks >= self.cfg.dynamic_profit_threshold_ticks

        if not has_profit:
            # 亏损时不止损，等待反转
            return None

        # 有盈利时，检查方向是否反转
        reversal_ticks = (st.best_profit_price - price) / self.cfg.pricetick

        if reversal_ticks >= self.cfg.dynamic_reversal_ticks:
            # 方向反转 → 平仓
            signal = TradingSignal(
                symbol=tick.symbol,
                action=1,  # SELL
                price=price,
                quantity=st.position,
                confidence=0.9,
                reason=f"dynamic_exit_reversal(profit={pnl_ticks:.1f}T,reversal={reversal_ticks:.1f}T)"
            )

            logger.info(
                f"[DualEngine][Exit] 动态止盈触发：profit={pnl_ticks:.1f}T, "
                f"reversal={reversal_ticks:.1f}T"
            )

            return signal

        return None

    def _check_traditional_exit(
        self,
        tick: MarketTick,
        st: SymbolState,
        pnl_ticks: float,
    ) -> Optional[TradingSignal]:
        """传统止盈逻辑"""
        price = tick.last_price

        # 移动止盈
        if self.cfg.enable_trailing_stop:
            if st.best_profit_price is None:
                st.best_profit_price = price
            elif price > st.best_profit_price:
                st.best_profit_price = price

            # 检查是否激活移动止盈
            if not st.trailing_active and pnl_ticks >= self.cfg.trailing_activation_ticks:
                st.trailing_active = True
                logger.info(
                    f"[DualEngine][Exit] 移动止盈已激活：profit={pnl_ticks:.1f}T"
                )

            # 检查回撤
            if st.trailing_active:
                pullback_ticks = (st.best_profit_price - price) / self.cfg.pricetick

                if pullback_ticks >= self.cfg.trailing_distance_ticks:
                    signal = TradingSignal(
                        symbol=tick.symbol,
                        action=1,  # SELL
                        price=price,
                        quantity=st.position,
                        confidence=0.9,
                        reason=f"trailing_stop(pullback={pullback_ticks:.1f}T)"
                    )

                    logger.info(
                        f"[DualEngine][Exit] 移动止盈触发：pullback={pullback_ticks:.1f}T"
                    )

                    return signal

        # 固定止盈
        profit_threshold = self.cfg.profit_take_pct / 100.0 * st.avg_cost_price / self.cfg.pricetick

        if pnl_ticks >= profit_threshold:
            signal = TradingSignal(
                symbol=tick.symbol,
                action=1,  # SELL
                price=price,
                quantity=st.position,
                confidence=0.9,
                reason=f"take_profit({pnl_ticks:.1f}T)"
            )

            logger.info(
                f"[DualEngine][Exit] 固定止盈触发：profit={pnl_ticks:.1f}T"
            )

            return signal

        return None

    # ----------------------------------------------------------------------
    # 技术指标计算
    # ----------------------------------------------------------------------
    @staticmethod
    def _calc_ema(prices: List[float], period: int) -> float:
        if not prices:
            return 0.0
        if len(prices) <= period:
            return sum(prices) / len(prices)

        alpha = 2.0 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = alpha * p + (1 - alpha) * ema
        return ema

    @staticmethod
    def _calc_atr(highs: List[float], lows: List[float]) -> float:
        if len(highs) < 2 or len(lows) < 2:
            return 0.0

        trs: List[float] = []
        for i in range(1, len(highs)):
            high = highs[i]
            low = lows[i]
            prev_close = highs[i - 1]
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            trs.append(tr)

        return sum(trs) / len(trs) if trs else 0.0

    @staticmethod
    def _calc_rsi(prices: List[float], period: int = 14) -> float:
        if len(prices) <= period:
            return 50.0

        gains: List[float] = []
        losses: List[float] = []

        for i in range(1, len(prices)):
            delta = prices[i] - prices[i - 1]
            if delta >= 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(-delta)

        gains = gains[-period:]
        losses = losses[-period:]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    # ----------------------------------------------------------------------
    # 状态查询
    # ----------------------------------------------------------------------
    def get_strategy_status(self, symbol: str) -> Dict[str, float]:
        """获取策略状态"""
        st = self.symbol_states.get(symbol)
        if not st:
            return {"data_points": 0}

        return {
            "data_points": float(len(st.prices)),
            "ema_fast": float(st.ema_fast),
            "ema_slow": float(st.ema_slow),
            "atr": float(st.atr),
            "rsi": float(st.rsi),
            "trend_up": float(1.0 if st.trend_up else 0.0),
            "osc_up_score": float(st.osc_up_score),
            "position": float(st.position),
            "avg_cost_price": float(st.avg_cost_price),
            "grid_center": float(st.grid_center),
        }

    def get_performance_metrics(self) -> Dict[str, float]:
        """获取性能指标"""
        return {
            "total_updates": float(self.total_updates),
            "total_signals": float(self.total_signals),
            "symbols_tracked": float(len(self.symbol_states)),
        }
