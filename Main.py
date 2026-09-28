import requests,asyncio
from telegram import Bot
from datetime import datetime
TELEGRAM_TOKEN="YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID="YOUR_CHAT_ID_HERE"
PAIRS=["B-BTCINR","B-ETHINR","B-SOLINR","B-DOGEINR","B-XRPINR","B-ADAINR","B-AVAXINR","B-MATICINR","B-LTCINR","B-DOTINR","B-LINKINR","B-BNBINR","B-TRXINR"]
SCAN_INTERVAL=900
bot=Bot(token=TELEGRAM_TOKEN)
def get_coindcx_ticker():
 url="https://public.coindcx.com/market_data/ticker"
 try:return requests.get(url,timeout=10).json()
 except:return[]
def get_pair_data(pair,all_data):
 for item in all_data:
  if item['market']==pair:return{'price':float(item['last_price']),'volume':float(item['volume_24h']),'change':float(item['change_24_hour'])}
 return None
def check_a_plus_setup(pair,data):
 if abs(data['change'])>3.0 and data['volume']>50000000:return True,f"Volume: {data['volume']/10000000:.2f}Cr | Move: {data['change']:.2f}%"
 return False,""
async def send_telegram(text):
 try:await bot.send_message(chat_id=TELEGRAM_CHAT_ID,text=text,parse_mode='HTML')
 except Exception as e:print(f"Telegram Error: {e}")
async def run_scan():
 await send_telegram("🚀 <b>V5.6 CoinDCX Bot Online</b>\nScanning: 13 INR Pairs\nInterval: 15 Minutes")
 while True:
  start_time=datetime.now().strftime("%d %b %Y, %I:%M:%S %p IST")
  all_data=get_coindcx_ticker()
  scanned=0;setups=0
  for pair in PAIRS:
   data=get_pair_data(pair,all_data)
   if data:
    scanned+=1
    is_setup,reason=check_a_plus_setup(pair,data)
    if is_setup:
     setups+=1
     alert=f"🔥 <b>A+ SETUP FOUND</b> 🔥\n\n<b>Pair:</b> {pair}\n<b>Price:</b> ₹{data['price']:,.2f}\n<b>{reason}</b>"
     await send_telegram(alert)
  status=f"✅ <b>Scan Complete</b>\nPairs: {scanned}/13 processed\nNew Setups: {setups}\nLast scan: {start_time}\nNext scan: 15 minutes"
  await send_telegram(status)
  await asyncio.sleep(SCAN_INTERVAL)
if __name__=="__main__":asyncio.run(run_scan())
