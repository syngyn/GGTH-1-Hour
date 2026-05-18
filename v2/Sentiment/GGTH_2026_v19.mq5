//+------------------------------------------------------------------+
//|                              GGTH-Predictor-2026-FIFO.mq5        |
//|                                    Copyright 2026, Jason Rusk    |
//|                                     jason.w.rusk@gmail.com       |
//+------------------------------------------------------------------+
#property copyright   "Copyright 2026, Jason Rusk"
#property link        "jason.w.rusk@gmail.com"
#property version     "1.18"
#property description "GGTH ML Predictor EA — FIFO Compliant Edition"
#property description "v1.14: Adaptive learning aggregates campaigns (not legs) for unbiased Kelly"
#property description "v1.15: Brace-bounded JSON parse, atomic outcomes file, per-ticket close reasons, Y2038-safe watchdog"
#property description "v1.16: Flat EA-signal; adaptive confidence-floor gate"
#property description "v1.17: Shared SL; trailing activation; stops_level check"
#property description "v1.18: Sentiment veto (tester bypass); on-chart panel"
#property strict

#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| Version string — single source of truth for trade comments,      |
//| log lines, and any other place we want to identify which build   |
//| produced an artifact. Update here only.                          |
//+------------------------------------------------------------------+
#define EA_VERSION_STR "1.18"

//+------------------------------------------------------------------+
//| Enumerations                                                      |
//+------------------------------------------------------------------+
enum ENUM_LOT_MODE
  {
   LOT_MODE_FIXED = 0,    // Fixed Lot Size
   LOT_MODE_RISK  = 1     // Risk Percent
  };

//+------------------------------------------------------------------+
//| Input Parameters                                                  |
//+------------------------------------------------------------------+
//--- Testing Mode
input group "=== Testing Mode ==="
input bool            InpStrategyTesterMode        = false;        // Strategy Tester Mode (use CSV lookups)

//--- Trading Setup
input group "=== Trading Setup ==="
input string          InpSymbol                    = "EURUSD";     // Trading Symbol
input ENUM_TIMEFRAMES InpTradingTimeframe           = PERIOD_H1;   // Prediction timeframe for trading
input bool            InpEnableTrading              = true;        // Enable live trading
input ENUM_LOT_MODE   InpLotMode                   = LOT_MODE_FIXED; // Lot Sizing Mode
input double          InpFixedLot                  = 0.1;         // Base Lot Size
input double          InpRiskPercent               = 1.0;         // Risk % (if using Risk mode)
input int             InpMagic                     = 20260522;    // Magic Number
input bool            InpFIFOCompliant              = true;        // FIFO Compliant Mode (NFA/US brokers)

//--- Institutional Filters
input group "=== Institutional Filters ==="
input double          InpMaxMarginUsagePct         = 60.0;        // MAX Margin Utilization %

//
// v1.17 cleanup: removed InpStartHour / InpEndHour from the institutional
// filters group. They duplicated the InpSession1/2/3 cluster below
// (which is the cluster actually consulted by IsTradingAllowed) and the
// duplication was confusing operators — most recently when v15.ex5 ran in
// the Strategy Tester with InpStartHour=0 / InpEndHour=24 alongside an
// InpSession1 0:02–16:00, leaving it ambiguous which one was authoritative.
// Use the multi-session cluster below for trading hours.

//--- Strategy & Signal
input group "=== Strategy & Signal ==="
input double          InpMinPredictionPips         = 17.0;        // Min Signal Confidence (pips)
//
// v1.17 cleanup: removed InpAveragingStep / InpMaxPositions / InpLotMultiplier.
// All three were declared but never consulted by any code path — averaging
// down is fully driven by the per-level configuration in the cluster below
// (InpAvgLevel1/2/3 Lots+Pips). Keeping unused inputs in the panel just
// invited the operator to tune values that did nothing.

//--- Averaging Down
input group "=== Averaging Down ==="
input bool            InpUseAveragingDown          = true;        // Enable Averaging Down
input double          InpAvgLevel1Lots             = 0.2;        // Level 1: Lot Size
input int             InpAvgLevel1Pips             = 15;          // Level 1: Pips Against Position
input double          InpAvgLevel2Lots             = 0.2;        // Level 2: Lot Size
input int             InpAvgLevel2Pips             = 35;          // Level 2: Pips Against Position
input double          InpAvgLevel3Lots             = 0.3;         // Level 3: Lot Size
input int             InpAvgLevel3Pips             = 10000;       // Level 3: Pips Against (10000=disabled)

//--- Profit Protection
input group "=== Profit Protection ==="
input bool            InpUseProfitProtection       = true;        // Enable Profit Protection
input int             InpMinPositionsForProtection = 2;           // Min Positions to Trigger
input double          InpProfitTargetAmount        = 27.0;         // Profit Target ($) to Close All

//--- Max Hold Time
input group "=== Max Hold Time ==="
input bool            InpUseMaxHoldTime            = true;        // Enable Max Hold Time
input int             InpMaxHoldHours              = 10;          // Auto-Close Hold Time (hours)
//--- Market Context Veto (local EA-side volatility guard)
input group "=== Market Context Veto ==="
input bool            InpUseMarketContextVeto      = false;       // Use Local Volatility Veto
input double          InpVolatilitySpikeMultiplier = 2.5;         // ATR Spike Threshold (2.5x=extreme)
input double          InpMaxCandleChangePercent    = 0.5;         // Max Single Candle % Move
input int             InpVolatilityLookback        = 20;          // Volatility Average Period

input group "=== Take Profit & Stop Loss ==="
input bool    InpUsePredictedPrice=true;                    // Use predicted price as TP
input int     InpStopLossPips=60;                          // Stop loss in pips
input int     InpTakeProfitPips=200;                        // Take profit in pips (if not using predicted)
input double  InpTPMultiplier=1.0;                          // TP multiplier (adjust predicted TP)
input int     InpMinTPPips=17;                               // Minimum TP distance in pips
input int     InpMaxTPPips=70;                             // Maximum TP distance in pips

//--- Trend Filter
input group "=== Trend Filter ==="
input bool    InpUseTrendFilter=true;                       // Use trend filter
input int     InpTrendMAPeriod=83;                         // Trend MA period
input ENUM_MA_METHOD InpTrendMAMethod=MODE_EMA;             // Trend MA method
input ENUM_APPLIED_PRICE InpTrendMAPrice=PRICE_CLOSE;       // Trend MA price

//--- RSI Filter
input group "=== RSI Filter ==="
input bool    InpUseRSIFilter=true;                         // Use RSI filter
input int     InpRSIPeriod=14;                              // RSI period
input double  InpRSIOverbought=75.0;                        // RSI overbought level
input double  InpRSIOversold=35.0;                          // RSI oversold level

//--- Trailing Stop
input group "=== Trailing Stop ==="
input bool    InpUseTrailingStop=false;                     // Enable trailing stop
input int     InpTrailingStopPips=12;                       // Trailing stop distance in pips
input int     InpTrailingStepPips=5;                        // Minimum price movement to trail (pips)
input int     InpTrailingActivationPips=25;                 // Min profit before trailing engages (pips). v1.16: prevents premature exit on small profitable wiggles — without this floor, a +13-pip move that retraces 5 pips would close the position at +1 pip even though the original TP was much further away. Set to 0 to engage immediately on any profit (legacy behaviour).

//--- Trading Days
input group "=== Trading Days ==="
input bool    InpTradeMonday=true;                          // Trade on Monday
input bool    InpTradeTuesday=true;                         // Trade on Tuesday
input bool    InpTradeWednesday=true;                       // Trade on Wednesday
input bool    InpTradeThursday=true;                        // Trade on Thursday
input bool    InpTradeFriday=true;                          // Trade on Friday
input bool    InpTradeSaturday=false;                       // Trade on Saturday
input bool    InpTradeSunday=false;                         // Trade on Sunday

//--- Trading Sessions
input group "=== Trading Sessions ==="
input bool    InpUseSession1=true;                          // Enable Session 1
input int     InpSession1StartHour=0;                       // Session 1 Start Hour (0-23)
input int     InpSession1StartMinute=0;                     // Session 1 Start Minute (0-59)
input int     InpSession1EndHour=17;                        // Session 1 End Hour (0-23)
input int     InpSession1EndMinute=0;                       // Session 1 End Minute (0-59)

input bool    InpUseSession2=false;                         // Enable Session 2
input int     InpSession2StartHour=8;                       // Session 2 Start Hour (0-23)
input int     InpSession2StartMinute=0;                     // Session 2 Start Minute (0-59)
input int     InpSession2EndHour=16;                        // Session 2 End Hour (0-23)
input int     InpSession2EndMinute=0;                       // Session 2 End Minute (0-59)

input bool    InpUseSession3=false;                         // Enable Session 3
input int     InpSession3StartHour=16;                      // Session 3 Start Hour (0-23)
input int     InpSession3StartMinute=0;                     // Session 3 Start Minute (0-59)
input int     InpSession3EndHour=23;                        // Session 3 End Hour (0-23)
input int     InpSession3EndMinute=59;                      // Session 3 End Minute (0-59)

//--- Display Settings
input group "=== Display Settings ==="
input int     InpFontSize=14;                               // Font size
input int     InpLineSpacing=12;                            // Extra spacing between lines (px)
input int     InpPanelPadding=10;                           // Inner panel padding (px)
input color   InpTextColor=clrWhite;                        // Text color
input color   InpUpColor=clrLimeGreen;                      // Up prediction color
input color   InpDownColor=clrRed;                          // Down prediction color
input int     InpXOffset=20;                                // X offset from left
input int     InpYOffset=30;                                // Y offset from top
input bool    InpShowDebug=true;                            // Show debug info

//--- Adaptive Learning Settings
input group "=== Adaptive Learning ==="
input bool    InpEnableAdaptiveLearning=true;              // Enable online adaptive learning
input int     InpAdaptLookback=20;                          // Rolling window: trades to evaluate
input int     InpAdaptEveryN=5;                             // Trigger adaptation every N closed trades
input double  InpAdaptRate=0.15;                            // Learning rate (0.05=slow, 0.30=fast)
input double  InpAdaptMinPredFloor=1.0;                     // Minimum allowed adaptive pred pips
input double  InpAdaptMinPredCeil=60.0;                     // Maximum allowed adaptive pred pips
input double  InpAdaptLotMultFloor=0.25;                    // Minimum lot multiplier
input double  InpAdaptLotMultCeil=1.5;                      // Maximum lot multiplier (capped at 1.5x)
input bool    InpAdaptResetOnInit=false;                    // Reset all learned params on init
input bool    InpShowAdaptiveDebug=true;                    // Show adaptive learning output

//--- Stale Prediction Watchdog (v1.13)
input group "=== Stale Prediction Watchdog ==="
input bool    InpEnableStaleWatchdog=true;                  // Block new entries if Python predictor is stale
input int     InpStalePredictionMaxMinutes=90;              // Max age (min) before predictions are stale
input bool    InpFailClosedOnMissingHeartbeat=false;        // Block trading if no heartbeat seen yet (false = allow)
input bool    InpShowWatchdogStatusOnChart=true;            // Display watchdog status banner on chart

//--- Trade Journal (v1.13)
input group "=== Trade Journal ==="
input bool    InpEnableTradeJournal=true;                   // Write per-trade decision context to CSV
input bool    InpJournalAveragingTrades=true;               // Also journal averaging-down legs (recommended)
input bool    InpShowJournalDebug=false;                    // Print journal write events to log

//--- Sentiment Filter (v1.18)
input group "=== Sentiment Filter ==="
input bool   InpUseSentiment          = true;     // Enable sentiment veto (live only — auto-disabled in backtests)
input string InpSentimentFile         = "forex_sentiment.json"; // Sentiment JSON filename (Common Files)
input double InpSentimentMinConf      = 0.20;     // Minimum confidence to act (0=always, 1=never)
input int    InpSentimentMaxAgeSec    = 1800;     // Max age in seconds before sentiment ignored (1800=30min)
input double InpSentimentVetoBand     = 0.10;     // |score| must exceed this to veto opposite signal
input bool   InpShowSentimentPanel    = true;     // Show sentiment panel on chart

//+------------------------------------------------------------------+
//| Market Context Structure (FIXED)                                 |
//+------------------------------------------------------------------+
struct CMarketContext
  {
   bool              veto_active;
   string            reasons[];
   double            volatility_ratio;
   double            max_candle_change;
   datetime          last_check;
  };

//+------------------------------------------------------------------+
//| CSV Prediction Structure                                          |
//+------------------------------------------------------------------+
struct CCSVPrediction
  {
   datetime          timestamp;
   double            prediction;
   double            change_pct;
   double            ensemble_std;
  };

//+------------------------------------------------------------------+
//| Prediction Data Structure                                         |
//+------------------------------------------------------------------+
struct CPredictionData
  {
   double            prediction;
   double            change_pct;
   double            ensemble_std;
   datetime          last_update;
   bool              trade_allowed;
  };

//+------------------------------------------------------------------+
//| Prediction Record Structure                                       |
//+------------------------------------------------------------------+
struct CPredictionRecord
  {
   datetime          timestamp;
   double            predicted_price;
   double            start_price;
   bool              checked;
   bool              accurate;
   datetime          check_time;
   string            timeframe_name;
  };

//+------------------------------------------------------------------+
//| Accuracy Tracker Structure                                        |
//+------------------------------------------------------------------+
struct CAccuracyTracker
  {
   int               total_predictions;
   int               accurate_predictions;
   double            accuracy_percent;
   CPredictionRecord current_prediction;
  };

//+------------------------------------------------------------------+
//| Averaging State Structure                                         |
//+------------------------------------------------------------------+
struct CAveragingState
  {
   double            original_entry_price;
   double            original_take_profit;
   double            original_stop_loss;     // v1.16: shared SL price for the
                                              //   whole campaign (Option C). All
                                              //   averaging legs are opened with
                                              //   this SL, matching the existing
                                              //   shared-TP design.
   long              original_position_type;
   datetime          series_start_time;
   bool              level1_triggered;
   bool              level2_triggered;
   bool              level3_triggered;
  };

//+------------------------------------------------------------------+
//| Single closed trade record for adaptive learning                 |
//+------------------------------------------------------------------+
#define MAX_TRADE_HISTORY 200
#define MAX_OPEN_TRACKING  50

struct CTradeRecord
  {
   ulong             position_id;       // MT5 position ID (DEAL_POSITION_ID)
   datetime          open_time;
   datetime          close_time;
   double            profit;
   double            pred_change_pct;   // signal strength at entry
   double            pred_pips;         // predicted distance at entry
   double            rsi_at_entry;
   bool              was_buy;
   bool              won;               // profit > 0
   bool              used;              // slot occupied
  };

//--- Lightweight record kept while trade is still open
struct COpenTradeEntry
  {
   ulong             position_id;
   double            pred_change_pct;
   double            pred_pips;
   double            rsi_at_entry;
   bool              was_buy;
   bool              used;
  };

//+------------------------------------------------------------------+
//| Per-ticket pending close reason (v1.15)                          |
//+------------------------------------------------------------------+
//  v1.14 used a single shared `m_pending_close_reason` string that
//  CloseAllPositions stamped before issuing the close requests, and
//  OnTradeTransaction read when the matching deals fired. This works
//  for ONE close-all per tick — but if both CheckMaxHoldTime and
//  CheckProfitProtection trigger on the same tick (or close-enough
//  ticks for the deal queue to overlap), the second stamp overwrites
//  the first and the deals from the first close get attributed to
//  the wrong reason in the journal CSV.
//
//  v1.15 replaces this with a per-ticket ring buffer. CloseAllPositions
//  stamps each ticket individually right before issuing PositionClose;
//  OnTradeTransaction looks up the closing deal's position_id and
//  consumes the matching entry. The shared string remains as a
//  fallback for any close path that doesn't go through CloseAllPositions.
#define MAX_PENDING_CLOSES 50

struct CPendingClose
  {
   ulong   position_id;
   string  reason;
   bool    used;
  };

//+------------------------------------------------------------------+
//| Sentiment Snapshot (v1.18)                                       |
//| Parsed from forex_sentiment.json produced by the Python          |
//| sentiment pipeline. The EA caches one snapshot per tick using    |
//| the same mtime-guard pattern as the ea_signal file.              |
//+------------------------------------------------------------------+
struct CSentimentSnapshot
  {
   double   score;           // [-1,+1]  positive = base bullish vs quote
   double   confidence;      // [0,1]
   double   base_score;
   double   quote_score;
   long     age_seconds;     // seconds since the JSON timestamp
   bool     valid;           // false = file missing / stale / parse error
  };

//+------------------------------------------------------------------+
//| Adaptive learning state (persisted to file)                      |
//+------------------------------------------------------------------+
struct CAdaptiveState
  {
   //--- Adapted parameters (these replace the equivalent Inp* values)
   double            min_pred_pips;     // adaptive InpMinPredictionPips
   double            lot_multiplier;    // multiplied onto base lot size
   double            rsi_overbought;    // adaptive RSI OB level
   double            rsi_oversold;      // adaptive RSI OS level

   //--- Rolling performance metrics (computed each adaptation)
   double            win_rate;
   double            profit_factor;
   double            avg_win;
   double            avg_loss;
   double            kelly_fraction;

   //--- Counters
   int               trades_since_last_adapt;
   int               total_adaptations;
   int               consecutive_losses;

   //--- Rolling trade history (circular buffer)
   CTradeRecord      history[MAX_TRADE_HISTORY];
   int               history_head;     // next write index (circular)
   int               history_size;     // how many valid entries (up to MAX)
  };

//+------------------------------------------------------------------+
//| Campaign aggregator (v1.14)                                      |
//+------------------------------------------------------------------+
//  A "campaign" is the lifecycle of a single primary entry plus any
//  averaging-down legs that follow it, ending when CountOpenPositions==0.
//
//  Why this exists: the previous adaptive-learning code wrote a separate
//  history row for EVERY closing deal (primary close, AVG L1 close,
//  AVG L2 close, ...) even though the strategy's true outcome is the
//  net P/L across the whole campaign. A primary that lost 50 pips but
//  was rescued by averaging back to flat was being recorded as one loss
//  + multiple separate wins, distorting win_rate / profit_factor / Kelly.
//
//  This struct accumulates per-campaign P/L and tags the result with the
//  context of the PRIMARY entry only. ProcessClosedTrade defers the
//  history write until the campaign closes, then emits ONE row.
struct CCampaignState
  {
   bool              active;             // true between primary entry and final leg close
   ulong             primary_pos_id;     // pos_id of the original primary leg
   datetime          start_time;         // time of primary entry
   bool              was_buy;            // primary direction
   double            pred_change_pct;    // signal strength at primary entry
   double            pred_pips;          // predicted distance at primary entry
   double            rsi_at_entry;       // RSI at primary entry
   double            accumulated_pl;     // sum of profit+swap+commission across all legs
   int               legs_total;         // primary + averaging legs filled
   int               legs_closed;        // close events received so far
  };

