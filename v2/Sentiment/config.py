"""Central configuration for the forex sentiment pipeline."""
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class Config:
    # Where the EA expects to read the JSON.
    # Per-terminal:  ...\MetaQuotes\Terminal\<broker_id>\MQL5\Files
    # Common:        ...\MetaQuotes\Terminal\Common\Files
    mt5_files_path: str = r"C:\Users\Jason\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
    output_filename: str = "forex_sentiment.json"

    # Refresh cycle
    update_interval_seconds: int = 600  # 10 minutes

    # Time decay for news age
    half_life_hours: float = 6.0
    max_age_hours: float = 48.0

    # Ensemble weights (re-normalised if a model fails to load)
    ensemble_weights: Dict[str, float] = field(default_factory=lambda: {
        "finbert":  0.50,
        "vader":    0.30,
        "textblob": 0.20,
    })

    # Optional API keys -- leave empty to run on RSS only
    newsapi_key: str = ""    # https://newsapi.org   (100/day free)
    finnhub_key: str = ""    # https://finnhub.io    (60/min free)
    marketaux_key: str = ""  # https://marketaux.com (100/day free)

    # Pairs to publish to the EA
    pairs: List[str] = field(default_factory=lambda: [
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
        "AUDUSD", "USDCAD", "NZDUSD",
    ])

    # Source quality multipliers (0..1)
    source_weights: Dict[str, float] = field(default_factory=lambda: {
        "reuters":     1.00,
        "marketwatch": 0.85,
        "fxstreet":    0.85,
        "forexlive":   0.85,
        "dailyfx":     0.80,
        "finnhub":     0.80,
        "investing":   0.75,
        "newsapi":     0.70,
        "rss":         0.60,
    })


CONFIG = Config()