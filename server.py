"""
StockPerformer - S&P 500 Dashboard Backend
Run: python server.py  →  open http://localhost:5000

Cache policy:
  - 1-month daily chart   → refreshed every 24 hours (or if missing)
  - 10-year monthly chart → refreshed every 10 days  (or if missing)
  - Penny stocks          → same rules, stored in penny_data_cache.json
  - Market cap            → fetched with 10-year pass, cached 10 days
"""

from flask import Flask, jsonify, send_from_directory
import yfinance as yf
import pandas as pd
import requests as req
import json, os, threading, time
from datetime import datetime, timedelta
from io import StringIO

app    = Flask(__name__)
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE     = os.path.join(BASE_DIR, 'stock_data_cache.json')
PENNY_CACHE    = os.path.join(BASE_DIR, 'penny_data_cache.json')

MAX_AGE_1M_H   = 24          # hours before re-fetching 1-month data
MAX_AGE_10Y_D  = 10          # days  before re-fetching 10-year data
PENNY_TOP_N         = 500         # max penny stocks to keep
PENNY_CACHE_VERSION = 2           # bump when data schema changes to force re-fetch

TECH_CACHE          = os.path.join(BASE_DIR, 'tech_data_cache.json')
TECH_CACHE_VERSION  = 1

WATCHLIST_FILE      = os.path.join(BASE_DIR, 'watchlist.json')
ETF_STOCKS_FILE     = os.path.join(BASE_DIR, 'etf_stocks.json')

ETF_CACHE           = os.path.join(BASE_DIR, 'etf_data_cache.json')
ETF_CACHE_VERSION   = 2

# ── ETF universe ───────────────────────────────────────────────────────────
# ~250 major US-listed ETFs across providers and asset classes
ETF_LIST = list(dict.fromkeys([
    # ── Vanguard ──
    'VOO','VTI','VEA','VWO','BND','VXUS','VGT','VHT','VYM','VNQ',
    'VO','VB','VV','VDE','VFH','VIS','VAW','VPU','VCR','VDC',
    'VOOG','VOOV','VONE','VTHR','VTWG','VTWO','VYMI','VIGI','VCIT',
    'VCSH','VGIT','VGSH','VGLT','VMBS','VTIP','BNDX','VNQI',
    'VT','VXUS','VIGI','VWOB','VIG','VIGI',
    # ── iShares (BlackRock) ──
    'IVV','AGG','EFA','EEM','GLD','TLT','LQD','HYG','IWM','IJH',
    'IJR','IEFA','IEMG','ITOT','IAU','SLV','MBB','GOVT','USIG',
    'IGSB','IGIB','LQDT','TIP','EMB','SHYG','JNK','FLOT',
    'IWF','IWD','IWB','IWN','IWO','IWS','IWP','IWR','IWC',
    'IVW','IVE','IWL','IJT','IJS','IJJ','INTF','QUAL','SIZE','USMV',
    'MTUM','VLUE','MINV','ACWI','EWJ','EWZ','EWC','EWG','EWU',
    'EWH','EWS','EWA','EWQ','EWL','EWT','EWY','EWN','EWI','EWP',
    'SOXX','IGV','ITB','XHB','IBB','IHI','IYW','IYF','IYH','IYE',
    'IYR','IYZ','IYC','IYJ','IYK','IYM','IYG',
    # ── SPDR (State Street) ──
    'SPY','MDY','SDY','GLD','SLV','DIA','XLF','XLK','XLE','XLU',
    'XLI','XLV','XLP','XLB','XLRE','XLC','XLY','KRE','KBE','KIE',
    'XOP','XME','XHB','XRT','XBI','XPH','SPDW','SPEM','SPSM',
    'SPLG','SPYG','SPYV','RSP','GLDM','SPTS','SPTI','SPTL',
    # ── Invesco ──
    'QQQ','QQQM','RSP','SPHQ','SPLV','SPMO','PDN','IVOG','IVOV',
    'IVOO','PGX','PFF','BKLN','PHB','PCEF','PDBC','DBB','DBO',
    'DBC','DBA','DJP','GSG',
    # ── Schwab ──
    'SCHB','SCHD','SCHA','SCHF','SCHX','SCHZ','SCHG','SCHV','SCHE',
    'SCHH','SCHP','SCHR','SCHI','SCHQ','SCHM','SCHC',
    # ── ARK Invest ──
    'ARKK','ARKW','ARKG','ARKF','ARKQ','ARKX','IZRL',
    # ── ProShares (leveraged/inverse) ──
    'TQQQ','SQQQ','SSO','SDS','UPRO','SPXS','SPXU','QID','QLD',
    'TBT','TBF','PSQ','SH','DOG','RWM','TWM','TNA','TZA','UVXY',
    'VIXY','SVXY',
    # ── Sector & Thematic ──
    'BOTZ','ROBO','AIQ','IRBO','WCLD','CLOU','SKYY','IGN',
    'FINX','ARKF','CIBR','HACK','BUG','ETHO','ICLN','QCLN',
    'TAN','FAN','CNRG','LIT','REMX','COPX','GDX','GDXJ','SIL',
    'RING','PICK','MOO','WOOD','XES','OIH','DRIP','GUSH',
    # ── Fixed Income & Bonds ──
    'BSV','BIV','BLV','VCLT','VMLUX','FBND','FBNX',
    'NEAR','SHY','IEI','IEF','TLH','SCHO','SCHR','SCHQ',
    'SPAB','SPSB','SPIB','SPLB','SPTM','FLRN','USFR',
    # ── Dividend & Income ──
    'DVY','HDV','SDY','NOBL','DGRO','DGRW','RDIV','PEY',
    'FDL','FVD','DTD','DTN','DLN','DTH','VYMI',
    # ── Real Estate ──
    'VNQ','IYR','SCHH','USRT','REM','MORT','KBWY',
    # ── International & EM ──
    'MCHI','KWEB','INDA','VPL','VGK','VEUR','EZU','FEZ','EWZ',
    'RSX','TUR','EPI','EIDO','THD','EWM','EPOL','GXG','ARGT',
    'FM','AFK','NGE','EZA','EGPT',
    # ── Multi-Asset & Other ──
    'AOR','AOM','AOA','AOK','GAL','MDIV','YYY','PCEF',
    # ── Berkshire Hathaway (conglomerate, often grouped with funds) ──
    'BRK-B','BRK-A',
]))