//+------------------------------------------------------------------+
//| GGTH Expert Advisor Class                                        |
//+------------------------------------------------------------------+
class CGGTHExpert
  {
private:
   //--- Trade management
   CTrade            m_trade;
   
   //--- Symbol and file management
   string            m_symbol;
   string            m_predictions_file;
   string            m_status_file;
   
   //--- Indicator handles
   int               m_handle_trend_ma;
   int               m_handle_rsi;
   
   //--- Prediction data
   CPredictionData   m_pred_1H;
   CPredictionData   m_pred_4H;
   CPredictionData   m_pred_1D;
   double            m_current_price;
   
   //--- Accuracy tracking
   CAccuracyTracker  m_tracker_1H;
   CAccuracyTracker  m_tracker_4H;
   CAccuracyTracker  m_tracker_1D;
   
   //--- Market context (FIXED)
   CMarketContext    m_market_context;
   
   //--- Averaging state
   CAveragingState   m_avg_state;
   
   //--- CSV data for backtesting
   CCSVPrediction    m_csv_1H[];
   CCSVPrediction    m_csv_4H[];
   CCSVPrediction    m_csv_1D[];
   int               m_csv_1H_count;
   int               m_csv_4H_count;
   int               m_csv_1D_count;
   
   //--- State variables
   datetime          m_last_pred_bar_time;   // Last bar time on prediction timeframe
   datetime          m_last_chart_bar_time;  // Last bar time on chart timeframe (Period())
   datetime          m_last_trade_time;
   int               m_min_trade_interval;

   //--- Adaptive learning state
   CAdaptiveState    m_adaptive;
   COpenTradeEntry   m_open_tracking[MAX_OPEN_TRACKING]; // pending open trades

   //--- Campaign aggregator state (v1.14)
   //  See struct definition above for the full lifecycle. One m_campaign
   //  spans the entirety of a primary entry + its averaging legs; closes
   //  accumulate P/L into accumulated_pl until CountOpenPositions() reaches 0.
   CCampaignState    m_campaign;

   //--- Python veto bridge
   bool              m_trade_allowed;      // from {SYMBOL}_status.json trade_allowed
   datetime          m_last_json_mod;      // stale-file guard for predictions JSON
   datetime          m_last_status_mod;    // stale-file guard for status JSON
   long              m_last_updated_utc;   // UTC epoch from status (heartbeat watchdog).
                                            // Was int; changed to long in v1.15 so the
                                            // watchdog still functions past 2038-01-19
                                            // when 32-bit signed epochs roll negative.
   string            m_status_regime;      // trending / ranging / volatile / unknown
   datetime          m_last_outcome_flush; // last trade-outcomes JSON flush

   //--- v1.16 — flat EA signal file ({SYMBOL}_ea_signal.json).
   //   The Python predictor (v9.4+) writes a small flat-keys-only JSON
   //   alongside the verbose nested predictions_multitf.json. The EA
   //   reads ONLY the flat file for trading decisions; the nested file
   //   is for diagnostics. If the flat file is present we prefer it;
   //   if not we fall back to the legacy nested-file path so older
   //   predictor builds keep working during the transition.
   datetime          m_last_signal_mod;    // stale-file guard for ea_signal.json
   bool              m_using_flat_signal;  // true when flat signal was successfully loaded this cycle
   double            m_confidence_floor;   // % — minimum |change_pct| to act on (from flat signal)

   //--- Watchdog state (v1.13)
   //  Cached so multiple call sites (CheckForTradeSignal, CheckAveragingDown,
   //  DisplayInfo) share the same evaluation per tick rather than re-querying
   //  TimeGMT() and recomputing the staleness condition independently.
   bool              m_watchdog_stale;     // true when predictions are stale
   int               m_watchdog_age_sec;   // age in seconds (-1 = no heartbeat seen)
   string            m_watchdog_reason;    // human-readable reason text

   //--- Trade Journal state (v1.13)
   //  Stamped before every CGGTHExpert::CloseAllPositions call so the
   //  subsequent OnTradeTransaction(s) firing per-deal can attribute the
   //  exit to the EA-initiated reason. Broker-side closes (TP/SL/SO) are
   //  detected via DEAL_REASON instead and override this string.
   //
   //  v1.15: kept as a fallback path. The authoritative attribution is
   //  now per-ticket via m_pending_closes[] below; this string is used
   //  only when a deal arrives whose position_id is not in the map.
   string            m_pending_close_reason;

   //--- Per-ticket pending close reasons (v1.15) — see CPendingClose
   //    definition above for the full rationale. Sized for MAX_PENDING_CLOSES
   //    concurrent close requests; CloseAllPositions stamps before each
   //    PositionClose, OnTradeTransaction consumes when the deal arrives.
   CPendingClose     m_pending_closes[MAX_PENDING_CLOSES];

   //--- Sentiment cache (v1.18)
   //    Refreshed once per tick via ReadSentimentFile(). The mtime guard
   //    prevents re-parsing on every tick when the 10-min pipeline hasn't
   //    written a new file yet. Always invalid during (bool)MQLInfoInteger(MQL_TESTER) runs.
   CSentimentSnapshot m_sentiment;
   datetime           m_last_sentiment_mod;

public:
   //--- Constructor/Destructor
                     CGGTHExpert();
                    ~CGGTHExpert();
   
   //--- Main interface methods
   int               Init();
   void              Deinit();
   void              OnTick();
   void              OnTradeTransaction(const MqlTradeTransaction &trans,
                                        const MqlTradeRequest &request,
                                        const MqlTradeResult &result);

private:
   //--- Initialization methods
   void              InitializeTrackers();
   bool              InitializeIndicators();
   bool              LoadCSVBacktestData();
   
   //--- Event handlers
   void              OnNewBar();
   void              OnNewChartBar();
   
   //--- Prediction loading
   bool              LoadPredictionsFromJSON();
   bool              LoadStatusFromJSON();           // reads Python veto decision
   bool              LoadPredictionsFromCSV();
   bool              ParsePredictionJSON(string json,string timeframe,CPredictionData &pred);
   bool              LoadCSVLookupFile(ENUM_TIMEFRAMES timeframe);

   //--- v1.16 — flat-signal reader (preferred when available)
   //   Reads {SYMBOL}_ea_signal.json written by predictor v9.4+. The flat
   //   schema is documented in the Python file (_write_ea_signal). On
   //   success, populates the same m_pred_*/m_trade_allowed/m_status_regime/
   //   m_last_updated_utc fields the legacy loaders populate, plus the
   //   new m_confidence_floor. Returns false to let the caller fall back
   //   to the legacy nested-JSON path.
   bool              LoadEASignalFromJSON();
   
   //--- Trading logic
   void              CheckForTradeSignal();
   bool              IsTradingAllowed();
   bool              IsWithinTradingSession(int hour,int minute);
   
   //--- Filters
   bool              CheckTrendFilter(bool &signal_buy,bool &signal_sell);
   bool              CheckRSIFilter(bool &signal_buy,bool &signal_sell);
   
   //--- Market context (FIXED - volatility-based)
   void              UpdateMarketContext();
   
   //--- Position management
   int               CountOpenPositions();
   double            GetTotalProfit();
   bool              GetFirstPositionInfo(double &entry_price,long &pos_type,datetime &open_time,double &take_profit,double &stop_loss);
   bool              CloseAllPositions(string reason);
   double            CalculateLotSize();
   
   //--- Averaging down
   void              CheckAveragingDown();
   bool              ExecuteAveragingOrder(int level,double lots);
   void              ResetAveragingState();
   
   //--- Profit protection and management
   void              CheckProfitProtection();
   void              CheckMaxHoldTime();
   void              ApplyTrailingStop();
   
   //--- Accuracy tracking
   void              UpdateAccuracyTracking();
   void              CheckAccuracyForTimeframe(CAccuracyTracker &tracker,CPredictionData &pred,ENUM_TIMEFRAMES tf);
   void              SaveAccuracyData();
   void              LoadAccuracyData();
   
   //--- Display methods (MAXIMUM SPACING)
   void              DisplayInfo();
   void              DisplayPredictionLine(string tf_name,CPredictionData &pred,CAccuracyTracker &tracker,int x,int &y,int lh);
   void              DisplayError();
   void              CreateLabel(string name,int x,int y,string text,int font_size,color clr);

   //--- Adaptive learning
   void              InitAdaptiveState();
   void              RecordTradeEntry(ulong position_id,bool is_buy,double pred_change_pct,double pred_pips,double rsi);
   void              ProcessClosedTrade(ulong position_id,double profit);
   void              AdaptParameters();
   void              ComputeRollingMetrics(double &win_rate,double &profit_factor,
                                           double &avg_win,double &avg_loss);
   double            ComputeKellyFraction(double win_rate,double avg_win,double avg_loss);
   void              SaveAdaptiveState();
   void              LoadAdaptiveState();
   void              DisplayAdaptiveInfo(int x_pos,int &y_pos,int line_height);

   //--- Campaign aggregator (v1.14)
   //  BeginCampaign stamps entry context on the primary leg only — subsequent
   //  averaging legs flow into the SAME campaign via RegisterAveragingLeg.
   //  ProcessClosedTrade accumulates P/L; when the campaign goes flat,
   //  FinalizeCampaign writes ONE history row and resets the aggregator.
   void              ResetCampaignState();
   void              BeginCampaign(ulong position_id,bool is_buy,
                                   double pred_change_pct,double pred_pips,
                                   double rsi);
   void              RegisterAveragingLeg();
   void              FinalizeCampaign();

   //--- Stale-prediction watchdog (v1.13)
   //  EvaluateWatchdog refreshes m_watchdog_* members from m_last_updated_utc
   //  and TimeGMT(). IsPredictionStale is the single decision point used by
   //  CheckForTradeSignal and CheckAveragingDown. Both honour the input flag
   //  InpEnableStaleWatchdog and InpStrategyTesterMode bypass.
   void              EvaluateWatchdog();
   bool              IsPredictionStale();

   //--- Trade journal (v1.13)
   //  WriteJournalEntry runs at every successful Buy/Sell (including averaging
   //  legs when InpJournalAveragingTrades is on). WriteJournalExit runs from
   //  OnTradeTransaction on every closing deal. Headers are written lazily
   //  (only when the file is first created), so existing journals append.
   void              WriteJournalEntry(ulong position_id,bool is_buy,
                                       double entry_price,double lot_size,
                                       double sl,double tp,
                                       string tf_used,double pred_change_pct,
                                       double pred_pips,double rsi_at_entry,
                                       string entry_kind);
   void              WriteJournalExit(ulong position_id,ulong deal_ticket,
                                      double close_price,double profit,
                                      double swap,double commission,
                                      string exit_reason);
   string            DealReasonToString(long deal_reason);

   //--- Per-ticket pending-close map helpers (v1.15) — replaces the
   //    single-string race window described above CPendingClose.
   void              StampPendingClose(ulong position_id, string reason);
   string            ConsumePendingClose(ulong position_id);
   void              ResetPendingCloses();

   //--- Sentiment (v1.18)
   //    ReadSentimentFile() parses forex_sentiment.json from Common Files
   //    and caches the result in m_sentiment. Always marks invalid when
   //    (bool)MQLInfoInteger(MQL_TESTER) so backtests are never contaminated with live data.
   //    DisplaySentimentPanel() renders the cached snapshot on-chart.
   void              ReadSentimentFile();
   void              DisplaySentimentPanel(int x, int &y, int lh);
  };

//--- Global instance of expert
CGGTHExpert g_expert;

//+------------------------------------------------------------------+
//| Expert initialization function                                    |
//+------------------------------------------------------------------+
int OnInit()
  {
   return(g_expert.Init());
  }

//+------------------------------------------------------------------+
//| Expert deinitialization function                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   g_expert.Deinit();
  }

//+------------------------------------------------------------------+
//| Expert tick function                                              |
//+------------------------------------------------------------------+
void OnTick()
  {
   g_expert.OnTick();
  }

//+------------------------------------------------------------------+
//| Trade transaction handler - routes to adaptive learner           |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   g_expert.OnTradeTransaction(trans,request,result);
  }

//+------------------------------------------------------------------+
//| Constructor                                                       |
//+------------------------------------------------------------------+
CGGTHExpert::CGGTHExpert() : m_symbol(InpSymbol),
                             m_handle_trend_ma(INVALID_HANDLE),
                             m_handle_rsi(INVALID_HANDLE),
                             m_current_price(0),
                             m_csv_1H_count(0),
                             m_csv_4H_count(0),
                             m_csv_1D_count(0),
                             m_last_pred_bar_time(0),
                             m_last_chart_bar_time(0),
                             m_last_trade_time(0),
                             m_min_trade_interval(60),
                             m_trade_allowed(true),
                             m_last_json_mod(0),
                             m_last_status_mod(0),
                             m_last_updated_utc(0),
                             m_last_outcome_flush(0),
                             m_watchdog_stale(false),
                             m_watchdog_age_sec(-1),
                             m_last_signal_mod(0),
                             m_using_flat_signal(false),
                             m_confidence_floor(0.0),
                             m_last_sentiment_mod(0)
  {
   m_status_regime="unknown";
   m_watchdog_reason="";
   m_pending_close_reason="";
   m_sentiment.valid=false;
   m_sentiment.score=0.0;
   m_sentiment.confidence=0.0;
   m_sentiment.base_score=0.0;
   m_sentiment.quote_score=0.0;
   m_sentiment.age_seconds=0;
  }

//+------------------------------------------------------------------+
//| Destructor                                                        |
//+------------------------------------------------------------------+
CGGTHExpert::~CGGTHExpert()
  {
  }

//+------------------------------------------------------------------+
//| Initialization and checking for input parameters                 |
//+------------------------------------------------------------------+
int CGGTHExpert::Init()
  {
//--- Validate trading timeframe BEFORE doing any other init work.
//    The Python predictor only emits 1H / 4H / 1D signals, so any other value
//    would silently fail every tick at the switch in CheckPredictionAndTrade().
//    Failing here with INIT_PARAMETERS_INCORRECT surfaces the misconfig in the
//    tester / terminal immediately and prevents the EA from entering OnTick.
   if(InpTradingTimeframe != PERIOD_H1 &&
      InpTradingTimeframe != PERIOD_H4 &&
      InpTradingTimeframe != PERIOD_D1)
     {
      PrintFormat("[INIT] FATAL: InpTradingTimeframe=%s is unsupported. "
                  "Predictor only emits 1H/4H/1D — set InpTradingTimeframe to "
                  "PERIOD_H1, PERIOD_H4, or PERIOD_D1. (Note: this is the "
                  "PREDICTION timeframe, not the chart timeframe — the EA "
                  "can be attached to any chart, e.g. M5.)",
                  EnumToString(InpTradingTimeframe));
      return(INIT_PARAMETERS_INCORRECT);
     }

//--- v1.16: validate that InpSymbol exists on the broker, and that the
//    configured SL/TP distances clear the broker's minimum stop distance.
//
//    The first check exists because a typo like InpSymbol="GPDUSD" instead
//    of "GBPUSD" produced a cryptic chain — "cannot load indicator (GPDUSD)
//    [4801]" → "Error creating Trend MA indicator" → "Failed to initialize
//    indicators" — none of which pointed at the actual root cause. Now we
//    fail with a clear message naming the bad symbol.
//
//    The second check catches cases where InpStopLossPips is below the
//    broker's SYMBOL_TRADE_STOPS_LEVEL minimum. Without it, every order
//    would be rejected with TRADE_RETCODE_INVALID_STOPS (4756) at runtime
//    and the operator would just see "no trades" with no obvious cause.
   if(!SymbolInfoInteger(m_symbol, SYMBOL_SELECT))
     {
      // Try to add to Market Watch first — some brokers hide symbols by
      // default. SymbolSelect returns false if the name truly doesn't exist.
      if(!SymbolSelect(m_symbol, true))
        {
         PrintFormat("[INIT] FATAL: InpSymbol=\"%s\" not found on this broker. "
                     "Check Market Watch (Ctrl+M) for the exact symbol name "
                     "your broker uses (some brokers append suffixes like "
                     "\".m\" or use prefixes like \"#\"). Common typos: "
                     "GPDUSD→GBPUSD, USDPJY→USDJPY.",
                     m_symbol);
         return(INIT_PARAMETERS_INCORRECT);
        }
     }

   {
      int    stops_level_points = (int)SymbolInfoInteger(m_symbol, SYMBOL_TRADE_STOPS_LEVEL);
      double init_point          = SymbolInfoDouble(m_symbol, SYMBOL_POINT);
      double init_pip            = (_Digits == 3 || _Digits == 5) ? init_point * 10.0 : init_point;
      double sl_distance_price   = InpStopLossPips * init_pip;
      double min_stop_price      = stops_level_points * init_point;

      if(stops_level_points > 0 && sl_distance_price < min_stop_price)
        {
         double min_pips = (init_pip > 0) ? (min_stop_price / init_pip) : 0;
         PrintFormat("[INIT] FATAL: InpStopLossPips=%d (%.5f price units) is "
                     "below this broker's minimum stop distance of %d points "
                     "(%.5f price units = %.1f pips). Increase "
                     "InpStopLossPips to at least %.0f to avoid runtime "
                     "TRADE_RETCODE_INVALID_STOPS (4756) errors.",
                     InpStopLossPips, sl_distance_price,
                     stops_level_points, min_stop_price, min_pips,
                     MathCeil(min_pips) + 1);
         return(INIT_PARAMETERS_INCORRECT);
        }

      // Same check for take-profit when fixed-pip mode is in use. When
      // InpUsePredictedPrice=true the TP is derived from the prediction
      // and clamped by InpMinTPPips/InpMaxTPPips at trade time, so we
      // validate the floor (InpMinTPPips) instead of InpTakeProfitPips.
      double tp_check_pips = InpUsePredictedPrice ? (double)InpMinTPPips : (double)InpTakeProfitPips;
      double tp_distance_price = tp_check_pips * init_pip;
      if(stops_level_points > 0 && tp_distance_price < min_stop_price)
        {
         double min_pips = (init_pip > 0) ? (min_stop_price / init_pip) : 0;
         PrintFormat("[INIT] FATAL: %s=%g pips (%.5f price units) is below "
                     "broker minimum stop distance %.5f. Increase the input "
                     "to at least %.0f pips.",
                     (InpUsePredictedPrice ? "InpMinTPPips" : "InpTakeProfitPips"),
                     tp_check_pips, tp_distance_price, min_stop_price,
                     MathCeil(min_pips) + 1);
         return(INIT_PARAMETERS_INCORRECT);
        }

      if(InpShowDebug)
         PrintFormat("[INIT] Broker stops_level=%d points (%.5f price units / %.1f pips). "
                     "SL=%d pips OK, TP floor=%g pips OK.",
                     stops_level_points, min_stop_price,
                     (init_pip > 0 ? min_stop_price / init_pip : 0),
                     InpStopLossPips, tp_check_pips);
   }

//--- Set up file paths
   m_predictions_file=m_symbol+"_predictions_multitf.json";
   m_status_file=m_symbol+"_status.json";

//--- Initialize tracking structures
   InitializeTrackers();

//--- Load saved accuracy data
   LoadAccuracyData();

//--- Create indicator handles
   if(!InitializeIndicators())
     {
      Print("Error: Failed to initialize indicators");
      return(INIT_FAILED);
     }

//--- Load CSV backtest data if in tester mode
   if(InpStrategyTesterMode)
     {
      if(!LoadCSVBacktestData())
        {
         Print("Error: Failed to load CSV backtest data");
         return(INIT_FAILED);
        }
     }

//--- Initialize averaging state
   ResetAveragingState();

//--- Initialize adaptive learning state
   InitAdaptiveState();
   if(!InpAdaptResetOnInit)
      LoadAdaptiveState();

//--- Initialize market context (FIXED)
   m_market_context.veto_active=false;
   m_market_context.volatility_ratio=0;
   m_market_context.max_candle_change=0;
   m_market_context.last_check=0;
   ArrayResize(m_market_context.reasons,0);

//--- Reset watchdog + journal state (v1.13). The constructor already does
//    this, but on EA hot-reload (param change, recompile) the same instance
//    persists; explicit reset here guarantees a clean slate every Init.
   m_watchdog_stale=false;
   m_watchdog_age_sec=-1;
   m_watchdog_reason="";
   m_pending_close_reason="";

//--- v1.15: clear per-ticket close-reason map. Like the watchdog state
//    above, the constructor already does this — but on hot-reload the
//    same instance persists, so we reset explicitly here.
   ResetPendingCloses();

//--- Set magic number
   m_trade.SetExpertMagicNumber(InpMagic);

   PrintFormat("GGTH Predictor EA v"+EA_VERSION_STR+" initialized | Magic: %d | FIFO: %s | "
               "Watchdog: %s (%dm) | Journal: %s | Adaptive: %s",
               InpMagic, (InpFIFOCompliant?"ON":"OFF"),
               (InpEnableStaleWatchdog?"ON":"OFF"), InpStalePredictionMaxMinutes,
               (InpEnableTradeJournal?"ON":"OFF"),
               (InpEnableAdaptiveLearning?"ON (campaign-aggregated)":"OFF"));
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Deinitialization                                                  |
//+------------------------------------------------------------------+
void CGGTHExpert::Deinit()
  {
//--- Save accuracy data
   SaveAccuracyData();

//--- Save adaptive learning state
   if(InpEnableAdaptiveLearning)
      SaveAdaptiveState();

//--- Release indicator handles
   if(m_handle_trend_ma!=INVALID_HANDLE)
      IndicatorRelease(m_handle_trend_ma);
   if(m_handle_rsi!=INVALID_HANDLE)
      IndicatorRelease(m_handle_rsi);

//--- Remove all chart objects
   ObjectsDeleteAll(0,"MLEA_");
   ObjectsDeleteAll(0,"SENT_");   // v1.18 sentiment panel labels

   Print("GGTH Predictor EA v"+EA_VERSION_STR+" deinitialized");
  }

//+------------------------------------------------------------------+
//| Main tick handler                                                 |
//+------------------------------------------------------------------+
void CGGTHExpert::OnTick()
  {
//--- Update current price
   m_current_price=SymbolInfoDouble(m_symbol,SYMBOL_BID);

//--- Check for new PREDICTION TIMEFRAME bar (update signal / accuracy tracking)
   datetime pred_bar_time=iTime(m_symbol,InpTradingTimeframe,0);
   if(pred_bar_time!=m_last_pred_bar_time)
     {
      m_last_pred_bar_time=pred_bar_time;
      OnNewBar();
     }

//--- Check for new CHART TIMEFRAME bar (fire a trade on every bar while signal is active)
   datetime chart_bar_time=iTime(m_symbol,Period(),0);
   if(chart_bar_time!=m_last_chart_bar_time)
     {
      m_last_chart_bar_time=chart_bar_time;
      OnNewChartBar();
     }

//--- Load predictions
   bool predictions_loaded=false;
   if(InpStrategyTesterMode)
      predictions_loaded=LoadPredictionsFromCSV();
   else
      predictions_loaded=LoadPredictionsFromJSON();

//--- Refresh stale-prediction watchdog state once per tick (v1.13).
//    All call sites (CheckForTradeSignal, CheckAveragingDown, DisplayInfo)
//    read the cached m_watchdog_* members rather than re-evaluating
//    TimeGMT() and the threshold each time.
   EvaluateWatchdog();

//--- Refresh sentiment cache once per tick (v1.18).
//    ReadSentimentFile() is a no-op during (bool)MQLInfoInteger(MQL_TESTER); the mtime guard
//    inside makes it cheap on live ticks when the file hasn't changed.
   if(InpUseSentiment)
      ReadSentimentFile();

//--- Update display
   if(predictions_loaded)
      DisplayInfo();
   else
      DisplayError();

//--- Check profit protection
   if(InpUseProfitProtection)
      CheckProfitProtection();

//--- Check max hold time
   if(InpUseMaxHoldTime)
      CheckMaxHoldTime();

//--- Apply trailing stop if enabled
   if(InpUseTrailingStop)
      ApplyTrailingStop();

//--- Check for averaging down opportunities
   if(InpUseAveragingDown)
      CheckAveragingDown();
  }


//+------------------------------------------------------------------+
//| Prediction timeframe bar handler - update signal & tracking      |
//+------------------------------------------------------------------+
void CGGTHExpert::OnNewBar()
  {
//--- Update market context if veto system enabled (FIXED VERSION)
   if(InpUseMarketContextVeto)
      UpdateMarketContext();

//--- Update accuracy tracking
   UpdateAccuracyTracking();

//--- BELT-AND-SUSPENDERS: enforce max hold time on every new bar too.
//--- This catches edge cases where session boundaries may have delayed
//--- the tick-level timer check (e.g. post-weekend gap opens).
   if(InpUseMaxHoldTime)
      CheckMaxHoldTime();
  }

//+------------------------------------------------------------------+
//| Chart timeframe bar handler - fire trade on every bar            |
//+------------------------------------------------------------------+
void CGGTHExpert::OnNewChartBar()
  {
//--- Place a trade on this chart bar if signal conditions are met
   if(InpEnableTrading)
      CheckForTradeSignal();
  }

//+------------------------------------------------------------------+
//| Initialize tracking structures                                    |
//+------------------------------------------------------------------+
void CGGTHExpert::InitializeTrackers()
  {
//--- Initialize H1 tracker
   m_tracker_1H.total_predictions=0;
   m_tracker_1H.accurate_predictions=0;
   m_tracker_1H.accuracy_percent=0.0;
   m_tracker_1H.current_prediction.checked=false;
   m_tracker_1H.current_prediction.timeframe_name="H1";

//--- Initialize H4 tracker
   m_tracker_4H.total_predictions=0;
   m_tracker_4H.accurate_predictions=0;
   m_tracker_4H.accuracy_percent=0.0;
   m_tracker_4H.current_prediction.checked=false;
   m_tracker_4H.current_prediction.timeframe_name="H4";

//--- Initialize D1 tracker
   m_tracker_1D.total_predictions=0;
   m_tracker_1D.accurate_predictions=0;
   m_tracker_1D.accuracy_percent=0.0;
   m_tracker_1D.current_prediction.checked=false;
   m_tracker_1D.current_prediction.timeframe_name="D1";
  }

//+------------------------------------------------------------------+
//| Initialize indicators                                             |
//+------------------------------------------------------------------+
bool CGGTHExpert::InitializeIndicators()
  {
//--- Create trend MA handle
   if(InpUseTrendFilter)
     {
      m_handle_trend_ma=iMA(m_symbol,InpTradingTimeframe,InpTrendMAPeriod,
                            0,InpTrendMAMethod,InpTrendMAPrice);
      if(m_handle_trend_ma==INVALID_HANDLE)
        {
         Print("Error creating Trend MA indicator");
         return(false);
        }
     }

//--- Create RSI handle
   if(InpUseRSIFilter)
     {
      m_handle_rsi=iRSI(m_symbol,InpTradingTimeframe,InpRSIPeriod,PRICE_CLOSE);
      if(m_handle_rsi==INVALID_HANDLE)
        {
         Print("Error creating RSI indicator");
         return(false);
        }
     }

   return(true);
  }

//+------------------------------------------------------------------+
//| Reset averaging state structure                                   |
//+------------------------------------------------------------------+
void CGGTHExpert::ResetAveragingState()
  {
   m_avg_state.original_entry_price=0;
   m_avg_state.original_take_profit=0;
   m_avg_state.original_stop_loss=0;
   m_avg_state.original_position_type=-1;
   m_avg_state.series_start_time=0;
   m_avg_state.level1_triggered=false;
   m_avg_state.level2_triggered=false;
   m_avg_state.level3_triggered=false;
  }

//+------------------------------------------------------------------+
//| Execute averaging order                                           |
//+------------------------------------------------------------------+
bool CGGTHExpert::ExecuteAveragingOrder(int level,double lots)
  {
//--- FIFO COMPLIANCE: averaging must always match the existing position direction.
//--- This is already guaranteed by using m_avg_state.original_position_type,
//--- but if FIFO mode is on we double-check before sending the order.
   if(InpFIFOCompliant)
     {
      for(int i=PositionsTotal()-1; i>=0; i--)
        {
         ulong chk=PositionGetTicket(i);
         if(chk<=0) continue;
         if(PositionGetString(POSITION_SYMBOL)!=m_symbol) continue;
         if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;
         long existing_type=PositionGetInteger(POSITION_TYPE);
         if(existing_type!=m_avg_state.original_position_type)
           {
            Print("[FIFO] Averaging order blocked - direction mismatch detected");
            return(false);
           }
        }
     }

//--- Calculate lot size
   double lot_size=CalculateLotSize();
   if(lot_size<=0)
      lot_size=lots;

//--- Get current prices
   double ask=SymbolInfoDouble(m_symbol,SYMBOL_ASK);
   double bid=SymbolInfoDouble(m_symbol,SYMBOL_BID);

//--- Use original position's TP for averaging orders.
//--- v1.16: also use the original position's SL price. Previously sl=0
//--- meant averaging legs had NO stop-loss — a primary that hit its
//--- 35-pip SL would close, but the averaging legs would ride
//--- unprotected to broker margin call or InpMaxHoldHours, whichever
//--- came first. Asymmetric risk model.
//---
//--- Option C from the design discussion: every leg in the campaign
//--- shares the SAME absolute SL price. When price reaches that level
//--- the broker closes every leg simultaneously. This matches the
//--- existing shared-TP design (line below) and makes the campaign
//--- behave as one logical position with one entry-price band, one TP,
//--- one SL.
//---
//--- A zero original_stop_loss means the primary was opened without
//--- an SL (shouldn't happen with current code paths but a defensive
//--- pass-through is correct behaviour — the leg gets sl=0 just like
//--- the primary did). Logged so the operator notices.
   double tp=m_avg_state.original_take_profit;
   double sl=m_avg_state.original_stop_loss;

   if(sl<=0 && InpShowDebug)
      Print("[AVG] WARN: averaging leg L",level," opened with no SL — primary "
            "had original_stop_loss<=0. Verify primary's SL was set on entry.");

   string comment=StringFormat("GGTH v"+EA_VERSION_STR+" [AVG L%d] TP:%."+IntegerToString(_Digits)+"f",level,tp);

//--- Execute order based on position type
   if(m_avg_state.original_position_type==POSITION_TYPE_BUY)
     {
      if(m_trade.Buy(lot_size,m_symbol,ask,sl,tp,comment))
        {
         Print("[AVG] Averaging DOWN - BUY Level ",level," at ",ask," TP: ",tp);
         //--- v1.14: register this leg with the campaign aggregator so the
         //    next ProcessClosedTrade run knows to wait for all legs.
         if(InpEnableAdaptiveLearning)
            RegisterAveragingLeg();
         //--- Trade journal (v1.13): tag this leg so analysis can separate
         //    averaging fills from primary entries via the entry_kind column.
         if(InpEnableTradeJournal && InpJournalAveragingTrades)
           {
            ulong avg_pos_id=m_trade.ResultOrder();
            string kind=StringFormat("AVG_L%d",level);
            WriteJournalEntry(avg_pos_id,true,ask,lot_size,sl,tp,
                              "AVG",0.0,0.0,0.0,kind);
           }
         return(true);
        }
     }
   else if(m_avg_state.original_position_type==POSITION_TYPE_SELL)
     {
      if(m_trade.Sell(lot_size,m_symbol,bid,sl,tp,comment))
        {
         Print("[AVG] Averaging DOWN - SELL Level ",level," at ",bid," TP: ",tp);
         //--- v1.14: see comment above
         if(InpEnableAdaptiveLearning)
            RegisterAveragingLeg();
         //--- Trade journal (v1.13): see comment above
         if(InpEnableTradeJournal && InpJournalAveragingTrades)
           {
            ulong avg_pos_id=m_trade.ResultOrder();
            string kind=StringFormat("AVG_L%d",level);
            WriteJournalEntry(avg_pos_id,false,bid,lot_size,sl,tp,
                              "AVG",0.0,0.0,0.0,kind);
           }
         return(true);
        }
     }

   return(false);
  }

//+------------------------------------------------------------------+
//| Calculate lot size based on mode                                  |
//+------------------------------------------------------------------+
double CGGTHExpert::CalculateLotSize()
  {
   double lot_size=0;

   if(InpLotMode==LOT_MODE_FIXED)
     {
      lot_size=InpFixedLot;
     }
   else if(InpLotMode==LOT_MODE_RISK)
     {
      double balance     = AccountInfoDouble(ACCOUNT_BALANCE);
      double risk_amount = balance*(InpRiskPercent/100.0);

      double point  = SymbolInfoDouble(m_symbol,SYMBOL_POINT);
      int    digits = (int)SymbolInfoInteger(m_symbol,SYMBOL_DIGITS);
      double pip    = (digits==3 || digits==5) ? point*10.0 : point;

      double sl_distance = InpStopLossPips*pip;                          // price units
      double tick_value  = SymbolInfoDouble(m_symbol,SYMBOL_TRADE_TICK_VALUE);
      double tick_size   = SymbolInfoDouble(m_symbol,SYMBOL_TRADE_TICK_SIZE);

      if(sl_distance>0 && tick_value>0 && tick_size>0)
        {
         double sl_in_ticks  = sl_distance/tick_size;                    // convert price-dist to ticks
         double loss_per_lot = sl_in_ticks*tick_value;                   // $ lost per 1.0 lot if SL hits
         if(loss_per_lot>0)
            lot_size = risk_amount/loss_per_lot;
        }

      if(InpShowDebug)
         PrintFormat("[RISK-LOT] bal=%.2f risk$=%.2f slPips=%d tickVal=%.5f tickSize=%.5f -> lot=%.4f",
                     balance,risk_amount,InpStopLossPips,tick_value,tick_size,lot_size);
     }

//--- Regime modulation: halve lot in volatile regime to limit drawdown
   if(m_status_regime=="volatile")
     {
      lot_size*=0.5;
      if(InpShowDebug)
         Print("[REGIME] Volatile — lot halved to ",DoubleToString(lot_size,2));
     }

//--- Normalize lot size
   double min_lot=SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_MIN);
   double max_lot=SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_MAX);
   double lot_step=SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_STEP);

   lot_size=MathFloor(lot_size/lot_step)*lot_step;
   lot_size=MathMax(lot_size,min_lot);
   lot_size=MathMin(lot_size,max_lot);

   return(lot_size);
  }

