"""
Tests for all Flask API endpoints using the Flask test client.

No real network calls are made — yfinance is mocked wherever a route
would normally hit it. The in-memory state dicts start empty (status='init'),
which is the clean slate produced by importing server.py without running
__main__.
"""
import json
import pytest
from unittest.mock import patch, MagicMock


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json(response):
    """Parse response body as JSON."""
    return json.loads(response.data)


def _mock_stock(symbol='AAPL'):
    """Minimal stock dict that fetch_watch_stock would return."""
    return {
        'symbol': symbol, 'name': 'Test Corp', 'sector': 'Technology',
        'market_cap': 1_000_000, 'price': 150.0,
        'day_change': 1.0, 'day_pct': 0.67,
        'month_pct': 5.0, 'pct_1mo': 5.0,
        'pct_5d': 1.0, 'pct_15d': 2.0, 'pct_45d': 3.0,
        'pct_3mo': 4.0, 'pct_6mo': 7.0, 'pct_1y': 20.0,
        'year_pct': 150.0, 'pct_5y': 300.0,
        'prices': [148.0, 149.0, 150.0],
        'dates':  ['2025-01-29', '2025-01-30', '2025-01-31'],
        'prices_1y': [100.0] * 252, 'dates_1y': ['2024-01-01'] * 252,
        'prices_10y': [50.0] * 120, 'dates_10y': ['2015-01-01'] * 120,
        'added_at': '2025-01-31T00:00:00',
    }


# ── Static file ───────────────────────────────────────────────────────────────

class TestIndexRoute:
    def test_root_returns_200(self, client):
        resp = client.get('/')
        assert resp.status_code == 200

    def test_root_returns_html(self, client):
        resp = client.get('/')
        assert b'<!DOCTYPE html>' in resp.data or b'<html' in resp.data


# ── Read-only data endpoints ──────────────────────────────────────────────────

class TestDataEndpoints:
    ENDPOINTS = [
        '/api/stocks',
        '/api/penny-stocks',
        '/api/tech-stocks',
        '/api/etfs',
        '/api/watchlist',
        '/api/etf-stocks',
    ]

    @pytest.mark.parametrize('url', ENDPOINTS)
    def test_returns_200(self, client, url):
        resp = client.get(url)
        assert resp.status_code == 200

    @pytest.mark.parametrize('url', ENDPOINTS)
    def test_returns_json(self, client, url):
        resp = client.get(url)
        assert resp.content_type.startswith('application/json')

    @pytest.mark.parametrize('url', [
        '/api/stocks', '/api/penny-stocks', '/api/tech-stocks', '/api/etfs',
    ])
    def test_response_has_required_keys(self, client, url):
        body = _json(client.get(url))
        assert 'status' in body
        assert 'count' in body
        assert 'data' in body
        assert isinstance(body['data'], list)

    def test_watchlist_has_status_and_data(self, client):
        body = _json(client.get('/api/watchlist'))
        assert 'status' in body
        assert 'data' in body

    def test_etf_stocks_has_status_and_data(self, client):
        body = _json(client.get('/api/etf-stocks'))
        assert 'status' in body
        assert 'data' in body


# ── /api/status ───────────────────────────────────────────────────────────────

class TestStatusEndpoint:
    def test_returns_200(self, client):
        assert client.get('/api/status').status_code == 200

    def test_has_all_dataset_keys(self, client):
        body = _json(client.get('/api/status'))
        for key in ('sp500', 'penny', 'tech', 'etf'):
            assert key in body

    def test_each_dataset_has_status_and_count(self, client):
        body = _json(client.get('/api/status'))
        for key in ('sp500', 'penny', 'tech', 'etf'):
            assert 'status' in body[key]
            assert 'count' in body[key]


# ── /api/refresh endpoints ────────────────────────────────────────────────────

class TestRefreshEndpoints:
    @pytest.mark.parametrize('url', ['/api/refresh', '/api/refresh/1m', '/api/refresh/10y'])
    def test_returns_200(self, client, url):
        assert client.get(url).status_code == 200

    @pytest.mark.parametrize('url', ['/api/refresh', '/api/refresh/1m', '/api/refresh/10y'])
    def test_returns_started_status(self, client, url):
        body = _json(client.get(url))
        # 'already_loading' is also valid when a background refresh is in progress
        assert body.get('status') in ('started', 'already_loading')

    @pytest.mark.parametrize('url', [
        '/api/watchlist/refresh',
        '/api/etf-stocks/refresh',
    ])
    def test_list_refresh_returns_200(self, client, url):
        assert client.get(url).status_code == 200


# ── POST /api/watchlist/add ───────────────────────────────────────────────────

