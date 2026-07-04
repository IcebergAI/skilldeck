def apply_discount(price, percent):
    if percent < 0 or percent > 100:
        raise ValueError("percent out of range")
    return round(price * (1 - percent / 100), 2)
