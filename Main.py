import os,json,time,math,hmac,hashlib,sqlite3,requests,asyncio
from datetime import datetime,timezone,timedelta
from telegram import Bot
TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID")
API_KEY=os.getenv("COINDCX_API_KEY")
API_SECRET=os.getenv("COINDCX_API_SECRET")
STARTING_EQUITY=float(os.getenv("STARTING_EQUITY","5769"))
MAX_RISK_PCT=float(os.getenv("MAX_RISK_PCT","0.02"))
MAX_LEVERAGE=float(os.getenv("MAX_LEVERAGE","5"))
PREFERRED_LEVERAGE=float(os.getenv("PREFERRED_LEVERAGE","3"))
SCAN_PAIRS=int(os.getenv("SCAN_PAIRS","30"))
SCAN_SECONDS=int(os.getenv("SCAN_SECONDS","300"))
FEE_RATE=float(os.getenv("FEE_RATE","0.0005"))
SLIPPAGE_RATE=float(os.getenv("SLIPPAGE_RATE","0.0005"))
BTC_BULL_ZONE=float(os.getenv("BTC_BULL_ZONE","84800"))
BTC_BEAR_ZONE=float(os.getenv("BTC_BEAR_ZONE","83000"))
BTC_DANGER_ZONE=float(os.getenv("BTC_DANGER_ZONE","82500"))
DATA_DIR=os.getenv("DATA_DIR","/data")
os.makedirs(DATA_DIR,exist_ok=True)
DB_FILE=os.path.join(DATA_DIR,"v55_state.db")
IST=timezone(timedelta(hours=5,minutes=30))
PUBLIC="https://public.coindcx.com"
API="https://api.coindcx.com"
bot=Bot(token=TOKEN)
session=requests.Session()
session.headers.update({"User-Agent":"CoinDCX-V55-Signal-Bot/1.0"})
def db():return sqlite3.connect(DB_FILE)
def init_db():
 con=db();cur=con.cursor()
 cur.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY,value TEXT)")
 cur.execute("CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT,pair TEXT,direction TEXT,entry REAL,sl REAL,tp1 REAL,tp2 REAL,quantity REAL,risk REAL,rr REAL,status TEXT,outcome TEXT,pnl REAL DEFAULT 0)")
 cur.execute("CREATE TABLE IF NOT EXISTS transactions (fingerprint TEXT PRIMARY KEY,created_at TEXT,pair TEXT,amount REAL,fee REAL,stage TEXT)")
 con.commit();con.close()
def state_get(key,default=None):
 con=db();cur=con.cursor();cur.execute("SELECT value FROM state WHERE key=?",(key,));row=cur.fetchone();con.close()
 if not row:return default
 return row[0]
def state_set(key,value):
 con=db();cur=con.cursor();cur.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,str(value)));con.commit();con.close()
async def send(text):
 try:await bot.send_message(chat_id=CHAT_ID,text=text,parse_mode="HTML")
 except Exception as e:print("TELEGRAM ERROR:",e)
def get_json(url,params=None,timeout=15):
 try:r=session.get(url,params=params,timeout=timeout)
 if r.status_code!=200:print("HTTP ERROR:",r.status_code,url);return None
 return r.json()
 except Exception as e:print("REQUEST ERROR:",url,e);return None
def signed_post(path,payload):
 payload=dict(payload);payload["timestamp"]=int(time.time()*1000);body=json.dumps(payload,separators=(",",":"));signature=hmac.new(API_SECRET.encode(),body.encode(),hashlib.sha256).hexdigest();headers={"Content-Type":"application/json","X-AUTH-APIKEY":API_KEY,"X-AUTH-SIGNATURE":signature}
 try:r=session.post(API+path,data=body,headers=headers,timeout=15)
 if r.status_code!=200:print("AUTH HTTP ERROR:",r.status_code,r.text[:300]);return None
 return r.json()
 except Exception as e:print("AUTH REQUEST ERROR:",e);return None
def get_active_instruments():
 url=API+"/exchange/v1/derivatives/futures/data/active_instruments";data=get_json(url,params=[("margin_currency_short_name[]","INR")])
 if not isinstance(data,list):print("ACTIVE INSTRUMENT ERROR:",data);return[]
 return[x for x in data if isinstance(x,str)and x.startswith("B-")and x.endswith("_INR")]
def get_futures_prices():
 url=PUBLIC+"/market_data/v3/current_prices/futures/rt";data=get_json(url)
 if not isinstance(data,dict):return{}
 return data.get("prices",{})
