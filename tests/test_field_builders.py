"""
Tests for the pure field-builder functions that transform raw yfinance
price Series into the dicts the frontend consumes.

All tests use synthetic price series — no network calls.
"""
import pytest
from tests.conftest import make_series
from server import _1m_fields, _10y_fields, _max_fields, _penny_time_fields


# ── _1m_fields ────────────────────────────────────────────────────────────────

class TestOneMFields:
    def test_returns_none_for_empty_series(self):
        assert _1m_fields(make_series([])) is None

    def test_basic_structure(self):
        prices = [100.0] * 20 + [110.0]
        result = _1m_fields(make_series(prices))
        assert result is not None
        assert 'price' in result
        assert 'day_change' in result
        assert 'day_pct' in result
        assert 'month_pct' in result
        assert 'prices' in result
        assert 'dates' in result

    def test_price_is_last_value(self):
        prices = [100.0, 105.0, 110.0]
        result = _1m_fields(make_series(prices))
        assert result['price'] == 110.0

    def test_day_change_calculated_correctly(self):
        prices = [100.0, 105.0, 110.0]
        result = _1m_fields(make_series(prices))
        assert result['day_change'] == round(110.0 - 105.0, 2)

    def test_month_pct_calculated_correctly(self):
        prices = [100.0] * 10 + [120.0]
        result = _1m_fields(make_series(prices))
        expected = round((120.0 - 100.0) / 100.0 * 100, 2)
        assert result['month_pct'] == expected

    def test_single_element_series(self):
        result = _1m_fields(make_series([150.0]))
        assert result['price'] == 150.0
        assert result['day_change'] == 0.0

    def test_flat_prices_produce_zero_pct(self):
        prices = [50.0] * 22
        result = _1m_fields(make_series(prices))
        assert result['month_pct'] == 0.0
        assert result['day_pct'] == 0.0

    def test_prices_list_matches_series(self):
        prices = list(range(100, 122))  # 22 values
        result = _1m_fields(make_series(prices))
        assert result['prices'] == [float(p) for p in prices]
        assert len(result['dates']) == len(prices)


# ── _10y_fields ───────────────────────────────────────────────────────────────

class TestTenYFields:
    def test_basic_structure(self):
        series = make_series([100.0] * 120, freq='ME')
        result = _10y_fields(series)
        assert 'prices_10y' in result
        assert 'dates_10y' in result
        assert 'year_pct' in result
        assert 'pct_5y' in result

    def test_year_pct_calculation(self):
        # 100 → 200 = 100% gain
        prices = [100.0] + [150.0] * 118 + [200.0]
        result = _10y_fields(make_series(prices, freq='ME'))
        assert result['year_pct'] == 100.0

    def test_pct_5y_uses_60th_bar_from_end(self):
        # Last 60 bars: start at 100, end at 150 → 50% gain
        prices = [50.0] * 60 + [100.0] * 59 + [150.0]
        result = _10y_fields(make_series(prices, freq='ME'))
        assert result['pct_5y'] == 50.0

    def test_pct_5y_falls_back_when_fewer_than_60_bars(self):
        # Only 10 bars — pct_5y should use prices[0] as base
        prices = [100.0] + [9.0] * 8 + [200.0]
        result = _10y_fields(make_series(prices, freq='ME'))
        assert result['pct_5y'] == 100.0

    def test_prices_and_dates_same_length(self):
        series = make_series([float(i) for i in range(1, 121)], freq='ME')
        result = _10y_fields(series)
        assert len(result['prices_10y']) == len(result['dates_10y'])

    def test_dates_are_strings(self):
        series = make_series([100.0] * 5, freq='ME')
        result = _10y_fields(series)
        for d in result['dates_10y']:
            assert isinstance(d, str)


# ── _max_fields ───────────────────────────────────────────────────────────────