# Curated tech watchlist — mega-cap, large-cap, and notable mid-cap tech
TECH_STOCKS = [
    # Mega-cap / FAANG+
    'AAPL','MSFT','NVDA','GOOGL','GOOG','AMZN','META','TSLA','AVGO','ORCL',
    # Semiconductors
    'AMD','INTC','QCOM','TXN','MU','AMAT','LRCX','KLAC','MRVL','ARM','SMCI','ON',
    # Cloud / Enterprise Software
    'CRM','ADBE','NOW','INTU','SAP','WDAY','SNOW','DDOG','MDB','TEAM','ZS','PANW',
    # Consumer Tech / E-commerce
    'NFLX','SPOT','SHOP','PINS','SNAP','UBER','LYFT','ABNB','DASH',
    # Fintech / Payments
    'PYPL','SQ','V','MA','COIN','AFRM','HOOD',
    # Networking / Infrastructure
    'CSCO','NET','ANET','CRWD','FTNT',
    # Hardware / Devices
    'HPQ','DELL','STX','WDC','PSTG',
    # AI / Emerging Tech
    'PLTR','AI','PATH','BBAI','SOUN','IREN',
    # Chinese Tech (US-listed)
    'BABA','JD','PDD','BIDU','NIO',
]

# ── In-memory state ────────────────────────────────────────────────────────
_EMPTY = dict(data=[], time=None, status='idle',
              last_1m_update=None, last_10y_update=None)
_sp500  = dict(**_EMPTY)
_penny  = dict(**_EMPTY)
_tech   = dict(**_EMPTY)
_etf        = dict(**_EMPTY)
_etf_stocks = dict(**_EMPTY)
_watch      = dict(**_EMPTY)
_lock   = threading.Lock()

# ── Penny stock candidate universe ─────────────────────────────────────────
# ~200 actively-traded US-listed stocks historically at or near penny range.
# We download all, filter to current price < $5, rank by 1-mo %, keep top 100.
PENNY_CANDIDATES = list(dict.fromkeys([
    # Biotech / Pharma
    'SNDL','OCGN','NOVN','ATOS','MNMD','SEEL','PBTS','RDHL','QLGN','ADTX',
    'AGRX','AKBA','APVO','APTX','AQST','ATAI','AVTX','AVXL','BLCM','CDTX',
    'CEMI','CETX','CFRX','CLRB','CMRX','CTXR','DARE','DBVT','DFFN','EDSA',
    'EVFM','EVOK','FBIO','FBRX','FDMT','FMTX','FOLD','GERN','GHSI','GNPX',
    'IMMP','INAB','VXRT','NRXP','LMDX','IMTX','OPTN','GTHX','ENLV','HRTX',
    'ALDX','ZYNE','ATNF','NRBO','PMVP','CRBP','FRLN','CTIC','AGIO','SRRK',
    # Crypto Mining
    'MARA','RIOT','SOS','BTBT','HUT','BITF','CLSK','CIFR','WULF','IREN',
    'BTDR','CORZ','DGHI','HIVE',
    # EV / Clean Energy / SPAC legacy
    'GOEV','MULN','FFIE','CENN','ARVL','WKHS','NKLA','IDEX','GEVO','CLNE',
    'AMPE','FCEL','BLNK','EVGO','HYZN','SOLO','AYRO','NUVVE','PTRA','ELMS',
    'LOTZ','XPEV','LI','NIO',
    # Cannabis
    'ACB','CGC','TLRY','HEXO','CRON','OGI','APHA','GRWG','KERN','VEXT',
    'PLNHF','CURLF','TCNNF','HRVSF',
    # Technology / Small Cap
    'MVIS','GFAI','SOPA','UAVS','AIXI','AGFY','ATIF','BIMI','SIFY','WISA',
    'CPSL','DGLY','NOK','KPLT','PROG','BBIG','ATER','PHUN','XELA','FUBO',
    'SPCE','BNGO','EYES','CODA','FNKO','SKLZ','WISH','PSFE','OPEN','IRNT',
    'GREE','CLOV','EXPR','NAKD','WKSP','ATIP','BARK','DOGZ','TTCF','MARK',
    'COMS','NTRB','IDEANOMICS','GFAI','TPVG','VERB','SOPA','AITX','SWVL',
    # Shipping / Dry Bulk
    'RIG','SDRL','INDO','TELL','IMPP','SHIP','TOPS','FREE','EDRY','EGLE',
    'GOGL','GASS','TRMD','ESEA','CTRM','SINO','PSHG','GLBS','DCIX','DSSI',
    'GNSS','GNK','SBLK','SALT','CMRE',
    # Mining / Precious Metals
    'AG','HL','GPL','GORO','EXK','CDE','MAG','USAS','SBSW','GATO','AUMN',
    'SILV','LAAC','PAAS','FFOX','MGLD',
    # Oil & Gas
    'SWN','NOG','SD','BATL','HPK','TELL','SM','CPE','REI','PTEN',
    # Telecom / Misc
    'NOK','SIFY','GSAT','IDT','LWAY','COMS','LIQT',
]))

# ── Disk cache helpers ─────────────────────────────────────────────────────

def _load(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f'[WARN] Could not read {path}: {e}')
        return None

def _save(path, payload):
    try:
        with open(path, 'w') as f:
            json.dump(payload, f)
        print(f'[INFO] Saved {len(payload.get("data", []))} records → {os.path.basename(path)}')
    except Exception as e:
        print(f'[WARN] Could not save {path}: {e}')

def _age_h(ts):
    if not ts:
        return float('inf')
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 3600
    except Exception:
        return float('inf')

def _stale_1m(d):  return _age_h(d.get('last_1m_update')  if d else None) >= MAX_AGE_1M_H
def _stale_10y(d): return _age_h(d.get('last_10y_update') if d else None) >= MAX_AGE_10Y_D * 24

# ── S&P 500 ticker list ────────────────────────────────────────────────────

def get_sp500_tickers():
    try:
        url     = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp    = req.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        df = pd.read_html(StringIO(resp.text))[0]
        return [{'symbol': str(r['Symbol']).strip(),
                 'name':   str(r['Security']).strip(),
                 'sector': str(r['GICS Sector']).strip()}
                for _, r in df.iterrows()]
    except Exception as e:
        print(f'[ERROR] S&P 500 ticker list: {e}')
        return []

