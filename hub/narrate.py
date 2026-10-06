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
from datetime import datetime

import requests

from . import config

BRIEF_FILE = config.SITE_DIR / "data" / "brief.json"
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
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


def main() -> dict:
    key = os.getenv("GEMINI_API_KEY")
    feed = json.loads(config.FEED_FILE.read_text(encoding="utf-8"))
    fno_path = config.SITE_DIR / "data" / "fno.json"
    fno = json.loads(fno_path.read_text(encoding="utf-8")) if fno_path.exists() else None
    out = {"ts": datetime.now(config.IST).isoformat(timespec="minutes"), "text": "", "source": "Gemini"}

    if not key:
        out["text"] = "Daily brief is off: GEMINI_API_KEY is not set in the repository secrets."
    else:
        try:
            r = requests.post(URL.format(m=MODEL), headers={"x-goog-api-key": key},
                              json={"contents": [{"parts": [{"text": PROMPT.format(data=_summary(feed, fno))}]}]},
                              timeout=60)
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
