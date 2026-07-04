TAX_RATES = {"US": 0.07, "DE": 0.19, "FR": 0.20}


def line_total(quantity, unit_price):
    return quantity * unit_price


def generate_invoice(order, customer, printer):
    # validate
    if not order.lines:
        raise ValueError("empty order")
    for line in order.lines:
        if line.quantity <= 0:
            raise ValueError(f"bad quantity for {line.sku}")
        if line.unit_price < 0:
            raise ValueError(f"bad price for {line.sku}")
    if customer.country not in TAX_RATES:
        raise ValueError(f"unsupported country {customer.country}")

    # subtotal
    subtotal = 0.0
    for line in order.lines:
        subtotal += line_total(line.quantity, line.unit_price)

    # discounts
    discount = 0.0
    if customer.loyalty_years >= 5:
        discount += subtotal * 0.05
    if order.coupon and order.coupon.startswith("SAVE"):
        try:
            discount += subtotal * (int(order.coupon[4:]) / 100)
        except ValueError:
            pass
    if subtotal - discount > 10000:
        discount += 50.0

    # tax
    taxable = subtotal - discount
    tax = taxable * TAX_RATES[customer.country]
    total = taxable + tax

    # render
    lines = []
    lines.append(f"INVOICE {order.number}")
    lines.append(f"Customer: {customer.name} ({customer.country})")
    lines.append("-" * 40)
    for line in order.lines:
        amount = line_total(line.quantity, line.unit_price)
        lines.append(f"{line.sku:<12} x{line.quantity:>3}  {amount:>10.2f}")
    lines.append("-" * 40)
    lines.append(f"Subtotal: {subtotal:>10.2f}")
    lines.append(f"Discount: {discount:>10.2f}")
    lines.append(f"Tax:      {tax:>10.2f}")
    lines.append(f"Total:    {total:>10.2f}")
    document = "\n".join(lines)

    # deliver
    printer.spool(document)
    if customer.email:
        printer.email(customer.email, subject=f"Invoice {order.number}",
                      body=document)
    return total
