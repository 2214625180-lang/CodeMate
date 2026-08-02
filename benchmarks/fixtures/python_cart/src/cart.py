from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CartLine:
    unit_price: Decimal
    quantity: int


def calculate_subtotal(lines: list[CartLine]) -> Decimal:
    return sum((line.unit_price * line.quantity for line in lines), Decimal("0"))


def calculate_total(lines: list[CartLine], tax_rate: Decimal) -> Decimal:
    """Return the subtotal including tax."""

    subtotal = calculate_subtotal(lines)
    tax = subtotal * tax_rate
    return subtotal - tax