# ── Batch OHLCV downloader ─────────────────────────────────────────────────

def download_closes(symbols, period, interval, batch_size=100):
    """Return {yf_symbol: pd.Series of close prices}."""
    out, total = {}, (len(symbols) + batch_size - 1) // batch_size
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        bn    = i // batch_size + 1
        print(f'[INFO]   dl batch {bn}/{total}  period={period} interval={interval}')
        try:
            raw = yf.download(batch, period=period, interval=interval,
                              group_by='ticker', auto_adjust=True,
                              progress=False, threads=True)
            for sym in batch:
                try:
                    if (sym, 'Close') in raw.columns:
                        cl = raw[(sym, 'Close')]
                    elif 'Close' in raw.columns:
                        cl = raw['Close']
                    else:
                        cl = raw[sym]['Close']
                    cl = cl.dropna()
                    if len(cl): out[sym] = cl
                except Exception: pass
        except Exception as e:
            print(f'[WARN]   batch {bn} error: {e}')
        time.sleep(0.3)
    return out

# ── Market-cap batch fetch (via yfinance fast_info) ───────────────────────

def fetch_market_caps(symbols, batch_size=50):
    """Return {symbol: market_cap_int} using yfinance fast_info."""
    caps = {}
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        try:
            tickers = yf.Tickers(' '.join(batch))
            for sym in batch:
                try:
                    mc = tickers.tickers[sym].fast_info.market_cap
                    if mc:
                        caps[sym] = int(mc)
                except Exception:
                    pass
        except Exception as e:
            print(f'[WARN] market-cap batch error: {e}')
        time.sleep(0.3)
    return caps

def fetch_names_sectors(symbols, batch_size=50):
    """Return {symbol: {name, sector}} using yfinance fast_info / info."""
    result = {}
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        try:
            tickers = yf.Tickers(' '.join(batch))
            for sym in batch:
                try:
                    fi = tickers.tickers[sym].fast_info
                    info = tickers.tickers[sym].info
                    result[sym] = {
                        'name':   info.get('shortName') or sym,
                        'sector': info.get('sector') or 'Unknown',
                    }
                except Exception:
                    pass
        except Exception as e:
            print(f'[WARN] name/sector batch error: {e}')
        time.sleep(0.3)
    return result

# ── Per-stock field builders ───────────────────────────────────────────────

def _1m_fields(cl):
    prices = [round(float(p), 2) for p in cl.tolist()]
    dates  = [str(d.date()) for d in cl.index]
    if not prices: return None
    cur, op, prev = prices[-1], prices[0], prices[-2] if len(prices) > 1 else prices[-1]
    dc = round(cur - prev, 2)
    return dict(price=cur,
                day_change=dc,
                day_pct=round(dc / prev * 100 if prev else 0, 2),
                month_change=round(cur - op, 2),
                month_pct=round((cur - op) / op * 100 if op else 0, 2),
                prices=prices, dates=dates)

def _10y_fields(cl):
    p10 = [round(float(p), 2) for p in cl.tolist()]
    d10 = [str(d.date()) for d in cl.index]
    yp  = round((p10[-1] - p10[0]) / p10[0] * 100, 2) if len(p10) >= 2 and p10[0] else None
    p5s = p10[-60] if len(p10) >= 60 else (p10[0] if p10 else None)
    p5y = round((p10[-1] - p5s) / p5s * 100, 2) if p5s and p10 else None
    return dict(prices_10y=p10, dates_10y=d10, year_pct=yp, pct_5y=p5y)

def _max_fields(cl):
    """Build max-history (up to 30+ years) monthly fields for ETF charts."""
    all_p = [round(float(p), 2) for p in cl.tolist()]
    all_d = [str(d.date()) for d in cl.index]
    if not all_p:
        return dict(prices_10y=[], dates_10y=[], year_pct=None, pct_5y=None,
                    prices_30y=[], dates_30y=[], pct_30y=None)
    # 10y = last 120 monthly bars
    p10 = all_p[-120:]; d10 = all_d[-120:]
    yp  = round((p10[-1] - p10[0]) / p10[0] * 100, 2) if len(p10) >= 2 and p10[0] else None
    p5s = p10[-60] if len(p10) >= 60 else p10[0]
    p5y = round((all_p[-1] - p5s) / p5s * 100, 2) if p5s else None
    # 30y / max = all available monthly bars
    p30y = round((all_p[-1] - all_p[0]) / all_p[0] * 100, 2) if len(all_p) >= 2 and all_p[0] else None
    return dict(prices_10y=p10, dates_10y=d10, year_pct=yp, pct_5y=p5y,
                prices_30y=all_p, dates_30y=all_d, pct_30y=p30y)

def _penny_time_fields(cl):
    """Build multi-period growth fields from 1-year daily close series."""
    prices = [round(float(p), 2) for p in cl.tolist()]
    dates  = [str(d.date()) for d in cl.index]
    if not prices:
        return None
    cur  = prices[-1]
    prev = prices[-2] if len(prices) > 1 else cur
    dc   = round(cur - prev, 2)

    def pct_n(n):
        """% change over the last n trading days."""
        if len(prices) <= n:
            return None
        base = prices[-(n + 1)]
        return round((cur - base) / base * 100, 2) if base else None

    idx_1mo = max(0, len(prices) - 22)
    op = prices[idx_1mo]
    return dict(
        price        = cur,
        day_change   = dc,
        day_pct      = round(dc / prev * 100 if prev else 0, 2),
        month_change = round(cur - op, 2),
        month_pct    = round((cur - op) / op * 100 if op else 0, 2),
        pct_5d       = pct_n(5),
        pct_15d      = pct_n(15),
        pct_45d      = pct_n(45),
        pct_3mo      = pct_n(65),
        pct_1y       = round((cur - prices[0]) / prices[0] * 100, 2) if prices[0] else None,
        prices       = prices[-22:],   # last ~1 month for sparkline
        dates        = dates[-22:],
        prices_1y    = prices,         # full 1-year daily
        dates_1y     = dates,
    )

# ── S&P 500 smart refresh ──────────────────────────────────────────────────

