import os
import time
import json
import hmac
import hashlib
import math
import re
import html
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import requests
import pandas as pd


# ============================================================
# COINDCX FUTURES — ₹5K PROOF TRADING SYSTEM V5.5
# REAL VERIFICATION ENGINE
#
# IMPORTANT:
# - NO TRADE EXECUTION
# - NO "FAKE PASS"
# - UNKNOWN / UNAVAILABLE / STALE / UNVERIFIABLE = FAIL
# - Only Telegram alerts are generated.
# ============================================================


# ============================================================
# 1. ONLY 4 RAILWAY VARIABLES REQUIRED
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY")
COINDCX_API_SECRET = os.environ.get("COINDCX_API_SECRET")


# ============================================================
# 2. HARD-LOCK CONFIGURATION
# ============================================================

STARTING_CAPITAL_INR = 5000.0

MAX_LEVERAGE = 5.0
PREFERRED_LEVERAGE = 3.0

MAX_RISK_PERCENT = 0.02

WICK_BUFFER = 0.008

MAX_TRADES_30D = 20

TAX_RESERVE_PERCENT = 0.312

DAILY_LOSS_PERCENT = 0.02

MONTHLY_STOP_PERCENT = 0.10

ZONE_BULL = 84800.0
ZONE_BEAR = 83000.0
ZONE_DANGER = 82500.0

GLOBAL_BTC_4H_ATR_PERCENT = 3.0
GLOBAL_BTC_1H_MOVE_PERCENT = 2.0

POLL_SECONDS = 180

DATA_TIMEOUT_SECONDS = 10

MAX_CANDLE_STALENESS_SECONDS = 120

NEWS_WINDOW_HOURS = 4

BTC_PAIR = "B-BTC_USDT"

MONITORED_COINS = [
    "B-BTC_USDT",
    "B-ETH_USDT",
    "B-SOL_USDT",
    "B-XRP_USDT",
    "B-DOGE_USDT",
    "B-ADA_USDT",
    "B-LTC_USDT",
]

STATE_FILE = "v55_state.json"

IST = ZoneInfo("Asia/Kolkata")


# ============================================================
# 3. ENDPOINTS
# ============================================================

PUBLIC_BASE = "https://public.coindcx.com"

AUTH_BASE = "https://api.coindcx.com"


# ============================================================
# 4. STATE
# ============================================================

DEFAULT_STATE = {
    "last_zone_alert": None,
    "last_zone_candle": None,
    "danger_until": None,
    "fakeout_alerts": [],
    "sent_setup_ids": [],
    "daily_date": None,
    "daily_start_equity": None,
    "monthly_key": None,
    "monthly_start_equity": None,
}


def load_state():
    try:
        if not os.path.exists(STATE_FILE):
            return DEFAULT_STATE.copy()

        with open(STATE_FILE, "r") as f:
            state = json.load(f)

        for k, v in DEFAULT_STATE.items():
            if k not in state:
                state[k] = v

        return state

    except Exception as e:
        print(f"[STATE ERROR] {e}")
        return DEFAULT_STATE.copy()


STATE = load_state()


def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(STATE, f, indent=2)
    except Exception as e:
        print(f"[STATE SAVE ERROR] {e}")


# ============================================================
# 5. TELEGRAM
# ============================================================

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Missing Telegram variables.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        r = requests.post(
            url,
            json=payload,
            timeout=DATA_TIMEOUT_SECONDS
        )

        if r.status_code != 200:
            print(f"[TELEGRAM ERROR] {r.status_code} {r.text}")
            return False

        return True

    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")
        return False


# ============================================================
# 6. GENERIC HTTP
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "CoinDCX-V5.5-Proof-System/1.0"
})


def public_get(url, params=None):
    try:
        r = SESSION.get(
            url,
            params=params,
            timeout=DATA_TIMEOUT_SECONDS
        )

        if r.status_code != 200:
            print(f"[PUBLIC API] HTTP {r.status_code}: {url}")
            return None

        return r.json()

    except Exception as e:
        print(f"[PUBLIC API ERROR] {url}: {e}")
        return None


def auth_request(method, path, body=None, query=None):
    if not COINDCX_API_KEY or not COINDCX_API_SECRET:
        print("[AUTH ERROR] CoinDCX API variables missing.")
        return None

    if body is None:
        body = {}

    body = dict(body)

    body["timestamp"] = int(time.time() * 1000)

    payload = json.dumps(
        body,
        separators=(",", ":")
    )

    signature = hmac.new(
        COINDCX_API_SECRET.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": COINDCX_API_KEY,
        "X-AUTH-SIGNATURE": signature,
    }

    url = AUTH_BASE + path

    try:
        if method.upper() == "POST":
            r = SESSION.post(
                url,
                data=payload,
                headers=headers,
                timeout=DATA_TIMEOUT_SECONDS
            )
        else:
            r = SESSION.get(
                url,
                params=query,
                data=payload,
                headers=headers,
                timeout=DATA_TIMEOUT_SECONDS
            )

        if r.status_code != 200:
            print(
                f"[AUTH API] HTTP {r.status_code}: "
                f"{r.text[:500]}"
            )
            return None

        return r.json()

    except Exception as e:
        print(f"[AUTH API ERROR] {path}: {e}")
        return None


# ============================================================
# 7. TIME
# ============================================================

def now_ms():
    return int(time.time() * 1000)


def utc_now():
    return datetime.now(timezone.utc)


def candle_is_completed(open_time_ms, interval_seconds):
    close_time_ms = open_time_ms + interval_seconds * 1000
    return close_time_ms <= now_ms()


def candle_age_seconds(open_time_ms, interval_seconds):
    close_time = open_time_ms / 1000 + interval_seconds
    return max(0, time.time() - close_time)


# ============================================================
# 8. COINDCX CANDLES
# ============================================================

RESOLUTIONS = {
    "15m": ("15", 900),
    "1h": ("60", 3600),
    "4h": ("240", 14400),
}


def get_coindcx_candles(pair, interval="15m", hours=120):
    if interval not in RESOLUTIONS:
        return None

    resolution, seconds = RESOLUTIONS[interval]

    end_sec = int(time.time())
    start_sec = end_sec - int(hours * 3600)

    url = f"{PUBLIC_BASE}/market_data/candlesticks"

    params = {
        "pair": pair,
        "from": start_sec,
        "to": end_sec,
        "resolution": resolution,
        "pcode": "f",
    }

    data = public_get(url, params=params)

    if not isinstance(data, dict):
        return None

    rows = data.get("data")

    if not isinstance(rows, list) or len(rows) < 10:
        return None

    try:
        df = pd.DataFrame(rows)

        required = [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "time",
        ]

        for col in required:
            if col not in df.columns:
                return None

        for col in [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "time",
        ]:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        df = df.dropna()

        df = df.sort_values(
            "time"
        ).drop_duplicates(
            "time"
        ).reset_index(drop=True)

        df["completed"] = df["time"].apply(
            lambda x: candle_is_completed(
                int(x),
                seconds
            )
        )

        return df

    except Exception as e:
        print(f"[CANDLE ERROR] {pair} {interval}: {e}")
        return None


def get_completed_candles(pair, interval, hours=120):
    df = get_coindcx_candles(
        pair,
        interval,
        hours
    )

    if df is None:
        return None

    completed = df[df["completed"]].copy()

    if len(completed) < 10:
        return None

    return completed.reset_index(drop=True)


# ============================================================
# 9. CURRENT FUTURES PRICE / FUNDING
# ============================================================

def get_current_prices():
    url = (
        f"{PUBLIC_BASE}"
        "/market_data/v3/current_prices/futures/rt"
    )

    return public_get(url)


def get_current_market(pair):
    data = get_current_prices()

    if not isinstance(data, dict):
        return None

    prices = data.get("prices", {})

    item = prices.get(pair)

    if not isinstance(item, dict):
        return None

    def number(key):
        try:
            value = item.get(key)
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    return {
        "last": number("ls"),
        "mark": number("mp"),
        "funding": number("fr"),
        "high": number("h"),
        "low": number("l"),
        "volume": number("v"),
        "change_percent": number("pc"),
        "timestamp": int(item.get("ctRT", 0) or 0),
    }


# ============================================================
# 10. ORDER BOOK
# ============================================================

