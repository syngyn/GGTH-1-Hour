"""
sentiment_reader_py.py
----------------------
Lightweight reader for forex_sentiment.json produced by the sentiment
pipeline (Sentiment/main.py). Used by unified_predictor_v9.py to inject
sentiment into the flat ea_signal file so the EA reads a single source.

Design notes:
- Stateless reads (re-parse each call) so a stale-file check is trivial.
- Returns None on any failure; predictor must treat absence as "no signal".
- Age is computed against the JSON's own timestamp, not file mtime,
  so atomic-write replacements don't reset it.
- Symbol normalisation matches the sentiment pipeline (uppercased, no slash).
"""
from __future__ import annotations
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class SentimentSnapshot:
    pair: str
    score: float            # [-1, 1]  positive => base strong vs quote
    confidence: float       # [0, 1]
    base: str
    quote: str
    base_score: float
    quote_score: float
    age_seconds: float      # how old is the underlying snapshot

    def is_fresh(self, max_age_s: int) -> bool:
        return self.age_seconds <= max_age_s

    def is_actionable(self, min_conf: float, max_age_s: int) -> bool:
        return self.confidence >= min_conf and self.is_fresh(max_age_s)


class SentimentReader:
    """Read per-pair sentiment from forex_sentiment.json."""

    def __init__(self, json_path: str):
        self.json_path = json_path

    def _exists(self) -> bool:
        return os.path.isfile(self.json_path)

    def read(self, pair: str) -> Optional[SentimentSnapshot]:
        """Return a SentimentSnapshot for `pair`, or None if missing/stale/invalid."""
        if not self._exists():
            log.debug("sentiment file not found: %s", self.json_path)
            return None
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            log.warning("sentiment read failed: %s", e)
            return None

        # Compute snapshot age from the JSON timestamp, not file mtime.
        ts_str = data.get("timestamp")
        if not ts_str:
            return None
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            return None
        age_s = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())

        target = pair.upper().replace("/", "")
        for entry in data.get("pairs", []):
            if entry.get("pair", "").upper() == target:
                try:
                    return SentimentSnapshot(
                        pair=entry["pair"],
                        score=float(entry.get("score", 0.0)),
                        confidence=float(entry.get("confidence", 0.0)),
                        base=entry.get("base", ""),
                        quote=entry.get("quote", ""),
                        base_score=float(entry.get("base_score", 0.0)),
                        quote_score=float(entry.get("quote_score", 0.0)),
                        age_seconds=age_s,
                    )
                except (KeyError, TypeError, ValueError) as e:
                    log.warning("malformed sentiment entry for %s: %s", target, e)
                    return None
        return None


def apply_sentiment_to_signal(
    sentiment: Optional[SentimentSnapshot],
    signal_buy: bool,
    signal_sell: bool,
    *,
    mode: str = "veto",                # "veto" | "bias" | "off"
    min_confidence: float = 0.30,
    max_age_seconds: int = 1800,
    veto_band: float = 0.20,           # |score| > band required to veto opposite
    bias_weight: float = 0.30,         # for "bias" mode, blend factor
    raw_strength: float = 0.0,         # for "bias" mode, original signal strength
) -> tuple[bool, bool, dict]:
    """
    Apply sentiment to a buy/sell signal pair. Returns:
       (new_signal_buy, new_signal_sell, info_dict)

    info_dict always includes the keys:
       sentiment_score, sentiment_confidence, sentiment_age_s,
       sentiment_action ("none"|"veto_buy"|"veto_sell"|"bias_added"),
       sentiment_used (bool)

    Failure modes are handled fail-open: if sentiment is missing, stale, or
    below min_confidence, the original signals pass through unmodified.
    """
    info = {
        "sentiment_score": 0.0,
        "sentiment_confidence": 0.0,
        "sentiment_age_s": -1.0,
        "sentiment_action": "none",
        "sentiment_used": False,
    }

    if mode == "off" or sentiment is None:
        return signal_buy, signal_sell, info

    info["sentiment_score"] = sentiment.score
    info["sentiment_confidence"] = sentiment.confidence
    info["sentiment_age_s"] = sentiment.age_seconds

    if not sentiment.is_actionable(min_confidence, max_age_seconds):
        return signal_buy, signal_sell, info

    info["sentiment_used"] = True

    if mode == "veto":
        # Veto only when sentiment is decisively in the OPPOSITE direction
        if signal_buy and sentiment.score < -veto_band:
            info["sentiment_action"] = "veto_buy"
            return False, signal_sell, info
        if signal_sell and sentiment.score > +veto_band:
            info["sentiment_action"] = "veto_sell"
            return signal_buy, False, info
        return signal_buy, signal_sell, info

    if mode == "bias":
        # Confidence-scaled additive bias on a [-1,1] strength axis.
        # Caller passes raw_strength; we return new gates based on blended.
        bias = sentiment.score * sentiment.confidence
        blended = (1.0 - bias_weight) * raw_strength + bias_weight * bias
        info["sentiment_action"] = "bias_added"
        info["sentiment_blended_strength"] = blended
        # Caller decides how to re-threshold blended; we leave gates alone.
        return signal_buy, signal_sell, info

    return signal_buy, signal_sell, info