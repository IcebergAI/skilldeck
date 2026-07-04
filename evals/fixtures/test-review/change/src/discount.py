def apply_discount(price, percent, coupon=None):
    if percent < 0 or percent > 100:
        raise ValueError("percent out of range")
    if coupon is not None:
        if not coupon.startswith("SAVE"):
            raise ValueError("unknown coupon")
        percent = min(percent + 15, 100)
    return round(price * (1 - percent / 100), 2)
