"""
Daily market brief written by Gemini (free tier), from this hub's own data.

Reads docs/data/feed.json and docs/data/fno.json, asks Gemini for a short plain-English brief,
and writes docs/data/brief.json. Needs GEMINI_API_KEY (GitHub secret). If the key is missing the
step writes a note and exits cleanly, so the rest of the daily job is unaffected.

Note: this brief works only from the hub's numbers. It has no live news feed. Adding news needs a
separate free news source, which is a later step.
"""
import json
import os
import time
from datetime import datetime

import requests

from . import config

BRIEF_FILE = config.SITE_DIR / "data" / "brief.json"
MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")   # Google's alias for the current Flash model
URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"


def _summary(feed: dict, fno: dict | None) -> str:
    lines = []
    for name, b in feed["indices"].items():
        t = b.get("today") or {}
        lines.append(f"{name}: last close {b['last_close']} on {b['last_date']}. "
                     f"Estimated close for {t.get('target')}: {t.get('pred')} "
                     f"(range {t.get('lo')}–{t.get('hi')}, {t.get('expected_move_pct')}% vs prior close).")
        if t.get("actual") is not None and t.get("pred"):
            miss = (t["actual"] / t["pred"] - 1) * 100
            inside = t["lo"] <= t["actual"] <= t["hi"]
            lines.append(f"  Actual close {t['actual']} on {t.get('target')}: {miss:+.2f}% vs the estimate, "
                         f"{'inside' if inside else 'OUTSIDE'} the estimated range. Say this plainly in the brief.")
        m = b["horizons"]["month"]["forecast"]
        if m:
            lines.append(f"  Month-end range {m['lo']}–{m['hi']} (no point call; model does not beat baseline).")
    if fno:
        for name, u in fno["underlyings"].items():
            for v in u["views"]:
                if v.get("structure"):
                    lines.append(f"{name} {v['label']} ({v['expiry']}): model structure {v['structure']}, "
                                 f"net {v['net_per_unit']} per unit, PCR {v['pcr']}.")
                else:
                    lines.append(f"{name} {v['label']} ({v['expiry']}): no structure. {v.get('reason', '')}")
    return "\n".join(lines)


def _context_summary(ctx: dict | None) -> str:
    """FII/DII flows, FX and headlines from hub/context.py. Lists what is missing too."""
    if not ctx:
        return "Market context file missing: FII/DII, FX and news are not available today."
    lines = []
    for r in ctx.get("fii_dii") or []:
        lines.append(f"{r['category']} cash flow on {r['date']}: buy {r['buy']}, sell {r['sell']}, net {r['net']} crore.")
    fx = ctx.get("fx")
    if fx:
        lines.append(f"USD/INR {fx['usd_inr']} (ECB reference, {fx['date']}).")
    for name, g in (ctx.get("global") or {}).items():
        lines.append(f"{name} close {g['last']} on {g['date']}, {g['change_pct']}% vs the prior close {g['prev']}.")
    if ctx.get("india_vix"):
        v = ctx["india_vix"]
        lines.append(f"India VIX {v['last']} ({v['change_pct']}% on the day).")
    for name, c in (ctx.get("commodities") or {}).items():
        chg = f"{c['change_pct']}% vs the prior close {c['prev_close']}" if c.get("change_pct") is not None else ""
        lines.append(f"{name}: {c['contract']} (expiry {c['expiry']}) last {c['last']}, {chg}.")
    for h in (ctx.get("headlines") or [])[:40]:
        lines.append(f"Headline ({h['source']}): {h['title']}")
    for k, msg in (ctx.get("errors") or {}).items():
        lines.append(f"Not available today, {k}: {msg}")
    return "\n".join(lines)


