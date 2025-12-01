from __future__ import annotations

import time
from dataclasses import dataclass
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from models.market_data import MarketTick
from models.trading_models import TradingSignal
from strategy.base import TradingStrategy


@dataclass
class ComprehensiveSignal:
    """整合后的高层信号（给引擎做决策用）"""
    final_score: float                 # 0–100
    recommendation: str               # "BUY" / "WAIT"
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size_multiplier: float
    details: Dict[str, float]


@dataclass
class SymbolState:
    """单只股票的状态与技术指标缓存"""
    prices: Deque[float]
    highs: Deque[float]
    lows: Deque[float]
    volumes: Deque[int]
    timestamps: Deque[float]

    ema_fast: float = 0.0
    ema_slow: float = 0.0
    atr: float = 0.0
    rsi: float = 50.0

    last_update_ts: float = 0.0
    last_buy_ts: float = 0.0

    # 震荡上行判定
    is_osc_up: bool = False
    osc_up_score: float = 0.0


class KabuIntegratedTradingStrategy(TradingStrategy):
    """
    【重写版】Kabu 专用震荡上行 + 微网格/剥头皮策略

    目标：
    - 判断某只股票是否处于“震荡上行”状态
    - 在此状态下，频繁给出高胜率的 BUY 信号，让外部引擎用高频微利参数去“吃 tick”
    - 只产生买入信号（action=0），平仓与止盈止损由 EnhancedTradingEngine + StateManager 负责
    """

    def __init__(self, trading_unit: int = 100):
        super().__init__()
        self.trading_unit = trading_unit

        # 每个 symbol 的滚动指标
        self.symbol_states: Dict[str, SymbolState] = {}

        # 最近一次综合信号（给引擎做二次确认用）
        self.last_comprehensive: Dict[str, ComprehensiveSignal] = {}

        # 性能统计
        self.total_updates: int = 0
        self.total_signals: int = 0

        # 指标窗口长度
        self.price_window = 200        # 用于 EMA / ATR / RSI
        self.rsi_period = 14

    # ----------------------------------------------------------------------
    # 对外接口：给引擎 / StateManager 调用
    # ----------------------------------------------------------------------
    def register_symbol(self, symbol: str) -> None:
        """初始化某只股票的状态（系统启动时调用一次即可）"""
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
        """在每个 tick 到来时更新技术指标"""
        symbol = tick.symbol
        if symbol not in self.symbol_states:
            self.register_symbol(symbol)

        st = self.symbol_states[symbol]
        now = time.time()

        # 1. 更新原始数据
        st.prices.append(tick.last_price)
        # 简化：用 last_price 近似 high/low（短周期剥头皮足够）
        st.highs.append(tick.last_price)
        st.lows.append(tick.last_price)
        st.volumes.append(tick.volume)
        st.timestamps.append(now)
        st.last_update_ts = now

        self.total_updates += 1

        if len(st.prices) < self.rsi_period + 2:
            # 数据不足，不计算指标
            return

        prices_list = list(st.prices)
        highs_list = list(st.highs)
        lows_list = list(st.lows)

        # 2. 计算 EMA
        st.ema_fast = self._calc_ema(prices_list, period=20)
        st.ema_slow = self._calc_ema(prices_list, period=60)

        # 3. 估算 ATR（用 high/low 的差）
        st.atr = self._calc_atr(highs_list, lows_list)

        # 4. 计算 RSI
        st.rsi = self._calc_rsi(prices_list, period=self.rsi_period)

        # 5. 震荡上行判定
        st.is_osc_up, st.osc_up_score = self._detect_oscillating_up(symbol, tick, st)

    def generate_signal(self, tick: MarketTick) -> Optional[TradingSignal]:
        """
        由引擎在每个 tick 调用：
        - 若当前不满足“震荡上行”，返回 None
        - 若满足震荡上行，且出现短期回调，则返回 BUY 信号
        """
        symbol = tick.symbol
        if symbol not in self.symbol_states:
            return None

        st = self.symbol_states[symbol]
        if len(st.prices) < self.rsi_period + 2:
            return None

        # 最新的趋势与波动信息
        price = tick.last_price
        atr = st.atr
        ema_fast = st.ema_fast
        ema_slow = st.ema_slow
        rsi = st.rsi

        # --- 1. 先判断是否震荡上行 ---
        if not st.is_osc_up:
            comp = ComprehensiveSignal(
                final_score=st.osc_up_score,
                recommendation="WAIT",
                entry_price=price,
                stop_loss=0.0,
                take_profit=0.0,
                position_size_multiplier=0.0,
                details={
                    "ema_fast": ema_fast,
                    "ema_slow": ema_slow,
                    "atr_pct": atr / price if price > 0 else 0.0,
                    "rsi": rsi,
                },
            )
            self.last_comprehensive[symbol] = comp
            return None

        # --- 2. 在震荡上行中寻找“回调买点” ---
        atr_pct = atr / price if price > 0 else 0.0

        # 条件：
        #  - 价格仍在慢速 EMA 上方（保持多头结构）
        #  - 价格回落到快速 EMA 附近或略下方（短期回调）
        #  - RSI 回落但不进入极端超卖（维持多头惯性）
        is_pullback = (
            price > ema_slow * 1.000       # 仍在慢 EMA 上方
            and price < ema_fast * 1.002   # 略低于快 EMA
            and 35 <= rsi <= 60
        )

        # 控制信号频率：同一只股票，两次买入间隔 >= 5 秒
        now = time.time()
        if not is_pullback or now - st.last_buy_ts < 5.0:
            comp = ComprehensiveSignal(
                final_score=st.osc_up_score,
                recommendation="WAIT",
                entry_price=price,
                stop_loss=0.0,
                take_profit=0.0,
                position_size_multiplier=0.0,
                details={
                    "ema_fast": ema_fast,
                    "ema_slow": ema_slow,
                    "atr_pct": atr_pct,
                    "rsi": rsi,
                },
            )
            self.last_comprehensive[symbol] = comp
            return None

        # --- 3. 构造 BUY 信号（单次微网格 / 剥头皮） ---
        # 止损：1.5 * ATR
        stop_loss = price - 1.5 * atr
        # 止盈：1 * ATR（引擎本身还有 MIN_PROFIT_TICKS 等微利参数）
        take_profit = price + 1.0 * atr

        # 综合评分：震荡上行得分 + 额外加分（ATR在合理区间）
        vol_score = 0.0
        if 0.003 <= atr_pct <= 0.02:   # 0.3% - 2% 日内波幅
            vol_score = 20.0
        final_score = max(0.0, min(100.0, st.osc_up_score + vol_score))

        comp = ComprehensiveSignal(
            final_score=final_score,
            recommendation="BUY",
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_multiplier=1.0,
            details={
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "atr_pct": atr_pct,
                "rsi": rsi,
            },
        )
        self.last_comprehensive[symbol] = comp
        self.total_signals += 1
        st.last_buy_ts = now

        # TradingSignal 的具体定义在 models.trading_models 中，这里只使用
        # 引擎真正用到的字段：symbol / action / price / quantity / confidence
        signal = TradingSignal(
            symbol=symbol,
            action=0,  # 0 = BUY（见 EnhancedTradingEngine._handle_idle_state 的判断）
            price=price,
            quantity=self.trading_unit,
            confidence=final_score / 100.0,
        )
        return signal

    # ----------------------------------------------------------------------
    # 给引擎 / 状态管理器使用的辅助接口
    # ----------------------------------------------------------------------
    def get_last_comprehensive_signal(self, symbol: str) -> Optional[ComprehensiveSignal]:
        return self.last_comprehensive.get(symbol)

    def get_performance_metrics(self) -> Dict[str, float]:
        """供健康检查用"""
        return {
            "total_updates": float(self.total_updates),
            "total_signals": float(self.total_signals),
            "symbols_tracked": float(len(self.symbol_states)),
        }

    def get_strategy_status(self, symbol: str) -> Dict[str, float]:
        """
        可选：状态管理器在 can_open_position 中可以调用
       （你之前有一段调用被注释掉了，这里保持兼容）
        """
        st = self.symbol_states.get(symbol)
        if not st:
            return {"data_points": 0}

        return {
            "data_points": float(len(st.prices)),
            "ema_fast": float(st.ema_fast),
            "ema_slow": float(st.ema_slow),
            "atr": float(st.atr),
            "rsi": float(st.rsi),
            "osc_up_score": float(st.osc_up_score),
            "is_osc_up": float(1.0 if st.is_osc_up else 0.0),
        }

    # ----------------------------------------------------------------------
    # 内部指标计算函数
    # ----------------------------------------------------------------------
    @staticmethod
    def _calc_ema(prices: List[float], period: int) -> float:
        if not prices:
            return 0.0
        if len(prices) <= period:
            # 数据较少时，退化为简单平均
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
            prev_close = highs[i - 1]  # 这里用上一根 high 近似前收盘（短线足够）
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

        # 只用最近 period 段
        gains = gains[-period:]
        losses = losses[-period:]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def _detect_oscillating_up(
        self,
        symbol: str,
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

        is_osc_up = score >= 40.0  # 阈值可以以后放到配置里
        return is_osc_up, score
