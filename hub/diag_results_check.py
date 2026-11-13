"""
Results plausibility check (13 Nov 2026 audit). Coal India's and Coforge's Jul-Sep 2026 filings carry revenue only for
the year to date, and hub/nse_results.py read that as the quarter (+199.6%, +193.5% "growth"). This runs the corrected
reader (quarter_facts) on a few companies and prints the quarter it now finds, the year-ago quarter and the growth, from
NSE's public filings only (nothing from BharatStock).
    gh workflow run diag.yml -f module=diag_results_check
"""
from . import nse_results as nr
from . import shareholding as shp

SYMS = ["COALINDIA", "COFORGE", "STLTECH", "IOB", "TCS", "RELIANCE", "TITAN", "HATSUN"]


def main():
    s = shp.session()
    for sym in SYMS:
        try:
            rows = nr.filings(s, sym)
        except Exception as e:                       # noqa: BLE001
            print(sym, "filings failed:", str(e)[:120])
            continue
        if not rows:
            print(sym, "no filings")
            continue
        latest = max(r["quarter"] for r in rows)
        nature = "consolidated" if any(r["quarter"] == latest and r["nature"] == "consolidated" for r in rows) else "standalone"
        ago = min((r["quarter"] for r in rows if r["nature"] == nature and abs((latest - r["quarter"]).days - 365) <= 20),
                  default=None, key=lambda q: abs((latest - q).days - 365))
        f1 = nr.quarter_facts(rows, latest, nature)
        f0 = nr.quarter_facts(rows, ago, nature) if ago else {}
        g = nr._growth(f1.get("revenue"), f0.get("revenue"))
        gp = nr._growth(f1.get("profit"), f0.get("profit"))
        cr = lambda v: None if v is None else round(v / 1e7)
        print(f"{sym} {nature} {latest} (from {f1.get('start')}, ytd={f1.get('ytd')}, derived={f1.get('derived')}): "
              f"revenue {cr(f1.get('revenue'))} cr vs {cr(f0.get('revenue'))} cr a year ago ({ago}) -> "
              f"{None if g is None else round(g, 1)}%; profit {cr(f1.get('profit'))} vs {cr(f0.get('profit'))} -> {None if gp is None else round(gp, 1)}%")


if __name__ == "__main__":
    main()