def refresh_sp500(force_1m=False, force_10y=False):
    global _sp500
    with _lock: _sp500['status'] = 'loading'

    disk    = _load(CACHE_FILE)
    do_1m   = force_1m  or _stale_1m(disk)
    do_10y  = force_10y or _stale_10y(disk)

    # Ticker list
    if do_10y or not (disk and disk.get('tickers')):
        print('[INFO] Fetching S&P 500 ticker list…')
        tickers = get_sp500_tickers()
        if not tickers:
            with _lock: _sp500['status'] = 'error'
            return
    else:
        tickers = disk['tickers']
        print(f'[INFO] Using cached ticker list ({len(tickers)} symbols).')

    syms    = [t['symbol'].replace('.', '-') for t in tickers]
    smap    = {t['symbol'].replace('.', '-'): dict(s)
               for s in (disk['data'] if disk and disk.get('data') else [])
               for t in [next((x for x in tickers if x['symbol'] == s['symbol']), None)]
               if t} if disk else {}

    # Rebuild smap cleanly
    smap = {}
    if disk and disk.get('data'):
        for s in disk['data']:
            smap[s['symbol'].replace('.', '-')] = dict(s)

    ts_1m  = disk.get('last_1m_update')  if disk else None
    ts_10y = disk.get('last_10y_update') if disk else None

    # Pass 1 — 1-month
    if do_1m:
        print(f'[INFO] Updating 1-month data (age={_age_h(ts_1m):.1f}h)…')
        cl1m = download_closes(syms, '1mo', '1d')
        for t in tickers:
            sy = t['symbol'].replace('.', '-')
            if sy not in cl1m: continue
            f = _1m_fields(cl1m[sy])
            if not f: continue
            if sy not in smap:
                smap[sy] = {'symbol': t['symbol'], 'name': t['name'],
                            'sector': t['sector'], 'market_cap': None,
                            'prices_10y': [], 'dates_10y': [], 'year_pct': None}
            smap[sy].update(f)
        ts_1m = datetime.now().isoformat()
        print(f'[INFO] 1-month done ({len(cl1m)} stocks).')
    else:
        print(f'[INFO] 1-month fresh ({_age_h(ts_1m):.1f}h old) — skip.')

    # Pass 2 — 10-year + market cap
    if do_10y:
        print(f'[INFO] Updating 10-year data (age={_age_h(ts_10y)/24:.1f}d)…')
        cl10y = download_closes(syms, '10y', '1mo')
        for t in tickers:
            sy = t['symbol'].replace('.', '-')
            if sy not in cl10y or sy not in smap: continue
            smap[sy].update(_10y_fields(cl10y[sy]))

        print('[INFO] Fetching market caps…')
        # Use original symbols (not yf-formatted) for the quote API
        orig_syms = [t['symbol'] for t in tickers]
        caps = fetch_market_caps(orig_syms)
        for sym, mc in caps.items():
            sy = sym.replace('.', '-')
            if sy in smap:
                smap[sy]['market_cap'] = mc

        ts_10y = datetime.now().isoformat()
        print(f'[INFO] 10-year done. Market caps fetched: {len(caps)}.')
    else:
        print(f'[INFO] 10-year fresh ({_age_h(ts_10y)/24:.1f}d old) — skip.')

    stocks = [s for t in tickers
              for s in [smap.get(t['symbol'].replace('.', '-'))]
              if s and s.get('prices')]

    payload = dict(time=datetime.now().isoformat(),
                   last_1m_update=ts_1m, last_10y_update=ts_10y,
                   tickers=tickers, data=stocks)
    _save(CACHE_FILE, payload)

    with _lock:
        _sp500.update(data=stocks, time=payload['time'],
                      last_1m_update=ts_1m, last_10y_update=ts_10y,
                      status='ready')
    print(f'[INFO] S&P 500 refresh done — {len(stocks)} stocks.')

# ── Penny stocks refresh ───────────────────────────────────────────────────

def refresh_penny(force_1m=False, force_10y=False):
    global _penny
    with _lock: _penny['status'] = 'loading'

    disk = _load(PENNY_CACHE)

    # Force full refresh if cache schema is outdated
    if disk and disk.get('version', 1) < PENNY_CACHE_VERSION:
        print('[INFO] Penny cache version mismatch — forcing full refresh.')
        disk = None

    do_1m  = force_1m  or not disk or _stale_1m(disk)
    do_10y = force_10y or not disk or _stale_10y(disk)

    syms_yf = [s.replace('.', '-') for s in PENNY_CANDIDATES]
    smap    = {}
    if disk and disk.get('data'):
        for s in disk['data']:
            smap[s['symbol'].replace('.', '-')] = dict(s)

    ts_1m  = disk.get('last_1m_update')  if disk else None
    ts_10y = disk.get('last_10y_update') if disk else None

    if do_1m:
        print(f'[INFO] Penny: updating 1-year daily data ({len(syms_yf)} candidates)…')
        cl1y = download_closes(syms_yf, '1y', '1d')
        for raw_sym, sym_yf in zip(PENNY_CANDIDATES, syms_yf):
            if sym_yf not in cl1y: continue
            f = _penny_time_fields(cl1y[sym_yf])
            if not f or f['price'] >= 25.0: continue   # allow up to $25
            if sym_yf not in smap:
                smap[sym_yf] = {'symbol': raw_sym, 'name': raw_sym,
                                'sector': 'Unknown', 'market_cap': None,
                                'prices_10y': [], 'dates_10y': [],
                                'year_pct': None, 'pct_5y': None}
            smap[sym_yf].update(f)
        # Fetch market caps right after 1m so they're always populated
        print('[INFO] Penny: fetching market caps...')
        active_orig = [smap[sy]['symbol'] for sy in smap if smap[sy].get('prices')]
        caps = fetch_market_caps(active_orig)
        for sym_yf, s in smap.items():
            mc = caps.get(s['symbol'])
            if mc: s['market_cap'] = mc

        ts_1m = datetime.now().isoformat()
        print(f'[INFO] Penny 1-year done ({len(smap)} candidates under $25).')
    else:
        print(f'[INFO] Penny 1-year fresh — skip.')

    if do_10y:
        print('[INFO] Penny: updating 10-year data...')
        active_syms = [sy for sy, s in smap.items() if s.get('prices')]
        cl10y = download_closes(active_syms, '10y', '1mo')
        for sy, s in smap.items():
            if sy in cl10y:
                s.update(_10y_fields(cl10y[sy]))   # includes pct_5y

        ts_10y = datetime.now().isoformat()
        print('[INFO] Penny 10-year done.')
    else:
        print('[INFO] Penny 10-year fresh — skip.')

    # Keep all stocks under $25 sorted by 1-mo %, capped at PENNY_TOP_N
    stocks = sorted(
        [s for s in smap.values() if s.get('prices') and s.get('price', 99) < 25.0],
        key=lambda s: s.get('month_pct', -999),
        reverse=True
    )[:PENNY_TOP_N]

    # Fetch readable names for stocks still using ticker as name
    unknown = [s['symbol'] for s in stocks if s['name'] == s['symbol']]
    if unknown:
        print(f'[INFO] Penny: fetching names/sectors for {len(unknown)} symbols...')
        ns = fetch_names_sectors(unknown)
        for s in stocks:
            if s['symbol'] in ns:
                s['name']   = ns[s['symbol']]['name']
                s['sector'] = ns[s['symbol']]['sector']

    payload = dict(version=PENNY_CACHE_VERSION,
                   time=datetime.now().isoformat(),
                   last_1m_update=ts_1m, last_10y_update=ts_10y, data=stocks)
    _save(PENNY_CACHE, payload)

    with _lock:
        _penny.update(data=stocks, time=payload['time'],
                      last_1m_update=ts_1m, last_10y_update=ts_10y,
                      status='ready')
    print(f'[INFO] Penny refresh done — {len(stocks)} stocks under $25.')

