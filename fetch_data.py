import ccxt
import pandas as pd
import os
import time

def fetch_historical_data(symbol='BTC/USDT:USDT', limit=1500):
    """
    Công cụ thu thập nến chuẩn bị nguyên liệu cho nền tảng Đa Khung Thời Gian.
    Bao gồm: M5, M15 (Scalping) - H1, H4 (Trung Hạn) - D1, 1W (Xu Hướng Vĩ Mô)
    """
    print(f"🔄 Bắt đầu dọn dẹp và tải dữ liệu lịch sử {symbol} từ OKX...")
    
    # Kết nối API OKX, không cài key
    exchange = ccxt.okx({'enableRateLimit': True})
    
    timeframes = ['5m', '15m', '1h', '4h', '1d', '1w']
    os.makedirs('data', exist_ok=True)
    
    for tf in timeframes:
        print(f"  👉 Đang cào dữ liệu khung {tf}...")
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            file_path = f"data/historical_{tf}.csv"
            df.to_csv(file_path, index=False)
            print(f"     ✅ Đã lưu {len(df)} nến vào: {file_path}")
            
            # Ngủ 1 nhịp nhẹ để tránh vượt rate-limit OKX (IP ban)
            time.sleep(1)
            
        except Exception as e:
            print(f"     ❌ Lỗi tải khung {tf}: {e}")

if __name__ == "__main__":
    fetch_historical_data(symbol='BTC/USDT:USDT', limit=1500)