def get_orderbook(pair):
    url = (
        f"{PUBLIC_BASE}"
        f"/market_data/v3/orderbook/{pair}-futures/50"
    )

    data = public_get(url)

    if not isinstance(data, dict):
        return None

    asks_raw = data.get("asks")
    bids_raw = data.get("bids")

    if not isinstance(asks_raw, dict):
        return None

    if not isinstance(bids_raw, dict):
        return None

    try:
        asks = sorted(
            [
                (float(price), float(qty))
                for price, qty in asks_raw.items()
            ],
            key=lambda x: x[0]
        )

        bids = sorted(
            [
                (float(price), float(qty))
                for price, qty in bids_raw.items()
            ],
            key=lambda x: x[0],
            reverse=True
        )

        if not asks or not bids:
            return None

        return {
            "asks": asks,
            "bids": bids,
            "timestamp": int(
                data.get("ts", 0) or 0
            ),
        }

    except Exception as e:
        print(f"[ORDERBOOK ERROR] {pair}: {e}")
        return None


def orderbook_metrics(orderbook):
    if not orderbook:
        return None

    asks = orderbook["asks"]
    bids = orderbook["bids"]

    best_ask = asks[0][0]
    best_bid = bids[0][0]

    mid = (best_ask + best_bid) / 2.0

    if mid <= 0:
        return None

    spread_percent = (
        (best_ask - best_bid)
        / mid
        * 100
    )

    bid_depth = sum(
        price * qty
        for price, qty in bids[:10]
    )

    ask_depth = sum(
        price * qty
        for price, qty in asks[:10]
    )

    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread_percent": spread_percent,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
    }


# ============================================================
# 11. REAL-TIME TRADES
# ============================================================

def get_recent_trades(pair):
    url = (
        f"{PUBLIC_BASE}"
        f"/market_data/v3/trades/{pair}-futures"
    )

    data = public_get(url)

    if isinstance(data, list):
        return data

    # fallback documented endpoint
    url2 = (
        f"{AUTH_BASE}"
        "/exchange/v1/derivatives/futures/data/trades"
    )

    data2 = public_get(
        url2,
        params={"pair": pair}
    )

    return data2 if isinstance(data2, list) else None


# ============================================================
# 12. INSTRUMENT DETAILS
# ============================================================

def get_instrument(pair):
    url = (
        f"{AUTH_BASE}"
        "/exchange/v1/derivatives/futures/data/instrument"
    )

    params = {
        "pair": pair,
        "margin_currency_short_name": "INR",
    }

    data = public_get(
        url,
        params=params
    )

    if not isinstance(data, dict):
        # Try USDT if INR response unavailable
        params["margin_currency_short_name"] = "USDT"

        data = public_get(
            url,
            params=params
        )

    if not isinstance(data, dict):
        return None

    instrument = data.get("instrument")

    return instrument if isinstance(
        instrument,
        dict
    ) else None


# ============================================================
# 13. USDT / INR CONVERSION
# ============================================================

def get_usdt_inr():
    url = (
        f"{AUTH_BASE}"
        "/api/v1/derivatives/futures/data/conversions"
    )

    data = auth_request(
        "GET",
        "/api/v1/derivatives/futures/data/conversions"
    )

    if not isinstance(data, list):
        return None

    for item in data:
        if (
            item.get("symbol") == "USDTINR"
            and item.get(
                "margin_currency_short_name"
            ) == "INR"
        ):
            try:
                return float(
                    item["conversion_price"]
                )
            except Exception:
                return None

    return None


# ============================================================
# 14. FUTURES WALLET / CURRENT EQUITY
# ============================================================

def get_futures_wallets():
    return auth_request(
        "GET",
        "/exchange/v1/derivatives/futures/wallets"
    )


def get_positions():
    body = {
        "page": "1",
        "size": "200",
        "margin_currency_short_name": [
            "INR",
            "USDT"
        ],
    }

    return auth_request(
        "POST",
        "/exchange/v1/derivatives/futures/positions",
        body=body
    )


def calculate_current_equity():
    wallets = get_futures_wallets()

    if not isinstance(wallets, list):
        return None

    conversion = get_usdt_inr()

    if conversion is None or conversion <= 0:
        return None

    equity_inr = 0.0

    for wallet in wallets:
        currency = wallet.get(
            "currency_short_name"
        )

        try:
            balance = float(
                wallet.get("balance", 0) or 0
            )

            locked = float(
                wallet.get("locked_balance", 0) or 0
            )

            total = balance + locked

            if currency == "INR":
                equity_inr += total

            elif currency == "USDT":
                equity_inr += total * conversion

        except Exception:
            continue

    # Add unrealized PNL where the API exposes it.
    positions = get_positions()

    if isinstance(positions, list):
        for p in positions:
            try:
                active_pos = float(
                    p.get("active_pos", 0) or 0
                )

                if abs(active_pos) <= 0:
                    continue

                pnl = p.get("pnl")

                if pnl is not None:
                    equity_inr += (
                        float(pnl) * conversion
                    )

            except Exception:
                continue

    if equity_inr <= 0:
        return None

    return equity_inr


# ============================================================
# 15. TRANSACTION HISTORY
# ============================================================

def get_transactions():
    body = {
        "stage": "all",
        "page": "1",
        "size": "1000",
        "margin_currency_short_name": [
            "INR",
            "USDT"
        ],
    }

    return auth_request(
        "POST",
        "/exchange/v1/derivatives/futures/positions/transactions",
        body=body
    )


# ============================================================
# 16. ACCOUNT CIRCUIT BREAKERS
# ============================================================

def update_account_state(current_equity):
    now = datetime.now(IST)

    today = now.strftime("%Y-%m-%d")

    if STATE.get("daily_date") != today:
        STATE["daily_date"] = today
        STATE["daily_start_equity"] = current_equity

    month_key = now.strftime("%Y-%m")

    if STATE.get("monthly_key") != month_key:
        STATE["monthly_key"] = month_key
        STATE["monthly_start_equity"] = current_equity

    save_state()


def account_circuit_breakers(current_equity):
    failures = []

    if current_equity is None:
        failures.append(
            "Current equity unavailable"
        )
        return failures

    update_account_state(current_equity)

    daily_start = STATE.get(
        "daily_start_equity"
    )

    monthly_start = STATE.get(
        "monthly_start_equity"
    )

    if daily_start:
        daily_drawdown = (
            daily_start - current_equity
        ) / daily_start

        if daily_drawdown >= DAILY_LOSS_PERCENT:
            failures.append(
                "DAILY CIRCUIT BREAKER ACTIVE"
            )

    if monthly_start:
        monthly_drawdown = (
            monthly_start - current_equity
        ) / monthly_start

        if monthly_drawdown >= MONTHLY_STOP_PERCENT:
            failures.append(
                "MONTHLY 10% STOP ACTIVE"
            )

    transactions = get_transactions()

    if not isinstance(transactions, list):
        failures.append(
            "Transaction history unavailable"
        )
        return failures

    now = time.time()

    # 24-hour cooldown after a losing closed trade
    for tx in transactions:
        try:
            created = float(
                tx.get("created_at", 0)
            ) / 1000.0

            if now - created > 86400:
                continue

            stage = str(
                tx.get("stage", "")
            ).lower()

            if stage not in [
                "exit",
                "tpsl_exit",
                "liquidation",
                "liquidate",
            ]:
                continue

            amount = float(
                tx.get("amount", 0) or 0
            )

            fee = float(
                tx.get("fee_amount", 0) or 0
            )

            net = amount - fee

            if net < 0:
                failures.append(
                    "24-HOUR LOSS COOLDOWN ACTIVE"
                )
                break

        except Exception:
            continue

    # Rolling 30-day trade count
    cutoff_ms = (
        int(time.time() * 1000)
        - 30 * 86400 * 1000
    )

    trade_ids = set()

    for tx in transactions:
        try:
            created = int(
                tx.get("created_at", 0)
            )

            if created < cutoff_ms:
                continue

            stage = str(
                tx.get("stage", "")
            ).lower()

            if stage in [
                "exit",
                "tpsl_exit",
                "liquidation",
                "liquidate",
            ]:
                parent = (
                    tx.get("parent_id")
                    or tx.get("position_id")
                )

                if parent:
                    trade_ids.add(
                        str(parent)
                    )

        except Exception:
            continue

    if len(trade_ids) >= MAX_TRADES_30D:
        failures.append(
            "20-TRADE ROLLING 30-DAY LIMIT REACHED"
        )

    return failures


# ============================================================
# 17. BTC DATA
# ============================================================

def calculate_atr(df, period=14):
    if df is None or len(df) < period + 2:
        return None

    previous_close = df["close"].shift(1)

    tr1 = df["high"] - df["low"]

    tr2 = (
        df["high"] - previous_close
    ).abs()

    tr3 = (
        df["low"] - previous_close
    ).abs()

    tr = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    atr = tr.rolling(period).mean()

    value = atr.iloc[-1]

    return (
        float(value)
        if pd.notna(value)
        else None
    )