# ── Tech stocks refresh ────────────────────────────────────────────────────

def refresh_tech(force_1m=False, force_10y=False):
    global _tech
    with _lock: _tech['status'] = 'loading'

    disk  = _load(TECH_CACHE)
    if disk and disk.get('version', 1) < TECH_CACHE_VERSION:
        disk = None

    do_1m  = force_1m  or not disk or _stale_1m(disk)
    do_10y = force_10y or not disk or _stale_10y(disk)

    syms_yf = [s.replace('.', '-') for s in TECH_STOCKS]
    smap    = {}
    if disk and disk.get('data'):
        for s in disk['data']:
            smap[s['symbol'].replace('.', '-')] = dict(s)

    ts_1m  = disk.get('last_1m_update')  if disk else None
    ts_10y = disk.get('last_10y_update') if disk else None

    if do_1m:
        print(f'[INFO] Tech: updating 1-year daily data ({len(syms_yf)} stocks)...')
        cl1y = download_closes(syms_yf, '1y', '1d')
        for raw_sym, sym_yf in zip(TECH_STOCKS, syms_yf):
            if sym_yf not in cl1y: continue
            f = _penny_time_fields(cl1y[sym_yf])   # same multi-period logic
            if not f: continue
            if sym_yf not in smap:
                smap[sym_yf] = {'symbol': raw_sym, 'name': raw_sym,
                                'sector': 'Technology', 'market_cap': None,
                                'prices_10y': [], 'dates_10y': [],
                                'year_pct': None, 'pct_5y': None}
            smap[sym_yf].update(f)
        # Fetch market caps + names right after 1m
        print('[INFO] Tech: fetching market caps + names...')
        active_orig = [smap[sy]['symbol'] for sy in smap if smap[sy].get('prices')]
        caps = fetch_market_caps(active_orig)
        for sym_yf, s in smap.items():
            mc = caps.get(s['symbol'])
            if mc: s['market_cap'] = mc
        ns = fetch_names_sectors(active_orig)
        for sym_yf, s in smap.items():
            if s['symbol'] in ns:
                s['name']   = ns[s['symbol']]['name']
                s['sector'] = ns[s['symbol']]['sector']

        ts_1m = datetime.now().isoformat()
        print(f'[INFO] Tech 1-year done ({len(smap)} stocks).')
    else:
        print('[INFO] Tech 1-year fresh — skip.')

    if do_10y:
        print('[INFO] Tech: updating 10-year data...')
        active = [sy for sy, s in smap.items() if s.get('prices')]
        cl10y  = download_closes(active, '10y', '1mo')
        for sy, s in smap.items():
            if sy in cl10y:
                s.update(_10y_fields(cl10y[sy]))

        print('[INFO] Tech: fetching market caps + names...')
        orig = [s['symbol'] for s in smap.values()]
        caps = fetch_market_caps(orig)
        for sym_yf, s in smap.items():
            mc = caps.get(s['symbol'])
            if mc: s['market_cap'] = mc

        # Fetch readable names/sectors
        try:
            ns = fetch_names_sectors(orig)
            for sym_yf, s in smap.items():
                if s['symbol'] in ns:
                    s['name']   = ns[s['symbol']]['name']
                    s['sector'] = ns[s['symbol']]['sector']
        except Exception as e:
            print(f'[WARN] Tech name fetch: {e}')

        ts_10y = datetime.now().isoformat()
        print('[INFO] Tech 10-year done.')
    else:
        print('[INFO] Tech 10-year fresh — skip.')

    # Preserve original ordering from TECH_STOCKS list
    stocks = []
    for raw_sym in TECH_STOCKS:
        sym_yf = raw_sym.replace('.', '-')
        s = smap.get(sym_yf)
        if s and s.get('prices'):
            stocks.append(s)

    payload = dict(version=TECH_CACHE_VERSION,
                   time=datetime.now().isoformat(),
                   last_1m_update=ts_1m, last_10y_update=ts_10y, data=stocks)
    _save(TECH_CACHE, payload)

    with _lock:
        _tech.update(data=stocks, time=payload['time'],
                     last_1m_update=ts_1m, last_10y_update=ts_10y,
                     status='ready')
    print(f'[INFO] Tech refresh done — {len(stocks)} stocks.')

# ── ETF refresh ───────────────────────────────────────────────────────────

