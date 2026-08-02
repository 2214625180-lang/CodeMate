from decimal import Decimal

from src.cart import CartLine, calculate_total


def build_checkout_amount(raw_prices: list[str], tax_rate: str) -> str:
    lines = [CartLine(unit_price=Decimal(price), quantity=1) for price in raw_prices]
    return str(calculate_total(lines, Decimal(tax_rate)))
