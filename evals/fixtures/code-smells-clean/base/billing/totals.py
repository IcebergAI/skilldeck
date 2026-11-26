SALES_TAX_PERCENT = 7


def invoice_total(cents: list[int], shipping: int) -> int:
    subtotal = sum(cents)
    tax = (subtotal * SALES_TAX_PERCENT + 50) // 100
    return subtotal + tax + shipping


def quote_total(cents: list[int], discount: int) -> int:
    subtotal = sum(cents)
    tax = (subtotal * SALES_TAX_PERCENT + 50) // 100
    return subtotal + tax - discount