def refresh_etf(force_1m=False, force_10y=False):
    global _etf
    with _lock: _etf['status'] = 'loading'

    disk = _load(ETF_CACHE)
    if disk and disk.get('version', 1) < ETF_CACHE_VERSION:
        disk = None

    do_1m  = force_1m  or not disk or _stale_1m(disk)
    do_10y = force_10y or not disk or _stale_10y(disk)

    syms_yf = [s.replace('.', '-') for s in ETF_LIST]
    smap    = {}
    if disk and disk.get('data'):
        for s in disk['data']:
            smap[s['symbol'].replace('.', '-')] = dict(s)

    ts_1m  = disk.get('last_1m_update')  if disk else None
    ts_10y = disk.get('last_10y_update') if disk else None

    if do_1m:
        print(f'[INFO] ETF: updating 1-year daily data ({len(syms_yf)} ETFs)...')
        cl1y = download_closes(syms_yf, '1y', '1d')
        for raw_sym, sym_yf in zip(ETF_LIST, syms_yf):
            if sym_yf not in cl1y: continue
            f = _penny_time_fields(cl1y[sym_yf])
            if not f: continue
            if sym_yf not in smap:
                smap[sym_yf] = {'symbol': raw_sym, 'name': raw_sym,
                                'sector': 'ETF', 'market_cap': None,
                                'prices_10y': [], 'dates_10y': [],
                                'prices_30y': [], 'dates_30y': [],
                                'year_pct': None, 'pct_5y': None, 'pct_30y': None}
            smap[sym_yf].update(f)

        # Fetch names, categories and AUM
        print('[INFO] ETF: fetching names/categories...')
        active_orig = [smap[sy]['symbol'] for sy in smap if smap[sy].get('prices')]
        for i in range(0, len(active_orig), 50):
            batch = active_orig[i:i + 50]
            try:
                tickers_obj = yf.Tickers(' '.join([s.replace('.', '-') for s in batch]))
                for sym in batch:
                    sym_yf = sym.replace('.', '-')
                    if sym_yf not in smap: continue
                    try:
                        info = tickers_obj.tickers[sym_yf].info
                        fi   = tickers_obj.tickers[sym_yf].fast_info
                        smap[sym_yf]['name']   = (info.get('shortName') or
                                                   info.get('longName') or sym)
                        smap[sym_yf]['sector'] = (info.get('category') or
                                                   info.get('sector') or 'ETF')
                        mc = None
                        try: mc = int(fi.market_cap or 0) or None
                        except Exception: pass
                        if mc: smap[sym_yf]['market_cap'] = mc
                    except Exception:
                        pass
            except Exception as e:
                print(f'[WARN] ETF name batch error: {e}')
            time.sleep(0.3)

        ts_1m = datetime.now().isoformat()
        print(f'[INFO] ETF 1-year done ({len(smap)} ETFs).')
    else:
        print('[INFO] ETF 1-year fresh — skip.')

    if do_10y:
        print('[INFO] ETF: updating max-history (30yr) data...')
        active = [sy for sy, s in smap.items() if s.get('prices')]
        clmax  = download_closes(active, 'max', '1mo')
        for sy, s in smap.items():
            if sy in clmax:
                s.update(_max_fields(clmax[sy]))
        ts_10y = datetime.now().isoformat()
        print('[INFO] ETF max-history done.')
    else:
        print('[INFO] ETF max-history fresh — skip.')

    # Preserve original ordering
    stocks = []
    for raw_sym in ETF_LIST:
        sym_yf = raw_sym.replace('.', '-')
        s = smap.get(sym_yf)
        if s and s.get('prices'):
            stocks.append(s)

    payload = dict(version=ETF_CACHE_VERSION,
                   time=datetime.now().isoformat(),
                   last_1m_update=ts_1m, last_10y_update=ts_10y, data=stocks)
    _save(ETF_CACHE, payload)

    with _lock:
        _etf.update(data=stocks, time=payload['time'],
                    last_1m_update=ts_1m, last_10y_update=ts_10y,
                    status='ready')
    print(f'[INFO] ETF refresh done — {len(stocks)} ETFs.')

# ── Watchlist ──────────────────────────────────────────────────────────────

def _load_watchlist():
    """Load watchlist symbols from disk. Returns list of symbol strings."""
    d = _load(WATCHLIST_FILE)
    if d and isinstance(d.get('symbols'), list):
        return d['symbols']
    return []

def _save_watchlist_symbols(symbols):
    try:
        with open(WATCHLIST_FILE, 'w') as f:
            json.dump({'symbols': symbols}, f)
    except Exception as e:
        print(f'[WARN] Could not save watchlist: {e}')

