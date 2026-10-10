"""
AI summaries of earnings-call transcripts and annual reports (11 Oct 2026), shown in the admin stock
report's Documents panel. Runs in .github/workflows/summaries.yml:

  on demand    SYMBOL set (the report's "Summarise" button): that company's latest transcript and
               latest annual report, if not already summarised.
  daily        no SYMBOL: the latest transcript of each company scoring 3+ on the multi-bagger screen
               that has not been summarised yet, at most AI_DAILY_LIMIT documents (default 15).

Documents come from the links in site/docs.json (hub/documents.py, NSE's own PDFs).

Model (AI_PROVIDER):
  gemini     the default and free: Google's Gemini API free tier (GEMINI_API_KEY, from Google AI Studio).
             Takes PDFs up to 50 MB / 1,000 pages, so transcripts and most annual reports go in whole.
             The free tier may use inputs to improve Google's products -- these are public NSE filings.
             On a rate limit it retries once on the lighter free model (GEMINI_FALLBACK_MODEL).
  anthropic  Claude (ANTHROPIC_API_KEY), paid per use; kept as an option.
A document too large for the chosen model is sent as text extracted with pypdf -- the whole text when it
fits, otherwise the Management Discussion & Analysis section onwards, and the summary says which pages.

Without the chosen provider's key, the requested company's entry records why nothing ran.
Output: site/summaries.json in the private repo, {symbol: {"tr": {...}, "ar": {...}, "_status": {...}}}.
"""
import base64
import io
import json
import os
import sys
from datetime import datetime

import requests

from . import config

DOCS_FILE = config.SITE_DIR / "data" / "docs.json"
SUMMARIES_FILE = config.SITE_DIR / "data" / "summaries.json"
MULTIBAGGER_FILE = config.SITE_DIR / "data" / "multibagger.json"
PROVIDER = os.getenv("AI_PROVIDER", "gemini").strip().lower()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
CLAUDE_MODEL = os.getenv("AI_MODEL", "claude-opus-5-5")
KEY_ENV = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
GEMINI_MAX_PDF_BYTES, GEMINI_MAX_PAGES = 48 * 1024 * 1024, 1000
DAILY_LIMIT = int(os.getenv("AI_DAILY_LIMIT", "15"))
MAX_PDF_BYTES = 30 * 1024 * 1024
MAX_TEXT_CHARS = 600_000            # roughly 150k tokens of annual-report text
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One line: the single most important takeaway."},
        "summary": {"type": "string", "description": "Three to five plain sentences."},
        "key_points": {"type": "array", "items": {"type": "string"}, "description": "Five to eight points."},
        "guidance": {"type": "array", "items": {"type": "string"},
                     "description": "Forward-looking statements by management, as stated. Empty if none."},
        "risks": {"type": "array", "items": {"type": "string"}},
        "numbers": {"type": "array", "items": {
            "type": "object",
            "properties": {"metric": {"type": "string"}, "value": {"type": "string"}, "context": {"type": "string"}},
            "required": ["metric", "value", "context"], "additionalProperties": False}},
        "management_tone": {"type": "string", "enum": ["positive", "balanced", "cautious", "negative"]},
        "watch_next": {"type": "array", "items": {"type": "string"},
                       "description": "What an investor should check in the next quarter's results."},
    },
    "required": ["headline", "summary", "key_points", "guidance", "risks", "numbers", "management_tone", "watch_next"],
    "additionalProperties": False,
}

INSTRUCTIONS = {
    "tr": ("This is an Indian listed company's earnings-call transcript, filed with NSE. Summarise it for a "
           "long-term equity investor: what changed in the business this quarter, what management said about "
           "demand, margins, capacity and capital allocation, any guidance, and what analysts pressed on. "
           "Use only figures stated in the transcript, with their units (Rs crore, %, bps). Where management "
           "avoided a question or gave no number, say so rather than inferring one."),
    "ar": ("This is an Indian listed company's annual report, filed with NSE. Summarise it for a long-term "
           "equity investor: the year's performance and its drivers, strategy and capital allocation, segment "
           "or product trends, risks management itself flags, and anything unusual in governance, related-party "
           "dealings or auditor remarks that appears in the text provided. Use only figures stated in the text, "
           "with their units."),
}


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def download(url: str) -> bytes:
    r = requests.get(url, headers=UA, timeout=120)
    r.raise_for_status()
    if len(r.content) > 200 * 1024 * 1024:
        raise ValueError("document over 200 MB")
    return r.content


