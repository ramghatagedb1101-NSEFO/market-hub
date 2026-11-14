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
  compare      any data point against a number or another data point (owner, 14 Nov 2026: "pick and choose the
               existing data points ... all possible combinations")
               {left: OPERAND, op: ">"|"<"|">="|"<="|"crosses_above"|"crosses_below", right: OPERAND, tf}
               OPERAND = {src, n?, value?}; src (see OPERANDS):
                 price, open, high, low, close      the index; the last completed bar of tf minutes
                 day_open, day_high, day_low         today so far
                 prev_close, prev_high, prev_low     yesterday's session
                 orb_high, orb_low                   high / low of today's first n minutes (none until they are over)
                 ema, sma, rsi, atr                  of the index's closes on tf-minute bars, period n
                 adx                                 Wilder's ADX (trend strength, 0-100) on tf-minute bars, period n
                 chg_prev, chg_open                  % move from yesterday's close / today's open
                 opt_price                           the price of the option the strategy would trade (now only)
                 dte                                 days to the traded expiry
                 value                               a number
               "crosses" compares the last two completed bars; it cannot use opt_price.
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


def atr(bars: list[Bar], n: int) -> list[float | None]:
    """Wilder's average true range."""
    out = [None] * len(bars)
    trs = []
    for i, b in enumerate(bars):
        pc = bars[i - 1][4] if i else b[4]
        trs.append(max(b[2] - b[3], abs(b[2] - pc), abs(b[3] - pc)))
    if len(trs) < n:
        return out
    a = sum(trs[:n]) / n
    out[n - 1] = a
    for i in range(n, len(trs)):
        a = (a * (n - 1) + trs[i]) / n
        out[i] = a
    return out


def adx(bars: list[Bar], n: int) -> list[float | None]:
    """Wilder's ADX (owner, 14 Nov 2026: "add ADX indicator"): trend strength 0-100, whichever the direction."""
    size = len(bars)
    out = [None] * size
    if size < 2 * n:                            # first reading at bar 2n - 1
        return out
    tr, pdm, mdm = [], [], []
    for i in range(1, size):
        h, l, pc = bars[i][2], bars[i][3], bars[i - 1][4]
        up, down = h - bars[i - 1][2], bars[i - 1][3] - l
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
        pdm.append(up if up > down and up > 0 else 0.0)
        mdm.append(down if down > up and down > 0 else 0.0)
    s_tr, s_p, s_m = sum(tr[:n]), sum(pdm[:n]), sum(mdm[:n])
    dx = []
    for j in range(n - 1, len(tr)):
        if j >= n:
            s_tr, s_p, s_m = s_tr - s_tr / n + tr[j], s_p - s_p / n + pdm[j], s_m - s_m / n + mdm[j]
        pdi, mdi = (100 * s_p / s_tr, 100 * s_m / s_tr) if s_tr else (0.0, 0.0)
        dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0)
    a = sum(dx[:n]) / n
    out[2 * n - 1] = a                          # bar index: dx[k] belongs to bar k + n
    for k in range(n, len(dx)):
        a = (a * (n - 1) + dx[k]) / n
        out[k + n] = a
    return out


OPERANDS = {"price", "open", "high", "low", "close", "day_open", "day_high", "day_low", "prev_close", "prev_high",
            "prev_low", "orb_high", "orb_low", "ema", "sma", "rsi", "atr", "adx", "chg_prev", "chg_open", "opt_price",
            "dte", "value"}
COMPARE_OPS = {">", "<", ">=", "<=", "crosses_above", "crosses_below"}
NAMES = {"price": "index", "open": "bar open", "high": "bar high", "low": "bar low", "close": "bar close",
         "day_open": "today's open", "day_high": "today's high", "day_low": "today's low",
         "prev_close": "yesterday's close", "prev_high": "yesterday's high", "prev_low": "yesterday's low",
         "orb_high": "opening-range high", "orb_low": "opening-range low", "ema": "EMA", "sma": "SMA", "rsi": "RSI",
         "atr": "ATR", "adx": "ADX", "chg_prev": "% from yesterday", "chg_open": "% from open", "opt_price": "option price",
         "dte": "days to expiry", "value": ""}


def _days(bars1: list[Bar]) -> dict:
    """date -> (open, high, low, close) of each session in the one-minute bars."""
    out = {}
    for b in bars1:
        d = b[0].date()
        o = out.get(d)
        out[d] = (b[1], b[2], b[3], b[4]) if o is None else (o[0], max(o[1], b[2]), min(o[2], b[3]), b[4])
    return out