def select_pairs(active,prices):
 candidates=[]
 for pair in active:
  p=prices.get(pair)
  if not isinstance(p,dict):continue
  try:last=float(p.get("ls",0));volume=float(p.get("v",0))
  if last<=0:continue
  turnover=last*volume;candidates.append((pair,turnover))
  except Exception:continue
 candidates.sort(key=lambda x:x[1],reverse=True)
 return[x[0] for x in candidates[:SCAN_PAIRS]]
def get_candles(pair,resolution,limit=300):
 seconds_map={"1":60,"5":300,"60":3600};step=seconds_map[resolution];now=int(time.time());start=now-step*(limit+20);url=PUBLIC+"/market_data/candlesticks";params={"pair":pair,"from":start,"to":now,"resolution":resolution,"pcode":"f"};data=get_json(url,params=params)
 if not isinstance(data,dict):return[]
 candles=data.get("data",[])
 if not isinstance(candles,list):return[]
 cleaned=[]
 for c in candles:
  try:item={"time":int(c["time"]),"open":float(c["open"]),"high":float(c["high"]),"low":float(c["low"]),"close":float(c["close"]),"volume":float(c["volume"])}
  if item["time"]+step*1000<=int(time.time()*1000):cleaned.append(item)
  except Exception:continue
 cleaned.sort(key=lambda x:x["time"])
 return cleaned[-limit:]
