from datetime import date, timedelta

from billing.invoice import LOYALTY_RATE, LOYALTY_YEARS, TAX_RATES, line_total

QUOTE_VALIDITY = timedelta(days=30)


def quote_total(quote, customer):
    amount = 0.0
    for line in quote.lines:
        amount += line_total(line.quantity, line.unit_price)
    if customer.loyalty_years >= LOYALTY_YEARS:
        amount -= amount * LOYALTY_RATE
    return round(amount * (1 + TAX_RATES[customer.country]), 2)


def quote_expired(quote, today=None):
    return (today or date.today()) > quote.issued_on + QUOTE_VALIDITY
