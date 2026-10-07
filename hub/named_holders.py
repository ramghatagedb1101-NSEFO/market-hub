"""
Named public shareholders above the 2-lakh nominal-value disclosure threshold, from NSE's XBRL
shareholding filing -- the primary evidence for matching a registered "marquee investor" to a real
holding: the shareholder's exact legal name on an official regulatory filing, with an exact share
count and percentage, never a fuzzy name guess and never a third-party aggregator.

The SEBI-mandated in-bse-shp taxonomy gives a public disclosure a distinct element name
("DetailsOfSharesHeldBy..."), different from the plain names used for promoter-family members
("IndividualsOrHUF", "OthersIndianShareholders") -- confirmed on a real filing (20 Microns,
2026-10-07) that carries both kinds of context in the same document. Only contexts whose base name
starts with "DetailsOfSharesHeldBy" are read here, so a promoter's spouse or child is never picked up
as an independent public holder.

A name's numeric facts (shares, percentage) use the same context id with the "D_" prefix dropped --
also confirmed against two categories (resident individuals, bodies corporate) in the same filing.
"""
import re

NAME_TAG = "NameOfTheShareholder"
PUBLIC_PREFIX = "DetailsOfSharesHeldBy"


def _all_facts(text: str, tag: str) -> list[tuple[str, str]]:
    return re.findall(r'<in-bse-shp:' + tag + r'[^>]*contextRef="([^"]*)"[^>]*>([^<]*)</in-bse-shp:' + tag + r'>', text)


def named_holders_from_text(text: str) -> list[dict]:
    """[{name, shares, pct, category}] for every public (non-promoter) named holder in the filing."""
    names = _all_facts(text, NAME_TAG)
    shares = dict(_all_facts(text, "NumberOfShares"))
    pcts = dict(_all_facts(text, "ShareholdingAsAPercentageOfTotalNumberOfShares"))
    out = []
    for ctx, raw_name in names:
        if not ctx.startswith("D_" + PUBLIC_PREFIX):
            continue   # a promoter-family member's name, not a public holder
        numeric_ctx = ctx[2:]   # same context, "D_" dropped -- how the numeric facts reference it
        name = raw_name.strip()
        if not name:
            continue
        sh = shares.get(numeric_ctx)
        pc = pcts.get(numeric_ctx)
        category = re.sub(r"_Context\d+$", "", numeric_ctx)
        category = category[len(PUBLIC_PREFIX):] if category.startswith(PUBLIC_PREFIX) else category
        out.append({
            "name": name,
            "shares": int(float(sh)) if sh not in (None, "") else None,
            "pct": round(float(pc) * 100, 4) if pc not in (None, "") else None,
            "category": category,
        })
    return out


def fetch_named_holders(xbrl_url: str) -> list[dict]:
    """Convenience wrapper: fetches the filing and reads the named holders from it. Prefer
    shareholding.fetch_xbrl_text() + named_holders_from_text() when the same filing is also read for
    institutional facts, so it is downloaded only once."""
    from . import shareholding as shp
    return named_holders_from_text(shp.fetch_xbrl_text(xbrl_url))


def _normalize(name: str) -> list[str]:
    return [w for w in re.sub(r"[^A-Za-z ]", " ", name.upper()).split() if w]


def match_registry(holders: list[dict], investors: list[dict]) -> list[dict]:
    """A holder matches a registry investor when every word of one of the investor's aliases appears
    in the holder's name, in the same order -- a first+last name match tolerates a filing's middle
    name or initial without doing any fuzzy spelling correction. Matches are evidence to review, never
    counted as confirmed automatically: the registry's own `status` field is the source of truth for
    whether an investor is confirmed, this only says a filing's name lines up with a candidate alias."""
    matches = []
    for holder in holders:
        holder_words = _normalize(holder["name"])
        for inv in investors:
            for alias in inv.get("aliases", []) + inv.get("family_aliases", []):
                alias_words = _normalize(alias)
                if not alias_words:
                    continue
                positions = []
                search_from = 0
                ok = True
                for w in alias_words:
                    try:
                        pos = holder_words.index(w, search_from)
                    except ValueError:
                        ok = False
                        break
                    positions.append(pos)
                    search_from = pos + 1
                if ok:
                    matches.append({"investor": inv["name"], "alias_matched": alias,
                                     "holder_name": holder["name"], "shares": holder["shares"],
                                     "pct": holder["pct"], "category": holder["category"]})
                    break
    return matches