//+------------------------------------------------------------------+
//| Count open positions for symbol                                   |
//+------------------------------------------------------------------+
int CGGTHExpert::CountOpenPositions()
  {
   int count=0;
   for(int i=PositionsTotal()-1; i>=0; i--)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket>0)
        {
         if(PositionGetString(POSITION_SYMBOL)==m_symbol &&
            PositionGetInteger(POSITION_MAGIC)==InpMagic)
           {
            count++;
           }
        }
     }
   return count;
  }

//+------------------------------------------------------------------+
//| Get total profit of all positions for symbol                      |
//+------------------------------------------------------------------+
double CGGTHExpert::GetTotalProfit()
  {
   double total_profit=0;
   for(int i=PositionsTotal()-1; i>=0; i--)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket>0)
        {
         if(PositionGetString(POSITION_SYMBOL)==m_symbol &&
            PositionGetInteger(POSITION_MAGIC)==InpMagic)
           {
            total_profit+=PositionGetDouble(POSITION_PROFIT);
            total_profit+=PositionGetDouble(POSITION_SWAP);
           }
        }
     }
   return total_profit;
  }

//+------------------------------------------------------------------+
//| Get first position info for averaging                             |
//+------------------------------------------------------------------+
bool CGGTHExpert::GetFirstPositionInfo(double &entry_price,long &pos_type,datetime &open_time,double &take_profit,double &stop_loss)
  {
   datetime earliest_time=D'2099.12.31';
   bool found=false;

   for(int i=PositionsTotal()-1; i>=0; i--)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket>0)
        {
         if(PositionGetString(POSITION_SYMBOL)==m_symbol &&
            PositionGetInteger(POSITION_MAGIC)==InpMagic)
           {
            datetime pos_time=(datetime)PositionGetInteger(POSITION_TIME);
            if(pos_time<earliest_time)
              {
               earliest_time=pos_time;
               entry_price=PositionGetDouble(POSITION_PRICE_OPEN);
               pos_type=PositionGetInteger(POSITION_TYPE);
               open_time=pos_time;
               take_profit=PositionGetDouble(POSITION_TP);
               // v1.16: also surface SL so CheckAveragingDown can cache it
               // for subsequent legs (Option C: shared SL across campaign).
               stop_loss=PositionGetDouble(POSITION_SL);
               found=true;
              }
           }
        }
     }
   return found;
  }

//+------------------------------------------------------------------+
//| Close all positions for symbol                                    |
//+------------------------------------------------------------------+
bool CGGTHExpert::CloseAllPositions(string reason)
  {
//--- Trade journal (v1.13): stamp the close reason BEFORE any
//    PositionClose call so that the OnTradeTransaction(s) firing for each
//    closing deal can attribute the exit. Broker-side TP/SL hits never
//    pass through this method, so DealReasonToString() in the journal
//    writer overrides this string when DEAL_REASON is TP/SL/SO.
   m_pending_close_reason=reason;

   bool all_closed=true;
   int closed_count=0;
   double total_profit=GetTotalProfit();

   //--- FIFO COMPLIANCE: collect matching tickets and sort by open time (oldest first)
   //--- This satisfies the NFA FIFO rule which requires positions to be closed
   //--- in the same order they were opened (first-in, first-out).
   ulong    tickets[];
   datetime times[];
   int      match_count=0;

   ArrayResize(tickets,PositionsTotal());
   ArrayResize(times,  PositionsTotal());

   for(int i=0; i<PositionsTotal(); i++)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket>0)
        {
         if(PositionGetString(POSITION_SYMBOL)==m_symbol &&
            PositionGetInteger(POSITION_MAGIC)==InpMagic)
           {
            tickets[match_count]=(ulong)ticket;
            times[match_count]  =(datetime)PositionGetInteger(POSITION_TIME);
            match_count++;
           }
        }
     }

   //--- Insertion-sort by open time ascending (oldest first)
   for(int a=1; a<match_count; a++)
     {
      ulong    t_key =tickets[a];
      datetime dt_key=times[a];
      int b=a-1;
      while(b>=0 && times[b]>dt_key)
        {
         tickets[b+1]=tickets[b];
         times[b+1]  =times[b];
         b--;
        }
      tickets[b+1]=t_key;
      times[b+1]  =dt_key;
     }

   //--- Close in FIFO order (oldest position first).
   //--- v1.15: stamp the close reason against THIS specific ticket immediately
   //    before issuing PositionClose. The matching deal will arrive in
   //    OnTradeTransaction (possibly after additional close-all calls have
   //    overwritten m_pending_close_reason on subsequent ticks); the per-
   //    ticket map ensures attribution survives that race.
   for(int i=0; i<match_count; i++)
     {
      StampPendingClose(tickets[i], reason);
      if(m_trade.PositionClose(tickets[i]))
        {
         closed_count++;
        }
      else
        {
         all_closed=false;
         Print("ERROR: Failed to close position ",tickets[i]," Error: ",GetLastError());
        }
     }

   if(closed_count>0)
     {
      Print("[OK] ",reason," - Closed ",closed_count," positions | Total P/L: $",
            DoubleToString(total_profit,2));
      ResetAveragingState();
     }

   return all_closed;
  }

//+------------------------------------------------------------------+
//| Check profit protection                                           |
//+------------------------------------------------------------------+
void CGGTHExpert::CheckProfitProtection()
  {
   if(!InpUseProfitProtection)
      return;

   int position_count=CountOpenPositions();

//--- Only trigger if we have minimum required positions
   if(position_count<InpMinPositionsForProtection)
      return;

   double total_profit=GetTotalProfit();

//--- Check if profit target reached
   if(total_profit>=InpProfitTargetAmount)
     {
      string reason=StringFormat("PROFIT PROTECTION: $%.2f profit with %d positions",
                                 total_profit,position_count);
      CloseAllPositions(reason);
     }
  }

//+------------------------------------------------------------------+
//| Check max hold time                                               |
//+------------------------------------------------------------------+
void CGGTHExpert::CheckMaxHoldTime()
  {
   if(!InpUseMaxHoldTime)
      return;

   int position_count=CountOpenPositions();
   if(position_count==0)
      return;

   //--- Use TimeCurrent() for wall-clock elapsed time.
   //--- This is UNCONDITIONAL - session boundaries do NOT pause the timer.
   datetime current_time=TimeCurrent();
   long max_seconds=(long)InpMaxHoldHours*3600;
   bool found_expired=false;

//--- Scan ALL our positions; close entire campaign if any single position is expired.
   for(int i=PositionsTotal()-1; i>=0; i--)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket<=0) continue;

      if(PositionGetString(POSITION_SYMBOL)!=m_symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;

      datetime open_time=(datetime)PositionGetInteger(POSITION_TIME);

      //--- Guard against broker/backtest clock anomalies
      if(open_time<=0 || open_time>current_time) continue;

      long hold_seconds=(long)(current_time - open_time);

      if(hold_seconds >= max_seconds)
        {
         found_expired=true;
         Print(StringFormat("[TIMER] Position #%I64u held %d min (max %d h) - closing all",
                            ticket, (int)(hold_seconds/60), InpMaxHoldHours));
         break;
        }
     }

   if(found_expired)
     {
      string reason=StringFormat("MAX HOLD TIME: Position(s) exceeded %d hours",InpMaxHoldHours);
      CloseAllPositions(reason);
     }
  }

//+------------------------------------------------------------------+
//| Check averaging down                                              |
//+------------------------------------------------------------------+
void CGGTHExpert::CheckAveragingDown()
  {
   if(!InpUseAveragingDown)
      return;

//--- Stale-prediction watchdog (v1.13): refuse to add to a campaign on stale data.
//    Averaging-down INTO a stale signal compounds risk at exactly the moment
//    the underlying thesis may have decayed. Existing legs are still managed
//    by CheckMaxHoldTime / CheckProfitProtection / ApplyTrailingStop — only
//    the addition of NEW levels is blocked here.
   if(IsPredictionStale())
     {
      if(InpShowDebug)
         Print("[WATCHDOG] ",m_watchdog_reason," — averaging blocked");
      return;
     }

//--- Check margin utilization using ACCOUNT_MARGIN_FREE
   double avg_free_margin  = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double avg_equity       = AccountInfoDouble(ACCOUNT_EQUITY);
   double avg_margin_usage = (avg_equity>0) ? ((avg_equity-avg_free_margin)/avg_equity*100.0) : 0.0;
   if(avg_margin_usage > InpMaxMarginUsagePct)
     {
      if(InpShowDebug)
         Print("[MARGIN] Averaging blocked: margin usage ",DoubleToString(avg_margin_usage,1),
               "% exceeds limit of ",DoubleToString(InpMaxMarginUsagePct,1),"%");
      return;
     }

   int position_count=CountOpenPositions();

//--- If no positions, reset state
   if(position_count==0)
     {
      if(m_avg_state.original_entry_price>0)
        {
         ResetAveragingState();
         if(InpShowDebug)
            Print("Averaging state reset - no positions");
        }
      return;
     }

//--- Get first position info (including take profit AND stop loss).
//--- v1.16: now returns SL so we can cache it on series init for the
//--- Option-C shared-SL design (every averaging leg uses this same
//--- absolute SL price).
   double entry_price;
   long pos_type;
   datetime open_time;
   double take_profit;
   double stop_loss;

   if(!GetFirstPositionInfo(entry_price,pos_type,open_time,take_profit,stop_loss))
      return;

//--- Initialize state if this is a new position series.
//---
//--- v1.15 fix: if take_profit==0 we MUST NOT cache it. ApplyTrailingStop
//--- zeroes the TP when it engages (line ~1459 — "Remove TP when trailing
//--- engages"). After an EA restart with a trailing-stopped primary still
//--- open, this code would cache TP=0 here, then ExecuteAveragingOrder
//--- would open new averaging legs with no take-profit at all — they'd
//--- sit until SL or max-hold.
//---
//--- If we can't establish a real TP for the series, skip the rest of
//--- this tick. Either ApplyTrailingStop is now managing exits (good —
//--- averaging is unnecessary on a profitable position) or the
//--- position was opened externally and we simply shouldn't average it.
   if(m_avg_state.series_start_time!=open_time)
     {
      if(take_profit<=0)
        {
         if(InpShowDebug)
            Print("[AVG] Skipping series init: position has no TP (likely trailing-stopped). "
                  "Averaging requires a target — exits will be handled by trailing stop or max-hold.");
         return;
        }
      ResetAveragingState();
      m_avg_state.original_entry_price=entry_price;
      m_avg_state.original_take_profit=take_profit;
      // v1.16: cache primary's SL so subsequent averaging legs share it.
      // If the primary genuinely had no SL (older trade or external open),
      // cache the zero — ExecuteAveragingOrder will then warn and fall
      // through to legs with sl=0, preserving prior behaviour for those
      // edge cases without making a worse silent decision here.
      m_avg_state.original_stop_loss=stop_loss;
      m_avg_state.original_position_type=pos_type;
      m_avg_state.series_start_time=open_time;

      if(InpShowDebug)
         Print("New position series started at ",entry_price,
               " with TP at ",take_profit,
               " SL at ",DoubleToString(stop_loss,_Digits),
               (stop_loss<=0 ? " [WARN: primary has no SL — averaging legs will inherit no protection]" : ""));
     }

//--- Calculate pip value
   double point=SymbolInfoDouble(m_symbol,SYMBOL_POINT);
   double pip=point;
   if(_Digits==3 || _Digits==5)
      pip=point*10.0;

   double current_bid=SymbolInfoDouble(m_symbol,SYMBOL_BID);
   double current_ask=SymbolInfoDouble(m_symbol,SYMBOL_ASK);

//--- Calculate how far price has moved against position
   double pips_against=0;

   if(m_avg_state.original_position_type==POSITION_TYPE_BUY)
     {
      pips_against=(m_avg_state.original_entry_price-current_bid)/pip;
     }
   else if(m_avg_state.original_position_type==POSITION_TYPE_SELL)
     {
      pips_against=(current_ask-m_avg_state.original_entry_price)/pip;
     }

//--- Only average down if price moved against us
   if(pips_against<=0)
      return;

//--- Direction gate: refuse to average if Python prediction has flipped direction.
//--- Averaging into a reversed signal compounds a losing bet.
  {
   CPredictionData avg_pred;
   switch(InpTradingTimeframe)
     {
      case PERIOD_H1: avg_pred=m_pred_1H; break;
      case PERIOD_H4: avg_pred=m_pred_4H; break;
      default:        avg_pred=m_pred_1D; break;
     }
   if(avg_pred.prediction>0)
     {
      bool avg_pred_bull=(avg_pred.prediction>m_current_price);
      bool avg_pos_bull =(m_avg_state.original_position_type==POSITION_TYPE_BUY);
      if(avg_pred_bull!=avg_pos_bull)
        {
         if(InpShowDebug)
            Print("[AVG] Direction gate: prediction flipped — averaging blocked");
         return;
        }
     }
  }

//--- Check Level 1
   if(!m_avg_state.level1_triggered && pips_against>=InpAvgLevel1Pips)
     {
      if(ExecuteAveragingOrder(1,InpAvgLevel1Lots))
        {
         m_avg_state.level1_triggered=true;
         Print("[AVG] Level 1 triggered at ",DoubleToString(pips_against,1)," pips against");
        }
     }

//--- Check Level 2
   if(!m_avg_state.level2_triggered && pips_against>=InpAvgLevel2Pips)
     {
      if(ExecuteAveragingOrder(2,InpAvgLevel2Lots))
        {
         m_avg_state.level2_triggered=true;
         Print("[AVG] Level 2 triggered at ",DoubleToString(pips_against,1)," pips against");
        }
     }

//--- Check Level 3
   if(!m_avg_state.level3_triggered && pips_against>=InpAvgLevel3Pips)
     {
      if(ExecuteAveragingOrder(3,InpAvgLevel3Lots))
        {
         m_avg_state.level3_triggered=true;
         Print("[AVG] Level 3 triggered at ",DoubleToString(pips_against,1)," pips against");
        }
     }
  }

//+------------------------------------------------------------------+
//| Apply trailing stop                                               |
//+------------------------------------------------------------------+
//+------------------------------------------------------------------+
//| Apply trailing stop - PROFIT ONLY + REMOVE TP VERSION            |
//+------------------------------------------------------------------+
void CGGTHExpert::ApplyTrailingStop()
  {
   if(!InpUseTrailingStop)
      return;

   double point=SymbolInfoDouble(m_symbol,SYMBOL_POINT);
   double pip=point;
   if(_Digits==3 || _Digits==5)
      pip=point*10.0;

   double trailing_stop_distance=InpTrailingStopPips*pip;
   double trailing_step=InpTrailingStepPips*pip;

   for(int i=PositionsTotal()-1; i>=0; i--)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket>0)
        {
         if(PositionGetString(POSITION_SYMBOL)==m_symbol &&
            PositionGetInteger(POSITION_MAGIC)==InpMagic)
           {
            long pos_type=PositionGetInteger(POSITION_TYPE);
            double pos_open=PositionGetDouble(POSITION_PRICE_OPEN);
            double pos_sl=PositionGetDouble(POSITION_SL);
            double pos_tp=PositionGetDouble(POSITION_TP);

            double bid=SymbolInfoDouble(m_symbol,SYMBOL_BID);
            double ask=SymbolInfoDouble(m_symbol,SYMBOL_ASK);

            if(pos_type==POSITION_TYPE_BUY)
              {
               //--- Calculate current profit in pips
               double profit_pips=(bid-pos_open)/pip;

               //--- v1.16: only engage trailing once profit clears the
               //    activation threshold. Below the threshold we leave the
               //    position alone — its hardcoded SL/TP from entry are
               //    still in force. This prevents premature exit on small
               //    profitable wiggles (e.g. +13 pips followed by a 5-pip
               //    retrace closing at +1).
               if(profit_pips < InpTrailingActivationPips)
                  continue;

               double new_sl=bid-trailing_stop_distance;

               //--- v1.16 bugfix: when pos_sl==0 (no SL currently set —
               //    e.g. a legacy averaging leg from before the v1.16
               //    shared-SL fix), the previous condition
               //        new_sl > pos_sl && (new_sl - pos_sl) >= step
               //    reduced to true on any profitable tick, instantly
               //    placing a tight stop near entry. Now mirrors the
               //    SELL-branch logic: when pos_sl==0, just check that
               //    new_sl > pos_open (protective). When pos_sl>0,
               //    require the ratchet + step.
               bool ok = (new_sl > pos_open) && (
                            pos_sl <= 0
                              ? true
                              : (new_sl > pos_sl && (new_sl - pos_sl) >= trailing_step)
                         );
               if(ok)
                 {
                  //--- Remove TP when trailing engages (set to 0)
                  double new_tp=0;
                  
                  if(m_trade.PositionModify(ticket,new_sl,new_tp))
                    {
                     if(pos_tp>0 && InpShowDebug)
                       {
                        Print("[TRAIL] ENGAGED for BUY #",ticket);
                        Print("  Profit: +",DoubleToString(profit_pips,1)," pips");
                        Print("  New SL: ",new_sl," | TP REMOVED");
                       }
                     else if(InpShowDebug)
                       {
                        Print("[TRAIL] Updated for BUY #",ticket," to ",new_sl);
                       }
                    }
                  else
                    {
                     if(InpShowDebug)
                        Print("ERROR: Failed to modify BUY position #",ticket," Error: ",GetLastError());
                    }
                 }
              }
            else if(pos_type==POSITION_TYPE_SELL)
              {
               //--- Calculate current profit in pips
               double profit_pips=(pos_open-ask)/pip;

               //--- v1.16: same activation threshold as BUY branch.
               //    Only engage trailing once profit clears the floor.
               if(profit_pips < InpTrailingActivationPips)
                  continue;

               double new_sl=ask+trailing_stop_distance;
               
               //--- Check if we should move the stop
               if((pos_sl==0 || new_sl<pos_sl) && new_sl<pos_open && (pos_sl-new_sl)>=trailing_step)
                 {
                  //--- Remove TP when trailing engages (set to 0)
                  double new_tp=0;
                  
                  if(m_trade.PositionModify(ticket,new_sl,new_tp))
                    {
                     if(pos_tp>0 && InpShowDebug)
                       {
                        Print("[TRAIL] ENGAGED for SELL #",ticket);
                        Print("  Profit: +",DoubleToString(profit_pips,1)," pips");
                        Print("  New SL: ",new_sl," | TP REMOVED");
                       }
                     else if(InpShowDebug)
                       {
                        Print("[TRAIL] Updated for SELL #",ticket," to ",new_sl);
                       }
                    }
                  else
                    {
                     if(InpShowDebug)
                        Print("ERROR: Failed to modify SELL position #",ticket," Error: ",GetLastError());
                    }
                 }
              }
           }
        }
     }
  }



