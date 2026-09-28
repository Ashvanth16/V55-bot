import os,requests,asyncio
from telegram import Bot
from datetime import datetime
TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID")
KEY=os.getenv("COINDCX_API_KEY")
SECRET=os.getenv("COINDCX_API_SECRET")
PAIRS=["B-BTCINR","B-ETHINR","B-SOLINR","B-DOGEINR","B-XRPINR","B-ADAINR","B-AVAXINR","B-MATICINR","B-LTCINR","B-DOTINR","B-LINKINR","B-BNBINR","B-TRXINR"]
SCAN=900
bot=Bot(token=TOKEN)
def get_data():
 url="https://public.coindcx.com/market_data/ticker"
 try:
  r=requests.get(url,timeout=10)
  d=r.json()
  if type(d)==list:return d
  else:print("API ERR:",d);return[]
 except Exception as e:print("REQ ERR:",e);return[]
def get_pair(p,data):
 if type(data)!=list:return None
 for i in data:
  if type(i)==dict and i.get("market")==p:
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
 await send(f"🚀<b>V5.6.4 Online</b>\nPairs:13\nKey Loaded:{bool(KEY)}")
 while True:
  t=datetime.now().strftime("%d %b %I:%M:%S %p IST")
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
