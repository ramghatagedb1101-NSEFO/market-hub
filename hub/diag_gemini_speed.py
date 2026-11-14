"""
How long Google's Gemini takes to read a back-test sentence (14 Nov 2026: the Back-tests page's "Read my back-test"
sometimes sat for minutes, sometimes answered in 20 s). Sends the page's own instructions (BT_GUIDE from
relay/Backtest.gs) and the owner's example sentence to each model, with and without the model's thinking step, and
writes the timings to diag_output/gemini_speed.json. Timings and status codes only: no key, no answer text.
Run on GitHub: diag.yml -f module=diag_gemini_speed (GEMINI_API_KEY secret).
"""
import json
import os
import subprocess
import time
from datetime import datetime

import requests

Q = ("On a 5 minute interval of Nifty Index, using Supertrend indicator, Buy Nifty Call Option at ATM for current Weekly "
     "expiry when Supertrend gives BUY signal. When Supertrend gives SELL signal Buy Nifty Put Option at ATM for current "
     "Weekly Expiry. At 3.00 PM squareoff this open trade regardless of profit or loss. Perform backtest for data since "
     "Aug-2026.")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"


def guide() -> str:
    js = "const fs=require('fs');eval(fs.readFileSync('relay/Backtest.gs','utf8').replace(/^const /gm,'var '));" \
         "process.stdout.write(BT_GUIDE)"
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout


def one(key: str, model: str, gen_extra: dict, sys_text: str) -> dict:
    gen = {"responseMimeType": "application/json", "temperature": 0}
    gen.update(gen_extra)
    body = {"systemInstruction": {"parts": [{"text": sys_text}]}, "contents": [{"role": "user", "parts": [{"text": Q}]}],
            "generationConfig": gen}
    t0 = time.time()
    try:
        r = requests.post(URL.format(m=model), headers={"x-goog-api-key": key}, json=body, timeout=100)
        out = {"code": r.status_code, "s": round(time.time() - t0, 1)}
        if r.status_code == 200:
            j = r.json()
            u = j.get("usageMetadata") or {}
            out.update(thoughts=u.get("thoughtsTokenCount"), answer=u.get("candidatesTokenCount"))
            try:
                s = json.loads(j["candidates"][0]["content"]["parts"][0]["text"]).get("strategy") or {}
                out["put_side"] = bool(s.get("put_groups"))
            except Exception:                                # noqa: BLE001
                out["unreadable"] = True
        else:
            out["msg"] = ((r.json().get("error") or {}).get("message") or "")[:160] if r.text.startswith("{") else r.text[:120]
        return out
    except requests.Timeout:
        return {"code": "timeout", "s": round(time.time() - t0, 1)}


def main() -> None:
    key = os.environ["GEMINI_API_KEY"]
    sys_text = "Today is 2026-11-14 (Saturday) (India). Data runs to yesterday.\n" + guide()
    configs = [("gemini-3.8-flash", "default", {}),
               ("gemini-3.8-flash", "thinking low", {"thinkingConfig": {"thinkingLevel": "low"}}),
               ("gemini-3.8-flash", "thinking off", {"thinkingConfig": {"thinkingBudget": 0}}),
               ("gemini-3.5-flash-lite", "default", {})]
    res = {"ran": datetime.utcnow().isoformat(timespec="seconds") + "Z", "prompt_chars": len(sys_text), "runs": []}
    for rnd in range(3):
        for m, label, extra in configs:
            r = one(key, m, extra, sys_text)
            r.update(model=m, config=label, round=rnd + 1)
            print(json.dumps(r), flush=True)
            res["runs"].append(r)
            time.sleep(4)                                    # stay under the free tier's requests a minute
    os.makedirs("diag_output", exist_ok=True)
    json.dump(res, open("diag_output/gemini_speed.json", "w"), indent=1)


if __name__ == "__main__":
    main()