//+------------------------------------------------------------------+
//| Update market context - FIXED VOLATILITY-BASED VERSION           |
//+------------------------------------------------------------------+
void CGGTHExpert::UpdateMarketContext()
  {
   if(!InpUseMarketContextVeto)
      return;

//--- Reset veto state
   m_market_context.veto_active=false;
   ArrayResize(m_market_context.reasons,0);
   m_market_context.volatility_ratio=0;
   m_market_context.max_candle_change=0;

//--- CHECK 1: Volatility Spike Detection (Risk-Off Events)
   double atr_current_buffer[];
   double atr_avg_buffer[];
   ArraySetAsSeries(atr_current_buffer,true);
   ArraySetAsSeries(atr_avg_buffer,true);

//--- Get current H1 ATR
   int atr_h1_handle=iATR(m_symbol,PERIOD_H1,14);
   if(atr_h1_handle==INVALID_HANDLE)
     {
      Print("ERROR: Cannot create ATR indicator for volatility check");
      return;
     }

   if(CopyBuffer(atr_h1_handle,0,0,1,atr_current_buffer)<1)
     {
      IndicatorRelease(atr_h1_handle);
      return;
     }

   double atr_current=atr_current_buffer[0];
   IndicatorRelease(atr_h1_handle);

//--- Get average ATR over longer period
   int atr_avg_handle=iATR(m_symbol,PERIOD_H4,InpVolatilityLookback);
   if(atr_avg_handle==INVALID_HANDLE)
     {
      Print("ERROR: Cannot create ATR indicator for average");
      return;
     }

   if(CopyBuffer(atr_avg_handle,0,0,1,atr_avg_buffer)<1)
     {
      IndicatorRelease(atr_avg_handle);
      return;
     }

   double atr_average=atr_avg_buffer[0];
   IndicatorRelease(atr_avg_handle);

//--- Calculate volatility ratio
   if(atr_average>0)
     {
      m_market_context.volatility_ratio=atr_current/atr_average;

      if(m_market_context.volatility_ratio>=InpVolatilitySpikeMultiplier)
        {
         m_market_context.veto_active=true;
         int size=ArraySize(m_market_context.reasons);
         ArrayResize(m_market_context.reasons,size+1);
         m_market_context.reasons[size]=StringFormat("Volatility Spike (%.1fx normal)",
                                                      m_market_context.volatility_ratio);
        }
     }

//--- CHECK 2: Rapid Price Movement Detection
   double close_prices[];
   ArraySetAsSeries(close_prices,true);

   int bars_copied=CopyClose(m_symbol,Period(),0,10,close_prices);

   if(bars_copied>=10)
     {
      double max_change_pct=0;

      for(int i=0; i<9; i++)
        {
         if(close_prices[i+1]>0)
           {
            double change_pct=MathAbs((close_prices[i]-close_prices[i+1])/close_prices[i+1])*100.0;
            if(change_pct>max_change_pct)
               max_change_pct=change_pct;
           }
        }

      m_market_context.max_candle_change=max_change_pct;

      if(max_change_pct>=InpMaxCandleChangePercent)
        {
         m_market_context.veto_active=true;
         int size=ArraySize(m_market_context.reasons);
         ArrayResize(m_market_context.reasons,size+1);
         m_market_context.reasons[size]=StringFormat("Rapid Price Movement (%.2f%% candle)",
                                                      max_change_pct);
        }
     }

//--- CHECK 3: Gap Detection
   if(bars_copied>=2)
     {
      double current_open=iOpen(m_symbol,Period(),0);
      double prev_close=close_prices[1];

      if(prev_close>0)
        {
         double gap_pct=MathAbs((current_open-prev_close)/prev_close)*100.0;

         if(gap_pct>=0.3)
           {
            m_market_context.veto_active=true;
            int size=ArraySize(m_market_context.reasons);
            ArrayResize(m_market_context.reasons,size+1);
            m_market_context.reasons[size]=StringFormat("Price Gap Detected (%.2f%%)",gap_pct);
           }
        }
     }

   m_market_context.last_check=TimeCurrent();

//--- Debug output
   if(InpShowDebug)
     {
      if(m_market_context.veto_active)
        {
         Print("[VETO] MARKET CONTEXT VETO ACTIVE:");
         for(int i=0; i<ArraySize(m_market_context.reasons); i++)
           {
            Print("  - ",m_market_context.reasons[i]);
           }
        }
      else
        {
         Print("[MKT] Market Context: NORMAL");
         Print("  Volatility Ratio: ",DoubleToString(m_market_context.volatility_ratio,2),"x");
         Print("  Max Candle Change: ",DoubleToString(m_market_context.max_candle_change,2),"%");
        }
     }
  }

//+------------------------------------------------------------------+
//| Load CSV backtest data                                            |
//+------------------------------------------------------------------+
bool CGGTHExpert::LoadCSVBacktestData()
  {
   Print("Loading CSV backtest data...");

   bool success=true;

//--- Load 1H data
   if(!LoadCSVLookupFile(PERIOD_H1))
     {
      Print("Warning: Failed to load 1H CSV data");
      success=false;
     }

//--- Load 4H data
   if(!LoadCSVLookupFile(PERIOD_H4))
     {
      Print("Warning: Failed to load 4H CSV data");
      success=false;
     }

//--- Load 1D data
   if(!LoadCSVLookupFile(PERIOD_D1))
     {
      Print("Warning: Failed to load 1D CSV data");
      success=false;
     }

   if(success)
      Print("[INIT] CSV backtest data loaded");

   return success;
  }

