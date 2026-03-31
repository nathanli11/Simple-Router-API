import unittest

from app.config import split_symbol


class TestConfig(unittest.TestCase):
    def test_split_symbol_usdt(self) -> None:
        self.assertEqual(split_symbol("BTCUSDT"), ("BTC", "USDT"))

    def test_split_symbol_usd(self) -> None:
        self.assertEqual(split_symbol("BTCUSD"), ("BTC", "USD"))

    def test_split_symbol_usdc(self) -> None:
        self.assertEqual(split_symbol("BTCUSDC"), ("BTC", "USDC"))

    def test_split_symbol_fallback(self) -> None:
        self.assertEqual(split_symbol("FOOBAR"), ("FOO", "BAR"))