def annual_report_text(pdf: bytes) -> tuple[str, str]:
    """(text to send, which pages it covers)."""
    from pypdf import PdfReader
    pages = [(p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages]
    total = sum(len(t) for t in pages)
    if total <= MAX_TEXT_CHARS:
        return "\n\n".join(pages), f"all {len(pages)} pages"
    # The section's own first page, not the contents page that lists it: the heading near the top of
    # a page, past the opening pages (Titan FY26: listed on page 4, starts much later).
    keys = ("management discussion", "management's discussion", "management’s discussion")
    hits = [i for i, t in enumerate(pages) if i > 5 and any(k in t.lower() for k in keys)]
    tops = [i for i in hits if any(k in pages[i][:400].lower() for k in keys)]
    start = (tops or hits or [0])[0]
    chosen, size, end = [], 0, start
    for i in range(start, len(pages)):
        if size + len(pages[i]) > MAX_TEXT_CHARS:
            break
        chosen.append(pages[i])
        size += len(pages[i])
        end = i
    where = "Management Discussion & Analysis onwards" if start else "the opening section"
    return "\n\n".join(chosen), f"pages {start + 1}-{end + 1} of {len(pages)} ({where}; the report is too long to send whole)"


def pdf_pages(pdf: bytes) -> int:
    from pypdf import PdfReader
    return len(PdfReader(io.BytesIO(pdf)).pages)


def ask_gemini(client, pdf: bytes | None, text: str | None, instructions: str) -> tuple[str, str]:
    """(JSON text, model used). Free-tier rate limits: one retry on the lighter free model."""
    part = ({"type": "document", "data": base64.b64encode(pdf).decode("ascii"), "mime_type": "application/pdf"}
            if pdf is not None else {"type": "text", "text": text})
    fmt = {"type": "text", "mime_type": "application/json", "schema": SCHEMA}
    for model in (GEMINI_MODEL, GEMINI_FALLBACK_MODEL):
        try:
            r = client.interactions.create(model=model, input=[part, {"type": "text", "text": instructions}],
                                           response_format=fmt)
            return r.output_text, model
        except Exception as exc:
            # The SDK's interactions call raises its own status errors (status_code), older calls
            # ClientError (code); a 429 from either is the free tier's rate limit.
            limited = 429 in (getattr(exc, "status_code", None), getattr(exc, "code", None))
            if not limited or model == GEMINI_FALLBACK_MODEL:
                raise
    raise RuntimeError("unreachable")


def ask_claude(client, pdf: bytes | None, text: str | None, instructions: str) -> tuple[str, str]:
    source = ({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                              "data": base64.standard_b64encode(pdf).decode("ascii")}}
              if pdf is not None else {"type": "text", "text": text})
    resp = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [source, {"type": "text", "text": instructions}]}],
    )
    if resp.stop_reason == "refusal":
        raise ValueError("the model declined to summarise this document")
    return next((b.text for b in resp.content if b.type == "text"), ""), resp.model


def make_client():
    if PROVIDER == "anthropic":
        import anthropic
        return anthropic.Anthropic()
    from google import genai
    return genai.Client()          # reads GEMINI_API_KEY


def summarise(client, kind: str, doc: dict) -> dict:
    pdf = download(doc["url"])
    coverage = None
    if PROVIDER == "anthropic":
        whole = kind == "tr" and len(pdf) <= MAX_PDF_BYTES
    else:
        whole = len(pdf) <= GEMINI_MAX_PDF_BYTES and pdf_pages(pdf) <= GEMINI_MAX_PAGES
    text = None
    if not whole:
        text, coverage = annual_report_text(pdf)
        if not text.strip():
            raise ValueError("no readable text in the PDF (scanned images only)")
    ask = ask_claude if PROVIDER == "anthropic" else ask_gemini
    raw, model = ask(client, pdf if whole else None, text, INSTRUCTIONS[kind])
    out = {"date": doc.get("date"), "url": doc["url"], "fy": doc.get("fy"), "model": model,
           "created": datetime.now(config.IST).isoformat(timespec="minutes"),
           "summary": json.loads(raw)}
    if coverage:
        out["coverage"] = coverage
    return out


def plan(docs: dict, done: dict, symbol: str | None) -> list[tuple[str, str, dict]]:
    """[(symbol, kind, doc)] still to summarise."""
    def pending(sym, kind):
        latest = (docs.get(sym, {}).get(kind) or [None])[0]
        if latest and (done.get(sym, {}).get(kind) or {}).get("url") != latest["url"]:
            return latest
        return None

    if symbol:
        return [(symbol, k, d) for k in ("tr", "ar") if (d := pending(symbol, k))]
    mb = load(MULTIBAGGER_FILE, {})
    ranked = sorted((r for r in mb.get("ranked", []) if (r.get("score") or 0) >= 3), key=lambda r: r.get("rank") or 1e9)
    out = []
    for r in ranked:
        d = pending(r["symbol"], "tr")
        if d:
            out.append((r["symbol"], "tr", d))
        if len(out) >= DAILY_LIMIT:
            break
    return out


def main() -> dict:
    symbol = (os.getenv("SYMBOL") or "").strip().upper() or None
    docs, done = load(DOCS_FILE, {}), load(SUMMARIES_FILE, {})
    now = datetime.now(config.IST).isoformat(timespec="minutes")
    todo = plan(docs, done, symbol)
    report = {"symbol": symbol, "to_summarise": len(todo), "done": [], "failed": []}

    def status(sym, state, message):
        done.setdefault(sym, {})["_status"] = {"state": state, "message": message, "at": now}

    if symbol and not todo:
        status(symbol, "done", "Nothing new to summarise." if docs.get(symbol)
               else "No transcripts or annual reports on file for this company yet.")
    key_env = KEY_ENV.get(PROVIDER, "GEMINI_API_KEY")
    if todo and not os.getenv(key_env):
        report["error"] = f"{key_env} is not set"
        how = ("a free Gemini API key from aistudio.google.com" if PROVIDER == "gemini" else "an Anthropic API key")
        for sym in {s for s, _, _ in todo}:
            status(sym, "error", f"AI summaries need {how}: add it as the GitHub Actions secret {key_env} "
                                 "in the market-hub repository.")
        todo = []
    client = make_client() if todo else None
    for sym, kind, doc in todo:
        try:
            done.setdefault(sym, {})[kind] = summarise(client, kind, doc)
            report["done"].append(f"{sym}:{kind}")
            status(sym, "done", "Summarised.")
        except Exception as exc:
            report["failed"].append({"doc": f"{sym}:{kind}", "error": str(exc)[:200]})
            status(sym, "error", f"Could not summarise the {'transcript' if kind == 'tr' else 'annual report'}: {str(exc)[:160]}")
    SUMMARIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUMMARIES_FILE.write_text(json.dumps(done, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
    sys.exit(0)