bool CGGTHExpert::LoadCSVLookupFile(ENUM_TIMEFRAMES timeframe)
  {
   string tf_str="";
   CCSVPrediction temp_array[];
   int count=0;

   switch(timeframe)
     {
      case PERIOD_H1:
         tf_str="1H";
         break;
      case PERIOD_H4:
         tf_str="4H";
         break;
      case PERIOD_D1:
         tf_str="1D";
         break;
      default:
         return(false);
     }

   string filename=m_symbol+"_"+tf_str+"_lookup.csv";

//--- Try to open from Common folder first
   int file_handle=FileOpen(filename,FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(file_handle==INVALID_HANDLE)
     {
      file_handle=FileOpen(filename,FILE_READ|FILE_TXT|FILE_ANSI);
      if(file_handle==INVALID_HANDLE)
        {
         Print("ERROR: Cannot open ",filename);
         return(false);
        }
     }

//--- Read header line
   string header_line="";
   while(!FileIsEnding(file_handle))
     {
      header_line=FileReadString(file_handle);
      if(header_line!="") break;
     }

   bool has_full_format=
      (StringFind(header_line,"change_pct")>=0 &&
       StringFind(header_line,"ensemble_std")>=0);

//--- Read all records
   ArrayResize(temp_array,10000);
   double last_price=0;

   while(!FileIsEnding(file_handle))
     {
      string line=FileReadString(file_handle);
      if(line=="" || StringLen(line)<5) continue;

      string parts[];
      int num_parts=StringSplit(line,',',parts);

      if(num_parts<2) continue;

//--- Parse timestamp
      string timestamp_str=parts[0];
      StringTrimLeft(timestamp_str);
      StringTrimRight(timestamp_str);
      StringReplace(timestamp_str,".","-");
      datetime dt=StringToTime(timestamp_str);

//--- Parse prediction
      double prediction=StringToDouble(parts[1]);

      double change_pct=0;
      double ensemble_std=0.025;

//--- If full format, read additional columns
      if(has_full_format && num_parts>=4)
        {
         change_pct=StringToDouble(parts[2]);
         ensemble_std=StringToDouble(parts[3]);
        }
      else
        {
         if(last_price>0)
            change_pct=((prediction-last_price)/last_price)*100.0;
         else
            change_pct=0.0;
        }

      if(dt>0 && prediction>0)
        {
         if(count>=ArraySize(temp_array))
            ArrayResize(temp_array,count+1000);

         temp_array[count].timestamp=dt;
         temp_array[count].prediction=prediction;
         temp_array[count].change_pct=change_pct;
         temp_array[count].ensemble_std=ensemble_std;
         count++;

         last_price=prediction;
        }
     }

   FileClose(file_handle);

   if(count==0)
      return(false);

//--- Store in appropriate member array
   switch(timeframe)
     {
      case PERIOD_H1:
         ArrayResize(m_csv_1H,count);
         ArrayCopy(m_csv_1H,temp_array,0,0,count);
         m_csv_1H_count=count;
         break;

      case PERIOD_H4:
         ArrayResize(m_csv_4H,count);
         ArrayCopy(m_csv_4H,temp_array,0,0,count);
         m_csv_4H_count=count;
         break;

      case PERIOD_D1:
         ArrayResize(m_csv_1D,count);
         ArrayCopy(m_csv_1D,temp_array,0,0,count);
         m_csv_1D_count=count;
         break;
     }

   return(true);
  }

//+------------------------------------------------------------------+
//| Load predictions from CSV for backtesting                         |
//+------------------------------------------------------------------+
bool CGGTHExpert::LoadPredictionsFromCSV()
  {
   datetime current_time=iTime(m_symbol,InpTradingTimeframe,0);

//--- Search 1H predictions
   for(int i=0; i<m_csv_1H_count; i++)
     {
      if(m_csv_1H[i].timestamp==current_time)
        {
         m_pred_1H.prediction=m_csv_1H[i].prediction;
         m_pred_1H.change_pct=m_csv_1H[i].change_pct;
         m_pred_1H.ensemble_std=m_csv_1H[i].ensemble_std;
         m_pred_1H.last_update=current_time;
         m_pred_1H.trade_allowed=true;
         break;
        }
     }

//--- Search 4H predictions
   for(int i=0; i<m_csv_4H_count; i++)
     {
      if(m_csv_4H[i].timestamp==current_time)
        {
         m_pred_4H.prediction=m_csv_4H[i].prediction;
         m_pred_4H.change_pct=m_csv_4H[i].change_pct;
         m_pred_4H.ensemble_std=m_csv_4H[i].ensemble_std;
         m_pred_4H.last_update=current_time;
         m_pred_4H.trade_allowed=true;
         break;
        }
     }

//--- Search 1D predictions
   for(int i=0; i<m_csv_1D_count; i++)
     {
      if(m_csv_1D[i].timestamp==current_time)
        {
         m_pred_1D.prediction=m_csv_1D[i].prediction;
         m_pred_1D.change_pct=m_csv_1D[i].change_pct;
         m_pred_1D.ensemble_std=m_csv_1D[i].ensemble_std;
         m_pred_1D.last_update=current_time;
         m_pred_1D.trade_allowed=true;
         break;
        }
     }

   return(true);
  }

//+------------------------------------------------------------------+
//| Load predictions from JSON for live trading                       |
//+------------------------------------------------------------------+
bool CGGTHExpert::LoadPredictionsFromJSON()
  {
//--- v1.16: prefer the flat EA-facing signal file when the predictor
//--- (v9.4+) has written one. The flat file is safer to parse — top-level
//--- keys only, no nested objects, schema explicitly documented — and
//--- carries the v9.4 confidence_floor field that the legacy nested file
//--- doesn't have. If the flat file is absent or fails to parse we fall
//--- through to the legacy path so older predictor builds keep working.
   if(LoadEASignalFromJSON())
     {
      m_using_flat_signal = true;
      return true;
     }
   m_using_flat_signal = false;

   string filename=m_symbol+"_predictions_multitf.json";

//--- Stale-file guard: skip re-parse if file has not changed since last read
   datetime mod_time=(datetime)FileGetInteger(filename,FILE_MODIFY_DATE);
   if(mod_time>0 && mod_time<=m_last_json_mod)
      return(m_pred_1H.prediction>0);
   m_last_json_mod=mod_time;

   int file_handle=FileOpen(filename,FILE_READ|FILE_TXT|FILE_ANSI);
   if(file_handle==INVALID_HANDLE)
      return(false);

//--- Read entire file
   string json_content="";
   while(!FileIsEnding(file_handle))
     {
      json_content+=FileReadString(file_handle);
     }
   FileClose(file_handle);

   if(json_content=="")
      return(false);

//--- Parse predictions for each timeframe
   bool success=ParsePredictionJSON(json_content,"1H",m_pred_1H);
   success=success && ParsePredictionJSON(json_content,"4H",m_pred_4H);
   success=success && ParsePredictionJSON(json_content,"1D",m_pred_1D);

//--- Load Python-side veto decision from status file
   LoadStatusFromJSON();

   return success;
  }

//+------------------------------------------------------------------+
//| Load Python veto decision from EURUSD_status.json                |
//+------------------------------------------------------------------+
bool CGGTHExpert::LoadStatusFromJSON()
  {
//--- Status file written by Python as {SYMBOL}_status.json
   string filename=m_symbol+"_status.json";

//--- Modification-date short-circuit: skip parsing if file unchanged since
//--- last read. OnTick fires on every tick (50-100/sec on a busy session)
//--- so re-parsing the same JSON each time is wasteful. Cached values
//--- (m_trade_allowed, m_status_regime, m_last_updated_utc) remain valid
//--- between calls.
   datetime mod_time=(datetime)FileGetInteger(filename,FILE_MODIFY_DATE);
   if(mod_time>0 && mod_time<=m_last_status_mod)
      return(true);   // unchanged — cached values remain valid

   int handle=FileOpen(filename,FILE_READ|FILE_TXT|FILE_ANSI);
   if(handle==INVALID_HANDLE)
     {
      m_trade_allowed=true;   // file absent -> default allow
      return(false);
     }

   m_last_status_mod=mod_time;

   string json="";
   while(!FileIsEnding(handle))
      json+=FileReadString(handle);
   FileClose(handle);

//--- Locate "trade_allowed" key. Use the fully-quoted key form so we don't
//--- accidentally match a substring inside another key name.
   int pos=StringFind(json,"\"trade_allowed\"");
   if(pos<0)
     {
      m_trade_allowed=true;
      return(false);
     }

//--- Find the colon then the boolean value after it
   int colon_pos=StringFind(json,":",pos);
   if(colon_pos<0)
     {
      m_trade_allowed=true;
      return(false);
     }

   int val_start=colon_pos+1;
   while(val_start<StringLen(json) && StringGetCharacter(json,val_start)==32)
      val_start++;

//--- Read 5 chars: enough to match "true" or "fals"
   string val=StringSubstr(json,val_start,5);
   StringToLower(val);
   m_trade_allowed=(StringFind(val,"true")>=0);

   if(InpShowDebug && !m_trade_allowed)
      Print("[PYTHON VETO] status file: trade_allowed=false");

//--- Parse last_updated_utc for heartbeat watchdog.
//--- v1.15: search the QUOTED key (was unquoted, inconsistent with the
//--- adjacent trade_allowed and regime parsers and would silently match
//--- substrings of any future key containing "last_updated_utc"). Also
//--- cast to long to match m_last_updated_utc's widened type.
   int utc_pos=StringFind(json,"\"last_updated_utc\"");
   if(utc_pos>=0)
     {
      int utc_colon=StringFind(json,":",utc_pos);
      if(utc_colon>=0)
        {
         int ustart=utc_colon+1;
         while(ustart<StringLen(json) && StringGetCharacter(json,ustart)==32) ustart++;
         //--- Read up to 16 chars — long enough for any 64-bit epoch and
         //--- StringToInteger stops at the first non-digit anyway.
         string uval=StringSubstr(json,ustart,16);
         m_last_updated_utc=(long)StringToInteger(uval);
        }
     }

//--- Parse regime for lot-size modulation. Use quoted-key form to ensure
//--- we match the top-level "regime" rather than a nested one inside
//--- market_context (Python writes both, with the same value, but the
//--- nested one appears first in the JSON serialization order).
   int reg_pos=StringFind(json,"\"regime\"");
   if(reg_pos>=0)
     {
      int reg_colon=StringFind(json,":",reg_pos);
      if(reg_colon>=0)
        {
         int rstart=reg_colon+1;
         while(rstart<StringLen(json) &&
               (StringGetCharacter(json,rstart)==32 || StringGetCharacter(json,rstart)==34))
            rstart++;
         string rval=StringSubstr(json,rstart,10);
         if(StringFind(rval,"volatile")>=0)      m_status_regime="volatile";
         else if(StringFind(rval,"trending")>=0) m_status_regime="trending";
         else if(StringFind(rval,"ranging")>=0)  m_status_regime="ranging";
         else                                     m_status_regime="unknown";
        }
     }

   return(true);
  }

//+------------------------------------------------------------------+
//| v1.16 — Load flat EA-facing signal file ({SYMBOL}_ea_signal.json) |
//|                                                                   |
//| The flat-keys-only schema is documented in the Python predictor   |
//| (_write_ea_signal). This file is deliberately small and shallow   |
//| so the MQL5 string-search parser cannot misalign — the safer path |
//| compared to the legacy nested predictions_multitf.json.           |
//|                                                                   |
//| On success this populates EVERY field LoadPredictionsFromJSON +   |
//| LoadStatusFromJSON populate together: m_pred_*, m_trade_allowed,  |
//| m_status_regime, m_last_updated_utc, plus the new m_confidence_   |
//| floor that gates trade entry below the adaptive threshold.        |
//|                                                                   |
//| Returns false if the file is missing, unchanged since last read,  |
//| or fails to produce a valid prediction. Caller falls back to the  |
//| legacy nested-JSON path on false.                                 |
//+------------------------------------------------------------------+
bool CGGTHExpert::LoadEASignalFromJSON()
  {
   string filename = m_symbol + "_ea_signal.json";

//--- Stale-file guard: same pattern as LoadPredictionsFromJSON. Note
//--- this guard intentionally uses its own m_last_signal_mod field —
//--- the flat file and the legacy file have independent mtimes.
   datetime mod_time = (datetime)FileGetInteger(filename, FILE_MODIFY_DATE);
   if(mod_time <= 0)
      return false;   // file does not exist or has no mtime — fall back to legacy
   if(mod_time <= m_last_signal_mod)
     {
      //--- File unchanged since last successful read. Cached values are
      //--- still valid; report success so the caller skips the legacy path.
      return (m_pred_1H.prediction > 0);
     }

   int h = FileOpen(filename, FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(h == INVALID_HANDLE)
      return false;

   string json = "";
   while(!FileIsEnding(h)) json += FileReadString(h);
   FileClose(h);

   if(StringLen(json) < 20)   // smallest plausible signal is ~hundreds of bytes
      return false;

//--- Schema gate. The predictor stamps schema_version=1; refuse to load
//--- forwards-incompatible files. If the predictor is upgraded to a v2
//--- schema, the EA must be upgraded in lockstep.
   double sv = 0.0;
   if(!ExtractJsonNumber(json, "\"schema_version\"", sv) || (int)sv != 1)
     {
      Print("[FLAT-SIGNAL] Refusing to load — schema_version=", (int)sv,
            " not supported by this EA build (expects 1). "
            "Upgrade EA in lockstep with predictor.");
      return false;
     }

//--- Each field is independently extracted. ExtractJson* leaves the
//--- destination untouched on missing/malformed key, so partial files
//--- degrade gracefully rather than silently zeroing out cached state.
   double pred_1H = 0, pred_4H = 0, pred_1D = 0;
   double chg_1H = 0,  chg_4H = 0,  chg_1D = 0;
   double std_1H = 0,  std_4H = 0,  std_1D = 0;
   double current_price_signal = 0;
   double conf_floor = 0;
   double last_utc_d = 0;
   bool   trade_allowed_local = true;
   string regime_local = "unknown";

   ExtractJsonNumber(json, "\"pred_1H\"",          pred_1H);
   ExtractJsonNumber(json, "\"pred_4H\"",          pred_4H);
   ExtractJsonNumber(json, "\"pred_1D\"",          pred_1D);
   ExtractJsonNumber(json, "\"change_1H_pct\"",    chg_1H);
   ExtractJsonNumber(json, "\"change_4H_pct\"",    chg_4H);
   ExtractJsonNumber(json, "\"change_1D_pct\"",    chg_1D);
   ExtractJsonNumber(json, "\"ensemble_std_1H\"",  std_1H);
   ExtractJsonNumber(json, "\"ensemble_std_4H\"",  std_4H);
   ExtractJsonNumber(json, "\"ensemble_std_1D\"",  std_1D);
   ExtractJsonNumber(json, "\"current_price\"",    current_price_signal);
   ExtractJsonNumber(json, "\"confidence_floor\"", conf_floor);
   ExtractJsonNumber(json, "\"last_updated_utc\"", last_utc_d);
   ExtractJsonBool  (json, "\"trade_allowed\"",    trade_allowed_local);
   ExtractJsonString(json, "\"regime\"",           regime_local);

//--- Reject obviously-bad parses — must have at least the 1H prediction.
//--- We don't require all three TFs because a future predictor build
//--- may legitimately publish only one or two; but no 1H means the
//--- signal is unusable.
   if(pred_1H <= 0)
     {
      Print("[FLAT-SIGNAL] Parse produced pred_1H<=0; falling back to legacy file.");
      return false;
     }

//--- Commit. Populate the same fields the legacy loaders populate so
//--- the rest of the EA doesn't care which path produced them.
   m_pred_1H.prediction   = pred_1H;
   m_pred_1H.change_pct   = chg_1H;
   m_pred_1H.ensemble_std = std_1H;
   m_pred_1H.last_update  = TimeCurrent();
   m_pred_1H.trade_allowed = trade_allowed_local;

   m_pred_4H.prediction   = pred_4H;
   m_pred_4H.change_pct   = chg_4H;
   m_pred_4H.ensemble_std = std_4H;
   m_pred_4H.last_update  = TimeCurrent();
   m_pred_4H.trade_allowed = trade_allowed_local;

   m_pred_1D.prediction   = pred_1D;
   m_pred_1D.change_pct   = chg_1D;
   m_pred_1D.ensemble_std = std_1D;
   m_pred_1D.last_update  = TimeCurrent();
   m_pred_1D.trade_allowed = trade_allowed_local;

   m_trade_allowed     = trade_allowed_local;
   m_status_regime     = regime_local;
   m_last_updated_utc  = (long)last_utc_d;
   m_confidence_floor  = conf_floor;

   m_last_signal_mod = mod_time;
   return true;
  }

//+------------------------------------------------------------------+
//| Find the closing brace that matches the opening brace at start.   |
//| Returns -1 if no balanced match is found before end of string.    |
//|                                                                   |
//| Used by ParsePredictionJSON to bound the field searches to the    |
//| current timeframe's object — see comment in that function.        |
//+------------------------------------------------------------------+
int FindMatchingBrace(const string &json, int open_pos)
  {
   int depth = 0;
   int len = StringLen(json);
   for(int i = open_pos; i < len; i++)
     {
      ushort c = StringGetCharacter(json, i);
      if(c == '{')
         depth++;
      else if(c == '}')
        {
         depth--;
         if(depth == 0) return i;
        }
     }
   return -1;
  }

//+------------------------------------------------------------------+
//| Extract a numeric value for a given key inside a (small) JSON    |
//| object substring. Returns true on success, leaving out untouched  |
//| if the key is missing or unparseable. Helper for ParsePredictionJSON. |
//+------------------------------------------------------------------+
bool ExtractJsonNumber(const string &obj, const string &quoted_key, double &out)
  {
   int kpos = StringFind(obj, quoted_key);
   if(kpos < 0) return false;

   int colon = StringFind(obj, ":", kpos + StringLen(quoted_key));
   if(colon < 0) return false;

   int vstart = colon + 1;
   //--- Skip whitespace after the colon (space + tab)
   while(vstart < StringLen(obj))
     {
      ushort c = StringGetCharacter(obj, vstart);
      if(c != 32 && c != 9) break;
      vstart++;
     }

   //--- Find end of numeric token (comma, closing brace, or end of string).
   //--- A simple linear scan over the value chars is fine here — we trust
   //--- the writer to produce well-formed JSON numbers (no embedded commas).
   int vend = vstart;
   int len  = StringLen(obj);
   while(vend < len)
     {
      ushort c = StringGetCharacter(obj, vend);
      if(c == ',' || c == '}' || c == '\n' || c == '\r')
         break;
      vend++;
     }

   string vstr = StringSubstr(obj, vstart, vend - vstart);
   StringTrimLeft(vstr);
   StringTrimRight(vstr);
   out = StringToDouble(vstr);
   return true;
  }

//+------------------------------------------------------------------+
//| Extract a STRING value for a given key. Looks for the opening    |
//| quote after the colon and reads until the matching close quote.  |
//| Does NOT handle escaped quotes (\") — the predictor never emits  |
//| them in the flat signal so this is a deliberate simplification.  |
//+------------------------------------------------------------------+
bool ExtractJsonString(const string &obj, const string &quoted_key, string &out)
  {
   int kpos = StringFind(obj, quoted_key);
   if(kpos < 0) return false;

   int colon = StringFind(obj, ":", kpos + StringLen(quoted_key));
   if(colon < 0) return false;

   //--- Find the opening quote of the value
   int q_open = StringFind(obj, "\"", colon);
   if(q_open < 0) return false;

   int q_close = StringFind(obj, "\"", q_open + 1);
   if(q_close < 0) return false;

   out = StringSubstr(obj, q_open + 1, q_close - q_open - 1);
   return true;
  }

//+------------------------------------------------------------------+
//| Extract a BOOL value for a given key (true/false JSON literal).  |
//+------------------------------------------------------------------+
bool ExtractJsonBool(const string &obj, const string &quoted_key, bool &out)
  {
   int kpos = StringFind(obj, quoted_key);
   if(kpos < 0) return false;

   int colon = StringFind(obj, ":", kpos + StringLen(quoted_key));
   if(colon < 0) return false;

   //--- Read up to 8 chars after the colon — long enough to spot "true" or "false"
   //--- regardless of leading whitespace.
   int vstart = colon + 1;
   while(vstart < StringLen(obj))
     {
      ushort c = StringGetCharacter(obj, vstart);
      if(c != 32 && c != 9) break;
      vstart++;
     }
   string snippet = StringSubstr(obj, vstart, 8);
   //--- Case-sensitive — JSON spec says lowercase only, predictor emits lowercase.
   if(StringFind(snippet, "true") == 0)
     {
      out = true;
      return true;
     }
   if(StringFind(snippet, "false") == 0)
     {
      out = false;
      return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
//| Parse prediction JSON for a single timeframe block.               |
//|                                                                   |
//| v1.15 fix (CRITICAL): the previous implementation searched for    |
//| "prediction"/"change_pct"/"ensemble_std" anywhere in the file     |
//| after the timeframe key, with no upper bound on the search. If    |
//| the timeframe's own object was missing one of those fields (e.g.  |
//| because the writer crashed mid-flush, or a future schema change), |
//| the parser would silently grab the field from the *next* time-    |
//| frame's object. The EA would then trade on cross-contaminated     |
//| data — and because the file mtime had advanced, the watchdog      |
//| would not catch it.                                               |
//|                                                                   |
//| The fix: locate the timeframe's opening brace, walk to its        |
//| matching close, and confine ALL field searches to the resulting   |
//| substring. Any missing field stays at its zero-init default       |
//| rather than absorbing a value from a sibling block.               |
//+------------------------------------------------------------------+
bool CGGTHExpert::ParsePredictionJSON(string json,string timeframe,CPredictionData &pred)
  {
   string search_key="\""+timeframe+"\":";
   int pos = StringFind(json, search_key);
   if(pos < 0) return(false);

//--- Find the opening brace that begins this timeframe's object.
//--- Skip any whitespace between the colon and the brace.
   int obj_open = StringFind(json, "{", pos);
   if(obj_open < 0) return(false);

//--- Walk to the matching close brace. Anything after this point belongs
//--- to a different timeframe (or to top-level metadata) and must NOT
//--- influence this timeframe's parse.
   int obj_close = FindMatchingBrace(json, obj_open);
   if(obj_close < 0) return(false);

   string obj = StringSubstr(json, obj_open, obj_close - obj_open + 1);

//--- Extract each field from the bounded substring.
//--- Missing fields leave the corresponding pred.* member at its prior
//--- value, so a partial flush degrades gracefully rather than reading
//--- a sibling timeframe's number.
   ExtractJsonNumber(obj, "\"prediction\"",   pred.prediction);
   ExtractJsonNumber(obj, "\"change_pct\"",   pred.change_pct);
   ExtractJsonNumber(obj, "\"ensemble_std\"", pred.ensemble_std);

   pred.last_update   = TimeCurrent();
   pred.trade_allowed = true;

   return(pred.prediction > 0);
  }

//+------------------------------------------------------------------+
//| Update accuracy tracking                                          |
//+------------------------------------------------------------------+
void CGGTHExpert::UpdateAccuracyTracking()
  {
   CheckAccuracyForTimeframe(m_tracker_1H,m_pred_1H,PERIOD_H1);
   CheckAccuracyForTimeframe(m_tracker_4H,m_pred_4H,PERIOD_H4);
   CheckAccuracyForTimeframe(m_tracker_1D,m_pred_1D,PERIOD_D1);
  }

//+------------------------------------------------------------------+
//| Check accuracy for specific timeframe                             |
//+------------------------------------------------------------------+
void CGGTHExpert::CheckAccuracyForTimeframe(CAccuracyTracker &tracker,CPredictionData &pred,ENUM_TIMEFRAMES tf)
  {
//--- If we have a new prediction, record it
   if(pred.last_update>tracker.current_prediction.timestamp && pred.prediction>0)
     {
      if(!tracker.current_prediction.checked)
        {
//--- Check previous prediction if it exists
         if(tracker.current_prediction.timestamp>0)
           {
            datetime check_time=tracker.current_prediction.timestamp;
            int shift=iBarShift(m_symbol,tf,check_time);

            if(shift>=1)
              {
               double actual_price=iClose(m_symbol,tf,shift-1);
               double predicted_direction=(tracker.current_prediction.predicted_price-tracker.current_prediction.start_price);
               double actual_direction=(actual_price-tracker.current_prediction.start_price);

               bool accurate=(predicted_direction*actual_direction>0);

               tracker.total_predictions++;
               if(accurate)
                  tracker.accurate_predictions++;

               if(tracker.total_predictions>0)
                  tracker.accuracy_percent=(double)tracker.accurate_predictions/tracker.total_predictions*100.0;

               tracker.current_prediction.checked=true;
               tracker.current_prediction.accurate=accurate;
              }
           }
        }

//--- Record new prediction
      tracker.current_prediction.timestamp=pred.last_update;
      tracker.current_prediction.predicted_price=pred.prediction;
      tracker.current_prediction.start_price=m_current_price;
      tracker.current_prediction.checked=false;
     }
  }

//+------------------------------------------------------------------+
//| Check for trade signal                                            |
//+------------------------------------------------------------------+
void CGGTHExpert::CheckForTradeSignal()
  {
   if(!InpEnableTrading)
      return;

//--- Heartbeat watchdog (v1.13): now configurable + chart-visible.
//    The check applies to NEW ENTRIES only; CheckMaxHoldTime, profit
//    protection, and trailing stops continue to manage open positions
//    even when the watchdog is firing — we always want to be able to
//    EXIT, even on stale data.
   if(IsPredictionStale())
     {
      if(InpShowDebug)
         Print("[WATCHDOG] ",m_watchdog_reason," — new entry blocked");
      return;
     }

//--- Python veto: honours uncertainty, cross-TF agreement, and macro vetoes
   if(!m_trade_allowed)
     {
      if(InpShowDebug)
         Print("[PYTHON VETO] New entry blocked — Python veto active (see status file)");
      return;
     }

//--- Check if trading is allowed (day/session filters)
   if(!IsTradingAllowed())
      return;

//--- Apply market context veto early if active
   if(InpUseMarketContextVeto && m_market_context.veto_active)
     {
      if(InpShowDebug)
         Print("Trade blocked by Market Context Veto");
      return;
     }

//--- Check margin utilization using ACCOUNT_MARGIN_FREE (canonical MT5 method)
   double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double equity      = AccountInfoDouble(ACCOUNT_EQUITY);
   double margin_usage= (equity>0) ? ((equity-free_margin)/equity*100.0) : 0.0;
   if(margin_usage > InpMaxMarginUsagePct)
     {
      if(InpShowDebug)
         Print("[MARGIN] New trade blocked: margin usage ",DoubleToString(margin_usage,1),
               "% exceeds limit of ",DoubleToString(InpMaxMarginUsagePct,1),"%");
      return;
     }

//--- Get the prediction for selected timeframe
   CPredictionData selected_pred;
   string tf_name="";

   switch(InpTradingTimeframe)
     {
      case PERIOD_H1:
         selected_pred=m_pred_1H;
         tf_name="1H";
         break;
      case PERIOD_H4:
         selected_pred=m_pred_4H;
         tf_name="4H";
         break;
      case PERIOD_D1:
         selected_pred=m_pred_1D;
         tf_name="1D";
         break;
      default:
         Print("ERROR: Unsupported trading timeframe");
         return;
     }

   if(selected_pred.prediction<=0)
      return;

//--- Determine pip size
   double point=SymbolInfoDouble(m_symbol,SYMBOL_POINT);
   double pip=point;
   if(_Digits==3 || _Digits==5)
      pip=point*10.0;

//--- Compute prediction distance in pips
   double delta_pips=(selected_pred.prediction-m_current_price)/pip;

   bool signal_buy=false;
   bool signal_sell=false;

//--- Use adaptive min_pred_pips if learning is enabled, else use input
   double effective_min_pred_pips=InpEnableAdaptiveLearning
                                  ? m_adaptive.min_pred_pips
                                  : (double)InpMinPredictionPips;

   if(effective_min_pred_pips<=0)
     {
      signal_buy=(selected_pred.prediction>m_current_price);
      signal_sell=(selected_pred.prediction<m_current_price);
     }
   else
     {
      signal_buy=(delta_pips>=effective_min_pred_pips);
      signal_sell=(delta_pips<=-effective_min_pred_pips);
     }

//--- v1.16 — adaptive confidence floor (Python-side live-trade feedback).
//    The flat signal file carries m_confidence_floor in PERCENT, derived
//    from the Bayesian posterior over realised winrate. When recent live
//    P/L is poor, the floor rises and the EA must see a stronger predicted
//    move before entering. When the loop is healthy, the floor stays at
//    the predictor's BASELINE_FLOOR (default 0.05%) which is a no-op.
//
//    Skipped when:
//      • flat signal not available (m_using_flat_signal=false) — legacy
//        predictor builds don't publish a floor, so we keep prior behaviour
//      • floor is non-positive (predictor explicitly disabled adaptation)
//
//    Note this is INDEPENDENT of effective_min_pred_pips: pips and % are
//    complementary measures (5 pips on EURUSD ≠ 5 pips on USDJPY in %
//    terms), and both gates must clear for a signal to survive.
   if(m_using_flat_signal && m_confidence_floor > 0.0)
     {
//--- v1.18 fix: recompute abs_change from live price vs predicted price.
//    The signal file's change_Xh_pct was computed at prediction time against
//    the price Python saw when it ran. By the time the EA reads the file,
//    price may have moved substantially — the pre-baked pct is stale.
//    Using the live current price gives the same number the panel displays.
      double abs_change = (m_current_price > 0)
                        ? MathAbs((selected_pred.prediction - m_current_price) / m_current_price) * 100.0
                        : MathAbs(selected_pred.change_pct);
      if(abs_change < m_confidence_floor)
        {
         if(InpShowDebug)
            PrintFormat("[CONF-FLOOR] %s |change|=%.3f%% < floor=%.3f%% — entry blocked",
                        tf_name, abs_change, m_confidence_floor);
         signal_buy  = false;
         signal_sell = false;
        }
     }

//--- If no valid direction, exit
   if(!signal_buy && !signal_sell)
      return;

//--- Apply trend filter
   if(InpUseTrendFilter)
     {
      if(!CheckTrendFilter(signal_buy,signal_sell))
        {
         if(InpShowDebug)
            Print("Trade rejected by trend filter");
         return;
        }
     }

//--- Apply RSI filter
   if(InpUseRSIFilter)
     {
      if(!CheckRSIFilter(signal_buy,signal_sell))
        {
         if(InpShowDebug)
            Print("Trade rejected by RSI filter");
         return;
        }
     }

//--- v1.18: Sentiment veto.
//    CRITICAL DESIGN NOTE — BACKTESTS:
//    During (bool)MQLInfoInteger(MQL_TESTER), ReadSentimentFile() marks m_sentiment.valid=false,
//    so this block is always a no-op in Strategy Tester. This is correct:
//    there is no historical sentiment archive — applying today's news
//    sentiment to past bars would be severe look-ahead bias. Backtest
//    results therefore reflect the ML prediction engine alone, which is
//    the correct baseline. Sentiment is a live-only risk filter on top.
//
//    LIVE MODE:
//    A veto fires only when sentiment is fresh enough (< InpSentimentMaxAgeSec),
//    confident enough (>= InpSentimentMinConf), AND decisively opposed to the
//    signal (|score| > InpSentimentVetoBand). Neutral or uncertain sentiment
//    passes all signals through unchanged (fail-open).
   if(InpUseSentiment && m_sentiment.valid && !(bool)MQLInfoInteger(MQL_TESTER))
     {
      if(signal_buy && m_sentiment.score < -InpSentimentVetoBand)
        {
         if(InpShowDebug)
            PrintFormat("[SENTIMENT] BUY vetoed — score=%.3f conf=%.2f age=%ds",
                        m_sentiment.score, m_sentiment.confidence, (int)m_sentiment.age_seconds);
         return;
        }
      if(signal_sell && m_sentiment.score > +InpSentimentVetoBand)
        {
         if(InpShowDebug)
            PrintFormat("[SENTIMENT] SELL vetoed — score=%.3f conf=%.2f age=%ds",
                        m_sentiment.score, m_sentiment.confidence, (int)m_sentiment.age_seconds);
         return;
        }
     }

//--- Calculate position size (apply adaptive lot multiplier)
   double lot_size=CalculateLotSize();
   if(InpEnableAdaptiveLearning)
      lot_size*=m_adaptive.lot_multiplier;
   if(lot_size<=0)
      return;

//--- Re-normalize after multiplier
   {
    double min_lot=SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_MIN);
    double max_lot=SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_MAX);
    double lot_step=SymbolInfoDouble(m_symbol,SYMBOL_VOLUME_STEP);
    lot_size=MathFloor(lot_size/lot_step)*lot_step;
    lot_size=MathMax(lot_size,min_lot);
    lot_size=MathMin(lot_size,max_lot);
   }

//--- FIFO COMPLIANCE: block any trade that would hedge an existing position.
//--- NFA Rule 2-43(b) prohibits opening a position opposite to an existing one
//--- on the same symbol. We must also refuse to open a new position in any
//--- direction while an opposite position is open.
   if(InpFIFOCompliant)
     {
      for(int i=PositionsTotal()-1; i>=0; i--)
        {
         ulong chk_ticket=PositionGetTicket(i);
         if(chk_ticket<=0) continue;
         if(PositionGetString(POSITION_SYMBOL)!=m_symbol) continue;
         if(PositionGetInteger(POSITION_MAGIC)!=InpMagic) continue;

         long existing_type=PositionGetInteger(POSITION_TYPE);
         if(signal_buy && existing_type==POSITION_TYPE_SELL)
           {
            if(InpShowDebug)
               Print("[FIFO] BUY blocked - open SELL position exists (FIFO mode)");
            return;
           }
         if(signal_sell && existing_type==POSITION_TYPE_BUY)
           {
            if(InpShowDebug)
               Print("[FIFO] SELL blocked - open BUY position exists (FIFO mode)");
            return;
           }
        }
     }

//--- Read current RSI for entry record
   double rsi_entry=50.0;
   if(InpUseRSIFilter && m_handle_rsi!=INVALID_HANDLE)
     {
      double rsi_buf[];
      ArraySetAsSeries(rsi_buf,true);
      if(CopyBuffer(m_handle_rsi,0,0,1,rsi_buf)==1)
         rsi_entry=rsi_buf[0];
     }

//--- Calculate SL and TP
   double sl_distance=InpStopLossPips*pip;
   double tp_price=0;
   double tp_distance=0;

//--- Use predicted price as TP
   if(InpUsePredictedPrice)
     {
      tp_price=selected_pred.prediction*InpTPMultiplier;

      double tp_pips=MathAbs(tp_price-m_current_price)/pip;

      if(tp_pips<InpMinTPPips)
         return;

      if(tp_pips>InpMaxTPPips)
        {
         if(signal_buy)
            tp_price=m_current_price+(InpMaxTPPips*pip);
         else
            tp_price=m_current_price-(InpMaxTPPips*pip);
        }
     }
   else
     {
      tp_distance=InpTakeProfitPips*pip;
     }

//--- Execute trade
   if(signal_buy)
     {
      double ask=SymbolInfoDouble(m_symbol,SYMBOL_ASK);
      double sl=ask-sl_distance;
      double tp=InpUsePredictedPrice ? tp_price : ask+tp_distance;

      if(tp<=ask)
         return;

  double display_pct = (m_current_price > 0)
                     ? (selected_pred.prediction - m_current_price) / m_current_price * 100.0
                     : 0.0;
string comment = StringFormat("GGTH v" + EA_VERSION_STR + " [%s] %s%.3f%% TP:%." + IntegerToString(_Digits) + "f",
                              tf_name,
                              (display_pct >= 0 ? "+" : ""),
                              display_pct,
                              tp);

      if(m_trade.Buy(lot_size,m_symbol,ask,sl,tp,comment))
        {
         m_last_trade_time=TimeCurrent();
         ulong pos_id=m_trade.ResultOrder();
         //--- Record entry for adaptive learning
         //--- In MT5, position_id == the opening ORDER ticket (ResultOrder),
         //--- which matches DEAL_POSITION_ID on the closing deal.
         if(InpEnableAdaptiveLearning)
           {
            RecordTradeEntry(pos_id,true,selected_pred.change_pct,MathAbs(delta_pips),rsi_entry);
           }
         //--- Trade journal (v1.13): persist full decision context to CSV
         if(InpEnableTradeJournal)
           {
            WriteJournalEntry(pos_id,true,ask,lot_size,sl,tp,
                              tf_name,selected_pred.change_pct,
                              MathAbs(delta_pips),rsi_entry,"PRIMARY");
           }
         Print("GGTH BUY placed [",tf_name,"]",
               " pred:",DoubleToString(selected_pred.prediction,_Digits),
               " TP:",DoubleToString(tp,_Digits),
               " SL:",DoubleToString(sl,_Digits),
               " LotMult:",DoubleToString(m_adaptive.lot_multiplier,2));
        }
     }
   else if(signal_sell)
     {
      double bid=SymbolInfoDouble(m_symbol,SYMBOL_BID);
      double sl=bid+sl_distance;
      double tp=InpUsePredictedPrice ? tp_price : bid-tp_distance;

      if(tp>=bid)
         return;

      string comment=StringFormat("GGTH v"+EA_VERSION_STR+" [%s] %.2f%% TP:%."+IntegerToString(_Digits)+"f",
                                  tf_name,
                                  selected_pred.change_pct,
                                  tp);

      if(m_trade.Sell(lot_size,m_symbol,bid,sl,tp,comment))
        {
         m_last_trade_time=TimeCurrent();
         ulong pos_id=m_trade.ResultOrder();
         //--- Record entry for adaptive learning
         if(InpEnableAdaptiveLearning)
           {
            RecordTradeEntry(pos_id,false,selected_pred.change_pct,MathAbs(delta_pips),rsi_entry);
           }
         //--- Trade journal (v1.13): persist full decision context to CSV
         if(InpEnableTradeJournal)
           {
            WriteJournalEntry(pos_id,false,bid,lot_size,sl,tp,
                              tf_name,selected_pred.change_pct,
                              MathAbs(delta_pips),rsi_entry,"PRIMARY");
           }
         Print("GGTH SELL placed [",tf_name,"]",
               " pred:",DoubleToString(selected_pred.prediction,_Digits),
               " TP:",DoubleToString(tp,_Digits),
               " SL:",DoubleToString(sl,_Digits),
               " LotMult:",DoubleToString(m_adaptive.lot_multiplier,2));
        }
     }
  }

//+------------------------------------------------------------------+
//| Check trend filter                                                |
//+------------------------------------------------------------------+
bool CGGTHExpert::CheckTrendFilter(bool &signal_buy,bool &signal_sell)
  {
   double ma_buffer[];
   ArraySetAsSeries(ma_buffer,true);

   if(CopyBuffer(m_handle_trend_ma,0,0,2,ma_buffer)!=2)
      return(false);

   double current_ma=ma_buffer[0];
   double current_close=iClose(m_symbol,Period(),0);

//--- Only allow buy if price is above MA
   if(signal_buy && current_close<current_ma)
     {
      signal_buy=false;
      return(false);
     }

//--- Only allow sell if price is below MA
   if(signal_sell && current_close>current_ma)
     {
      signal_sell=false;
      return(false);
     }

   return(true);
  }

//+------------------------------------------------------------------+
//| Check RSI filter                                                  |
//+------------------------------------------------------------------+
bool CGGTHExpert::CheckRSIFilter(bool &signal_buy,bool &signal_sell)
  {
   double rsi_buffer[];
   ArraySetAsSeries(rsi_buffer,true);

   if(CopyBuffer(m_handle_rsi,0,0,2,rsi_buffer)!=2)
      return(false);

   double current_rsi=rsi_buffer[0];

//--- Use adaptive RSI levels if learning enabled
   double ob_level=InpEnableAdaptiveLearning ? m_adaptive.rsi_overbought : InpRSIOverbought;
   double os_level=InpEnableAdaptiveLearning ? m_adaptive.rsi_oversold   : InpRSIOversold;

//--- Don't buy if RSI is overbought
   if(signal_buy && current_rsi>ob_level)
     {
      signal_buy=false;
      return(false);
     }

//--- Don't sell if RSI is oversold
   if(signal_sell && current_rsi<os_level)
     {
      signal_sell=false;
      return(false);
     }

   return(true);
  }

//+------------------------------------------------------------------+
//| Check if trading is allowed                                       |
//+------------------------------------------------------------------+
bool CGGTHExpert::IsTradingAllowed()
  {
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(),dt);

//--- Check day of week
   switch(dt.day_of_week)
     {
      case 1:
         if(!InpTradeMonday) return(false);
         break;
      case 2:
         if(!InpTradeTuesday) return(false);
         break;
      case 3:
         if(!InpTradeWednesday) return(false);
         break;
      case 4:
         if(!InpTradeThursday) return(false);
         break;
      case 5:
         if(!InpTradeFriday) return(false);
         break;
      case 6:
         if(!InpTradeSaturday) return(false);
         break;
      case 0:
         if(!InpTradeSunday) return(false);
         break;
     }

//--- Check trading sessions
   return IsWithinTradingSession(dt.hour,dt.min);
  }

//+------------------------------------------------------------------+
//| Check if within trading session                                   |
//+------------------------------------------------------------------+
bool CGGTHExpert::IsWithinTradingSession(int hour,int minute)
  {
   int current_minutes=hour*60+minute;

//--- Check Session 1
   if(InpUseSession1)
     {
      int start1=InpSession1StartHour*60+InpSession1StartMinute;
      int end1=InpSession1EndHour*60+InpSession1EndMinute;

      if(start1<=end1)
        {
         if(current_minutes>=start1 && current_minutes<=end1)
            return(true);
        }
      else
        {
         if(current_minutes>=start1 || current_minutes<=end1)
            return(true);
        }
     }

//--- Check Session 2
   if(InpUseSession2)
     {
      int start2=InpSession2StartHour*60+InpSession2StartMinute;
      int end2=InpSession2EndHour*60+InpSession2EndMinute;

      if(start2<=end2)
        {
         if(current_minutes>=start2 && current_minutes<=end2)
            return(true);
        }
      else
        {
         if(current_minutes>=start2 || current_minutes<=end2)
            return(true);
        }
     }

//--- Check Session 3
   if(InpUseSession3)
     {
      int start3=InpSession3StartHour*60+InpSession3StartMinute;
      int end3=InpSession3EndHour*60+InpSession3EndMinute;

      if(start3<=end3)
        {
         if(current_minutes>=start3 && current_minutes<=end3)
            return(true);
        }
      else
        {
         if(current_minutes>=start3 || current_minutes<=end3)
            return(true);
        }
     }

   return(false);
  }

//+------------------------------------------------------------------+
//| Display information — compact panel with solid background        |
//+------------------------------------------------------------------+
void CGGTHExpert::DisplayInfo()
  {
   int fs  = InpFontSize;
   int lh  = fs + InpLineSpacing;         // line height = font size + spacing
   int pad = InpPanelPadding;             // inner padding px
   int bw  = fs * 80;                    // box width scales with font size
   int tx  = InpXOffset + pad;           // text x (inside padding)
   int ty  = InpYOffset + pad;           // running text y

   int content_rows = 2;                  // title + price
   content_rows += 1;                     // separator
   bool show_wd = (InpShowWatchdogStatusOnChart &&
                   InpEnableStaleWatchdog &&
                   !InpStrategyTesterMode);
   if(show_wd) { content_rows += 1; content_rows += 1; } // wd + sep
   content_rows += 1;                     // PREDICTIONS header
   content_rows += 6;                     // 3 TFs × 2 rows each
   if(InpEnableAdaptiveLearning) content_rows += 5; // sep+hdr+3 rows
   bool show_sent = (InpUseSentiment && !(bool)MQLInfoInteger(MQL_TESTER));
   if(show_sent) content_rows += (m_sentiment.valid ? 5 : 3); // sep+hdr+rows

   int bh = pad * 2 + content_rows * lh + 20;  // +20: extra bottom padding + separator gaps

   // ── Background rectangle ─────────────────────────────────────
   string bg = "MLEA_BG";
   if(ObjectFind(0, bg) < 0)
     {
      ObjectCreate(0, bg, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, bg, OBJPROP_CORNER,    CORNER_LEFT_UPPER);
      ObjectSetInteger(0, bg, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, bg, OBJPROP_BACK,       false);
      ObjectSetInteger(0, bg, OBJPROP_ZORDER,     0);
      ObjectSetString (0, bg, OBJPROP_TOOLTIP,    "\n");
     }
   ObjectSetInteger(0, bg, OBJPROP_XDISTANCE,  InpXOffset);
   ObjectSetInteger(0, bg, OBJPROP_YDISTANCE,  InpYOffset);
   ObjectSetInteger(0, bg, OBJPROP_XSIZE,      bw);
   ObjectSetInteger(0, bg, OBJPROP_YSIZE,      bh);
   ObjectSetInteger(0, bg, OBJPROP_BGCOLOR,    C'10,14,28');
   ObjectSetInteger(0, bg, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, bg, OBJPROP_COLOR,      C'45,75,160');
   ObjectSetInteger(0, bg, OBJPROP_WIDTH,      2);
   ObjectSetInteger(0, bg, OBJPROP_ZORDER,     0);

   // ── Helper: thin separator bar ───────────────────────────────
   // Drawn as a narrow colored rectangle label, not a text label,
   // so it fills the full box width reliably at all font sizes.
   string sep_id = "MLEA_Sep";
   #define MKSEP(id, yy) \
     { if(ObjectFind(0,(id))<0) { \
         ObjectCreate(0,(id),OBJ_RECTANGLE_LABEL,0,0,0); \
         ObjectSetInteger(0,(id),OBJPROP_CORNER,CORNER_LEFT_UPPER); \
         ObjectSetInteger(0,(id),OBJPROP_SELECTABLE,false); \
         ObjectSetInteger(0,(id),OBJPROP_BACK,false); \
         ObjectSetString (0,(id),OBJPROP_TOOLTIP,"\n"); } \
       ObjectSetInteger(0,(id),OBJPROP_XDISTANCE, InpXOffset+4); \
       ObjectSetInteger(0,(id),OBJPROP_YDISTANCE, (yy)); \
       ObjectSetInteger(0,(id),OBJPROP_XSIZE, bw-8); \
       ObjectSetInteger(0,(id),OBJPROP_YSIZE, 2); \
       ObjectSetInteger(0,(id),OBJPROP_BGCOLOR, C'60,100,200'); \
       ObjectSetInteger(0,(id),OBJPROP_BORDER_TYPE, BORDER_FLAT); \
       ObjectSetInteger(0,(id),OBJPROP_COLOR, C'60,100,200'); \
       ObjectSetInteger(0,(id),OBJPROP_ZORDER, 1); }

   // ── Row 1: Title ─────────────────────────────────────────────
   CreateLabel("MLEA_Title", tx, ty,
               "GGTH PREDICTOR v"+EA_VERSION_STR+"  |  "+m_symbol,
               fs+1, clrGold);
   ty += lh;

   // ── Row 2: Price + Regime ────────────────────────────────────
   string price_str = StringFormat("Price: %."+IntegerToString(_Digits)+"f    Regime: "+m_status_regime,
                                   m_current_price);
   CreateLabel("MLEA_Price", tx, ty, price_str, fs, clrWhite);
   ty += lh + 2;

   // ── Separator ────────────────────────────────────────────────
   MKSEP("MLEA_Sep1", ty);
   ty += 8;

   // ── Watchdog banner ──────────────────────────────────────────
   if(show_wd)
     {
      string wd_txt;
      color  wd_col;
      if(m_watchdog_stale)
        {
         wd_txt = StringFormat("[!] STALE  age=%dm  ENTRIES BLOCKED",
                               (m_watchdog_age_sec >= 0 ? m_watchdog_age_sec/60 : -1));
         wd_col = clrRed;
        }
      else if(m_last_updated_utc <= 0)
        {
         wd_txt = "[?] No heartbeat from Python yet";
         wd_col = clrOrange;
        }
      else
        {
         wd_txt = StringFormat("[OK] Watchdog  age=%dm / limit=%dm",
                               m_watchdog_age_sec/60, InpStalePredictionMaxMinutes);
         wd_col = clrLimeGreen;
        }
      CreateLabel("MLEA_Watchdog", tx, ty, wd_txt, fs-1, wd_col);
      ty += lh + 2;
      MKSEP("MLEA_Sep2", ty);
      ty += 8;
     }

   // ── PREDICTIONS header ───────────────────────────────────────
   CreateLabel("MLEA_PredHeader", tx, ty, "PREDICTIONS", fs, clrYellow);
   ty += lh;

   // ── Three timeframe blocks ───────────────────────────────────
   DisplayPredictionLine("1H", m_pred_1H, m_tracker_1H, tx, ty, lh);
   DisplayPredictionLine("4H", m_pred_4H, m_tracker_4H, tx, ty, lh);
   DisplayPredictionLine("1D", m_pred_1D, m_tracker_1D, tx, ty, lh);

   // ── Adaptive section ─────────────────────────────────────────
   if(InpEnableAdaptiveLearning)
     {
      MKSEP("MLEA_Sep3", ty);
      ty += 8;
      DisplayAdaptiveInfo(tx, ty, lh);
     }
   else
     {
      // Hide sep3 if adaptive is off but was previously on
      if(ObjectFind(0, "MLEA_Sep3") >= 0)
         ObjectSetInteger(0, "MLEA_Sep3", OBJPROP_YSIZE, 0);
     }

   // ── Sentiment section (bottom of box) ───────────────────────
   if(show_sent)
     {
      MKSEP("MLEA_Sep4", ty);
      ty += 8;
      DisplaySentimentPanel(tx, ty, lh);
     }
   else
     {
      if(ObjectFind(0, "MLEA_Sep4") >= 0)
         ObjectSetInteger(0, "MLEA_Sep4", OBJPROP_YSIZE, 0);
     }

   #undef MKSEP

   ChartRedraw();
  }

//+------------------------------------------------------------------+
//| Compact prediction line — two rows per timeframe, advances y     |
//+------------------------------------------------------------------+
void CGGTHExpert::DisplayPredictionLine(string tf_name,CPredictionData &pred,
                                        CAccuracyTracker &tracker,int x,int &y,int lh)
  {
   string dir    = (pred.prediction > m_current_price) ? "UP  " : "DOWN";
   color  clr    = (pred.prediction > m_current_price) ? InpUpColor : InpDownColor;
   int    digits = _Digits;

//--- Row 1: TF + direction + price + % change
   string r1 = StringFormat("%s  %s  %."+IntegerToString(digits)+"f  (%+.2f%%)",
                             tf_name, dir, pred.prediction, pred.change_pct);
   CreateLabel("MLEA_Pred_"+tf_name, x, y, r1, InpFontSize, clr);
   y += lh;

//--- Row 2: accuracy (indented)
   string r2;
   if(tracker.total_predictions > 0)
      r2 = StringFormat("    Acc: %d/%d  (%.1f%%)",
                        tracker.accurate_predictions,
                        tracker.total_predictions,
                        tracker.accuracy_percent);
   else
      r2 = "    Acc: -- (no data yet)";

   color acc_clr = (tracker.accuracy_percent >= 60) ? clrLimeGreen :
                   (tracker.accuracy_percent >= 50) ? clrYellow : clrRed;
   if(tracker.total_predictions == 0) acc_clr = clrGray;

   CreateLabel("MLEA_Acc_"+tf_name, x, y, r2, InpFontSize-2, acc_clr);
   y += lh + 4;
  }

//+------------------------------------------------------------------+
//| Display error message                                             |
//+------------------------------------------------------------------+
void CGGTHExpert::DisplayError()
  {
   int x = InpXOffset + 8;
   int y = InpYOffset + 8;
   int fs = InpFontSize;

//--- Background
   string bg = "MLEA_BG";
   if(ObjectFind(0, bg) < 0)
     {
      ObjectCreate(0, bg, OBJ_RECTANGLE_LABEL, 0, 0, 0);
      ObjectSetInteger(0, bg, OBJPROP_CORNER,    CORNER_LEFT_UPPER);
      ObjectSetInteger(0, bg, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, bg, OBJPROP_BACK,       false);
      ObjectSetString (0, bg, OBJPROP_TOOLTIP,    "\n");
     }
   ObjectSetInteger(0, bg, OBJPROP_XDISTANCE, InpXOffset);
   ObjectSetInteger(0, bg, OBJPROP_YDISTANCE, InpYOffset);
   ObjectSetInteger(0, bg, OBJPROP_XSIZE,     fs * 80);
   ObjectSetInteger(0, bg, OBJPROP_YSIZE,     fs * 5);
   ObjectSetInteger(0, bg, OBJPROP_BGCOLOR,   C'10,14,28');
   ObjectSetInteger(0, bg, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, bg, OBJPROP_COLOR,     C'45,75,160');
   ObjectSetInteger(0, bg, OBJPROP_WIDTH,     2);
   ObjectSetInteger(0, bg, OBJPROP_ZORDER,    0);

   CreateLabel("MLEA_Error1", x, y,
               "GGTH PREDICTOR v"+EA_VERSION_STR+" | Waiting for ML data...",
               fs, clrOrange);
   CreateLabel("MLEA_Error2", x, y + fs + 10,
               "Run: python unified_predictor_v9.py predict-multitf --symbol "+m_symbol,
               fs-2, clrGray);

   ChartRedraw();
  }

//+------------------------------------------------------------------+
//| Create label helper                                               |
//+------------------------------------------------------------------+
void CGGTHExpert::CreateLabel(string name,int x,int y,string text,
                               int font_size,color clr)
  {
   if(ObjectFind(0,name)<0)
     {
      ObjectCreate(0,name,OBJ_LABEL,0,0,0);
      ObjectSetInteger(0,name,OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(0,name,OBJPROP_ANCHOR,ANCHOR_LEFT_UPPER);
     }

   ObjectSetInteger(0,name,OBJPROP_XDISTANCE,x);
   ObjectSetInteger(0,name,OBJPROP_YDISTANCE,y);
   ObjectSetString(0,name,OBJPROP_TEXT,text);
   ObjectSetInteger(0,name,OBJPROP_FONTSIZE,font_size);
   ObjectSetInteger(0,name,OBJPROP_COLOR,clr);
   ObjectSetString(0,name,OBJPROP_FONT,"Courier New");
   ObjectSetInteger(0,name,OBJPROP_ZORDER,1);
   ObjectSetInteger(0,name,OBJPROP_BACK,false);
  }

//+------------------------------------------------------------------+
//| Save accuracy data                                                |
//+------------------------------------------------------------------+
void CGGTHExpert::SaveAccuracyData()
  {
   string filename="accuracy_"+m_symbol+"_v8.dat";
   int handle=FileOpen(filename,FILE_WRITE|FILE_BIN);

   if(handle!=INVALID_HANDLE)
     {
      FileWriteInteger(handle,m_tracker_1H.total_predictions);
      FileWriteInteger(handle,m_tracker_1H.accurate_predictions);
      FileWriteInteger(handle,m_tracker_4H.total_predictions);
      FileWriteInteger(handle,m_tracker_4H.accurate_predictions);
      FileWriteInteger(handle,m_tracker_1D.total_predictions);
      FileWriteInteger(handle,m_tracker_1D.accurate_predictions);
      FileClose(handle);

      if(InpShowDebug)
         Print("[SAVE] Accuracy data saved");
     }
  }

//+------------------------------------------------------------------+
//| Load accuracy data                                                |
//+------------------------------------------------------------------+
void CGGTHExpert::LoadAccuracyData()
  {
   string filename="accuracy_"+m_symbol+"_v8.dat";
   int handle=FileOpen(filename,FILE_READ|FILE_BIN);

   if(handle!=INVALID_HANDLE)
     {
      m_tracker_1H.total_predictions=FileReadInteger(handle);
      m_tracker_1H.accurate_predictions=FileReadInteger(handle);
      if(m_tracker_1H.total_predictions>0)
         m_tracker_1H.accuracy_percent=
            (double)m_tracker_1H.accurate_predictions/
            m_tracker_1H.total_predictions*100.0;

      m_tracker_4H.total_predictions=FileReadInteger(handle);
      m_tracker_4H.accurate_predictions=FileReadInteger(handle);
      if(m_tracker_4H.total_predictions>0)
         m_tracker_4H.accuracy_percent=
            (double)m_tracker_4H.accurate_predictions/
            m_tracker_4H.total_predictions*100.0;

      m_tracker_1D.total_predictions=FileReadInteger(handle);
      m_tracker_1D.accurate_predictions=FileReadInteger(handle);
      if(m_tracker_1D.total_predictions>0)
         m_tracker_1D.accuracy_percent=
            (double)m_tracker_1D.accurate_predictions/
            m_tracker_1D.total_predictions*100.0;

      FileClose(handle);
      Print("[LOAD] Historical accuracy data loaded");
     }
  }

//+------------------------------------------------------------------+
//| Initialize adaptive state to defaults from inputs                 |
//+------------------------------------------------------------------+
void CGGTHExpert::InitAdaptiveState()
  {
   m_adaptive.min_pred_pips     = (double)InpMinPredictionPips;
   m_adaptive.lot_multiplier    = 1.0;
   m_adaptive.rsi_overbought    = InpRSIOverbought;
   m_adaptive.rsi_oversold      = InpRSIOversold;
   m_adaptive.win_rate          = 0.5;
   m_adaptive.profit_factor     = 1.0;
   m_adaptive.avg_win           = 0.0;
   m_adaptive.avg_loss          = 0.0;
   m_adaptive.kelly_fraction    = 0.0;
   m_adaptive.trades_since_last_adapt = 0;
   m_adaptive.total_adaptations = 0;
   m_adaptive.consecutive_losses= 0;
   m_adaptive.history_head      = 0;
   m_adaptive.history_size      = 0;

   for(int i=0; i<MAX_OPEN_TRACKING; i++)
      m_open_tracking[i].used=false;

//--- v1.14: clean campaign state on init
   ResetCampaignState();

   Print("[INIT] Adaptive learning state initialised (defaults from inputs)");
  }

//+------------------------------------------------------------------+
//| Reset campaign aggregator (v1.14)                                 |
//+------------------------------------------------------------------+
void CGGTHExpert::ResetCampaignState()
  {
   m_campaign.active           = false;
   m_campaign.primary_pos_id   = 0;
   m_campaign.start_time       = 0;
   m_campaign.was_buy          = false;
   m_campaign.pred_change_pct  = 0.0;
   m_campaign.pred_pips        = 0.0;
   m_campaign.rsi_at_entry     = 0.0;
   m_campaign.accumulated_pl   = 0.0;
   m_campaign.legs_total       = 0;
   m_campaign.legs_closed      = 0;
  }

//+------------------------------------------------------------------+
//| Begin a new campaign — called from RecordTradeEntry on primaries  |
//+------------------------------------------------------------------+
void CGGTHExpert::BeginCampaign(ulong position_id,bool is_buy,
                                 double pred_change_pct,double pred_pips,
                                 double rsi)
  {
//--- Defensive: if a campaign was somehow left active (shouldn't happen
//    under FIFO mode), force-finalize whatever P&L it accumulated before
//    starting a new one. Better to record a partial campaign than silently
//    leak state across campaigns.
   if(m_campaign.active)
     {
      Print("[CAMPAIGN] WARN: previous campaign was still active when new "
            "primary entered. Force-finalizing with accumulated_pl=",
            DoubleToString(m_campaign.accumulated_pl,2));
      FinalizeCampaign();
     }

   m_campaign.active           = true;
   m_campaign.primary_pos_id   = position_id;
   m_campaign.start_time       = TimeCurrent();
   m_campaign.was_buy          = is_buy;
   m_campaign.pred_change_pct  = pred_change_pct;
   m_campaign.pred_pips        = pred_pips;
   m_campaign.rsi_at_entry     = rsi;
   m_campaign.accumulated_pl   = 0.0;
   m_campaign.legs_total       = 1;     // primary leg counts as 1
   m_campaign.legs_closed      = 0;

   if(InpShowAdaptiveDebug)
      Print("[CAMPAIGN] Started: pos=",position_id," dir=",(is_buy?"BUY":"SELL"),
            " predPips=",DoubleToString(pred_pips,1));
  }

//+------------------------------------------------------------------+
//| Register an averaging-leg fill against the active campaign        |
//+------------------------------------------------------------------+
void CGGTHExpert::RegisterAveragingLeg()
  {
   if(!m_campaign.active)
     {
      //--- This can happen if averaging was triggered on a primary that
      //--- was placed before adaptive learning was enabled. We treat the
      //--- whole thing as orphan (per-leg fallback in ProcessClosedTrade).
      return;
     }
   m_campaign.legs_total++;
   if(InpShowAdaptiveDebug)
      Print("[CAMPAIGN] Averaging leg ",m_campaign.legs_total-1,
            " registered (legs_total=",m_campaign.legs_total,")");
  }

//+------------------------------------------------------------------+
//| Write the active campaign to history and reset                    |
//|                                                                   |
//| Behaviour change vs v1.13:                                        |
//|   Previously each closing deal wrote its OWN history entry, so a  |
//|   3-leg averaging campaign that netted +$5 would write 3 records  |
//|   (often a mix of winners and losers from individual legs). The   |
//|   computed win_rate / profit_factor were therefore averages of    |
//|   leg-level P&L, not strategy-level outcomes.                     |
//|                                                                   |
//|   v1.14 writes a SINGLE record per campaign with the summed P&L   |
//|   and the primary entry's context. win_rate now answers "did      |
//|   THIS thesis make money", which is the question the adaptive    |
//|   learner should be optimising.                                   |
//+------------------------------------------------------------------+
void CGGTHExpert::FinalizeCampaign()
  {
   if(!m_campaign.active) return;

   int idx = m_adaptive.history_head;
   m_adaptive.history[idx].position_id     = m_campaign.primary_pos_id;
   m_adaptive.history[idx].open_time       = m_campaign.start_time;
   m_adaptive.history[idx].close_time      = TimeCurrent();
   m_adaptive.history[idx].profit          = m_campaign.accumulated_pl;
   m_adaptive.history[idx].won             = (m_campaign.accumulated_pl > 0);
   m_adaptive.history[idx].pred_change_pct = m_campaign.pred_change_pct;
   m_adaptive.history[idx].pred_pips       = m_campaign.pred_pips;
   m_adaptive.history[idx].rsi_at_entry    = m_campaign.rsi_at_entry;
   m_adaptive.history[idx].was_buy         = m_campaign.was_buy;
   m_adaptive.history[idx].used            = true;

//--- Advance circular head
   m_adaptive.history_head = (m_adaptive.history_head + 1) % MAX_TRADE_HISTORY;
   if(m_adaptive.history_size < MAX_TRADE_HISTORY)
      m_adaptive.history_size++;

//--- Track consecutive losses at CAMPAIGN level (not leg level)
   if(m_campaign.accumulated_pl > 0)
      m_adaptive.consecutive_losses=0;
   else
      m_adaptive.consecutive_losses++;

   m_adaptive.trades_since_last_adapt++;

   if(InpShowAdaptiveDebug)
      Print("[CAMPAIGN] Finalized: pos=",m_campaign.primary_pos_id,
            " legs=",m_campaign.legs_total,
            " total_pl=",DoubleToString(m_campaign.accumulated_pl,2),
            " | ConsecLoss: ",m_adaptive.consecutive_losses,
            " | CampaignsSinceLast: ",m_adaptive.trades_since_last_adapt);

//--- Adapt if we've accumulated enough campaigns
   if(m_adaptive.trades_since_last_adapt >= InpAdaptEveryN)
      AdaptParameters();

//--- Reset for next campaign
   ResetCampaignState();
  }

//+------------------------------------------------------------------+
//| Record conditions at trade entry                                   |
//+------------------------------------------------------------------+
void CGGTHExpert::RecordTradeEntry(ulong position_id,bool is_buy,
                                    double pred_change_pct,double pred_pips,
                                    double rsi)
  {
   if(!InpEnableAdaptiveLearning || position_id==0) return;

//--- Find free slot in open-tracking array (used for orphan-fallback path
//    only — primary attribution now goes through the campaign aggregator)
   bool slot_taken=false;
   for(int i=0; i<MAX_OPEN_TRACKING; i++)
     {
      if(!m_open_tracking[i].used)
        {
         m_open_tracking[i].position_id     = position_id;
         m_open_tracking[i].pred_change_pct = pred_change_pct;
         m_open_tracking[i].pred_pips       = pred_pips;
         m_open_tracking[i].rsi_at_entry    = rsi;
         m_open_tracking[i].was_buy         = is_buy;
         m_open_tracking[i].used            = true;
         slot_taken=true;
         if(InpShowAdaptiveDebug)
            Print("[ENTRY] Recorded entry for position_id ",position_id,
                  " | predPips:",DoubleToString(pred_pips,1),
                  " | RSI:",DoubleToString(rsi,1));
         break;
        }
     }
   if(!slot_taken)
      Print("[WARN] Adaptive: open tracking array full - entry not recorded");

//--- v1.14: begin a new campaign for this primary entry. Averaging legs
//    don't pass through here; they hit RegisterAveragingLeg from inside
//    ExecuteAveragingOrder. RecordTradeEntry is only called from the
//    primary BUY/SELL success branches in CheckForTradeSignal.
   BeginCampaign(position_id,is_buy,pred_change_pct,pred_pips,rsi);
  }

//+------------------------------------------------------------------+
//| Called from OnTradeTransaction when a position closes             |
//|                                                                   |
//| v1.14 routing:                                                    |
//|   - If a campaign is active, accumulate this leg's P&L.           |
//|     When CountOpenPositions() drops to 0, finalize.               |
//|   - If no campaign is active (orphan close — e.g. position was    |
//|     placed before adaptive learning was enabled, or restart       |
//|     between primary entry and close), fall back to the OLD per-   |
//|     leg behaviour so we still record SOMETHING in history.        |
//+------------------------------------------------------------------+
void CGGTHExpert::ProcessClosedTrade(ulong position_id,double profit)
  {
   if(!InpEnableAdaptiveLearning) return;

//--- Free the open-tracking slot if present (always, regardless of path)
   bool found_in_tracking=false;
   COpenTradeEntry entry;
   ZeroMemory(entry);
   for(int i=0; i<MAX_OPEN_TRACKING; i++)
     {
      if(m_open_tracking[i].used && m_open_tracking[i].position_id==position_id)
        {
         entry = m_open_tracking[i];
         m_open_tracking[i].used=false;
         found_in_tracking=true;
         break;
        }
     }

//--- Always write the per-leg outcome to the Python feedback file —
//--- the Python ensemble weight learner consumes leg-level outcomes
//--- and is downstream of this whole campaign decision.
//---
//--- v1.15 fix: prior implementation had two concurrency hazards:
//---  (1) Write opened with FILE_WRITE only — no FILE_SHARE_READ. If the
//---      Python predictor was reading at the same instant, MT5 would
//---      return INVALID_HANDLE and the outcome would be silently lost.
//---  (2) Truncate-and-rewrite with no atomicity. A crash mid-write would
//---      leave the file empty or partial; the next Python read would
//---      then either fail to parse or reset its state to "[]".
//--- The fix below: read the existing array (with FILE_SHARE_READ so we
//--- never block Python), build the new content in memory, write to a
//--- .tmp sibling, then atomic-rename via FileMove(FILE_REWRITE) which
//--- on Windows is atomic for same-volume renames. Python is also
//--- updated to retry-once on parse failure as a belt-and-braces measure.
  {
   string outf      = m_symbol + "_trade_outcomes.json";
   string outf_tmp  = m_symbol + "_trade_outcomes.json.tmp";
   string existing  = "[]";

   //--- Read existing array (share-read so Python isn't blocked)
   int rh = FileOpen(outf, FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(rh != INVALID_HANDLE)
     {
      existing = "";
      while(!FileIsEnding(rh)) existing += FileReadString(rh);
      FileClose(rh);
      if(StringLen(existing) < 3) existing = "[]";
     }

   //--- Build the new record. position_id is the join key against the
   //--- entries CSV; close_time is informational.
   string rec = StringFormat(
      "{\"position_id\":%I64u,\"profit\":%.2f,\"actual_close\":%.5f,\"close_time\":\"%s\"}",
      position_id, profit, m_current_price,
      TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES));

   //--- Splice the record in before the closing bracket. Tolerates an
   //--- empty array "[]" by detecting bracket position.
   int bracket = StringFind(existing, "]", 0);
   string newjson = (bracket > 1)
      ? StringSubstr(existing, 0, bracket) + "," + rec + "]"
      : "[" + rec + "]";

   //--- Write the new content to a temporary file. If this fails or the
   //--- process crashes here, the original outf is untouched.
   //--- FILE_SHARE_READ on the writer too — even the tmp briefly exists
   //--- and we don't want to break Python if it's polling for tmp files.
   int wh = FileOpen(outf_tmp,
                     FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(wh == INVALID_HANDLE)
     {
      Print("[OUTCOMES] ERROR: cannot open tmp file ",outf_tmp,
            " for write: ",GetLastError(),
            ". Outcome NOT recorded for pos=",position_id);
     }
   else
     {
      FileWriteString(wh, newjson);
      FileClose(wh);

      //--- Atomic rename — FILE_REWRITE allows overwriting existing
      //--- destination. After this point the new file IS the live file.
      //--- If FileMove fails (rare — disk full, perms), we leave the
      //--- tmp behind so a later run (or the user) can recover from it.
      if(!FileMove(outf_tmp, 0, outf, FILE_REWRITE))
        {
         Print("[OUTCOMES] ERROR: FileMove failed: ",GetLastError(),
               ". Tmp file left at ",outf_tmp," for recovery.");
        }
     }
  }

//--- v1.14: route adaptive learning bookkeeping through the campaign aggregator
   if(m_campaign.active)
     {
      m_campaign.accumulated_pl += profit;
      m_campaign.legs_closed++;

      if(InpShowAdaptiveDebug)
         Print("[CAMPAIGN] Leg closed: pos=",position_id,
               " leg_pl=",DoubleToString(profit,2),
               " accumulated=",DoubleToString(m_campaign.accumulated_pl,2),
               " legs_closed=",m_campaign.legs_closed,"/",m_campaign.legs_total);

      //--- Are all legs closed? CountOpenPositions reflects post-close state
      //    so when this drops to zero the entire campaign is flat.
      if(CountOpenPositions()==0)
         FinalizeCampaign();
      return;
     }

//--- Orphan path — no campaign in flight. Record a single per-leg history
//    entry so adaptive learning gets SOME signal (but loses entry context
//    if the open-tracking slot wasn't found either).
   int idx = m_adaptive.history_head;
   m_adaptive.history[idx].position_id     = position_id;
   m_adaptive.history[idx].profit          = profit;
   m_adaptive.history[idx].won             = (profit>0);
   m_adaptive.history[idx].close_time      = TimeCurrent();
   m_adaptive.history[idx].used            = true;

   if(found_in_tracking)
     {
      m_adaptive.history[idx].pred_change_pct = entry.pred_change_pct;
      m_adaptive.history[idx].pred_pips       = entry.pred_pips;
      m_adaptive.history[idx].rsi_at_entry    = entry.rsi_at_entry;
      m_adaptive.history[idx].was_buy         = entry.was_buy;
     }

   m_adaptive.history_head = (m_adaptive.history_head + 1) % MAX_TRADE_HISTORY;
   if(m_adaptive.history_size < MAX_TRADE_HISTORY)
      m_adaptive.history_size++;

   if(profit>0) m_adaptive.consecutive_losses=0;
   else         m_adaptive.consecutive_losses++;
   m_adaptive.trades_since_last_adapt++;

   if(InpShowAdaptiveDebug)
      Print("[ORPHAN] Closed (no campaign tracking) | P/L: ",DoubleToString(profit,2),
            " | ConsecLoss: ",m_adaptive.consecutive_losses);

   if(m_adaptive.trades_since_last_adapt >= InpAdaptEveryN)
      AdaptParameters();
  }

//+------------------------------------------------------------------+
//| Core adaptation algorithm                                         |
//+------------------------------------------------------------------+
void CGGTHExpert::AdaptParameters()
  {
   if(m_adaptive.history_size < 3) return; // need at least 3 trades

   double win_rate=0, profit_factor=0, avg_win=0, avg_loss=0;
   ComputeRollingMetrics(win_rate,profit_factor,avg_win,avg_loss);

   m_adaptive.win_rate      = win_rate;
   m_adaptive.profit_factor = profit_factor;
   m_adaptive.avg_win       = avg_win;
   m_adaptive.avg_loss      = avg_loss;

   double kelly = ComputeKellyFraction(win_rate,avg_win,avg_loss);
   m_adaptive.kelly_fraction = kelly;

   double rate = InpAdaptRate;

   //--- 1) Adapt min_pred_pips ----------------------------------------
   //    Tighten (raise) when losing to demand stronger signals.
   //    Loosen (lower) when consistently winning.
   double target_pred_pips = m_adaptive.min_pred_pips;
   if(win_rate < 0.40)
      target_pred_pips = m_adaptive.min_pred_pips * (1.0 + rate);
   else if(win_rate >= 0.60 && profit_factor >= 1.5)
      target_pred_pips = m_adaptive.min_pred_pips * (1.0 - rate * 0.5);

   m_adaptive.min_pred_pips = MathMax(InpAdaptMinPredFloor,
                              MathMin(InpAdaptMinPredCeil, target_pred_pips));

   //--- 2) Adapt lot_multiplier via half-Kelly -----------------------
   //    Kelly fraction clipped to [0, 0.5]; multiplier = kelly * 2
   double kelly_clamped = MathMax(0.0, MathMin(0.5, kelly));
   double kelly_target  = kelly_clamped * 2.0;  // maps [0,0.5] -> [0,1]
   if(kelly_target < 0.25) kelly_target = 0.25; // minimum participation

   // Smooth towards kelly target using learning rate
   m_adaptive.lot_multiplier += rate * (kelly_target - m_adaptive.lot_multiplier);
   m_adaptive.lot_multiplier  = MathMax(InpAdaptLotMultFloor,
                                MathMin(InpAdaptLotMultCeil, m_adaptive.lot_multiplier));

   //--- 3) Adapt RSI levels -------------------------------------------
   //    Tighten (more restrictive) when win rate is poor.
   //    Relax when strong.
   if(win_rate < 0.40)
     {
      // Tighten: move OB down, OS up -> fewer signals pass
      m_adaptive.rsi_overbought = MathMax(55.0, m_adaptive.rsi_overbought - rate * 5.0);
      m_adaptive.rsi_oversold   = MathMin(45.0, m_adaptive.rsi_oversold   + rate * 5.0);
     }
   else if(win_rate >= 0.60 && profit_factor >= 1.5)
     {
      // Relax: widen RSI window
      m_adaptive.rsi_overbought = MathMin(80.0, m_adaptive.rsi_overbought + rate * 3.0);
      m_adaptive.rsi_oversold   = MathMax(20.0, m_adaptive.rsi_oversold   - rate * 3.0);
     }

   m_adaptive.trades_since_last_adapt = 0;
   m_adaptive.total_adaptations++;

   Print("[ADAPT] UPDATE #",m_adaptive.total_adaptations);
   Print("   WinRate: ",DoubleToString(win_rate*100,1),"%",
         " | PF: ",DoubleToString(profit_factor,2),
         " | Kelly: ",DoubleToString(kelly*100,1),"%");
   Print("   MinPredPips: ",DoubleToString(m_adaptive.min_pred_pips,1),
         " | LotMult: ",DoubleToString(m_adaptive.lot_multiplier,3),
         " | RSI OB/OS: ",DoubleToString(m_adaptive.rsi_overbought,1),
         "/",DoubleToString(m_adaptive.rsi_oversold,1));

//--- Save immediately so state is not lost if EA crashes
   SaveAdaptiveState();
  }

//+------------------------------------------------------------------+
//| Compute rolling performance metrics over last InpAdaptLookback   |
//+------------------------------------------------------------------+
void CGGTHExpert::ComputeRollingMetrics(double &win_rate,double &profit_factor,
                                         double &avg_win,double &avg_loss)
  {
   int window = MathMin(InpAdaptLookback, m_adaptive.history_size);
   if(window==0) { win_rate=0.5; profit_factor=1.0; avg_win=0; avg_loss=0; return; }

   int wins=0;
   double gross_win=0, gross_loss=0;

//--- Walk backwards through circular buffer
   for(int k=0; k<window; k++)
     {
      int idx = (m_adaptive.history_head - 1 - k + MAX_TRADE_HISTORY) % MAX_TRADE_HISTORY;
      if(!m_adaptive.history[idx].used) continue;

      double p = m_adaptive.history[idx].profit;
      if(p > 0) { wins++; gross_win  += p; }
      else       {         gross_loss += MathAbs(p); }
     }

   win_rate      = (double)wins / window;
   profit_factor = (gross_loss > 0) ? gross_win / gross_loss : (gross_win > 0 ? 10.0 : 1.0);
   avg_win       = (wins > 0) ? gross_win  / wins         : 0.0;
   avg_loss      = (window - wins > 0) ? gross_loss / (window - wins) : 0.0;
  }

//+------------------------------------------------------------------+
//| Half-Kelly fraction: f = p - (1-p)/b  where b = avg_win/avg_loss |
//+------------------------------------------------------------------+
double CGGTHExpert::ComputeKellyFraction(double win_rate,double avg_win,double avg_loss)
  {
   if(avg_loss <= 0 || avg_win <= 0) return 0.0;
   double b = avg_win / avg_loss;          // payoff ratio
   double f = win_rate - (1.0 - win_rate) / b;
   return MathMax(0.0, f * 0.5);           // half-Kelly for safety
  }

//+------------------------------------------------------------------+
//| OnTradeTransaction - fires on every deal (entry and exit)        |
//+------------------------------------------------------------------+
void CGGTHExpert::OnTradeTransaction(const MqlTradeTransaction &trans,
                                      const MqlTradeRequest &request,
                                      const MqlTradeResult &result)
  {
//--- v1.13: this handler now serves BOTH adaptive learning AND the trade
//    journal. We can't early-exit on InpEnableAdaptiveLearning anymore —
//    the journal must record exits regardless. Each downstream branch
//    is gated by its own input flag.
   if(!InpEnableAdaptiveLearning && !InpEnableTradeJournal) return;

//--- We only care about completed deals on our symbol
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(trans.symbol != m_symbol) return;

   ulong deal_ticket = trans.deal;
   if(deal_ticket == 0) return;

//--- Select the deal from history
   if(!HistoryDealSelect(deal_ticket)) return;

   long deal_entry = HistoryDealGetInteger(deal_ticket, DEAL_ENTRY);

//--- Only process closing deals (DEAL_ENTRY_OUT or DEAL_ENTRY_INOUT)
   if(deal_entry != DEAL_ENTRY_OUT && deal_entry != DEAL_ENTRY_INOUT) return;

   double   raw_profit  = HistoryDealGetDouble(deal_ticket,  DEAL_PROFIT);
   double   swap        = HistoryDealGetDouble(deal_ticket,  DEAL_SWAP);
   double   commission  = HistoryDealGetDouble(deal_ticket,  DEAL_COMMISSION);
   double   total_pl    = raw_profit + swap + commission;
   double   close_price = HistoryDealGetDouble(deal_ticket,  DEAL_PRICE);
   long     deal_reason = HistoryDealGetInteger(deal_ticket, DEAL_REASON);
   ulong    position_id = HistoryDealGetInteger(deal_ticket, DEAL_POSITION_ID);

//--- Adaptive learning hook (unchanged behaviour)
   if(InpEnableAdaptiveLearning)
      ProcessClosedTrade(position_id, total_pl);

//--- Trade journal exit row (v1.13, refined v1.15)
//    Resolve the close reason in this priority order:
//      1. DEAL_REASON if it's TP/SL/SO/MOBILE/etc. — broker-side authoritative
//      2. Per-ticket pending-close map (v1.15) — survives same-tick races
//      3. Legacy m_pending_close_reason — fallback for any non-mapped paths
//    The per-ticket consume() empties the slot atomically so it can't be
//    double-counted by a follow-up deal on the same position.
   if(InpEnableTradeJournal)
     {
      string reason_str = DealReasonToString(deal_reason);
      if(reason_str=="EXPERT")
        {
         string ticket_reason = ConsumePendingClose(position_id);
         if(StringLen(ticket_reason) > 0)
            reason_str = "EXPERT:" + ticket_reason;
         else if(StringLen(m_pending_close_reason) > 0)
            reason_str = "EXPERT:" + m_pending_close_reason;
        }
      WriteJournalExit(position_id,deal_ticket,close_price,
                       raw_profit,swap,commission,reason_str);
     }
  }

//+------------------------------------------------------------------+
//| Save adaptive state to file                                       |
//+------------------------------------------------------------------+
void CGGTHExpert::SaveAdaptiveState()
  {
   string filename="adaptive_"+m_symbol+"_v1.dat";
   int h=FileOpen(filename,FILE_WRITE|FILE_BIN);
   if(h==INVALID_HANDLE)
     {
      Print("[ERROR] Adaptive: could not open ",filename," for writing");
      return;
     }

//--- Write header version tag (v1.14: bumped to 20260002 for campaign state)
   FileWriteInteger(h,20260002);

//--- Write adapted parameters
   FileWriteDouble(h,m_adaptive.min_pred_pips);
   FileWriteDouble(h,m_adaptive.lot_multiplier);
   FileWriteDouble(h,m_adaptive.rsi_overbought);
   FileWriteDouble(h,m_adaptive.rsi_oversold);

//--- Write metrics
   FileWriteDouble(h,m_adaptive.win_rate);
   FileWriteDouble(h,m_adaptive.profit_factor);
   FileWriteDouble(h,m_adaptive.avg_win);
   FileWriteDouble(h,m_adaptive.avg_loss);
   FileWriteDouble(h,m_adaptive.kelly_fraction);

//--- Write counters
   FileWriteInteger(h,m_adaptive.total_adaptations);
   FileWriteInteger(h,m_adaptive.consecutive_losses);
   FileWriteInteger(h,m_adaptive.history_head);
   FileWriteInteger(h,m_adaptive.history_size);

//--- Write history records
   for(int i=0; i<MAX_TRADE_HISTORY; i++)
     {
      FileWriteLong(h,(long)m_adaptive.history[i].position_id);
      FileWriteLong(h,(long)m_adaptive.history[i].close_time);
      FileWriteDouble(h,m_adaptive.history[i].profit);
      FileWriteDouble(h,m_adaptive.history[i].pred_change_pct);
      FileWriteDouble(h,m_adaptive.history[i].pred_pips);
      FileWriteDouble(h,m_adaptive.history[i].rsi_at_entry);
      FileWriteInteger(h,m_adaptive.history[i].was_buy ? 1 : 0);
      FileWriteInteger(h,m_adaptive.history[i].won     ? 1 : 0);
      FileWriteInteger(h,m_adaptive.history[i].used    ? 1 : 0);
     }

//--- v1.14 (file format v2): write campaign state so it survives EA restart
//    mid-campaign. Without this, a recompile or terminal restart while a
//    primary + averaging legs are open would reset the campaign aggregator
//    and the eventual closes would fall through to the orphan path.
   FileWriteInteger(h,m_campaign.active ? 1 : 0);
   FileWriteLong   (h,(long)m_campaign.primary_pos_id);
   FileWriteLong   (h,(long)m_campaign.start_time);
   FileWriteInteger(h,m_campaign.was_buy ? 1 : 0);
   FileWriteDouble (h,m_campaign.pred_change_pct);
   FileWriteDouble (h,m_campaign.pred_pips);
   FileWriteDouble (h,m_campaign.rsi_at_entry);
   FileWriteDouble (h,m_campaign.accumulated_pl);
   FileWriteInteger(h,m_campaign.legs_total);
   FileWriteInteger(h,m_campaign.legs_closed);

   FileClose(h);
   if(InpShowAdaptiveDebug)
      Print("[SAVE] Adaptive state saved (",m_adaptive.history_size," campaigns)");
  }

//+------------------------------------------------------------------+
//| Load adaptive state from file                                     |
//+------------------------------------------------------------------+
void CGGTHExpert::LoadAdaptiveState()
  {
   string filename="adaptive_"+m_symbol+"_v1.dat";
   int h=FileOpen(filename,FILE_READ|FILE_BIN);
   if(h==INVALID_HANDLE)
     {
      Print("[INFO] Adaptive: no saved state found - using input defaults");
      return;
     }

   int version=FileReadInteger(h);
   //--- v1.14: accept both v1 (legacy, no campaign block) and v2 formats.
   //    Anything else is a version we don't know how to read → bail.
   if(version!=20260001 && version!=20260002)
     {
      FileClose(h);
      Print("[WARN] Adaptive: state file version mismatch (got ",version,
            ") - using defaults");
      return;
     }

   m_adaptive.min_pred_pips  = FileReadDouble(h);
   m_adaptive.lot_multiplier = FileReadDouble(h);
   m_adaptive.rsi_overbought = FileReadDouble(h);
   m_adaptive.rsi_oversold   = FileReadDouble(h);
   m_adaptive.win_rate       = FileReadDouble(h);
   m_adaptive.profit_factor  = FileReadDouble(h);
   m_adaptive.avg_win        = FileReadDouble(h);
   m_adaptive.avg_loss       = FileReadDouble(h);
   m_adaptive.kelly_fraction = FileReadDouble(h);
   m_adaptive.total_adaptations  = FileReadInteger(h);
   m_adaptive.consecutive_losses = FileReadInteger(h);
   m_adaptive.history_head   = FileReadInteger(h);
   m_adaptive.history_size   = FileReadInteger(h);

   for(int i=0; i<MAX_TRADE_HISTORY; i++)
     {
      m_adaptive.history[i].position_id     = (ulong)FileReadLong(h);
      m_adaptive.history[i].close_time      = (datetime)FileReadLong(h);
      m_adaptive.history[i].profit          = FileReadDouble(h);
      m_adaptive.history[i].pred_change_pct = FileReadDouble(h);
      m_adaptive.history[i].pred_pips       = FileReadDouble(h);
      m_adaptive.history[i].rsi_at_entry    = FileReadDouble(h);
      m_adaptive.history[i].was_buy         = (FileReadInteger(h)==1);
      m_adaptive.history[i].won             = (FileReadInteger(h)==1);
      m_adaptive.history[i].used            = (FileReadInteger(h)==1);
     }

//--- v2-only: read campaign state, else leave defaults from ResetCampaignState
   if(version==20260002)
     {
      m_campaign.active          = (FileReadInteger(h)==1);
      m_campaign.primary_pos_id  = (ulong)FileReadLong(h);
      m_campaign.start_time      = (datetime)FileReadLong(h);
      m_campaign.was_buy         = (FileReadInteger(h)==1);
      m_campaign.pred_change_pct = FileReadDouble(h);
      m_campaign.pred_pips       = FileReadDouble(h);
      m_campaign.rsi_at_entry    = FileReadDouble(h);
      m_campaign.accumulated_pl  = FileReadDouble(h);
      m_campaign.legs_total      = FileReadInteger(h);
      m_campaign.legs_closed     = FileReadInteger(h);
     }

   FileClose(h);
   Print("[LOAD] Adaptive state loaded: ",m_adaptive.history_size," campaigns | ",
         m_adaptive.total_adaptations," adaptations | format v",
         (version==20260002?2:1));
   Print("  MinPredPips: ",DoubleToString(m_adaptive.min_pred_pips,1),
         " | LotMult: ",DoubleToString(m_adaptive.lot_multiplier,3),
         " | WinRate: ",DoubleToString(m_adaptive.win_rate*100,1),"%");

   if(m_campaign.active)
      Print("  [CAMPAIGN] Restored active campaign: pos=",m_campaign.primary_pos_id,
            " legs=",m_campaign.legs_total," accumulated=$",
            DoubleToString(m_campaign.accumulated_pl,2));
  }

//+------------------------------------------------------------------+
//| Display adaptive learning state — compact, no box borders        |
//+------------------------------------------------------------------+
void CGGTHExpert::DisplayAdaptiveInfo(int x_pos,int &y_pos,int line_height)
  {
//--- Header
   CreateLabel("MLEA_AdaptHeader", x_pos, y_pos,
               "ADAPTIVE LEARNING", InpFontSize, clrCyan);
   y_pos += line_height;

//--- Win rate / PF / Kelly
   color wr_color = (m_adaptive.win_rate >= 0.55) ? clrLimeGreen :
                    (m_adaptive.win_rate >= 0.40) ? clrYellow : clrRed;
   string wr_str  = StringFormat("WR: %.1f%%  PF: %.2f  Kelly: %.1f%%",
                                  m_adaptive.win_rate * 100,
                                  m_adaptive.profit_factor,
                                  m_adaptive.kelly_fraction * 100);
   CreateLabel("MLEA_AdaptWR", x_pos, y_pos, wr_str, InpFontSize-1, wr_color);
   y_pos += line_height;

//--- Adaptive parameters
   string pp_str = StringFormat("Pips: %.1f  Lots: %.3fx  #adapt: %d",
                                 m_adaptive.min_pred_pips,
                                 m_adaptive.lot_multiplier,
                                 m_adaptive.total_adaptations);
   CreateLabel("MLEA_AdaptPP", x_pos, y_pos, pp_str, InpFontSize-1, clrWhite);
   y_pos += line_height;

//--- RSI levels
   string rsi_str = StringFormat("RSI OB/OS: %.0f / %.0f  Trades: %d",
                                  m_adaptive.rsi_overbought,
                                  m_adaptive.rsi_oversold,
                                  m_adaptive.history_size);
   CreateLabel("MLEA_AdaptRSI", x_pos, y_pos, rsi_str, InpFontSize-1, clrWhite);
   y_pos += line_height;
  }
//+------------------------------------------------------------------+
//| ============== v1.13: Stale-Prediction Watchdog ============== |
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//| Refresh cached watchdog state once per tick                       |
//+------------------------------------------------------------------+
void CGGTHExpert::EvaluateWatchdog()
  {
//--- Reset
   m_watchdog_stale=false;
   m_watchdog_age_sec=-1;
   m_watchdog_reason="";

//--- Strategy-tester / CSV mode: predictions come from a static CSV which
//--- by definition has no live heartbeat — bypass entirely.
   if(InpStrategyTesterMode)
      return;

//--- Master toggle
   if(!InpEnableStaleWatchdog)
      return;

//--- No heartbeat seen yet: depends on fail-closed flag
   if(m_last_updated_utc<=0)
     {
      if(InpFailClosedOnMissingHeartbeat)
        {
         m_watchdog_stale=true;
         m_watchdog_reason="No heartbeat received from Python predictor yet";
        }
      return;   // fail-open default: allow until first heartbeat
     }

//--- Compare current UTC against last heartbeat. TimeGMT() returns absolute
//--- UTC and is independent of broker timezone or DST shifts.
//--- v1.15: utc_now is now long (was (int) cast). At 03:14:08 UTC on
//--- 2038-01-19 a 32-bit signed epoch wraps negative; the long type
//--- carries the watchdog past that boundary cleanly. The age_sec
//--- result is still safely-int-sized because it's just a difference
//--- between two recent timestamps, not the timestamps themselves.
   long utc_now = (long)TimeGMT();
   m_watchdog_age_sec = (int)(utc_now - m_last_updated_utc);

//--- Negative age means the heartbeat is in the future — almost certainly
//--- a clock skew between this terminal and the Python host. Don't block
//--- on this (it would persist until the clocks resync), but log loudly.
   if(m_watchdog_age_sec<-60)
     {
      if(InpShowDebug)
         Print("[WATCHDOG] WARN: heartbeat is ",-m_watchdog_age_sec/60,
               " min in the FUTURE — clock skew between Python host and this terminal?");
      m_watchdog_age_sec=0;
      return;
     }

   int max_sec=InpStalePredictionMaxMinutes*60;
   if(m_watchdog_age_sec>max_sec)
     {
      m_watchdog_stale=true;
      m_watchdog_reason=StringFormat("Python predictor stale: %d min old (limit %d min)",
                                     m_watchdog_age_sec/60,InpStalePredictionMaxMinutes);
     }
  }

//+------------------------------------------------------------------+
//| Single decision point — read by all entry and averaging callers   |
//+------------------------------------------------------------------+
bool CGGTHExpert::IsPredictionStale()
  {
   return m_watchdog_stale;
  }

//+------------------------------------------------------------------+
//| ================== v1.13: Trade Journal ====================== |
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//| Map MT5 DEAL_REASON enum to a short human-readable tag            |
//+------------------------------------------------------------------+
string CGGTHExpert::DealReasonToString(long deal_reason)
  {
   switch((ENUM_DEAL_REASON)deal_reason)
     {
      case DEAL_REASON_CLIENT:    return "MANUAL";       // closed by client (terminal)
      case DEAL_REASON_MOBILE:    return "MANUAL_MOBILE";
      case DEAL_REASON_WEB:       return "MANUAL_WEB";
      case DEAL_REASON_EXPERT:    return "EXPERT";       // closed by EA — caller fills detail
      case DEAL_REASON_SL:        return "SL";
      case DEAL_REASON_TP:        return "TP";
      case DEAL_REASON_SO:        return "STOPOUT";
      case DEAL_REASON_ROLLOVER:  return "ROLLOVER";
      case DEAL_REASON_VMARGIN:   return "VARIATION_MARGIN";
      case DEAL_REASON_SPLIT:     return "SPLIT";
      default:                    return StringFormat("UNKNOWN_%d",(int)deal_reason);
     }
  }

//+------------------------------------------------------------------+
//| Per-ticket pending-close map helpers (v1.15)                     |
//|                                                                   |
//| Replaces the single-string m_pending_close_reason race window.   |
//| See struct CPendingClose definition for full rationale.          |
//+------------------------------------------------------------------+
void CGGTHExpert::ResetPendingCloses()
  {
   for(int i=0; i<MAX_PENDING_CLOSES; i++)
     {
      m_pending_closes[i].used        = false;
      m_pending_closes[i].position_id = 0;
      m_pending_closes[i].reason      = "";
     }
  }

void CGGTHExpert::StampPendingClose(ulong position_id, string reason)
  {
//--- Reuse an existing slot for the same position_id if present (this can
//--- happen if CloseAllPositions retries a previously-failed close on the
//--- same ticket — we want the latest reason, not a duplicate row).
   for(int i=0; i<MAX_PENDING_CLOSES; i++)
     {
      if(m_pending_closes[i].used && m_pending_closes[i].position_id == position_id)
        {
         m_pending_closes[i].reason = reason;
         return;
        }
     }
//--- Otherwise grab the first free slot
   for(int i=0; i<MAX_PENDING_CLOSES; i++)
     {
      if(!m_pending_closes[i].used)
        {
         m_pending_closes[i].position_id = position_id;
         m_pending_closes[i].reason      = reason;
         m_pending_closes[i].used        = true;
         return;
        }
     }
//--- Map is full. This should be impossible in practice (MAX_PENDING_CLOSES
//--- is 50, much larger than any realistic same-tick close batch), but log
//--- loudly because if it ever happens, journal attribution will silently
//--- degrade for whichever position can't be stamped.
   Print("[WARN] Pending-close map full at ",MAX_PENDING_CLOSES,
         " entries — pos=",position_id," reason='",reason,
         "' will fall back to legacy single-string attribution.");
  }

string CGGTHExpert::ConsumePendingClose(ulong position_id)
  {
   for(int i=0; i<MAX_PENDING_CLOSES; i++)
     {
      if(m_pending_closes[i].used && m_pending_closes[i].position_id == position_id)
        {
         string r = m_pending_closes[i].reason;
         m_pending_closes[i].used        = false;
         m_pending_closes[i].position_id = 0;
         m_pending_closes[i].reason      = "";
         return r;
        }
     }
   return "";
  }

//+------------------------------------------------------------------+
//| Write entry row to {symbol}_trade_journal_entries.csv             |
//|                                                                   |
//| Columns (28):                                                     |
//|   timestamp_utc, position_id, symbol, direction, entry_kind,      |
//|   entry_price, lot_size, sl, tp, tf_used,                         |
//|   pred_change_pct, pred_pips, rsi_at_entry,                       |
//|   pred_1h, pred_4h, pred_1d, current_price,                       |
//|   pred_std_1h, pred_std_4h, pred_std_1d,                          |
//|   regime, trade_allowed, watchdog_age_sec,                        |
//|   account_balance, account_equity, free_margin_pct,               |
//|   adapt_lot_mult, adapt_min_pred_pips                             |
//|                                                                   |
//| Header is written exactly once per file. Subsequent runs append.  |
//+------------------------------------------------------------------+
void CGGTHExpert::WriteJournalEntry(ulong position_id,bool is_buy,
                                    double entry_price,double lot_size,
                                    double sl,double tp,
                                    string tf_used,double pred_change_pct,
                                    double pred_pips,double rsi_at_entry,
                                    string entry_kind)
  {
   string filename=m_symbol+"_trade_journal_entries.csv";
   bool   need_header=!FileIsExist(filename);

//--- Open append mode. FILE_TXT|FILE_ANSI keeps the file plain UTF-8 / ASCII
//--- so pandas.read_csv reads it without any encoding hints.
   int h=FileOpen(filename,FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(h==INVALID_HANDLE)
     {
      Print("[JOURNAL] ERROR opening ",filename," for write: ",GetLastError());
      return;
     }
   FileSeek(h,0,SEEK_END);

   if(need_header)
     {
      FileWriteString(h,
        "timestamp_utc,position_id,symbol,direction,entry_kind,"
        "entry_price,lot_size,sl,tp,tf_used,"
        "pred_change_pct,pred_pips,rsi_at_entry,"
        "pred_1h,pred_4h,pred_1d,current_price,"
        "pred_std_1h,pred_std_4h,pred_std_1d,"
        "regime,trade_allowed,watchdog_age_sec,"
        "account_balance,account_equity,free_margin_pct,"
        "adapt_lot_mult,adapt_min_pred_pips\n");
     }

//--- Compose row — every field must produce a deterministic, parser-safe
//--- value (no commas inside any cell, no embedded newlines).
   string ts=TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS);
   StringReplace(ts,".","-");   // 2026.05.04 12:34:56 -> 2026-05-04 12:34:56

   double balance=AccountInfoDouble(ACCOUNT_BALANCE);
   double equity =AccountInfoDouble(ACCOUNT_EQUITY);
   double freemar=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double freepct=(equity>0) ? (freemar/equity*100.0) : 0.0;

   string row=StringFormat(
      "%s,%I64u,%s,%s,%s,"
      "%.5f,%.2f,%.5f,%.5f,%s,"
      "%.4f,%.2f,%.2f,"
      "%.5f,%.5f,%.5f,%.5f,"
      "%.5f,%.5f,%.5f,"
      "%s,%s,%d,"
      "%.2f,%.2f,%.2f,"
      "%.3f,%.2f\n",
      ts, position_id, m_symbol, (is_buy?"BUY":"SELL"), entry_kind,
      entry_price, lot_size, sl, tp, tf_used,
      pred_change_pct, pred_pips, rsi_at_entry,
      m_pred_1H.prediction, m_pred_4H.prediction, m_pred_1D.prediction, m_current_price,
      m_pred_1H.ensemble_std, m_pred_4H.ensemble_std, m_pred_1D.ensemble_std,
      m_status_regime, (m_trade_allowed?"true":"false"), m_watchdog_age_sec,
      balance, equity, freepct,
      m_adaptive.lot_multiplier, m_adaptive.min_pred_pips
   );

   FileWriteString(h,row);
   FileClose(h);

   if(InpShowJournalDebug)
      Print("[JOURNAL] Entry written: pos=",position_id," kind=",entry_kind,
            " dir=",(is_buy?"BUY":"SELL")," tf=",tf_used);
  }

//+------------------------------------------------------------------+
//| Write exit row to {symbol}_trade_journal_exits.csv                |
//|                                                                   |
//| Columns (10):                                                     |
//|   timestamp_utc, position_id, deal_ticket, symbol,                |
//|   close_price, profit, swap, commission, total_pl, exit_reason    |
//|                                                                   |
//| Position-id is the JOIN key against the entries CSV. A single     |
//| campaign with N averaging legs produces N entry rows + N exit     |
//| rows; pandas.merge(entries, exits, on='position_id') reconstructs |
//| each leg's full lifecycle.                                        |
//+------------------------------------------------------------------+
void CGGTHExpert::WriteJournalExit(ulong position_id,ulong deal_ticket,
                                   double close_price,double profit,
                                   double swap,double commission,
                                   string exit_reason)
  {
   string filename=m_symbol+"_trade_journal_exits.csv";
   bool   need_header=!FileIsExist(filename);

   int h=FileOpen(filename,FILE_READ|FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(h==INVALID_HANDLE)
     {
      Print("[JOURNAL] ERROR opening ",filename," for write: ",GetLastError());
      return;
     }
   FileSeek(h,0,SEEK_END);

   if(need_header)
     {
      FileWriteString(h,
        "timestamp_utc,position_id,deal_ticket,symbol,"
        "close_price,profit,swap,commission,total_pl,exit_reason\n");
     }

   string ts=TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS);
   StringReplace(ts,".","-");

//--- Sanitise exit_reason — strip any commas to keep CSV well-formed
   StringReplace(exit_reason,",",";");

   double total_pl=profit+swap+commission;

   string row=StringFormat(
      "%s,%I64u,%I64u,%s,"
      "%.5f,%.2f,%.2f,%.2f,%.2f,%s\n",
      ts, position_id, deal_ticket, m_symbol,
      close_price, profit, swap, commission, total_pl, exit_reason
   );

   FileWriteString(h,row);
   FileClose(h);

   if(InpShowJournalDebug)
      Print("[JOURNAL] Exit written: pos=",position_id," reason=",exit_reason,
            " total_pl=",DoubleToString(total_pl,2));
  }

//+------------------------------------------------------------------+
//| v1.18 — Read forex_sentiment.json from MT5 Common Files          |
//|                                                                   |
//| Always marks m_sentiment.valid=false during (bool)MQLInfoInteger(MQL_TESTER) so the   |
//| backtest code path is guaranteed to see no sentiment data.        |
//| In live mode, uses the same mtime-guard pattern as               |
//| LoadEASignalFromJSON: cheap on repeat calls when the 10-min       |
//| pipeline hasn't written a new snapshot yet.                       |
//+------------------------------------------------------------------+
void CGGTHExpert::ReadSentimentFile()
  {
//--- Strategy Tester: always invalid — no historical sentiment data.
//    This is the single point of enforcement for the backtest bypass.
   if((bool)MQLInfoInteger(MQL_TESTER))
     {
      m_sentiment.valid = false;
      return;
     }

   string fname = InpSentimentFile;

//--- Mtime guard: re-parse only when the file has changed.
   datetime mod = (datetime)FileGetInteger(fname, FILE_MODIFY_DATE, true);
   if(mod <= 0)
     {
      m_sentiment.valid = false;   // file not found in Common Files
      return;
     }
   if(mod <= m_last_sentiment_mod && m_sentiment.valid)
      return;   // unchanged since last successful read; cached values still good

   int h = FileOpen(fname, FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_COMMON);
   if(h == INVALID_HANDLE)
     {
      m_sentiment.valid = false;
      return;
     }

   string json = "";
   while(!FileIsEnding(h)) json += FileReadString(h);
   FileClose(h);

   if(StringLen(json) < 20)
     {
      m_sentiment.valid = false;
      return;
     }

//--- Parse "timestamp" to compute age.
//    Format from Python: "2026-05-11T17:00:12+00:00"
//    We extract the date/time portion and use StringToTime.
   string ts_val = "";
   if(!ExtractJsonString(json, "\"timestamp\"", ts_val))
     {
      m_sentiment.valid = false;
      return;
     }
   // Strip timezone suffix — StringToTime handles "YYYY.MM.DD HH:MM:SS"
   StringReplace(ts_val, "T", " ");
   if(StringLen(ts_val) > 19) ts_val = StringSubstr(ts_val, 0, 19);
   StringReplace(ts_val, "-", ".");
   datetime snap_time = StringToTime(ts_val);
   long age_s = (long)(TimeGMT() - snap_time);
   if(age_s < 0) age_s = 0;

//--- Enforce max-age before touching the pair search.
   if(age_s > (long)InpSentimentMaxAgeSec)
     {
      m_sentiment.valid = false;
      if(InpShowDebug)
         PrintFormat("[SENTIMENT] File too old (%ds > limit %ds) — ignored",
                     (int)age_s, InpSentimentMaxAgeSec);
      return;
     }

//--- Find the entry for our trading symbol inside the "pairs" array.
//    The array looks like: "pairs": [ {..., "pair": "EURUSD", ...}, ... ]
//    We search for the pair name as a string value, then bound to that object.
   string target = m_symbol; // e.g. "EURUSD"
   string search = "\"" + target + "\"";
   int pair_pos  = StringFind(json, search);
   if(pair_pos < 0)
     {
      m_sentiment.valid = false;
      if(InpShowDebug)
         Print("[SENTIMENT] Pair ", target, " not found in sentiment file");
      return;
     }

//--- Walk backwards from pair_pos to find the enclosing '{' of this pair object.
   int obj_open = pair_pos;
   while(obj_open > 0 && StringGetCharacter(json, obj_open) != '{') obj_open--;
   int obj_close = FindMatchingBrace(json, obj_open);
   if(obj_close < 0)
     {
      m_sentiment.valid = false;
      return;
     }

   string obj = StringSubstr(json, obj_open, obj_close - obj_open + 1);

//--- Extract fields — leave defaults if any are missing (fail-open).
   double score = 0.0, conf = 0.0, base_s = 0.0, quote_s = 0.0;
   ExtractJsonNumber(obj, "\"score\"",       score);
   ExtractJsonNumber(obj, "\"confidence\"",  conf);
   ExtractJsonNumber(obj, "\"base_score\"",  base_s);
   ExtractJsonNumber(obj, "\"quote_score\"", quote_s);

//--- Enforce minimum confidence gate.
   if(conf < InpSentimentMinConf)
     {
      m_sentiment.valid = false;
      if(InpShowDebug)
         PrintFormat("[SENTIMENT] Confidence %.2f < min %.2f — ignored",
                     conf, InpSentimentMinConf);
      return;
     }

//--- Commit.
   m_sentiment.score       = score;
   m_sentiment.confidence  = conf;
   m_sentiment.base_score  = base_s;
   m_sentiment.quote_score = quote_s;
   m_sentiment.age_seconds = age_s;
   m_sentiment.valid       = true;
   m_last_sentiment_mod    = mod;
  }

//+------------------------------------------------------------------+
//| v1.18 — Sentiment section rendered inline at bottom of main box  |
//+------------------------------------------------------------------+
void CGGTHExpert::DisplaySentimentPanel(int x, int &y, int lh)
  {
//--- Header
   CreateLabel("SENT_Header", x, y, "NEWS SENTIMENT", InpFontSize, clrYellow);
   y += lh;

   if(!m_sentiment.valid)
     {
      CreateLabel("SENT_Bias",   x, y, "No data — run: python main.py", InpFontSize-1, clrGray);
      y += lh;
      CreateLabel("SENT_Detail", x, y, "(stale / low-conf / file missing)", InpFontSize-2, clrGray);
      y += lh;
      if(ObjectFind(0,"SENT_Score") >= 0) ObjectSetString(0,"SENT_Score",OBJPROP_TEXT,"");
      if(ObjectFind(0,"SENT_Comp")  >= 0) ObjectSetString(0,"SENT_Comp", OBJPROP_TEXT,"");
      if(ObjectFind(0,"SENT_Veto")  >= 0) ObjectSetString(0,"SENT_Veto", OBJPROP_TEXT,"");
      return;
     }

//--- Bias + score + confidence
   string bias;
   color  bias_clr;
   if(m_sentiment.score > InpSentimentVetoBand)
     { bias = "BULLISH"; bias_clr = InpUpColor; }
   else if(m_sentiment.score < -InpSentimentVetoBand)
     { bias = "BEARISH"; bias_clr = InpDownColor; }
   else
     { bias = "NEUTRAL"; bias_clr = clrGray; }

   string score_str = StringFormat("%s  score: %+.3f  conf: %.0f%%",
                                   bias, m_sentiment.score,
                                   m_sentiment.confidence * 100.0);
   CreateLabel("SENT_Score", x, y, score_str, InpFontSize, bias_clr);
   y += lh;

//--- Component scores + age
   string comp_str = StringFormat("Base: %+.3f  Quote: %+.3f  Age: %dm",
                                  m_sentiment.base_score,
                                  m_sentiment.quote_score,
                                  (int)(m_sentiment.age_seconds / 60));
   CreateLabel("SENT_Comp", x, y, comp_str, InpFontSize-1, clrSilver);
   y += lh;

//--- Veto status
   string veto_str;
   color  veto_clr;
   if(m_sentiment.score > InpSentimentVetoBand)
     { veto_str = "SELL signals may be vetoed"; veto_clr = clrOrange; }
   else if(m_sentiment.score < -InpSentimentVetoBand)
     { veto_str = "BUY signals may be vetoed";  veto_clr = clrOrange; }
   else
     { veto_str = "No active veto";             veto_clr = clrGray; }
   CreateLabel("SENT_Veto", x, y, veto_str, InpFontSize-1, veto_clr);
   y += lh;

   if(ObjectFind(0,"SENT_Bias")   >= 0) ObjectSetString(0,"SENT_Bias",  OBJPROP_TEXT,"");
   if(ObjectFind(0,"SENT_Detail") >= 0) ObjectSetString(0,"SENT_Detail",OBJPROP_TEXT,"");
  }
//+------------------------------------------------------------------+
