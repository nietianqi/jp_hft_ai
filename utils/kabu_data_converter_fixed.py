# -*- coding: utf-8 -*-
"""
kabu_data_converter_fixed.py

修正Kabu API的Bid/Ask混淆问题
"""

from typing import Dict, Any, List, Tuple
from datetime import datetime


def convert_kabu_board_to_standard(kabu_board: Dict[str, Any]) -> Dict[str, Any]:
    """
    将Kabu的板行情转换为标准格式
    
    ⚠️ 关键修正:
    - Kabu的Buy1 = 买方报价 (Bid)
    - Kabu的Sell1 = 卖方报价 (Ask)
    """
    
    # 提取最佳买卖价
    buy1 = kabu_board.get("Buy1", {})
    sell1 = kabu_board.get("Sell1", {})
    
    best_bid = float(buy1.get("Price", 0)) if buy1 else 0.0
    best_ask = float(sell1.get("Price", 0)) if sell1 else 0.0
    
    # 提取深度数据
    bids: List[Tuple[float, int]] = []
    asks: List[Tuple[float, int]] = []
    
    for i in range(1, 11):
        buy_level = kabu_board.get(f"Buy{i}")
        if buy_level and buy_level.get("Price"):
            price = float(buy_level["Price"])
            qty = int(buy_level.get("Qty", 0))
            if price > 0 and qty > 0:
                bids.append((price, qty))
        
        sell_level = kabu_board.get(f"Sell{i}")
        if sell_level and sell_level.get("Price"):
            price = float(sell_level["Price"])
            qty = int(sell_level.get("Qty", 0))
            if price > 0 and qty > 0:
                asks.append((price, qty))
    
    bids.sort(reverse=True)
    asks.sort()
    
    current_price = float(kabu_board.get("CurrentPrice", 0))
    if current_price <= 0 and best_bid > 0 and best_ask > 0:
        current_price = (best_bid + best_ask) / 2
    
    return {
        "symbol": kabu_board.get("Symbol"),
        "timestamp": datetime.now(),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "last_price": current_price,
        "bids": bids,
        "asks": asks,
        "bid_qty": int(buy1.get("Qty", 0)) if buy1 else 0,
        "ask_qty": int(sell1.get("Qty", 0)) if sell1 else 0,
        "vwap": float(kabu_board.get("VWAP", 0)),
        "trading_volume": int(kabu_board.get("TradingVolume", 0)),
        "buy_market_order": int(kabu_board.get("MarketOrderBuyQty", 0)),
        "sell_market_order": int(kabu_board.get("MarketOrderSellQty", 0)),
    }
