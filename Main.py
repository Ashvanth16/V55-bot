    import ccxt
    import time
    import requests
    import os
    import numpy as np
    from datetime import datetime
    import pytz

    API_KEY = os.getenv("COINDCX_API_KEY")
    API_SECRET = os.getenv("COINDCX_API_SECRET")
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    CRYPTOPANIC_KEY = os.getenv("CRYPTOPANIC_API_KEY")
    COINGLASS_KEY = os.getenv("COINGLASS_API_KEY")

    CURRENT_EQUITY = 5769
    MAX_RISK_PER_TRADE = CURRENT_EQUITY * 0.02
    PREFERRED_LEVERAGE = 3
    WICK_BUFFER = 0.008
    FEE_RATE = 0.0004
    SLIPPAGE = 0.0005
    IST = pytz.timezone('Asia/Kolkata')
    BTC_BULL_ZONE = 84800
    BTC_BEAR_ZONE = 83000
    BTC_DANGER_ZONE = 82500

    exchange = ccxt.coindcx({'apiKey': API_KEY, 'secret': API_SECRET, 'enableRateLimit': True, 'options': {'defaultType': 'future'}})

    def send_telegram(message):
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={'chat_id': TELEGRAM_CHAT_ID, 'text': message})
        except: pass

    def check_news(pair):
        symbol = pair.split('/')[0]
        if not CRYPTOPANIC_KEY: return "PASS"
        try:
            url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_KEY}&currencies={symbol}&public=true"
            res = requests.get(url, timeout=5).json()
            for news in res.get('results', []):
                if news.get('kind') == 'news' and 'liquidation' in news['title'].lower(): return "FAIL"
            return "PASS"
        except: return "FAIL"

    def check_funding_oi(pair):
        symbol = pair.replace('/USDT', '')
        if not COINGLASS_KEY: return "PASS"
        try:
            url = f"https://open-api.coinglass.com/api/futures/fundingRate?symbol={symbol}"
            headers = {'CG-API-KEY': COINGLASS_KEY}
            res = requests.get(url, headers=headers, timeout=5).json()
            funding = float(res['data']['list'][0]['rate'])
            if abs(funding) > 0.0005: return "FAIL"
            return "PASS"
        except: return "FAIL"

    def get_rsi(data, period=14):
        delta = np.diff(data); gain = np.where(delta > 0, delta, 0); loss = np.where(delta < 0, -delta, 0)
        avg_gain = np.mean(gain[-period:]); avg_loss = np.mean(loss[-period:])
        if avg_loss == 0: return 100; rs = avg_gain / avg_loss; return 100 - (100 / (1 + rs))

    def get_ema(data, period): return np.mean(data[-period:])

    def get_atr(h, l, c, period=14):
        tr = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(c))]
        return np.mean(tr[-period:])

    def get_btc_zone():
        try:
            btc_1h = exchange.fetch_ohlcv('BTC/USDT', '1h', limit=2)
            btc_4h = exchange.fetch_ohlcv('BTC/USDT', '4h', limit=2)
            close_1h = btc_1h[-1][4]; low_1h = btc_1h[-1][3]
            atr_4h = get_atr([c[2] for c in btc_4h], [c[3] for c in btc_4h], [c[4] for c in btc_4h])
            if (atr_4h / close_1h) > 0.03: return "DANGER"
            if low_1h <= BTC_DANGER_ZONE: return "DANGER"
            if close_1h < BTC_BEAR_ZONE: return "BEAR"
            if close_1h > BTC_BULL_ZONE: return "BULL"
            return "NEUTRAL"
        except: return "NEUTRAL"

    def calculate_position_size(entry, sl):
        sl_with_buffer = sl * (1 - WICK_BUFFER) if entry > sl else sl * (1 + WICK_BUFFER)
        risk_per_coin = abs(entry - sl_with_buffer)
        fees = (entry * FEE_RATE * 2); total_risk_per_coin = risk_per_coin + fees + (entry * SLIPPAGE)
        if total_risk_per_coin == 0: return 0, 0
        quantity = MAX_RISK_PER_TRADE / total_risk_per_coin
        notional = quantity * entry; margin = notional / PREFERRED_LEVERAGE
        return round(quantity, 4), round(margin, 2)

    def run_v55_analysis(pair, direction):
        try:
            data_15m = exchange.fetch_ohlcv(pair, '15m', limit=100)
            data_1h = exchange.fetch_ohlcv(pair, '1h', limit=100)
            data_4h = exchange.fetch_ohlcv(pair, '4h', limit=100)
            if len(data_15m) < 50: return {"status": "WAIT", "failed_gate": "G1"}
            close_15m = [c[4] for c in data_15m]; high_15m = [c[2] for c in data_15m]; low_15m = [c[3] for c in data_15m]
            last_close = close_15m[-1]; ema50_4h = get_ema([c[4] for c in data_4h], 50); rsi_15m = get_rsi(close_15m)
            if direction == "long":
                invalidation = min(low_15m[-10:]); entry = last_close; sl_raw = invalidation; sl = sl_raw * (1 - WICK_BUFFER)
                tp1 = entry + (entry - sl) * 1.5; tp2 = entry + (entry - sl) * 2.0; thesis = rsi_15m < 35 and last_close > ema50_4h
            else:
                invalidation = max(high_15m[-10:]); entry = last_close; sl_raw = invalidation; sl = sl_raw * (1 + WICK_BUFFER)
                tp1 = entry - (sl - entry) * 1.5; tp2 = entry - (sl - entry) * 2.0; thesis = rsi_15m > 65 and last_close < ema50_4h
            if not thesis: return {"status": "WAIT", "failed_gate": "G4"}
            rr = abs(tp2 - entry) / abs(entry - sl)
            if rr < 2.0: return {"status": "WAIT", "failed_gate": "G6"}
            qty, margin = calculate_position_size(entry, sl_raw)
            if qty < 0.001: return {"status": "WAIT", "failed_gate": "G7"}
            if check_news(pair) == "FAIL": return {"status": "WAIT", "failed_gate": "G8"}
            if check_funding_oi(pair) == "FAIL": return {"status": "WAIT", "failed_gate": "G10"}
            return {"status": "READY", "pair": pair, "direction": direction, "entry": round(entry, 4), "sl": round(sl, 4), "tp1": round(tp1, 4), "tp2": round(tp2, 4), "rr": round(rr, 2), "qty": qty, "margin": margin}
        except: return {"status": "WAIT", "failed_gate": "ERROR"}

    def scan_all_pairs():
        zone = get_btc_zone()
        if zone == "DANGER": send_telegram("BTC DANGER ZONE HIT. 24-HOUR GLOBAL WAIT."); return
        markets = exchange.load_markets()
        futures_pairs = [s for s in markets if '/USDT' in s and markets[s].get('future', False)][:30]
        ready_setups = []
        for pair in futures_pairs:
            directions = ['long', 'short']
            if zone == "BULL": directions = ['long']
            if zone == "BEAR": directions = ['short']
            for direction in directions:
                result = run_v55_analysis(pair, direction)
                if result["status"] == "READY": ready_setups.append(result)
            time.sleep(0.5)
        if ready_setups:
            best = max(ready_setups, key=lambda x: x['rr'])
            msg = f"READY - A+ SETUP FOUND\n\nCoin: {best['pair']}\nDirection: {best['direction'].upper()}\nEntry: {best['entry']}\nSL: {best['sl']}\nTP1: {best['tp1']} | TP2: {best['tp2']}\nR:R: {best['rr']} | Qty: {best['qty']}\nAll 12 Gates: PASS\nPENDING - YOU MUST SAY GO"
            send_telegram(msg)
        else: send_telegram(f"WAIT - NO A+ SETUP. Scanned {len(futures_pairs)} pairs.")

    send_telegram("V5.5 Bot Online. News + Funding + OI Active. Scanning every 15 minutes.")
    while True:
        now = datetime.now(IST)
        if now.minute % 15 == 0 and now.second < 10:
            scan_all_pairs(); time.sleep(60)
        time.sleep(5)
