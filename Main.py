 import os,requests,asyncio,json,time,hmac,hashlib
from telegram import Bot
from datetime import datetime,timezone,timedelta
TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID")
KEY=os.getenv("COINDCX_API_KEY")
SECRET=os.getenv("COINDCX_API_SECRET")

PAIRS=["B-BTC_INR","B-ETH_INR","B-SOL_INR","B-DOGE_INR","B-XRP_INR","B-ADA_INR","B-AVAX_INR","B-MATIC_INR","B-LTC_INR","B-DOT_INR","B-LINK_INR","B-BNB_INR","B-TRX_INR"]
SCAN=900
bot=Bot(token=TOKEN)
IST=timezone(timedelta(hours=5,minutes=30))

def get_signature(data):
 message=json.dumps(data,separators=(',',':'))
 return hmac.new(SECRET.encode('utf-8'),message.encode('utf-8'),hashlib.sha256).hexdigest()

def get_data():
 url="https://api.coindcx.com/exchange/v1/markets/ticker" # PRO API
 payload={"timestamp":int(time.time()*1000)}
 headers={"X-AUTH-APIKEY":KEY,"X-AUTH-SIGNATURE":get_signature(payload)}
 try:
  r=requests.post(url,json=payload,headers=headers,timeout=10)
  d=r.json()
  return d if type(d)==list else []
 except Exception as e:
  print("API ERR:",e)
  return[]

def get_pair(p,data):
 if type(data)!=list:return None
 for i in data:
  if type(i)==dict and str(i.get("market","")).strip()==p:
   try:return{"price":float(i.get("last_price",0)),"vol":float(i.get("volume_24h",0)),"ch":float(i.get("change_24_hour",0))}
   except:return None
 return None

def check(p,d):
 if abs(d["ch"])>3.0 and d["vol"]>50000000:return True,f"Vol:{d['vol']/10000000:.2f}Cr Move:{d['ch']:.2f}%"
 return False,""

async def send(t):
 try:await bot.send_message(chat_id=CHAT_ID,text=t,parse_mode="HTML")
 except Exception as e:print("TG ERR:",e)

async def run():
 await send(f"🚀<b>V6.0.0 PRO API Online IST</b>\nPairs:13")
 while True:
  t=datetime.now(IST).strftime("%d %b %I:%M:%S %p IST")
  data=get_data()
  s=0;u=0
  for p in PAIRS:
   d=get_pair(p,data)
   if d:
    s+=1
    ok,r=check(p,d)
    if ok:u+=1;await send(f"🔥<b>A+ SETUP</b>🔥\n<b>Pair:</b>{p}\n<b>Price:</b>₹{d['price']:,.2f}\n<b>{r}</b>")
  await send(f"✅<b>Scan Done</b>\nScanned:{s}/13\nSetups:{u}\nTime:{t}")
  await asyncio.sleep(SCAN)

if __name__=="__main__":asyncio.run(run())