def operand(o: dict, tb: list[Bar], bars1: list[Bar], tf: int, ctx: dict) -> list:
    """The operand's value at each tf-minute bar in tb (None where it has no value yet)."""
    src, n = o.get("src"), int(o.get("n") or 14)
    size = len(tb)
    if src == "value":
        return [float(o.get("value") or 0)] * size
    if src == "dte":
        return [ctx.get("dte")] * size
    if src == "opt_price":
        return [None] * (size - 1) + [ctx.get("opt_price")] if size else []
    closes = [b[4] for b in tb]
    if src in ("price", "close"):
        return closes
    if src in ("open", "high", "low"):
        return [b[{"open": 1, "high": 2, "low": 3}[src]] for b in tb]
    if src in ("ema", "sma"):
        return (ema if src == "ema" else sma)(closes, n)
    if src == "rsi":
        return rsi(closes, n)
    if src == "atr":
        return atr(tb, n)
    if src == "adx":
        return adx(tb, n)
    days = _days(bars1)
    order = sorted(days)
    by_day: dict = {}
    for x in bars1:
        by_day.setdefault(x[0].date(), []).append(x)
    out = [None] * max(size - 2, 0)             # comparisons read only the last two bars: work out just those
    for b in tb[-2:]:
        d = b[0].date()
        before = [x for x in order if x < d]
        prev = days[before[-1]] if before else None
        end = b[0] + timedelta(minutes=tf - 1)
        day1 = [x for x in by_day.get(d, []) if x[0] <= end]
        if src in ("day_open", "day_high", "day_low", "chg_open"):
            if not day1:
                out.append(None)
            elif src == "day_open":
                out.append(day1[0][1])
            elif src == "day_high":
                out.append(max(x[2] for x in day1))
            elif src == "day_low":
                out.append(min(x[3] for x in day1))
            else:
                out.append((b[4] / day1[0][1] - 1) * 100 if day1[0][1] else None)
        elif src in ("prev_close", "prev_high", "prev_low", "chg_prev"):
            pc = prev[3] if prev else ctx.get("prev_close")
            if src == "prev_close":
                out.append(pc)
            elif src == "prev_high":
                out.append(prev[1] if prev else None)
            elif src == "prev_low":
                out.append(prev[2] if prev else None)
            else:
                out.append((b[4] / pc - 1) * 100 if pc else None)
        elif src in ("orb_high", "orb_low"):
            m = int(o.get("n") or 15)
            rng = [x for x in day1 if (x[0].hour * 60 + x[0].minute) - 555 < m]
            if len(rng) < m or len(day1) <= m:
                out.append(None)
            else:
                out.append(max(x[2] for x in rng) if src == "orb_high" else min(x[3] for x in rng))
        else:
            out.append(None)
    return out


def _label(o: dict) -> str:
    src = o.get("src")
    if src == "value":
        return f"{float(o.get('value') or 0):g}"
    name = NAMES.get(src, src)
    if src in ("ema", "sma", "rsi", "atr", "adx"):
        return f"{name} {int(o.get('n') or 14)}"
    if src in ("orb_high", "orb_low"):
        return f"{name} ({int(o.get('n') or 15)} min)"
    return name


def compare(sig: dict, bars1: list[Bar], ctx: dict) -> tuple[bool, str]:
    tf = int(sig.get("tf", 5))
    left, right, op = sig.get("left") or {}, sig.get("right") or {}, sig.get("op", ">")
    words = f"{_label(left)} {op.replace('_', ' ')} {_label(right)}"
    tb = resample(bars1, tf)
    if not tb:
        if not {left.get("src"), right.get("src")} <= {"value", "dte", "opt_price"}:
            return False, "no index prices yet"
        tb = [(None, 0, 0, 0, 0)]
    a_s, b_s = operand(left, tb, bars1, tf, ctx), operand(right, tb, bars1, tf, ctx)
    if op in ("crosses_above", "crosses_below"):
        if len(a_s) < 2 or None in (a_s[-1], a_s[-2], b_s[-1], b_s[-2]):
            return False, words + ": not ready"
        if op == "crosses_above":
            ok = a_s[-2] <= b_s[-2] and a_s[-1] > b_s[-1]
        else:
            ok = a_s[-2] >= b_s[-2] and a_s[-1] < b_s[-1]
        return ok, f"{words} ({a_s[-1]:,.2f} vs {b_s[-1]:,.2f})"
    if not a_s or not b_s or a_s[-1] is None or b_s[-1] is None:
        return False, words + ": not ready"
    a, b = a_s[-1], b_s[-1]
    ok = {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}.get(op, False)
    return ok, f"{words} ({a:,.2f} vs {b:,.2f})"


def _avg(kind: str):
    return ema if kind == "ema" else sma


def check(sig: dict, bars: list[Bar], now: datetime, prev_close: float | None, expiry: str | None,
          ctx: dict | None = None) -> tuple[bool, str]:
    """(true or not, words for the journal). Bars: completed one-minute bars, yesterday's and today's.
    ctx: {"opt_price": price of the option the strategy would trade} for the compare signal."""
    t = sig.get("type")
    today = now.date()
    if t == "compare":
        c = dict(ctx or {}, prev_close=prev_close, dte=(date.fromisoformat(expiry) - today).days if expiry else None)
        return compare(sig, bars, c)
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
