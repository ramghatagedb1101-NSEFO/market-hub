"""
Zerodha Kite Connect source (paid API, the user's existing subscription).

Needs three environment secrets:
  KITE_API_KEY, KITE_API_SECRET   from the Kite developer console (static)
  KITE_ACCESS_TOKEN               issued each morning by the login flow (expires daily)

Every job's Kite calls go through PacedKite (14 Oct 2026, from the 13 Oct Kite / BharatStock call audit; also used by
rg/market_data.get_kite). Before, the daily jobs sent quote calls back to back -- rg/market_data.py ~100-150 a run at
2-4 a second against Kite's limit of 1 -- so refusals quietly dropped stocks from screens, and each job downloaded the
same instrument lists several times. Now, per process:
  - quote / ltp / ohlc calls at least 1.05 s apart (Kite: 1 a second), historical candles 0.35 s apart (3 a second);
  - a "Too many requests" refusal is waited out and retried (3 tries) instead of losing the data;
  - a quote for more than 500 instruments is split into paced calls of 500 (Kite's limit per call);
  - each exchange's instrument list is downloaded once a day: kept in memory and on disk (.cache/kite_instruments/,
    which every step of a GitHub job shares), so `python -m hub`, hub.stocks, hub.fno ... share one download.
"""
from urllib.parse import quote_plus
import os
import pickle
import time
from datetime import date, datetime, timedelta, timezone

from kiteconnect import KiteConnect

from .. import config

QUOTE_GAP = 1.05          # seconds between quote-family calls (Kite: 1 request a second)
HIST_GAP = 0.35           # seconds between historical-candle calls (Kite: 3 a second)
QUOTE_MAX = 500           # instruments per quote call (Kite's limit)
QUOTE_URL_MAX = 6000      # characters of instrument list per quote call: Kite's front server refuses very long URLs
CACHE_DIR = config.REPO / ".cache" / "kite_instruments"
_IST = timezone(timedelta(hours=5, minutes=30))
_last = {"quote": 0.0, "hist": 0.0}      # shared by every client in the process
_lists = {}                              # (exchange, date) -> instrument rows
stats = {"quote_calls": 0, "hist_calls": 0, "throttled": 0, "list_downloads": 0}


def _today() -> date:
    return datetime.now(_IST).date()


def _wait(kind: str) -> None:
    gap = QUOTE_GAP if kind == "quote" else HIST_GAP
    pause = gap - (time.monotonic() - _last[kind])
    if pause > 0:
        time.sleep(pause)
    _last[kind] = time.monotonic()


def _throttled(exc: Exception) -> bool:
    return "too many" in str(exc).lower() or getattr(exc, "code", None) == 429


class PacedKite(KiteConnect):
    """KiteConnect with the job-wide pacing, retry, chunking and instrument-list cache described above."""

    def _paced(self, kind: str, fn):
        for attempt in range(3):
            _wait(kind)
            stats["quote_calls" if kind == "quote" else "hist_calls"] += 1
            try:
                return fn()
            except Exception as exc:
                if not _throttled(exc) or attempt == 2:
                    raise
                stats["throttled"] += 1
                time.sleep(1.1 * (attempt + 1))

    def _quote_family(self, method, instruments):
        flat = []
        for i in instruments:
            flat.extend(i if isinstance(i, (list, tuple, set)) else [i])
        # Chunks by count AND by request-line length (23 Oct 2026): 500 long option names (NFO:TCS26OCT4100CE...) made a
        # ~17,000-character URL that Kite's front server refused ("400 Bad request", HTML), so the NIFTY 50 option screen
        # (hub/stocks.py prefetch) failed every day from 14 Oct. The relay keeps its own URLs short for the same reason.
        out, part, size = {}, [], 0
        for inst in flat:
            cost = len("i=" + quote_plus(str(inst))) + 1
            if part and (len(part) >= QUOTE_MAX or size + cost > QUOTE_URL_MAX):
                chunk = part
                out.update(self._paced("quote", lambda: method(self, chunk)) or {})
                part, size = [], 0
            part.append(inst); size += cost
        if part:
            chunk = part
            out.update(self._paced("quote", lambda: method(self, chunk)) or {})
        return out

    def quote(self, *instruments):
        return self._quote_family(KiteConnect.quote, instruments)

    def ltp(self, *instruments):
        return self._quote_family(KiteConnect.ltp, instruments)

    def ohlc(self, *instruments):
        return self._quote_family(KiteConnect.ohlc, instruments)

    def historical_data(self, *args, **kwargs):
        return self._paced("hist", lambda: KiteConnect.historical_data(self, *args, **kwargs))

    def instruments(self, exchange=None):
        key = (exchange or "ALL", _today())
        if key in _lists:
            return _lists[key]
        path = CACHE_DIR / f"{key[0]}_{key[1].isoformat()}.pkl"
        try:
            rows = pickle.loads(path.read_bytes())
        except (OSError, pickle.PickleError, EOFError):
            rows = None
        if not rows:
            rows = self._paced("hist", lambda: KiteConnect.instruments(self, exchange) if exchange else KiteConnect.instruments(self))
            stats["list_downloads"] += 1
            if rows:
                try:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(pickle.dumps(rows))
                    for old in CACHE_DIR.glob(f"{key[0]}_*.pkl"):       # earlier days' copies
                        if old != path:
                            old.unlink(missing_ok=True)
                except OSError:
                    pass
        _lists[key] = rows
        return rows


def client() -> KiteConnect:
    k = PacedKite(api_key=os.environ["KITE_API_KEY"])
    k.set_access_token(os.environ["KITE_ACCESS_TOKEN"])
    return k


def _retry(fn, tries=4):
    """store.refresh_prices() deliberately raises rather than write a partial day, so a transient
    Kite/network blip here would otherwise skip the entire rest of the daily pipeline (same class of
    bug fixed 2026-10-08 on the Kite-token relay call). Does not retry a real auth/lookup error
    (KeyError from instrument_token), only the call itself."""
    last_exc = None
    for attempt in range(tries):
        try:
            return fn()
        except KeyError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
    raise last_exc


def instrument_token(k: KiteConnect, exchange: str, tradingsymbol: str) -> int:
    rows = _retry(lambda: k.instruments(exchange))
    for row in rows:
        if row["tradingsymbol"] == tradingsymbol:
            return int(row["instrument_token"])
    raise KeyError(f"{tradingsymbol} not found on {exchange}")


def daily_closes(k: KiteConnect, token: int, start: date, end: date) -> dict:
    """{ 'YYYY-MM-DD': close } for daily candles in [start, end]."""
    rows = _retry(lambda: k.historical_data(token, start, end, "day"))
    return {r["date"].date().isoformat(): float(r["close"]) for r in rows}
