from decimal import Decimal
import unittest

from src.cart import CartLine, calculate_total


class CalculateTotalTests(unittest.TestCase):
    def test_adds_tax_to_subtotal(self) -> None:
        lines = [CartLine(unit_price=Decimal("10.00"), quantity=2)]

        total = calculate_total(lines, Decimal("0.10"))

        self.assertEqual(total, Decimal("22.0000"))


if __name__ == "__main__":
    unittest.main()
