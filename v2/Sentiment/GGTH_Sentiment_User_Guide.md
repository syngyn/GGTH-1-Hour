# GGTH Predictor + News Sentiment Pipeline
## User Guide — v1.18

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [File & Folder Layout](#2-file--folder-layout)
3. [First-Time Setup](#3-first-time-setup)
4. [Running the Sentiment Pipeline](#4-running-the-sentiment-pipeline)
5. [Running the GGTH Predictor (Python)](#5-running-the-ggth-predictor-python)
6. [Attaching the EA in MetaTrader 5](#6-attaching-the-ea-in-metatrader-5)
7. [The On-Chart Panel Explained](#7-the-on-chart-panel-explained)
8. [How Sentiment Affects Trading](#8-how-sentiment-affects-trading)
9. [EA Input Reference](#9-ea-input-reference)
10. [Backtesting](#10-backtesting)
11. [Troubleshooting](#11-troubleshooting)
12. [Recommended Daily Workflow](#12-recommended-daily-workflow)

---

## 1. System Overview

The system has three independent processes that work together:

```
┌─────────────────────────────────────────────────────────────┐
│  PROCESS 1 — News Sentiment Pipeline  (python main.py)      │
│  Fetches forex news every 10 min → scores sentiment →       │
│  writes forex_sentiment.json to MT5 Common Files            │
└──────────────────────────┬──────────────────────────────────┘
                           │  forex_sentiment.json
┌──────────────────────────▼──────────────────────────────────┐
│  PROCESS 2 — GGTH ML Predictor  (python unified_predictor)  │
│  Runs ML ensemble (LSTM/GRU/Transformer/TCN/LightGBM) →     │
│  writes EURUSD_ea_signal.json to MT5 Files folder           │
└──────────────────────────┬──────────────────────────────────┘
                           │  EURUSD_ea_signal.json
┌──────────────────────────▼──────────────────────────────────┐
│  PROCESS 3 — GGTH EA  (GGTH_2026_v18.mq5 in MT5)           │
│  Reads both files → applies ML signal + sentiment veto →    │
│  executes trades on EURUSD M5 chart                         │
└─────────────────────────────────────────────────────────────┘
```

**Key principle:** The three processes are independent. Each one can be restarted without affecting the others. The EA reads files — it never talks to Python directly.

---

## 2. File & Folder Layout

### Python project folder (wherever you keep your scripts)
```
your_project_folder\
├── unified_predictor_v9.py     ← ML prediction engine
├── ggth_gui.py                 ← GUI launcher for the predictor
├── main.py                     ← Sentiment pipeline entry point
├── config.py                   ← Sentiment pipeline settings
├── forex_sentiment.py          ← Sentiment aggregation logic
├── news_fetcher.py             ← RSS + API news fetcher
├── sentiment_models.py         ← FinBERT / VADER / TextBlob ensemble
├── sentiment_reader_py.py      ← Python-side sentiment reader utility
├── sentiment_writer.py         ← Atomic JSON writer
├── currency_mapper.py          ← Keyword → currency mapping
├── requirements.txt            ← Python dependencies
├── run_ggth_gui.bat            ← Double-click launcher (recommended)
└── setup_wizard.bat            ← First-time MT5 path configurator
```

### MT5 Common Files folder
```
C:\Users\Jason\AppData\Roaming\MetaQuotes\Terminal\Common\Files\
└── forex_sentiment.json        ← Written by main.py, read by EA
```

### MT5 Terminal Files folder (per-broker)
```
...\MetaQuotes\Terminal\<broker_hash>\MQL5\Files\
├── EURUSD_ea_signal.json       ← Written by predictor, read by EA
├── EURUSD_status.json          ← Python veto + regime + heartbeat
├── EURUSD_trade_journal_entries.csv
└── EURUSD_trade_journal_exits.csv
```

### MT5 Experts folder
```
...\MQL5\Experts\
└── GGTH_2026_v18.mq5           ← Compile and attach this
```

---

## 3. First-Time Setup

### Step 1 — Install Python dependencies

Open a command prompt in your project folder and run:

```
pip install -r requirements.txt
```

The sentiment pipeline requires `aiohttp`, `feedparser`, `vaderSentiment`, `textblob`, `transformers`, and `torch`. The predictor has additional dependencies — install those from its own requirements file if separate, or run the GUI launcher which handles it automatically.

**Note:** On first run, `transformers` will download the FinBERT model (~500 MB). This only happens once.

### Step 2 — Configure the MT5 path

Run `setup_wizard.bat` and follow the prompts. It auto-detects your MT5 installation and writes `config.json` with the correct file path. You can also run the GGTH GUI and use the **Browse…** button next to MT5 Files, then click **Save MT5 Path**.

### Step 3 — (Optional) Add API keys for more news sources

Open `config.py` and fill in any keys you have:

```python
newsapi_key:   str = "your_key_here"   # newsapi.org  — 100 req/day free
finnhub_key:   str = "your_key_here"   # finnhub.io   — 60 req/min free
marketaux_key: str = "your_key_here"   # marketaux.com — 100 req/day free
```

The pipeline runs on RSS feeds alone if no keys are provided — this is perfectly functional.

### Step 4 — Compile the EA

Copy `GGTH_2026_v18.mq5` into your `MQL5\Experts\` folder, open MetaEditor, and press **F7** to compile. Confirm there are zero errors in the Errors tab.

---

## 4. Running the Sentiment Pipeline

Open a command prompt in your project folder:

```
python main.py
```

You should see output like this within a few seconds:

```
2026-05-11 10:00:01 INFO forex_sentiment | Fetching news...
2026-05-11 10:00:04 INFO forex_sentiment | Fetched 187 unique articles
2026-05-11 10:00:12 INFO forex_sentiment | Wrote 7 pairs / 8 currencies to
    C:\...\Common\Files\forex_sentiment.json
```

The pipeline then sleeps for 10 minutes and repeats. **Leave this terminal open** while trading. It runs indefinitely until you press Ctrl+C.

### What it does each cycle

1. Fetches articles from up to 8 sources (6 RSS + any API keys you configured)
2. Deduplicates by URL hash
3. Scores each article through the three-model ensemble:
   - **FinBERT** (50% weight) — finance-tuned BERT, most accurate
   - **VADER** (30% weight) — rule-based, fast, good for headlines
   - **TextBlob** (20% weight) — general sentiment baseline
4. Applies time decay — articles older than 6 hours count half as much; articles older than 48 hours are ignored
5. Aggregates per currency (USD, EUR, GBP, JPY, CHF, AUD, CAD, NZD)
6. Derives per-pair scores by differencing base vs. quote currency scores
7. Writes the result atomically so the EA never reads a half-written file

### Verifying the output

Open `forex_sentiment.json` in the MT5 Common Files folder. A healthy file looks like:

```json
{
  "timestamp": "2026-05-11T17:00:12+00:00",
  "pairs": [
    {
      "pair": "EURUSD",
      "score": -0.107,
      "confidence": 0.38,
      "base_score": -0.071,
      "quote_score": 0.142
    }
  ]
}
```

- **score** — positive means base currency (EUR) is bullish relative to quote (USD)
- **confidence** — how much agreement across articles; below 0.30 the EA ignores it
- **timestamp** — must be within the last 30 minutes for the EA to act on it

---

## 5. Running the GGTH Predictor (Python)

Use the GUI launcher for the easiest experience:

```
run_ggth_gui.bat
```

Or launch directly:

```
python ggth_gui.py
```

### Recommended settings for live trading

| Setting | Value |
|---|---|
| Symbol | EURUSD |
| Action | **Train ALL models (multi-TF)** — first time only |
| Action | **Predict CONTINUOUSLY (multi-TF JSON)** — for live |
| Interval | 60 minutes |
| Models | LSTM + Transformer + LightGBM |
| Kalman smoothing | On |

### Workflow

1. **First time:** select Train ALL models, click Run, wait for training to complete (30–90 min depending on hardware)
2. **Every session:** select Predict CONTINUOUSLY, click Run, leave running

The predictor writes `EURUSD_ea_signal.json` to your MT5 Files folder approximately once per hour. The EA reads this file on every tick.

---

## 6. Attaching the EA in MetaTrader 5

1. Open an **EURUSD M5** chart
2. Drag `GGTH_2026_v18` from the Navigator panel onto the chart
3. In the Inputs tab, set:

| Input | Recommended Value |
|---|---|
| InpSymbol | EURUSD |
| InpTradingTimeframe | PERIOD_H1 |
| InpEnableTrading | true |
| InpFixedLot | 0.1 |
| InpMagic | 20260522 |
| InpFIFOCompliant | true (for US brokers) |
| InpProfitTargetAmount | 5.00 |
| InpUseTrendFilter | true |
| InpTrendMAPeriod | 100 |
| InpTradeMonday–Thursday | true |
| InpTradeFriday–Sunday | false |
| InpUseSentiment | true |
| InpSentimentMinConf | 0.30 |
| InpSentimentMaxAgeSec | 1800 |
| InpSentimentVetoBand | 0.20 |

4. Click OK and confirm the smiley face appears in the top-right of the chart (indicates EA is running and AutoTrading is on)

---

## 7. The On-Chart Panel Explained

The dark panel in the top-left corner shows everything happening in real time.

```
┌──────────────────────────────────────────┐
│ GGTH PREDICTOR v1.18  |  EURUSD          │  ← Title
│ Price: 1.08432    Regime: trending        │  ← Live bid + market regime
│ ──────────────────────────────────────── │
│ [OK] Watchdog  age=4m / limit=90m        │  ← Prediction freshness
│ ──────────────────────────────────────── │
│ PREDICTIONS                               │
│ 1H  UP    1.08500  (+0.06%)              │  ← 1H ML prediction
│     Acc: 45/72  (62.5%)                  │  ← Direction accuracy so far
│ 4H  DOWN  1.08100  (-0.31%)              │
│     Acc: 12/20  (60.0%)                  │
│ 1D  UP    1.09200  (+0.71%)              │
│     Acc: 5/8  (62.5%)                    │
│ ──────────────────────────────────────── │
│ NEWS SENTIMENT                            │  ← Sentiment section
│ BULLISH  score: +0.241  conf: 68%        │  ← Direction, score, confidence
│ Base: +0.312  Quote: -0.071  Age: 4m    │  ← Per-currency breakdown
│ SELL signals may be vetoed               │  ← Current veto status
└──────────────────────────────────────────┘
```

### Panel elements

**Regime** — the Python predictor classifies market conditions as `trending`, `ranging`, or `volatile`. In volatile regime, lot size is halved automatically.

**Watchdog** — shows how old the ML predictions are. Green means fresh. Red means stale and new entries are blocked (existing positions are still managed). If you see STALE, check that the predictor is running.

**Predictions** — one row per timeframe (1H, 4H, 1D). The arrow shows direction. Accuracy tracks how often the predicted direction matched reality since the EA was attached.

**Sentiment score** — ranges from -1.0 to +1.0. Positive means the base currency (EUR) has bullish news momentum relative to the quote (USD). Negative means the opposite.

**Confidence** — how consistently the three models and multiple articles agreed. Below 30% the EA ignores the sentiment reading entirely.

**Age** — how many minutes since the last sentiment update. The EA ignores readings older than 30 minutes (configurable via `InpSentimentMaxAgeSec`).

**Veto status** — tells you which trade directions are currently at risk of being blocked by sentiment. "No active veto" means sentiment is neutral and all signals pass through normally.

---

## 8. How Sentiment Affects Trading

### The veto mechanism

Sentiment acts as a **filter, not a signal**. It does not initiate trades — it only blocks trades that the ML model already wants to take, when news strongly disagrees.

A veto fires only when all three conditions are true simultaneously:

1. The sentiment file is fresh (less than 30 minutes old)
2. Confidence is at or above the minimum threshold (default 0.30)
3. The sentiment score is decisively opposite to the proposed trade direction (score magnitude exceeds the veto band, default 0.20)

If any condition is not met, the signal passes through unchanged. This is intentional — the system fails open, meaning a missing or uncertain sentiment reading never blocks a trade.

### Worked examples

**Example 1 — Veto fires:**
ML model says BUY (EURUSD predicted UP).
Sentiment score = -0.35, confidence = 0.52, age = 8 minutes.
Score -0.35 exceeds the -0.20 veto band → **BUY is blocked**.
The EA logs: `[SENTIMENT] BUY vetoed — score=-0.350 conf=0.52 age=480s`

**Example 2 — Veto does not fire (neutral sentiment):**
ML model says BUY.
Sentiment score = -0.12, confidence = 0.44, age = 5 minutes.
Score -0.12 is within the ±0.20 neutral band → **BUY proceeds normally**.

**Example 3 — Veto does not fire (low confidence):**
ML model says SELL.
Sentiment score = +0.45, confidence = 0.22, age = 3 minutes.
Confidence 0.22 is below the 0.30 minimum → **SELL proceeds normally**.

**Example 4 — Veto does not fire (stale data):**
ML model says BUY.
Sentiment score = -0.60, confidence = 0.71, age = 38 minutes.
Age 38 min exceeds the 30-minute limit → **BUY proceeds normally**.

### What sentiment does NOT do

- It does not change lot size
- It does not move stop loss or take profit levels
- It does not close open positions
- It does not generate signals on its own
- It has zero effect on backtests (intentionally disabled)

---

## 9. EA Input Reference

### Sentiment Filter group

| Input | Default | Description |
|---|---|---|
| InpUseSentiment | true | Master switch. When false, sentiment is completely ignored and no file reads occur |
| InpSentimentFile | forex_sentiment.json | Filename in MT5 Common Files. Must match the output_filename in config.py |
| InpSentimentMinConf | 0.30 | Confidence below this is treated as "no signal" — trade passes through |
| InpSentimentMaxAgeSec | 1800 | File older than this (seconds) is treated as stale — trade passes through |
| InpSentimentVetoBand | 0.20 | Score must exceed this magnitude to veto an opposite signal. Higher = less aggressive |
| InpShowSentimentPanel | true | Controls whether the NEWS SENTIMENT section appears in the on-chart panel |

### Tuning guidance

**InpSentimentMinConf** — Lower this (e.g. 0.15) to act on weaker news signals. The trade-off is more false vetoes during quiet news periods when models disagree. Raise it (e.g. 0.45) to only act on very clear news events.

**InpSentimentVetoBand** — Lower this (e.g. 0.10) to veto more aggressively on smaller sentiment differences. Raise it (e.g. 0.35) to only veto when news is strongly one-directional. The default 0.20 is a balanced starting point.

**InpSentimentMaxAgeSec** — 1800 seconds (30 minutes) aligns with the 10-minute update cycle, giving three missed cycles before stale. Reduce to 1200 (20 minutes) for stricter freshness requirements during volatile sessions.

---

## 10. Backtesting

### How to run a clean backtest

1. Open MT5 Strategy Tester (Ctrl+R)
2. Select `GGTH_2026_v18` as the Expert
3. Set symbol to EURUSD, timeframe to M5
4. Enable **InpStrategyTesterMode = true** in the inputs
5. Place your CSV prediction files in the MT5 Files folder (generated by the predictor's `backtest` or `safe-backtest` mode)
6. Run the test

### Why sentiment is automatically disabled in backtests

When MT5 runs a backtest, the EA detects it via `MQLInfoInteger(MQL_TESTER)`. The sentiment file reader immediately marks the snapshot invalid and returns without reading any file. This happens before any veto logic runs.

This design is intentional and correct. There is no historical sentiment archive — the pipeline only stores the current snapshot. If sentiment were active during backtests, it would apply today's news to bars from months or years ago, which is severe look-ahead bias and would produce meaningless results.

Your backtest results represent the ML prediction engine performance only. This is the right baseline — the ML model is the trading edge. Sentiment is a live-only risk filter that may reduce drawdown and filter out trades during adverse news conditions, but its effect cannot be quantified in backtests without a separate historical sentiment database.

---

## 11. Troubleshooting

### Sentiment panel shows "No data — run: python main.py"

The EA cannot find or read `forex_sentiment.json`. Check:

- Is `main.py` running in a terminal? It must stay open.
- Does `forex_sentiment.json` exist in `C:\Users\Jason\AppData\Roaming\MetaQuotes\Terminal\Common\Files\`?
- Is the filename in `config.py` (`output_filename`) exactly the same as `InpSentimentFile` in the EA?
- Check that `config.py` has `mt5_files_path` pointing to the Common Files folder (the one with `Common` in the path, not a per-broker terminal folder)

### Watchdog shows STALE — ENTRIES BLOCKED

The ML predictor has not written a fresh signal recently. The EA continues managing open positions but will not open new trades. Check:

- Is the GGTH GUI running in Predict CONTINUOUSLY mode?
- Check the GUI log for Python errors
- Confirm `EURUSD_ea_signal.json` exists in your MT5 Files folder and has a recent timestamp

### Sentiment confidence is always very low

This usually means FinBERT failed to load and the weight fell back to VADER and TextBlob only. Check the terminal running `main.py` for a line like:

```
ERROR sentiment_models | FinBERT load failed; redistributing weight
```

If so, verify `torch` is installed correctly:
```
python -c "import torch; print(torch.__version__)"
```

If torch is missing: `pip install torch>=2.2`

### RSS feeds returning 0 articles

Some RSS feeds occasionally block automated requests. Check:

```
curl https://www.fxstreet.com/rss/news
```

If that fails, check your firewall or corporate proxy settings. The pipeline will still work with fewer sources — it just needs at least one feed responding.

### EA not trading despite a valid signal

Work through this checklist in order:

1. Is AutoTrading enabled? (The button in MT5 toolbar must be green)
2. Does the chart show a smiley face in the top-right?
3. Is `InpEnableTrading = true`?
4. Is the current day enabled in Trading Days inputs?
5. Is the current time within an enabled trading session?
6. Is the watchdog green?
7. Is the ML signal strong enough? (delta_pips must exceed InpMinPredictionPips, default 15)
8. Is the RSI filter blocking? (Check RSI value vs OB/OS levels)
9. Is the trend filter blocking? (Price vs MA100)
10. Is a sentiment veto active? (Check the panel veto status line)
11. Is margin utilization above InpMaxMarginUsagePct (60%)?

---

## 12. Recommended Daily Workflow

### Before the trading session

1. **Start the sentiment pipeline** — open a terminal, `cd` to your project folder, run `python main.py`. Verify the first cycle completes successfully (should take 10–15 seconds).

2. **Start the GGTH predictor** — run `run_ggth_gui.bat`, select Predict CONTINUOUSLY, click Run. Verify the GUI log shows a successful prediction write.

3. **Open MT5** — confirm the EA panel shows:
   - Watchdog: green [OK]
   - Sentiment: showing a score (not "No data")
   - All three timeframe predictions populated

### During the session

- Glance at the panel periodically. The sentiment section updates every 10 minutes.
- If the veto status changes to "BUY signals may be vetoed" or "SELL signals may be vetoed", the EA will automatically filter signals in that direction for as long as the news signal persists.
- The watchdog age increments every minute. It will turn red if the predictor stops. Restart the GUI if this happens.

### After the session

- Stop the GGTH GUI (click the Stop button)
- You can leave `main.py` running 24/7 — it uses minimal resources and keeps the sentiment file fresh for when you return
- Review `EURUSD_trade_journal_entries.csv` and `EURUSD_trade_journal_exits.csv` in your MT5 Files folder for a full record of every trade

### Weekly

- Check prediction accuracy in the on-chart panel. Consistent accuracy above 55% on any timeframe is a good sign. Below 50% over a large sample (50+ predictions) warrants retraining.
- Retrain models: open the GUI, select Train ALL models (multi-TF), click Run.
