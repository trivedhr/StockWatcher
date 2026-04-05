"""
Tests for disk-cache helpers: _load, _save, _stale_1m, _stale_10y.

These are pure logic / file-I/O tests — no network required.
"""
import json
import os
import pytest
from datetime import datetime, timedelta
from server import _load, _save, _stale_1m, _stale_10y, MAX_AGE_1M_H, MAX_AGE_10Y_D


# ── _load ─────────────────────────────────────────────────────────────────────

class TestLoad:
    def test_returns_none_for_missing_file(self, tmp_path):
        assert _load(str(tmp_path / 'no_such_file.json')) is None

    def test_returns_none_for_invalid_json(self, tmp_path):
        bad = tmp_path / 'bad.json'
        bad.write_text('{ not valid json }')
        assert _load(str(bad)) is None

    def test_loads_valid_json(self, tmp_path):
        payload = {'version': 2, 'data': [{'symbol': 'AAPL'}]}
        f = tmp_path / 'cache.json'
        f.write_text(json.dumps(payload))
        result = _load(str(f))
        assert result == payload

    def test_returns_empty_dict_for_empty_object(self, tmp_path):
        f = tmp_path / 'empty.json'
        f.write_text('{}')
        assert _load(str(f)) == {}


# ── _save ─────────────────────────────────────────────────────────────────────

class TestSave:
    def test_writes_json_to_disk(self, tmp_path):
        path = str(tmp_path / 'out.json')
        payload = {'version': 1, 'data': [{'symbol': 'SPY'}]}
        _save(path, payload)
        with open(path) as f:
            assert json.load(f) == payload

    def test_overwrites_existing_file(self, tmp_path):
        path = str(tmp_path / 'out.json')
        _save(path, {'data': [1]})
        _save(path, {'data': [2]})
        with open(path) as f:
            assert json.load(f) == {'data': [2]}

    def test_round_trip_load_save(self, tmp_path):
        path = str(tmp_path / 'rt.json')
        original = {'version': 3, 'time': '2025-01-01T00:00:00',
                    'data': [{'symbol': 'VOO', 'price': 450.0}]}
        _save(path, original)
        assert _load(path) == original


# ── _stale_1m ─────────────────────────────────────────────────────────────────

class TestStaleOneM:
    def _ts(self, hours_ago):
        return (datetime.now() - timedelta(hours=hours_ago)).isoformat()

    def test_none_disk_is_stale(self):
        assert _stale_1m(None) is True

    def test_missing_key_is_stale(self):
        assert _stale_1m({}) is True

    def test_fresh_cache_is_not_stale(self):
        d = {'last_1m_update': self._ts(1)}  # 1 hour ago < 24h threshold
        assert _stale_1m(d) is False

    def test_exactly_at_threshold_is_stale(self):
        d = {'last_1m_update': self._ts(MAX_AGE_1M_H)}
        assert _stale_1m(d) is True

    def test_old_cache_is_stale(self):
        d = {'last_1m_update': self._ts(MAX_AGE_1M_H + 1)}
        assert _stale_1m(d) is True

    def test_future_timestamp_is_not_stale(self):
        d = {'last_1m_update': (datetime.now() + timedelta(hours=1)).isoformat()}
        assert _stale_1m(d) is False


# ── _stale_10y ────────────────────────────────────────────────────────────────

class TestStaleTenY:
    def _ts(self, days_ago):
        return (datetime.now() - timedelta(days=days_ago)).isoformat()

    def test_none_disk_is_stale(self):
        assert _stale_10y(None) is True

    def test_missing_key_is_stale(self):
        assert _stale_10y({}) is True

    def test_fresh_cache_is_not_stale(self):
        d = {'last_10y_update': self._ts(1)}  # 1 day ago < 10d threshold
        assert _stale_10y(d) is False

    def test_exactly_at_threshold_is_stale(self):
        d = {'last_10y_update': self._ts(MAX_AGE_10Y_D)}
        assert _stale_10y(d) is True

    def test_old_cache_is_stale(self):
        d = {'last_10y_update': self._ts(MAX_AGE_10Y_D + 1)}
        assert _stale_10y(d) is True

    def test_9_days_old_is_not_stale(self):
        d = {'last_10y_update': self._ts(MAX_AGE_10Y_D - 1)}
        assert _stale_10y(d) is False
