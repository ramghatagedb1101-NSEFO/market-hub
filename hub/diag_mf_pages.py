"""16 Nov 2026 audit: the stock report's fund list stops at 100 schemes (Titan) while the batch counts 372. Prints, per
page of BharatStock's mf-holdings for one company, the row count and the pagination block (no scheme names or figures)."""
import os
import sys

import requests

from .multibagger import MFH, UA


def main() -> int:
    sym = (sys.argv[1] if len(sys.argv) > 1 else "TITAN").upper()
    key = os.environ["BHARATSTOCK_API_KEY"]
    for page in (1, 2, 3, 4, 5):
        url = MFH.format(t=sym) + f"?page_size=100&page={page}"
        r = requests.get(url, headers={"X-API-Key": key, **UA}, timeout=30)
        body = r.json() if r.status_code == 200 else {}
        rows = body.get("data", []) if isinstance(body, dict) else body
        dates = sorted({str(x.get("as_of_date") or x.get("portfolio_date") or x.get("date") or "")[:10] for x in rows})
        print(f"page {page}: HTTP {r.status_code}, rows {len(rows)}, pagination {body.get('pagination') if isinstance(body, dict) else None}, "
              f"top-level keys {sorted(body.keys()) if isinstance(body, dict) else 'list'}, dates {dates[:3]}..{dates[-2:]}")
        if not rows:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