PROMPT = """You are writing the daily market brief for a private dashboard used by one active trader
who trades NIFTY and BANKNIFTY options. Write in plain English, in these sections with short headings:

1. Where the markets stand: NIFTY, BANKNIFTY, SENSEX closes and the model's estimates for today's close.
2. Global backdrop: only what the headlines or data below support. Say plainly where that is missing.
3. Gold, crude, dollar and rupee: use the USD/INR figure. If gold or crude data is missing, say so.
4. Institutional flows: FII and DII cash flows, and what the net numbers suggest. Say they are provisional.
5. India news and economy: the most relevant India headlines, one line each. Do not add facts that are not in them.
6. F&O: the model's suggestions, the expiry, the band width, and that they have no track record yet.
7. Risks and what to watch: concrete events or levels from the data, not generic warnings.

Rules: use only the data below. Do not invent news, causes, prices or events. Quote a number only if it is in the data.
If something is missing, say "not available today" in that section. No personal financial advice.
Keep it under 600 words.

Data:
{data}"""


NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b")
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


def _write_nvidia(api_key: str, prompt: str) -> str:
    """NVIDIA NIM (OpenAI-compatible). Free credits on build.nvidia.com."""
    r = requests.post(NVIDIA_URL, headers={"Authorization": f"Bearer {api_key}"},
                      json={"model": NVIDIA_MODEL, "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 6000, "temperature": 0.3},
                      timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"NVIDIA returned {r.status_code}: {r.text[:300]}")
    msg = r.json()["choices"][0]["message"]
    # Reasoning models may put the answer in content, or leave it empty and only fill reasoning_content.
    text = (msg.get("content") or "").strip() or (msg.get("reasoning_content") or "").strip()
    if not text:
        raise RuntimeError("NVIDIA returned an empty answer")
    return text


def _data(feed: dict, fno: dict | None, ctx: dict | None) -> str:
    return _summary(feed, fno) + "\n" + _context_summary(ctx)


def main() -> dict:
    nv_key = os.getenv("NVIDIA_API_KEY")
    key = os.getenv("GEMINI_API_KEY")
    feed = json.loads(config.FEED_FILE.read_text(encoding="utf-8"))
    fno_path = config.SITE_DIR / "data" / "fno.json"
    fno = json.loads(fno_path.read_text(encoding="utf-8")) if fno_path.exists() else None
    ctx_path = config.SITE_DIR / "data" / "context.json"
    ctx = json.loads(ctx_path.read_text(encoding="utf-8")) if ctx_path.exists() else None
    out = {"ts": datetime.now(config.IST).isoformat(timespec="minutes"), "text": "", "source": ""}

    if nv_key:
        out["source"] = f"NVIDIA · {NVIDIA_MODEL}"
        try:
            out["text"] = _write_nvidia(nv_key, PROMPT.format(data=_data(feed, fno, ctx)))
        except Exception as exc:
            out["text"] = f"Daily brief could not be written ({NVIDIA_MODEL}). {exc}"
    elif not key:
        out["source"] = "none"
        out["text"] = "Daily brief is off: no AI key is set in the repository secrets (NVIDIA_API_KEY or GEMINI_API_KEY)."
    else:
        out["source"] = f"Gemini · {MODEL}"
        try:
            body = {"contents": [{"parts": [{"text": PROMPT.format(data=_data(feed, fno, ctx))}]}]}
            for attempt in range(4):   # Gemini returns 429/503 under load; back off and retry
                r = requests.post(URL.format(m=MODEL), headers={"x-goog-api-key": key}, json=body, timeout=60)
                if r.status_code not in (429, 503):
                    break
                time.sleep(15 * (attempt + 1))
            if r.status_code != 200:
                raise RuntimeError(f"Gemini returned {r.status_code}: {r.text[:300]}")
            out["text"] = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as exc:
            # Record the reason on the page instead of failing the job. The rest still publishes.
            out["text"] = f"Daily brief could not be written ({MODEL}). {exc}"

    BRIEF_FILE.parent.mkdir(parents=True, exist_ok=True)
    BRIEF_FILE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