class TestWatchlistAdd:
    def test_missing_body_returns_400(self, client):
        resp = client.post('/api/watchlist/add',
                           data='{}', content_type='application/json')
        assert resp.status_code == 400

    def test_empty_symbol_returns_400(self, client):
        resp = client.post('/api/watchlist/add',
                           json={'symbol': ''})
        assert resp.status_code == 400

    def test_empty_symbol_error_message(self, client):
        body = _json(client.post('/api/watchlist/add', json={'symbol': ''}))
        assert body['ok'] is False
        assert 'error' in body

    def test_valid_symbol_added_successfully(self, client):
        with patch('server.fetch_watch_stock', return_value=_mock_stock('MSFT')):
            resp = client.post('/api/watchlist/add', json={'symbol': 'MSFT'})
        assert resp.status_code == 200
        body = _json(resp)
        assert body['ok'] is True
        assert body['stock']['symbol'] == 'MSFT'

    def test_unknown_symbol_returns_404(self, client):
        with patch('server.fetch_watch_stock', return_value=None):
            resp = client.post('/api/watchlist/add', json={'symbol': 'XXXXXX'})
        assert resp.status_code == 404

    def test_duplicate_symbol_returns_error(self, client):
        with patch('server.fetch_watch_stock', return_value=_mock_stock('DUPL')), \
             patch('server._load_watchlist', return_value=['DUPL']):
            resp = client.post('/api/watchlist/add', json={'symbol': 'DUPL'})
        body = _json(resp)
        assert body['ok'] is False
        assert 'already' in body['error'].lower()


# ── DELETE /api/watchlist/remove ─────────────────────────────────────────────

class TestWatchlistRemove:
    def test_remove_nonexistent_returns_404(self, client):
        with patch('server._load_watchlist', return_value=[]):
            resp = client.delete('/api/watchlist/remove/ZZZZ')
        assert resp.status_code == 404

    def test_remove_existing_returns_ok(self, client):
        with patch('server._load_watchlist', return_value=['AAPL']), \
             patch('server._save_watchlist_symbols'):
            resp = client.delete('/api/watchlist/remove/AAPL')
        body = _json(resp)
        assert body['ok'] is True


# ── POST /api/etf-stocks/add ──────────────────────────────────────────────────

class TestEtfStocksAdd:
    def test_missing_symbol_returns_400(self, client):
        resp = client.post('/api/etf-stocks/add', json={'symbol': ''})
        assert resp.status_code == 400

    def test_valid_symbol_added(self, client):
        with patch('server.fetch_watch_stock', return_value=_mock_stock('VOO')), \
             patch('server._load_etf_stocks_symbols', return_value=[]), \
             patch('server._save_etf_stocks_symbols'):
            resp = client.post('/api/etf-stocks/add', json={'symbol': 'VOO'})
        assert resp.status_code == 200
        body = _json(resp)
        assert body['ok'] is True

    def test_unknown_symbol_returns_404(self, client):
        with patch('server.fetch_watch_stock', return_value=None):
            resp = client.post('/api/etf-stocks/add', json={'symbol': 'XXXXXX'})
        assert resp.status_code == 404


# ── DELETE /api/etf-stocks/remove ────────────────────────────────────────────

class TestEtfStocksRemove:
    def test_remove_nonexistent_returns_404(self, client):
        with patch('server._load_etf_stocks_symbols', return_value=[]):
            resp = client.delete('/api/etf-stocks/remove/SPY')
        assert resp.status_code == 404

    def test_remove_existing_returns_ok(self, client):
        with patch('server._load_etf_stocks_symbols', return_value=['SPY']), \
             patch('server._save_etf_stocks_symbols'):
            resp = client.delete('/api/etf-stocks/remove/SPY')
        body = _json(resp)
        assert body['ok'] is True


# ── /api/search ───────────────────────────────────────────────────────────────

class TestSearch:
    def test_empty_query_returns_not_ok(self, client):
        resp = client.get('/api/search?q=')
        body = _json(resp)
        assert body['ok'] is False

    def test_valid_symbol_returns_ok(self, client):
        mock_info = {'shortName': 'Apple Inc.', 'sector': 'Technology'}
        with patch('yfinance.Ticker') as mock_ticker:
            mock_ticker.return_value.info = mock_info
            resp = client.get('/api/search?q=AAPL')
        body = _json(resp)
        assert body['ok'] is True
        assert body['name'] == 'Apple Inc.'

    def test_unknown_symbol_returns_not_ok(self, client):
        with patch('yfinance.Ticker') as mock_ticker:
            mock_ticker.return_value.info = {}
            resp = client.get('/api/search?q=XXXXXX')
        body = _json(resp)
        assert body['ok'] is False


# ── 404 for unknown routes ────────────────────────────────────────────────────

class TestNotFound:
    def test_unknown_route_returns_404(self, client):
        assert client.get('/api/nonexistent').status_code == 404