def _safe(v):
    """Convert NaN / Infinity to None so jsonify never crashes."""
    import math
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, dict):
        return {k: _safe(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_safe(i) for i in v]
    return v

def fetch_watch_stock(symbol):
    """Fetch full data for a single symbol. Returns stock dict or None."""
    sym_yf = symbol.replace('.', '-').upper()
    try:
        cl1y = download_closes([sym_yf], '1y', '1d')
        if sym_yf not in cl1y:
            return None
        f = _penny_time_fields(cl1y[sym_yf])
        if not f:
            return None

        cl10y_map = download_closes([sym_yf], '10y', '1mo')
        f10y = _10y_fields(cl10y_map[sym_yf]) if sym_yf in cl10y_map else \
               dict(prices_10y=[], dates_10y=[], year_pct=None, pct_5y=None)

        ticker = yf.Ticker(sym_yf)
        info   = ticker.info
        mc     = None
        try: mc = int(ticker.fast_info.market_cap or 0) or None
        except Exception: pass

        # ETFs often use 'longName' and have no sector — fall back gracefully
        name   = (info.get('shortName') or info.get('longName') or symbol.upper())
        sector = (info.get('category') or info.get('sector') or
                  info.get('fundFamily') or 'ETF/Fund')

        stock = {
            'symbol':     symbol.upper(),
            'name':       str(name),
            'sector':     str(sector),
            'market_cap': mc,
            'added_at':   datetime.now().isoformat(),
        }
        stock.update(f)
        stock.update(f10y)
        all_cl = cl1y[sym_yf]
        stock['prices_1y'] = [round(float(p), 2) for p in all_cl.tolist()]
        stock['dates_1y']  = [str(d.date()) for d in all_cl.index]
        return _safe(stock)   # strip any NaN/Inf before JSON serialisation
    except Exception as e:
        print(f'[WARN] fetch_watch_stock({symbol}): {e}')
        return None

def refresh_watchlist():
    """Re-fetch price data for all watchlist symbols."""
    global _watch
    symbols = _load_watchlist()
    with _lock:
        _watch['status'] = 'loading'
    stocks = []
    for sym in symbols:
        s = fetch_watch_stock(sym)
        if s:
            stocks.append(s)
    with _lock:
        _watch['data']   = stocks
        _watch['time']   = datetime.now().isoformat()
        _watch['status'] = 'ready'
    print(f'[INFO] Watchlist refreshed — {len(stocks)} stocks.')

# ── ETF Stocks (user-curated persistent list) ─────────────────────────────

def _load_etf_stocks_symbols():
    d = _load(ETF_STOCKS_FILE)
    if d and isinstance(d.get('symbols'), list):
        return d['symbols']
    return []

def _save_etf_stocks_symbols(symbols):
    try:
        with open(ETF_STOCKS_FILE, 'w') as f:
            json.dump({'symbols': symbols}, f)
    except Exception as e:
        print(f'[WARN] Could not save etf_stocks: {e}')

def refresh_etf_stocks():
    global _etf_stocks
    symbols = _load_etf_stocks_symbols()
    with _lock:
        _etf_stocks['status'] = 'loading'
    stocks = []
    for sym in symbols:
        s = fetch_watch_stock(sym)   # reuse same full-data fetcher
        if s:
            stocks.append(s)
    with _lock:
        _etf_stocks['data']   = stocks
        _etf_stocks['time']   = datetime.now().isoformat()
        _etf_stocks['status'] = 'ready'
    print(f'[INFO] ETF Stocks refreshed — {len(stocks)} items.')

# ── Flask routes ───────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/api/stocks')
def get_stocks():
    with _lock:
        return jsonify(dict(status=_sp500['status'], count=len(_sp500['data']),
                            cached_at=_sp500['time'],
                            last_1m_update=_sp500['last_1m_update'],
                            last_10y_update=_sp500['last_10y_update'],
                            data=_sp500['data']))

@app.route('/api/penny-stocks')
def get_penny():
    with _lock:
        return jsonify(dict(status=_penny['status'], count=len(_penny['data']),
                            cached_at=_penny['time'],
                            last_1m_update=_penny['last_1m_update'],
                            last_10y_update=_penny['last_10y_update'],
                            data=_penny['data']))

@app.route('/api/tech-stocks')
def get_tech():
    with _lock:
        return jsonify(dict(status=_tech['status'], count=len(_tech['data']),
                            cached_at=_tech['time'],
                            last_1m_update=_tech['last_1m_update'],
                            last_10y_update=_tech['last_10y_update'],
                            data=_tech['data']))

@app.route('/api/etfs')
def get_etfs():
    with _lock:
        return jsonify(dict(status=_etf['status'], count=len(_etf['data']),
                            cached_at=_etf['time'],
                            last_1m_update=_etf['last_1m_update'],
                            last_10y_update=_etf['last_10y_update'],
                            data=_etf['data']))

@app.route('/api/watchlist')
def get_watchlist():
    with _lock:
        return jsonify(dict(status=_watch['status'], count=len(_watch['data']),
                            data=_watch['data']))

@app.route('/api/watchlist/add', methods=['POST'])
def watchlist_add():
    try:
        from flask import request as freq
        symbol = (freq.json or {}).get('symbol', '').strip().upper()
        if not symbol:
            return jsonify({'ok': False, 'error': 'No symbol provided'}), 400
        symbols = _load_watchlist()
        if symbol in symbols:
            return jsonify({'ok': False, 'error': f'{symbol} already in watchlist'})
        s = fetch_watch_stock(symbol)
        if not s:
            return jsonify({'ok': False, 'error': f'Could not find data for {symbol}'}), 404
        symbols.append(symbol)
        _save_watchlist_symbols(symbols)
        with _lock:
            _watch['data'].append(s)
            _watch['status'] = 'ready'
        return jsonify({'ok': True, 'stock': s})
    except Exception as e:
        print(f'[ERROR] watchlist_add: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/watchlist/remove/<symbol>', methods=['DELETE'])
def watchlist_remove(symbol):
    symbol = symbol.upper()
    symbols = _load_watchlist()
    if symbol not in symbols:
        return jsonify({'ok': False, 'error': f'{symbol} not in watchlist'}), 404
    symbols.remove(symbol)
    _save_watchlist_symbols(symbols)
    with _lock:
        _watch['data'] = [s for s in _watch['data'] if s['symbol'] != symbol]
    return jsonify({'ok': True})

@app.route('/api/watchlist/refresh')
def watchlist_refresh():
    threading.Thread(target=refresh_watchlist, daemon=True).start()
    return jsonify({'status': 'started'})

# ── ETF Stocks routes ──────────────────────────────────────────────────────

@app.route('/api/etf-stocks')
def get_etf_stocks():
    with _lock:
        return jsonify(dict(status=_etf_stocks['status'],
                            count=len(_etf_stocks['data']),
                            data=_etf_stocks['data']))

@app.route('/api/etf-stocks/add', methods=['POST'])
def etf_stocks_add():
    try:
        from flask import request as freq
        symbol = (freq.json or {}).get('symbol', '').strip().upper()
        if not symbol:
            return jsonify({'ok': False, 'error': 'No symbol provided'}), 400
        symbols = _load_etf_stocks_symbols()
        if symbol in symbols:
            return jsonify({'ok': False, 'error': f'{symbol} already in ETF Stocks'})
        s = fetch_watch_stock(symbol)
        if not s:
            return jsonify({'ok': False, 'error': f'Could not find data for {symbol}'}), 404
        symbols.append(symbol)
        _save_etf_stocks_symbols(symbols)
        with _lock:
            _etf_stocks['data'].append(s)
            _etf_stocks['status'] = 'ready'
        return jsonify({'ok': True, 'stock': s})
    except Exception as e:
        print(f'[ERROR] etf_stocks_add: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/etf-stocks/remove/<symbol>', methods=['DELETE'])
def etf_stocks_remove(symbol):
    symbol = symbol.upper()
    symbols = _load_etf_stocks_symbols()
    if symbol not in symbols:
        return jsonify({'ok': False, 'error': f'{symbol} not in ETF Stocks'}), 404
    symbols.remove(symbol)
    _save_etf_stocks_symbols(symbols)
    with _lock:
        _etf_stocks['data'] = [s for s in _etf_stocks['data'] if s['symbol'] != symbol]
    return jsonify({'ok': True})

@app.route('/api/etf-stocks/refresh')
def etf_stocks_refresh():
    threading.Thread(target=refresh_etf_stocks, daemon=True).start()
    return jsonify({'status': 'started'})

@app.route('/api/search')
def search_symbol():
    """Quick symbol lookup — returns name/sector if valid."""
    from flask import request as freq
    q = freq.args.get('q', '').strip().upper()
    if not q:
        return jsonify({'ok': False})
    try:
        info = yf.Ticker(q.replace('.', '-')).info
        name = info.get('shortName') or info.get('longName')
        if not name:
            return jsonify({'ok': False, 'error': 'Symbol not found'})
        return jsonify({'ok': True, 'symbol': q,
                        'name': name, 'sector': info.get('sector', '')})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/refresh')
def api_refresh():
    with _lock:
        if _sp500['status'] == 'loading': return jsonify({'status':'already_loading'})
    threading.Thread(target=refresh_sp500, kwargs=dict(force_1m=True, force_10y=True), daemon=True).start()
    threading.Thread(target=refresh_penny, kwargs=dict(force_1m=True, force_10y=True), daemon=True).start()
    threading.Thread(target=refresh_tech,  kwargs=dict(force_1m=True, force_10y=True), daemon=True).start()
    threading.Thread(target=refresh_etf,   kwargs=dict(force_1m=True, force_10y=True), daemon=True).start()
    return jsonify({'status':'started'})

@app.route('/api/refresh/1m')
def api_refresh_1m():
    threading.Thread(target=refresh_sp500, kwargs=dict(force_1m=True), daemon=True).start()
    threading.Thread(target=refresh_penny, kwargs=dict(force_1m=True), daemon=True).start()
    threading.Thread(target=refresh_tech,  kwargs=dict(force_1m=True), daemon=True).start()
    threading.Thread(target=refresh_etf,   kwargs=dict(force_1m=True), daemon=True).start()
    return jsonify({'status':'started'})

@app.route('/api/refresh/10y')
def api_refresh_10y():
    threading.Thread(target=refresh_sp500, kwargs=dict(force_10y=True), daemon=True).start()
    threading.Thread(target=refresh_penny, kwargs=dict(force_10y=True), daemon=True).start()
    threading.Thread(target=refresh_tech,  kwargs=dict(force_10y=True), daemon=True).start()
    threading.Thread(target=refresh_etf,   kwargs=dict(force_10y=True), daemon=True).start()
    return jsonify({'status':'started'})

@app.route('/api/status')
def api_status():
    with _lock:
        return jsonify({
            'sp500':  dict(status=_sp500['status'], count=len(_sp500['data']),
                           last_1m=_sp500['last_1m_update'], last_10y=_sp500['last_10y_update']),
            'penny':  dict(status=_penny['status'], count=len(_penny['data']),
                           last_1m=_penny['last_1m_update'], last_10y=_penny['last_10y_update']),
            'tech':   dict(status=_tech['status'],  count=len(_tech['data']),
                           last_1m=_tech['last_1m_update'],  last_10y=_tech['last_10y_update']),
            'etf':    dict(status=_etf['status'],   count=len(_etf['data']),
                           last_1m=_etf['last_1m_update'],   last_10y=_etf['last_10y_update']),
        })

@app.route('/api/profile/<symbol>')
def get_profile(symbol):
    try:
        info   = yf.Ticker(symbol.replace('.', '-')).info
        fields = ['symbol','shortName','longName','sector','industry','country',
                  'website','longBusinessSummary','fullTimeEmployees',
                  'marketCap','trailingPE','forwardPE','trailingEps',
                  'dividendYield','dividendRate','fiftyTwoWeekHigh','fiftyTwoWeekLow',
                  'beta','averageVolume','totalRevenue','profitMargins',
                  'returnOnEquity','debtToEquity','currentRatio',
                  'earningsQuarterlyGrowth','revenueGrowth','currentPrice','previousClose']
        result = {k: info.get(k) for k in fields}
        result['symbol'] = symbol
        return jsonify(result)
    except Exception as e:
        return jsonify({'symbol': symbol, 'error': str(e)}), 500

# ── Startup ────────────────────────────────────────────────────────────────

def _boot(cache_path, state_dict, refresh_fn, label, required_version=None):
    disk = _load(cache_path)
    version_ok = (required_version is None or
                  (disk and disk.get('version', 1) >= required_version))
    if disk and disk.get('data') and version_ok:
        with _lock:
            state_dict.update(data=disk['data'], time=disk.get('time'),
                              last_1m_update=disk.get('last_1m_update'),
                              last_10y_update=disk.get('last_10y_update'),
                              status='ready')
        print(f'[INFO] {label}: loaded {len(disk["data"])} from cache.')
        do1m, do10y = _stale_1m(disk), _stale_10y(disk)
        if do1m or do10y:
            threading.Thread(target=refresh_fn,
                             kwargs=dict(force_1m=do1m, force_10y=do10y), daemon=True).start()
        else:
            print(f'[INFO] {label}: cache fully fresh, no background update needed.')
    else:
        reason = 'version mismatch' if (disk and not version_ok) else 'no cache'
        print(f'[INFO] {label}: {reason} — fetching fresh (this may take a few minutes)...')
        threading.Thread(target=refresh_fn, daemon=True).start()

if __name__ == '__main__':
    _boot(CACHE_FILE,  _sp500, refresh_sp500, 'S&P 500')
    _boot(PENNY_CACHE, _penny, refresh_penny, 'Penny', required_version=PENNY_CACHE_VERSION)
    _boot(TECH_CACHE,  _tech,  refresh_tech,  'Tech',  required_version=TECH_CACHE_VERSION)
    _boot(ETF_CACHE,   _etf,   refresh_etf,   'ETF',   required_version=ETF_CACHE_VERSION)

    # Boot watchlist
    wl_syms = _load_watchlist()
    if wl_syms:
        print(f'[INFO] Watchlist: {len(wl_syms)} saved symbols, refreshing...')
        threading.Thread(target=refresh_watchlist, daemon=True).start()
    else:
        with _lock:
            _watch['data'] = []
            _watch['status'] = 'ready'
        print('[INFO] Watchlist: empty.')

    # Boot ETF Stocks
    etf_s_syms = _load_etf_stocks_symbols()
    if etf_s_syms:
        print(f'[INFO] ETF Stocks: {len(etf_s_syms)} saved symbols, refreshing...')
        threading.Thread(target=refresh_etf_stocks, daemon=True).start()
    else:
        with _lock:
            _etf_stocks['data'] = []
            _etf_stocks['status'] = 'ready'
        print('[INFO] ETF Stocks: empty.')

    print('\n========================================')
    print('  StockPerformer  ->  http://localhost:5000')
    print('========================================\n')
    app.run(debug=False, port=5000, use_reloader=False)