def btc_market_regime():
    btc_4h = get_completed_candles(
        BTC_PAIR,
        "4h",
        240
    )

    btc_1h = get_completed_candles(
        BTC_PAIR,
        "1h",
        120
    )

    btc_15m = get_completed_candles(
        BTC_PAIR,
        "15m",
        72
    )

    if any(
        x is None
        for x in [
            btc_4h,
            btc_1h,
            btc_15m
        ]
    ):
        return {
            "valid": False,
            "reason": "BTC candle data unavailable",
        }

    if len(btc_4h) < 30:
        return {
            "valid": False,
            "reason": "BTC 4H data insufficient",
        }

    latest_4h = btc_4h.iloc[-1]
    latest_1h = btc_1h.iloc[-1]

    atr = calculate_atr(
        btc_4h,
        14
    )

    if atr is None:
        return {
            "valid": False,
            "reason": "BTC ATR unavailable",
        }

    atr_percent = (
        atr / latest_4h["close"]
    ) * 100

    one_hour_range_percent = (
        (
            latest_1h["high"]
            - latest_1h["low"]
        )
        / latest_1h["open"]
    ) * 100

    one_hour_body_percent = (
        abs(
            latest_1h["close"]
            - latest_1h["open"]
        )
        / latest_1h["open"]
    ) * 100

    if atr_percent > GLOBAL_BTC_4H_ATR_PERCENT:
        return {
            "valid": True,
            "global_wait": True,
            "reason": (
                f"BTC 4H ATR {atr_percent:.2f}% "
                f"> {GLOBAL_BTC_4H_ATR_PERCENT}%"
            ),
            "zone": "GLOBAL_WAIT",
        }

    if (
        one_hour_range_percent
        > GLOBAL_BTC_1H_MOVE_PERCENT
        or one_hour_body_percent
        > GLOBAL_BTC_1H_MOVE_PERCENT
    ):
        return {
            "valid": True,
            "global_wait": True,
            "reason": (
                f"BTC 1H movement "
                f"{max(one_hour_range_percent, one_hour_body_percent):.2f}% "
                f"> {GLOBAL_BTC_1H_MOVE_PERCENT}%"
            ),
            "zone": "GLOBAL_WAIT",
        }

    # Trend structure
    close_4h = btc_4h["close"]

    ema20_4h = (
        close_4h.ewm(span=20).mean().iloc[-1]
    )

    ema50_4h = (
        close_4h.ewm(span=50).mean().iloc[-1]
    )

    close_1h = btc_1h["close"]

    ema20_1h = (
        close_1h.ewm(span=20).mean().iloc[-1]
    )

    ema50_1h = (
        close_1h.ewm(span=50).mean().iloc[-1]
    )

    bull_structure = (
        latest_4h["close"] > ema20_4h
        and ema20_4h > ema50_4h
        and latest_1h["close"] > ema20_1h
        and ema20_1h > ema50_1h
    )

    bear_structure = (
        latest_4h["close"] < ema20_4h
        and ema20_4h < ema50_4h
        and latest_1h["close"] < ema20_1h
        and ema20_1h < ema50_1h
    )

    # Zone logic uses ONLY completed 1H candle.
    close_1h_value = float(
        latest_1h["close"]
    )

    low_1h_value = float(
        latest_1h["low"]
    )

    high_1h_value = float(
        latest_1h["high"]
    )

    candle_time = int(
        latest_1h["time"]
    )

    zone = "CHOP_ZONE"

    if low_1h_value <= ZONE_DANGER:
        zone = "ZONE_3_DANGER"

    elif close_1h_value < ZONE_BEAR:
        zone = "ZONE_2_BEAR"

    elif close_1h_value > ZONE_BULL:
        zone = "ZONE_1_BULL"

    fakeout = None

    if (
        high_1h_value > ZONE_BULL
        and close_1h_value <= ZONE_BULL
    ):
        fakeout = "BULL_FAKEOUT"

    elif (
        low_1h_value < ZONE_BEAR
        and close_1h_value >= ZONE_BEAR
    ):
        fakeout = "BEAR_FAKEOUT"

    return {
        "valid": True,
        "global_wait": False,
        "zone": zone,
        "fakeout": fakeout,
        "candle_time": candle_time,
        "btc_1h_close": close_1h_value,
        "btc_1h_low": low_1h_value,
        "btc_1h_high": high_1h_value,
        "atr_4h": atr,
        "atr_4h_percent": atr_percent,
        "one_hour_range_percent":
            one_hour_range_percent,
        "bull_structure": bull_structure,
        "bear_structure": bear_structure,
    }


# ============================================================
# 18. PIVOT / STRUCTURAL LEVELS
# ============================================================

def pivot_levels(df, left=2, right=2):
    highs = []
    lows = []

    if df is None:
        return highs, lows

    if len(df) < left + right + 5:
        return highs, lows

    for i in range(
        left,
        len(df) - right
    ):
        high = float(
            df.iloc[i]["high"]
        )

        low = float(
            df.iloc[i]["low"]
        )

        left_highs = df.iloc[
            i-left:i
        ]["high"]

        right_highs = df.iloc[
            i+1:i+right+1
        ]["high"]

        left_lows = df.iloc[
            i-left:i
        ]["low"]

        right_lows = df.iloc[
            i+1:i+right+1
        ]["low"]

        if (
            high > float(left_highs.max())
            and high > float(right_highs.max())
        ):
            highs.append(high)

        if (
            low < float(left_lows.min())
            and low < float(right_lows.min())
        ):
            lows.append(low)

    return highs, lows


def unique_sorted_levels(levels):
    levels = sorted(
        set(
            round(float(x), 10)
            for x in levels
            if x is not None
            and math.isfinite(float(x))
        )
    )

    return levels


# ============================================================
# 19. RSI
# ============================================================

def calculate_rsi(series, period=14):
    delta = series.diff()

    gain = delta.clip(lower=0)

    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(
        period
    ).mean()

    avg_loss = loss.rolling(
        period
    ).mean()

    rs = avg_gain / avg_loss.replace(
        0,
        math.nan
    )

    rsi = 100 - (
        100 / (1 + rs)
    )

    return rsi


# ============================================================
# 20. CANDIDATE STRUCTURE
# ============================================================

def candidate_structure(pair):
    df_4h = get_completed_candles(
        pair,
        "4h",
        240
    )

    df_1h = get_completed_candles(
        pair,
        "1h",
        120
    )

    df_15m = get_completed_candles(
        pair,
        "15m",
        72
    )

    if any(
        x is None
        for x in [
            df_4h,
            df_1h,
            df_15m
        ]
    ):
        return None

    if min(
        len(df_4h),
        len(df_1h),
        len(df_15m)
    ) < 30:
        return None

    # -----------------------------
    # 4H structure
    # -----------------------------

    ema20_4h = (
        df_4h["close"]
        .ewm(span=20)
        .mean()
        .iloc[-1]
    )

    ema50_4h = (
        df_4h["close"]
        .ewm(span=50)
        .mean()
        .iloc[-1]
    )

    # -----------------------------
    # 1H structure
    # -----------------------------

    ema20_1h = (
        df_1h["close"]
        .ewm(span=20)
        .mean()
        .iloc[-1]
    )

    ema50_1h = (
        df_1h["close"]
        .ewm(span=50)
        .mean()
        .iloc[-1]
    )

    rsi_1h = calculate_rsi(
        df_1h["close"]
    ).iloc[-1]

    # -----------------------------
    # 15M confirmation
    # -----------------------------

    latest = df_15m.iloc[-1]

    previous = df_15m.iloc[-2]

    previous_20 = df_15m.iloc[
        -21:-1
    ]

    resistance_15 = float(
        previous_20["high"].max()
    )

    support_15 = float(
        previous_20["low"].min()
    )

    volume_average = float(
        df_15m["volume"]
        .rolling(20)
        .mean()
        .iloc[-1]
    )

    volume_confirmed = (
        float(latest["volume"])
        >= volume_average * 1.10
    )

    bullish_15 = (
        latest["close"]
        > resistance_15
        and latest["close"]
        > latest["open"]
        and volume_confirmed
    )

    bearish_15 = (
        latest["close"]
        < support_15
        and latest["close"]
        < latest["open"]
        and volume_confirmed
    )

    # -----------------------------
    # Pivots
    # -----------------------------

    highs_4h, lows_4h = pivot_levels(
        df_4h,
        2,
        2
    )

    highs_1h, lows_1h = pivot_levels(
        df_1h,
        2,
        2
    )

    highs_15m, lows_15m = pivot_levels(
        df_15m,
        2,
        2
    )

    resistance_levels = unique_sorted_levels(
        highs_4h
        + highs_1h
        + highs_15m
    )

    support_levels = unique_sorted_levels(
        lows_4h
        + lows_1h
        + lows_15m
    )

    return {
        "df_4h": df_4h,
        "df_1h": df_1h,
        "df_15m": df_15m,

        "ema20_4h": float(ema20_4h),
        "ema50_4h": float(ema50_4h),

        "ema20_1h": float(ema20_1h),
        "ema50_1h": float(ema50_1h),

        "rsi_1h": float(rsi_1h)
        if pd.notna(rsi_1h)
        else None,

        "latest_15m": latest,
        "previous_15m": previous,

        "bullish_15": bullish_15,
        "bearish_15": bearish_15,

        "resistance_levels":
            resistance_levels,

        "support_levels":
            support_levels,

        "volume_confirmed":
            volume_confirmed,
    }


