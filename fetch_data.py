import ccxt
import pandas as pd
import os
import time

def fetch_historical_data(symbol='BTC/USDT:USDT', since_year=2020):
    """
    Công cụ thu thập nến chuẩn bị nguyên liệu cho nền tảng Đa Khung Thời Gian.
    Bao gồm: M5, M15 (Scalping) - H1, H4 (Trung Hạn) - D1, 1W (Xu Hướng Vĩ Mô)
    Kéo data lặp lại cuốn chiếu (Pagination) từ năm được chỉ định cho tới hiện tại.
    """
    print(f"🔄 Bắt đầu dọn dẹp và tải dữ liệu lịch sử {symbol} từ năm {since_year}...")
    
    # Kết nối API OKX, không cài key
    exchange = ccxt.okx({'enableRateLimit': True})
    
    timeframes = ['5m', '15m', '1h', '4h', '1d', '1w']
    os.makedirs('data', exist_ok=True)
    
    # Tính mốc thời gian bắt đầu cào (Timestamp milliseconds)
    since_ms = exchange.parse8601(f"{since_year}-01-01T00:00:00Z")
    
    for tf in timeframes:
        print(f"  👉 Đang cào dữ liệu khung {tf} từ năm {since_year}...")
        all_candles = []
        current_since = since_ms
        
        try:
            while True:
                # OKX max giới hạn 100 nến mỗi lần gọi, ta sẽ lặp liên tục dời mốc thời gian lên
                ohlcv = exchange.fetch_ohlcv(symbol, tf, since=current_since, limit=100)
                if not ohlcv:
                    break
                    
                all_candles.extend(ohlcv)
                # Dời mốc bắt đầu lên cây nến cuối cùng + 1 tick để tránh bị trùng lặp
                current_since = ohlcv[-1][0] + 1
                
                # In tiến trình (ẩn bớt)
                if len(all_candles) % 5000 == 0:
                    print(f"     ⏳ Đã lấy được {len(all_candles)} nến {tf}...")
                    
                # Ngủ nhẹ để tránh đánh sập đường truyền OKX
                time.sleep(0.12)
                
            df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # Xóa các dòng trùng lặp (nếu nối nến gối đầu nhau)
            df.drop_duplicates(subset='timestamp', inplace=True)
            
            file_path = f"data/historical_{tf}.csv"
            df.to_csv(file_path, index=False)
            print(f"     ✅ TỔNG CỘNG Đã lưu {len(df)} nến vào: {file_path}")
            
        except Exception as e:
            print(f"     ❌ Lỗi tải khung {tf}: {e}")

if __name__ == "__main__":
    fetch_historical_data(symbol='BTC/USDT:USDT', since_year=2020)
