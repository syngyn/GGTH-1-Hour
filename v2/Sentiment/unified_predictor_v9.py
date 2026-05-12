"""
Multi-Timeframe Predictor v9.5
Author: Jason Rusk jason.w.rusk@gmail.com
Copyright 2026

v9.5 fixes (this revision — CRITICAL):
- FIXED: ensemble weight learner was poisoned by failing models. The eval
        log stored only SUCCESSFUL model predictions in a compact list,
        but update_ensemble_weights then iterated by list position to
        attribute errors to model_errors[i]. When a model failed (e.g.
        LGBM throwing on prediction), its slot in the predictions list
        silently disappeared, the next model's error landed in its
        weight bucket, and the failing model's bucket stayed at zero
        forever. The softmax weight learner interpreted zero error as
        perfect skill and rewarded the failing model with the highest
        weight — exactly how LGBM accumulated 80%+ weight on all three
        timeframes while throwing 5 cycles in a row in production.

        v9.5 makes the predictions list IDENTITY-ALIGNED: it always has
        one slot per model in models.keys() order, with None for any
        model that failed this cycle. update_ensemble_weights now skips
        None entries and tracks per-model sample counts, so a model
        with zero successful evaluations is excluded from the softmax
        entirely (its existing weight is preserved).
- ADDED: full traceback printed on the FIRST failure of each model in a
        streak. Prior code printed only the exception class+message,
        which made root-cause diagnosis impossible — five cryptic
        "fail #N" lines in the log told us nothing about what actually
        broke. The traceback prints once per streak (subsequent failures
        get the one-line message) so the log doesn't drown in repeats.
- ADDED: clearer LGBM error when prediction-time DataFrame is missing
        columns the model was trained on. Previously this raised a
        cryptic pandas KeyError from inside the iloc[-1] slice; now we
        explicitly check model.feature_name_ against df_tabular.columns
        before slicing and raise with the missing column names + a
        retrain remediation hint.

v9.4 fixes (carried forward):
- REMOVED: runtime auto-pip-install. Prior versions called pip from inside
        the predictor when an import failed, defeating the entire purpose
        of having a pinned requirements.txt — pip would happily upgrade
        tensorflow / keras / protobuf to whatever the latest tag was, and
        saved Keras 2.15 model files would refuse to deserialise with
        confusing errors. v9.4 replaces this with import-or-die: missing
        packages produce a single clear remediation message and exit(2).
        Also warns (without exiting) if installed TF/Keras versions
        differ from the requirements.txt pins.
- ADDED: flat EA-facing signal file ({symbol}_ea_signal.json). The EA
        must NEVER parse predictions_multitf.json directly — that file
        is for diagnostics and may grow nested objects between versions.
        The flat file has only top-level keys (no nesting, no arrays of
        objects) so the MQL5 string-search parser cannot go wrong. Adding
        a key is a safe operation; renaming or removing one is breaking.
- ADDED: live-trade adaptive feedback. EA trade outcomes now feed a
        Beta(α,β) posterior over realised winrate, and the resulting
        confidence_floor is published in the flat EA signal file.
- ADDED: rolling metrics rollup ({symbol}_metrics.json) written every
        cycle. Tracks per-TF MAE, directional accuracy, average predicted
        and realised % moves, veto counters, and model failure counts.

v9.3 fixes (carried forward):
- FIXED: timezone bug in last_updated_utc — was datetime.utcnow().timestamp(),
        which is the well-known Python footgun where a naive datetime is
        interpreted as LOCAL time by .timestamp(). On a Pacific-time host
        this stamped heartbeats ~7h in the future, the EA's watchdog clamped
        them to "future skew" and silently disabled staleness checking.
        Now uses time.time() which is unambiguously UTC on every platform.
- FIXED: EA→Python feedback filename mismatch. _read_ea_trade_outcomes was
        reading trade_outcomes_{symbol}.json while the EA writes to
        {symbol}_trade_outcomes.json. Every closed-trade outcome since the
        feedback loop was introduced was silently discarded. Path now
        matches the EA.
- FIXED: TOCTOU race in _read_ea_trade_outcomes. The old "read then truncate"
        pattern lost any EA write that arrived between the two operations
        (and a Python crash mid-pattern wiped the file). Replaced with
        rename-based atomic consume; combined with the EA's v1.15 atomic
        write, neither side can lose an outcome even on crash.
- FIXED: prediction_history pollution by EA outcomes. Old code appended
        EA outcomes with empty 'predictions':[] to prediction_history;
        update_ensemble_weights correctly skipped them but they still
        consumed slots in the bounded history (cap=20), pushing real
        model-error entries out faster. Now drained from feedback file
        without polluting the history.
- ADDED: atomic writes for pending_evaluations file via save_to_file.
        A crash mid-write previously corrupted the file and lost every
        queued evaluation in it.
- FIXED: log_startup_banner version string drift (was hardcoded "v8").

v9.2 fixes (carried forward):
- WIRED: GaussianHMM regime detection — was imported but never used since v8.
        New _fit_hmm_regime() runs at end of training; _detect_regime() now
        uses the persisted HMM with confidence-weighted classification and
        falls back to the original heuristic if the HMM file is absent or
        prediction throws.
- ADDED: Persisted ensemble state — weights, prediction history, and per-
        model health counters are saved to ensemble_state_{symbol}.json at
        the end of every prediction cycle and loaded at __init__. Process
        restarts no longer reset weights to equal.
- FIXED: Regime-bias model name alignment — when a model failed silently in
        the multi-TF prediction loop, model_names = list(models.keys()) kept
        the failed model in the name list, so _apply_regime_bias picked the
        wrong scalar for each remaining successful prediction. Now we track
        successful_model_names and pull weights by index from the original
        weight vector before renormalising.
- ADDED: Per-model health tracking — consecutive failures per (timeframe,
        model_name) tracked in self.model_health and persisted alongside
        ensemble state. Models exceeding HEALTH_FAIL_THRESHOLD (5) are
        excluded from subsequent cycles until the health file is reset.

v9.0 fixes (carried forward):
- REMOVED: dead duplicate UnifiedLSTMPredictor class block at top of file
           (it shadowed the real class — its session/agreement vetos were never running).
- FIXED: fwd_range_win_* targets used a backward-rolling window; now correctly
         look forward over [i+1, i+hor].
- FIXED: outlier handling in _prepare_sequential_data now winsorizes (clips)
         instead of dropping rows, preserving sequence continuity.
- FIXED: prediction cycles no longer download data twice per call.
- FIXED: run_safe_backtest no longer refits scalers at predict-time
         (was destroying the calibration baked in at training).
- FIXED: ensemble_model_types is no longer mutated re-entrantly; LGBM expansion
         is idempotent across multiple training calls in one process.
- FIXED: per-timeframe feature selection in train_model_multitimeframe.
- FIXED: _evaluate_past_predictions uses UTC consistently and uses
         copy_rates_range with a window so broker timezone offsets don't
         cause us to look up the wrong bar. Also adds 7-day expiry on
         pending evaluations so the file stops growing without bound.
- FIXED: update_ensemble_weights skips EA-feedback entries (which carry no
         per-model predictions) so they no longer dilute the per-model MAE.
- FIXED: run_continuous now subtracts cycle elapsed time from sleep so
         cycles don't drift later and later.

v8.2 fixes (carried forward):
- TCN now has residual connections and full-lookback receptive field [1,2,4,8,16]
- Per-model log-return clamps (0.5% / 1% / 2% for 1H / 4H / 1D)
- Macro data handling tolerates DXY/SPX unavailability
- GaussianHMM regime detection + DXY/SPX correlation veto (HMM finally wired in v9.2)
- Walk-Forward Backtesting structure (now actually correct in v9.0)
- GRU model option + LSTM attention head
"""
import sys
import os
import io
import warnings

# ── Windows cp1252 fix ────────────────────────────────────────────────────────
# The default Windows console encoding (cp1252) cannot encode Unicode arrows,
# em-dashes, or other non-Latin characters used in log output.  Force UTF-8
# before any print() call so we never get a UnicodeEncodeError that silently
# kills regime detection or any other diagnostic path.
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', write_through=True)
import time
import json
import pickle
import argparse
import glob
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# --- CONFIGURATION: MT5 PATH ---
try:
    from config_manager import get_mt5_files_path as get_config_mt5_path, get_config
except ImportError:
    print("=" * 80)
    print("ERROR: config_manager.py not found!")
    print("=" * 80)
    sys.exit(1)

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# ── Refactored modules ────────────────────────────────────────────────────────
from logger import get_logger, log_startup_banner



# ═════════════════════════════════════════════════════════════════════════════
# IMPORT-OR-DIE  (v9.5 — replaces the v9.3 runtime pip-install path)
# ═════════════════════════════════════════════════════════════════════════════
#
# Prior versions called `subprocess.check_call([..., "pip", "install", ...])`
# inside the predictor when an import failed. That defeats the entire
# purpose of having a pinned requirements.txt — pip would happily upgrade
# tensorflow, keras, protobuf or numpy to whatever the latest tag was, and
# saved Keras 2.15 model files would then refuse to deserialise with
# "Cannot deserialize" errors that give no hint that the real cause is a
# silent dependency upgrade.
#
# A live trading predictor must NEVER mutate its own runtime environment.
# We import everything at module load and fail loudly with a single clear
# remediation message if anything is missing.
# ═════════════════════════════════════════════════════════════════════════════

_REQUIRED_PACKAGES = [
    # (importable_name, pip_name_for_remediation_message)
    ("MetaTrader5",  "MetaTrader5"),
    ("pandas",       "pandas"),
    ("numpy",        "numpy"),
    ("tensorflow",   "tensorflow==2.15.0"),
    ("sklearn",      "scikit-learn"),
    ("lightgbm",     "lightgbm"),
    ("keras_tuner",  "keras-tuner"),
    ("hmmlearn",     "hmmlearn"),
]

_missing: List[Tuple[str, str]] = []
for _imp, _pip in _REQUIRED_PACKAGES:
    try:
        __import__(_imp)
    except ImportError:
        _missing.append((_imp, _pip))

if _missing:
    msg = (
        "\n" + "=" * 78 + "\n"
        "FATAL: required packages not installed.\n"
        + "=" * 78 + "\n\n"
        "Missing imports:\n"
        + "\n".join(f"  - {imp}  (pip name: {pip})" for imp, pip in _missing)
        + "\n\n"
        "This predictor will NOT auto-install dependencies. The pinned\n"
        "versions in requirements.txt exist for a reason: tensorflow/keras\n"
        "version drift can silently invalidate trained model checkpoints.\n\n"
        "Activate your venv and run:\n"
        f"    {sys.executable} -m pip install -r requirements.txt\n\n"
        "Then restart the predictor.\n"
        + "=" * 78
    )
    print(msg, file=sys.stderr)
    sys.exit(2)

# All third-party imports below are safe — we just verified each one above.
import numpy as np
import pandas as pd
from model_builders import build_dl_model, KalmanFilter, TransformerBlock, AttentionLayer
from hmmlearn.hmm import GaussianHMM
import MetaTrader5 as mt5
import tensorflow as tf
import keras
from keras import layers
from keras.models import Model, load_model
from keras.optimizers import Adam
from keras.callbacks import EarlyStopping, ReduceLROnPlateau
from sklearn.preprocessing import RobustScaler
import lightgbm as lgb
import keras_tuner as kt

# v9.4: warn loudly if the user's installed TF/Keras differ from the pinned
# pair in requirements.txt. We don't refuse to run, because someone may
# have a perfectly valid reason to upgrade and retrain — but we make sure
# they can't miss it in the log if their existing checkpoints suddenly
# stop loading.
_PINNED_TF    = "2.15.0"
_PINNED_KERAS = "2.15.0"
if tf.__version__ != _PINNED_TF or keras.__version__ != _PINNED_KERAS:
    print(
        "\n[WARN] TensorFlow/Keras version differs from requirements.txt:\n"
        f"   installed: tf={tf.__version__}  keras={keras.__version__}\n"
        f"   pinned:    tf={_PINNED_TF}  keras={_PINNED_KERAS}\n"
        "   Saved model checkpoints from a different version may fail to\n"
        "   deserialise. If you intentionally upgraded, plan to retrain.\n",
        file=sys.stderr,
    )

warnings.filterwarnings('ignore')

np.random.seed(42)
tf.random.set_seed(42)
tf.config.run_functions_eagerly(False)

# Number of LightGBM models trained with different random seeds.
# Their spread gives an uncertainty estimate comparable to DL ensemble_std.
_LGBM_SEED_COUNT = 5
_LGBM_SEEDS      = [42, 123, 456, 789, 1011]


# --- Helper Classes ---

# KalmanFilter, TransformerBlock, AttentionLayer -> see model_builders.py


# ═════════════════════════════════════════════════════════════════════════════
# Live-trade-feedback adaptive state  (v9.4 — issue #3)
# ═════════════════════════════════════════════════════════════════════════════
#
# Prior versions read EA trade outcomes from disk and threw them away.
# v9.4 maintains a Beta(α, β) posterior over the recent realised winrate
# from EA-closed trades and translates it into a `confidence_floor` that
# the EA must clear before entering. When live winrate is poor, the
# floor rises and the EA becomes more selective; when it improves, the
# floor relaxes back toward the baseline.
#
# Why Beta? It is conjugate to Bernoulli outcomes (a win or a loss is a
# Bernoulli draw on each trade), so updating is just α += win_count and
# β += loss_count. The posterior mean μ = α / (α+β) is a smooth running
# winrate that doesn't whipsaw on a single bad trade the way a 5-trade
# moving average would.
#
# An exponential decay (DECAY_PER_TRADE) keeps the posterior responsive
# to recent regime changes — without it, a great Q1 followed by a
# disastrous Q2 would still show a posterior anchored on Q1.
#
# The translation from posterior to confidence_floor is intentionally
# conservative: a 50%+ realised winrate maps to BASELINE_FLOOR (no
# tightening), while a sub-50% realised winrate raises the floor in
# proportion to how far below 50% we are, capped at MAX_FLOOR.
# ═════════════════════════════════════════════════════════════════════════════

class AdaptiveTradingState:
    """Bayesian Beta posterior on EA-realised winrate.

    Public attributes:
        alpha, beta          — Beta distribution parameters
        n_trades_seen        — total EA outcomes incorporated
        confidence_floor     — current minimum |change_pct| the EA should require
        last_update_utc      — epoch seconds of last update

    See module-level docstring above for design rationale.
    """

    # Class-level tunables (kept as constants so behaviour is auditable
    # via `git blame` rather than buried in config). Moving them to
    # config.json is deliberately avoided — these are model-trust
    # parameters, not user-facing settings.
    PRIOR_ALPHA      = 5.0    # ~5 hypothetical wins as prior — neither uninformed nor too strong
    PRIOR_BETA       = 5.0    # ~5 hypothetical losses
    DECAY_PER_TRADE  = 0.995  # multiplicative decay applied to (α-1, β-1) before each update
    BASELINE_FLOOR   = 0.05   # 0.05% — minimum predicted move EA requires when posterior is healthy
    MAX_FLOOR        = 0.30   # 0.30% — cap when posterior is very poor (otherwise EA would never trade)
    MIN_TRADES_TO_ADAPT = 8   # don't adjust floor until we've seen this many real outcomes

    def __init__(self):
        self.alpha            = self.PRIOR_ALPHA
        self.beta             = self.PRIOR_BETA
        self.n_trades_seen    = 0
        self.confidence_floor = self.BASELINE_FLOOR
        self.last_update_utc  = 0
        # Rolling P/L history (last 50 outcomes) for diagnostics only —
        # not used in the floor calculation. Populated by ingest().
        self.recent_outcomes: List[Dict[str, Any]] = []

    # ─────────── persistence ───────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version":   1,
            "alpha":             self.alpha,
            "beta":              self.beta,
            "n_trades_seen":     self.n_trades_seen,
            "confidence_floor":  self.confidence_floor,
            "last_update_utc":   self.last_update_utc,
            "posterior_winrate": self.posterior_winrate(),
            "recent_outcomes":   self.recent_outcomes[-50:],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AdaptiveTradingState":
        # Schema gate — refuse to load forwards-incompatible files
        if d.get("schema_version", 0) != 1:
            return cls()  # fresh start
        s = cls()
        s.alpha            = float(d.get("alpha",            cls.PRIOR_ALPHA))
        s.beta             = float(d.get("beta",             cls.PRIOR_BETA))
        s.n_trades_seen    = int  (d.get("n_trades_seen",    0))
        s.confidence_floor = float(d.get("confidence_floor", cls.BASELINE_FLOOR))
        s.last_update_utc  = int  (d.get("last_update_utc",  0))
        s.recent_outcomes  = list (d.get("recent_outcomes",  []))[-50:]
        return s

    # ─────────── update ───────────

    def ingest(self, outcomes: List[Dict[str, Any]]) -> int:
        """Update the posterior with a list of EA trade outcomes.

        Each outcome dict is expected to contain at least 'profit'.
        Returns the number of outcomes actually consumed (some may be
        rejected if the dict is missing the 'profit' field).
        """
        if not outcomes:
            return 0

        consumed = 0
        for o in outcomes:
            if "profit" not in o:
                continue
            try:
                profit = float(o["profit"])
            except (TypeError, ValueError):
                continue
            # Decay first — keeps posterior responsive to regime changes.
            # Decay only the EVIDENCE portion (α-1, β-1), not the prior,
            # so a long quiet period doesn't drift back to PRIOR's mean.
            evidence_a = max(0.0, self.alpha - self.PRIOR_ALPHA) * self.DECAY_PER_TRADE
            evidence_b = max(0.0, self.beta  - self.PRIOR_BETA)  * self.DECAY_PER_TRADE
            self.alpha = self.PRIOR_ALPHA + evidence_a
            self.beta  = self.PRIOR_BETA  + evidence_b
            # Bernoulli win = profit > 0
            if profit > 0:
                self.alpha += 1.0
            else:
                self.beta  += 1.0
            self.n_trades_seen += 1
            consumed += 1
            self.recent_outcomes.append({
                "profit": round(profit, 2),
                "ts":     o.get("close_time", ""),
            })

        # Trim diagnostics buffer
        if len(self.recent_outcomes) > 50:
            self.recent_outcomes = self.recent_outcomes[-50:]

        # Re-derive confidence floor from the new posterior
        self._recompute_floor()
        self.last_update_utc = int(time.time())
        return consumed

    # ─────────── derived ───────────

    def posterior_winrate(self) -> float:
        """Mean of the Beta posterior — current best estimate of P(win)."""
        denom = self.alpha + self.beta
        return float(self.alpha / denom) if denom > 0 else 0.5

    def _recompute_floor(self) -> None:
        """Update self.confidence_floor based on posterior_winrate()."""
        if self.n_trades_seen < self.MIN_TRADES_TO_ADAPT:
            self.confidence_floor = self.BASELINE_FLOOR
            return
        wr = self.posterior_winrate()
        if wr >= 0.50:
            # Healthy — keep the baseline floor. We don't reward a winning
            # streak by lowering the floor below baseline; that just
            # encourages the EA to take low-quality trades.
            self.confidence_floor = self.BASELINE_FLOOR
        else:
            # Poor — raise the floor proportionally to how far below 0.50
            # we are. shortfall ∈ (0, 0.5]; scale into (BASELINE, MAX].
            shortfall = 0.50 - wr
            scale = shortfall / 0.50          # 0 → 1
            self.confidence_floor = (
                self.BASELINE_FLOOR
                + scale * (self.MAX_FLOOR - self.BASELINE_FLOOR)
            )


# ═════════════════════════════════════════════════════════════════════════════
# Rolling metrics rollup  (v9.4 — issue #4)
# ═════════════════════════════════════════════════════════════════════════════
#
# Per-cycle metrics: per-TF MAE, directional accuracy, average predicted move,
# average realised move, veto counts, model failure counts. Written to disk
# every cycle for monitoring; consumable by `python predictor.py report`.
# ═════════════════════════════════════════════════════════════════════════════

