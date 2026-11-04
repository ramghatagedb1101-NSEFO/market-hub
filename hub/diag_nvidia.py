"""
Which NVIDIA models answer this account, and how fast (4 Nov 2026: the written brief got 404 "Not found for account" or a
timeout from all 8 models it tried). Run on GitHub with diag.yml, where NVIDIA_API_KEY lives. The log of this public repo
is public: prints status codes and timings only, with account and function ids removed from any message.
"""
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import narrate

BASE = "https://integrate.api.nvidia.com/v1"
SKIP = re.compile(r"embed|rerank|safety|guard|vision|-vl|ocr|parse|clip|paligemma|retriever|flux|stable-diffusion|sdxl|audio|asr|tts", re.I)


def clean(text: str) -> str:
    text = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}", "<id>", text or "")
    text = re.sub(r"(account|Account)\s*'[^']*'?", r"\1 <id>", text)
    return " ".join(text.split())[:160]


def ask(key: str, model: str, prompt: str, tokens: int, timeout: int) -> tuple:
    start = time.monotonic()
    try:
        r = requests.post(f"{BASE}/chat/completions", headers={"Authorization": f"Bearer {key}"}, timeout=timeout,
                          json={"model": model, "messages": [{"role": "user", "content": prompt}],
                                "max_tokens": tokens, "temperature": 0.2})
        secs = round(time.monotonic() - start, 1)
        if r.status_code == 200:
            m = r.json()["choices"][0]["message"]
            return model, 200, secs, f"{len(m.get('content') or '')} chars"
        return model, r.status_code, secs, clean(r.text)
    except requests.RequestException as exc:
        return model, type(exc).__name__, round(time.monotonic() - start, 1), ""


def main() -> None:
    key = os.environ.get("NVIDIA_API_KEY", "")
    print("key present:", bool(key), "| looks like an NVIDIA key:", key.startswith("nvapi-"))
    if not key:
        return
    anon = requests.get(f"{BASE}/models", timeout=30)
    signed = requests.get(f"{BASE}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    print("model list: without key", anon.status_code, "| with key", signed.status_code)
    ids = [m["id"] for m in signed.json().get("data", [])] if signed.status_code == 200 else []
    chat = [m for m in ids if not SKIP.search(m)]
    print(f"{len(ids)} listed, {len(chat)} look like chat models")

    with ThreadPoolExecutor(3) as pool:   # the free tier allows about 40 requests a minute
        short = list(pool.map(lambda m: ask(key, m, "Reply with the word ok.", 20, 45), chat))
    counts = {}
    for row in short:
        counts[row[1]] = counts.get(row[1], 0) + 1
    print("short test, by answer:", counts)
    for row in sorted(short, key=lambda x: (str(x[1]) != "200", x[2])):
        print(row)

    prompt = narrate.PROMPT.format(data="NIFTY closed 23960.6, up 0.6%. BANKNIFTY closed 55900. " * 40)
    print("brief-sized test, prompt", len(prompt), "chars:")
    for model in [r[0] for r in sorted(short, key=lambda x: x[2]) if r[1] == 200][:6]:
        print(ask(key, model, prompt, 1500, 150))


if __name__ == "__main__":
    main()
