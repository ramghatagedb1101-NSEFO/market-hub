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


PROMPT = """You are writing a short daily brief for a private market dashboard.
Use only the numbers below. Do not invent news, events or causes.
Write 5 to 8 plain sentences: where the indices stand, what the estimated closes imply,
what the F&O suggestions are (state they are model suggestions with no track record yet),
and one clear risk note. Do not give personal financial advice.

Data:
{data}"""


NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b")
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


def _write_nvidia(api_key: str, prompt: str) -> str:
    """NVIDIA NIM (OpenAI-compatible). Free credits on build.nvidia.com."""
    r = requests.post(NVIDIA_URL, headers={"Authorization": f"Bearer {api_key}"},
                      json={"model": NVIDIA_MODEL, "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 700, "temperature": 0.3},
                      timeout=90)
    if r.status_code != 200:
        raise RuntimeError(f"NVIDIA returned {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"].strip()


def main() -> dict:
    nv_key = os.getenv("NVIDIA_API_KEY")
    key = os.getenv("GEMINI_API_KEY")
    feed = json.loads(config.FEED_FILE.read_text(encoding="utf-8"))
    fno_path = config.SITE_DIR / "data" / "fno.json"
    fno = json.loads(fno_path.read_text(encoding="utf-8")) if fno_path.exists() else None
    out = {"ts": datetime.now(config.IST).isoformat(timespec="minutes"), "text": "", "source": ""}

    if nv_key:
        out["source"] = f"NVIDIA · {NVIDIA_MODEL}"
        try:
            out["text"] = _write_nvidia(nv_key, PROMPT.format(data=_summary(feed, fno)))
        except Exception as exc:
            out["text"] = f"Daily brief could not be written ({NVIDIA_MODEL}). {exc}"
    elif not key:
        out["source"] = "none"
        out["text"] = "Daily brief is off: no AI key is set in the repository secrets (NVIDIA_API_KEY or GEMINI_API_KEY)."
    else:
        out["source"] = f"Gemini · {MODEL}"
        try:
            body = {"contents": [{"parts": [{"text": PROMPT.format(data=_summary(feed, fno))}]}]}
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
