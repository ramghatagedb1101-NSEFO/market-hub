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
import time
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
TIME_BUDGET_S = 35 * 60             # stop starting new documents after this; the job's limit is 45 minutes
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": ["quarterly earnings call", "business update call", "investor or analyst meet",
                                                 "annual general meeting", "annual report", "other"],
                     "description": "What this document actually is (read it; do not assume from the file name)."},
        "period": {"type": "string", "description": "The quarter or year discussed, e.g. 'Q1 FY27 (quarter to 30 Jun 2026)'. Empty if none."},
        "headline": {"type": "string", "description": "One line: the single most important takeaway."},
        "summary": {"type": "string", "description": "Three to five plain sentences."},
        "results": {"type": "array", "items": {"type": "string"},
                    "description": "The period's reported performance as stated: revenue, EBITDA and margin, profit, segment "
                                   "figures, each with the change on a year ago (and the previous quarter where given). Empty if "
                                   "the document does not discuss results."},
        "qa": {"type": "array", "items": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "What the analyst asked, in one line."},
                           "answer": {"type": "string", "description": "Management's answer in one or two lines, with any figure; "
                                                                          "'No direct answer' if they avoided it."}},
            "required": ["question", "answer"], "additionalProperties": False},
            "description": "The main analyst questions and management's answers, in order (up to 10). Empty if there was no Q&A."},
        "changed": {"type": "array", "items": {"type": "string"},
                    "description": "What is new or different from before: new guidance, revised targets, new projects, "
                                   "changes in tone. Empty if nothing changed."},
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
    "required": ["doc_type", "period", "headline", "summary", "results", "qa", "changed", "key_points", "guidance", "risks",
                 "numbers", "management_tone", "watch_next"],
    "additionalProperties": False,
}

INSTRUCTIONS = {
    "tr": ("This is a call transcript an Indian listed company filed with NSE. First say what kind of call it is "
           "(quarterly earnings call, business update, analyst meet, AGM) and which period it covers. Then summarise "
           "it for a long-term equity investor, in this order of importance: the period's reported results with their "
           "changes (results), what is new compared with before (changed), the analysts' main questions and "
           "management's answers (qa), management's comments on demand, margins, capacity and capital allocation, and "
           "guidance. Use only figures stated in the transcript, with their units (Rs crore, %, bps). Where management "
           "avoided a question or gave no number, say so rather than inferring one."),
    "ar": ("This is an Indian listed company's annual report, filed with NSE. Summarise it for a long-term "
           "equity investor: the year's performance and its drivers, strategy and capital allocation, segment "
           "or product trends, risks management itself flags, and anything unusual in governance, related-party "
           "dealings or auditor remarks that appears in the text provided. Put the year's reported figures with "
           "their changes in results; qa stays empty. Use only figures stated in the text, with their units."),
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


TRANSIENT_CODES = (429, 500, 502, 503, 504)
TRANSIENT_WORDS = ("high demand", "unavailable", "overloaded", "disconnected", "timed out", "timeout", "connection reset")


def _transient(exc) -> bool:
    """Rate limits, overloads and dropped connections: worth another try (11 Oct 2026: a 503 "high demand"
    and a "Server disconnected" each failed a summary outright)."""
    if any(c in TRANSIENT_CODES for c in (getattr(exc, "status_code", None), getattr(exc, "code", None))):
        return True
    return any(w in str(exc).lower() for w in TRANSIENT_WORDS)


def ask_gemini(client, pdf: bytes | None, text: str | None, instructions: str) -> tuple[str, str]:
    """(JSON text, model used). On a rate limit, an overload or a dropped connection: the same model again
    after 20 s, then the lighter free model (GEMINI_FALLBACK_MODEL), twice."""
    part = ({"type": "document", "data": base64.b64encode(pdf).decode("ascii"), "mime_type": "application/pdf"}
            if pdf is not None else {"type": "text", "text": text})
    fmt = {"type": "text", "mime_type": "application/json", "schema": SCHEMA}
    last = None
    for model, wait in ((GEMINI_MODEL, 0), (GEMINI_MODEL, 20), (GEMINI_FALLBACK_MODEL, 0), (GEMINI_FALLBACK_MODEL, 30)):
        if wait:
            time.sleep(wait)
        try:
            r = client.interactions.create(model=model, input=[part, {"type": "text", "text": instructions}],
                                           response_format=fmt)
            return r.output_text, model
        except Exception as exc:
            if not _transient(exc):
                raise
            last = exc
    raise last


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
    try:                           # a call that hangs must not use up the job (23 Oct 2026): 4 minutes per request
        from google.genai import types
        return genai.Client(http_options=types.HttpOptions(timeout=240_000))
    except Exception:
        return genai.Client()      # reads GEMINI_API_KEY


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
        have = done.get(sym, {}).get(kind) or {}
        if latest and have.get("url") != latest["url"]:
            return latest
        # 12 Oct 2026: summaries written before doc_type / results / Q&A existed are redone when asked for
        if latest and symbol and "doc_type" not in (have.get("summary") or {}):
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
    SUMMARIES_FILE.parent.mkdir(parents=True, exist_ok=True)

    def save():
        SUMMARIES_FILE.write_text(json.dumps(done, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # 23 Oct 2026: the job was cancelled at its 45-minute limit on 20, 22 and 23 Oct, silently and with every finished
    # summary lost (the file was written only at the end). Now each summary is saved as it is made, progress is printed,
    # and the run stops by itself after TIME_BUDGET_S so the save-to-private-repo step still runs; the rest wait for tomorrow.
    started = time.monotonic()
    for n, (sym, kind, doc) in enumerate(todo, 1):
        if time.monotonic() - started > TIME_BUDGET_S:
            report["deferred"] = [f"{s}:{k}" for s, k, _ in todo[n - 1:]]
            print(f"[summaries] time budget used: {len(report['deferred'])} left for the next run", flush=True)
            break
        t0 = time.monotonic()
        try:
            done.setdefault(sym, {})[kind] = summarise(client, kind, doc)
            report["done"].append(f"{sym}:{kind}")
            status(sym, "done", "Summarised.")
        except Exception as exc:
            report["failed"].append({"doc": f"{sym}:{kind}", "error": str(exc)[:200]})
            status(sym, "error", f"Could not summarise the {'transcript' if kind == 'tr' else 'annual report'}: {str(exc)[:160]}")
        save()
        print(f"[summaries] {n}/{len(todo)} {sym}:{kind} {'ok' if report['done'] and report['done'][-1] == f'{sym}:{kind}' else 'failed'} in {time.monotonic() - t0:.0f}s", flush=True)
    save()
    # 27 Oct 2026, outside review: the exact 20-23 Oct bug (cancelled, nothing saved, no trace of why) is
    # already fixed structurally above (incremental save, time budget, deferred list) -- this is a
    # regression guard, not a fix for something still broken. Reports every run, success or not: a report
    # written only on failure would never clear itself once the job starts working again.
    silent_nothing = bool(report["to_summarise"]) and not (report["done"] or report["failed"]
                                                            or report.get("deferred") or report.get("error"))
    try:
        from .source_health import report_progress
        report_progress("summaries", ok=not silent_nothing,
                        detail=(f"{report['to_summarise']} to summarise, none done/failed/deferred, no error"
                                if silent_nothing else f"{len(report['done'])} done, {len(report['failed'])} failed"))
    except Exception as exc:
        print(f"[summaries] progress report not sent: {exc}")
    return report


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
    sys.exit(0)
