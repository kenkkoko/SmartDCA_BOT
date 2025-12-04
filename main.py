import os
import requests
import yfinance as yf
import pandas as pd
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    BroadcastRequest,
    TextMessage
)
import google.generativeai as genai

# --- Configuration ---
# ⚠️ Critical: Read tokens from environment variables for security
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
# LINE_USER_ID is no longer needed for broadcast, but keeping it in env is fine

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
        # CNN structure handling
        if 'fear_and_greed' in data:
            score = int(round(data['fear_and_greed']['score']))
            return score
        return None
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

def generate_ai_advice(market_status_list):
    """Generates DCA advice using Gemini AI"""
    if not GEMINI_API_KEY:
        return "⚠️ AI 建議無法產生 (未設定 API Key)"

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.0-flash')
        
        prompt = f"""
        你是一位極度穩健的 DCA (平均成本法) 投資顧問。你的核心策略是嚴格遵守「在市場情緒極度恐懼時才強力買入」的紀律。

        請根據以下觸發的市場數據，提供一個**簡潔、明確**的操作建議 (50字以內)。

        **分析重點：**
        1. 立即指出市場是否處於「極度恐懼」(FNG/RSI <= 25)。
        2. 強調如果市場處於極度恐懼區間，應當**立即執行最大額度**的 DCA 投入。
        3. 如果市場處於「恐懼」(FNG/RSI <= 44)，建議保持耐心，**按計劃分批小額買入**。
        4. 如果同時有多個市場觸發訊號，請給出綜合建議。

        當前觸發的市場狀態:
        {chr(10).join(market_status_list)}

        根據以上資訊，你的行動建議是？
        """
        
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Error generating AI advice: {e}")
        return "⚠️ AI 暫時無法提供建議"

def main():
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("Error: LINE_CHANNEL_ACCESS_TOKEN not set.")
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
        triggers.append(f"🪙 加密貨幣: {crypto_fng} ({get_status_text(crypto_fng)} {get_status_emoji(crypto_fng)})")
    
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
    
    # Generate AI Advice
    print("Generating AI advice...")
    ai_advice = generate_ai_advice(triggers)
    message_text += f"\n\n🤖 **AI 投資顧問建議**:\n{ai_advice}"
    
    message_text += "\n\n💡 建議分批進場"

    print("Broadcasting LINE notification...")
    try:
        configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
        api_client = ApiClient(configuration)
        messaging_api = MessagingApi(api_client)

        # Broadcast Request (Sends to ALL friends)
        broadcast_request = BroadcastRequest(
            messages=[TextMessage(text=message_text)]
        )
        
        messaging_api.broadcast(broadcast_request)
        print("Broadcast sent successfully!")

    except Exception as e:
        print(f"Error sending LINE notification: {e}")

if __name__ == "__main__":
    main()