class MetricsTracker:
    """Per-cycle metrics aggregator.

    Holds counters and rolling per-TF MAE / directional-accuracy windows.
    Counters are zeroed on construction and incremented through the run;
    `snapshot()` returns a JSON-serialisable dict for atomic write.

    Counter semantics:
        macro_veto_count       — context['veto_active'] fired this cycle
        uncertainty_veto_count — ensemble_std exceeded threshold
        agreement_veto_count   — multi-TF agreement_score below threshold
        confidence_floor_blocks — predictions below adaptive floor
        model_failures[(tf,model)] — exceptions raised mid-prediction

    Per-TF rolling stats (deque cap WINDOW=200):
        mae_buffers[tf]        — |predicted - realised|
        direction_buffers[tf]  — 1 if sign matched, 0 otherwise
        predicted_pct_buffers  — predicted % move
        realised_pct_buffers   — realised  % move
    """

    WINDOW = 200  # cap on rolling buffers per TF

    def __init__(self):
        from collections import deque

        self.macro_veto_count        = 0
        self.uncertainty_veto_count  = 0
        self.agreement_veto_count    = 0
        self.confidence_floor_blocks = 0
        self.cycles                  = 0

        self.model_failures: Dict[str, int] = {}   # f"{tf}:{model}" → count

        self.mae_buffers           : Dict[str, Any] = {tf: deque(maxlen=self.WINDOW) for tf in ("1H", "4H", "1D")}
        self.direction_buffers     : Dict[str, Any] = {tf: deque(maxlen=self.WINDOW) for tf in ("1H", "4H", "1D")}
        self.predicted_pct_buffers : Dict[str, Any] = {tf: deque(maxlen=self.WINDOW) for tf in ("1H", "4H", "1D")}
        self.realised_pct_buffers  : Dict[str, Any] = {tf: deque(maxlen=self.WINDOW) for tf in ("1H", "4H", "1D")}

    # ─────────── recording helpers ───────────

    def record_cycle(self) -> None:
        self.cycles += 1

    def record_macro_veto(self) -> None:
        self.macro_veto_count += 1

    def record_uncertainty_veto(self) -> None:
        self.uncertainty_veto_count += 1

    def record_agreement_veto(self) -> None:
        self.agreement_veto_count += 1

    def record_floor_block(self) -> None:
        self.confidence_floor_blocks += 1

    def record_model_failure(self, tf: str, model_name: str) -> None:
        key = f"{tf}:{model_name}"
        self.model_failures[key] = self.model_failures.get(key, 0) + 1

    def record_evaluation(self, tf: str, predicted: float, realised: float,
                          start_price: float) -> None:
        """Called from _evaluate_past_predictions when a prediction matures.

        predicted / realised are absolute prices; start_price is the
        anchor at the time of the prediction. We store both the absolute
        MAE (for raw model error) and the % moves (so a 0.0001 error on
        EURUSD vs USDJPY is comparable).
        """
        if start_price <= 0:
            return
        self.mae_buffers[tf].append(abs(predicted - realised))
        # Direction: did predicted side of anchor match realised side?
        pred_dir     = 1 if predicted > start_price else (-1 if predicted < start_price else 0)
        realised_dir = 1 if realised  > start_price else (-1 if realised  < start_price else 0)
        # 0 if either side is exactly flat — uncommon but possible on D1.
        # We score as a miss; a pure-flat prediction has no actionable
        # directional signal anyway.
        match = 1 if (pred_dir != 0 and pred_dir == realised_dir) else 0
        self.direction_buffers[tf].append(match)
        self.predicted_pct_buffers[tf].append(
            ((predicted - start_price) / start_price) * 100.0
        )
        self.realised_pct_buffers[tf].append(
            ((realised - start_price) / start_price) * 100.0
        )

    # ─────────── snapshot / persist ───────────

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable rollup."""
        per_tf = {}
        for tf in ("1H", "4H", "1D"):
            mae_buf  = self.mae_buffers[tf]
            dir_buf  = self.direction_buffers[tf]
            pred_buf = self.predicted_pct_buffers[tf]
            real_buf = self.realised_pct_buffers[tf]
            n = len(mae_buf)
            if n == 0:
                per_tf[tf] = {
                    "samples": 0,
                    "mae": None,
                    "directional_accuracy": None,
                    "avg_predicted_pct": None,
                    "avg_realised_pct":  None,
                }
            else:
                per_tf[tf] = {
                    "samples": n,
                    "mae": round(float(np.mean(mae_buf)), 6),
                    "directional_accuracy": round(float(np.mean(dir_buf)), 4),
                    "avg_predicted_pct": round(float(np.mean(pred_buf)), 4),
                    "avg_realised_pct":  round(float(np.mean(real_buf)), 4),
                }
        return {
            "schema_version": 1,
            "cycles":   self.cycles,
            "saved_at_utc": int(time.time()),
            "per_timeframe": per_tf,
            "veto_counters": {
                "macro":            self.macro_veto_count,
                "uncertainty":      self.uncertainty_veto_count,
                "agreement":        self.agreement_veto_count,
                "confidence_floor": self.confidence_floor_blocks,
            },
            "model_failures": dict(self.model_failures),
        }


# --- Main Predictor Class ---

class UnifiedLSTMPredictor:
    def __init__(self, symbol: str = "EURUSD", related_symbols: Optional[List[str]] = None,
                 ensemble_model_types: Optional[List[str]] = None, use_kalman: bool = False,
                 use_multitimeframe: bool = False,
                 train_start: Optional[str] = None,
                 train_end:   Optional[str] = None,
                 predict_start: Optional[str] = None,
                 predict_end:   Optional[str] = None):
        self.log = get_logger("ggth.predictor")
        log_startup_banner("v9.5")
        self.symbol = symbol.upper()
        # --- NEW MACRO SYMBOLS ---
        self.dxy_symbol = "USDX"
        self.spx_symbol = "SPX500"

        self.related_symbols = related_symbols or ["AUDUSD", "GBPUSD"]
        self.ensemble_model_types = ensemble_model_types if ensemble_model_types is not None else ['lstm', 'transformer', 'lgbm']
        self.num_ensemble_models = len(self.ensemble_model_types)
        self.lookback_periods = 60
        self.base_path = self.get_mt5_files_path()
        self.use_kalman = use_kalman
        self.use_multitimeframe = use_multitimeframe

        # --- DATE RANGE FILTERS ---
        # Parse ISO date strings (YYYY-MM-DD) into datetime objects when provided
        def _parse_date(s: Optional[str]) -> Optional[datetime]:
            if s is None:
                return None
            try:
                return datetime.strptime(s, "%Y-%m-%d")
            except ValueError:
                raise ValueError(f"Date '{s}' must be in YYYY-MM-DD format.")

        self.train_start:   Optional[datetime] = _parse_date(train_start)
        self.train_end:     Optional[datetime] = _parse_date(train_end)
        self.predict_start: Optional[datetime] = _parse_date(predict_start)
        self.predict_end:   Optional[datetime] = _parse_date(predict_end)

        # Validate: predict window must not overlap training window
        if self.train_end and self.predict_start:
            if self.predict_start < self.train_end:
                raise ValueError(
                    f"--predict-start ({predict_start}) must be >= --train-end ({train_end}) "
                    f"to avoid look-ahead bias."
                )

        # File paths
        self.predictions_file = os.path.join(self.base_path, f"{self.symbol}_predictions_multitf.json")
        self.status_file = os.path.join(self.base_path, f"{self.symbol}_status.json")
        self.feature_scaler_path = os.path.join(self.base_path, f"feature_scaler_{self.symbol}.pkl")
        self.target_scaler_path = os.path.join(self.base_path, f"target_scaler_{self.symbol}.pkl")
        self.selected_features_path = os.path.join(self.base_path, f"selected_features_{self.symbol}.json")
        self.pending_eval_path = os.path.join(self.base_path, f"pending_evaluations_{self.symbol}.json")
        self.tuner_dir = os.path.join(self.base_path, 'tuner_results')
        # Manifest records exact train window so backtest generation can verify no overlap
        self.cutoff_manifest_path = os.path.join(self.base_path, f"training_cutoff_{self.symbol}.json")
        # v9.2: persisted ensemble state (weights + history) so process restarts
        # don't reset learned weights to equal. Loaded by load_model_assets_*.
        self.ensemble_state_path = os.path.join(self.base_path, f"ensemble_state_{self.symbol}.json")
        # v9.2: per-model health counters — consecutive failures per model.
        # When a model exceeds the consecutive-failure threshold it is marked
        # as unhealthy and excluded from the ensemble until a manual reset.
        self.model_health_path = os.path.join(self.base_path, f"model_health_{self.symbol}.json")
        # v9.2: persisted HMM regime model. Trained alongside the predictors;
        # _detect_regime uses it preferentially with the existing heuristic
        # fallback when the file isn't present (backward compat with v8/v9.1).
        self.hmm_regime_path = os.path.join(self.base_path, f"hmm_regime_{self.symbol}.pkl")

        # ─── v9.4: flat EA-facing signal + adaptive feedback + metrics ───
        # The EA must NEVER parse predictions_multitf.json directly. That
        # file is for the predictor's own diagnostics and may grow extra
        # fields, sub-objects, or change shape between versions. Instead,
        # every cycle we write a tiny flat signal file containing exactly
        # the keys the EA needs — no nesting, top-level only — so the
        # MQL5 string-search parser can never go wrong.
        self.ea_signal_path     = os.path.join(self.base_path, f"{self.symbol}_ea_signal.json")
        # Bayesian posterior state for live-trade-feedback adaptive threshold
        # (Beta(α, β) over the recent realised winrate). Tracks confidence
        # floor that the EA must clear before opening a position.
        self.adaptive_state_path = os.path.join(self.base_path, f"{self.symbol}_adaptive_state.json")
        # Rolling metrics rollup (per-TF MAE, directional accuracy, vetoes,
        # model failures, average prediction distance, average realised move).
        # Written every prediction cycle for reporting / monitoring.
        self.metrics_path        = os.path.join(self.base_path, f"{self.symbol}_metrics.json")

        self.target_column = 'fwd_log_return_1h'
        self.feature_cols: Optional[List[str]] = None
        # Per-timeframe feature lists. Multi-TF training selects features
        # against each TF's own forward target (1H momentum vs 1D trend etc.)
        # so each TF can use the features most predictive for its own horizon.
        # Falls back to self.feature_cols at inference if a TF-specific list
        # isn't present (backward compat with v8.x trained models).
        self.feature_cols_by_tf: Dict[str, List[str]] = {}
        self.models: Dict[str, Any] = {}
        self.feature_scaler = RobustScaler()
        self.target_scaler = RobustScaler()

        self.models_by_timeframe: Dict[str, Dict[str, Any]] = {}
        self.scalers_by_timeframe: Dict[str, Tuple[RobustScaler, RobustScaler]] = {}

        self.kalman_config = {
            "1H": {"Q": 0.00001, "R": 0.01},
            "4H": {"Q": 0.00005, "R": 0.02},
            "1D": {"Q": 0.0001, "R": 0.05}
        }
        self.kalman_filters = {tf: KalmanFilter(c["Q"], c["R"]) for tf, c in self.kalman_config.items()}

        self.previous_predictions = {tf: None for tf in self.kalman_config.keys()}
        self.ema_alpha = 0.3
        # Per-timeframe ensemble weights dict: {"1H": [...], "4H": [...], "1D": [...]}
        # Each list has one weight per model, summing to 1.0.
        # Keeping weights separate per timeframe lets each TF learn which model
        # is strongest on its own horizon (e.g. LGBM on ranging 4H, TCN on trending 1D).
        if self.num_ensemble_models > 0:
            equal_weight = 1.0 / self.num_ensemble_models
            self.ensemble_weights: Dict[str, List[float]] = {
                tf_key: [equal_weight] * self.num_ensemble_models
                for tf_key in self.kalman_config.keys()  # "1H", "4H", "1D"
            }
        else:
            self.ensemble_weights: Dict[str, List[float]] = {}
        self.prediction_history = {tf: [] for tf in self.kalman_config.keys()}
        self.ensemble_lookback = 20
        self.ensemble_learning_rate = 0.1

        # v9.2 — model health tracking. Per-model consecutive-failure counter;
        # a model that exceeds MODEL_HEALTH_FAIL_THRESHOLD is excluded from the
        # ensemble until manually reset. Tracked per (timeframe, model_name)
        # to avoid taking down the whole ensemble for a single TF/model fault.
        self.model_health: Dict[str, Dict[str, int]] = {
            tf: {} for tf in self.kalman_config.keys()
        }
        # v9.2 — fitted HMM regime model. Loaded lazily by _detect_regime
        # when self.hmm_regime_path exists. None means use heuristic fallback.
        self._hmm_model = None
        self._hmm_state_to_regime: Dict[int, str] = {}

        self.initialize_mt5()
        self.ensure_symbols_selected()

        # v9.2 — load persisted ensemble state (weights + prediction history +
        # model health) if a previous run left one. Safe no-op on first run.
        self._load_ensemble_state()

        # v9.4 — instantiate metrics tracker and load adaptive state.
        # MetricsTracker is intentionally in-memory only; the per-cycle
        # snapshot is what gets persisted (so a restart simply zeros the
        # rolling counters, which is the right behaviour — they'd be
        # stale after downtime anyway). AdaptiveTradingState IS persisted
        # because the Bayesian posterior IS the long-running state.
        self.metrics = MetricsTracker()
        self.adaptive = self._load_adaptive_state()

    def get_mt5_files_path(self) -> str:
        mt5_path = get_config_mt5_path()
        if not os.path.exists(mt5_path):
            sys.exit(1)
        return mt5_path

    def initialize_mt5(self) -> None:
        if not mt5.initialize():
            sys.exit(1)
        print(f"Connected to MT5: {mt5.account_info().login}")

    def ensure_symbols_selected(self):
        """Ensures DXY and SP500 are in Market Watch."""
        for s in [self.symbol, self.dxy_symbol, self.spx_symbol] + self.related_symbols:
            mt5.symbol_select(s, True)

    def _download_macro_data(self, bars: int = 300) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """
        Safely download macro data (DXY and SPX).
        Returns (df_dxy, df_spx) - either can be None if unavailable.
        """
        df_dxy = None
        df_spx = None
        
        # Try to get DXY data - check multiple possible symbol names
        dxy_symbols = [self.dxy_symbol, "USDX", "DXY", "DX", "US Dollar Index"]
        for sym in dxy_symbols:
            try:
                mt5.symbol_select(sym, True)
                data = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, bars)
                if data is not None and len(data) > 0:
                    df_dxy = pd.DataFrame(data)
                    df_dxy['time'] = pd.to_datetime(df_dxy['time'], unit='s')
                    df_dxy.set_index('time', inplace=True)
                    self.dxy_symbol = sym  # Update to working symbol
                    break
            except Exception:
                continue
        
        # Try to get SPX data - check multiple possible symbol names
        spx_symbols = [self.spx_symbol, "SPX500", "SP500", "US500", "SPX", "S&P500", "US500.cash"]
        for sym in spx_symbols:
            try:
                mt5.symbol_select(sym, True)
                data = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, bars)
                if data is not None and len(data) > 0:
                    df_spx = pd.DataFrame(data)
                    df_spx['time'] = pd.to_datetime(df_spx['time'], unit='s')
                    df_spx.set_index('time', inplace=True)
                    self.spx_symbol = sym  # Update to working symbol
                    break
            except Exception:
                continue
        
        return df_dxy, df_spx

    def _detect_regime(self, df_main: pd.DataFrame) -> str:
        """
        Classify the current market regime.

        v9.2 — now tries the persisted GaussianHMM first (the import was
        already there but the model was never used). Falls back to the
        original vol/trend heuristic when:
          - no fitted HMM file exists yet, or
          - the HMM raises during prediction (unstable transition matrix
            on a fresh-launch with an unusual feature window).

        Three regime labels are recognised, mapped to HMM states by their
        learned mean / variance characteristics in _fit_hmm_regime:
            "trending"  — state with non-zero mean log-return; TCN /
                          Transformer tend to outperform here.
            "volatile"  — state with the highest variance; all models
                          degrade but LGBM degrades least.
            "ranging"   — state with low variance and ~zero mean; LGBM
                          and mean-reversion logic perform best.

        Args:
            df_main: H1 OHLCV DataFrame (index = datetime, 'close' required).

        Returns:
            One of "trending", "volatile", "ranging", or "unknown".
        """
        try:
            close = df_main['close']
            if len(close) < 40:
                return 'unknown'

            log_ret = np.log(close / close.shift(1)).dropna()

            # ── HMM path (v9.2) ────────────────────────────────────────────
            # Lazy-load the persisted model on first call, then reuse.
            if self._hmm_model is None and os.path.exists(self.hmm_regime_path):
                try:
                    with open(self.hmm_regime_path, 'rb') as f:
                        bundle = pickle.load(f)
                    self._hmm_model = bundle['model']
                    self._hmm_state_to_regime = bundle['state_to_regime']
                    print(f"   HMM regime model loaded from "
                          f"{os.path.basename(self.hmm_regime_path)}")
                except Exception as e:
                    print(f"   HMM load failed ({e}); falling back to heuristic")
                    self._hmm_model = None

            if self._hmm_model is not None:
                try:
                    # HMM expects a 2D feature array; we use log-returns only.
                    # Use the last ~200 bars as evidence — long enough for the
                    # forward-backward to converge, short enough to reflect
                    # the CURRENT regime rather than ancient state.
                    obs_window = log_ret.iloc[-200:].values.reshape(-1, 1)
                    states = self._hmm_model.predict(obs_window)
                    current_state = int(states[-1])
                    regime = self._hmm_state_to_regime.get(current_state, 'unknown')
                    # Posterior probability of the current state — a confidence
                    # signal. Low confidence (< 0.55) means the HMM isn't sure;
                    # treat as 'ranging' (the safest default).
                    posteriors = self._hmm_model.predict_proba(obs_window)
                    confidence = float(posteriors[-1, current_state])
                    if confidence < 0.55:
                        print(f"   HMM regime: state={current_state} "
                              f"(low confidence {confidence:.2f}) → 'ranging' (safe default)")
                        return 'ranging'
                    print(f"   HMM regime: state={current_state} "
                          f"({confidence:.2f}) → {regime.upper()}")
                    return regime
                except Exception as e:
                    print(f"   HMM predict failed ({e}); falling back to heuristic")
                    # Fall through to heuristic below

            # ── Heuristic fallback (original v8/v9 behaviour) ──────────────
            # Short-term vs long-term volatility ratio
            vol_short = log_ret.iloc[-20:].std()
            vol_long  = log_ret.iloc[-100:].std() if len(log_ret) >= 100 else vol_short

            # Normalised directional slope over the last 20 bars
            # (mean log-return divided by short-term vol -> a dimensionless Z-score)
            mean_ret_short = log_ret.iloc[-20:].mean()
            trend_z = (mean_ret_short / vol_short) if vol_short > 0 else 0.0

            # Regime thresholds (calibrated for EURUSD H1; adjust if needed)
            VOL_SPIKE_RATIO = 1.6   # vol_short > 1.6 × vol_long -> volatile
            TREND_Z_THRESH  = 1.2   # |trend_z| > 1.2 -> trending

            if vol_short > VOL_SPIKE_RATIO * vol_long:
                regime = 'volatile'
            elif abs(trend_z) > TREND_Z_THRESH:
                regime = 'trending'
            else:
                regime = 'ranging'

            print(f"   Regime (heuristic): vol_ratio={vol_short/max(vol_long,1e-10):.2f}, "
                  f"trend_z={trend_z:.2f} -> {regime.upper()}")
            return regime

        except Exception as e:
            print(f"   Warning: Regime detection failed ({e}), defaulting to 'unknown'")
            return 'unknown'

    def _fit_hmm_regime(self, df_h1: pd.DataFrame) -> None:
        """
        Fit a 3-state Gaussian HMM on H1 log-returns and persist it for use
        by _detect_regime().

        Called from train_model_multitimeframe() so the HMM is refit every
        time the predictors are retrained — keeping its state mapping in sync
        with the same data distribution the predictors learned on.

        State-to-regime mapping is post-hoc, derived from the learned
        per-state mean / variance:
          - state with the highest variance → "volatile"
          - of the remaining two, state with the larger |mean| → "trending"
          - the last state → "ranging"

        This avoids the brittle "state 0 = trending, state 1 = ranging" hard-
        coding that has burned every HMM-in-finance project at some point.

        Args:
            df_h1: H1 OHLCV DataFrame (index = datetime, 'close' required).
        """
        print("\n[HMM] Fitting regime model on H1 log-returns...")
        try:
            close   = df_h1['close']
            log_ret = np.log(close / close.shift(1)).dropna().values.reshape(-1, 1)
            if len(log_ret) < 500:
                print(f"   Skipping HMM fit — only {len(log_ret)} returns "
                      "(need >= 500 for stable convergence)")
                return

            # Three states is the conventional choice for FX regime work and
            # matches the three labels the rest of the system already uses.
            # `full` covariance is overkill for univariate input — `diag` is
            # equivalent and faster.
            hmm = GaussianHMM(
                n_components=3,
                covariance_type="diag",
                n_iter=200,
                tol=1e-4,
                random_state=42,
            )
            hmm.fit(log_ret)

            # Build state-to-regime mapping
            means = hmm.means_.flatten()      # shape (3,)
            vars_ = hmm.covars_.flatten()     # shape (3,) — diag covar

            volatile_state = int(np.argmax(vars_))
            remaining = [s for s in range(3) if s != volatile_state]
            # Of the two remaining, the one with the larger |mean| is trending
            trending_state = max(remaining, key=lambda s: abs(means[s]))
            ranging_state  = [s for s in remaining if s != trending_state][0]

            state_to_regime = {
                volatile_state: 'volatile',
                trending_state: 'trending',
                ranging_state:  'ranging',
            }

            # Persist
            with open(self.hmm_regime_path, 'wb') as f:
                pickle.dump(
                    {'model': hmm, 'state_to_regime': state_to_regime},
                    f,
                )

            print("   HMM fit complete:")
            for s in range(3):
                print(f"     state {s}: mean={means[s]:+.6f} "
                      f"std={np.sqrt(vars_[s]):.6f} → {state_to_regime[s]}")
            print(f"   Saved to {os.path.basename(self.hmm_regime_path)}")

            # Replace any previously-loaded model so the same process picks up
            # the new fit immediately
            self._hmm_model = hmm
            self._hmm_state_to_regime = state_to_regime

        except Exception as e:
            print(f"   HMM fit failed ({e}); regime detection will use "
                  "heuristic fallback")
            import traceback
            traceback.print_exc()

    def _expected_dxy_sign(self) -> int:
        """
        Return the expected sign of correlation between this pair and DXY.

            -1 → pair has USD on the quote side (e.g. EURUSD, GBPUSD, AUDUSD).
                 DXY rising means USD strengthening, so the pair falls →
                 negative correlation expected.
            +1 → pair has USD on the base side (e.g. USDJPY, USDCAD, USDCHF).
                 DXY rising means USD strengthening, so the pair rises →
                 positive correlation expected.

        Returns +1 by default for non-FX symbols (gold, indices, etc.) — the
        caller should treat the macro veto as informational rather than
        authoritative for those.
        """
        sym = self.symbol.upper()
        # Heuristic: if the symbol starts with USD, USD is the base currency.
        # If it ends with USD (and doesn't start with it), USD is the quote.
        if sym.startswith('USD'):
            return +1
        if sym.endswith('USD'):
            return -1
        # Pairs with no USD leg: skip macro-direction logic by returning +1
        # (the divergence and corr checks become non-binding for these).
        return +1

    def get_market_context(self, df_main, df_dxy, df_spx):
        """
        Refined Intermarket Veto Logic.
        Handles missing macro data gracefully.
        Adds 'regime' key (trending / ranging / volatile) for ensemble biasing.
        """
        # Detect regime from price action before any macro check
        regime = self._detect_regime(df_main)

        # Default return if macro data is unavailable
        default_context = {
            "veto_active": False,
            "reasons": [],
            "z_score": 0.0,
            "dxy_corr": 0.0,
            "macro_data_available": False,
            "regime": regime,
        }
        
        # Check if we have valid macro data
        dxy_valid = (df_dxy is not None and 
                     not df_dxy.empty and 
                     'close' in df_dxy.columns and 
                     len(df_dxy) >= 24)
        spx_valid = (df_spx is not None and 
                     not df_spx.empty and 
                     'close' in df_spx.columns and 
                     len(df_spx) >= 24)
        
        if not dxy_valid or not spx_valid:
            missing = []
            if not dxy_valid:
                missing.append(f"DXY ({self.dxy_symbol})")
            if not spx_valid:
                missing.append(f"SPX ({self.spx_symbol})")
            print(f"   Note: Macro data unavailable for {', '.join(missing)} - skipping intermarket analysis")
            return default_context
        
        try:
            # 1. Calculate Z-Score for Risk Sentiment (SPX)
            spx_returns = df_spx['close'].pct_change(24)
            if spx_returns.std() == 0:
                z_score_risk = 0.0
            else:
                z_score_risk = (spx_returns.iloc[-1] - spx_returns.mean()) / spx_returns.std()

            # 2. Institutional Divergence (SMT)
            # The "expected" DXY-vs-pair correlation depends on the symbol:
            #   EURUSD/GBPUSD/AUDUSD/NZDUSD → strongly NEGATIVE (USD on quote side)
            #   USDJPY/USDCAD/USDCHF       → strongly POSITIVE (USD on base side)
            # The divergence signal fires when the actual recent slope direction
            # disagrees with the expected sign of correlation.
            dxy_slope  = df_dxy['close'].iloc[-5:].diff().mean()
            main_slope = df_main['close'].iloc[-5:].diff().mean()

            expected_sign = self._expected_dxy_sign()  # -1 for EURUSD-like, +1 for USDxxx
            if expected_sign < 0:
                # EURUSD-style: divergence = DXY and pair moving the same way
                is_divergent = (dxy_slope * main_slope) > 0
            else:
                # USDJPY-style: divergence = DXY and pair moving opposite ways
                is_divergent = (dxy_slope * main_slope) < 0

            # 3. Correlation Strength
            current_corr = df_main['close'].rolling(24).corr(df_dxy['close']).iloc[-1]

            # Handle NaN correlation
            if pd.isna(current_corr):
                current_corr = 0.0

            # --- VETO SUMMARY ---
            veto_reasons = []
            if z_score_risk < -2.0:
                veto_reasons.append("Extreme Risk-Off Panic")
            if is_divergent:
                veto_reasons.append("Macro Divergence (SMT)")
            # Weak correlation = current_corr is on the wrong side of zero or
            # too close to zero given the expected sign. For EURUSD-like
            # (expected negative), we want corr <= -0.70; for USDJPY-like
            # (expected positive), we want corr >= +0.70. Anything weaker is
            # a sign the relationship has broken down.
            if expected_sign < 0 and current_corr > -0.70:
                veto_reasons.append("Weak Inverse Correlation")
            elif expected_sign > 0 and current_corr < 0.70:
                veto_reasons.append("Weak Positive Correlation")

            return {
                "veto_active": len(veto_reasons) > 0,
                "reasons": veto_reasons,
                "z_score": round(float(z_score_risk), 2),
                "dxy_corr": round(float(current_corr), 4),
                "macro_data_available": True,
                "regime": regime,
            }
            
        except Exception as e:
            print(f"   Warning: Error in market context analysis: {e}")
            return default_context

    def download_data(self, bars: int = 35000,
                      date_from: Optional[datetime] = None,
                      date_to:   Optional[datetime] = None) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """
        Download multi-timeframe data from MT5.

        When date_from / date_to are provided the method uses copy_rates_range()
        so the returned data is strictly bounded by those dates.  This is the
        mechanism that prevents training data from leaking into the test window.

        Args:
            bars:      Number of bars (used only when no date range is given)
            date_from: Inclusive start datetime (UTC)
            date_to:   Inclusive end datetime (UTC)

        Returns:
            Tuple of (df_h1, df_h4, df_d1) DataFrames
        """
        if date_from or date_to:
            # Resolve defaults so copy_rates_range always gets explicit bounds
            _from = date_from or datetime(2000, 1, 1)
            _to   = date_to   or datetime.utcnow()
            range_str = f"{_from.strftime('%Y-%m-%d')} to {_to.strftime('%Y-%m-%d')}"
            print(f"Downloading multi-timeframe data for {self.symbol} [{range_str}]...")
            try:
                raw_h1 = mt5.copy_rates_range(self.symbol, mt5.TIMEFRAME_H1, _from, _to)
                raw_h4 = mt5.copy_rates_range(self.symbol, mt5.TIMEFRAME_H4, _from, _to)
                raw_d1 = mt5.copy_rates_range(self.symbol, mt5.TIMEFRAME_D1, _from, _to)
            except Exception as e:
                print(f"Error downloading data by range: {e}")
                return None, None, None
        else:
            print(f"Downloading multi-timeframe data for {self.symbol} (last {bars} bars)...")
            try:
                raw_h1 = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_H1, 0, bars)
                raw_h4 = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_H4, 0, bars // 4)
                raw_d1 = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_D1, 0, bars // 20)
            except Exception as e:
                print(f"Error downloading data: {e}")
                return None, None, None

        try:
            df_h1 = pd.DataFrame(raw_h1)
            df_h4 = pd.DataFrame(raw_h4)
            df_d1 = pd.DataFrame(raw_d1)

            min_bars = {"H1": 100, "H4": 50, "D1": 20}
            for df, name in [(df_h1, "H1"), (df_h4, "H4"), (df_d1, "D1")]:
                required = min_bars.get(name, 100)
                if df is None or df.empty or len(df) < required:
                    print(f"Failed to download {name} data for {self.symbol} "
                          f"(got {len(df) if df is not None else 0}, need {required})")
                    return None, None, None
                df['time'] = pd.to_datetime(df['time'], unit='s')
                df.set_index('time', inplace=True)
                df.rename(columns={'tick_volume': 'volume'}, inplace=True)

            print(f"Downloaded {len(df_h1)} H1 bars from {df_h1.index.min()} to {df_h1.index.max()}")
            return df_h1, df_h4, df_d1

        except Exception as e:
            print(f"Error processing downloaded data: {e}")
            return None, None, None

    def create_features(self, df_h1: pd.DataFrame, df_h4: pd.DataFrame, df_d1: pd.DataFrame) -> pd.DataFrame:
        """
        Create a rich multi-timeframe feature set for model training.

        Feature groups
        --------------
        H1 momentum   : log returns (1h / 4h / 1d / 1w) + 5 lagged 1h returns
        H1 volatility : ATR-14, rolling std-14, rolling std-30, vol ratio, BB width/%B
        H1 trend      : SMA-10/20/50, price-to-SMA ratios, SMA crossover ratio,
                        MACD line/signal/hist, ADX-14 with +DI / -DI
        H1 oscillators: RSI-7/14, Stochastic %K/%D
        H4 (reindexed): SMA-20/50, RSI-14, ATR-14, MACD hist,
                        price-to-SMA-20 ratio
        D1 (reindexed): SMA-20/50, RSI-14, price-to-SMA-20 ratio
        Volume/spread : tick volume (H1), spread (when available)
        Time          : hour sin/cos, day-of-week sin/cos,
                        London session flag, NY session flag,
                        London-NY overlap flag
        Targets       : fwd_log_return_1h / 4h / 1d  (excluded from feature cols)

        All indicators are computed with EWM (Wilder smoothing) where applicable
        so they match the definitions used in most professional platforms.
        OHLC raw prices are retained in the DataFrame for target computation but
        are excluded from the feature selection candidate pool in
        perform_feature_selection().

        Args:
            df_h1: H1 OHLCV DataFrame  (index = datetime, renamed tick_volume -> volume)
            df_h4: H4 OHLCV DataFrame
            df_d1: D1 OHLCV DataFrame

        Returns:
            DataFrame aligned to the H1 index with all features + targets.
        """
        print("Creating advanced features...")
        df = df_h1.copy()

        # ── Local indicator helpers ────────────────────────────────────────────
        # All helpers operate on plain pd.Series / DataFrames and return Series.
        # Using EWM with adjust=False approximates Wilder's smoothing (span = period).

        def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
            delta = close.diff()
            gain  = delta.where(delta > 0, 0.0).ewm(span=period, adjust=False).mean()
            loss  = (-delta.where(delta < 0, 0.0)).ewm(span=period, adjust=False).mean()
            return 100 - (100 / (1 + gain / (loss + 1e-8)))

        def _atr(ohlc: pd.DataFrame, period: int = 14) -> pd.Series:
            h, l, c = ohlc['high'], ohlc['low'], ohlc['close']
            tr = pd.concat([h - l,
                            (h - c.shift(1)).abs(),
                            (l - c.shift(1)).abs()], axis=1).max(axis=1)
            return tr.ewm(span=period, adjust=False).mean()

        def _adx(ohlc: pd.DataFrame, period: int = 14):
            """Returns (adx, plus_di, minus_di) as three Series."""
            h, l = ohlc['high'], ohlc['low']
            up   = h.diff()
            down = -l.diff()
            plus_dm  = np.where((up > down) & (up > 0),   up,   0.0)
            minus_dm = np.where((down > up) & (down > 0), down, 0.0)
            atr_s    = _atr(ohlc, period)
            plus_di  = (100 * pd.Series(plus_dm,  index=ohlc.index)
                            .ewm(span=period, adjust=False).mean() / (atr_s + 1e-8))
            minus_di = (100 * pd.Series(minus_dm, index=ohlc.index)
                            .ewm(span=period, adjust=False).mean() / (atr_s + 1e-8))
            dx  = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-8))
            adx = dx.ewm(span=period, adjust=False).mean()
            return adx, plus_di, minus_di

        def _macd(close: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9):
            """Returns (macd_line, signal, histogram) as three Series."""
            line   = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
            signal = line.ewm(span=sig, adjust=False).mean()
            return line, signal, line - signal

        def _bollinger(close: pd.Series, period: int = 20, n_std: float = 2.0):
            """Returns (bb_width, bb_pct) — width normalised by SMA, %B in [0,1]."""
            sma   = close.rolling(period).mean()
            std   = close.rolling(period).std()
            upper = sma + n_std * std
            lower = sma - n_std * std
            width = (upper - lower) / (sma + 1e-8)
            pct   = (close - lower) / (upper - lower + 1e-8)
            return width, pct

        def _stochastic(ohlc: pd.DataFrame, k: int = 14, d: int = 3):
            """Returns (%K, %D) both in [0, 100]."""
            lo  = ohlc['low'].rolling(k).min()
            hi  = ohlc['high'].rolling(k).max()
            pct_k = 100 * (ohlc['close'] - lo) / (hi - lo + 1e-8)
            return pct_k, pct_k.rolling(d).mean()

        def _reindex(series: pd.Series) -> pd.Series:
            """Forward-fill a lower-timeframe series onto the H1 index."""
            return series.reindex(df.index, method='ffill')

        # ── Backward-looking returns (momentum features — valid inputs) ────────
        df['log_return_1h'] = np.log(df['close'] / df['close'].shift(1))
        df['log_return_4h'] = np.log(df['close'] / df['close'].shift(4))
        df['log_return_1d'] = np.log(df['close'] / df['close'].shift(24))
        df['log_return_1w'] = np.log(df['close'] / df['close'].shift(168))

        # Lagged 1h log-returns (give the model recent direction history)
        for lag in [1, 2, 3, 5, 10]:
            df[f'log_return_lag_{lag}'] = df['log_return_1h'].shift(lag)

        # ── Volatility ────────────────────────────────────────────────────────
        df['atr_14_h1']      = _atr(df, 14)
        df['volatility_14']  = df['log_return_1h'].rolling(14).std()
        df['volatility_30']  = df['log_return_1h'].rolling(30).std()
        # Ratio of short-to-long vol: >1 -> vol spike (regime signal)
        df['vol_ratio']      = df['volatility_14'] / (df['volatility_30'] + 1e-8)

        # ── Trend — SMA crossovers and price position ─────────────────────────
        df['sma_10_h1']         = df['close'].rolling(10).mean()
        df['sma_20_h1']         = df['close'].rolling(20).mean()
        df['sma_50_h1']         = df['close'].rolling(50).mean()
        df['close_sma10_ratio'] = df['close'] / (df['sma_10_h1'] + 1e-8) - 1
        df['close_sma20_ratio'] = df['close'] / (df['sma_20_h1'] + 1e-8) - 1
        df['close_sma50_ratio'] = df['close'] / (df['sma_50_h1'] + 1e-8) - 1
        df['sma10_sma20_ratio'] = df['sma_10_h1'] / (df['sma_20_h1'] + 1e-8) - 1  # crossover signal

        # ── MACD ──────────────────────────────────────────────────────────────
        df['macd_line'], df['macd_signal'], df['macd_hist'] = _macd(df['close'])

        # ── Bollinger Bands ───────────────────────────────────────────────────
        df['bb_width'], df['bb_pct'] = _bollinger(df['close'], 20)

        # ── RSI (fast + standard) ─────────────────────────────────────────────
        df['rsi_7_h1']  = _rsi(df['close'], 7)
        df['rsi_14_h1'] = _rsi(df['close'], 14)

        # ── ADX (trend strength + directional components) ─────────────────────
        df['adx_14_h1'], df['plus_di_14_h1'], df['minus_di_14_h1'] = _adx(df, 14)

        # ── Stochastic ────────────────────────────────────────────────────────
        df['stoch_k'], df['stoch_d'] = _stochastic(df, 14, 3)

        # ── Volume ────────────────────────────────────────────────────────────
        if 'volume' in df.columns:
            vol_ma = df['volume'].rolling(20).mean()
            df['volume_ratio'] = df['volume'] / (vol_ma + 1e-8)  # normalised vs. recent average

        # ── Spread (available from MT5 rates) ─────────────────────────────────
        if 'spread' in df.columns:
            spread_ma = df['spread'].rolling(20).mean()
            df['spread_ratio'] = df['spread'] / (spread_ma + 1e-8)

      # ── H4 features (shifted 1 period BEFORE reindexing to prevent look-ahead bias) ──
        df['sma_20_h4']         = _reindex(df_h4['close'].rolling(20).mean().shift(1))
        df['sma_50_h4']         = _reindex(df_h4['close'].rolling(50).mean().shift(1))
        df['rsi_14_h4']         = _reindex(_rsi(df_h4['close'], 14).shift(1))
        df['atr_14_h4']         = _reindex(_atr(df_h4, 14).shift(1))
        _, _, macd_hist_h4      = _macd(df_h4['close'])
        df['macd_hist_h4']      = _reindex(macd_hist_h4.shift(1))
        df['close_sma20_h4_ratio'] = df['close'] / (_reindex(df_h4['close'].rolling(20).mean().shift(1)) + 1e-8) - 1

        # ── D1 features (shifted 1 period BEFORE reindexing to prevent look-ahead bias) ──
        df['sma_20_d1']            = _reindex(df_d1['close'].rolling(20).mean().shift(1))
        df['sma_50_d1']            = _reindex(df_d1['close'].rolling(50).mean().shift(1))
        df['rsi_14_d1']            = _reindex(_rsi(df_d1['close'], 14).shift(1))
        df['close_sma20_d1_ratio'] = df['close'] / (_reindex(df_d1['close'].rolling(20).mean().shift(1)) + 1e-8) - 1
        # ── Time / session features ────────────────────────────────────────────
        # Complete cyclic pairs — a sin alone carries no phase information
        hour = df.index.hour
        dow  = df.index.dayofweek
        df['hour_sin'] = np.sin(2 * np.pi * hour / 24)
        df['hour_cos'] = np.cos(2 * np.pi * hour / 24)
        df['dow_sin']  = np.sin(2 * np.pi * dow  / 7)
        df['dow_cos']  = np.cos(2 * np.pi * dow  / 7)

        # Session windows (UTC hours) — EURUSD volatility profile is session-driven
        df['session_london']  = ((hour >= 7)  & (hour < 16)).astype(np.int8)
        df['session_ny']      = ((hour >= 13) & (hour < 21)).astype(np.int8)
        df['session_overlap'] = ((hour >= 13) & (hour < 16)).astype(np.int8)

        # ── Forward-looking targets (EXCLUDED from feature cols) ──────────────
        df['fwd_log_return_1h'] = np.log(df['close'].shift(-1)  / df['close'])
        df['fwd_log_return_4h'] = np.log(df['close'].shift(-4)  / df['close'])
        df['fwd_log_return_1d'] = np.log(df['close'].shift(-24) / df['close'])

        # ── Range-outcome binary targets (Improvement 7) ──────────────────────
        # Maps directly to EA trade outcomes at ~2:1 reward:risk.
        # 1.0=target hit first  0.0=stop hit first  0.5=ambiguous / neither hit
        #
        # CRITICAL: We need max(high[i+1..i+hor]) and min(low[i+1..i+hor]) — i.e.
        # a FORWARD rolling window. Pandas only has backward rolling, so we
        # reverse, roll, reverse back, then shift(-1) so position i holds
        # the aggregate over (i+1 .. i+hor].
        # Previous version used df['high'].shift(-1).rolling(_hor).max() which
        # is mostly BACKWARD-looking with a one-bar forward peek — those targets
        # were silently leaking past data.
        for _hor, _sfx in [(4, '1h'), (16, '4h'), (96, '1d')]:
            _tgt_pct  = 0.0010   # 0.10% of price ~10 pips on EURUSD at 1.10
            _stp_pct  = 0.0005   # 0.05% of price ~ 5 pips
            _fwd_high = (df['high'][::-1]
                         .rolling(_hor, min_periods=1).max()[::-1]
                         .shift(-1))
            _fwd_low  = (df['low'][::-1]
                         .rolling(_hor, min_periods=1).min()[::-1]
                         .shift(-1))
            _tgt_hit  = (_fwd_high - df['close']) >= df['close'] * _tgt_pct
            _stp_hit  = (df['close'] - _fwd_low)  >= df['close'] * _stp_pct
            df[f'fwd_range_win_{_sfx}'] = np.where(
                _tgt_hit & ~_stp_hit, 1.0,
                np.where(~_tgt_hit & _stp_hit, 0.0, 0.5)
            )

        # ── Clean ─────────────────────────────────────────────────────────────
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.dropna(inplace=True)

        if len(df) < self.lookback_periods + 100:
            print(f"WARNING: Only {len(df)} bars after feature creation — may be insufficient for training.")

        # Count candidate features (excludes raw OHLC and targets)
        _exclude = {'open', 'high', 'low', 'close', 'volume', 'spread', 'real_volume',
                    'fwd_log_return_1h', 'fwd_log_return_4h', 'fwd_log_return_1d'}
        n_candidates = sum(1 for c in df.columns if c not in _exclude)
        print(f"   Created {n_candidates} candidate features from {len(df)} bars")
        return df

    def perform_feature_selection(self, df: pd.DataFrame, num_features: int = 30) -> pd.DataFrame:
        """
        Select most important features using LightGBM.

        Args:
            df: DataFrame with all features
            num_features: Number of top features to select (default raised to 30
                          to match the expanded candidate pool from create_features)

        Returns:
            DataFrame with selected features
        """
        print(f"Performing feature selection to find top {num_features} features...")
        target = self.target_column
        # Exclude forward-looking targets and raw OHLC price levels.
        # Backward-looking log returns (log_return_4h, log_return_1d, etc.) are
        # intentionally kept as candidate features — they carry valid momentum signal.
        exclude_cols = {
            target,
            'fwd_log_return_1h', 'fwd_log_return_4h', 'fwd_log_return_1d',
            'fwd_range_win_1h',  'fwd_range_win_4h',  'fwd_range_win_1d',
            'close', 'open', 'high', 'low',
        }
        features = [col for col in df.columns if col not in exclude_cols]

        X = df[features]
        y = df[target]

        # Train LightGBM for feature importance
        lgb_train = lgb.Dataset(X, y)
        params = {
            'objective': 'regression_l1',
            'metric': 'mae',
            'n_estimators': 200,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 1,
            'verbose': -1,
            'n_jobs': -1,
            'seed': 42
        }

        model = lgb.train(params, lgb_train, num_boost_round=100)
        feature_importance = pd.DataFrame({
            'feature': features,
            'importance': model.feature_importance()
        }).sort_values('importance', ascending=False)

        self.feature_cols = feature_importance['feature'].head(num_features).tolist()
        print(f"   Selected top {len(self.feature_cols)} features.")

        # Save selected features
        with open(self.selected_features_path, 'w') as f:
            json.dump(self.feature_cols, f)

        return df[self.feature_cols + [
            'fwd_log_return_1h', 'fwd_log_return_4h', 'fwd_log_return_1d',
            'fwd_range_win_1h',  'fwd_range_win_4h',  'fwd_range_win_1d',
            'close'
        ]]

    def _prepare_sequential_data(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Prepare sequential data for deep learning models.

        Args:
            df: DataFrame with features

        Returns:
            Tuple of (X_train, y_train, X_val, y_val)
        """
        target_col = self.target_column
        train_size = int(len(df) * 0.70)
        val_size = int(len(df) * 0.15)

        train_df = df[:train_size]
        val_df = df[train_size:train_size + val_size]

        print(f"   Target stats - Mean: {train_df[target_col].mean():.6f}, Std: {train_df[target_col].std():.6f}")

        # Winsorize (clip) extreme outliers in the target rather than dropping rows.
        # Dropping rows from a time-series breaks the sequence continuity that the
        # LSTM/GRU/Transformer/TCN rely on — a 60-bar window built after row-drops
        # would silently span gaps in real time. Clipping preserves continuity
        # while still preventing a few extreme bars from dominating MSE/Huber.
        mean_return = train_df[target_col].mean()
        std_return  = train_df[target_col].std()
        lower_clip  = mean_return - 5 * std_return
        upper_clip  = mean_return + 5 * std_return
        n_clipped = int(((train_df[target_col] < lower_clip) |
                         (train_df[target_col] > upper_clip)).sum())
        train_df = train_df.copy()
        train_df[target_col] = train_df[target_col].clip(lower_clip, upper_clip)
        print(f"   Winsorized {n_clipped} target outliers "
              f"(rows kept for sequence continuity)")

        # Initialize scalers
        self.feature_scaler = RobustScaler()
        self.target_scaler = RobustScaler()

        # Scale features and target
        train_scaled_features = self.feature_scaler.fit_transform(train_df[self.feature_cols])
        train_scaled_target = self.target_scaler.fit_transform(train_df[[target_col]])

        val_scaled_features = self.feature_scaler.transform(val_df[self.feature_cols])
        val_scaled_target = self.target_scaler.transform(val_df[[target_col]])

        print(f"   Target scaler - Center: {self.target_scaler.center_[0]:.6f}, Scale: {self.target_scaler.scale_[0]:.6f}")

        def create_sequences(features: np.ndarray, target: np.ndarray, lookback: int) -> Tuple[np.ndarray, np.ndarray]:
            """Create sequences for time series prediction."""
            X, y = [], []
            for i in range(lookback, len(features)):
                X.append(features[i - lookback:i])
                y.append(target[i])
            return np.array(X), np.array(y)

        X_train, y_train = create_sequences(train_scaled_features, train_scaled_target, self.lookback_periods)
        X_val, y_val = create_sequences(val_scaled_features, val_scaled_target, self.lookback_periods)

        print(f"   Prepared sequential data: X_train shape {X_train.shape}")
        return X_train, y_train, X_val, y_val

    def _prepare_tabular_data(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series, List[str]]:
        """
        Prepare tabular data for tree-based models.

        Args:
            df: DataFrame with features

        Returns:
            Tuple of (X_train, y_train, X_val, y_val, feature_columns)
        """
        print("Preparing tabular data for tree-based models...")
        df_tabular = df.copy()
        feature_cols_tabular = self.feature_cols[:]

        # Create lag features
        for col in self.feature_cols:
            for lag in [1, 3, 5, 10]:
                new_col = f'{col}_lag_{lag}'
                df_tabular[new_col] = df_tabular[col].shift(lag)
                if new_col not in feature_cols_tabular:
                    feature_cols_tabular.append(new_col)

        df_tabular.dropna(inplace=True)
        final_feature_cols = [c for c in feature_cols_tabular if c in df_tabular.columns]

        # Split data
        train_size = int(len(df_tabular) * 0.85)
        train_df = df_tabular[:train_size]
        val_df = df_tabular[train_size:]

        X_train = train_df[final_feature_cols]
        y_train = train_df[self.target_column]
        X_val = val_df[final_feature_cols]
        y_val = val_df[self.target_column]

        print(f"   Prepared tabular data: X_train shape {X_train.shape}")
        return X_train, y_train, X_val, y_val, final_feature_cols

    def _build_dl_model(self, model_type: str, input_shape: Tuple[int, int], hp: Optional[kt.HyperParameters] = None) -> Model:
        """Delegate to model_builders.build_dl_model — see model_builders.py for architectures."""
        return build_dl_model(model_type, input_shape, hp)

    def tune_hyperparameters(self) -> None:
        """Run hyperparameter tuning for deep learning models."""
        print("\n" + "=" * 60 + "\nStarting Hyperparameter Tuning...\n" + "=" * 60)

        # Download and prepare data
        df_h1, df_h4, df_d1 = self.download_data()
        if df_h1 is None:
            return

        df_features = self.create_features(df_h1, df_h4, df_d1)
        df_selected = self.perform_feature_selection(df_features)
        X_train, y_train, X_val, y_val = self._prepare_sequential_data(df_selected)

        # Save scalers
        with open(self.feature_scaler_path, 'wb') as f:
            pickle.dump(self.feature_scaler, f)
        with open(self.target_scaler_path, 'wb') as f:
            pickle.dump(self.target_scaler, f)

        # Create tuner
        def model_builder(hp):
            return self._build_dl_model('lstm', (X_train.shape[1], X_train.shape[2]), hp=hp)

        tuner = kt.RandomSearch(
            model_builder,
            objective='val_loss',
            max_trials=15,
            executions_per_trial=1,
            directory=self.tuner_dir,
            project_name=f'tuner_{self.symbol}'
        )

        # Run tuning
        tuner.search(
            X_train, y_train,
            epochs=50,
            validation_data=(X_val, y_val),
            callbacks=[EarlyStopping('val_loss', patience=5)]
        )

        # Display results
        best_hps = tuner.get_best_hyperparameters(num_trials=1)[0]
        print("\n--- Best Hyperparameters Found ---")
        for param, value in best_hps.values.items():
            print(f"{param}: {value}")
        print("---------------------------------\n")
        print("Tuning complete. Re-run with 'train --force' to use these new settings.")

    # ------------------------------------------------------------------
    # Training cutoff manifest
    # ------------------------------------------------------------------
    def _save_cutoff_manifest(self, actual_train_start: Optional[datetime],
                               actual_train_end:   Optional[datetime],
                               status:              str = "completed") -> None:
        """
        Persist the exact training window to disk so that backtest / predict
        commands can always verify they're not overlapping with training data.

        Args:
            actual_train_start: First bar of training data (None = beginning).
            actual_train_end:   Last bar of training data (None = latest).
            status:             "in_progress" when called before training starts,
                                "completed" when training finishes successfully.
                                _warn_if_predict_overlaps_training() treats only
                                "completed" manifests as authoritative.
        """
        manifest = {
            "symbol":       self.symbol,
            "train_start":  actual_train_start.strftime("%Y-%m-%d") if actual_train_start else None,
            "train_end":    actual_train_end.strftime("%Y-%m-%d")   if actual_train_end   else None,
            "trained_at":   datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "models":       self.ensemble_model_types,
            "status":       status,
        }
        with open(self.cutoff_manifest_path, 'w') as f:
            json.dump(manifest, f, indent=4)
        print(f"\n[MANIFEST] Training cutoff saved ({status}): {self.cutoff_manifest_path}")
        print(f"           Train window: {manifest['train_start']} -> {manifest['train_end']}")

    def _load_cutoff_manifest(self) -> Optional[Dict]:
        """Load the training cutoff manifest if it exists."""
        if os.path.exists(self.cutoff_manifest_path):
            with open(self.cutoff_manifest_path, 'r') as f:
                return json.load(f)
        return None

    def _warn_if_predict_overlaps_training(self) -> None:
        """
        Print a warning (but don't abort) if the requested prediction window
        overlaps with the recorded training window, or if the manifest
        indicates training never finished cleanly.
        """
        manifest = self._load_cutoff_manifest()
        if not manifest:
            return

        # Warn loudly if the last training run was interrupted or the
        # manifest predates the status field. Models may be partially
        # written and inference results unreliable.
        status = manifest.get("status", "unknown")
        if status != "completed":
            print("\n" + "!" * 70)
            print(f"  WARNING: training manifest status is '{status}'.")
            if status == "in_progress":
                print("  This means a previous training run started but never")
                print("  marked itself complete — it may have crashed or been killed.")
                print("  Models on disk may be partially written or stale.")
            else:
                print("  Manifest predates the v9 status field (legacy format).")
            print("  Recommend retraining: train-multitf --force")
            print("!" * 70 + "\n")

        if not manifest.get("train_end"):
            return
        train_end_dt = datetime.strptime(manifest["train_end"], "%Y-%m-%d")
        pred_start   = self.predict_start or datetime(2000, 1, 1)
        if pred_start < train_end_dt:
            print("\n" + "!" * 70)
            print("  WARNING: predict-start is INSIDE the training window.")
            print(f"  Training ended:     {manifest['train_end']}")
            print(f"  Prediction starts:  {pred_start.strftime('%Y-%m-%d')}")
            print("  This will produce look-ahead bias in the backtest results.")
            print("  Set --predict-start >= " + manifest['train_end'] + " for a clean test.")
            print("!" * 70 + "\n")

    def train_model(self, force_retrain: bool = False) -> None:
        """
        Train the ensemble of models (OLD METHOD - single timeframe).
        For multi-timeframe training, use train_model_multitimeframe() instead.

        Args:
            force_retrain: Force retraining even if models exist
        """
        print("\n" + "=" * 60 + "\nStarting Hybrid Ensemble Training (Single Timeframe)...\n" + "=" * 60)
        print("WARNING: This trains only 1H models and scales predictions.")
        print("For better results, use train_model_multitimeframe() instead.\n")

        if self.train_start or self.train_end:
            print(f"[DATE FILTER] Training data restricted to: "
                  f"{self.train_start.strftime('%Y-%m-%d') if self.train_start else 'beginning'} "
                  f"-> {self.train_end.strftime('%Y-%m-%d') if self.train_end else 'end'}\n")

        # Auto-expand 'lgbm' to _LGBM_SEED_COUNT instances for uncertainty estimation.
        # Skip if already expanded (e.g. this method called twice in one process)
        # so we don't get exponential growth of the LGBM count on each call.
        lgbm_count = self.ensemble_model_types.count('lgbm')
        if lgbm_count == 1:
            _exp = []
            for _mt in self.ensemble_model_types:
                if _mt == 'lgbm':
                    _exp.extend(['lgbm'] * _LGBM_SEED_COUNT)
                else:
                    _exp.append(_mt)
            self.ensemble_model_types = _exp
            self.num_ensemble_models = len(_exp)
            _eq = 1.0 / self.num_ensemble_models
            self.ensemble_weights = {k: [_eq] * self.num_ensemble_models for k in self.kalman_config}
            print(f'[LGBM] Expanded to {_LGBM_SEED_COUNT} seeds: {self.num_ensemble_models} total models')
        elif lgbm_count > 1:
            print(f'[LGBM] Already expanded ({lgbm_count} lgbm instances) — skipping re-expansion')

        # Check if models already exist
        model_type_counts_check = defaultdict(int)
        all_models_exist = True
        for model_type in self.ensemble_model_types:
            model_index = model_type_counts_check[model_type]
            if not os.path.exists(self._get_model_path(model_type, model_index)):
                all_models_exist = False
                break
            model_type_counts_check[model_type] += 1

        if all_models_exist and not force_retrain:
            print("All models already exist. Loading them. Use --force to retrain.")
            self.load_model_assets()
            return

        # Download and prepare data (date-bounded when args supplied)
        df_h1, df_h4, df_d1 = self.download_data(date_from=self.train_start, date_to=self.train_end)
        if df_h1 is None:
            return

        # Record an in-progress manifest BEFORE training begins. If training
        # crashes mid-run, _warn_if_predict_overlaps_training will know to
        # warn rather than treat stale models as authoritative.
        _intent_end = self.train_end or df_h1.index.max().to_pydatetime()
        self._save_cutoff_manifest(self.train_start, _intent_end, status="in_progress")

        df_features = self.create_features(df_h1, df_h4, df_d1)
        df_selected = self.perform_feature_selection(df_features)

        # Prepare data for different model types
        X_train_seq, y_train_seq, X_val_seq, y_val_seq = self._prepare_sequential_data(df_selected)
        X_train_tab, y_train_tab, X_val_tab, y_val_tab, _ = self._prepare_tabular_data(df_selected)

        # Save scalers
        with open(self.feature_scaler_path, 'wb') as f:
            pickle.dump(self.feature_scaler, f)
        with open(self.target_scaler_path, 'wb') as f:
            pickle.dump(self.target_scaler, f)

        # Try to load best hyperparameters from tuning
        best_hps = None
        try:
            tuner = kt.RandomSearch(
                lambda hp: self._build_dl_model('lstm', (X_train_seq.shape[1], X_train_seq.shape[2]), hp),
                objective='val_loss',
                directory=self.tuner_dir,
                project_name=f'tuner_{self.symbol}'
            )
            best_hps = tuner.get_best_hyperparameters(num_trials=1)[0]
            print("Found best hyperparameters from tuning.")
        except Exception:
            print("No tuning data found. Using default hyperparameters for DL models.")

        # Train each model in the ensemble
        model_type_counts = defaultdict(int)
        for model_type in self.ensemble_model_types:
            model_index = model_type_counts[model_type]
            print(f"\n--- Training Model {model_type.upper()} (Instance {model_index}) ---")
            tf.random.set_seed(42 + model_index)

            if model_type in ['lstm', 'gru', 'transformer', 'tcn']:
                # Train deep learning model
                model = self._build_dl_model(model_type, (X_train_seq.shape[1], X_train_seq.shape[2]), hp=best_hps)
                callbacks = [
                    EarlyStopping('val_loss', patience=15, restore_best_weights=True),
                    ReduceLROnPlateau('val_loss', patience=5, factor=0.5)
                ]
                model.fit(
                    X_train_seq, y_train_seq,
                    validation_data=(X_val_seq, y_val_seq),
                    epochs=150,
                    batch_size=64,
                    callbacks=callbacks,
                    verbose=1
                )
                model.save(self._get_model_path(model_type, model_index))

            elif model_type == 'lgbm':
                lgbm_seed = _LGBM_SEEDS[model_index % len(_LGBM_SEEDS)]
                model = lgb.LGBMRegressor(
                    objective='regression_l1',
                    n_estimators=1000,
                    learning_rate=0.05,
                    random_state=lgbm_seed,
                    num_leaves=63,
                    subsample=0.85,
                    colsample_bytree=0.85,
                    n_jobs=-1,
                    verbose=-1
                )
                model.fit(
                    X_train_tab, y_train_tab,
                    eval_set=[(X_val_tab, y_val_tab)],
                    eval_metric='mae',
                    callbacks=[lgb.early_stopping(100, verbose=False)]
                )
                print(f'  LGBM seed={lgbm_seed} | features={model.n_features_in_}')
                with open(self._get_model_path(model_type, model_index), 'wb') as f:
                    pickle.dump(model, f)

            model_type_counts[model_type] += 1

        print("\nEnsemble training complete and all assets saved.")
        self.load_model_assets()

        # v9.2 — fit HMM regime model alongside the predictors (see comment
        # in train_model_multitimeframe for rationale).
        self._fit_hmm_regime(df_h1)

        # Mark the manifest as completed (was 'in_progress' from before training)
        actual_end = self.train_end or (df_h1.index.max().to_pydatetime() if df_h1 is not None else None)
        self._save_cutoff_manifest(self.train_start, actual_end, status="completed")

    def train_model_multitimeframe(self, force_retrain: bool = False) -> None:
        """
        Train separate models for each timeframe (1H, 4H, 1D).
        This is the RECOMMENDED method for accurate multi-timeframe predictions.

        Args:
            force_retrain: Force retraining even if models exist
        """
        print("\n" + "=" * 60)
        print("Starting Multi-Timeframe Ensemble Training...")
        print("=" * 60 + "\n")
        print("This will train 3 separate ensembles (1H, 4H, 1D)")
        print(f"Total models to train: {len(self.ensemble_model_types) * 3}")
        print("Estimated time: 4-6 hours\n")

        if self.train_start or self.train_end:
            print(f"[DATE FILTER] Training data restricted to: "
                  f"{self.train_start.strftime('%Y-%m-%d') if self.train_start else 'beginning'} "
                  f"-> {self.train_end.strftime('%Y-%m-%d') if self.train_end else 'end'}\n")

        # Auto-expand 'lgbm' to _LGBM_SEED_COUNT instances for uncertainty estimation.
        # Skip if already expanded (e.g. this method called twice in one process)
        # so we don't get exponential growth of the LGBM count on each call.
        lgbm_count = self.ensemble_model_types.count('lgbm')
        if lgbm_count == 1:
            _exp = []
            for _mt in self.ensemble_model_types:
                if _mt == 'lgbm':
                    _exp.extend(['lgbm'] * _LGBM_SEED_COUNT)
                else:
                    _exp.append(_mt)
            self.ensemble_model_types = _exp
            self.num_ensemble_models = len(_exp)
            _eq = 1.0 / self.num_ensemble_models
            self.ensemble_weights = {k: [_eq] * self.num_ensemble_models for k in self.kalman_config}
            print(f'[LGBM] Expanded to {_LGBM_SEED_COUNT} seeds: {self.num_ensemble_models} total models')
        elif lgbm_count > 1:
            print(f'[LGBM] Already expanded ({lgbm_count} lgbm instances) — skipping re-expansion')

        # Download and prepare data (date-bounded when args supplied)
        df_h1, df_h4, df_d1 = self.download_data(date_from=self.train_start, date_to=self.train_end)
        if df_h1 is None:
            return

        # Record an in-progress manifest BEFORE training begins. If training
        # crashes mid-run (this method takes 4-6 hours so that's a real risk),
        # _warn_if_predict_overlaps_training will know to flag the models as
        # potentially incomplete rather than treat them as authoritative.
        _intent_end = self.train_end or df_h1.index.max().to_pydatetime()
        self._save_cutoff_manifest(self.train_start, _intent_end, status="in_progress")

        df_features = self.create_features(df_h1, df_h4, df_d1)

        # Define target columns for each timeframe
        timeframe_targets = {
            '1H': 'fwd_log_return_1h',
            '4H': 'fwd_log_return_4h',
            '1D': 'fwd_log_return_1d'
        }

        # ── Per-timeframe feature selection ───────────────────────────────────
        # Each TF target rewards different signal — 1H benefits from short-term
        # momentum, 1D from longer-term trend strength. Selecting the same
        # feature pool for all three (the previous behaviour, optimised only
        # for 1H) is suboptimal. We now select per-TF and save TF-tagged
        # feature lists. The 1H list also gets saved to the legacy base path
        # for backward compatibility with single-TF inference paths.
        feature_cols_by_tf: Dict[str, List[str]] = {}
        df_selected_by_tf: Dict[str, pd.DataFrame] = {}
        base_features_path = self.selected_features_path  # remember original
        for tf_name, target_col in timeframe_targets.items():
            print(f"\n[Feature Selection] {tf_name} target ({target_col})")
            self.target_column = target_col
            self.selected_features_path = base_features_path.replace(
                '.json', f'_{tf_name}.json'
            )
            df_sel_tf = self.perform_feature_selection(df_features.copy())
            feature_cols_by_tf[tf_name] = list(self.feature_cols)
            df_selected_by_tf[tf_name] = df_sel_tf
            print(f"   {tf_name}: selected {len(self.feature_cols)} features")

        # Restore legacy base path and save the 1H list there too so that any
        # single-TF inference path (run_prediction_cycle, load_model_assets)
        # keeps working without code changes elsewhere.
        self.selected_features_path = base_features_path
        with open(self.selected_features_path, 'w') as f:
            json.dump(feature_cols_by_tf['1H'], f)
        self.feature_cols_by_tf = feature_cols_by_tf
        self.feature_cols = feature_cols_by_tf['1H']  # base = 1H

        # Try to load best hyperparameters from tuning
        best_hps = None
        try:
            tuner = kt.RandomSearch(
                lambda hp: self._build_dl_model('lstm', (60, 25), hp),
                objective='val_loss',
                directory=self.tuner_dir,
                project_name=f'tuner_{self.symbol}'
            )
            best_hps = tuner.get_best_hyperparameters(num_trials=1)[0]
            print("Found best hyperparameters from tuning.")
        except Exception:
            print("No tuning data found. Using default hyperparameters.")

        # Train a separate ensemble for each timeframe
        for tf_name, target_col in timeframe_targets.items():
            print(f"\n{'=' * 60}")
            print(f"Training Ensemble for {tf_name} Predictions (Target: {target_col})")
            print(f"{'=' * 60}\n")

            # Set target column AND feature_cols for this TF — _prepare_*
            # helpers read self.feature_cols when building inputs.
            self.target_column = target_col
            self.feature_cols   = feature_cols_by_tf[tf_name]
            df_selected         = df_selected_by_tf[tf_name]

            # Prepare data with this target
            X_train_seq, y_train_seq, X_val_seq, y_val_seq = self._prepare_sequential_data(df_selected)
            X_train_tab, y_train_tab, X_val_tab, y_val_tab, _ = self._prepare_tabular_data(df_selected)

            # Save scalers for this timeframe
            scaler_suffix = f"_{tf_name}"
            with open(self.feature_scaler_path.replace('.pkl', f'{scaler_suffix}.pkl'), 'wb') as f:
                pickle.dump(self.feature_scaler, f)
            with open(self.target_scaler_path.replace('.pkl', f'{scaler_suffix}.pkl'), 'wb') as f:
                pickle.dump(self.target_scaler, f)

            # Train each model type for this timeframe
            model_type_counts = defaultdict(int)
            for model_type in self.ensemble_model_types:
                model_index = model_type_counts[model_type]
                print(f"\n--- Training {model_type.upper()} for {tf_name} (Instance {model_index}) ---")
                tf.random.set_seed(42 + model_index)

                if model_type in ['lstm', 'gru', 'transformer', 'tcn']:
                    model = self._build_dl_model(model_type, (X_train_seq.shape[1], X_train_seq.shape[2]), hp=best_hps)
                    callbacks = [
                        EarlyStopping('val_loss', patience=15, restore_best_weights=True),
                        ReduceLROnPlateau('val_loss', patience=5, factor=0.5)
                    ]
                    model.fit(
                        X_train_seq, y_train_seq,
                        validation_data=(X_val_seq, y_val_seq),
                        epochs=150,
                        batch_size=64,
                        callbacks=callbacks,
                        verbose=1
                    )
                    # Save with timeframe suffix
                    model_path = self._get_model_path(model_type, model_index).replace('.keras', f'_{tf_name}.keras')
                    model.save(model_path)
                    print(f"Saved: {model_path}")

                elif model_type == 'lgbm':
                    lgbm_seed = _LGBM_SEEDS[model_index % len(_LGBM_SEEDS)]
                    model = lgb.LGBMRegressor(
                        objective='regression_l1',
                        n_estimators=1000,
                        learning_rate=0.05,
                        random_state=lgbm_seed,
                        num_leaves=63,
                        subsample=0.85,
                        colsample_bytree=0.85,
                        n_jobs=-1,
                        verbose=-1
                    )
                    model.fit(
                        X_train_tab, y_train_tab,
                        eval_set=[(X_val_tab, y_val_tab)],
                        eval_metric='mae',
                        callbacks=[lgb.early_stopping(100, verbose=False)]
                    )
                    print(f'  LGBM {tf_name} seed={lgbm_seed} | features={model.n_features_in_}')
                    # Save with timeframe suffix
                    model_path = self._get_model_path(model_type, model_index).replace('.pkl', f'_{tf_name}.pkl')
                    with open(model_path, 'wb') as f:
                        pickle.dump(model, f)
                    print(f"Saved: {model_path}")

                model_type_counts[model_type] += 1

        # Restore base target/feature_cols to 1H defaults so any subsequent
        # single-TF code paths in the same process see consistent state.
        self.target_column = 'fwd_log_return_1h'
        self.feature_cols  = feature_cols_by_tf['1H']

        # Copy 1H scalers and models to base names for backward compatibility
        print("\nSaving base scalers and models for backward compatibility...")
        try:
            import shutil

            # Copy scalers
            h1_feature_scaler = self.feature_scaler_path.replace('.pkl', '_1H.pkl')
            h1_target_scaler = self.target_scaler_path.replace('.pkl', '_1H.pkl')

            if os.path.exists(h1_feature_scaler):
                shutil.copy(h1_feature_scaler, self.feature_scaler_path)
                print(f"[OK] Copied {os.path.basename(h1_feature_scaler)} -> {os.path.basename(self.feature_scaler_path)}")

            if os.path.exists(h1_target_scaler):
                shutil.copy(h1_target_scaler, self.target_scaler_path)
                print(f"[OK] Copied {os.path.basename(h1_target_scaler)} -> {os.path.basename(self.target_scaler_path)}")

            # Copy model files
            print("\nCopying 1H models to base names...")
            model_type_counts = defaultdict(int)
            for model_type in self.ensemble_model_types:
                model_index = model_type_counts[model_type]
                base_model_path = self._get_model_path(model_type, model_index)

                # Construct 1H model path
                ext = '.keras' if model_type in ['lstm', 'gru', 'transformer', 'tcn'] else '.pkl'
                h1_model_path = base_model_path.replace(ext, f'_1H{ext}')

                if os.path.exists(h1_model_path):
                    shutil.copy(h1_model_path, base_model_path)
                    print(f"[OK] Copied {os.path.basename(h1_model_path)} -> {os.path.basename(base_model_path)}")

                model_type_counts[model_type] += 1

        except Exception as e:
            print(f"Warning: Could not copy all base files: {e}")
            print("This may cause issues with backtest mode, but multi-TF predictions will work fine.")

        print("\n" + "=" * 60)
        print("Multi-timeframe ensemble training complete!")
        print("=" * 60)
        print(f"\nTrained {len(self.ensemble_model_types) * 3} models total")
        print("Use predict-multitf command to make predictions with these models")

        # v9.2 — fit HMM regime model on the SAME H1 series the predictors
        # learned on. Persisted to hmm_regime_{symbol}.pkl and picked up
        # automatically by _detect_regime on the next prediction cycle.
        self._fit_hmm_regime(df_h1)

        # Mark the manifest as completed (was 'in_progress' from before training)
        actual_end = self.train_end or (df_h1.index.max().to_pydatetime() if df_h1 is not None else None)
        self._save_cutoff_manifest(self.train_start, actual_end, status="completed")

    def load_model_assets(self) -> bool:
        """
        Load all trained models and scalers (single timeframe method).

        Returns:
            True if successful, False otherwise
        """
        print("Loading all model assets for the ensemble...")

        # Auto-detect models if not specified
        if not self.ensemble_model_types:
            self.ensemble_model_types = self._detect_trained_models()
            if not self.ensemble_model_types:
                print("Error: No trained models found. Please run the 'train' command first.")
                return False
            self.num_ensemble_models = len(self.ensemble_model_types)
            equal_weight = 1.0 / self.num_ensemble_models
            self.ensemble_weights = {
                tf_key: [equal_weight] * self.num_ensemble_models
                for tf_key in self.kalman_config.keys()
            }
            print(f"Detected trained models: {self.ensemble_model_types}")

        try:
            # Load feature list and scalers
            with open(self.selected_features_path, 'r') as f:
                self.feature_cols = json.load(f)

            # Try to load base scaler first, fallback to multi-TF scalers if needed
            feature_scaler_loaded = False
            target_scaler_loaded = False

            # Try base scaler first
            if os.path.exists(self.feature_scaler_path):
                with open(self.feature_scaler_path, 'rb') as f:
                    self.feature_scaler = pickle.load(f)
                feature_scaler_loaded = True
            else:
                # Check for multi-timeframe scalers (try 1H first as base timeframe)
                for tf_suffix in ['_1H', '_4H', '_1D']:
                    mtf_path = self.feature_scaler_path.replace('.pkl', f'{tf_suffix}.pkl')
                    if os.path.exists(mtf_path):
                        print(f"Note: Using multi-timeframe scaler: {os.path.basename(mtf_path)}")
                        with open(mtf_path, 'rb') as f:
                            self.feature_scaler = pickle.load(f)
                        feature_scaler_loaded = True
                        break

            if not feature_scaler_loaded:
                raise FileNotFoundError(f"Feature scaler not found: {self.feature_scaler_path}")

            # Try base target scaler first
            if os.path.exists(self.target_scaler_path):
                with open(self.target_scaler_path, 'rb') as f:
                    self.target_scaler = pickle.load(f)
                target_scaler_loaded = True
            else:
                # Check for multi-timeframe target scalers
                for tf_suffix in ['_1H', '_4H', '_1D']:
                    mtf_path = self.target_scaler_path.replace('.pkl', f'{tf_suffix}.pkl')
                    if os.path.exists(mtf_path):
                        with open(mtf_path, 'rb') as f:
                            self.target_scaler = pickle.load(f)
                        target_scaler_loaded = True
                        break

            if not target_scaler_loaded:
                raise FileNotFoundError(f"Target scaler not found: {self.target_scaler_path}")

            # Load each model
            self.models = {}
            model_type_counts = defaultdict(int)

            for model_type in self.ensemble_model_types:
                model_index = model_type_counts[model_type]
                model_path = self._get_model_path(model_type, model_index)
                model_name = f"{model_type}_{model_index}"

                # Auto-detect multi-timeframe model files if base doesn't exist
                actual_model_path = model_path
                if not os.path.exists(model_path):
                    # Check for multi-timeframe model files
                    for tf_suffix in ['_1H', '_4H', '_1D']:
                        if model_type in ['lstm', 'gru', 'transformer', 'tcn']:
                            # Try .keras first (newer), then .h5 (older)
                            for ext in ['.keras', '.h5']:
                                mtf_path = model_path.replace('.keras', f'{tf_suffix}{ext}').replace('.h5', f'{tf_suffix}{ext}')
                                if os.path.exists(mtf_path):
                                    print(f"Note: Using multi-timeframe model: {os.path.basename(mtf_path)}")
                                    actual_model_path = mtf_path
                                    break
                        else:  # lgbm
                            mtf_path = model_path.replace('.pkl', f'{tf_suffix}.pkl')
                            if os.path.exists(mtf_path):
                                print(f"Note: Using multi-timeframe model: {os.path.basename(mtf_path)}")
                                actual_model_path = mtf_path
                                break

                        if actual_model_path != model_path:
                            break

                if not os.path.exists(actual_model_path):
                    print(f"ERROR: Model file not found: {model_path}")
                    print(f"       Also checked for multi-TF versions with suffixes _1H, _4H, _1D")
                    return False

                if model_type in ['lstm', 'gru', 'transformer', 'tcn']:
                    print(f"  Loading {model_name} from {os.path.basename(actual_model_path)}...")
                    self.models[model_name] = load_model(
                        actual_model_path,
                        custom_objects={
                            'TransformerBlock': TransformerBlock,
                            'AttentionLayer': AttentionLayer
                        },
                        compile=False
                    )
                    print(f"  Loaded {model_name}")
                elif model_type == 'lgbm':
                    with open(actual_model_path, 'rb') as f:
                        self.models[model_name] = pickle.load(f)

                model_type_counts[model_type] += 1

            print(f"Successfully loaded {len(self.models)} models: {list(self.models.keys())}")
            return True

        except FileNotFoundError as e:
            print(f"Error: Model assets not found. Please train the model first. Missing: {e.filename}")
            return False
        except TypeError as e:
            # This usually indicates version mismatch between training and loading
            error_msg = str(e)
            if "Could not deserialize" in error_msg or "keras.src" in error_msg:
                print("\n" + "=" * 80)
                print("ERROR: MODEL VERSION MISMATCH DETECTED!")
                print("=" * 80)
                print("\nYour saved models are incompatible with your current Keras/TensorFlow version.")
                print("\nThis happens when:")
                print("  - Models were trained with Keras 3.x but you have Keras 2.x")
                print("  - Models were trained with Keras 2.x but you have Keras 3.x")
                print("  - TensorFlow version changed after training")
                print("\nSOLUTION:")
                print("  1. Retrain your models with your current environment")
                print(f"     Command: python unified_predictor_v8.py train-multitf --symbol {self.symbol} --force")
                print("\n  2. Or run from GUI: Select 'Train Models' and check 'Force Retrain'")
                print("\nYour current versions:")
                print(f"  TensorFlow: {tf.__version__}")
                print(f"  Keras: {keras.__version__}")
                print("\n" + "=" * 80)
            else:
                print(f"Error loading model assets: {e}")
                import traceback
                traceback.print_exc()
            return False
        except Exception as e:
            print(f"Error loading model assets: {e}")
            import traceback
            traceback.print_exc()
            return False

    def load_model_assets_multitimeframe(self) -> bool:
        """
        Load models for all timeframes (multi-timeframe method).

        Returns:
            True if successful, False otherwise
        """
        print("Loading multi-timeframe model assets...")

        try:
            if not self.ensemble_model_types:
                self.ensemble_model_types = self._detect_trained_models()
                if not self.ensemble_model_types:
                    print("Error: No trained models found.")
                    return False

            # Load base (1H) feature list for backward compatibility
            try:
                with open(self.selected_features_path, 'r') as f:
                    self.feature_cols = json.load(f)
            except FileNotFoundError:
                print("ERROR: Feature list not found. Please train models first.")
                return False

            # Load per-TF feature lists if present (v9.0+ training writes
            # selected_features_{symbol}_{tf}.json). For models trained on
            # v8.x where these don't exist, fall back to the base list so
            # all TFs share the same features (the legacy behaviour).
            timeframe_list = ['1H', '4H', '1D']
            self.feature_cols_by_tf = {}
            for tf_name in timeframe_list:
                tf_path = self.selected_features_path.replace(
                    '.json', f'_{tf_name}.json'
                )
                if os.path.exists(tf_path):
                    with open(tf_path, 'r') as f:
                        self.feature_cols_by_tf[tf_name] = json.load(f)
                    print(f"   Loaded {tf_name} feature list ({len(self.feature_cols_by_tf[tf_name])} features)")
                else:
                    self.feature_cols_by_tf[tf_name] = self.feature_cols
                    print(f"   No {tf_name}-specific feature list — using base list "
                          f"(v8.x compatibility)")

            self.models_by_timeframe = {}
            self.scalers_by_timeframe = {}

            for tf_name in timeframe_list:
                print(f"\nLoading models for {tf_name}...")

                # Load scalers for this timeframe
                try:
                    scaler_suffix = f"_{tf_name}"
                    with open(self.feature_scaler_path.replace('.pkl', f'{scaler_suffix}.pkl'), 'rb') as f:
                        feature_scaler = pickle.load(f)
                    with open(self.target_scaler_path.replace('.pkl', f'{scaler_suffix}.pkl'), 'rb') as f:
                        target_scaler = pickle.load(f)
                    self.scalers_by_timeframe[tf_name] = (feature_scaler, target_scaler)
                    print(f"  Loaded scalers for {tf_name}")
                except FileNotFoundError:
                    print(f"WARNING: Scalers not found for {tf_name}")
                    return False

                # Load models for this timeframe
                models = {}
                model_type_counts = defaultdict(int)

                for model_type in self.ensemble_model_types:
                    model_index = model_type_counts[model_type]
                    model_name = f"{model_type}_{model_index}"

                    if model_type in ['lstm', 'gru', 'transformer', 'tcn']:
                        model_path = self._get_model_path(model_type, model_index).replace('.keras', f'_{tf_name}.keras')
                        if os.path.exists(model_path):
                            print(f"  Loading {model_name} from {os.path.basename(model_path)}...")
                            # compile=False skips TF graph recompilation at load time.
                            # Without it, Keras traces the full computation graph for every
                            # custom-layer model, which can take minutes or hang entirely on
                            # CPU.  We only need inference here — no gradients required.
                            models[model_name] = load_model(
                                model_path,
                                custom_objects={
                                    'TransformerBlock': TransformerBlock,
                                    'AttentionLayer': AttentionLayer
                                },
                                compile=False
                            )
                            print(f"  Loaded {model_name}")
                        else:
                            print(f"ERROR: Model not found: {model_path}")
                            return False

                    elif model_type == 'lgbm':
                        model_path = self._get_model_path(model_type, model_index).replace('.pkl', f'_{tf_name}.pkl')
                        if os.path.exists(model_path):
                            with open(model_path, 'rb') as f:
                                models[model_name] = pickle.load(f)
                            print(f"  Loaded {model_name}")
                        else:
                            print(f"ERROR: Model not found: {model_path}")
                            return False

                    model_type_counts[model_type] += 1

                self.models_by_timeframe[tf_name] = models
                print(f"  Total models for {tf_name}: {len(models)}")

            print(f"\nSuccessfully loaded models for all {len(self.models_by_timeframe)} timeframes")
            return len(self.models_by_timeframe) > 0

        except TypeError as e:
            # This usually indicates version mismatch between training and loading
            error_msg = str(e)
            if "Could not deserialize" in error_msg or "keras.src" in error_msg:
                print("\n" + "=" * 80)
                print("ERROR: MODEL VERSION MISMATCH DETECTED!")
                print("=" * 80)
                print("\nYour saved models are incompatible with your current Keras/TensorFlow version.")
                print("\nThis happens when:")
                print("  - Models were trained with Keras 3.x but you have Keras 2.x")
                print("  - Models were trained with Keras 2.x but you have Keras 3.x")
                print("  - TensorFlow version changed after training")
                print("\nSOLUTION:")
                print("  1. Retrain your models with your current environment")
                print(f"     Command: python unified_predictor_v8.py train-multitf --symbol {self.symbol} --force")
                print("\n  2. Or run from GUI: Select 'Train Models' and check 'Force Retrain'")
                print("\nYour current versions:")
                print(f"  TensorFlow: {tf.__version__}")
                print(f"  Keras: {keras.__version__}")
                print("\n" + "=" * 80)
            else:
                print(f"Error loading model assets: {e}")
                import traceback
                traceback.print_exc()
            return False
        except Exception as e:
            print(f"Error loading multi-timeframe model assets: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _detect_trained_models(self) -> Optional[List[str]]:
        """
        Detect trained models from saved files.

        Returns:
            List of detected model types or None if none found
        """
        # Find all model files
        all_model_files = glob.glob(os.path.join(self.base_path, f"model_{self.symbol}_*.h5"))
        all_model_files += glob.glob(os.path.join(self.base_path, f"model_{self.symbol}_*.pkl"))
        all_model_files += glob.glob(os.path.join(self.base_path, f"model_{self.symbol}_*.keras"))

        found_models = set()

        # Parse model files
        for f in all_model_files:
            parts = os.path.basename(f).split('_')
            if len(parts) >= 4:
                model_type = parts[2]
                try:
                    # Handle both regular and multitimeframe models
                    index_part = parts[3].split('.')[0]

                    # Also detect multi-timeframe models
                    if index_part in ['1H', '4H', '1D']:
                        # This is a multi-TF model
                        if len(parts) >= 5:
                            # Format: model_SYMBOL_TYPE_INDEX_TIMEFRAME.ext
                            try:
                                model_index = int(parts[3])
                                if model_type in ['lstm', 'gru', 'transformer', 'tcn', 'lgbm']:
                                    found_models.add((model_type, model_index))
                            except ValueError:
                                pass
                        continue

                    model_index = int(index_part)
                    if model_type in ['lstm', 'gru', 'transformer', 'tcn', 'lgbm']:
                        found_models.add((model_type, model_index))
                except (ValueError, IndexError):
                    continue

        # Sort by index then type
        found_models = sorted(list(found_models), key=lambda x: (x[1], x[0]))
        detected = [model_type for model_type, model_index in found_models]

        print(f"   Found model files: {found_models}")
        print(f"   Detected models: {detected}")
        return detected if detected else None

    def _get_model_path(self, model_type: str, index: int) -> str:
        """Get the file path for a model."""
        ext = 'keras' if model_type in ['lstm', 'gru', 'transformer', 'tcn'] else 'pkl'
        return os.path.join(self.base_path, f"model_{self.symbol}_{model_type}_{index}.{ext}")

    def _apply_regime_bias(
        self,
        base_weights: List[float],
        model_names: List[str],
        regime: str,
    ) -> List[float]:
        """
        Multiply base ensemble weights by regime-specific per-model scalars,
        then renormalise so the result still sums to 1.0.

        The intuition behind the bias table:
            trending  — TCN and Transformer capture long-range directional
                        structure well; LGBM treats each bar as i.i.d. and
                        misses momentum, so it gets a mild penalty.
            ranging   — LGBM excels at mean-reversion because decision trees
                        have no assumption of temporal order.  TCN/Transformer
                        can overfit to spurious trends, so they get down-weighted.
            volatile  — All deep models are hurt by distributional shift; LGBM
                        is slightly more robust.  Dampen everything a little and
                        let LGBM lead.
            unknown   — No bias; keep whatever base_weights are.

        The scalar values are intentionally conservative (range 0.8–1.3) so
        the regime can nudge but not override learned accuracy weights.  Tune
        on your own backtest data once you have enough evaluated predictions.

        Args:
            base_weights: Current per-TF weight vector (already accuracy-weighted).
            model_names:  Names of each model in the same order as base_weights
                          (e.g. ["lstm_0", "transformer_1", "lgbm_2"]).
            regime:       Output of _detect_regime().

        Returns:
            Renormalised weight list of the same length.
        """
        REGIME_BIAS: Dict[str, Dict[str, float]] = {
            'trending': {
                'lstm': 1.1, 'gru': 1.0, 'transformer': 1.3, 'tcn': 1.3, 'lgbm': 0.8
            },
            'ranging': {
                'lstm': 1.0, 'gru': 1.0, 'transformer': 0.8, 'tcn': 0.8, 'lgbm': 1.3
            },
            'volatile': {
                'lstm': 0.9, 'gru': 0.9, 'transformer': 0.8, 'tcn': 0.8, 'lgbm': 1.2
            },
        }

        bias_map = REGIME_BIAS.get(regime, {})
        if not bias_map:
            return base_weights  # 'unknown' or unrecognised regime — no change

        biased = []
        for w, name in zip(base_weights, model_names):
            # Extract model type from names like "lstm_0", "transformer_1", "lgbm_2"
            model_type = name.split('_')[0] if '_' in name else name
            scalar = bias_map.get(model_type, 1.0)
            biased.append(w * scalar)

        total = sum(biased)
        if total <= 0:
            return base_weights  # safety: don't zero out all weights
        return [b / total for b in biased]

    def run_prediction_cycle(self):
        """Updated with Macro integration."""
        print(f"\n--- Single-Timeframe Prediction Cycle: {self.symbol} ---")

        print("\n" + "=" * 60)
        print(f"Starting Prediction Cycle for {self.symbol} at {datetime.now()}")
        print("=" * 60 + "\n")
        print("WARNING: Using single-timeframe models with scaling.")
        print("For better predictions, use run_prediction_cycle_multitimeframe()\n")

        # Load models if not already loaded
        if not self.models:
            if not self.load_model_assets():
                return

        # Evaluate past predictions and update weights
        self._evaluate_past_predictions()
        self.update_ensemble_weights()

        # ── Single download per cycle ─────────────────────────────────────────
        # Download once with the bar counts each timeframe actually needs.
        # Previously this method downloaded twice with mismatched counts and
        # discarded the first result, wasting bandwidth and risking macro/feature
        # divergence if a new bar arrived between calls.
        # H1 bar count must cover the longest warmup (log_return_1w = 168 bars)
        # plus the sequence lookback (60) plus a safety buffer -> 500 is sufficient.
        raw_h1 = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_H1, 0, 500)
        raw_h4 = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_H4, 0, 150)
        raw_d1 = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_D1, 0,  75)

        df_h1 = pd.DataFrame(raw_h1) if raw_h1 is not None else pd.DataFrame()
        df_h4 = pd.DataFrame(raw_h4) if raw_h4 is not None else pd.DataFrame()
        df_d1 = pd.DataFrame(raw_d1) if raw_d1 is not None else pd.DataFrame()

        # Validate data — minimums are per-timeframe to match the download counts above
        _min_bars = {"H1": 250, "H4": 60, "D1": 55}
        for df, name in [(df_h1, "H1"), (df_h4, "H4"), (df_d1, "D1")]:
            required = _min_bars[name]
            if df.empty or len(df) < required:
                print(f"ERROR: Insufficient {name} data for prediction "
                      f"(got {len(df) if not df.empty else 0}, need {required})")
                return
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True)
            if 'tick_volume' in df.columns:
                df.rename(columns={'tick_volume': 'volume'}, inplace=True)

        # Macro context computed off the SAME dataframes used for prediction
        df_dxy, df_spx = self._download_macro_data(300)
        context = self.get_market_context(df_h1, df_dxy, df_spx)

        # Create features
        df = self.create_features(df_h1, df_h4, df_d1)
        # ── Live price from MT5 tick (not last bar close) ─────────────────────────
        # df['close'].iloc[-1] is the close of the last COMPLETED bar — up to
        # one full H1 period behind live price. Using the live tick ensures
        # change_pct and the on-chart panel both reflect what the market is
        # actually doing right now.
        _tick = mt5.symbol_info_tick(self.symbol)
        current_price = float(_tick.bid) if (_tick is not None and _tick.bid > 0) else df['close'].iloc[-1]
        if _tick is None or _tick.bid <= 0:
            print("   [WARN] MT5 tick unavailable — falling back to last bar close for current_price")
        else:
            print(f"   Live price from MT5 tick: {current_price:.5f} (last bar close was {df['close'].iloc[-1]:.5f})")

        # ── Feature compatibility check ────────────────────────────────────────
        if self.feature_cols:
            missing_cols = [c for c in self.feature_cols if c not in df.columns]
            if missing_cols:
                print("\n" + "!" * 70)
                print("  FEATURE MISMATCH — saved feature list does not match current DataFrame.")
                print(f"  Missing columns ({len(missing_cols)}): {missing_cols}")
                print("  This happens when create_features() is updated after models were trained.")
                print("  ACTION REQUIRED: retrain all models with:")
                print("      python unified_predictor_v8.py train-multitf --force")
                print("!" * 70 + "\n")
                return

        # Prepare sequential input
        last_sequence_raw = df.iloc[-self.lookback_periods:][self.feature_cols].values
        last_sequence_scaled = self.feature_scaler.transform(last_sequence_raw)
        X_pred_seq = last_sequence_scaled.reshape(1, self.lookback_periods, len(self.feature_cols))

        # Convert to TensorFlow tensor to avoid retracing warnings
        X_pred_seq = tf.convert_to_tensor(X_pred_seq, dtype=tf.float32)

        # Prepare tabular input for LightGBM
        df_tabular = df.copy()
        final_tab_cols = []
        for model_name, model in self.models.items():
            if 'lgbm' in model_name:
                final_tab_cols = model.feature_name_
                break

        X_pred_tab = None
        if final_tab_cols:
            for col in self.feature_cols:
                for lag in [1, 3, 5, 10]:
                    new_col = f'{col}_lag_{lag}'
                    if new_col in final_tab_cols:
                        df_tabular[new_col] = df_tabular[col].shift(lag)

            # Check for NaN values in tabular features
            last_row = df_tabular.iloc[-1][final_tab_cols]
            if last_row.isna().any():
                print("WARNING: NaN values detected in tabular features, filling with forward fill")
                df_tabular.ffill(inplace=True)

            X_pred_tab = df_tabular.iloc[-1][final_tab_cols].values.reshape(1, -1)

        # Make predictions
        predictions = {}
        timeframes = {"1H": 1, "4H": 4, "1D": 24}
        ensemble_predictions_map = {}

        print("\nMaking predictions with hybrid ensemble...")
        for tf_name, steps in timeframes.items():
            ensemble_preds = []
            raw_log_returns = []

            # Get predictions from each model
            for model_name, model in self.models.items():
                pred_log_return = 0.0

                try:
                    if 'lgbm' in model_name and X_pred_tab is not None:
                        pred_log_return = model.predict(X_pred_tab)[0]
                    elif 'lgbm' not in model_name:
                        # Use direct call to avoid retracing
                        pred_log_return_scaled = model(X_pred_seq, training=False).numpy()[0][0]
                        pred_log_return = self.target_scaler.inverse_transform([[pred_log_return_scaled]])[0][0]
                    
                    # SAFEGUARD: Clamp extreme log returns (before scaling)
                    # Base max return is 0.5% for 1H
                    max_base_log_return = 0.005
                    if abs(pred_log_return) > max_base_log_return:
                        original_lr = pred_log_return
                        pred_log_return = np.clip(pred_log_return, -max_base_log_return, max_base_log_return)
                        print(f"  WARNING: {model_name} log return clamped from {original_lr:.6f} to {pred_log_return:.6f}")
                        
                except Exception as e:
                    print(f"WARNING: Error predicting with {model_name}: {e}")
                    continue

                raw_log_returns.append(pred_log_return)

                # Scale log return by time horizon LINEARLY.
                # Previous code used sqrt-time, which is correct for the
                # standard deviation of returns under Brownian motion but
                # WRONG for the expected drift — the drift of log returns
                # scales linearly with t (E[log(P_t/P_0)] = μt). With sqrt
                # scaling the 4H/1D predictions were systematically about
                # half what the model intended.
                steps_adjusted = float(steps)
                predicted_price = current_price * np.exp(pred_log_return * steps_adjusted)

                # Validate predicted price
                if np.isnan(predicted_price) or np.isinf(predicted_price):
                    print(f"WARNING: Invalid prediction from {model_name}, using current price")
                    predicted_price = current_price

                ensemble_preds.append(predicted_price)

            # Check if we have valid predictions
            if not ensemble_preds:
                print(f"ERROR: No valid predictions for {tf_name}, skipping")
                continue

            print(f"\n{tf_name} Debug:")
            print(f"  Raw log returns: {[f'{lr:.6f}' for lr in raw_log_returns]}")
            print(f"  Steps: {steps} -> Adjusted: {steps_adjusted:.2f}")
            print(f"  Predicted prices: {[f'{p:.5f}' for p in ensemble_preds]}")

            ensemble_predictions_map[tf_name] = ensemble_preds
            tf_weights = self.ensemble_weights.get(tf_name, [])
            if tf_weights and len(tf_weights) >= len(ensemble_preds):
                # Fix 4: apply regime bias before combining
                regime = context.get('regime', 'unknown')
                model_names = list(self.models.keys())
                tf_weights = self._apply_regime_bias(
                    tf_weights[:len(ensemble_preds)], model_names[:len(ensemble_preds)], regime
                )
                raw_prediction = np.average(ensemble_preds, weights=tf_weights)
            else:
                raw_prediction = np.mean(ensemble_preds)

            print(f"  Raw ensemble average: {raw_prediction:.5f}")

            # Apply smoothing to log returns
            raw_log_return = np.log(raw_prediction / current_price)

            if self.use_kalman:
                # Use Kalman filtering
                print(f"  Kalman state before: x={self.kalman_filters[tf_name].x:.6f}, p={self.kalman_filters[tf_name].p:.6f}")
                smoothed_log_return = self.kalman_filters[tf_name].update(raw_log_return)
                print(f"  Kalman smoothed log return: {smoothed_log_return:.6f} (raw: {raw_log_return:.6f})")
                print(f"  Kalman state after: x={self.kalman_filters[tf_name].x:.6f}, p={self.kalman_filters[tf_name].p:.6f}")
                smoothed_prediction = current_price * np.exp(smoothed_log_return)
            else:
                # Use EMA smoothing
                if self.previous_predictions[tf_name] is not None:
                    prev_log_return = np.log(self.previous_predictions[tf_name] / current_price)
                    smoothed_log_return = self.ema_alpha * raw_log_return + (1 - self.ema_alpha) * prev_log_return
                    smoothed_prediction = current_price * np.exp(smoothed_log_return)
                    print(f"  EMA smoothed log return: {smoothed_log_return:.6f} (raw: {raw_log_return:.6f})")
                else:
                    smoothed_prediction = raw_prediction
                    print(f"  Using raw prediction (first prediction)")

            self.previous_predictions[tf_name] = smoothed_prediction

            max_change_pct = {'1H': 0.5, '4H': 1.0, '1D': 2.0}
            max_change = current_price * (max_change_pct.get(tf_name, 1.0) / 100.0)

            if abs(smoothed_prediction - current_price) > max_change:
                original_pred = smoothed_prediction
                if smoothed_prediction > current_price:
                    smoothed_prediction = current_price + max_change
                else:
                    smoothed_prediction = current_price - max_change
                print(f"  Capped from {original_pred:.5f} to {smoothed_prediction:.5f}")

            # change percentage for the EA
            change_pct = ((smoothed_prediction - current_price) / current_price) * 100.0

            predictions[tf_name] = {
                'prediction': round(smoothed_prediction, 5),
                'change_pct': round(change_pct, 3),
                'ensemble_std': round(np.std(ensemble_preds), 5),
            }

        # Log predictions for future evaluation
        self._log_prediction_for_evaluation(timeframes, ensemble_predictions_map, current_price)

        # Uncertainty veto (same logic as multi-TF path — Fix 3)
        UNCERTAINTY_THRESHOLD = 0.008  # 0.8% of current price
        uncertainty_veto = any(
            data['ensemble_std'] / current_price > UNCERTAINTY_THRESHOLD
            for data in predictions.values()
        )
        if uncertainty_veto:
            print(f"   VETO (uncertainty): ensemble std exceeds {UNCERTAINTY_THRESHOLD*100:.1f}% threshold")
            self.metrics.record_uncertainty_veto()
        if context.get('veto_active'):
            self.metrics.record_macro_veto()

        # v9.4 — drain EA outcomes into the adaptive Bayesian posterior.
        # Must happen BEFORE the flat signal write, because confidence_floor
        # might change as a result of new outcomes and we want the EA to
        # see the latest floor on this very cycle.
        self._ingest_ea_outcomes_into_adaptive()

        trade_allowed = not context['veto_active'] and not uncertainty_veto
        veto_reasons = []
        if context.get('veto_active'):     veto_reasons += context.get('reasons', [])
        if uncertainty_veto:               veto_reasons += ["UNCERTAINTY"]

        # Save predictions and status
        status = {
            'last_update': datetime.now().isoformat(),
            # NOTE (timezone fix, 2026-05): use time.time() not
            # datetime.utcnow().timestamp(). The latter is a well-known
            # Python footgun: utcnow() returns a NAIVE datetime, and
            # .timestamp() on a naive datetime interprets it as LOCAL
            # time, then converts to epoch. The returned value is offset
            # from true UTC by the local timezone offset. The EA's
            # heartbeat watchdog reads this value as UTC, so the bug
            # makes every heartbeat look hours in the future and
            # silently disables staleness checking.
            # time.time() always returns true UTC epoch on every platform.
            'last_updated_utc': int(time.time()),
            'status': 'online',
            'symbol': self.symbol,
            'current_price': round(current_price, 5),
            'ensemble_weights': {
                tf_key: [round(w, 3) for w in weights]
                for tf_key, weights in self.ensemble_weights.items()
            },
            'price': df_h1['close'].iloc[-1],
            'market_context': context,
            'regime': context.get('regime', 'unknown'),
            'uncertainty_veto': uncertainty_veto,
            'trade_allowed': trade_allowed,
            # v9.4: include for diagnostic visibility, but EA must NOT
            # parse this file. EA reads ea_signal.json instead.
            'confidence_floor_pct': round(self.adaptive.confidence_floor, 4),
        }

        self.save_to_file(self.predictions_file, predictions)
        self.save_to_file(self.status_file, status)

        # v9.4 — flat EA-facing signal file (issue #2). EA parses ONLY this.
        self._write_ea_signal(
            current_price=current_price,
            regime=context.get('regime', 'unknown'),
            trade_allowed=trade_allowed,
            veto_reasons=veto_reasons,
            timeframe_predictions=predictions,
        )

        # v9.2 — persist ensemble weights / history / model health so a
        # process restart picks up where this cycle left off.
        self._save_ensemble_state()
        # v9.4 — persist metrics rollup
        self._save_metrics()

        # Display results
        print("\n--- Prediction Cycle Complete! ---")
        print(f"Current Price: {current_price:.5f}")
        for timeframe, data in predictions.items():
            direction = "UP" if data['prediction'] > current_price else "DOWN"
            change_pct = ((data['prediction'] - current_price) / current_price) * 100
            print(f"   {direction} {timeframe}: {data['prediction']:.5f} ({change_pct:+.3f}%) (Uncertainty: +/-{data['ensemble_std']:.5f})")

    def run_prediction_cycle_multitimeframe(self):
        """Updated with Macro integration."""
        print(f"\n--- Multi-Timeframe Cycle: {self.symbol} ---")

        print("\n" + "=" * 60)
        print(f"Starting Multi-Timeframe Prediction Cycle for {self.symbol}")
        print("=" * 60 + "\n")

        if not hasattr(self, 'models_by_timeframe') or not self.models_by_timeframe:
            if not self.load_model_assets_multitimeframe():
                return

        # Evaluate past predictions logged in the previous cycle and use the
        # results to update per-timeframe ensemble weights.  These calls were
        # only present in run_prediction_cycle (single-TF path) — their absence
        # here meant multi-TF weights were permanently frozen at the equal
        # initialisation value of 0.200 regardless of model accuracy.
        self._evaluate_past_predictions()
        self.update_ensemble_weights()

        # ── Single download per cycle ─────────────────────────────────────────
        # Previously this method downloaded twice (once via download_data with
        # the wrong bar counts, then again with correct counts) and discarded
        # the first result. Now we download exactly once with the counts each
        # timeframe actually needs, and use those same dataframes for both the
        # macro/regime analysis and the prediction features.
        # H1 bar count must cover the longest warmup (log_return_1w = 168 bars)
        # plus the sequence lookback (60) plus a safety buffer -> 500 is sufficient.
        raw_h1 = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_H1, 0, 500)
        raw_h4 = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_H4, 0, 150)
        raw_d1 = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_D1, 0,  75)

        df_h1 = pd.DataFrame(raw_h1) if raw_h1 is not None else pd.DataFrame()
        df_h4 = pd.DataFrame(raw_h4) if raw_h4 is not None else pd.DataFrame()
        df_d1 = pd.DataFrame(raw_d1) if raw_d1 is not None else pd.DataFrame()

        # Validate data — minimums are per-timeframe to match the download counts above
        _min_bars = {"H1": 250, "H4": 60, "D1": 55}
        for df, name in [(df_h1, "H1"), (df_h4, "H4"), (df_d1, "D1")]:
            required = _min_bars[name]
            if df.empty or len(df) < required:
                print(f"ERROR: Insufficient {name} data "
                      f"(got {len(df) if not df.empty else 0}, need {required})")
                return
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('time', inplace=True)
            if 'tick_volume' in df.columns:
                df.rename(columns={'tick_volume': 'volume'}, inplace=True)

        # Macro context computed off the SAME dataframes used for prediction
        df_dxy, df_spx = self._download_macro_data(300)
        context = self.get_market_context(df_h1, df_dxy, df_spx)

        # Create features
        df = self.create_features(df_h1, df_h4, df_d1)
        # ── Live price from MT5 tick (not last bar close) ─────────────────────────
        # df['close'].iloc[-1] is the close of the last COMPLETED bar — up to
        # one full H1 period behind live price. Using the live tick ensures
        # change_pct and the on-chart panel both reflect what the market is
        # actually doing right now.
        _tick = mt5.symbol_info_tick(self.symbol)
        current_price = float(_tick.bid) if (_tick is not None and _tick.bid > 0) else df['close'].iloc[-1]
        if _tick is None or _tick.bid <= 0:
            print("   [WARN] MT5 tick unavailable — falling back to last bar close for current_price")
        else:
            print(f"   Live price from MT5 tick: {current_price:.5f} (last bar close was {df['close'].iloc[-1]:.5f})")

        # ── Feature compatibility check ────────────────────────────────────────
        # Check that every per-TF feature list is fully present in the current
        # DataFrame. If create_features() has been updated since training,
        # column names may not match and we'd get a cryptic pandas KeyError
        # deep inside the prediction loop.
        all_required = set()
        for tf_features in self.feature_cols_by_tf.values():
            all_required.update(tf_features)
        # Fall back to base list if per-TF dict is empty (v8.x compat)
        if not all_required and self.feature_cols:
            all_required = set(self.feature_cols)
        missing_cols = [c for c in all_required if c not in df.columns]
        if missing_cols:
            print("\n" + "!" * 70)
            print("  FEATURE MISMATCH — saved feature list does not match current DataFrame.")
            print(f"  Missing columns ({len(missing_cols)}): {missing_cols}")
            print("  This happens when create_features() is updated after models were trained.")
            print("  ACTION REQUIRED: retrain all models with:")
            print(f"      python unified_predictor_v9.py train-multitf --symbol {self.symbol} --force")
            print("!" * 70 + "\n")
            return

        predictions = {}
        # Accumulate raw per-model price predictions per timeframe so they can
        # be logged for future evaluation (feeds update_ensemble_weights).
        # Previously this map was never built in the multi-TF path, so
        # _log_prediction_for_evaluation could never be called and weights
        # were permanently stuck at the equal-weight initialisation of 0.200.
        ensemble_predictions_map: Dict[str, List[float]] = {}

        print("\nMaking predictions with timeframe-specific models...")
        for tf_name, models in self.models_by_timeframe.items():
            if not models:
                print(f"WARNING: No models for {tf_name}, skipping")
                continue

            # Get scalers for this timeframe
            feature_scaler, target_scaler = self.scalers_by_timeframe[tf_name]

            # Use this timeframe's selected feature list (falls back to base
            # list if loaded from a v8.x training that didn't save per-TF lists).
            tf_features = self.feature_cols_by_tf.get(tf_name, self.feature_cols)

            # Prepare input data
            last_sequence_raw = df.iloc[-self.lookback_periods:][tf_features].values
            last_sequence_scaled = feature_scaler.transform(last_sequence_raw)
            X_pred_seq = last_sequence_scaled.reshape(1, self.lookback_periods, len(tf_features))

            # Convert to TensorFlow tensor to avoid retracing warnings
            X_pred_seq = tf.convert_to_tensor(X_pred_seq, dtype=tf.float32)

            # v9.2 health threshold — a model with this many consecutive
            # failures is excluded from the cycle entirely. Defined here so
            # it lives at the same scope as model_health for clarity.
            HEALTH_FAIL_THRESHOLD = 5

            # Get predictions from each model.
            # v9.2 — track success/failure per model so:
            #   (a) the regime-bias mapping aligns names→weights even when
            #       individual models fail, and
            #   (b) repeated failures auto-exclude unhealthy models.
            #
            # v9.5 (CRITICAL fix) — per_model_predictions tracks ALL models
            # by name, with None for failures. This drives the evaluation
            # log so update_ensemble_weights can attribute errors by model
            # IDENTITY rather than list position. Previously, when a model
            # threw, its slot in the predictions list silently disappeared,
            # the next model's error landed in its weight bucket, and the
            # failing model's bucket stayed at zero — which the softmax
            # weight learner then interpreted as "perfect accuracy" and
            # rewarded with the highest weight. This is how LGBM ended up
            # at 80%+ weight while throwing 5 cycles in a row.
            ensemble_preds: List[float] = []
            successful_model_names: List[str] = []
            per_model_predictions: Dict[str, Optional[float]] = {
                name: None for name in models.keys()
            }
            for model_name, model in models.items():
                # Skip models that have crossed the consecutive-failure
                # threshold. Reset requires either retraining (which deletes
                # the state file) or manual editing of model_health_*.json.
                tf_health = self.model_health.setdefault(tf_name, {})
                fail_count = tf_health.get(model_name, 0)
                if fail_count >= HEALTH_FAIL_THRESHOLD:
                    print(f"  [HEALTH] {tf_name}/{model_name} excluded — "
                          f"{fail_count} consecutive failures (threshold "
                          f"{HEALTH_FAIL_THRESHOLD}). Edit "
                          f"{os.path.basename(self.model_health_path)} to reset.")
                    continue

                try:
                    if 'lgbm' in model_name:
                        # Prepare tabular data for LightGBM.
                        # v9.5 — surface a clearer error if any of the columns
                        # the model was trained on are missing from the
                        # current df_tabular. The previous code raised a
                        # cryptic KeyError that the outer except swallowed
                        # without revealing which column was the culprit.
                        df_tabular = df.copy()
                        for col in tf_features:
                            for lag in [1, 3, 5, 10]:
                                new_col = f'{col}_lag_{lag}'
                                df_tabular[new_col] = df_tabular[col].shift(lag)
                        df_tabular.ffill(inplace=True)

                        required_cols = list(model.feature_name_)
                        missing = [c for c in required_cols if c not in df_tabular.columns]
                        if missing:
                            raise KeyError(
                                f"LGBM was trained on {len(required_cols)} features but "
                                f"{len(missing)} are missing from the current DataFrame: "
                                f"{missing[:5]}{'...' if len(missing) > 5 else ''}. "
                                f"This usually means create_features() or the per-TF "
                                f"feature list changed since the model was last trained. "
                                f"Retrain with --force to realign."
                            )

                        X_pred_tab = df_tabular.iloc[-1][required_cols].values.reshape(1, -1)
                        pred_log_return = model.predict(X_pred_tab)[0]
                    else:
                        # Deep learning model - use direct call to avoid retracing
                        pred_log_return_scaled = model(X_pred_seq, training=False).numpy()[0][0]
                        pred_log_return = target_scaler.inverse_transform([[pred_log_return_scaled]])[0][0]

                    # SAFEGUARD: Clamp extreme log returns before converting to price
                    # Max expected returns: 1H=0.5%, 4H=1%, 1D=2%
                    max_log_return = {'1H': 0.005, '4H': 0.01, '1D': 0.02}.get(tf_name, 0.01)
                    
                    if abs(pred_log_return) > max_log_return:
                        original_lr = pred_log_return
                        pred_log_return = np.clip(pred_log_return, -max_log_return, max_log_return)
                        print(f"  WARNING: {model_name} log return clamped from {original_lr:.6f} to {pred_log_return:.6f}")

                    # Convert log return to price (NO SCALING!)
                    predicted_price = current_price * np.exp(pred_log_return)

                    if not np.isnan(predicted_price) and not np.isinf(predicted_price):
                        ensemble_preds.append(predicted_price)
                        successful_model_names.append(model_name)
                        # v9.5: record by model identity so the eval log
                        # can carry None for the failing models — see
                        # comment above per_model_predictions.
                        per_model_predictions[model_name] = float(predicted_price)
                        # On success: zero the health counter for this model
                        tf_health[model_name] = 0
                    else:
                        # Numerically invalid prediction — count as failure
                        tf_health[model_name] = fail_count + 1
                        # v9.4: also count for metrics rollup
                        self.metrics.record_model_failure(tf_name, model_name)
                        print(f"WARNING: {model_name} for {tf_name} produced "
                              f"non-finite price (fail #{tf_health[model_name]})")

                except Exception as e:
                    # v9.5 — log the full traceback ONCE per model the first
                    # time it fails (or after a successful cycle resets
                    # fail_count to 0). Subsequent failures get the one-line
                    # warning to avoid filling the log with the same trace.
                    tf_health[model_name] = fail_count + 1
                    self.metrics.record_model_failure(tf_name, model_name)
                    if fail_count == 0:
                        # First failure in this streak — capture full diagnostic
                        import traceback
                        print(f"WARNING: {model_name} for {tf_name} failed for "
                              f"the first time (this streak): "
                              f"{type(e).__name__}: {e}")
                        print("  ── Full traceback (first failure only) ──")
                        traceback.print_exc()
                        print("  ── End traceback ──")
                    else:
                        print(f"WARNING: {model_name} for {tf_name} failed "
                              f"(fail #{tf_health[model_name]}): "
                              f"{type(e).__name__}: {e}")
                    continue

            if not ensemble_preds:
                print(f"ERROR: No valid predictions for {tf_name}")
                continue

            # Record raw per-model predictions for this timeframe so they can
            # be logged at the end of the cycle and evaluated in the next cycle.
            #
            # v9.5 (CRITICAL fix): the list MUST be aligned to the full
            # models.keys() order with None for any model that failed this
            # cycle. update_ensemble_weights iterates by index and indexes
            # into model_errors[i] — if a failed model's slot is silently
            # missing, the next model's error lands in its bucket and the
            # failed model's bucket stays at zero forever. The softmax
            # weight learner then interprets zero error as perfect skill
            # and rewards the failing model with the highest weight. That
            # is exactly what happened to LGBM in production.
            full_model_order = list(models.keys())
            ensemble_predictions_map[tf_name] = [
                per_model_predictions[name] for name in full_model_order
            ]

            # Weighted ensemble average using per-timeframe weights.
            # v9.2 — align weights to the SUCCESSFUL models only. Previously
            # we sliced model_names = list(models.keys()) which kept failed
            # models in the name list, misaligning the regime-bias map.
            tf_weights_full = self.ensemble_weights.get(tf_name, [])
            if tf_weights_full and len(tf_weights_full) == len(list(models.keys())):
                # Pull out the weight slot for each successful model in order
                model_idx = {name: i for i, name in enumerate(models.keys())}
                tf_weights = [
                    tf_weights_full[model_idx[name]]
                    for name in successful_model_names
                ]
                # Renormalise — dropping a model means the remaining weights
                # no longer sum to 1.0
                ws = sum(tf_weights)
                if ws > 0:
                    tf_weights = [w / ws for w in tf_weights]

                # Apply regime bias on the SUCCESSFUL subset only
                regime = context.get('regime', 'unknown')
                tf_weights = self._apply_regime_bias(
                    tf_weights, successful_model_names, regime
                )
                raw_prediction = np.average(ensemble_preds, weights=tf_weights)
                weight_info = (f"weights={[f'{w:.3f}' for w in tf_weights]} "
                               f"[regime={regime}, "
                               f"{len(successful_model_names)}/{len(models)} models]")
            else:
                raw_prediction = np.mean(ensemble_preds)
                weight_info = "weights=equal (fallback — weight vector unavailable)"

            print(f"\n{tf_name}:")
            print(f"  Ensemble predictions: {[f'{p:.5f}' for p in ensemble_preds]}")
            print(f"  Weighted average: {raw_prediction:.5f} ({weight_info})")

            # Apply smoothing
            raw_log_return = np.log(raw_prediction / current_price)

            if self.use_kalman:
                smoothed_log_return = self.kalman_filters[tf_name].update(raw_log_return)
                smoothed_prediction = current_price * np.exp(smoothed_log_return)
                print(f"  Kalman smoothed: {smoothed_prediction:.5f}")
            else:
                if self.previous_predictions[tf_name] is not None:
                    prev_log_return = np.log(self.previous_predictions[tf_name] / current_price)
                    smoothed_log_return = self.ema_alpha * raw_log_return + (1 - self.ema_alpha) * prev_log_return
                    smoothed_prediction = current_price * np.exp(smoothed_log_return)
                    print(f"  EMA smoothed: {smoothed_prediction:.5f}")
                else:
                    smoothed_prediction = raw_prediction
                self.previous_predictions[tf_name] = smoothed_prediction

            # Sanity check
            max_change_pct = {'1H': 0.5, '4H': 1.0, '1D': 2.0}
            max_change = current_price * (max_change_pct.get(tf_name, 1.0) / 100.0)

            if abs(smoothed_prediction - current_price) > max_change:
                original_pred = smoothed_prediction
                if smoothed_prediction > current_price:
                    smoothed_prediction = current_price + max_change
                else:
                    smoothed_prediction = current_price - max_change
                print(f"  Capped from {original_pred:.5f} to {smoothed_prediction:.5f}")

            # Calculate change percentage
            change_pct = ((smoothed_prediction - current_price) / current_price) * 100.0

            predictions[tf_name] = {
                'prediction': round(smoothed_prediction, 5),
                'change_pct': round(change_pct, 3),
                'ensemble_std': round(np.std(ensemble_preds), 5)
            }

        # ── Fix 3: Uncertainty veto ────────────────────────────────────────────
        # When the ensemble models strongly disagree on a given bar their
        # individual predictions scatter widely.  A high relative std is a
        # signal that the bar is ambiguous; we block trading rather than
        # pick a direction arbitrarily.
        UNCERTAINTY_THRESHOLD = 0.008  # 0.8% of current price (~8.7 pips at 1.085)
        uncertainty_veto = False
        for tf_key, tf_data in predictions.items():
            rel_std = tf_data['ensemble_std'] / current_price
            if rel_std > UNCERTAINTY_THRESHOLD:
                uncertainty_veto = True
                print(f"   VETO (uncertainty): {tf_key} relative std={rel_std*100:.3f}% "
                      f"exceeds threshold {UNCERTAINTY_THRESHOLD*100:.1f}%")

        # ── Fix 5: Cross-timeframe directional agreement ───────────────────────
        # With exactly 3 timeframes, agreement_score can only be 1.0 (all agree)
        # or 0.333 (2-vs-1 split). The old threshold of 0.67 made a 2/3 majority
        # identical to full disagreement, permanently vetoing any mixed reading.
        # Threshold lowered to 0.30: passes on 2/3 majority (score=0.333),
        # only fires when all timeframes are split (impossible with 3, but safe
        # with 4+). Genuine model chaos is caught by uncertainty_veto above.
        if len(predictions) >= 2:
            directions = [
                1 if data['prediction'] > current_price else -1
                for data in predictions.values()
            ]
            agreement_score = abs(sum(directions)) / len(directions)
            print(f"   Directional agreement score: {agreement_score:.2f} "
                  f"(1.0=full, 0.33=split)")
            agreement_veto = agreement_score < 0.30
            if agreement_veto:
                print(f"   VETO (agreement): timeframes disagree on direction "
                      f"({agreement_score:.2f} < 0.30)")
                self.metrics.record_agreement_veto()
        else:
            agreement_score = 1.0
            agreement_veto = False

        # v9.4 — record the other vetoes (uncertainty was already detected
        # earlier in this method; we count it here for the rollup).
        if uncertainty_veto:           self.metrics.record_uncertainty_veto()
        if context.get('veto_active'): self.metrics.record_macro_veto()

        trade_allowed = (
            not context['veto_active']
            and not uncertainty_veto
            and not agreement_veto
        )

        # v9.4 — drain EA outcomes into the adaptive Bayesian posterior.
        # See single-TF cycle for rationale.
        self._ingest_ea_outcomes_into_adaptive()

        veto_reasons = []
        if context.get('veto_active'): veto_reasons += context.get('reasons', [])
        if uncertainty_veto:           veto_reasons += ["UNCERTAINTY"]
        if agreement_veto:             veto_reasons += ["AGREEMENT"]

        # Log this cycle's raw predictions so the next cycle can evaluate them
        # against the actual prices and feed the results into update_ensemble_weights.
        # This call was missing from the multi-TF path entirely — without it
        # pending_evaluations_*.json stays empty and weights can never evolve.
        timeframes_steps = {"1H": 1, "4H": 4, "1D": 24}
        self._log_prediction_for_evaluation(timeframes_steps, ensemble_predictions_map, current_price)

        # Save predictions and status
        status = {
            'last_update': datetime.now().isoformat(),
            # See timezone-fix note in the equivalent block above —
            # time.time() returns true UTC, datetime.utcnow().timestamp()
            # is offset by the local TZ.
            'last_updated_utc': int(time.time()),
            'status': 'online',
            'symbol': self.symbol,
            'current_price': round(current_price, 5),
            'method': 'multi-timeframe',
            'ensemble_weights': {
                tf_key: [round(w, 3) for w in weights]
                for tf_key, weights in self.ensemble_weights.items()
            },
            'market_context': context,
            'regime': context.get('regime', 'unknown'),
            'agreement_score': round(agreement_score, 3),
            'uncertainty_veto': uncertainty_veto,
            'agreement_veto': agreement_veto,
            'trade_allowed': trade_allowed,
            # v9.4: include for diagnostic visibility — EA reads ea_signal.json,
            # not this file.
            'confidence_floor_pct': round(self.adaptive.confidence_floor, 4),
        }

        self.save_to_file(self.predictions_file, predictions)
        self.save_to_file(self.status_file, status)

        # v9.4 — flat EA-facing signal file (issue #2). EA parses ONLY this.
        self._write_ea_signal(
            current_price=current_price,
            regime=context.get('regime', 'unknown'),
            trade_allowed=trade_allowed,
            veto_reasons=veto_reasons,
            timeframe_predictions=predictions,
        )

        # v9.2 — persist ensemble weights / history / model health so a
        # process restart picks up where this cycle left off.
        self._save_ensemble_state()
        # v9.4 — persist metrics rollup
        self._save_metrics()

        # Display results
        print("\n--- Prediction Cycle Complete! ---")
        print(f"Current Price: {current_price:.5f}")
        for timeframe, data in predictions.items():
            direction = "UP" if data['prediction'] > current_price else "DOWN"
            change_pct = ((data['prediction'] - current_price) / current_price) * 100
            print(f"   {direction} {timeframe}: {data['prediction']:.5f} ({change_pct:+.3f}%) (±{data['ensemble_std']:.5f})")

    def _log_prediction_for_evaluation(self, timeframes_steps: Dict[str, int],
                                       ensemble_predictions_map: Dict[str, List[float]],
                                       current_price: float) -> None:
        """Log predictions for future evaluation.

        Uses UTC throughout. _evaluate_past_predictions() must compare against
        UTC too — mixing local time and broker time was previously causing
        evaluations to look up the wrong bar (or no bar at all) on machines
        whose local TZ differs from the broker server's TZ.
        """
        try:
            with open(self.pending_eval_path, 'r') as f:
                pending = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pending = []

        now = datetime.utcnow()
        for tf_name, steps in timeframes_steps.items():
            if tf_name in ensemble_predictions_map:
                pending.append({
                    "eval_timestamp": (now + timedelta(hours=steps)).isoformat(),
                    "pred_timestamp": now.isoformat(),
                    "timeframe": tf_name,
                    "start_price": current_price,
                    "predictions": ensemble_predictions_map[tf_name]
                })

        # v9.3: atomic write via save_to_file (tmp + os.replace). A crash
        # mid-write previously corrupted the pending_evaluations file and
        # we'd lose every queued evaluation in the file at that moment.
        self.save_to_file(self.pending_eval_path, pending)

    def _read_ea_trade_outcomes(self) -> list:
        """
        Read trade outcomes appended by the EA ProcessClosedTrade() method.

        v9.3 fixes (CRITICAL):
        ----------------------
        1. **Filename mismatch fixed.** Previously this method read from
           `trade_outcomes_{symbol}.json` while the EA writes to
           `{symbol}_trade_outcomes.json`. The two paths never matched —
           every EA outcome since this feedback loop was introduced has
           been silently discarded by Python. The path here now matches
           the EA's CGGTHExpert::ProcessClosedTrade exactly.

        2. **TOCTOU race fixed.** The previous "read, then write []" pattern
           had a race window: any EA write between our read at line A and
           our truncate at line B was overwritten and lost. Worse, the
           write was non-atomic — a Python crash between read and truncate
           left the file empty even though the outcomes were never
           processed.

           The fix is rename-based atomic consume: we MOVE the live file
           to a sibling .processing path, then read from there and delete
           when done. Because the EA always writes via tmp+rename (v1.15),
           and we always READ via os.replace, neither side ever observes
           a partial file or loses an outcome — even on hard crash, a
           leftover .processing file just gets reclaimed on next run.
        """
        # v9.3: filename now matches EA. Old "trade_outcomes_{symbol}.json"
        # path was a typo and silently swallowed every closed-trade outcome.
        outcomes_path  = os.path.join(self.base_path,
                                      f'{self.symbol}_trade_outcomes.json')
        consumed_path  = outcomes_path + '.processing'

        # Reclaim a leftover .processing from a previous crashed run BEFORE
        # touching the live file. If we crashed last time after rename but
        # before reading, the data is sitting in .processing waiting for us.
        if os.path.exists(consumed_path):
            try:
                with open(consumed_path, 'r') as f:
                    leftover = json.load(f)
                os.remove(consumed_path)
                if isinstance(leftover, list) and leftover:
                    print(f"   [OUTCOMES] Reclaimed {len(leftover)} entries "
                          f"from previous crashed run")
                    # Fall through and append leftover to whatever the live
                    # file holds — see merge below.
                else:
                    leftover = []
            except (json.JSONDecodeError, OSError) as e:
                print(f"   [OUTCOMES] Could not reclaim leftover .processing "
                      f"file ({e}); deleting and continuing.")
                try:
                    os.remove(consumed_path)
                except OSError:
                    pass
                leftover = []
        else:
            leftover = []

        if not os.path.exists(outcomes_path):
            return leftover

        # Atomic consume: move the live file out from under the EA. If the
        # rename succeeds, we own the data. If a concurrent EA write
        # appears between rename and read, it lands in a fresh outcomes_path
        # and we'll see it on the next cycle — nothing is lost.
        try:
            os.replace(outcomes_path, consumed_path)
        except OSError as e:
            print(f"   [OUTCOMES] Could not rename {outcomes_path} for "
                  f"consume ({e}); skipping this cycle.")
            return leftover

        try:
            with open(consumed_path, 'r') as f:
                outcomes = json.load(f)
            os.remove(consumed_path)   # success — discard the consumed copy
        except (json.JSONDecodeError, OSError) as e:
            # Malformed JSON in the consumed file. The EA's atomic write
            # in v1.15 should make this impossible, but if it ever happens
            # the data is unrecoverable. Log loudly and discard.
            print(f"   [OUTCOMES] WARN: could not parse consumed outcomes "
                  f"({e}). Data lost — see {consumed_path} (preserved for "
                  f"diagnostics).")
            return leftover

        if not isinstance(outcomes, list):
            print(f"   [OUTCOMES] WARN: outcomes file root is "
                  f"{type(outcomes).__name__}, expected list. Discarding.")
            return leftover

        return leftover + outcomes

    def _evaluate_past_predictions(self) -> None:
        """Evaluate past predictions against actual prices."""
        print("Evaluating past predictions for ensemble weighting...")

        # Merge EA trade outcomes into weight update (feedback loop).
        #
        # v9.3 note: prior implementation appended EA outcomes to
        # self.prediction_history with an empty 'predictions': [] field.
        # update_ensemble_weights then correctly skipped them, but they
        # still consumed slots in the bounded history (cap = ensemble_lookback,
        # default 20) — pushing real model-prediction entries out faster.
        #
        # We now read the outcomes (so the EA-side file is drained and
        # doesn't grow unbounded), but we do NOT append empty placeholders
        # to prediction_history. If a future revision wants to use traded
        # P/L to bias weights, it should be a separate signal stored in a
        # dedicated container, not muddled with model-error history.
        ea_outcomes = self._read_ea_trade_outcomes()
        if ea_outcomes:
            print(f'   Drained {len(ea_outcomes)} EA trade outcomes from '
                  f'feedback file (not yet wired into ensemble weights — '
                  f'see _evaluate_past_predictions docstring).')

        try:
            with open(self.pending_eval_path, 'r') as f:
                pending = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            print("   No pending predictions to evaluate.")
            return

        remaining_evals = []
        evaluated_count = 0
        expired_count = 0
        # Use UTC consistently — eval_timestamps were written with utcnow(),
        # so we must compare with utcnow() here too.
        now = datetime.utcnow()

        # Drop entries older than 7 days that we never managed to evaluate.
        # Without this, transient MT5 history gaps (weekend gaps, purged old
        # bars, etc.) cause stale entries to accumulate forever and re-tried
        # every cycle.
        STALE_AFTER = timedelta(days=7)

        for entry in pending:
            try:
                eval_time = datetime.fromisoformat(entry['eval_timestamp'])

                # Ensure timezone-naive datetime for comparison
                if eval_time.tzinfo is not None:
                    eval_time = eval_time.replace(tzinfo=None)

                # Expire stale entries
                if (now - eval_time) > STALE_AFTER:
                    expired_count += 1
                    continue

                if now >= eval_time:
                    # Fetch actual price at evaluation time using a window query.
                    # mt5.copy_rates_from(eval_time, 1) interprets eval_time as
                    # broker server time (via local-tz translation in the python
                    # bindings), so on a machine whose local TZ ≠ broker TZ the
                    # exact-match lookup misses or returns the wrong bar.
                    # Querying a ±12h range and picking the closest bar is
                    # robust to any reasonable TZ offset.
                    window_start = eval_time - timedelta(hours=12)
                    window_end   = eval_time + timedelta(hours=12)
                    rates = mt5.copy_rates_range(self.symbol, mt5.TIMEFRAME_H1,
                                                 window_start, window_end)
                    if rates is not None and len(rates) > 0:
                        rates_df = pd.DataFrame(rates)
                        rates_df['time_dt'] = pd.to_datetime(rates_df['time'], unit='s')
                        # Closest bar to eval_time
                        diff = (rates_df['time_dt'] - eval_time).abs()
                        closest_idx = diff.idxmin()
                        actual_future_price = float(rates_df.iloc[closest_idx]['close'])
                        self.prediction_history[entry['timeframe']].append({
                            'predictions': entry['predictions'],
                            'actual': actual_future_price,
                            'timestamp': entry['pred_timestamp']
                        })
                        # Keep only recent history
                        if len(self.prediction_history[entry['timeframe']]) > self.ensemble_lookback:
                            self.prediction_history[entry['timeframe']].pop(0)
                        evaluated_count += 1

                        # v9.4 — record per-TF metrics. We use the ensemble
                        # mean as the "predicted" value (matches what the
                        # EA acted on); start_price is the price at the
                        # moment the prediction was made.
                        try:
                            tf_name      = entry['timeframe']
                            preds_list   = entry.get('predictions') or []
                            # v9.5 — predictions list now carries None for
                            # any model that failed at prediction time. Strip
                            # them before computing the ensemble mean.
                            preds_clean  = [p for p in preds_list if p is not None]
                            start_price  = float(entry.get('start_price', 0.0))
                            if preds_clean and start_price > 0:
                                ensemble_mean = float(np.mean(preds_clean))
                                self.metrics.record_evaluation(
                                    tf=tf_name,
                                    predicted=ensemble_mean,
                                    realised=actual_future_price,
                                    start_price=start_price,
                                )
                        except Exception:
                            # metrics recording must NEVER break the eval path
                            pass
                    else:
                        # Keep for retry if data not available yet (still under expiry)
                        remaining_evals.append(entry)
                else:
                    # Not time to evaluate yet
                    remaining_evals.append(entry)
            except Exception as e:
                print(f"   Error evaluating entry: {e}")
                continue

        print(f"   Evaluated {evaluated_count} predictions. "
              f"{len(remaining_evals)} remaining. {expired_count} expired (>7d).")

        # Save remaining evaluations (atomic — see save_to_file)
        self.save_to_file(self.pending_eval_path, remaining_evals)

    def update_ensemble_weights(self) -> None:
        """
        Update per-timeframe ensemble weights based on past prediction accuracy.

        Each timeframe (1H, 4H, 1D) maintains its own weight vector so that
        a model that excels on 1H but is mediocre on 1D gets rewarded
        independently for each horizon.  Previously a single shared list was
        updated by mixing errors across all timeframes, which muddied the
        signal — that bug is fixed here.
        """
        if not self.ensemble_weights:
            return

        print("Updating per-timeframe ensemble weights...")

        for tf_name, tf_history in self.prediction_history.items():
            if not tf_history:
                continue

            model_errors = [0.0] * self.num_ensemble_models
            # v9.5 — count samples PER MODEL, not per cycle. Previously the
            # weight learner divided every model's accumulated error by
            # the same total_samples count, so a model that failed half
            # the time looked half as bad as it really was — and a model
            # that always failed (predictions = None for that slot) had
            # error 0 / N = 0, which the softmax interpreted as perfect
            # accuracy. Now each model has its own n and a model that
            # produced no successful evaluations is excluded from the
            # softmax entirely (its weight is preserved unchanged).
            model_sample_counts = [0] * self.num_ensemble_models
            total_samples = 0
            skipped_ea = 0

            for entry in tf_history:
                preds = entry.get('predictions', [])
                # Skip entries with no per-model predictions (e.g. EA trade-outcome
                # feedback rows). Counting them in total_samples but not in
                # model_errors used to *dilute* the average MAE — making every
                # model look more accurate than it actually was, then the
                # softmax narrowed the weight spread further.
                if not preds:
                    skipped_ea += 1
                    continue
                actual = entry['actual']
                for i, pred in enumerate(preds):
                    if i >= len(model_errors):
                        continue
                    # v9.5 — None means "this model failed for this cycle".
                    # Don't accumulate its error and don't count it toward
                    # its own sample count. Other models in the same row
                    # are still counted; they each have their own bucket.
                    if pred is None:
                        continue
                    model_errors[i]        += abs(pred - actual)
                    model_sample_counts[i] += 1
                total_samples += 1

            if skipped_ea:
                print(f"   {tf_name}: skipped {skipped_ea} EA-feedback entries "
                      f"(no per-model breakdown to attribute error)")

            if total_samples < 5:
                print(f"   {tf_name}: Not enough evaluated predictions ({total_samples}/5 minimum).")
                continue

            # v9.5 — per-model average error using each model's OWN sample count.
            # Models with zero successful samples in the window are NOT included
            # in the softmax (we'd otherwise default-divide-by-1 and treat the
            # zero accumulator as perfect skill). Their existing weights are
            # preserved, only the participating models' weights are renormalised.
            participating: List[int] = []
            avg_errors_part: List[float] = []
            for i in range(self.num_ensemble_models):
                if model_sample_counts[i] > 0:
                    participating.append(i)
                    avg_errors_part.append(model_errors[i] / model_sample_counts[i])

            if not participating:
                print(f"   {tf_name}: no models had any successful evaluations — "
                      f"keeping current weights.")
                continue

            # Diagnostic: show per-model n alongside the average error
            avg_errors_full = [
                (model_errors[i] / model_sample_counts[i]) if model_sample_counts[i] > 0 else None
                for i in range(self.num_ensemble_models)
            ]

            # v9.5 — softmax over the PARTICIPATING subset only. Computing
            # softmax over the full vector with zero-error placeholder slots
            # for non-participating models would have given them all the
            # weight (exp(-0) = 1, the highest possible value).
            min_error = min(avg_errors_part) if avg_errors_part else 1e-8
            normalized_errors = [err / max(min_error, 1e-8) for err in avg_errors_part]

            temperature = 2.0  # higher -> more equal weights; lower -> winner-takes-more
            exp_neg_errors = [np.exp(-err / temperature) for err in normalized_errors]
            total_exp = sum(exp_neg_errors)

            if total_exp == 0:
                print(f"   {tf_name}: WARNING: all softmax weights are zero — keeping current weights.")
                continue

            # new_weights_part is in PARTICIPATING order, length = len(participating).
            # We need to expand it back to a full-length vector aligned to
            # self.num_ensemble_models, with non-participating models keeping
            # their current weight.
            current_weights = self.ensemble_weights.get(
                tf_name,
                [1.0 / self.num_ensemble_models] * self.num_ensemble_models
            )
            new_weights_full = list(current_weights)   # start as copy

            # Decide what fraction of the total weight budget to allocate
            # to participating models. Non-participating models keep their
            # existing weights (and thus existing share of the budget);
            # the remainder is divvied up among participating models in
            # proportion to the softmax.
            non_part_share = sum(
                current_weights[i]
                for i in range(self.num_ensemble_models)
                if i not in participating
            )
            part_budget = max(0.0, 1.0 - non_part_share)

            for k, model_idx in enumerate(participating):
                # softmax-derived target weight, scaled to fit the part_budget
                target_w = part_budget * (exp_neg_errors[k] / total_exp)
                old_w    = current_weights[model_idx]
                new_weights_full[model_idx] = (
                    (1 - self.ensemble_learning_rate) * old_w
                    + self.ensemble_learning_rate * target_w
                )

            # Re-normalise (float arithmetic can shift the sum slightly off 1.0)
            weight_sum = sum(new_weights_full)
            if weight_sum > 0:
                new_weights_full = [w / weight_sum for w in new_weights_full]

            self.ensemble_weights[tf_name] = new_weights_full

            # Diagnostic — print per-model n alongside the per-model error so
            # zero-sample models are visibly distinguishable from real-zero
            # error (which should not occur but if it does we want to see it).
            mae_str = []
            for i, e in enumerate(avg_errors_full):
                if e is None:
                    mae_str.append(f"-(n=0)")
                else:
                    mae_str.append(f"{e:.6f}(n={model_sample_counts[i]})")
            print(f"   {tf_name} - Avg MAE per model: {mae_str}")
            print(f"   {tf_name} - Updated weights:   {[f'{w:.3f}' for w in new_weights_full]}")

    def run_safe_backtest(self):
        """
        Walk-Forward Backtester.
        Fixes the 'Read-Ahead' cheating problem.
        """
        print("\n" + "=" * 80)
        print("Starting Safe Backtest (Walk-Forward Anti-Leakage)")
        print("=" * 80)

        # Try to load multi-timeframe models first, fall back to single-timeframe
        use_multitf = False
        if not self.models_by_timeframe:
            if self.load_model_assets_multitimeframe():
                use_multitf = True
                print("Using multi-timeframe models")
            elif not self.models:
                if not self.load_model_assets():
                    print("ERROR: Cannot run safe backtest without trained models.")
                    return
                print("Using single-timeframe models (less accurate)")
        else:
            use_multitf = True
            print("Using multi-timeframe models")

        # Download data scoped to the prediction window (with lookback padding)
        self._warn_if_predict_overlaps_training()
        if self.predict_start or self.predict_end:
            print(f"[DATE FILTER] Prediction window: "
                  f"{self.predict_start.strftime('%Y-%m-%d') if self.predict_start else 'beginning'} "
                  f"-> {self.predict_end.strftime('%Y-%m-%d') if self.predict_end else 'end'}\n")
        extra = timedelta(hours=2000 + 24)  # pad for walk-forward window
        dl_from = (self.predict_start - extra) if self.predict_start else None
        df_h1, df_h4, df_d1 = self.download_data(bars=15000, date_from=dl_from, date_to=self.predict_end)
        if df_h1 is None:
            return
            
        df_full = self.create_features(df_h1, df_h4, df_d1)

        # Build the column union that covers every per-TF feature list, so any
        # TF can pluck its own subset from df_selected at predict time.
        # Falls back to the base feature list when no per-TF lists are loaded.
        all_features = set()
        for tf_features in self.feature_cols_by_tf.values():
            all_features.update(tf_features)
        if not all_features and self.feature_cols:
            all_features = set(self.feature_cols)
        union_features = [c for c in all_features if c in df_full.columns]
        df_selected = df_full[union_features + ['fwd_log_return_1h', 'fwd_log_return_4h', 'fwd_log_return_1d', 'close']]

        window = 2000  # Minimum training window
        step = 100     # Step size between predictions
        
        # Only use timeframes the EA supports
        timeframes = {"1H": 1, "4H": 4, "1D": 24}
        results = {tf: {'timestamps': [], 'actual': [], 'predicted': []} for tf in timeframes.keys()}
        
        total_iterations = (len(df_full) - window - 1) // step
        print(f"\nTotal iterations: {total_iterations}")
        print(f"Training window: {window} bars")
        print(f"Step size: {step} bars\n")

        iteration = 0
        for i in range(window, len(df_full) - 1, step):
            iteration += 1
            
            # Training only on past data (NO FUTURE LEAKAGE)
            past = df_full.iloc[:i]
            current_idx = i

            # ── Anti-leakage anchor (v9.1) ─────────────────────────────────────
            # Predictions stamped at index[current_idx] (open time of bar i)
            # must be anchored on close[current_idx - 1] — the last close
            # actually known at that instant. close[current_idx] is bar i's
            # close, a future value relative to the timestamp. See the matching
            # note in run_backtest_generation. current_price is retained here
            # only for the progress print.
            anchor_price  = df_selected['close'].iloc[current_idx - 1]
            current_price = df_selected['close'].iloc[current_idx]   # progress-print only
            timestamp     = df_selected.index[current_idx]

            # Skip bars outside the requested prediction window
            ts_dt = timestamp.to_pydatetime() if hasattr(timestamp, 'to_pydatetime') else timestamp
            if self.predict_start and ts_dt < self.predict_start:
                continue
            if self.predict_end and ts_dt > self.predict_end:
                break
            
            # Make predictions for each timeframe
            for tf_name, steps in timeframes.items():
                ensemble_preds = []
                
                if use_multitf and tf_name in self.models_by_timeframe:
                    # Use multi-timeframe models (NO SCALING!)
                    models = self.models_by_timeframe[tf_name]
                    feature_scaler, target_scaler = self.scalers_by_timeframe[tf_name]
                    tf_features = self.feature_cols_by_tf.get(tf_name, self.feature_cols)

                    # CRITICAL: do NOT refit the feature scaler here. The trained
                    # models learned weights against the ORIGINAL training-time
                    # scaler. Refitting at predict-time changes the input
                    # distribution out from under the model and silently
                    # invalidates everything it learned. Refitting does not
                    # prevent look-ahead bias (that's a training-time concern);
                    # it only breaks calibration. Use the loaded scaler as-is.
                    features_scaled = feature_scaler.transform(df_selected[tf_features].iloc[:i+1].values)

                    if current_idx >= self.lookback_periods:
                        X_pred_seq = features_scaled[current_idx - self.lookback_periods:current_idx].reshape(
                            1, self.lookback_periods, len(tf_features)
                        )
                        X_pred_seq = tf.convert_to_tensor(X_pred_seq, dtype=tf.float32)

                        for model_name, model in models.items():
                            try:
                                if 'lgbm' in model_name:
                                    # Prepare tabular data
                                    df_tabular = df_selected.iloc[:i+1].copy()
                                    for col in tf_features:
                                        for lag in [1, 3, 5, 10]:
                                            new_col = f'{col}_lag_{lag}'
                                            df_tabular[new_col] = df_tabular[col].shift(lag)
                                    df_tabular.ffill(inplace=True)
                                    
                                    if timestamp in df_tabular.index:
                                        X_pred_tab = df_tabular.loc[timestamp][model.feature_name_].values.reshape(1, -1)
                                        pred_log_return = model.predict(X_pred_tab)[0]
                                    else:
                                        continue
                                else:
                                    pred_log_return_scaled = model(X_pred_seq, training=False).numpy()[0][0]
                                    pred_log_return = target_scaler.inverse_transform([[pred_log_return_scaled]])[0][0]
                                
                                # NO SCALING - multi-TF models predict for their specific timeframe
                                # Anchor on close[current_idx-1] (anti-leakage)
                                predicted_price = anchor_price * np.exp(pred_log_return)
                                
                                if not np.isnan(predicted_price) and not np.isinf(predicted_price):
                                    ensemble_preds.append(predicted_price)
                            except Exception:
                                continue
                else:
                    # Fallback: single-timeframe models with scaling.
                    # Same scaler-refit prohibition applies here — see comment above.
                    features_scaled = self.feature_scaler.transform(df_selected[self.feature_cols].iloc[:i+1].values)
                    
                    if current_idx >= self.lookback_periods:
                        X_pred_seq = features_scaled[current_idx - self.lookback_periods:current_idx].reshape(
                            1, self.lookback_periods, len(self.feature_cols)
                        )
                        X_pred_seq = tf.convert_to_tensor(X_pred_seq, dtype=tf.float32)
                        
                        for model_name, model in self.models.items():
                            try:
                                if 'lgbm' in model_name:
                                    continue  # Skip LGBM for simplicity
                                else:
                                    pred_log_return_scaled = model(X_pred_seq, training=False).numpy()[0][0]
                                    pred_log_return = self.target_scaler.inverse_transform([[pred_log_return_scaled]])[0][0]
                                
                                # Linear scaling for log-return drift across
                                # horizons (see comment in run_prediction_cycle).
                                # Anchor on close[current_idx-1] (anti-leakage)
                                steps_adjusted = float(steps)
                                predicted_price = anchor_price * np.exp(pred_log_return * steps_adjusted)
                                
                                if not np.isnan(predicted_price) and not np.isinf(predicted_price):
                                    ensemble_preds.append(predicted_price)
                            except Exception:
                                continue
                
                if ensemble_preds:
                    tf_weights = self.ensemble_weights.get(tf_name, [])
                    if tf_weights and len(tf_weights) == len(ensemble_preds):
                        weighted_price = np.average(ensemble_preds, weights=tf_weights)
                    else:
                        weighted_price = np.mean(ensemble_preds)

                    # Get actual future price (if available).
                    # Shifted -1 to match the new anchor: model trained on
                    # features-at-row-k → log_return from close[k] to close[k+steps].
                    # Inference at row current_idx with features through
                    # current_idx-1 therefore predicts close[(current_idx-1)+steps].
                    future_idx = min(current_idx + steps - 1, len(df_selected) - 1)
                    actual_price = df_selected['close'].iloc[future_idx]
                    
                    results[tf_name]['timestamps'].append(timestamp)
                    results[tf_name]['predicted'].append(weighted_price)
                    results[tf_name]['actual'].append(actual_price)
            
            # Progress indicator
            if iteration % 10 == 0 or iteration == 1:
                progress = (iteration / total_iterations) * 100
                print(f"Progress: {progress:.1f}% | Bar: {timestamp} | Price: {current_price:.5f}")
        
        # Calculate and display metrics
        print("\n" + "=" * 80)
        print("SAFE BACKTEST RESULTS (No Look-Ahead Bias)")
        print("=" * 80)
        
        for tf_name in timeframes.keys():
            if len(results[tf_name]['predicted']) > 0:
                predicted = np.array(results[tf_name]['predicted'])
                actual = np.array(results[tf_name]['actual'])
                
                # Calculate metrics
                mae = np.mean(np.abs(predicted - actual))
                mape = np.mean(np.abs((actual - predicted) / actual)) * 100
                rmse = np.sqrt(np.mean((predicted - actual) ** 2))
                
                # Directional accuracy
                pred_direction = np.sign(np.diff(predicted))
                actual_direction = np.sign(np.diff(actual))
                directional_accuracy = np.mean(pred_direction == actual_direction) * 100
                
                print(f"\n{tf_name} Timeframe:")
                print(f"  MAE:  {mae:.5f}")
                print(f"  MAPE: {mape:.2f}%")
                print(f"  RMSE: {rmse:.5f}")
                print(f"  Directional Accuracy: {directional_accuracy:.2f}%")
        
        # Export results to CSV
        self.export_safe_backtest_results(results)
        print("\n" + "=" * 80)
        print("SAFE BACKTEST COMPLETE!")
        print("=" * 80)

    def export_safe_backtest_results(self, results: Dict[str, Dict[str, List]]) -> None:
        """Export safe backtest results to CSV files."""
        print("\nExporting safe backtest results...")
        
        for tf_name, data in results.items():
            if len(data['timestamps']) > 0:
                output_file = os.path.join(self.base_path, f'{self.symbol}_{tf_name}_safe_backtest.csv')
                
                try:
                    df_results = pd.DataFrame({
                        'timestamp': data['timestamps'],
                        'predicted': data['predicted'],
                        'actual': data['actual'],
                        'error': np.array(data['predicted']) - np.array(data['actual']),
                        'abs_error': np.abs(np.array(data['predicted']) - np.array(data['actual']))
                    })
                    
                    df_results.to_csv(output_file, index=False)
                    print(f"   Created: {output_file}")
                except Exception as e:
                    print(f"   Error creating {output_file}: {e}")

    def run_backtest_generation(self) -> None:
        """Generate historical predictions for backtesting."""
        print("\n" + "=" * 60)
        print("Starting Backtest Generation...")
        print("=" * 60)

        # Warn if prediction window overlaps training window
        self._warn_if_predict_overlaps_training()

        if self.predict_start or self.predict_end:
            print(f"[DATE FILTER] Prediction window: "
                  f"{self.predict_start.strftime('%Y-%m-%d') if self.predict_start else 'beginning'} "
                  f"-> {self.predict_end.strftime('%Y-%m-%d') if self.predict_end else 'end'}\n")

        # Try to load multi-timeframe models first, fall back to single-timeframe
        use_multitf = False
        if not self.models_by_timeframe:
            if self.load_model_assets_multitimeframe():
                use_multitf = True
                print("Using multi-timeframe models")
            elif not self.models:
                if not self.load_model_assets():
                    print("ERROR: No trained models found.")
                    return
                print("Using single-timeframe models (less accurate)")
        else:
            use_multitf = True
            print("Using multi-timeframe models")

        # Download historical data scoped to the prediction window
        # We need slightly more data than the window itself so the lookback
        # buffer (60 bars) is populated for the very first prediction.
        extra = timedelta(hours=self.lookback_periods + 24)  # a bit of padding
        dl_from = (self.predict_start - extra) if self.predict_start else None
        df_h1, df_h4, df_d1 = self.download_data(bars=40000, date_from=dl_from, date_to=self.predict_end)
        if df_h1 is None:
            return

        # Create features
        df = self.create_features(df_h1, df_h4, df_d1)

        # Build the column union covering every per-TF feature list
        all_features = set()
        for tf_features in self.feature_cols_by_tf.values():
            all_features.update(tf_features)
        if not all_features and self.feature_cols:
            all_features = set(self.feature_cols)
        union_features = [c for c in all_features if c in df.columns]
        df_selected = df[union_features + ['fwd_log_return_1h', 'fwd_log_return_4h', 'fwd_log_return_1d', 'close']]

        # Only generate for timeframes the EA supports
        timeframes = {"1H": 1, "4H": 4, "1D": 24}
        all_predictions  = {tf: [] for tf in timeframes.keys()}
        all_change_pcts  = {tf: [] for tf in timeframes.keys()}
        all_ensemble_stds = {tf: [] for tf in timeframes.keys()}
        timestamps = []

        print(f"Generating predictions for {len(df_selected) - self.lookback_periods} bars...")

        for i in range(self.lookback_periods, len(df_selected)):
            # ── Anti-leakage anchor (v9.1) ─────────────────────────────────────
            # The prediction stamped at index[i] (the OPEN time of bar i) must
            # be anchored on data available at that instant — i.e. close[i-1],
            # NOT close[i]. The previous version used close[i] which is bar i's
            # CLOSE, a value not yet observable when the EA reads this row at
            # the start of bar i. That 1-bar look-ahead made TP land inside
            # bar i's range and produced ~100% win rates in tester.
            anchor_price = df_selected['close'].iloc[i - 1]
            timestamp    = df_selected.index[i]

            # --- Skip bars outside the requested prediction window ---
            ts_dt = timestamp.to_pydatetime() if hasattr(timestamp, 'to_pydatetime') else timestamp
            if self.predict_start and ts_dt < self.predict_start:
                continue
            if self.predict_end and ts_dt > self.predict_end:
                break

            # Get predictions for each timeframe
            for tf_name, steps in timeframes.items():
                ensemble_preds = []
                
                if use_multitf and tf_name in self.models_by_timeframe:
                    # Use multi-timeframe models (NO SCALING!)
                    models = self.models_by_timeframe[tf_name]
                    feature_scaler, target_scaler = self.scalers_by_timeframe[tf_name]
                    tf_features = self.feature_cols_by_tf.get(tf_name, self.feature_cols)

                    # Scale features
                    features_scaled = feature_scaler.transform(df_selected[tf_features].values)
                    X_pred_seq = features_scaled[i - self.lookback_periods:i].reshape(
                        1, self.lookback_periods, len(tf_features)
                    )
                    X_pred_seq = tf.convert_to_tensor(X_pred_seq, dtype=tf.float32)

                    for model_name, model in models.items():
                        try:
                            if 'lgbm' in model_name:
                                # Prepare tabular data for LightGBM
                                df_tabular = df_selected.iloc[:i+1].copy()
                                for col in tf_features:
                                    for lag in [1, 3, 5, 10]:
                                        new_col = f'{col}_lag_{lag}'
                                        df_tabular[new_col] = df_tabular[col].shift(lag)
                                df_tabular.ffill(inplace=True)
                                
                                if timestamp in df_tabular.index:
                                    X_pred_tab = df_tabular.loc[timestamp][model.feature_name_].values.reshape(1, -1)
                                    pred_log_return = model.predict(X_pred_tab)[0]
                                else:
                                    continue
                            else:
                                pred_log_return_scaled = model(X_pred_seq, training=False).numpy()[0][0]
                                pred_log_return = target_scaler.inverse_transform([[pred_log_return_scaled]])[0][0]
                            
                            # NO SCALING by steps - multi-TF models already predict for their timeframe
                            # Anchor on close[i-1] (anti-leakage — see v9.1 note above)
                            predicted_price = anchor_price * np.exp(pred_log_return)
                            
                            if not np.isnan(predicted_price) and not np.isinf(predicted_price):
                                ensemble_preds.append(predicted_price)
                        except Exception:
                            continue
                else:
                    # Fallback: single-timeframe models with scaling
                    features_scaled = self.feature_scaler.transform(df_selected[self.feature_cols].values)
                    X_pred_seq = features_scaled[i - self.lookback_periods:i].reshape(
                        1, self.lookback_periods, len(self.feature_cols)
                    )
                    X_pred_seq = tf.convert_to_tensor(X_pred_seq, dtype=tf.float32)
                    
                    for model_name, model in self.models.items():
                        try:
                            if 'lgbm' in model_name:
                                continue  # Skip LGBM for simplicity in fallback mode
                            else:
                                pred_log_return_scaled = model(X_pred_seq, training=False).numpy()[0][0]
                                pred_log_return = self.target_scaler.inverse_transform([[pred_log_return_scaled]])[0][0]
                            
                            # Linear scaling for log-return drift across
                            # horizons (see comment in run_prediction_cycle).
                            # Anchor on close[i-1] (anti-leakage — see v9.1 note above)
                            steps_adjusted = float(steps)
                            predicted_price = anchor_price * np.exp(pred_log_return * steps_adjusted)
                            
                            if not np.isnan(predicted_price) and not np.isinf(predicted_price):
                                ensemble_preds.append(predicted_price)
                        except Exception:
                            continue

                if ensemble_preds:
                    tf_weights = self.ensemble_weights.get(tf_name, [])
                    if tf_weights and len(tf_weights) == len(ensemble_preds):
                        weighted_price = np.average(ensemble_preds, weights=tf_weights)
                    else:
                        weighted_price = np.mean(ensemble_preds)
                    all_predictions[tf_name].append(weighted_price)
                    chg = ((weighted_price - anchor_price) / anchor_price) * 100.0
                    all_change_pcts[tf_name].append(round(chg, 3))
                    std = np.std(ensemble_preds) if len(ensemble_preds) > 1 else 0.0
                    all_ensemble_stds[tf_name].append(round(std, 5))
                else:
                    # No model output — emit anchor so the EA sees zero delta_pips
                    all_predictions[tf_name].append(anchor_price)
                    all_change_pcts[tf_name].append(0.0)
                    all_ensemble_stds[tf_name].append(0.0)

            timestamps.append(timestamp)

            # Progress indicator
            if (i - self.lookback_periods) % 500 == 0:
                progress = ((i - self.lookback_periods) / (len(df_selected) - self.lookback_periods)) * 100
                print(f"   Progress: {progress:.1f}%")

        # Export backtest files
        self.export_backtest_files(timestamps, all_predictions, all_change_pcts, all_ensemble_stds)
        print("\nBACKTEST GENERATION COMPLETE!")

    def export_backtest_files(self, timestamps: List, predictions: Dict[str, List[float]],
                              change_pcts: Dict[str, List[float]] = None,
                              ensemble_stds: Dict[str, List[float]] = None) -> None:
        """Export backtest predictions to CSV files."""
        print("\nExporting backtest files...")
        
        # Get the Common Files path for Strategy Tester
        # Common path is: AppData\Roaming\MetaQuotes\Terminal\Common\Files
        common_path = None
        try:
            appdata = os.environ.get('APPDATA', '')
            if appdata:
                common_path = os.path.join(appdata, 'MetaQuotes', 'Terminal', 'Common', 'Files')
                if not os.path.exists(common_path):
                    os.makedirs(common_path, exist_ok=True)
        except Exception as e:
            print(f"   Warning: Could not create Common Files folder: {e}")
        
        for tf_name, pred_values in predictions.items():
            # Save to regular MQL5\Files folder
            lookup_file = os.path.join(self.base_path, f'{self.symbol}_{tf_name}_lookup.csv')
            try:
                chg_list = change_pcts.get(tf_name, []) if change_pcts else []
                std_list = ensemble_stds.get(tf_name, []) if ensemble_stds else []
                with open(lookup_file, 'w') as f:
                    f.write('timestamp,prediction,change_pct,ensemble_std\n')
                    for idx_row, (ts, pred) in enumerate(zip(timestamps, pred_values)):
                        chg = chg_list[idx_row] if idx_row < len(chg_list) else 0.0
                        std = std_list[idx_row] if idx_row < len(std_list) else 0.0
                        f.write(f'{ts.strftime("%Y.%m.%d %H:%M")},{pred:.5f},{chg:.3f},{std:.5f}\n')
                print(f"   Created: {lookup_file}")
            except Exception as e:
                print(f"   Error creating {lookup_file}: {e}")
            
            # ALSO save to Common Files folder for Strategy Tester
            if common_path:
                common_lookup_file = os.path.join(common_path, f'{self.symbol}_{tf_name}_lookup.csv')
                try:
                    with open(common_lookup_file, 'w') as f:
                        f.write('timestamp,prediction,change_pct,ensemble_std\n')
                        for idx_row, (ts, pred) in enumerate(zip(timestamps, pred_values)):
                            chg = chg_list[idx_row] if idx_row < len(chg_list) else 0.0
                            std = std_list[idx_row] if idx_row < len(std_list) else 0.0
                            f.write(f'{ts.strftime("%Y.%m.%d %H:%M")},{pred:.5f},{chg:.3f},{std:.5f}\n')
                    print(f"   Created (Common): {common_lookup_file}")
                except Exception as e:
                    print(f"   Error creating Common file: {e}")
        
        print("\n" + "=" * 60)
        print("BACKTEST FILES CREATED")
        print("=" * 60)
        print(f"\nFiles saved to TWO locations:")
        print(f"  1. Regular:  {self.base_path}")
        print(f"  2. Common:   {common_path}")
        print(f"\nFor Strategy Tester, files MUST be in the Common folder.")
        print("=" * 60)

    def save_to_file(self, file_path: str, data: Any) -> None:
        """
        Atomically save JSON-serialisable data (dict or list) to a file.

        Writes to a .tmp sibling first, then uses os.replace() which is atomic
        on both Windows NTFS and Linux ext4.  This guarantees the EA always sees
        a complete file rather than a truncated mid-write JSON.

        v9.3: signature widened from Dict to Any so it can also be used for
        list-rooted files like pending_evaluations and trade_outcomes.
        """
        tmp_path = file_path + '.tmp'
        try:
            with open(tmp_path, 'w') as f:
                json.dump(data, f, indent=4)
            os.replace(tmp_path, file_path)   # atomic rename
        except Exception as e:
            print(f"Error saving to {file_path}: {e}")
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    # -------------------------------------------------------------------------
    # v9.2 — Ensemble state persistence
    # -------------------------------------------------------------------------
    def _save_ensemble_state(self) -> None:
        """
        Persist learned ensemble weights, recent prediction history, and
        per-model health counters to disk.

        Without this, every process restart resets weights to equal and the
        evaluation buffer to empty — meaning the next ~5 cycles re-learn
        what the previous run already knew. The file is small (a few KB).

        Schema-versioned so future upgrades can migrate cleanly.
        """
        # Cap history per timeframe to ensemble_lookback to keep the file small
        # and avoid replaying ancient stale evaluations after a long downtime.
        capped_history = {
            tf: hist[-self.ensemble_lookback:]
            for tf, hist in self.prediction_history.items()
        }
        state = {
            "schema_version": 1,
            "saved_at_utc":   datetime.utcnow().isoformat(),
            "symbol":         self.symbol,
            "model_types":    self.ensemble_model_types,
            "ensemble_weights": self.ensemble_weights,
            "prediction_history": capped_history,
            "model_health":   self.model_health,
        }
        self.save_to_file(self.ensemble_state_path, state)

    def _load_ensemble_state(self) -> None:
        """
        Restore ensemble weights, prediction history, and model health from
        the previous run's state file. No-op if the file doesn't exist or
        if the saved model_types list disagrees with this process's models
        (in which case applying old weights would be unsafe).
        """
        if not os.path.exists(self.ensemble_state_path):
            return
        try:
            with open(self.ensemble_state_path, "r") as f:
                state = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[STATE] Could not read {self.ensemble_state_path}: {e}. "
                  "Starting fresh.")
            return

        # Schema gate — refuse to load forwards-incompatible files
        sv = state.get("schema_version", 0)
        if sv != 1:
            print(f"[STATE] Ignoring saved state with schema_version={sv} "
                  f"(this build expects 1). Starting fresh.")
            return

        # Model-list gate — if the saved set doesn't match the current set,
        # the per-model weight slots don't align and applying them would
        # silently bias the wrong models. Require an exact list match.
        saved_models = state.get("model_types", [])
        if saved_models and saved_models != self.ensemble_model_types:
            print(f"[STATE] Saved state was for models {saved_models} "
                  f"but this run uses {self.ensemble_model_types}. "
                  "Starting fresh.")
            return

        loaded_weights = state.get("ensemble_weights", {})
        for tf, weights in loaded_weights.items():
            if tf in self.ensemble_weights and len(weights) == self.num_ensemble_models:
                self.ensemble_weights[tf] = list(weights)

        loaded_history = state.get("prediction_history", {})
        for tf, hist in loaded_history.items():
            if tf in self.prediction_history and isinstance(hist, list):
                # Cap on load too (safety against tampered files)
                self.prediction_history[tf] = hist[-self.ensemble_lookback:]

        loaded_health = state.get("model_health", {})
        for tf, fmap in loaded_health.items():
            if tf in self.model_health and isinstance(fmap, dict):
                # Coerce to int; a stringified count in the JSON would silently
                # break the >= comparisons in the health checker
                self.model_health[tf] = {
                    name: int(count) for name, count in fmap.items()
                }

        saved_at = state.get("saved_at_utc", "?")
        print(f"[STATE] Restored ensemble state from {saved_at}")
        for tf, weights in self.ensemble_weights.items():
            hist_len = len(self.prediction_history.get(tf, []))
            print(f"  {tf}: weights={[round(w,3) for w in weights]} "
                  f"history={hist_len} entries")

    # -------------------------------------------------------------------------
    # v9.4 — Adaptive trading state persistence (live-trade-feedback loop)
    # -------------------------------------------------------------------------
    def _load_adaptive_state(self) -> "AdaptiveTradingState":
        """Load the persisted Bayesian winrate posterior, or return a fresh one.

        Failure modes (missing file, corrupt JSON, schema mismatch) all
        fall through to a fresh AdaptiveTradingState. This is intentional —
        a corrupted adaptive file should NOT crash the predictor; the
        cost is at most a few cycles of re-learning, not a missed cycle.
        """
        if not os.path.exists(self.adaptive_state_path):
            return AdaptiveTradingState()
        try:
            with open(self.adaptive_state_path, "r") as f:
                d = json.load(f)
            s = AdaptiveTradingState.from_dict(d)
            print(f"[ADAPTIVE] Loaded posterior: "
                  f"α={s.alpha:.2f} β={s.beta:.2f} "
                  f"P(win)={s.posterior_winrate():.3f} "
                  f"floor={s.confidence_floor:.3f}% "
                  f"({s.n_trades_seen} trades seen)")
            return s
        except (OSError, json.JSONDecodeError) as e:
            print(f"[ADAPTIVE] Could not read {self.adaptive_state_path}: {e}. "
                  "Starting fresh.")
            return AdaptiveTradingState()

    def _save_adaptive_state(self) -> None:
        """Atomic write — see save_to_file."""
        self.save_to_file(self.adaptive_state_path, self.adaptive.to_dict())

    def _ingest_ea_outcomes_into_adaptive(self) -> None:
        """Drain EA trade outcomes and feed them into self.adaptive.

        v9.4: this is the actual feedback loop. Previous versions read
        the outcomes file and threw the data away; this version updates
        the Bayesian posterior, which in turn drives confidence_floor
        in the flat EA signal file the EA will read on its next tick.

        The drain is exclusive (atomic rename) — see _read_ea_trade_outcomes
        — so we cannot double-count an outcome across cycles.
        """
        outcomes = self._read_ea_trade_outcomes()
        if not outcomes:
            return
        n = self.adaptive.ingest(outcomes)
        if n > 0:
            print(f"[ADAPTIVE] Ingested {n} EA outcome(s) — "
                  f"posterior now α={self.adaptive.alpha:.2f} "
                  f"β={self.adaptive.beta:.2f} "
                  f"P(win)={self.adaptive.posterior_winrate():.3f} "
                  f"floor={self.adaptive.confidence_floor:.3f}%")
        self._save_adaptive_state()

    # -------------------------------------------------------------------------
    # v9.4 — Flat EA-facing signal file
    # -------------------------------------------------------------------------
    def _write_ea_signal(
        self,
        current_price: float,
        regime: str,
        trade_allowed: bool,
        veto_reasons: List[str],
        timeframe_predictions: Dict[str, Dict[str, float]],
    ) -> None:
        """Write the FLAT signal file the EA reads.

        v9.4 — this file replaces predictions_multitf.json as the EA's
        input. The verbose multi-TF file remains for diagnostics, but
        the EA must NEVER parse it: nested objects, future schema
        additions, or the smallest formatting change can break the
        MQL5 string-search parser. The flat file has only top-level
        keys, no nesting, no arrays of objects — just numbers and a
        single string regime/reason field. Adding a new key here is
        always safe (older EAs ignore unknown keys); removing or
        renaming a key is a breaking change requiring an EA update.

        Schema (top level only — no nesting):
            schema_version       int   — gate so EA refuses unknown future shapes
            symbol               str
            last_updated_utc     int   — true UTC epoch (see TZ-bug fix)
            current_price        float
            regime               str   — trending|ranging|volatile|unknown
            trade_allowed        bool
            confidence_floor     float — minimum |change_pct| EA should require
            veto_reason          str   — single short reason if !trade_allowed, else ""

            pred_1H              float — predicted PRICE for 1H horizon
            change_1H_pct        float — % change vs current_price (signed)
            ensemble_std_1H      float
            pred_4H              float
            change_4H_pct        float
            ensemble_std_4H      float
            pred_1D              float
            change_1D_pct        float
            ensemble_std_1D      float

        EA decision rule (recommended — actual EA logic stays in MQL5):
            allow trade if:  trade_allowed
                         and abs(change_<chosen_tf>_pct) >= confidence_floor
        """
        veto_reason = ""
        if not trade_allowed:
            # Single short reason — first one is most informative.
            # (Multiple vetoes can fire at once; the EA only needs to
            # know the trade is blocked, not the full taxonomy.)
            veto_reason = (veto_reasons[0] if veto_reasons else "blocked")[:64]

        signal: Dict[str, Any] = {
            "schema_version":   1,
            "symbol":           self.symbol,
            "last_updated_utc": int(time.time()),
            "current_price":    round(current_price, 5),
            "regime":           regime,
            "trade_allowed":    bool(trade_allowed),
            "confidence_floor": round(float(self.adaptive.confidence_floor), 4),
            "veto_reason":      veto_reason,
        }
        for tf in ("1H", "4H", "1D"):
            if tf in timeframe_predictions:
                d = timeframe_predictions[tf]
                pred         = float(d.get("prediction",   current_price))
                change_pct   = ((pred - current_price) / current_price) * 100.0 if current_price > 0 else 0.0
                ensemble_std = float(d.get("ensemble_std", 0.0))
            else:
                pred, change_pct, ensemble_std = current_price, 0.0, 0.0
            signal[f"pred_{tf}"]         = round(pred, 5)
            signal[f"change_{tf}_pct"]   = round(change_pct, 4)
            signal[f"ensemble_std_{tf}"] = round(ensemble_std, 5)

        self.save_to_file(self.ea_signal_path, signal)

    # -------------------------------------------------------------------------
    # v9.4 — Metrics persistence + reporting CLI
    # -------------------------------------------------------------------------
    def _save_metrics(self) -> None:
        """Atomic write of the rolling metrics rollup."""
        self.metrics.record_cycle()
        self.save_to_file(self.metrics_path, self.metrics.snapshot())

    def print_report(self) -> None:
        """Pretty-print the metrics rollup. Public so the CLI 'report'
        subcommand and ad-hoc debug calls can both invoke it."""
        if not os.path.exists(self.metrics_path):
            print(f"No metrics file yet: {self.metrics_path}")
            print("Run at least one prediction cycle first.")
            return
        try:
            with open(self.metrics_path, "r") as f:
                m = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Could not read metrics file: {e}")
            return

        ts = m.get("saved_at_utc", 0)
        when = datetime.utcfromtimestamp(ts).isoformat() if ts else "(unknown)"
        print()
        print("=" * 70)
        print(f"  GGTH Predictor metrics — {self.symbol}   (snapshot {when} UTC)")
        print("=" * 70)
        print(f"  Cycles run:        {m.get('cycles', 0)}")
        print()
        print("  Per-timeframe:")
        print(f"    {'TF':<4} {'samples':>8} {'MAE':>10} {'dir-acc':>9} "
              f"{'avg pred%':>10} {'avg real%':>10}")
        print(f"    {'-'*4} {'-'*8} {'-'*10} {'-'*9} {'-'*10} {'-'*10}")
        for tf in ("1H", "4H", "1D"):
            d = m.get("per_timeframe", {}).get(tf, {})
            n   = d.get("samples", 0)
            mae = d.get("mae")
            dac = d.get("directional_accuracy")
            ap  = d.get("avg_predicted_pct")
            ar  = d.get("avg_realised_pct")
            print(f"    {tf:<4} {n:>8} "
                  f"{(f'{mae:.6f}' if mae is not None else '—'):>10} "
                  f"{(f'{dac*100:.1f}%' if dac is not None else '—'):>9} "
                  f"{(f'{ap:+.3f}'  if ap  is not None else '—'):>10} "
                  f"{(f'{ar:+.3f}'  if ar  is not None else '—'):>10}")
        print()
        print("  Veto counters:")
        for k, v in (m.get("veto_counters") or {}).items():
            print(f"    {k:<22} {v}")
        print()
        print("  Model failures (consecutive raise events):")
        fails = m.get("model_failures") or {}
        if not fails:
            print("    (none)")
        else:
            for k, v in sorted(fails.items()):
                print(f"    {k:<22} {v}")
        print()

        # Adaptive posterior summary
        if os.path.exists(self.adaptive_state_path):
            try:
                with open(self.adaptive_state_path, "r") as f:
                    a = json.load(f)
                print("  Live-trade adaptive posterior:")
                print(f"    α={a.get('alpha', 0):.2f}   β={a.get('beta', 0):.2f}   "
                      f"P(win)={a.get('posterior_winrate', 0):.3f}")
                print(f"    n_trades_seen={a.get('n_trades_seen', 0)}   "
                      f"confidence_floor={a.get('confidence_floor', 0):.3f}%")
            except (OSError, json.JSONDecodeError):
                pass
        print("=" * 70)
        print()

    def run_continuous(self, interval_minutes: int = 60) -> None:
        """
        Run predictions continuously at specified intervals.

        Sleep duration is reduced by the cycle's elapsed time so cycles don't
        drift later and later. Errors back off exponentially (5, 10, 20, 40
        minutes, capped at the configured interval) so a flapping MT5
        connection doesn't get hammered.

        Args:
            interval_minutes: Minutes between prediction cycles
        """
        prediction_method = self.run_prediction_cycle_multitimeframe if self.use_multitimeframe else self.run_prediction_cycle

        print(f"\nStarting Continuous Mode for {self.symbol} (Interval: {interval_minutes} mins)")
        print(f"Using {'multi-timeframe' if self.use_multitimeframe else 'single-timeframe'} prediction method")

        backoff_minutes = 5
        max_backoff_minutes = max(interval_minutes, 60)

        while True:
            cycle_start = time.monotonic()
            try:
                prediction_method()
                # Reset backoff on success
                backoff_minutes = 5
                elapsed = time.monotonic() - cycle_start
                sleep_seconds = max(0.0, interval_minutes * 60 - elapsed)
                print(f"\nCycle took {elapsed:.1f}s. "
                      f"Waiting {sleep_seconds/60:.1f} min until next cycle...")
                time.sleep(sleep_seconds)
            except KeyboardInterrupt:
                print("\nService stopped by user.")
                break
            except Exception as e:
                print(f"\nAn error occurred: {e}")
                import traceback
                traceback.print_exc()
                print(f"Retrying in {backoff_minutes} minutes (exponential backoff)...")
                time.sleep(backoff_minutes * 60)
                backoff_minutes = min(backoff_minutes * 2, max_backoff_minutes)


