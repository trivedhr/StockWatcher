"""
Tests for _safe() — the NaN / Infinity → None sanitiser.

_safe() must be called before every jsonify() call so the JSON encoder
never chokes on non-serialisable floats coming back from yfinance.
"""
import math
import pytest
from server import _safe


# ── Scalar values ─────────────────────────────────────────────────────────────

class TestSafeScalars:
    def test_nan_becomes_none(self):
        assert _safe(float('nan')) is None

    def test_positive_inf_becomes_none(self):
        assert _safe(float('inf')) is None

    def test_negative_inf_becomes_none(self):
        assert _safe(float('-inf')) is None

    def test_normal_float_passes_through(self):
        assert _safe(3.14) == 3.14

    def test_zero_float_passes_through(self):
        assert _safe(0.0) == 0.0

    def test_negative_float_passes_through(self):
        assert _safe(-42.5) == -42.5

    def test_integer_passes_through(self):
        assert _safe(100) == 100

    def test_string_passes_through(self):
        assert _safe('AAPL') == 'AAPL'

    def test_none_passes_through(self):
        assert _safe(None) is None

    def test_bool_passes_through(self):
        assert _safe(True) is True
        assert _safe(False) is False


# ── Dict recursion ─────────────────────────────────────────────────────────────

class TestSafeDicts:
    def test_clean_dict_unchanged(self):
        d = {'price': 150.0, 'name': 'Apple'}
        assert _safe(d) == d

    def test_nan_value_in_dict_becomes_none(self):
        result = _safe({'pe_ratio': float('nan'), 'price': 150.0})
        assert result['pe_ratio'] is None
        assert result['price'] == 150.0

    def test_inf_value_in_dict_becomes_none(self):
        result = _safe({'ratio': float('inf')})
        assert result['ratio'] is None

    def test_nested_dict_cleaned_recursively(self):
        d = {'stats': {'pe': float('nan'), 'eps': 5.0}, 'price': 100.0}
        result = _safe(d)
        assert result['stats']['pe'] is None
        assert result['stats']['eps'] == 5.0
        assert result['price'] == 100.0

    def test_multiple_nan_values_in_dict(self):
        d = {'a': float('nan'), 'b': float('inf'), 'c': 1.0}
        result = _safe(d)
        assert result['a'] is None
        assert result['b'] is None
        assert result['c'] == 1.0

    def test_empty_dict_returns_empty_dict(self):
        assert _safe({}) == {}


# ── List recursion ─────────────────────────────────────────────────────────────

class TestSafeLists:
    def test_clean_list_unchanged(self):
        lst = [1.0, 2.0, 3.0]
        assert _safe(lst) == lst

    def test_nan_in_list_becomes_none(self):
        result = _safe([1.0, float('nan'), 3.0])
        assert result == [1.0, None, 3.0]

    def test_inf_in_list_becomes_none(self):
        result = _safe([float('inf'), 2.0])
        assert result[0] is None
        assert result[1] == 2.0

    def test_empty_list_returns_empty_list(self):
        assert _safe([]) == []

    def test_list_of_dicts_cleaned(self):
        data = [{'price': 100.0}, {'price': float('nan')}]
        result = _safe(data)
        assert result[0]['price'] == 100.0
        assert result[1]['price'] is None


# ── Stock dict (realistic payload) ────────────────────────────────────────────

class TestSafeStockPayload:
    def test_realistic_etf_payload_with_nan(self):
        """yfinance often returns NaN for ETF fields like trailingPE."""
        stock = {
            'symbol': 'VOO',
            'name': 'Vanguard S&P 500 ETF',
            'price': 450.32,
            'day_pct': float('nan'),
            'pe_ratio': float('nan'),
            'market_cap': float('inf'),
            'prices': [448.0, 449.5, 450.32],
        }
        result = _safe(stock)
        assert result['symbol'] == 'VOO'
        assert result['price'] == 450.32
        assert result['day_pct'] is None
        assert result['pe_ratio'] is None
        assert result['market_cap'] is None
        assert result['prices'] == [448.0, 449.5, 450.32]
