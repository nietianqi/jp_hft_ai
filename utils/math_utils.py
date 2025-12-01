def fast_tick_size(price: float) -> float:
    if price <= 3000:
        return 1.0
    elif price <= 5000:
        return 5.0
    elif price <= 30000:
        return 10.0
    elif price <= 50000:
        return 50.0
    else:
        return 100.0

def fast_round_tick(price: float) -> float:
    tick_size = fast_tick_size(price)
    return round(price / tick_size) * tick_size

def calculate_pnl_ticks(entry_price: float, current_price: float) -> float:
    tick_size = fast_tick_size(entry_price)
    return (current_price - entry_price) / tick_size
