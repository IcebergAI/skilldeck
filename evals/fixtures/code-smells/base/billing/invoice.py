TAX_RATES = {"US": 0.07, "DE": 0.19, "FR": 0.20}
LOYALTY_YEARS = 5
LOYALTY_RATE = 0.05


def line_total(quantity, unit_price):
    return quantity * unit_price


def subtotal(lines):
    return sum(line_total(line.quantity, line.unit_price) for line in lines)


def invoice_total(order, customer):
    amount = subtotal(order.lines)
    if customer.loyalty_years >= LOYALTY_YEARS:
        amount -= amount * LOYALTY_RATE
    return round(amount * (1 + TAX_RATES[customer.country]), 2)