def main():
    """Main entry point for the predictor."""
    print("""
    ================================================================
       Hybrid Ensemble MT5 Predictor v9.5 (With Macro Integration)
       Feat: Transformer, TCN, GRU, LightGBM & Multi-Timeframe Support
       TensorFlow Optimized - 2-3x Faster Predictions
    ================================================================
    """)

    # ------------------------------------------------------------------
    # Shared date-range arguments added to every relevant sub-command via
    # a dedicated parent parser.  All dates are YYYY-MM-DD strings.
    # ------------------------------------------------------------------
    parser = argparse.ArgumentParser(description="Hybrid Ensemble MT5 Predictor v9.5")
    subparsers = parser.add_subparsers(dest='mode', required=True, help="Operating mode")

    # Parent: symbol (all modes)
    parent_sym = argparse.ArgumentParser(add_help=False)
    parent_sym.add_argument('--symbol', type=str, default="EURUSD", help="Currency symbol (default: EURUSD).")

    # Parent: training date window (train modes)
    parent_train_dates = argparse.ArgumentParser(add_help=False)
    parent_train_dates.add_argument(
        '--train-start', type=str, default=None, metavar='YYYY-MM-DD',
        help="Earliest date of training data (inclusive).  "
             "E.g. --train-start 2020-01-01"
    )
    parent_train_dates.add_argument(
        '--train-end', type=str, default=None, metavar='YYYY-MM-DD',
        help="Latest date of training data (inclusive).  "
             "Set this to your chosen cutoff so the model never sees future data.  "
             "E.g. --train-end 2023-12-31"
    )

    # Parent: prediction / backtest date window (backtest + predict modes)
    parent_pred_dates = argparse.ArgumentParser(add_help=False)
    parent_pred_dates.add_argument(
        '--predict-start', type=str, default=None, metavar='YYYY-MM-DD',
        help="Start of the date range to generate prediction CSV rows for.  "
             "Should be >= --train-end to avoid look-ahead bias.  "
             "E.g. --predict-start 2024-01-01"
    )
    parent_pred_dates.add_argument(
        '--predict-end', type=str, default=None, metavar='YYYY-MM-DD',
        help="End of the date range to generate prediction CSV rows for.  "
             "E.g. --predict-end 2024-12-31"
    )

    # ------------------------------------------------------------------
    # Sub-commands
    # ------------------------------------------------------------------

    # train  (single-timeframe, legacy)
    p_train = subparsers.add_parser(
        'train', parents=[parent_sym, parent_train_dates],
        help="Train the model ensemble (single timeframe, legacy)."
    )
    p_train.add_argument('--force', action='store_true', help="Force retraining even if saved models exist.")
    p_train.add_argument(
        '--models', nargs='+',
        default=['lstm', 'transformer', 'lgbm'],
        choices=['lstm', 'gru', 'transformer', 'tcn', 'lgbm'],
        help="Model types to include in the ensemble."
    )

    # train-multitf  (recommended)
    p_train_mtf = subparsers.add_parser(
        'train-multitf', parents=[parent_sym, parent_train_dates],
        help="Train separate ensembles for 1H/4H/1D (RECOMMENDED)."
    )
    p_train_mtf.add_argument('--force', action='store_true', help="Force retraining even if saved models exist.")
    p_train_mtf.add_argument(
        '--models', nargs='+',
        default=['lstm', 'transformer', 'lgbm'],
        choices=['lstm', 'gru', 'transformer', 'tcn', 'lgbm'],
        help="Model types to include in each timeframe ensemble."
    )

    # tune
    subparsers.add_parser('tune', parents=[parent_sym], help="Run hyperparameter tuning for DL models.")

    # predict  (single-timeframe, live)
    p_predict = subparsers.add_parser(
        'predict', parents=[parent_sym],
        help="Run a live prediction cycle (single timeframe)."
    )
    p_predict.add_argument('--continuous', action='store_true', help="Loop continuously.")
    p_predict.add_argument('--interval', type=int, default=60, help="Minutes between cycles in continuous mode.")
    p_predict.add_argument('--models', nargs='+', choices=['lstm', 'gru', 'transformer', 'tcn', 'lgbm'],
                           help="Override automatic model detection.")
    p_predict.add_argument('--no-kalman', action='store_true', help="Disable Kalman filtering (use EMA).")

    # predict-multitf  (recommended live mode)
    p_predict_mtf = subparsers.add_parser(
        'predict-multitf', parents=[parent_sym],
        help="Run a live prediction cycle using timeframe-specific models (RECOMMENDED)."
    )
    p_predict_mtf.add_argument('--continuous', action='store_true', help="Loop continuously.")
    p_predict_mtf.add_argument('--interval', type=int, default=60, help="Minutes between cycles in continuous mode.")
    p_predict_mtf.add_argument('--models', nargs='+', choices=['lstm', 'gru', 'transformer', 'tcn', 'lgbm'],
                               help="Override automatic model detection.")
    p_predict_mtf.add_argument('--no-kalman', action='store_true', help="Disable Kalman filtering (use EMA).")

    # backtest  (generate lookup CSVs for MT5 Strategy Tester)
    subparsers.add_parser(
        'backtest', parents=[parent_sym, parent_pred_dates],
        help="Generate prediction lookup CSVs for MT5 Strategy Tester.  "
             "Use --predict-start / --predict-end to restrict the date range."
    )

    # safe-backtest  (walk-forward, no look-ahead)
    subparsers.add_parser(
        'safe-backtest', parents=[parent_sym, parent_pred_dates],
        help="Walk-forward backtest that prevents look-ahead bias.  "
             "Use --predict-start / --predict-end to restrict the date range."
    )

    # v9.4 — report  (print rolling metrics rollup)
    subparsers.add_parser(
        'report', parents=[parent_sym],
        help="Print the rolling metrics rollup (per-TF MAE, directional accuracy, "
             "veto counters, model failure counts, adaptive posterior). Reads "
             "the metrics file written by previous prediction cycles — does "
             "NOT run a new cycle."
    )

    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Build predictor keyword arguments from parsed args
    # ------------------------------------------------------------------
    predictor_args: Dict[str, Any] = {'symbol': args.symbol.upper()}

    # Training date window
    if hasattr(args, 'train_start') and args.train_start:
        predictor_args['train_start'] = args.train_start
    if hasattr(args, 'train_end') and args.train_end:
        predictor_args['train_end'] = args.train_end

    # Prediction / backtest date window
    if hasattr(args, 'predict_start') and args.predict_start:
        predictor_args['predict_start'] = args.predict_start
    if hasattr(args, 'predict_end') and args.predict_end:
        predictor_args['predict_end'] = args.predict_end

    # Mode-specific args
    if args.mode in ['train', 'train-multitf']:
        predictor_args['ensemble_model_types'] = args.models
        predictor_args['use_multitimeframe'] = (args.mode == 'train-multitf')
    elif args.mode in ['predict', 'predict-multitf']:
        if hasattr(args, 'models') and args.models:
            predictor_args['ensemble_model_types'] = args.models
        predictor_args['use_kalman'] = not (hasattr(args, 'no_kalman') and args.no_kalman)
        predictor_args['use_multitimeframe'] = (args.mode == 'predict-multitf')

    # Print resolved date windows so user can confirm before training starts
    if any(k in predictor_args for k in ('train_start', 'train_end', 'predict_start', 'predict_end')):
        print("Date windows resolved:")
        if 'train_start' in predictor_args or 'train_end' in predictor_args:
            print(f"  Train  : {predictor_args.get('train_start', 'beginning')} "
                  f"-> {predictor_args.get('train_end', 'latest available')}")
        if 'predict_start' in predictor_args or 'predict_end' in predictor_args:
            print(f"  Predict: {predictor_args.get('predict_start', 'beginning')} "
                  f"-> {predictor_args.get('predict_end', 'latest available')}")
        print()

    # Initialize predictor
    predictor = UnifiedLSTMPredictor(**predictor_args)

    # Execute requested mode
    try:
        if args.mode == 'tune':
            predictor.tune_hyperparameters()
        elif args.mode == 'train':
            predictor.train_model(force_retrain=args.force)
        elif args.mode == 'train-multitf':
            predictor.train_model_multitimeframe(force_retrain=args.force)
        elif args.mode == 'predict':
            if args.continuous:
                predictor.run_continuous(interval_minutes=args.interval)
            else:
                predictor.run_prediction_cycle()
        elif args.mode == 'predict-multitf':
            if args.continuous:
                predictor.run_continuous(interval_minutes=args.interval)
            else:
                predictor.run_prediction_cycle_multitimeframe()
        elif args.mode == 'backtest':
            predictor.run_backtest_generation()
        elif args.mode == 'safe-backtest':
            predictor.run_safe_backtest()
        elif args.mode == 'report':
            # v9.4 — read-only metrics dump, doesn't run a cycle
            predictor.print_report()
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        mt5.shutdown()
        print("\nShutdown complete. Thank you!")


if __name__ == "__main__":
    main()
