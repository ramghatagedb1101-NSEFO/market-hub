"""
Signals for the strategy builder, worked out on the index's one-minute bars (14 Nov 2026).

A bar is (time, open, high, low, close), time = the minute it started (IST, naive). Only completed bars are used:
the bar of the minute in progress is left out, so a signal never changes its mind within a minute.

Signal types (each a dict from the builder page; "tf" = bar size in minutes, 1 / 3 / 5 / 15):
  price_ma     index close above / below its moving average      {ma: "ema"|"sma", period, tf, op: "above"|"below"}
  ma_cross     fast average crossing the slow one on the last bar {ma, fast, slow, tf, dir: "up"|"down"}
  rsi          RSI above / below a level, or crossing it          {period, tf, op: "above"|"below"|"crosses_above"|
                                                                   "crosses_below", level}
  orb          index breaks the first N minutes' high / low       {minutes, dir: "up"|"down"}
  change       % move from yesterday's close or today's open      {from: "prev_close"|"open", op: "above"|"below", pct}
                                                                   (pct is signed: -0.5 = down half a percent)
  dte          days to the traded expiry                          {op: "<="|">=", days}
  weekday      day of the week                                     {days: [1..5]}   (1 = Monday)
"""
from datetime import date, datetime, timedelta

Bar = tuple  # (datetime, o, h, l, c)


def completed(bars: list[Bar], now: datetime) -> list[Bar]:
    return [b for b in bars if b[0] + timedelta(minutes=1) <= now]


def resample(bars: list[Bar], tf: int) -> list[Bar]:
    """1-minute bars -> tf-minute bars, aligned to 09:15, within each day; a partial last group is dropped."""
    if tf <= 1:
        return list(bars)
    out, group, key = [], [], None
    for b in bars:
        mins = (b[0].hour * 60 + b[0].minute) - 555
        k = (b[0].date(), mins // tf)
        if k != key:
            if group and len(group) == tf:
                out.append((group[0][0], group[0][1], max(x[2] for x in group), min(x[3] for x in group), group[-1][4]))
            group, key = [], k
        group.append(b)
    if group and len(group) == tf:
        out.append((group[0][0], group[0][1], max(x[2] for x in group), min(x[3] for x in group), group[-1][4]))
    return out


def sma(xs: list[float], n: int) -> list[float | None]:
    out, s = [], 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def ema(xs: list[float], n: int) -> list[float | None]:
    out, k, e = [], 2 / (n + 1), None
    for i, x in enumerate(xs):
        if i < n - 1:
            out.append(None)
            continue
        e = sum(xs[:n]) / n if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def rsi(xs: list[float], n: int) -> list[float | None]:
    """Wilder's RSI."""
    out = [None] * len(xs)
    if len(xs) <= n:
        return out
    gains = [max(xs[i] - xs[i - 1], 0) for i in range(1, len(xs))]
    losses = [max(xs[i - 1] - xs[i], 0) for i in range(1, len(xs))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(xs)):
        if i > n:
            ag = (ag * (n - 1) + gains[i - 1]) / n
            al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def _avg(kind: str):
    return ema if kind == "ema" else sma


def check(sig: dict, bars: list[Bar], now: datetime, prev_close: float | None, expiry: str | None) -> tuple[bool, str]:
    """(true or not, words for the journal). Bars: completed one-minute bars, yesterday's and today's."""
    t = sig.get("type")
    today = now.date()
    if t == "weekday":
        ok = now.isoweekday() in [int(d) for d in sig.get("days") or []]
        return ok, f"weekday {now.strftime('%a')}"
    if t == "dte":
        if not expiry:
            return False, "no expiry"
        n = (date.fromisoformat(expiry) - today).days
        ok = n <= int(sig["days"]) if sig.get("op", "<=") == "<=" else n >= int(sig["days"])
        return ok, f"{n} days to expiry"
    if not bars:
        return False, "no index prices yet"
    day_bars = [b for b in bars if b[0].date() == today]
    if t == "change":
        base = prev_close if sig.get("from", "prev_close") == "prev_close" else (day_bars[0][1] if day_bars else None)
        if not base:
            return False, "no base price"
        ch = (bars[-1][4] / base - 1) * 100
        ok = ch > float(sig["pct"]) if sig.get("op", "above") == "above" else ch < float(sig["pct"])
        return ok, f"index {ch:+.2f}% from {'yesterday' if sig.get('from', 'prev_close') == 'prev_close' else 'open'}"
    if t == "orb":
        m = int(sig.get("minutes", 15))
        rng = [b for b in day_bars if (b[0].hour * 60 + b[0].minute) - 555 < m]
        if len(rng) < m or len(day_bars) <= m:
            return False, f"first {m} minutes not complete"
        hi, lo, last = max(b[2] for b in rng), min(b[3] for b in rng), day_bars[-1][4]
        ok = last > hi if sig.get("dir", "up") == "up" else last < lo
        return ok, f"index {last:,.1f} vs first-{m}-minute range {lo:,.1f}-{hi:,.1f}"
    tf = int(sig.get("tf", 5))
    closes = [b[4] for b in resample(bars, tf)]
    if t == "price_ma":
        n = int(sig.get("period", 20))
        ma = _avg(sig.get("ma", "ema"))(closes, n)
        if not ma or ma[-1] is None:
            return False, f"{n}-bar average not ready"
        ok = closes[-1] > ma[-1] if sig.get("op", "above") == "above" else closes[-1] < ma[-1]
        return ok, f"index {closes[-1]:,.1f} vs {sig.get('ma', 'ema').upper()}{n} ({tf}m) {ma[-1]:,.1f}"
    if t == "ma_cross":
        f, s = int(sig.get("fast", 9)), int(sig.get("slow", 21))
        af, as_ = _avg(sig.get("ma", "ema"))(closes, f), _avg(sig.get("ma", "ema"))(closes, s)
        if len(closes) < 2 or as_[-2] is None or af[-2] is None:
            return False, "averages not ready"
        up = af[-2] <= as_[-2] and af[-1] > as_[-1]
        down = af[-2] >= as_[-2] and af[-1] < as_[-1]
        ok = up if sig.get("dir", "up") == "up" else down
        return ok, f"{f}/{s} ({tf}m) {'crossed up' if up else 'crossed down' if down else 'no cross'}"
    if t == "rsi":
        n, lvl, op = int(sig.get("period", 14)), float(sig.get("level", 50)), sig.get("op", "above")
        r = rsi(closes, n)
        if len(r) < 2 or r[-1] is None or r[-2] is None:
            return False, "RSI not ready"
        ok = {"above": r[-1] > lvl, "below": r[-1] < lvl,
              "crosses_above": r[-2] <= lvl < r[-1], "crosses_below": r[-2] >= lvl > r[-1]}.get(op, False)
        return ok, f"RSI{n} ({tf}m) {r[-1]:.1f}"
    return False, f"unknown signal {t!r}"
