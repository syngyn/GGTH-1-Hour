"""Sentiment ensemble. Each scorer returns (score in [-1,1], confidence in [0,1])."""
from dataclasses import dataclass
from typing import Dict, Tuple
import logging

log = logging.getLogger(__name__)


@dataclass
class ModelScore:
    score: float       # negative=bearish, positive=bullish
    confidence: float


class VaderScorer:
    name = "vader"

    def __init__(self):
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        self._sia = SentimentIntensityAnalyzer()

    def score(self, text: str) -> ModelScore:
        if not text:
            return ModelScore(0.0, 0.0)
        s = self._sia.polarity_scores(text)
        return ModelScore(score=s["compound"],
                          confidence=min(1.0, abs(s["compound"]) + 0.2))


class TextBlobScorer:
    name = "textblob"

    def score(self, text: str) -> ModelScore:
        if not text:
            return ModelScore(0.0, 0.0)
        from textblob import TextBlob
        b = TextBlob(text)
        pol = float(b.sentiment.polarity)
        sub = float(b.sentiment.subjectivity)
        # opinion-laden text gets discounted confidence
        return ModelScore(score=pol, confidence=max(0.1, 1.0 - 0.5 * sub))


class FinBertScorer:
    name = "finbert"

    def __init__(self, model_id: str = "ProsusAI/finbert", device: int = -1):
        from transformers import (AutoTokenizer,
                                  AutoModelForSequenceClassification,
                                  pipeline)
        tok = AutoTokenizer.from_pretrained(model_id)
        mdl = AutoModelForSequenceClassification.from_pretrained(model_id)
        self._pipe = pipeline("sentiment-analysis", model=mdl, tokenizer=tok,
                              device=device, truncation=True, max_length=512)

    def score(self, text: str) -> ModelScore:
        if not text:
            return ModelScore(0.0, 0.0)
        try:
            out = self._pipe(text[:1500])[0]
            label = out["label"].lower()
            conf = float(out["score"])
            if label.startswith("pos"):
                return ModelScore(+conf, conf)
            if label.startswith("neg"):
                return ModelScore(-conf, conf)
            return ModelScore(0.0, conf * 0.5)        # neutral
        except Exception as e:
            log.warning("finbert failed: %s", e)
            return ModelScore(0.0, 0.0)


class Ensemble:
    """Weighted, confidence-gated ensemble."""

    def __init__(self, weights: Dict[str, float], use_finbert: bool = True):
        self.weights = dict(weights)
        self.scorers = []

        if use_finbert and self.weights.get("finbert", 0) > 0:
            try:
                self.scorers.append(FinBertScorer())
            except Exception as e:
                log.error("FinBERT load failed; redistributing weight: %s", e)
                w = self.weights.pop("finbert", 0.0)
                tot = sum(self.weights.values()) or 1.0
                for k in list(self.weights.keys()):
                    self.weights[k] += w * (self.weights[k] / tot)

        if self.weights.get("vader", 0) > 0:
            self.scorers.append(VaderScorer())
        if self.weights.get("textblob", 0) > 0:
            self.scorers.append(TextBlobScorer())

        if not self.scorers:
            raise RuntimeError("No sentiment models could be loaded.")

    def score(self, text: str) -> Tuple[float, float, Dict[str, ModelScore]]:
        """Return (ensemble_score, ensemble_confidence, per_model_scores)."""
        per: Dict[str, ModelScore] = {s.name: s.score(text) for s in self.scorers}

        num = den = conf_acc = 0.0
        for name, ms in per.items():
            w = self.weights.get(name, 0.0)
            num += w * ms.confidence * ms.score
            den += w * ms.confidence
            conf_acc += w * ms.confidence

        ens = num / den if den > 1e-9 else 0.0
        return max(-1.0, min(1.0, ens)), min(1.0, conf_acc), per