# ============================================================
# 21. NEWS
# ============================================================

NEWS_FEEDS = [
    (
        "CoinDesk",
        "https://www.coindesk.com/arc/outboundfeeds/rss/"
    ),
    (
        "Cointelegraph",
        "https://cointelegraph.com/rss"
    ),
    (
        "Decrypt",
        "https://decrypt.co/feed"
    ),
]


HIGH_IMPACT_KEYWORDS = [
    "hack",
    "exploit",
    "attack",
    "bankruptcy",
    "insolvency",
    "sec",
    "regulation",
    "regulatory",
    "lawsuit",
    "ban",
    "banned",
    "sanction",
    "etf",
    "delist",
    "delisting",
    "listing",
    "liquidation",
    "liquidations",
    "stablecoin",
    "depeg",
    "exchange halt",
    "exchange outage",
    "bitcoin reserve",
    "ethereum",
    "bitcoin",
    "crypto crash",
]


def parse_rss_datetime(value):
    if not value:
        return None

    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(
            value
        ).astimezone(
            timezone.utc
        )

    except Exception:
        return None


def get_news():
    articles = []

    for source, url in NEWS_FEEDS:
        try:
            r = SESSION.get(
                url,
                timeout=DATA_TIMEOUT_SECONDS
            )

            if r.status_code != 200:
                continue

            root = ET.fromstring(
                r.content
            )

            for item in root.findall(
                ".//item"
            ):

                title = item.findtext(
                    "title",
                    default=""
                )

                pub = item.findtext(
                    "pubDate",
                    default=""
                )

                link = item.findtext(
                    "link",
                    default=""
                )

                dt = parse_rss_datetime(
                    pub
                )

                if dt is None:
                    continue

                articles.append({
                    "source": source,
                    "title": html.unescape(
                        title
                    ),
                    "link": link,
                    "time": dt,
                })

        except Exception as e:
            print(
                f"[NEWS ERROR] {source}: {e}"
            )

    return articles


def news_filter(pair):
    articles = get_news()

    if not articles:
        return {
            "pass": False,
            "reason":
                "News sources unavailable",
            "items": [],
        }

    now = utc_now()

    recent = []

    coin = pair.replace(
        "B-",
        ""
    ).replace(
        "_USDT",
        ""
    )

    related_words = [
        coin.lower(),
        "bitcoin",
        "crypto",
        "cryptocurrency",
        "market",
    ]

    for article in articles:
        age = (
            now - article["time"]
        ).total_seconds()

        if age < 0:
            continue

        if age <= NEWS_WINDOW_HOURS * 3600:
            text = (
                article["title"]
                .lower()
            )

            related = any(
                word in text
                for word in related_words
            )

            high_impact = any(
                word in text
                for word
                in HIGH_IMPACT_KEYWORDS
            )

            if related and high_impact:
                recent.append(
                    article
                )

    if recent:
        return {
            "pass": False,
            "reason":
                "Potential high-impact news detected",
            "items": recent[:5],
        }

    return {
        "pass": True,
        "reason":
            "No matching high-impact news in checked window",
        "items": [],
    }


# ============================================================
# 22. FUNDING / OI / POSITIONING
# ============================================================

def get_pair_stats(pair):
    body = {}

    url = (
        "/api/v1/derivatives/"
        f"futures/data/stats?pair={pair}"
    )

    data = auth_request(
        "POST",
        url,
        body=body
    )

    return data if isinstance(
        data,
        dict
    ) else None


def funding_oi_filter(pair):
    market = get_current_market(pair)

    if market is None:
        return {
            "pass": False,
            "reason":
                "Funding/current futures data unavailable",
        }

    funding = market.get("funding")

    if funding is None:
        return {
            "pass": False,
            "reason":
                "Funding unavailable",
        }

    stats = get_pair_stats(pair)

    if stats is None:
        return {
            "pass": False,
            "reason":
                "Funding/OI positioning data unavailable",
        }

    position = stats.get(
        "position"
    )

    if not isinstance(
        position,
        dict
    ):
        return {
            "pass": False,
            "reason":
                "Positioning data unavailable",
        }

    # IMPORTANT:
    # CoinDCX documented stats expose long/short positioning,
    # but that is NOT the same as exchange-wide Open Interest.
    #
    # V5.5 says:
    # UNKNOWN = FAIL
    #
    # Therefore we deliberately do NOT pretend positioning = OI.

    return {
        "pass": False,
        "reason":
            "True exchange-wide OI is not exposed by the verified CoinDCX endpoint; V5.5 requires OI verification",
        "funding": funding,
        "positioning": position,
    }


# ============================================================
# 23. ABNORMAL FLOW / WHALE FILTER
# ============================================================

