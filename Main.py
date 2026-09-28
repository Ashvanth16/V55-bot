import os,requests,asyncio,json
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

async def send(t):
 try:await bot.send_message(chat_id=CHAT_ID,text=t,parse_mode="HTML")
 except Exception as e:print("TG ERR:",e)

async def run():
 await send(f"🚀<b>V5.6.14 Full Debug Online</b>")
 data=get_data()
 if len(data)>0:
  first=json.dumps(data[0],indent=2) # PRINT WHOLE OBJECT
  await send(f"<b>COINDCX FIRST MARKET FULL DATA:</b>\n<code>{first}</code>")
 
 while True:
  t=datetime.now(IST).strftime("%d %b %I:%M:%S %p IST")
  data=get_data()
  s=len(data) # Just count how many pairs API returned
  await send(f"✅<b>Scan Done</b>\nAPI Returned:{s} pairs\nTime:{t}")
  await asyncio.sleep(SCAN)

if __name__=="__main__":asyncio.run(run())
