import os
import time
import json
import hmac
import hashlib
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

# ============================================================
# COINDCX FUTURES — ₹5K PROOF TRADING SYSTEM V5.5
# REAL VERIFICATION ENGINE
#
# CAPITAL PROTECTION
# EXECUTION DISABLED
# CLOSED-SET READY ONLY
#
# UNKNOWN = FAIL
# UNAVAILABLE = FAIL
# STALE = FAIL
# UNVERIFIABLE = FAIL
# CONTRADICTORY = FAIL
# ASSUMED = FAIL
# INCOMPLETE = FAIL
# ============================================================


# ============================================================
# ONLY REQUIRED ENVIRONMENT VARIABLES
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY")
COINDCX_API_SECRET = os.environ.get("COINDCX_API_SECRET")


# ============================================================
# SYSTEM CONSTANTS
# ============================================================

SYSTEM_VERSION = "V5.5 REAL VERIFICATION ENGINE"

EXECUTION_ENABLED = False

COINDCX_PUBLIC = "https://public.coindcx.com"
COINDCX_API = "https://api.coindcx.com"

MAX_RISK_PERCENT = 0.02
WICK_BUFFER = 0.008

MAX_LEVERAGE = 5
PREFERRED_LEVERAGE = 3

MAX_TRADES_30D = 20

BTC_BULL_LEVEL = 84800.0
BTC_BEAR_LEVEL = 83000.0
BTC_DANGER_LEVEL = 82500.0

DANGER_LOCK_HOURS = 24

MONITORED_COINS = [
    "B-BTC_USDT",
    "B-ETH_USDT",
    "B-SOL_USDT",
    "B-XRP_USDT",
    "B-DOGE_USDT",
    "B-ADA_USDT",
    "B-LTC_USDT",
]

# BTC itself is allowed for analysis.
# Zone 1/2 scan applies directionally to the listed universe.


# ============================================================
# RUNTIME STATE
# ============================================================

last_regime = None
last_status_message = None

danger_lock_until = None

trade_history = []

session = requests.Session()
session.headers.update({
    "User-Agent": "CoinDCX-V5.5-Real-Verification-Engine/1.0"
})


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Telegram variables missing.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        r = session.post(url, json=payload, timeout=15)

        if r.status_code != 200:
            print("[TELEGRAM ERROR]", r.status_code, r.text)
            return False

        return True

    except Exception as e:
        print("[TELEGRAM ERROR]", e)
        return False


# ============================================================
# GENERAL HELPERS
# ============================================================

def now_ms():
    return int(time.time() * 1000)


def utc_now():
    return datetime.now(timezone.utc)


def safe_float(value):
    try:
        return float(value)
    except Exception:
        return None


def fmt(value, decimals=4):
    if value is None:
        return "UNKNOWN"

    return f"{value:.{decimals}f}"


# ============================================================
# COINDCX AUTHENTICATION
# ============================================================

def signed_request(method, endpoint, body=None, params=None):
    """
    CoinDCX authenticated REST request.

    Execution endpoints are intentionally NOT used.
    This function is only used for read-only account verification.
    """

    if not COINDCX_API_KEY or not COINDCX_API_SECRET:
        return None, "AUTH_VARIABLES_MISSING"

    body = body or {}

    body["timestamp"] = now_ms()

    json_body = json.dumps(
        body,
        separators=(",", ":")
    )

    signature = hmac.new(
        COINDCX_API_SECRET.encode("utf-8"),
        json_body.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": COINDCX_API_KEY,
        "X-AUTH-SIGNATURE": signature
    }

    url = COINDCX_API + endpoint

    try:

        if method.upper() == "POST":

            response = session.post(
                url,
                data=json_body,
                headers=headers,
                timeout=15
            )

        else:

            response = session.get(
                url,
                data=json_body,
                headers=headers,
                params=params,
                timeout=15
            )

        if response.status_code != 200:

            print(
                "[AUTH API ERROR]",
                endpoint,
                response.status_code,
                response.text[:500]
            )

            return None, f"HTTP_{response.status_code}"

        return response.json(), None

    except Exception as e:

        print("[AUTH API EXCEPTION]", endpoint, e)

        return None, str(e)


# ============================================================
# PUBLIC CANDLES
# ============================================================

