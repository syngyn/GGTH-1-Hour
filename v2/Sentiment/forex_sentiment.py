"""Pipeline: news -> ensemble -> per-currency aggregation -> per-pair sentiment."""
from __future__ import annotations
import asyncio
import math
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import CONFIG
from news_fetcher import fetch_all, NewsItem
from sentiment_models import Ensemble
from currency_mapper import detect_currencies, split_pair

log = logging.getLogger(__name__)


@dataclass
class CurrencySentiment:
    currency: str
    score: float
    confidence: float
    article_count: int = 0
    contributors: List[dict] = field(default_factory=list)


@dataclass
class PairSentiment:
    pair: str
    score: float
    confidence: float
    base: Optional[CurrencySentiment] = None
    quote: Optional[CurrencySentiment] = None


def _time_decay(published: datetime,
                half_life_h: float,
                max_age_h: float) -> float:
    age_h = (datetime.now(timezone.utc) - published).total_seconds() / 3600.0
    if age_h < 0:
        age_h = 0.0
    if age_h > max_age_h:
        return 0.0
    return math.pow(0.5, age_h / half_life_h)


def aggregate(items: List[NewsItem],
              ensemble: Ensemble) -> Dict[str, CurrencySentiment]:
    by_ccy: Dict[str, dict] = {}

    for it in items:
        text = f"{it.title}. {it.summary}".strip()
        ccys = detect_currencies(text)
        if not ccys:
            continue

        score, conf, _ = ensemble.score(text)
        decay = _time_decay(it.published,
                            CONFIG.half_life_hours,
                            CONFIG.max_age_hours)
        if decay <= 0.0:
            continue
        src_w = CONFIG.source_weights.get(
            it.source, CONFIG.source_weights.get("rss", 0.5))
        weight = decay * src_w * max(0.05, conf)

        for ccy in ccys:
            d = by_ccy.setdefault(ccy, {
                "num": 0.0, "den": 0.0, "n": 0,
                "conf_num": 0.0, "conf_den": 0.0, "contrib": [],
            })
            d["num"] += weight * score
            d["den"] += weight
            d["conf_num"] += weight * conf
            d["conf_den"] += weight
            d["n"] += 1
            if len(d["contrib"]) < 5:
                age_h = (datetime.now(timezone.utc) - it.published).total_seconds() / 3600
                d["contrib"].append({
                    "title":  it.title[:160],
                    "source": it.source,
                    "score":  round(score, 3),
                    "conf":   round(conf, 3),
                    "age_h":  round(age_h, 1),
                    "url":    it.url,
                })

    out: Dict[str, CurrencySentiment] = {}
    for ccy, d in by_ccy.items():
        s = d["num"] / d["den"] if d["den"] > 1e-9 else 0.0
        c = d["conf_num"] / d["conf_den"] if d["conf_den"] > 1e-9 else 0.0
        n_factor = min(1.0, d["n"] / 10.0)         # saturate at ~10 articles
        out[ccy] = CurrencySentiment(
            currency=ccy,
            score=max(-1.0, min(1.0, s)),
            confidence=max(0.0, min(1.0, c * n_factor)),
            article_count=d["n"],
            contributors=d["contrib"],
        )
    return out


def derive_pairs(ccy: Dict[str, CurrencySentiment],
                 pairs: List[str]) -> List[PairSentiment]:
    neutral = CurrencySentiment(currency="?", score=0.0, confidence=0.0)
    out: List[PairSentiment] = []
    for p in pairs:
        b, q = split_pair(p)
        bs = ccy.get(b, neutral)
        qs = ccy.get(q, neutral)
        diff = bs.score - qs.score                 # base bullish - quote bullish
        score = max(-1.0, min(1.0, diff / 2.0))    # rescale to [-1,1]
        conf = math.sqrt(max(0.0, bs.confidence) * max(0.0, qs.confidence))
        out.append(PairSentiment(pair=p, score=score, confidence=conf,
                                 base=bs, quote=qs))
    return out


async def run_once() -> dict:
    log.info("Fetching news...")
    items = await fetch_all(CONFIG.newsapi_key, CONFIG.finnhub_key)
    log.info("Fetched %d unique articles", len(items))

    if not items:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "currencies": {}, "pairs": [],
        }

    ensemble = Ensemble(CONFIG.ensemble_weights, use_finbert=True)
    ccy_sent = aggregate(items, ensemble)
    pair_sent = derive_pairs(ccy_sent, CONFIG.pairs)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "currencies": {
            c: {
                "score":      round(s.score, 4),
                "confidence": round(s.confidence, 4),
                "n":          s.article_count,
                "contributors": s.contributors,
            }
            for c, s in ccy_sent.items()
        },
        "pairs": [
            {
                "pair":        p.pair,
                "score":       round(p.score, 4),
                "confidence":  round(p.confidence, 4),
                "base":        p.base.currency,
                "quote":       p.quote.currency,
                "base_score":  round(p.base.score, 4),
                "quote_score": round(p.quote.score, 4),
            }
            for p in pair_sent
        ],
    }