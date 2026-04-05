"""Shared fixtures for all test modules."""
import sys
import os

# Make sure the project root is on the path so tests can import server.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd
from datetime import datetime, timedelta


@pytest.fixture
def client():
    """Flask test client with a clean database for each test."""
    from server import app
    import db as db_module

    app.config['TESTING'] = True

    # Drop and recreate all auth tables so each test starts with an empty DB.
    # This is necessary because the SQLite file persists between test runs.
    db_module.Base.metadata.drop_all(db_module.engine)
    db_module.Base.metadata.create_all(db_module.engine)

    with app.test_client() as c:
        yield c


def make_series(prices, freq='B'):
    """
    Build a pandas Series with a DatetimeIndex — matches what yfinance returns.
    freq='B'  → business-day index  (1-year daily data)
    freq='ME' → month-end index     (10-year / max monthly data)
    """
    end = datetime(2025, 1, 31)
    idx = pd.date_range(end=end, periods=len(prices), freq=freq)
    return pd.Series([float(p) for p in prices], index=idx)