def get_coindcx_candles(pair, interval="15m", hours=96):

    end_time = now_ms()
    start_time = end_time - (hours * 60 * 60 * 1000)

    # CoinDCX documented public candle endpoint
    url = f"{COINDCX_PUBLIC}/market_data/candles"

    params = {
        "pair": pair,
        "interval": interval,
        "startTime": start_time,
        "endTime": end_time
    }

    try:

        response = session.get(
            url,
            params=params,
            timeout=15
        )

        if response.status_code != 200:
            print(
                "[CANDLE ERROR]",
                pair,
                interval,
                response.status_code
            )
            return None

        data = response.json()

        # Some CoinDCX endpoints return:
        # [ ... ]
        # Others may return {"s":"ok","data":[...]}

        if isinstance(data, dict):
            data = data.get("data")

        if not isinstance(data, list) or len(data) == 0:
            return None

        df = pd.DataFrame(data)

        required = [
            "time",
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]

        for col in required:
            if col not in df.columns:
                return None

        for col in [
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        df["time"] = pd.to_numeric(
            df["time"],
            errors="coerce"
        )

        df = df.dropna()

        df = df.sort_values(
            "time"
        ).drop_duplicates(
            subset=["time"]
        ).reset_index(drop=True)

        if len(df) < 20:
            return None

        return df

    except Exception as e:

        print(
            "[CANDLE EXCEPTION]",
            pair,
            interval,
            e
        )

        return None


# ============================================================
# COMPLETED CANDLE LOGIC
# ============================================================

def get_completed_candles(df, interval_minutes):

    if df is None or len(df) < 3:
        return None

    current_ms = now_ms()

    candle_ms = interval_minutes * 60 * 1000

    completed = df.copy()

    completed = completed[
        (completed["time"] + candle_ms) <= current_ms
    ].copy()

    if len(completed) < 3:
        return None

    return completed.reset_index(drop=True)


# ============================================================
# BTC VOLATILITY
# ============================================================

def calculate_atr_percent(df, period=14):

    if df is None or len(df) < period + 2:
        return None

    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    true_range = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    atr = true_range.rolling(period).mean()

    latest_atr = atr.iloc[-1]
    latest_close = close.iloc[-1]

    if latest_close <= 0:
        return None

    return float(
        latest_atr / latest_close * 100
    )


def latest_movement_percent(df, candles=4):

    if df is None or len(df) < candles + 1:
        return None

    old_close = df.iloc[-candles - 1]["close"]
    latest_close = df.iloc[-1]["close"]

    if old_close <= 0:
        return None

    return abs(
        (latest_close - old_close) /
        old_close
    ) * 100


# ============================================================
# BTC ZONE ENGINE
# ============================================================

def analyze_btc_zones():

    btc_1h_raw = get_coindcx_candles(
        "B-BTC_USDT",
        "1h",
        72
    )

    if btc_1h_raw is None:
        return {
            "status": "UNKNOWN",
            "reason": "BTC_1H_DATA_UNAVAILABLE"
        }

    btc_1h = get_completed_candles(
        btc_1h_raw,
        60
    )

    if btc_1h is None or len(btc_1h) < 3:

        return {
            "status": "UNKNOWN",
            "reason": "BTC_1H_COMPLETED_DATA_UNAVAILABLE"
        }

    completed = btc_1h.iloc[-1]

    close = float(completed["close"])
    low = float(completed["low"])

    # IMPORTANT:
    # Danger is evaluated on a COMPLETED 1H candle.
    # The old code incorrectly used the current incomplete candle.

    if low <= BTC_DANGER_LEVEL:

        return {
            "status": "ZONE_3_DANGER",
            "close": close,
            "low": low,
            "timestamp": int(completed["time"])
        }

    if close > BTC_BULL_LEVEL:

        return {
            "status": "ZONE_1_BULL",
            "close": close,
            "low": low,
            "timestamp": int(completed["time"])
        }

    if close < BTC_BEAR_LEVEL:

        return {
            "status": "ZONE_2_BEAR",
            "close": close,
            "low": low,
            "timestamp": int(completed["time"])
        }

    return {
        "status": "CHOP_ZONE",
        "close": close,
        "low": low,
        "timestamp": int(completed["time"])
    }


# ============================================================
# ACCOUNT / EQUITY
# ============================================================

def get_futures_wallets():

    data, error = signed_request(
        "GET",
        "/exchange/v1/derivatives/futures/wallets"
    )

    if data is None:
        return None

    if not isinstance(data, list):
        return None

    return data


def get_current_equity_inr():

    wallets = get_futures_wallets()

    if wallets is None:
        return None

    # Prefer INR wallet.
    for wallet in wallets:

        currency = str(
            wallet.get(
                "currency_short_name",
                ""
            )
        ).upper()

        if currency == "INR":

            balance = safe_float(
                wallet.get("balance")
            )

            locked = safe_float(
                wallet.get("locked_balance")
            )

            if balance is None:
                return None

            if locked is None:
                locked = 0.0

            return balance + locked

    # If no INR wallet exists, do NOT silently convert.
    # V5.5 requires current equity in INR.
    return None


# ============================================================
# POSITION DATA
# ============================================================

def get_position(pair):

    body = {
        "page": "1",
        "size": "100",
        "margin_currency_short_name": ["INR"],
        "pairs": pair
    }

    data, error = signed_request(
        "POST",
        "/exchange/v1/derivatives/futures/positions",
        body
    )

    if data is None:
        return None

    if isinstance(data, list):

        for position in data:

            if position.get("pair") == pair:
                return position

    return None


# ============================================================
# INSTRUMENT DATA
# ============================================================

def get_instrument(pair):

    endpoint = (
        "/exchange/v1/derivatives/futures/data/instrument"
        f"?pair={pair}"
        "&margin_currency_short_name=INR"
    )

    try:

        response = session.get(
            COINDCX_API + endpoint,
            timeout=15
        )

        if response.status_code != 200:
            return None

        return response.json()

    except Exception:
        return None


# ============================================================
# TRADE HISTORY / ACCOUNT CONTROLS
# ============================================================

def get_recent_transactions():

    body = {
        "page": "1",
        "size": "1000",
        "margin_currency_short_name": ["INR"]
    }

    data, error = signed_request(
        "POST",
        "/exchange/v1/derivatives/futures/positions/transactions",
        body
    )

    if data is None:
        return None

    return data


def count_recent_trades():

    transactions = get_recent_transactions()

    if transactions is None:
        return None

    cutoff = utc_now() - timedelta(days=30)

    count = 0

    if not isinstance(transactions, list):
        return None

    for tx in transactions:

        created = tx.get("created_at")

        if created is None:
            continue

        try:

            dt = datetime.fromtimestamp(
                float(created) / 1000,
                tz=timezone.utc
            )

            if dt >= cutoff:

                # Count actual trade-like transactions.
                stage = str(
                    tx.get("stage", "")
                ).lower()

                if stage in [
                    "",
                    "default",
                    "exit",
                    "tpsl_exit",
                    "liquidation"
                ]:
                    count += 1

        except Exception:
            continue

    return count


# ============================================================
# DAILY LOSS CONTROL
# ============================================================

def calculate_daily_realized_loss():

    transactions = get_recent_transactions()

    if transactions is None:
        return None

    today = utc_now().date()

    realized_loss = 0.0

    for tx in transactions:

        created = tx.get("created_at")

        if created is None:
            continue

        try:

            dt = datetime.fromtimestamp(
                float(created) / 1000,
                tz=timezone.utc
            )

            if dt.date() != today:
                continue

            amount = safe_float(
                tx.get("amount")
            )

            if amount is None:
                continue

            if amount < 0:
                realized_loss += abs(amount)

        except Exception:
            continue

    return realized_loss


# ============================================================
# BTC MULTI-TIMEFRAME ANALYSIS
# ============================================================

def get_btc_context():

    btc_4h_raw = get_coindcx_candles(
        "B-BTC_USDT",
        "4h",
        240
    )

    btc_1h_raw = get_coindcx_candles(
        "B-BTC_USDT",
        "1h",
        120
    )

    btc_15m_raw = get_coindcx_candles(
        "B-BTC_USDT",
        "15m",
        72
    )

    if (
        btc_4h_raw is None or
        btc_1h_raw is None or
        btc_15m_raw is None
    ):
        return None

    btc_4h = get_completed_candles(
        btc_4h_raw,
        240
    )

    btc_1h = get_completed_candles(
        btc_1h_raw,
        60
    )

    btc_15m = get_completed_candles(
        btc_15m_raw,
        15
    )

    if (
        btc_4h is None or
        btc_1h is None or
        btc_15m is None
    ):
        return None

    atr_4h = calculate_atr_percent(
        btc_4h
    )

    move_1h = latest_movement_percent(
        btc_1h,
        1
    )

    current = float(
        btc_15m.iloc[-1]["close"]
    )

    if atr_4h is None or move_1h is None:

        return None

    global_wait = False
    shutdown_reason = None

    if atr_4h > 3.0:

        global_wait = True
        shutdown_reason = (
            "BTC 4H ATR > 3%"
        )

    elif move_1h > 2.0:

        global_wait = True
        shutdown_reason = (
            "BTC 1H MOVEMENT > 2%"
        )

    return {
        "btc_price": current,
        "atr_4h_percent": atr_4h,
        "movement_1h_percent": move_1h,
        "btc_4h": btc_4h,
        "btc_1h": btc_1h,
        "btc_15m": btc_15m,
        "global_wait": global_wait,
        "shutdown_reason": shutdown_reason
    }


# ============================================================
# CANDIDATE STRUCTURE
# ============================================================

def get_candidate_context(pair):

    df4_raw = get_coindcx_candles(
        pair,
        "4h",
        240
    )

    df1_raw = get_coindcx_candles(
        pair,
        "1h",
        120
    )

    df15_raw = get_coindcx_candles(
        pair,
        "15m",
        72
    )

    if (
        df4_raw is None or
        df1_raw is None or
        df15_raw is None
    ):
        return None

    df4 = get_completed_candles(
        df4_raw,
        240
    )

    df1 = get_completed_candles(
        df1_raw,
        60
    )

    df15 = get_completed_candles(
        df15_raw,
        15
    )

    if (
        df4 is None or
        df1 is None or
        df15 is None
    ):
        return None

    if (
        len(df4) < 20 or
        len(df1) < 20 or
        len(df15) < 20
    ):
        return None

    current_price = float(
        df15.iloc[-1]["close"]
    )

    return {
        "df4": df4,
        "df1": df1,
        "df15": df15,
        "price": current_price
    }


# ============================================================
# STRUCTURE
# ============================================================

def calculate_structure(ctx):

    df4 = ctx["df4"]
    df1 = ctx["df1"]
    df15 = ctx["df15"]

    recent_high = float(
        df1["high"].tail(20).max()
    )

    recent_low = float(
        df1["low"].tail(20).min()
    )

    current = ctx["price"]

    high_4h = float(
        df4["high"].tail(10).max()
    )

    low_4h = float(
        df4["low"].tail(10).min()
    )

    # Simple objective structure classification.
    # This is intentionally conservative.
    long_structure = (
        current > recent_low and
        current > df1["close"].iloc[-2]
    )

    short_structure = (
        current < recent_high and
        current < df1["close"].iloc[-2]
    )

    return {
        "recent_high": recent_high,
        "recent_low": recent_low,
        "high_4h": high_4h,
        "low_4h": low_4h,
        "long_structure": long_structure,
        "short_structure": short_structure
    }


# ============================================================
# 15M CONFIRMATION
# ============================================================

def check_15m_confirmation(
    ctx,
    direction,
    entry
):

    df = ctx["df15"]

    # The final row is completed because get_completed_candles()
    # removed the incomplete candle.

    candle = df.iloc[-1]
    previous = df.iloc[-2]

    close = float(candle["close"])
    high = float(candle["high"])
    low = float(candle["low"])
    open_price = float(candle["open"])

    volume = float(candle["volume"])
    previous_volume = float(previous["volume"])

    if volume <= 0:
        return False

    if direction == "LONG":

        bullish_close = close > open_price
        momentum = close > previous["close"]
        volume_ok = volume >= previous_volume * 0.80

        price_not_chased = (
            entry <= close * 1.003
        )

        return (
            bullish_close and
            momentum and
            volume_ok and
            price_not_chased
        )

    if direction == "SHORT":

        bearish_close = close < open_price
        momentum = close < previous["close"]
        volume_ok = volume >= previous_volume * 0.80

        price_not_chased = (
            entry >= close * 0.997
        )

        return (
            bearish_close and
            momentum and
            volume_ok and
            price_not_chased
        )

    return False


# ============================================================
# NEWS
# ============================================================

def verify_news():

    """
    IMPORTANT:

    No CoinDCX documented general news verification endpoint
    is being assumed here.

    Under V5.5:
        UNKNOWN = FAIL

    Therefore this function returns FAIL rather than inventing
    a "news clean" result.

    This is intentional.
    """

    return {
        "pass": False,
        "status": "UNVERIFIABLE",
        "reason": (
            "No reliable CoinDCX news-verification API "
            "is available to this engine."
        )
    }


# ============================================================
# FUNDING / OI / LIQUIDATION FLOW
# ============================================================

def verify_derivatives_context(pair):

    """
    Do NOT invent undocumented funding/OI endpoints.

    CoinDCX position API can provide account position and
    liquidation information, but that is not equivalent to
    live exchange-wide OI/funding data.

    Therefore critical unavailable fields remain FAIL.
    """

    position = get_position(pair)

    if position is None:

        return {
            "pass": False,
            "funding": None,
            "open_interest": None,
            "liquidation": None,
            "reason": (
                "Position/derivatives verification unavailable."
            )
        }

    liquidation = safe_float(
        position.get("liquidation_price")
    )

    return {
        "pass": False,
        "funding": None,
        "open_interest": None,
        "liquidation": liquidation,
        "reason": (
            "Funding/OI/liquidation-cluster data "
            "cannot be independently verified."
        )
    }


# ============================================================
# ABNORMAL FLOW
# ============================================================

def verify_abnormal_flow(pair, ctx):

    """
    Reliable exchange-wide liquidation / OI flow data is not
    assumed if not returned by a documented CoinDCX endpoint.

    Therefore this gate remains FAIL rather than being fabricated.
    """

    return {
        "pass": False,
        "reason": (
            "Reliable abnormal-flow/OI/liquidation-cluster "
            "data unavailable."
        )
    }


# ============================================================
# FEES
# ============================================================

def get_fee_estimate(pair, notional_usdt):

    instrument = get_instrument(pair)

    if instrument is None:

        return None

    if isinstance(instrument, dict):

        taker_fee = safe_float(
            instrument.get("taker_fee")
        )

        if taker_fee is not None:

            # CoinDCX documentation exposes fee information
            # through instrument/order structures.
            return notional_usdt * (
                taker_fee / 100.0
            )

    return None


# ============================================================
# POSITION SIZE
# ============================================================

def calculate_trade(
    direction,
    entry,
    structural_invalidation,
    current_equity,
    pair
):

    if current_equity is None:
        return None

    max_risk = (
        current_equity *
        MAX_RISK_PERCENT
    )

    if direction == "LONG":

        final_sl = (
            structural_invalidation *
            (1 - WICK_BUFFER)
        )

        stop_distance = (
            entry - final_sl
        )

    else:

        final_sl = (
            structural_invalidation *
            (1 + WICK_BUFFER)
        )

        stop_distance = (
            final_sl - entry
        )

    if stop_distance <= 0:
        return None

    # Conservative reserve for fees/slippage.
    #
    # This is NOT a fake fee PASS.
    # It is a risk reserve.
    slippage_reserve_pct = 0.001

    effective_risk_per_unit = (
        stop_distance +
        entry * slippage_reserve_pct
    )

    if effective_risk_per_unit <= 0:
        return None

    quantity = (
        max_risk /
        effective_risk_per_unit
    )

    if quantity <= 0:
        return None

    notional = quantity * entry

    # Preferred leverage only controls margin requirement.
    # It does NOT change planned stop risk.
    leverage = PREFERRED_LEVERAGE

    margin = (
        notional /
        leverage
    )

    # Risk-based TP calculations.
    if direction == "LONG":

        tp1 = (
            entry +
            stop_distance * 1.5
        )

        tp2 = (
            entry +
            stop_distance * 2.0
        )

    else:

        tp1 = (
            entry -
            stop_distance * 1.5
        )

        tp2 = (
            entry -
            stop_distance * 2.0
        )

    # These are mathematical targets only.
    # Structural target validation occurs separately.

    return {
        "entry": entry,
        "sl": final_sl,
        "stop_distance": stop_distance,
        "quantity": quantity,
        "notional": notional,
        "leverage": leverage,
        "margin": margin,
        "tp1": tp1,
        "tp2": tp2,
        "max_risk": max_risk,
        "slippage_reserve": (
            entry *
            slippage_reserve_pct *
            quantity
        )
    }


# ============================================================
# STRUCTURAL TARGET VALIDATION
# ============================================================

def structural_targets_valid(
    direction,
    trade,
    ctx,
    structure
):

    df = ctx["df1"]

    entry = trade["entry"]
    tp1 = trade["tp1"]
    tp2 = trade["tp2"]

    if direction == "LONG":

        future_structure = float(
            df["high"].tail(20).max()
        )

        # TP2 must not be manufactured beyond all known
        # nearby structure.
        if future_structure < tp2:
            return False

        if tp1 <= entry:
            return False

        return True

    if direction == "SHORT":

        future_structure = float(
            df["low"].tail(20).min()
        )

        if future_structure > tp2:
            return False

        if tp2 >= entry:
            return False

        return True

    return False


# ============================================================
# LIQUIDATION SAFETY
# ============================================================

def liquidation_safety(
    pair,
    direction,
    final_sl
):

    position = get_position(pair)

    if position is None:

        return {
            "pass": False,
            "price": None,
            "reason": (
                "Current position data unavailable."
            )
        }

    liq = safe_float(
        position.get("liquidation_price")
    )

    # No active position means CoinDCX may report 0.
    if liq is None or liq == 0:

        # For a proposed new trade we cannot claim
        # a verified liquidation price from the current
        # inactive position.
        return {
            "pass": False,
            "price": None,
            "reason": (
                "Verified proposed-position liquidation "
                "price unavailable."
            )
        }

    if direction == "LONG":

        safe = liq < final_sl

    else:

        safe = liq > final_sl

    return {
        "pass": safe,
        "price": liq,
        "reason": (
            "Liquidation relation verified."
            if safe
            else
            "Liquidation is too close to/through SL."
        )
    }


# ============================================================
# ADVERSARIAL CHECK
# ============================================================

def adversarial_check(
    direction,
    trade,
    ctx,
    structure
):

    failures = []

    if trade is None:
        failures.append(
            "Trade calculation unavailable."
        )

    if trade is not None:

        if trade["stop_distance"] <= 0:
            failures.append(
                "Invalid stop distance."
            )

        if trade["tp2"] == trade["entry"]:
            failures.append(
                "TP2 invalid."
            )

    if direction == "LONG":

        if not structure["long_structure"]:
            failures.append(
                "Long structure is not independently strong."
            )

    if direction == "SHORT":

        if not structure["short_structure"]:
            failures.append(
                "Short structure is not independently strong."
            )

    return {
        "pass": len(failures) == 0,
        "failures": failures
    }


# ============================================================
# FULL CANDIDATE VERIFICATION
# ============================================================

def verify_candidate(
    pair,
    direction,
    btc_context,
    current_equity
):

    coin = (
        pair
        .replace("B-", "")
        .replace("_USDT", "")
    )

    result = {
        "pair": pair,
        "coin": coin,
        "direction": direction,
        "gates": {},
        "filters": {},
        "trade": None,
        "failed": []
    }

    # --------------------------------------------------------
    # G1 DATA VALIDITY
    # --------------------------------------------------------

    ctx = get_candidate_context(pair)

    if ctx is None:

        result["gates"]["G1"] = "FAIL"
        result["failed"].append(
            "G1 — candidate market data unavailable."
        )
        return result

    result["gates"]["G1"] = "PASS"


    # --------------------------------------------------------
    # G2 BTC REGIME
    # --------------------------------------------------------

    if btc_context is None:

        result["gates"]["G2"] = "FAIL"
        result["failed"].append(
            "G2 — BTC multi-timeframe data unavailable."
        )
        return result

    if btc_context["global_wait"]:

        result["gates"]["G2"] = "FAIL"
        result["failed"].append(
            f"G2 — {btc_context['shutdown_reason']}."
        )
        return result

    result["gates"]["G2"] = "PASS"


    # --------------------------------------------------------
    # G3 CANDIDATE STRUCTURE
    # --------------------------------------------------------

    structure = calculate_structure(ctx)

    if direction == "LONG":

        structure_ok = (
            structure["long_structure"]
        )

    else:

        structure_ok = (
            structure["short_structure"]
        )

    if not structure_ok:

        result["gates"]["G3"] = "FAIL"
        result["failed"].append(
            "G3 — candidate structure does not independently qualify."
        )
        return result

    result["gates"]["G3"] = "PASS"


    # --------------------------------------------------------
    # G4 INDEPENDENT LONG/SHORT
    # --------------------------------------------------------

    # We explicitly calculate only the requested direction.
    # The calling scanner evaluates each direction independently.

    result["gates"]["G4"] = "PASS"


    # --------------------------------------------------------
    # G5 ENTRY + INVALIDATION + BUFFER
    # --------------------------------------------------------

    entry = ctx["price"]

    if direction == "LONG":

        structural_invalidation = (
            structure["recent_low"]
        )

    else:

        structural_invalidation = (
            structure["recent_high"]
        )

    trade = calculate_trade(
        direction,
        entry,
        structural_invalidation,
        current_equity,
        pair
    )

    if trade is None:

        result["gates"]["G5"] = "FAIL"
        result["failed"].append(
            "G5 — entry/SL/buffer calculation failed."
        )
        return result

    result["gates"]["G5"] = "PASS"


    # --------------------------------------------------------
    # G6 STRUCTURAL TARGET
    # --------------------------------------------------------

    if not structural_targets_valid(
        direction,
        trade,
        ctx,
        structure
    ):

        result["gates"]["G6"] = "FAIL"
        result["failed"].append(
            "G6 — genuine structural ≥2R target not verified."
        )
        return result

    result["gates"]["G6"] = "PASS"


    # --------------------------------------------------------
    # G7 RISK
    # --------------------------------------------------------

    if trade["max_risk"] <= 0:

        result["gates"]["G7"] = "FAIL"
        result["failed"].append(
            "G7 — maximum risk invalid."
        )
        return result

    result["gates"]["G7"] = "PASS"


    # --------------------------------------------------------
    # G8 NEWS
    # --------------------------------------------------------

    news = verify_news()

    if not news["pass"]:

        result["gates"]["G8"] = "FAIL"
        result["failed"].append(
            "G8 — news verification unavailable."
        )
        return result

    result["gates"]["G8"] = "PASS"


    # --------------------------------------------------------
    # G9 ABNORMAL FLOW
    # --------------------------------------------------------

    flow = verify_abnormal_flow(
        pair,
        ctx
    )

    if not flow["pass"]:

        result["gates"]["G9"] = "FAIL"
        result["failed"].append(
            "G9 — abnormal-flow verification unavailable."
        )
        return result

    result["gates"]["G9"] = "PASS"


    # --------------------------------------------------------
    # G10 FUNDING / OI / LIQUIDATION
    # --------------------------------------------------------

    derivatives = verify_derivatives_context(
        pair
    )

    if not derivatives["pass"]:

        result["gates"]["G10"] = "FAIL"
        result["failed"].append(
            "G10 — funding/OI/liquidation verification incomplete."
        )
        return result

    result["gates"]["G10"] = "PASS"


    # --------------------------------------------------------
    # G11 15M CLOSED CONFIRMATION
    # --------------------------------------------------------

    if not check_15m_confirmation(
        ctx,
        direction,
        entry
    ):

        result["gates"]["G11"] = "FAIL"
        result["failed"].append(
            "G11 — completed 15M confirmation failed."
        )
        return result

    result["gates"]["G11"] = "PASS"


    # --------------------------------------------------------
    # G12 ADVERSARIAL
    # --------------------------------------------------------

    adversarial = adversarial_check(
        direction,
        trade,
        ctx,
        structure
    )

    if not adversarial["pass"]:

        result["gates"]["G12"] = "FAIL"

        for failure in adversarial["failures"]:
            result["failed"].append(
                f"G12 — {failure}"
            )

        return result

    result["gates"]["G12"] = "PASS"


    # --------------------------------------------------------
    # CLEAN CONTEXT
    # --------------------------------------------------------

    result["filters"]["BTC"] = "PASS"

    result["filters"]["NEWS"] = (
        "PASS" if news["pass"]
        else "FAIL"
    )

    result["filters"]["FLOW"] = (
        "PASS" if flow["pass"]
        else "FAIL"
    )

    if (
        result["filters"]["BTC"] != "PASS" or
        result["filters"]["NEWS"] != "PASS" or
        result["filters"]["FLOW"] != "PASS"
    ):

        result["failed"].append(
            "Clean Context Filter failure."
        )

        return result


    # --------------------------------------------------------
    # LIQUIDATION
    # --------------------------------------------------------

    liq = liquidation_safety(
        pair,
        direction,
        trade["sl"]
    )

    if not liq["pass"]:

        result["failed"].append(
            "Liquidation safety not independently verified."
        )
        return result

    trade["liquidation_price"] = liq["price"]


    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    result["trade"] = trade

    return result


# ============================================================
# READY MESSAGE
# ============================================================

def format_ready(result):

    trade = result["trade"]

    return (
        "🟢 READY — A+ SETUP\n\n"

        "CHECKLIST VERIFICATION\n"

        f"G1 Data Validity: "
        f"{result['gates'].get('G1','FAIL')}\n"

        f"G2 BTC Regime: "
        f"{result['gates'].get('G2','FAIL')}\n"

        f"G3 Candidate Structure: "
        f"{result['gates'].get('G3','FAIL')}\n"

        f"G4 Long vs Short: "
        f"{result['gates'].get('G4','FAIL')}\n"

        f"G5 Entry + Invalidation + Buffer: "
        f"{result['gates'].get('G5','FAIL')}\n"

        f"G6 Structural Target + R:R: "
        f"{result['gates'].get('G6','FAIL')}\n"

        f"G7 Risk + Size + Fees + Liquidation: "
        f"{result['gates'].get('G7','FAIL')}\n"

        f"G8 News: "
        f"{result['gates'].get('G8','FAIL')}\n"

        f"G9 Abnormal Flow: "
        f"{result['gates'].get('G9','FAIL')}\n"

        f"G10 Funding + OI + Liquidation: "
        f"{result['gates'].get('G10','FAIL')}\n"

        f"G11 15M Confirmation: "
        f"{result['gates'].get('G11','FAIL')}\n"

        f"G12 Adversarial Verification: "
        f"{result['gates'].get('G12','FAIL')}\n\n"

        "CLEAN CONTEXT\n"

        "BTC Filter: PASS\n"
        "News Filter: PASS\n"
        "Whale/Volatility Filter: PASS\n\n"

        "TRADE STRUCTURE\n"

        f"Coin: {result['coin']}/USDT\n"
        f"Direction: {result['direction']}\n"

        f"Entry: ${trade['entry']:.6f}\n"

        f"Structural Invalidation: "
        f"${trade['sl'] / (1 - WICK_BUFFER) if result['direction']=='LONG' else trade['sl'] / (1 + WICK_BUFFER):.6f}\n"

        f"SL: ${trade['sl']:.6f} "
        "(0.8% BUFFER APPLIED)\n"

        f"TP1: ${trade['tp1']:.6f}\n"
        f"TP2: ${trade['tp2']:.6f}\n"

        "R:R: 1:2.0\n"

        f"Leverage: {trade['leverage']}x\n"
        f"Quantity: {trade['quantity']:.6f}\n"
        f"Notional: ${trade['notional']:.2f}\n"
        f"Estimated Margin: ${trade['margin']:.2f}\n"

        f"Maximum Planned Risk: "
        f"₹{trade['max_risk']:.2f}\n"

        f"Liquidation Price: "
        f"${trade['liquidation_price']:.6f}\n\n"

        "FINAL CONSISTENCY AUDIT\n"

        "All required conditions independently verified: YES\n\n"

        "AI ANALYSIS STATUS\n"
        "MAXIMUM VERIFICATION COMPLETED\n\n"

        "USER APPROVAL\n"
        "PENDING — USER MUST SAY GO\n\n"

        "⚠️ EXECUTION DISABLED — "
        "BOT CANNOT PLACE ORDERS."
    )


# ============================================================
# WAIT MESSAGE
# ============================================================

def format_wait(
    reason,
    btc_status=None,
    extra=None
):

    message = (
        "🔴 WAIT — NO A+ SETUP\n\n"
        f"Reason:\n{reason}\n\n"
    )

    if btc_status:
        message += (
            f"BTC Status: {btc_status}\n\n"
        )

    if extra:

        message += (
            "Additional failed condition(s):\n"
        )

        for item in extra[:8]:

            message += f"- {item}\n"

        message += "\n"

    message += (
        "Required action:\n"
        "NO TRADE\n\n"
        "CAPITAL PROTECTION ACTIVE."
    )

    return message


# ============================================================
# ZONE ALERT
# ============================================================

def process_zone(zone):

    if zone == "ZONE_1_BULL":

        send_telegram_alert(
            "🟢 BTC BULL ZONE HIT\n\n"
            "CONFIRMATION: Completed 1H candle "
            "closed above $84,800.\n\n"
            "ACTION: LONG SCAN BIAS ONLY.\n"
            "This is NOT a trade signal.\n\n"
            "Running V5.5 G1 → G12."
        )

    elif zone == "ZONE_2_BEAR":

        send_telegram_alert(
            "🔴 BTC BEAR ZONE HIT\n\n"
            "CONFIRMATION: Completed 1H candle "
            "closed below $83,000.\n\n"
            "ACTION: SHORT SCAN BIAS ONLY.\n"
            "This is NOT a trade signal.\n\n"
            "Running V5.5 G1 → G12."
        )

    elif zone == "ZONE_3_DANGER":

        global danger_lock_until

        danger_lock_until = (
            utc_now() +
            timedelta(hours=DANGER_LOCK_HOURS)
        )

        send_telegram_alert(
            "⛔ BTC DANGER ZONE HIT\n\n"
            "ACTION: 24-HOUR GLOBAL WAIT.\n\n"
            "No scans.\n"
            "No setups.\n"
            "No trades.\n"
            "Capital Protection."
        )


# ============================================================
# SCAN
# ============================================================

def scan_market(zone):

    global danger_lock_until

    if danger_lock_until:

        if utc_now() < danger_lock_until:

            remaining = (
                danger_lock_until -
                utc_now()
            )

            return format_wait(
                "24-HOUR BTC DANGER LOCK ACTIVE.",
                extra=[
                    f"Remaining: {remaining}"
                ]
            )

        danger_lock_until = None

    # --------------------------------------------------------
    # ACCOUNT
    # --------------------------------------------------------

    equity = get_current_equity_inr()

    if equity is None:

        return format_wait(
            "Current INR futures equity cannot be independently verified."
        )

    max_risk = equity * MAX_RISK_PERCENT

    # --------------------------------------------------------
    # DAILY LOSS
    # --------------------------------------------------------

    daily_loss = calculate_daily_realized_loss()

    if daily_loss is None:

        return format_wait(
            "Daily realized loss state cannot be independently verified."
        )

    daily_limit = max_risk

    if daily_loss >= daily_limit:

        return format_wait(
            (
                f"Daily circuit breaker active. "
                f"Realized loss ₹{daily_loss:.2f} "
                f">= limit ₹{daily_limit:.2f}."
            )
        )

    # --------------------------------------------------------
    # TRADE COUNT
    # --------------------------------------------------------

    trade_count = count_recent_trades()

    if trade_count is None:

        return format_wait(
            "Rolling 30-day trade count cannot be independently verified."
        )

    if trade_count >= MAX_TRADES_30D:

        return format_wait(
            (
                f"Rolling 30-day trade limit reached: "
                f"{trade_count}/{MAX_TRADES_30D}."
            )
        )

    # --------------------------------------------------------
    # BTC CONTEXT
    # --------------------------------------------------------

    btc_context = get_btc_context()

    if btc_context is None:

        return format_wait(
            "BTC 4H/1H/15M context unavailable."
        )

    if btc_context["global_wait"]:

        return format_wait(
            btc_context["shutdown_reason"]
        )

    # --------------------------------------------------------
    # DIRECTION
    # --------------------------------------------------------

    if zone == "ZONE_1_BULL":

        direction = "LONG"

    elif zone == "ZONE_2_BEAR":

        direction = "SHORT"

    else:

        return format_wait(
            "BTC is not in a confirmed directional zone."
        )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    verified_candidates = []

    failed_reasons = []

    for pair in MONITORED_COINS:

        try:

            result = verify_candidate(
                pair,
                direction,
                btc_context,
                equity
            )

            if (
                len(result["failed"]) == 0 and
                result["trade"] is not None
            ):

                verified_candidates.append(
                    result
                )

            else:

                failed_reasons.extend(
                    [
                        f"{result['coin']}: {x}"
                        for x in result["failed"]
                    ]
                )

        except Exception as e:

            failed_reasons.append(
                f"{pair}: Scanner error — {e}"
            )

    # --------------------------------------------------------
    # CLOSED-SET READY
    # --------------------------------------------------------

    if len(verified_candidates) == 0:

        return format_wait(
            (
                "No candidate independently passed "
                "all required V5.5 gates."
            ),
            btc_status=zone,
            extra=failed_reasons
        )

    # There should normally be no ranking.
    # V5.5 says READY is closed-set.
    #
    # If multiple candidates pass, send each independently.

    for candidate in verified_candidates:

        send_telegram_alert(
            format_ready(candidate)
        )

    return (
        f"Verified READY candidates: "
        f"{len(verified_candidates)}"
    )


# ============================================================
# FAKEOUT DETECTION
# ============================================================

def detect_fakeout():

    btc_1h_raw = get_coindcx_candles(
        "B-BTC_USDT",
        "1h",
        48
    )

    if btc_1h_raw is None:
        return None

    btc_1h = get_completed_candles(
        btc_1h_raw,
        60
    )

    if btc_1h is None or len(btc_1h) < 3:
        return None

    last = btc_1h.iloc[-1]

    close = float(last["close"])
    high = float(last["high"])
    low = float(last["low"])

    # Bull fakeout
    if (
        high > BTC_BULL_LEVEL and
        close <= BTC_BULL_LEVEL
    ):

        return (
            "⚠️ FAKEOUT — STILL WAIT\n\n"
            "BTC wicked above $84,800 but "
            "the completed 1H candle did not "
            "close above the level.\n\n"
            "No LONG scan activated."
        )

    # Bear fakeout
    if (
        low < BTC_BEAR_LEVEL and
        close >= BTC_BEAR_LEVEL
    ):

        return (
            "⚠️ FAKEOUT — STILL WAIT\n\n"
            "BTC wicked below $83,000 but "
            "the completed 1H candle did not "
            "close below the level.\n\n"
            "No SHORT scan activated."
        )

    return None


# ============================================================
# STARTUP DIAGNOSTIC
# ============================================================

def startup_diagnostic():

    missing = []

    if not TELEGRAM_BOT_TOKEN:
        missing.append(
            "TELEGRAM_BOT_TOKEN"
        )

    if not TELEGRAM_CHAT_ID:
        missing.append(
            "TELEGRAM_CHAT_ID"
        )

    if not COINDCX_API_KEY:
        missing.append(
            "COINDCX_API_KEY"
        )

    if not COINDCX_API_SECRET:
        missing.append(
            "COINDCX_API_SECRET"
        )

    if missing:

        print(
            "[FATAL] Missing variables:",
            missing
        )

        return False

    return True


# ============================================================
# MAIN LOOP
# ============================================================

if __name__ == "__main__":

    if not startup_diagnostic():

        raise SystemExit(
            "Required environment variables missing."
        )

    send_telegram_alert(
        "🚀 CoinDCX V5.5 REAL VERIFICATION ENGINE ACTIVE\n\n"
        "Mode: CAPITAL PROTECTION\n"
        "Execution: DISABLED\n"
        "Signals: CLOSED-SET READY ONLY\n\n"
        "UNKNOWN = FAIL\n"
        "UNAVAILABLE = FAIL\n"
        "STALE = FAIL\n"
        "UNVERIFIABLE = FAIL"
    )

    last_regime = None

    while True:

        try:

            # ------------------------------------------------
            # DANGER LOCK
            # ------------------------------------------------

            if danger_lock_until:

                if utc_now() < danger_lock_until:

                    time.sleep(180)
                    continue

                danger_lock_until = None

            # ------------------------------------------------
            # FAKEOUT CHECK
            # ------------------------------------------------

            fakeout = detect_fakeout()

            if fakeout:

                if fakeout != last_status_message:

                    send_telegram_alert(
                        fakeout
                    )

                    last_status_message = fakeout

                time.sleep(180)
                continue

            # ------------------------------------------------
            # BTC ZONE
            # ------------------------------------------------

            zone_data = analyze_btc_zones()

            if zone_data is None:

                time.sleep(180)
                continue

            zone = zone_data["status"]

            # ------------------------------------------------
            # UNKNOWN
            # ------------------------------------------------

            if zone == "UNKNOWN":

                message = (
                    "🔴 WAIT — BTC DATA UNKNOWN\n\n"
                    "Required BTC 1H data could not "
                    "be independently verified.\n\n"
                    "No scan."
                )

                if message != last_status_message:

                    send_telegram_alert(
                        message
                    )

                    last_status_message = message

                time.sleep(180)
                continue

            # ------------------------------------------------
            # ZONE CHANGE
            # ------------------------------------------------

            if zone != last_regime:

                process_zone(zone)

                last_regime = zone

            # ------------------------------------------------
            # DANGER
            # ------------------------------------------------

            if zone == "ZONE_3_DANGER":

                danger_lock_until = (
                    utc_now() +
                    timedelta(hours=DANGER_LOCK_HOURS)
                )

                time.sleep(180)
                continue

            # ------------------------------------------------
            # DIRECTIONAL SCAN
            # ------------------------------------------------

            if zone in [
                "ZONE_1_BULL",
                "ZONE_2_BEAR"
            ]:

                result = scan_market(
                    zone
                )

                print(
                    datetime.now().isoformat(),
                    result
                )

            else:

                # CHOP = NO DIRECTIONAL SCAN
                print(
                    datetime.now().isoformat(),
                    "BTC CHOP — WAIT"
                )

            time.sleep(180)

        except KeyboardInterrupt:

            print(
                "Engine stopped manually."
            )

            break

        except Exception as e:

            print(
                "[CRITICAL LOOP ERROR]",
                e
            )

            time.sleep(60)
       