def abnormal_flow_filter(pair):
    orderbook = get_orderbook(pair)

    if orderbook is None:
        return {
            "pass": False,
            "reason":
                "Orderbook unavailable",
        }

    metrics = orderbook_metrics(
        orderbook
    )

    if metrics is None:
        return {
            "pass": False,
            "reason":
                "Orderbook metrics unavailable",
        }

    if metrics["spread_percent"] > 0.30:
        return {
            "pass": False,
            "reason":
                f"Spread too wide: {metrics['spread_percent']:.3f}%",
        }

    trades = get_recent_trades(pair)

    if trades is None:
        return {
            "pass": False,
            "reason":
                "Recent trade-flow data unavailable",
        }

    if not isinstance(
        trades,
        list
    ) or len(trades) < 10:
        return {
            "pass": False,
            "reason":
                "Insufficient recent trade-flow data",
        }

    recent = []

    cutoff = now_ms() - 15 * 60 * 1000

    for t in trades:
        try:
            timestamp = int(
                t.get(
                    "timestamp",
                    t.get("T", 0)
                )
            )

            if timestamp < cutoff:
                continue

            price = float(
                t.get(
                    "price",
                    t.get("p", 0)
                )
            )

            qty = float(
                t.get(
                    "quantity",
                    t.get("q", 0)
                )
            )

            if price > 0 and qty > 0:
                recent.append(
                    (price, qty)
                )

        except Exception:
            continue

    if len(recent) < 5:
        return {
            "pass": False,
            "reason":
                "Insufficient fresh trade-flow data",
        }

    notionals = [
        p * q
        for p, q in recent
    ]

    median_notional = sorted(
        notionals
    )[len(notionals) // 2]

    largest = max(
        notionals
    )

    # Conservative abnormal-print test.
    if (
        median_notional > 0
        and largest
        > median_notional * 100
    ):
        return {
            "pass": False,
            "reason":
                "Extreme recent trade-size anomaly detected",
        }

    return {
        "pass": True,
        "reason":
            "Orderbook and recent trade-flow checks clean",
        "spread":
            metrics["spread_percent"],
        "bid_depth":
            metrics["bid_depth"],
        "ask_depth":
            metrics["ask_depth"],
    }


# ============================================================
# 24. 15-MINUTE CONFIRMATION
# ============================================================

def confirmation_15m(structure, direction):
    latest = structure["latest_15m"]

    now = time.time()

    close_time = (
        float(latest["time"]) / 1000
        + 900
    )

    if close_time > now:
        return False, (
            "15M candle is incomplete"
        )

    if not structure[
        "volume_confirmed"
    ]:
        return False, (
            "15M volume confirmation failed"
        )

    if direction == "LONG":
        if not structure["bullish_15"]:
            return False, (
                "15M bullish breakout confirmation failed"
            )

        return True, (
            "Closed 15M bullish confirmation"
        )

    if direction == "SHORT":
        if not structure["bearish_15"]:
            return False, (
                "15M bearish breakdown confirmation failed"
            )

        return True, (
            "Closed 15M bearish confirmation"
        )

    return False, "Unknown direction"


# ============================================================
# 25. STRUCTURAL INVALIDATION
# ============================================================

def get_invalidation(structure, direction, entry):
    df_15 = structure["df_15m"]
    df_1h = structure["df_1h"]

    if direction == "LONG":

        lows_15 = [
            x for x
            in structure["support_levels"]
            if x < entry
        ]

        lows_1h = [
            x for x
            in pivot_levels(
                df_1h,
                2,
                2
            )[1]
            if x < entry
        ]

        candidates = (
            lows_15
            + lows_1h
        )

        if not candidates:
            return None

        return max(candidates)

    if direction == "SHORT":

        highs_15 = [
            x for x
            in structure["resistance_levels"]
            if x > entry
        ]

        highs_1h = [
            x for x
            in pivot_levels(
                df_1h,
                2,
                2
            )[0]
            if x > entry
        ]

        candidates = (
            highs_15
            + highs_1h
        )

        if not candidates:
            return None

        return min(candidates)

    return None


# ============================================================
# 26. STRUCTURAL TARGETS
# ============================================================

def structural_targets(
    structure,
    direction,
    entry,
    final_sl
):
    risk_distance = abs(
        entry - final_sl
    )

    if risk_distance <= 0:
        return None

    if direction == "LONG":

        levels = [
            x for x
            in structure["resistance_levels"]
            if x > entry
        ]

        levels = sorted(
            set(levels)
        )

        tp1_candidates = [
            x for x in levels
            if x >= (
                entry
                + risk_distance * 1.5
            )
        ]

        tp2_candidates = [
            x for x in levels
            if x >= (
                entry
                + risk_distance * 2.0
            )
        ]

        if not tp1_candidates:
            return None

        if not tp2_candidates:
            return None

        tp1 = tp1_candidates[0]

        tp2 = tp2_candidates[0]

        if tp2 <= tp1:
            return None

        return tp1, tp2

    if direction == "SHORT":

        levels = [
            x for x
            in structure["support_levels"]
            if x < entry
        ]

        levels = sorted(
            set(levels),
            reverse=True
        )

        tp1_candidates = [
            x for x in levels
            if x <= (
                entry
                - risk_distance * 1.5
            )
        ]

        tp2_candidates = [
            x for x in levels
            if x <= (
                entry
                - risk_distance * 2.0
            )
        ]

        if not tp1_candidates:
            return None

        if not tp2_candidates:
            return None

        tp1 = tp1_candidates[0]

        tp2 = tp2_candidates[0]

        if tp2 >= tp1:
            return None

        return tp1, tp2

    return None


# ============================================================
# 27. LIQUIDATION ESTIMATION
# ============================================================

def maintenance_margin_for_notional(
    notional_usdt,
    instrument
):
    schedule = instrument.get(
        "dynamic_safety_margin_details"
    )

    if not isinstance(
        schedule,
        dict
    ):
        return None

    try:
        brackets = sorted(
            [
                (
                    float(k),
                    float(v)
                )
                for k, v in schedule.items()
            ],
            key=lambda x: x[0]
        )

        remaining = notional_usdt
        maintenance = 0.0

        previous = 0.0

        for upper, rate_percent in brackets:

            portion = min(
                max(
                    remaining,
                    0
                ),
                upper - previous
            )

            if portion > 0:
                maintenance += (
                    portion
                    * rate_percent
                    / 100.0
                )

                remaining -= portion

            previous = upper

            if remaining <= 0:
                break

        if remaining > 0:
            return None

        return maintenance

    except Exception:
        return None


def estimated_liquidation(
    direction,
    entry,
    quantity,
    leverage,
    instrument
):
    if quantity <= 0:
        return None

    notional = (
        entry * quantity
    )

    maintenance = (
        maintenance_margin_for_notional(
            notional,
            instrument
        )
    )

    if maintenance is None:
        return None

    initial_margin = (
        notional / leverage
    )

    available_before_liq = (
        initial_margin
        - maintenance
    )

    if available_before_liq <= 0:
        return None

    move = (
        available_before_liq
        / quantity
    )

    if direction == "LONG":
        liq = entry - move
    else:
        liq = entry + move

    if liq <= 0:
        return None

    return liq


# ============================================================
# 28. RISK ENGINE
# ============================================================

def floor_to_increment(
    value,
    increment
):
    if increment <= 0:
        return value

    return (
        math.floor(
            value / increment
        )
        * increment
    )


def calculate_risk(
    pair,
    direction,
    entry,
    final_sl,
    equity_inr,
    instrument,
    orderbook
):
    conversion = get_usdt_inr()

    if conversion is None:
        return None

    max_risk_inr = (
        equity_inr
        * MAX_RISK_PERCENT
    )

    price_distance = abs(
        entry - final_sl
    )

    if price_distance <= 0:
        return None

    try:
        quantity_increment = float(
            instrument.get(
                "quantity_increment",
                0
            )
            or 0
        )

        min_quantity = float(
            instrument.get(
                "min_quantity",
                0
            )
            or 0
        )

        min_notional = float(
            instrument.get(
                "min_notional",
                0
            )
            or 0
        )

        taker_fee_percent = float(
            instrument.get(
                "taker_fee",
                0
            )
            or 0
        )

    except Exception:
        return None

    # Initial conservative quantity.
    fee_rate = (
        taker_fee_percent
        / 100.0
    )

    # Slippage estimate from order-book spread.
    metrics = orderbook_metrics(
        orderbook
    )

    if metrics is None:
        return None

    spread = (
        metrics["spread_percent"]
        / 100.0
    )

    estimated_slippage_rate = max(
        spread,
        0.0005
    )

    # Two-sided fee estimate:
    # entry + stop execution.
    per_unit_fee_usdt = (
        (entry + final_sl)
        * fee_rate
    )

    per_unit_slippage_usdt = (
        entry
        * estimated_slippage_rate
        + final_sl
        * estimated_slippage_rate
    )

    per_unit_total_risk_usdt = (
        price_distance
        + per_unit_fee_usdt
        + per_unit_slippage_usdt
    )

    if per_unit_total_risk_usdt <= 0:
        return None

    max_risk_usdt = (
        max_risk_inr
        / conversion
    )

    quantity = (
        max_risk_usdt
        / per_unit_total_risk_usdt
    )

    if quantity_increment > 0:
        quantity = floor_to_increment(
            quantity,
            quantity_increment
        )

    if quantity <= 0:
        return None

    if min_quantity > 0:
        if quantity < min_quantity:
            return None

    notional = (
        entry * quantity
    )

    if min_notional > 0:
        if notional < min_notional:
            return None

    margin_usdt = (
        notional
        / PREFERRED_LEVERAGE
    )

    margin_inr = (
        margin_usdt
        * conversion
    )

    stop_risk_usdt = (
        price_distance
        * quantity
    )

    fees_usdt = (
        (entry + final_sl)
        * quantity
        * fee_rate
    )

    slippage_usdt = (
        (
            entry
            + final_sl
        )
        * quantity
        * estimated_slippage_rate
    )

    funding_rate = None

    market = get_current_market(
        pair
    )

    if market:
        funding_rate = market.get(
            "funding"
        )

    # One funding interval as conservative
    # material-funding allowance.
    funding_usdt = 0.0

    if funding_rate is not None:
        funding_usdt = abs(
            notional
            * funding_rate
        )

    total_planned_usdt = (
        stop_risk_usdt
        + fees_usdt
        + slippage_usdt
        + funding_usdt
    )

    total_planned_inr = (
        total_planned_usdt
        * conversion
    )

    if total_planned_inr > max_risk_inr:
        return None

    liquidation = estimated_liquidation(
        direction,
        entry,
        quantity,
        PREFERRED_LEVERAGE,
        instrument
    )

    if liquidation is None:
        return None

    # Liquidation must be materially beyond SL.
    if direction == "LONG":
        if liquidation >= final_sl:
            return None
    else:
        if liquidation <= final_sl:
            return None

    return {
        "quantity": quantity,
        "notional_usdt": notional,
        "notional_inr":
            notional * conversion,
        "margin_usdt": margin_usdt,
        "margin_inr": margin_inr,
        "stop_risk_inr":
            stop_risk_usdt * conversion,
        "fees_inr":
            fees_usdt * conversion,
        "slippage_inr":
            slippage_usdt * conversion,
        "funding_inr":
            funding_usdt * conversion,
        "total_planned_risk_inr":
            total_planned_inr,
        "max_allowed_risk_inr":
            max_risk_inr,
        "liquidation":
            liquidation,
        "conversion":
            conversion,
        "fee_rate":
            fee_rate,
        "slippage_rate":
            estimated_slippage_rate,
        "funding_rate":
            funding_rate,
    }


# ============================================================
# 29. ENTRY
# ============================================================

def get_entry(pair, direction):
    orderbook = get_orderbook(pair)

    if orderbook is None:
        return None, None

    metrics = orderbook_metrics(
        orderbook
    )

    if metrics is None:
        return None, None

    if direction == "LONG":
        return (
            metrics["best_ask"],
            orderbook
        )

    if direction == "SHORT":
        return (
            metrics["best_bid"],
            orderbook
        )

    return None, None


# ============================================================
# 30. GATE 1
# ============================================================

def gate1_data(pair):
    market = get_current_market(
        pair
    )

    if market is None:
        return False, (
            "Current futures market data unavailable"
        )

    if market.get("last") is None:
        return False, (
            "Current price unavailable"
        )

    if market.get("mark") is None:
        return False, (
            "Mark price unavailable"
        )

    if market.get("timestamp", 0) <= 0:
        return False, (
            "Current market timestamp unavailable"
        )

    age = (
        now_ms()
        - market["timestamp"]
    ) / 1000

    if age > MAX_CANDLE_STALENESS_SECONDS:
        return False, (
            f"Current market data stale: {age:.1f}s"
        )

    orderbook = get_orderbook(
        pair
    )

    if orderbook is None:
        return False, (
            "Orderbook unavailable"
        )

    if orderbook_metrics(
        orderbook
    ) is None:
        return False, (
            "Orderbook invalid"
        )

    return True, "Fresh market data verified"


# ============================================================
# 31. G2
# ============================================================

def gate2_btc(btc):
    if not btc.get("valid"):
        return False, btc.get(
            "reason",
            "BTC data invalid"
        )

    if btc.get("global_wait"):
        return False, (
            btc.get(
                "reason",
                "BTC volatility shutdown"
            )
        )

    return True, (
        "BTC regime and volatility compatible"
    )


# ============================================================
# 32. G3
# ============================================================

def gate3_structure(
    structure,
    direction
):
    if structure is None:
        return False, (
            "Candidate structure unavailable"
        )

    if direction == "LONG":
        if not (
            structure["ema20_4h"]
            > structure["ema50_4h"]
        ):
            return False, (
                "4H bullish structure failed"
            )

        if not (
            structure["ema20_1h"]
            > structure["ema50_1h"]
        ):
            return False, (
                "1H bullish structure failed"
            )

        if (
            structure["rsi_1h"] is None
            or structure["rsi_1h"] < 50
        ):
            return False, (
                "1H momentum insufficient for LONG"
            )

    else:
        if not (
            structure["ema20_4h"]
            < structure["ema50_4h"]
        ):
            return False, (
                "4H bearish structure failed"
            )

        if not (
            structure["ema20_1h"]
            < structure["ema50_1h"]
        ):
            return False, (
                "1H bearish structure failed"
            )

        if (
            structure["rsi_1h"] is None
            or structure["rsi_1h"] > 50
        ):
            return False, (
                "1H momentum insufficient for SHORT"
            )

    return True, (
        "4H/1H structure and momentum verified"
    )


# ============================================================
# 33. G4
# ============================================================

def gate4_independent(
    structure,
    direction
):
    if direction == "LONG":
        if not structure["bullish_15"]:
            return False, (
                "Independent LONG case not confirmed"
            )

        return True, (
            "Independent LONG case qualifies"
        )

    if direction == "SHORT":
        if not structure["bearish_15"]:
            return False, (
                "Independent SHORT case not confirmed"
            )

        return True, (
            "Independent SHORT case qualifies"
        )

    return False, "Invalid direction"


# ============================================================
# 34. G5
# ============================================================

def gate5_entry_sl(
    direction,
    entry,
    structural_invalidation
):
    if entry is None:
        return False, None, (
            "Entry unavailable"
        )

    if structural_invalidation is None:
        return False, None, (
            "Structural invalidation unavailable"
        )

    if direction == "LONG":

        if structural_invalidation >= entry:
            return False, None, (
                "LONG invalidation is not below entry"
            )

        final_sl = (
            structural_invalidation
            * (1 - WICK_BUFFER)
        )

        if final_sl >= entry:
            return False, None, (
                "LONG buffered SL invalid"
            )

    else:

        if structural_invalidation <= entry:
            return False, None, (
                "SHORT invalidation is not above entry"
            )

        final_sl = (
            structural_invalidation
            * (1 + WICK_BUFFER)
        )

        if final_sl <= entry:
            return False, None, (
                "SHORT buffered SL invalid"
            )

    return True, final_sl, (
        "Structural invalidation and 0.8% buffer verified"
    )


# ============================================================
# 35. G6
# ============================================================

def gate6_targets(
    structure,
    direction,
    entry,
    final_sl
):
    targets = structural_targets(
        structure,
        direction,
        entry,
        final_sl
    )

    if targets is None:
        return False, None, None, (
            "No genuine structural TP1/TP2 satisfying 1.5R/2R"
        )

    tp1, tp2 = targets

    risk = abs(
        entry - final_sl
    )

    rr1 = abs(
        tp1 - entry
    ) / risk

    rr2 = abs(
        tp2 - entry
    ) / risk

    if rr1 < 1.5:
        return False, None, None, (
            "TP1 below 1.5R"
        )

    if rr2 < 2.0:
        return False, None, None, (
            "TP2 below genuine 2R"
        )

    return True, tp1, tp2, (
        "Structural TP1 and TP2 verified"
    )


# ============================================================
# 36. G8
# ============================================================

def gate8_news(pair):
    result = news_filter(
        pair
    )

    return (
        result["pass"],
        result["reason"]
    )


# ============================================================
# 37. G9
# ============================================================

def gate9_flow(pair):
    result = abnormal_flow_filter(
        pair
    )

    return (
        result["pass"],
        result["reason"]
    )


# ============================================================
# 38. G10
# ============================================================

def gate10_funding_oi(pair):
    result = funding_oi_filter(
        pair
    )

    return (
        result["pass"],
        result["reason"]
    )


# ============================================================
# 39. G11
# ============================================================

def gate11_15m(
    structure,
    direction
):
    return confirmation_15m(
        structure,
        direction
    )


# ============================================================
# 40. G12
# ============================================================

def gate12_adversarial(
    pair,
    direction,
    entry,
    final_sl,
    tp1,
    tp2,
    btc,
    structure,
    risk
):
    failures = []

    if direction == "LONG":

        if btc.get(
            "bear_structure"
        ):
            failures.append(
                "BTC 4H/1H bearish structure conflicts with LONG"
            )

        if entry >= tp1:
            failures.append(
                "Entry is already beyond TP1"
            )

    else:

        if btc.get(
            "bull_structure"
        ):
            failures.append(
                "BTC 4H/1H bullish structure conflicts with SHORT"
            )

        if entry <= tp1:
            failures.append(
                "Entry is already beyond TP1"
            )

    if tp2 is None:
        failures.append(
            "TP2 unavailable"
        )

    if risk is None:
        failures.append(
            "Risk verification unavailable"
        )

    if failures:
        return False, "; ".join(
            failures
        )

    return True, (
        "Adversarial verification found no unresolved material conflict"
    )


# ============================================================
# 41. SETUP ID
# ============================================================

def setup_id(
    pair,
    direction,
    entry,
    final_sl,
    tp2
):
    raw = (
        f"{pair}|{direction}|"
        f"{entry:.10f}|"
        f"{final_sl:.10f}|"
        f"{tp2:.10f}"
    )

    return hashlib.sha256(
        raw.encode()
    ).hexdigest()[:20]


def already_sent(setup):
    return setup in STATE[
        "sent_setup_ids"
    ]


def remember_setup(setup):
    STATE[
        "sent_setup_ids"
    ].append(setup)

    # Keep state manageable.
    STATE[
        "sent_setup_ids"
    ] = STATE[
        "sent_setup_ids"
    ][-500:]

    save_state()


# ============================================================
# 42. FULL V5.5 CANDIDATE ANALYSIS
# ============================================================

def analyze_candidate(
    pair,
    direction,
    btc,
    current_equity
):
    gates = {}

    # -----------------------------
    # G1
    # -----------------------------

    g1, g1_reason = gate1_data(
        pair
    )

    gates["G1"] = (
        "PASS" if g1 else "FAIL"
    )

    if not g1:
        return None, gates, g1_reason

    # -----------------------------
    # G2
    # -----------------------------

    g2, g2_reason = gate2_btc(
        btc
    )

    gates["G2"] = (
        "PASS" if g2 else "FAIL"
    )

    if not g2:
        return None, gates, g2_reason

    # -----------------------------
    # Structure
    # -----------------------------

    structure = candidate_structure(
        pair
    )

    g3, g3_reason = gate3_structure(
        structure,
        direction
    )

    gates["G3"] = (
        "PASS" if g3 else "FAIL"
    )

    if not g3:
        return None, gates, g3_reason

    # -----------------------------
    # G4
    # -----------------------------

    g4, g4_reason = gate4_independent(
        structure,
        direction
    )

    gates["G4"] = (
        "PASS" if g4 else "FAIL"
    )

    if not g4:
        return None, gates, g4_reason

    # -----------------------------
    # Entry
    # -----------------------------

    entry, orderbook = get_entry(
        pair,
        direction
    )

    if entry is None:
        gates["G5"] = "FAIL"

        return None, gates, (
            "Executable reference entry unavailable"
        )

    structural_invalidation = (
        get_invalidation(
            structure,
            direction,
            entry
        )
    )

    g5, final_sl, g5_reason = (
        gate5_entry_sl(
            direction,
            entry,
            structural_invalidation
        )
    )

    gates["G5"] = (
        "PASS" if g5 else "FAIL"
    )

    if not g5:
        return None, gates, g5_reason

    # -----------------------------
    # G6
    # -----------------------------

    g6, tp1, tp2, g6_reason = (
        gate6_targets(
            structure,
            direction,
            entry,
            final_sl
        )
    )

    gates["G6"] = (
        "PASS" if g6 else "FAIL"
    )

    if not g6:
        return None, gates, g6_reason

    # -----------------------------
    # G7
    # -----------------------------

    instrument = get_instrument(
        pair
    )

    if instrument is None:
        gates["G7"] = "FAIL"

        return None, gates, (
            "Instrument/risk metadata unavailable"
        )

    risk = calculate_risk(
        pair,
        direction,
        entry,
        final_sl,
        current_equity,
        instrument,
        orderbook
    )

    gates["G7"] = (
        "PASS"
        if risk is not None
        else "FAIL"
    )

    if risk is None:
        return None, gates, (
            "Risk, fee, slippage or liquidation verification failed"
        )

    # -----------------------------
    # G8
    # -----------------------------

    g8, g8_reason = gate8_news(
        pair
    )

    gates["G8"] = (
        "PASS" if g8 else "FAIL"
    )

    if not g8:
        return None, gates, g8_reason

    # -----------------------------
    # G9
    # -----------------------------

    g9, g9_reason = gate9_flow(
        pair
    )

    gates["G9"] = (
        "PASS" if g9 else "FAIL"
    )

    if not g9:
        return None, gates, g9_reason

    # -----------------------------
    # G10
    # -----------------------------

    g10, g10_reason = gate10_funding_oi(
        pair
    )

    gates["G10"] = (
        "PASS" if g10 else "FAIL"
    )

    if not g10:
        return None, gates, g10_reason

    # -----------------------------
    # G11
    # -----------------------------

    g11, g11_reason = gate11_15m(
        structure,
        direction
    )

    gates["G11"] = (
        "PASS" if g11 else "FAIL"
    )

    if not g11:
        return None, gates, g11_reason

    # -----------------------------
    # G12
    # -----------------------------

    g12, g12_reason = gate12_adversarial(
        pair,
        direction,
        entry,
        final_sl,
        tp1,
        tp2,
        btc,
        structure,
        risk
    )

    gates["G12"] = (
        "PASS" if g12 else "FAIL"
    )

    if not g12:
        return None, gates, g12_reason

    # -----------------------------
    # Clean Context
    # -----------------------------

    btc_clean = True

    if direction == "LONG":
        if btc.get(
            "bear_structure"
        ):
            btc_clean = False

    if direction == "SHORT":
        if btc.get(
            "bull_structure"
        ):
            btc_clean = False

    if not btc_clean:
        return None, gates, (
            "BTC Clean Context failed"
        )

    # -----------------------------
    # R:R
    # -----------------------------

    risk_distance = abs(
        entry - final_sl
    )

    rr1 = (
        abs(tp1 - entry)
        / risk_distance
    )

    rr2 = (
        abs(tp2 - entry)
        / risk_distance
    )

    # -----------------------------
    # Final consistency
    # -----------------------------

    required_gates = [
        "G1",
        "G2",
        "G3",
        "G4",
        "G5",
        "G6",
        "G7",
        "G8",
        "G9",
        "G10",
        "G11",
        "G12",
    ]

    if any(
        gates.get(g) != "PASS"
        for g in required_gates
    ):
        return None, gates, (
            "Final consistency audit failed"
        )

    return {
        "pair": pair,
        "direction": direction,
        "entry": entry,
        "structural_invalidation":
            structural_invalidation,
        "sl": final_sl,
        "tp1": tp1,
        "tp2": tp2,
        "rr1": rr1,
        "rr2": rr2,
        "risk": risk,
        "gates": gates,
        "btc": btc,
    }, gates, (
        "ALL V5.5 GATES PASSED"
    )


# ============================================================
# 43. READY MESSAGE
# ============================================================

def format_ready(setup, equity):
    pair = setup["pair"]

    coin = pair.replace(
        "B-",
        ""
    ).replace(
        "_USDT",
        ""
    )

    r = setup["risk"]

    return f"""
🟢 READY — A+ SETUP

CHECKLIST VERIFICATION

G1 Data Validity: PASS
G2 BTC Regime: PASS
G3 Candidate Structure: PASS
G4 Long vs Short: PASS
G5 Entry + Invalidation + Buffer: PASS
G6 Structural Target + R:R: PASS
G7 Risk + Size + Fees + Liquidation: PASS
G8 News: PASS
G9 Abnormal Flow/Whale: PASS
G10 Funding + OI + Liquidation: PASS
G11 15M Confirmation: PASS
G12 Adversarial Verification: PASS

CLEAN CONTEXT

BTC Filter: PASS
News Filter: PASS
Whale/Volatility Filter: PASS

TRADE STRUCTURE

Coin: {coin}/USDT

Direction: {setup["direction"]}

Entry: ${setup["entry"]:.8f}

Structural Invalidation:
${setup["structural_invalidation"]:.8f}

SL: ${setup["sl"]:.8f}
[0.8% BUFFER APPLIED]

TP1: ${setup["tp1"]:.8f}

TP2: ${setup["tp2"]:.8f}

R:R:
TP1 = {setup["rr1"]:.2f}R
TP2 = {setup["rr2"]:.2f}R

Leverage: {PREFERRED_LEVERAGE:.0f}x Isolated

Quantity: {r["quantity"]:.8f}

Notional:
USDT {r["notional_usdt"]:.4f}
INR ₹{r["notional_inr"]:.2f}

Margin:
₹{r["margin_inr"]:.2f}

Estimated Fees:
₹{r["fees_inr"]:.2f}

Estimated Slippage:
₹{r["slippage_inr"]:.2f}

Material Funding Impact:
₹{r["funding_inr"]:.2f}

Maximum Planned Risk:
₹{r["total_planned_risk_inr"]:.2f}

Maximum Allowed Risk:
₹{r["max_allowed_risk_inr"]:.2f}

Estimated Liquidation Price:
${r["liquidation"]:.8f}

Current Verified Equity:
₹{equity:.2f}

FINAL CONSISTENCY AUDIT

All required conditions independently verified: YES

AI ANALYSIS STATUS

MAXIMUM VERIFICATION COMPLETED

USER APPROVAL

PENDING — USER MUST SAY GO
""".strip()


# ============================================================
# 44. WAIT MESSAGE
# ============================================================

def format_wait(
    pair,
    direction,
    reason,
    gates=None
):
    gates = gates or {}

    gate_text = "\n".join(
        [
            f"{g}: {gates.get(g, 'NOT CHECKED')}"
            for g in [
                "G1",
                "G2",
                "G3",
                "G4",
                "G5",
                "G6",
                "G7",
                "G8",
                "G9",
                "G10",
                "G11",
                "G12",
            ]
        ]
    )

    return f"""
🔴 WAIT — NO A+ SETUP

Candidate:
{pair}

Direction:
{direction}

Failed Condition:
{reason}

GATE STATUS

{gate_text}

Required action:

NO TRADE

Capital protection overrides opportunity.

UNKNOWN / UNAVAILABLE / UNVERIFIABLE = FAIL
""".strip()


# ============================================================
# 45. BTC ZONE ALERTS
# ============================================================

def process_btc_zone(btc):
    if not btc.get("valid"):
        return

    candle_time = btc.get(
        "candle_time"
    )

    zone = btc.get(
        "zone"
    )

    fakeout = btc.get(
        "fakeout"
    )

    # -----------------------------
    # GLOBAL WAIT
    # -----------------------------

    if btc.get("global_wait"):
        send_telegram_alert(
            "⛔ BTC VOLATILITY SHUTDOWN\n\n"
            "ACTION: GLOBAL WAIT\n\n"
            f"Reason: {btc.get('reason')}\n\n"
            "No new trades.\n"
            "No new setups.\n"
            "No scans.\n"
            "Capital Protection."
        )

        return

    # -----------------------------
    # DANGER
    # -----------------------------

    if zone == "ZONE_3_DANGER":

        trigger_key = str(
            candle_time
        )

        if (
            STATE.get(
                "last_zone_candle"
            )
            != trigger_key
            or STATE.get(
                "last_zone_alert"
            )
            != "ZONE_3_DANGER"
        ):

            until = (
                datetime.now(timezone.utc)
                + timedelta(hours=24)
            )

            STATE[
                "danger_until"
            ] = until.isoformat()

            STATE[
                "last_zone_alert"
            ] = "ZONE_3_DANGER"

            STATE[
                "last_zone_candle"
            ] = trigger_key

            save_state()

            send_telegram_alert(
                "⛔ BTC DANGER ZONE HIT\n\n"
                "ACTION: 24-HOUR GLOBAL WAIT.\n\n"
                f"Completed 1H Low: "
                f"${btc['btc_1h_low']:.2f}\n"
                f"Danger Level: "
                f"${ZONE_DANGER:.2f}\n\n"
                "No scans.\n"
                "No new setups.\n"
                "No trades.\n"
                "Capital Protection."
            )

        return

    # -----------------------------
    # Existing 24h danger lock
    # -----------------------------

    danger_until = STATE.get(
        "danger_until"
    )

    if danger_until:
        try:
            dt = datetime.fromisoformat(
                danger_until
            )

            if (
                datetime.now(
                    timezone.utc
                ) < dt
            ):
                return

            STATE[
                "danger_until"
            ] = None

            save_state()

        except Exception:
            STATE[
                "danger_until"
            ] = None

            save_state()

    # -----------------------------
    # Fakeout
    # -----------------------------

    if fakeout:
        key = (
            f"{fakeout}|"
            f"{candle_time}"
        )

        if key not in STATE[
            "fakeout_alerts"
        ]:

            STATE[
                "fakeout_alerts"
            ].append(key)

            STATE[
                "fakeout_alerts"
            ] = STATE[
                "fakeout_alerts"
            ][-100:]

            save_state()

            if fakeout == "BULL_FAKEOUT":
                send_telegram_alert(
                    "⚠️ FAKEOUT — STILL WAIT\n\n"
                    "BTC wicked above $84,800 "
                    "but the completed 1H candle "
                    "closed at or below $84,800.\n\n"
                    "No LONG scan activated."
                )

            else:
                send_telegram_alert(
                    "⚠️ FAKEOUT — STILL WAIT\n\n"
                    "BTC wicked below $83,000 "
                    "but the completed 1H candle "
                    "closed at or above $83,000.\n\n"
                    "No SHORT scan activated."
                )

    # -----------------------------
    # Bull
    # -----------------------------

    if zone == "ZONE_1_BULL":

        key = (
            f"ZONE_1_BULL|"
            f"{candle_time}"
        )

        if key == STATE.get(
            "last_zone_candle"
        ):
            return

        STATE[
            "last_zone_alert"
        ] = "ZONE_1_BULL"

        STATE[
            "last_zone_candle"
        ] = key

        save_state()

        send_telegram_alert(
            "🟢 BTC BULL ZONE HIT\n\n"
            "ACTION: Scan BTC, ETH, SOL, XRP, "
            "DOGE, ADA and LTC for LONG setups only.\n\n"
            f"Completed 1H Close: "
            f"${btc['btc_1h_close']:.2f}\n"
            f"Bull Level: ${ZONE_BULL:.2f}\n\n"
            "ZONE HIT ≠ TRADE.\n"
            "Complete V5.5 verification required."
        )

        return

    # -----------------------------
    # Bear
    # -----------------------------

    if zone == "ZONE_2_BEAR":

        key = (
            f"ZONE_2_BEAR|"
            f"{candle_time}"
        )

        if key == STATE.get(
            "last_zone_candle"
        ):
            return

        STATE[
            "last_zone_alert"
        ] = "ZONE_2_BEAR"

        STATE[
            "last_zone_candle"
        ] = key

        save_state()

        send_telegram_alert(
            "🔴 BTC BEAR ZONE HIT\n\n"
            "ACTION: Scan BTC, ETH, SOL, XRP, "
            "DOGE, ADA and LTC for SHORT setups only.\n\n"
            f"Completed 1H Close: "
            f"${btc['btc_1h_close']:.2f}\n"
            f"Bear Level: ${ZONE_BEAR:.2f}\n\n"
            "ZONE HIT ≠ TRADE.\n"
            "Complete V5.5 verification required."
        )

        return


# ============================================================
# 46. RUN FULL SCAN
# ============================================================

def run_scan(
    btc,
    current_equity
):
    zone = btc.get(
        "zone"
    )

    if zone not in [
        "ZONE_1_BULL",
        "ZONE_2_BEAR",
    ]:
        return

    direction = (
        "LONG"
        if zone == "ZONE_1_BULL"
        else "SHORT"
    )

    # Account-level circuit breakers
    breaker_failures = (
        account_circuit_breakers(
            current_equity
        )
    )

    if breaker_failures:
        send_telegram_alert(
            "🔴 WAIT — ACCOUNT CONTROL ACTIVE\n\n"
            + "\n".join(
                f"- {x}"
                for x in breaker_failures
            )
            + "\n\nNO TRADE"
        )

        return

    valid_setups = []

    for pair in MONITORED_COINS:

        try:
            setup, gates, reason = (
                analyze_candidate(
                    pair,
                    direction,
                    btc,
                    current_equity
                )
            )

            if setup is not None:

                setup_key = setup_id(
                    pair,
                    direction,
                    setup["entry"],
                    setup["sl"],
                    setup["tp2"]
                )

                if not already_sent(
                    setup_key
                ):
                    valid_setups.append(
                        (
                            setup_key,
                            setup
                        )
                    )

            else:
                # IMPORTANT:
                # Do not send a WAIT every 3 minutes.
                # Only READY is pushed after full verification.
                print(
                    f"[WAIT] {pair} {direction}: "
                    f"{reason}"
                )

        except Exception as e:
            print(
                f"[SCAN ERROR] "
                f"{pair}: {e}"
            )

    # Send only genuine READY setups.
    for setup_key, setup in valid_setups:

        send_telegram_alert(
            format_ready(
                setup,
                current_equity
            )
        )

        remember_setup(
            setup_key
        )


# ============================================================
# 47. STARTUP VALIDATION
# ============================================================

def startup_validation():
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
            "[STARTUP ERROR] Missing:"
        )

        for x in missing:
            print(
                f"- {x}"
            )

        return False

    return True


