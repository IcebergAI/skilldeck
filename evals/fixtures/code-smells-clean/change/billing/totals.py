SALES_TAX_PERCENT = 7


def _taxed_subtotal(cents: list[int]) -> int:
    subtotal = sum(cents)
    tax = (subtotal * SALES_TAX_PERCENT + 50) // 100
    return subtotal + tax


def invoice_total(cents: list[int], shipping: int) -> int:
    return _taxed_subtotal(cents) + shipping


def quote_total(cents: list[int], discount: int) -> int:
    return _taxed_subtotal(cents) - discount