class TestMaxFields:
    def test_returns_empty_dicts_for_empty_series(self):
        result = _max_fields(make_series([], freq='ME'))
        assert result['prices_10y'] == []
        assert result['prices_30y'] == []
        assert result['year_pct'] is None
        assert result['pct_30y'] is None

    def test_prices_10y_is_last_120_bars(self):
        prices = list(range(1, 201))  # 200 bars
        result = _max_fields(make_series(prices, freq='ME'))
        assert result['prices_10y'] == [float(p) for p in prices[-120:]]

    def test_prices_30y_contains_all_bars(self):
        prices = list(range(1, 201))
        result = _max_fields(make_series(prices, freq='ME'))
        assert len(result['prices_30y']) == 200

    def test_prices_10y_equals_30y_when_le_120_bars(self):
        prices = [100.0] * 60
        result = _max_fields(make_series(prices, freq='ME'))
        assert result['prices_10y'] == result['prices_30y']

    def test_pct_30y_uses_full_history(self):
        # First bar 100, last bar 300 → 200% gain
        prices = [100.0] + [150.0] * 200 + [300.0]
        result = _max_fields(make_series(prices, freq='ME'))
        assert result['pct_30y'] == 200.0

    def test_structure_keys_present(self):
        result = _max_fields(make_series([100.0, 110.0], freq='ME'))
        for key in ('prices_10y', 'dates_10y', 'year_pct', 'pct_5y',
                    'prices_30y', 'dates_30y', 'pct_30y'):
            assert key in result


# ── _penny_time_fields ────────────────────────────────────────────────────────

class TestPennyTimeFields:
    def _full_series(self, start=100.0, end=150.0, n=252):
        """252 business days ≈ 1 trading year."""
        import numpy as np
        prices = list(map(float, range(int(start), int(start) + n - 1))) + [float(end)]
        # Ensure we have exactly n bars
        prices = prices[:n]
        return make_series(prices, freq='B')

    def test_returns_none_for_empty_series(self):
        assert _penny_time_fields(make_series([])) is None

    def test_basic_structure_keys(self):
        result = _penny_time_fields(self._full_series())
        expected_keys = {
            'price', 'day_change', 'day_pct',
            'month_change', 'month_pct', 'pct_1mo',
            'pct_5d', 'pct_15d', 'pct_45d', 'pct_3mo', 'pct_6mo', 'pct_1y',
            'prices', 'dates', 'prices_1y', 'dates_1y',
        }
        assert expected_keys.issubset(result.keys())

    def test_price_is_last_value(self):
        prices = list(range(100, 353))
        result = _penny_time_fields(make_series(prices))
        assert result['price'] == float(prices[-1])

    def test_pct_1y_uses_first_bar_as_base(self):
        # First bar 100, last bar 200 → 100% gain
        prices = [100.0] + [120.0] * 250 + [200.0]
        result = _penny_time_fields(make_series(prices))
        assert result['pct_1y'] == 100.0

    def test_pct_5d_none_when_series_too_short(self):
        # Only 4 bars — pct_5d needs at least 6
        result = _penny_time_fields(make_series([100.0, 101.0, 102.0, 103.0]))
        assert result['pct_5d'] is None

    def test_pct_6mo_none_when_series_too_short(self):
        # pct_6mo needs >126 bars
        prices = [100.0] * 100
        result = _penny_time_fields(make_series(prices))
        assert result['pct_6mo'] is None

    def test_pct_6mo_populated_with_enough_bars(self):
        prices = [100.0] * 130 + [200.0]  # 131 bars → pct_6mo available
        result = _penny_time_fields(make_series(prices))
        assert result['pct_6mo'] is not None

    def test_prices_sparkline_is_last_22_bars(self):
        prices = list(range(1, 250))
        result = _penny_time_fields(make_series(prices))
        assert result['prices'] == [float(p) for p in prices[-22:]]

    def test_prices_1y_contains_full_series(self):
        prices = list(range(1, 253))
        result = _penny_time_fields(make_series(prices))
        assert result['prices_1y'] == [float(p) for p in prices]

    def test_flat_prices_all_pct_zero(self):
        prices = [100.0] * 252
        result = _penny_time_fields(make_series(prices))
        assert result['day_pct'] == 0.0
        assert result['month_pct'] == 0.0
        assert result['pct_1y'] == 0.0

    def test_single_element_returns_result(self):
        result = _penny_time_fields(make_series([75.0]))
        assert result is not None
        assert result['price'] == 75.0
        assert result['day_change'] == 0.0