# ============================================================
# 48. MAIN LOOP
# ============================================================

def main():

    if not startup_validation():
        return

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

    last_status = None

    while True:

        try:

            # -------------------------
            # Account equity
            # -------------------------

            equity = calculate_current_equity()

            if equity is None:

                print(
                    "[WAIT] Current equity unavailable"
                )

                time.sleep(
                    POLL_SECONDS
                )

                continue

            print(
                f"[ACCOUNT] "
                f"Current equity ₹{equity:.2f}"
            )

            # -------------------------
            # BTC regime
            # -------------------------

            btc = btc_market_regime()

            if not btc.get(
                "valid"
            ):

                print(
                    "[WAIT] BTC data invalid: "
                    f"{btc.get('reason')}"
                )

                time.sleep(
                    POLL_SECONDS
                )

                continue

            # -------------------------
            # Status logging
            # -------------------------

            status_key = (
                btc.get("zone"),
                btc.get("candle_time"),
                btc.get("global_wait"),
            )

            if status_key != last_status:

                print(
                    "[BTC STATUS]",
                    btc
                )

                last_status = status_key

            # -------------------------
            # Zone protocol
            # -------------------------

            process_btc_zone(
                btc
            )

            # -------------------------
            # Global volatility
            # -------------------------

            if btc.get(
                "global_wait"
            ):
                time.sleep(
                    POLL_SECONDS
                )
                continue

            # -------------------------
            # Danger lock
            # -------------------------

            danger_until = STATE.get(
                "danger_until"
            )

            if danger_until:

                try:
                    danger_dt = (
                        datetime.fromisoformat(
                            danger_until
                        )
                    )

                    if (
                        datetime.now(
                            timezone.utc
                        )
                        < danger_dt
                    ):
                        time.sleep(
                            POLL_SECONDS
                        )
                        continue

                except Exception:
                    pass

            # -------------------------
            # Scan
            # -------------------------

            if btc.get(
                "zone"
            ) in [
                "ZONE_1_BULL",
                "ZONE_2_BEAR",
            ]:

                run_scan(
                    btc,
                    equity
                )

            time.sleep(
                POLL_SECONDS
            )

        except KeyboardInterrupt:

            print(
                "Bot stopped manually."
            )

            break

        except Exception as e:

            print(
                f"[CRITICAL LOOP ERROR] {e}"
            )

            time.sleep(60)


if __name__ == "__main__":
    main()