def aggregate(candles,minutes):
 if not candles:return[]
 bucket_ms=minutes*60*1000;groups={}
 for c in candles:bucket=(c["time"]//bucket_ms)*bucket_ms;groups.setdefault(bucket,[]).append(c)
 result=[]
 for t in sorted(groups):
  g=groups[t]
  if not g:continue
  result.append({"time":t,"open":g[0]["open"],"high":max(x["high"]for x in g),"low":min(x["low"]for x in g),"close":g[-1]["close"],"volume":sum(x["volume"]for x in g)})
 return result
def ema(values,period):
 if len(values)<period:return None
 k=2/(period+1);result=sum(values[:period])/period
 for value in values[period:]:result=value*k+result*(1-k)
 return result
def rsi(values,period=14):
 if len(values)<period+1:return None
 gains=[];losses=[]
 for i in range(1,len(values)):change=values[i]-values[i-1];gains.append(max(change,0));losses.append(max(-change,0))
 avg_gain=sum(gains[:period])/period;avg_loss=sum(losses[:period])/period
 for i in range(period,len(gains)):avg_gain=((avg_gain*(period-1))+gains[i])/period;avg_loss=((avg_loss*(period-1))+losses[i])/period
 if avg_loss==0:return 100.0
 rs=avg_gain/avg_loss
 return 100-(100/(1+rs))
def atr(candles,period=14):
 if len(candles)<period+1:return None
 trs=[]
 for i in range(1,len(candles)):current=candles[i];previous=candles[i-1];tr=max(current["high"]-current["low"],abs(current["high"]-previous["close"]),abs(current["low"]-previous["close"]));trs.append(tr)
 if len(trs)<period:return None
 return sum(trs[-period:])/period
def avg_volume(candles,period=20):
 if len(candles)<period:return None
 return sum(c["volume"]for c in candles[-period:])/period
def btc_regime(prices):
 btc=prices.get("B-BTC_INR")
 if not btc:return{"valid":False,"reason":"BTC Futures price unavailable"}
 try:btc_price=float(btc["ls"])
 except Exception:return{"valid":False,"reason":"BTC price invalid"}
 h1=get_candles("B-BTC_INR","60",220)
 if len(h1)<60:return{"valid":False,"reason":"BTC 1H history unavailable"}
 h4=aggregate(h1,240)
 if len(h4)<30:return{"valid":False,"reason":"BTC 4H history unavailable"}
 c4_atr=atr(h4,14)
 if c4_atr is None:return{"valid":False,"reason":"BTC 4H ATR unavailable"}
 last4=h4[-1]["close"];atr_pct=(c4_atr/last4)*100;last_h1=h1[-1];move_pct=(abs(last_h1["close"]-last_h1["open"])/last_h1["open"])*100
 if atr_pct>3:return{"valid":False,"shutdown":True,"reason":f"BTC 4H ATR {atr_pct:.2f}% > 3%"}
 if move_pct>2:return{"valid":False,"shutdown":True,"reason":f"BTC 1H move {move_pct:.2f}% > 2%"}
 last_close=h1[-1]["close"];last_low=h1[-1]["low"];zone="NEUTRAL"
 if last_low<=BTC_DANGER_ZONE:zone="DANGER"
 elif last_close<BTC_BEAR_ZONE:zone="BEAR"
 elif last_close>BTC_BULL_ZONE:zone="BULL"
 return{"valid":True,"shutdown":False,"price":btc_price,"atr_pct":atr_pct,"move_pct":move_pct,"zone":zone,"last_close":last_close}
def swing_low(candles,lookback=12):data=candles[-lookback:];return min(c["low"]for c in data)
def swing_high(candles,lookback=12):data=candles[-lookback:];return max(c["high"]for c in data)
def analyze_direction(pair,direction,h1,m15,h4,current,btc_zone):
 if len(h1)<60 or len(m15)<60 or len(h4)<30:return None
 c1=[x["close"]for x in h1];c4=[x["close"]for x in h4];c15=[x["close"]for x in m15]
 ema20_1=ema(c1,20);ema50_1=ema(c1,50);ema20_4=ema(c4,20);ema50_4=ema(c4,50);ema20_15=ema(c15,20);rsi1=rsi(c1);rsi15=rsi(c15);a1=atr(h1);av15=avg_volume(m15)
 if None in(ema20_1,ema50_1,ema20_4,ema50_4,ema20_15,rsi1,rsi15,a1,av15):return None
 last1=h1[-1];last4=h4[-1];last15=m15[-1];price=current;volume_ok=last15["volume"]>=av15*1.15;chase_pct=abs(price-last15["close"])/last15["close"]*100
 if chase_pct>0.50:return None
 if direction=="LONG":
  if btc_zone not in("BULL","NEUTRAL"):return None
  trend_ok=(last4["close"]>ema50_4 and ema20_4>ema50_4 and last1["close"]>ema50_1 and ema20_1>ema50_1);momentum_ok=(52<=rsi1<=68 and 52<=rsi15<=75);confirmation_ok=(last15["close"]>ema20_15 and volume_ok and last15["close"]>=last15["open"])
  if not(trend_ok and momentum_ok and confirmation_ok):return None
  invalidation=swing_low(h1,12);sl=invalidation*(1-0.008);risk_per_unit=price-sl
  if risk_per_unit<=0:return None
  resistance=swing_high(h1,30);tp1=price+risk_per_unit*1.5;structural_tp2=resistance
  if structural_tp2<=price:return None
  if structural_tp2<price+risk_per_unit*2:return None
  tp2=structural_tp2
 elif direction=="SHORT":
  if btc_zone not in("BEAR","NEUTRAL"):return None
  trend_ok=(last4["close"]<ema50_4 and ema20_4<ema50_4 and last1["close"]<ema50_1 and ema20_1<ema50_1);momentum_ok=(32<=rsi1<=48 and 25<=rsi15<=48);confirmation_ok=(last15["close"]<ema20_15 and volume_ok and last15["close"]<=last15["open"])
  if not(trend_ok and momentum_ok and confirmation_ok):return None
  invalidation=swing_high(h1,12);sl=invalidation*(1+0.008);risk_per_unit=sl-price
  if risk_per_unit<=0:return None
  support=swing_low(h1,30);tp1=price-risk_per_unit*1.5;structural_tp2=support
  if structural_tp2>=price:return None
  if structural_tp2>price-risk_per_unit*2:return None
  tp2=structural_tp2
 else:return None
 rr=abs(tp2-price)/abs(price-sl)
 if rr<2:return None
 return{"pair":pair,"direction":direction,"entry":price,"invalidation":invalidation,"sl":sl,"tp1":tp1,"tp2":tp2,"rr":rr,"atr":a1,"rsi1":rsi1,"rsi15":rsi15,"volume_ok":volume_ok}
def calculate_risk(setup,equity):
 entry=setup["entry"];sl=setup["sl"];stop_distance=abs(entry-sl);max_risk=equity*MAX_RISK_PCT;cost_rate=(FEE_RATE*2+SLIPPAGE_RATE*2);effective_risk_per_unit=(stop_distance+entry*cost_rate)
 if effective_risk_per_unit<=0:return None
 quantity=max_risk/effective_risk_per_unit
 if quantity<=0:return None
 notional=quantity*entry;leverage=min(PREFERRED_LEVERAGE,MAX_LEVERAGE);margin=notional/leverage;planned_risk=(stop_distance*quantity+notional*cost_rate)
 if planned_risk>max_risk:return None
 return{"quantity":quantity,"notional":notional,"leverage":leverage,"margin":margin,"planned_risk":planned_risk,"max_risk":max_risk}
def news_gate():return False,"Reliable news verification provider not configured"
def get_equity():value=state_get("current_equity",str(STARTING_EQUITY))
 try:return float(value)
 except Exception:return STARTING_EQUITY
def trade_count_30d():con=db();cur=con.cursor();cur.execute("SELECT COUNT(*) FROM signals WHERE datetime(created_at)>=datetime('now','-30 day')");count=cur.fetchone()[0];con.close();return count
def daily_loss():con=db();cur=con.cursor();today=datetime.now(IST).strftime("%Y-%m-%d");cur.execute("SELECT COALESCE(SUM(pnl),0) FROM signals WHERE substr(created_at,1,10)=?",(today,));value=cur.fetchone()[0];con.close();return float(value or 0)
def save_signal(setup,risk):
 con=db();cur=con.cursor();cur.execute("INSERT INTO signals(created_at,pair,direction,entry,sl,tp1,tp2,quantity,risk,rr,status) VALUES(?,?,?,?,?,?,?)",(datetime.now(IST).isoformat(),setup["pair"],setup["direction"],setup["entry"],setup["sl"],setup["tp1"],setup["tp2"],risk["quantity"],risk["planned_risk"],setup["rr"],"SIGNAL"));con.commit();con.close()
def format_ready(setup,risk,equity,btc):return f"""🟢 <b>V5.5 A+ SETUP DETECTED</b>\n\n<b>CoinDCX Futures — SIGNAL ONLY</b>\n\n━━━━━━━━━━━━━━━━━━\n\n<b>PAIR:</b> {setup['pair']}\n<b>DIRECTION:</b> {setup['direction']}\n\n<b>ENTRY:</b> ₹{setup['entry']:,.6f}\n\n<b>STRUCTURAL INVALIDATION:</b>\n₹{setup['invalidation']:,.6f}\n\n<b>FINAL SL:</b>\n₹{setup['sl']:,.6f}\n0.8% structural buffer APPLIED\n\n<b>TP1:</b>\n₹{setup['tp1']:,.6f}\n\n<b>TP2:</b>\n₹{setup['tp2']:,.6f}\n\n<b>R:R:</b> {setup['rr']:.2f}R\n\n━━━━━━━━━━━━━━━━━━\n\n<b>RISK ENGINE</b>\n\nEquity:\n₹{equity:,.2f}\n\nMaximum risk:\n₹{risk['max_risk']:,.2f}\n\nPlanned risk:\n₹{risk['planned_risk']:,.2f}\n\nQuantity:\n{risk['quantity']:.8f}\n\nNotional:\n₹{risk['notional']:,.2f}\n\nLeverage:\n{risk['leverage']:.1f}x\n\nMargin:\n₹{risk['margin']:,.2f}\n\n━━━━━━━━━━━━━━━━━━\n\n<b>BTC REGIME</b>\n\nPrice:\n₹{btc['price']:,.2f}\n\nZone:\n{btc['zone']}\n\n4H ATR:\n{btc['atr_pct']:.2f}%\n\n1H movement:\n{btc['move_pct']:.2f}%\n\n━━━━━━━━━━\n\n<b>STATUS:</b>\nREADY — USER APPROVAL REQUIRED\n\n⚠️ <b>NO ORDER HAS BEEN PLACED.</b>\n\nReply <b>GO</b> only after your own final verification."""
async def send_wait(reason,scanned):await send(f"""🔴 <b>V5.5 — WAIT</b>\n\nNo verified A+ setup.\n\n<b>CoinDCX Futures scanner:</b>\n{scanned} pairs checked\n\n<b>Reason:</b>\n{reason}\n\nCapital protection remains active.\n\nNo forced trade.\nNo manufactured signal.""")
async def scan_once():
 print("\n==============================\nV5.5 SCAN START\n==============================");active=get_active_instruments();prices=get_futures_prices()
 if not active:await send_wait("CoinDCX Futures active-instrument data unavailable.",0);return
 pairs=select_pairs(active,prices);print(f"Active INR futures: {len(active)} | Selected: {len(pairs)}")
 if not pairs:await send_wait("No valid CoinDCX INR Futures prices available.",0);return
 btc=btc_regime(prices)
 if not btc.get("valid"):await send_wait("BTC regime/data gate failed: "+btc.get("reason","unknown"),len(pairs));return
 if btc["zone"]=="DANGER":danger_until=time.time()+24*3600;state_set("global_wait_until",danger_until);await send("⛔ <b>BTC DANGER ZONE HIT</b>\n\n<b>V5.5 ACTION:</b>\n24-HOUR GLOBAL WAIT\nNo new trades.\nNo new setups.\nNo coin scans.\n\nCapital protection takes priority.");return
 wait_until=float(state_get("global_wait_until","0"))
 if time.time()<wait_until:remaining=int(wait_until-time.time());await send(f"⛔ <b>GLOBAL WAIT ACTIVE</b>\n\nRemaining:\n{remaining//3600}h {(remaining%3600)//60}m\n\nNo new setup scan.");return
 if btc.get("shutdown"):await send_wait(btc.get("reason","BTC volatility shutdown"),len(pairs));return
 count=trade_count_30d()
 if count>=20:await send_wait("Rolling 30-day trade limit reached.",len(pairs));return
 equity=get_equity();dl=daily_loss()
 if dl<=-(equity*MAX_RISK_PCT):await send_wait("Daily loss circuit breaker active.",len(pairs));return
 news_ok,news_reason=news_gate()
 if not news_ok:print("G8:",news_reason)
 candidates=[]
 for pair in pairs:
  if pair=="B-BTC_INR":continue
  try:current_data=prices.get(pair)
  if not current_data:continue
  current=float(current_data.get("ls",0))
  if current<=0:continue
  h1=get_candles(pair,"60",220);m5=get_candles(pair,"5",300)
  if len(h1)<60 or len(m5)<100:continue
  m15=aggregate(m5,15);h4=aggregate(h1,240)
  if len(m15)<60 or len(h4)<30:continue
  long_setup=analyze_direction(pair,"LONG",h1,m15,h4,current,btc["zone"]);short_setup=analyze_direction(pair,"SHORT",h1,m15,h4,current,btc["zone"])
  for setup in(long_setup,short_setup):
   if not setup:continue
   risk=calculate_risk(setup,equity)
   if not risk:continue
   candidates.append((setup,risk))
  except Exception as e:print("PAIR ERROR:",pair,e)
 if not candidates:await send(f"""🔴 <b>V5.5 SCAN COMPLETE — WAIT</b>\n\n<b>CoinDCX INR Futures scanned:</b>\n{len(pairs)}\n\n<b>BTC:</b>\n₹{btc['price']:,.2f}\n\n<b>BTC Zone:</b>\n{btc['zone']}\n\n<b>4H ATR:</b>\n{btc['atr_pct']:.2f}%\n\n<b>1H movement:</b>\n{btc['move_pct']:.2f}%\n\n<b>A+ setups:</b>\n0\n\nNo candidate passed the complete technical/risk engine.\n\nCapital protection remains active.\n\n🛡️ No forced trade.""");return
 candidates.sort(key=lambda x:x[0]["rr"],reverse=True);setup,risk=candidates[0];await send(f"""🟡 <b>TECHNICAL CANDIDATE FOUND</b>\n\nPair:\n{setup['pair']}\n\nDirection:\n{setup['direction']}\n\nR:R:\n{setup['rr']:.2f}R\n\nEntry:\n₹{setup['entry']:,.6f}\n\nSL:\n₹{setup['sl']:,.6f}\n\nTP2:\n₹{setup['tp2']:,.6f}\n\nRisk:\n₹{risk['planned_risk']:,.2f}\n\nHowever:\n\n<b>FINAL V5.5 STATUS = WAIT</b>\n\nG8 News verification is not yet connected.\nG9 Abnormal-flow verification is not yet complete.\nG10 OI/liquidation verification is not yet complete.\n\nThe bot will NOT call this A+ until those gates are independently verified.\n\nThis is intentional capital protection.""")
async def heartbeat():await send(f"""🤖 <b>CoinDCX V5.5 ENGINE ONLINE</b>\n\nMode:\nSIGNAL ONLY\n\nExecution:\nDISABLED\n\nUniverse:\nCoinDCX INR Futures\n\nTarget scan:\nTop {SCAN_PAIRS} active pairs\n\nRisk:\n{MAX_RISK_PCT*100:.1f}% maximum planned risk\nMax leverage:\n{MAX_LEVERAGE:.1f}x\nPreferred leverage:\n{PREFERRED_LEVERAGE:.1f}x\nBTC zone monitoring:\nACTIVE\n\nAutomatic order execution:\n❌ DISABLED\nCapital protection:\n🛡️ ACTIVE""")
async def run():
 init_db();await heartbeat()
 while True:
  try:await scan_once()
  except Exception as e:print("MAIN LOOP ERROR:",repr(e));await send(f"""⚠️ <b>V5.5 ENGINE ERROR</b>\n\nThe scanner encountered an internal error.\n\n<b>No trade will be generated.</b>\n\nReason:\n{str(e)[:500]}\n\nCapital protection remains active.""")
  await asyncio.sleep(SCAN_SECONDS)
if __name__=="__main__":asyncio.run(run())
