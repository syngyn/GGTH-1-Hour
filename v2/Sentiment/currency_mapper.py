"""Map free-text news to currencies via keyword regex."""
import re
from typing import Dict, List, Set, Tuple

CURRENCY_KEYWORDS: Dict[str, List[str]] = {
    "USD": [
        r"\busd\b", r"\bdollar\b", r"\bgreenback\b",
        r"\bfederal reserve\b", r"\bfed\b", r"\bfomc\b", r"\bpowell\b",
        r"\btreasur(?:y|ies)\b", r"\bnonfarm\b", r"\bnfp\b",
        r"\bcpi\b", r"\bppi\b", r"\bism\b", r"\bjolts\b", r"\bdxy\b",
        r"\bunited states\b", r"\bu\.s\.\b",
    ],
    "EUR": [
        r"\beur\b", r"\beuro\b", r"\becb\b", r"\blagarde\b", r"\bdraghi\b",
        r"\beuro area\b", r"\beurozone\b", r"\bbund\b",
        r"\bgermany\b", r"\bfrance\b", r"\bitaly\b", r"\bspain\b",
    ],
    "GBP": [
        r"\bgbp\b", r"\bsterling\b", r"\bpound\b", r"\bcable\b",
        r"\bbank of england\b", r"\bboe\b", r"\bbailey\b",
        r"\buk\b", r"\bunited kingdom\b", r"\bbritain\b", r"\bbritish\b",
    ],
    "JPY": [
        r"\bjpy\b", r"\byen\b", r"\bbank of japan\b", r"\bboj\b",
        r"\bueda\b", r"\bkuroda\b", r"\bjapan\b", r"\bjapanese\b",
        r"\btokyo\b", r"\bjgb\b",
    ],
    "CHF": [
        r"\bchf\b", r"\bfranc\b", r"\bswiss\b", r"\bswitzerland\b",
        r"\bsnb\b", r"\bjordan\b",
    ],
    "AUD": [
        r"\baud\b", r"\baussie\b", r"\baustralia\b", r"\baustralian\b",
        r"\brba\b", r"\biron ore\b",
    ],
    "CAD": [
        r"\bcad\b", r"\bloonie\b", r"\bcanada\b", r"\bcanadian\b",
        r"\bbank of canada\b", r"\bboc\b", r"\bmacklem\b",
    ],
    "NZD": [
        r"\bnzd\b", r"\bkiwi\b", r"\bnew zealand\b", r"\brbnz\b",
    ],
}

_COMPILED = {ccy: [re.compile(p, re.IGNORECASE) for p in pats]
             for ccy, pats in CURRENCY_KEYWORDS.items()}


def detect_currencies(text: str) -> Set[str]:
    if not text:
        return set()
    found = set()
    for ccy, patterns in _COMPILED.items():
        for p in patterns:
            if p.search(text):
                found.add(ccy)
                break
    return found


def split_pair(pair: str) -> Tuple[str, str]:
    p = pair.upper().replace("/", "")
    return p[:3], p[3:6]