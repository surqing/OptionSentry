from __future__ import annotations

import math
import unittest

from optionsentry.formatting import (
    format_display_number,
    format_display_range,
    format_key_bound,
    format_key_number,
    format_key_range,
)


class FormattingTests(unittest.TestCase):
    def test_key_formatting_preserves_compact_g_contract(self) -> None:
        self.assertEqual(format_key_number(600.0), "600")
        self.assertEqual(format_key_number(1.234567891), "1.23457")
        self.assertEqual(format_key_bound(math.inf), "inf")
        self.assertEqual(format_key_bound(-math.inf), "-inf")
        self.assertEqual(format_key_range(-math.inf, 0.1), "(-inf, 0.1)")

    def test_display_formatting_preserves_eight_decimal_contract(self) -> None:
        self.assertEqual(format_display_number(1.234567891), "1.23456789")
        self.assertEqual(format_display_number(0.0), "0")
        self.assertEqual(format_display_range(-math.inf, 0.1), "(-inf, 0.1)")


if __name__ == "__main__":
    unittest.main()
