import os
import requests
import yfinance as yf
import pandas as pd
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage
)

# --- Configuration ---
# ⚠️ Critical: Read tokens from environment variables for security
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.environ.get('LINE_USER_ID')

# Thresholds
EXTREME_FEAR_THRESHOLD = 25
FEAR_THRESHOLD = 44

def fetch_crypto_sentiment():
    """Fetches Crypto Fear & Greed Index from Alternative.me"""
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        value = int(data['data'][0]['value'])
        return value
    except Exception as e:
        print(f"Error fetching Crypto sentiment: {e}")
        return None

def fetch_us_stock_sentiment():
    """Fetches US Stock Fear & Greed Index from CNN"""
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        score = int(round(data['fear_and_greed']['score']))
        return score
    except Exception as e:
        print(f"Error fetching US Stock sentiment: {e}")
        return None

def fetch_tw_stock_rsi(ticker="0050.TW"):
    """Calculates RSI (14) for a TW stock using yfinance"""
    try:
        # Fetch 3 months of data to ensure enough for RSI calculation
        df = yf.download(ticker, period="3mo", interval="1d", progress=False)
        if df.empty or len(df) < 15:
            return None
        
        # Calculate RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        current_rsi = rsi.iloc[-1]
        # Handle Series if multiple columns (yfinance update)
        if isinstance(current_rsi, pd.Series):
             current_rsi = current_rsi.iloc[0]

        return int(round(current_rsi))
    except Exception as e:
        print(f"Error fetching TW Stock RSI: {e}")
        return None

def get_status_emoji(value):
    if value <= EXTREME_FEAR_THRESHOLD:
        return "🔴" # Extreme Fear
    if value <= FEAR_THRESHOLD:
        return "🟠" # Fear
    return "🔵" # Neutral/Greed

def get_status_text(value, is_rsi=False):
    if value <= EXTREME_FEAR_THRESHOLD:
        return "極度恐懼"
    if value <= FEAR_THRESHOLD:
        return "RSI偏低" if is_rsi else "恐懼"
    return "安全/貪婪"

def main():
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("Error: LINE_CHANNEL_ACCESS_TOKEN or LINE_USER_ID not set.")
        return

    print("Fetching market data...")
    crypto_fng = fetch_crypto_sentiment()
    us_stock_fng = fetch_us_stock_sentiment()
    tw_stock_rsi = fetch_tw_stock_rsi()

    print(f"Crypto: {crypto_fng}")
    print(f"US Stock: {us_stock_fng}")
    print(f"TW Stock (RSI): {tw_stock_rsi}")

    # Check if ANY market triggers a buy signal (<= 44)
    triggers = []
    
    if crypto_fng is not None and crypto_fng <= FEAR_THRESHOLD:
        triggers.append(f"₿ 加密貨幣: {crypto_fng} ({get_status_text(crypto_fng)} {get_status_emoji(crypto_fng)})")
    
    if us_stock_fng is not None and us_stock_fng <= FEAR_THRESHOLD:
        triggers.append(f"🇺🇸 美股: {us_stock_fng} ({get_status_text(us_stock_fng)} {get_status_emoji(us_stock_fng)})")
        
    if tw_stock_rsi is not None and tw_stock_rsi <= FEAR_THRESHOLD:
        triggers.append(f"🇹🇼 台股(0050): {tw_stock_rsi} ({get_status_text(tw_stock_rsi, is_rsi=True)} {get_status_emoji(tw_stock_rsi)})")

    # If no triggers, exit
    if not triggers:
        print("No buy signals detected. Exiting.")
        return

    # Construct Message
    message_text = "🔥 Smart DCA 訊號觸發 🔥\n\n"
    message_text += "\n".join(triggers)
    message_text += "\n\n💡 建議分批進場"

    print("Sending LINE notification...")
    try:
        configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        api_client = ApiClient(configuration)
        messaging_api = MessagingApi(api_client)

        push_message_request = PushMessageRequest(
            to=LINE_USER_ID,
            messages=[TextMessage(text=message_text)]
        )
        
        messaging_api.push_message(push_message_request)
        print("Notification sent successfully!")

    except Exception as e:
        print(f"Error sending LINE notification: {e}")

if __name__ == "__main__":
    main()


