import os,requests,asyncio
from telegram import Bot
from datetime import datetime,timezone,timedelta
TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID")
PAIRS=["B-BTC_INR","B-ETH_INR","B-SOL_INR","B-DOGE_INR","B-XRP_INR","B-ADA_INR","B-AVAX_INR","B-MATIC_INR","B-LTC_INR","B-DOT_INR","B-LINK_INR","B-BNB_INR","B-TRX_INR"]
SCAN=900
bot=Bot(token=TOKEN)
IST=timezone(timedelta(hours=5,minutes=30))

def get_data():
 url="https://public.coindcx.com/market_data/ticker"
 try:
  r=requests.get(url,timeout=10)
  d=r.json()
  return d if type(d)==list else []
 except:return[]

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
 await send(f"🚀<b>V5.6.13 Debug Online</b>")
 data=get_data()
 if len(data)>3:
  sample=f"<b>COINDCX REAL MARKET NAMES:</b>\n1.`{data[0].get('market')}`\n2.`{data[1].get('market')}`\n3.`{data[2].get('market')}`\n\nCopy these 3 and send me"
  await send(sample)
 
 while True:
  t=datetime.now(IST).strftime("%d %b %I:%M:%S %p IST")
  data=get_data()
  s=0;u=0
  for p in PAIRS:
   d=get_pair(p,data)
   if d:s+=1
  await send(f"✅<b>Scan Done</b>\nScanned:{s}/13\nTime:{t}")
  await asyncio.sleep(SCAN)

if __name__=="__main__":asyncio.run(run())
