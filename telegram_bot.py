import ccxt
import time
import pandas as pd
import joblib
import requests
import sys

# ==========================================================
# CẤU HÌNH BOT TELEGRAM
# ==========================================================
TELEGRAM_TOKEN = "ĐIỀN_TOKEN_BOT_CỦA_BẠN_VÀO_ĐÂY" 
TELEGRAM_CHAT_ID = "ĐIỀN_ID_NHÓM_HOẶC_ID_USER_CỦA_BẠN"  

def send_telegram_message(message):
    if "ĐIỀN_TOKEN" in TELEGRAM_TOKEN:
        print("\n⚠️ [DEMO MODE] Chưa điền Token. Báo cáo nến:")
        print(message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
        print("📲 Đã bắn tín hiệu Telegram!")
    except Exception as e:
        print(f"❌ Lỗi gửi Telegram: {e}")

def prep_live_features(exchange, symbol, tf):
    """Kéo dữ liệu API tươi và tính Features"""
    ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df[f'EMA_10_{tf}'] = df['close'].ewm(span=10, adjust=False).mean()
    df[f'EMA_50_{tf}'] = df['close'].ewm(span=50, adjust=False).mean()
    df[f'Body_{tf}'] = df['close'] - df['open']
    df[f'High_Shadow_{tf}'] = df['high'] - df[['open', 'close']].max(axis=1)
    df[f'Low_Shadow_{tf}'] = df[['open', 'close']].min(axis=1) - df['low']
    # Trả về Dòng dữ liệu của cây nến mới nhất vừa đóng cửa
    return df.iloc[-2] # iloc[-2] là lấy nến VỪA ĐÓNG. iloc[-1] là nến đang chạy dở chưa đóng hẳn.

def run_live_bot(symbol='BTC/USDT:USDT'):
    print("=====================================================")
    print("🤖 HỆ THỐNG AI ĐA KHUNG (SCALPING + TRUNG HẠN) ĐÃ BẬT")
    print("=====================================================")
    
    try:
        model_scalping = joblib.load('ai_model_scalping.pkl')
        model_medium = joblib.load('ai_model_medium_term.pkl')
        print("✅ Đã NẠP THÀNH CÔNG 2 Não Dữ Liệu!")
    except FileNotFoundError:
        print("❌ Chưa tìm thấy File Brain AI (.pkl)! Hãy ấn 'python train_model.py' trước để máy học!")
        sys.exit(1)

    exchange = ccxt.okx({'enableRateLimit': True})
    loop_interval_sec = 900 # 15 Phút check 1 lần cho Scalping

    while True:
        try:
            current_time = time.time()
            remainder = current_time % loop_interval_sec
            sleep_time = loop_interval_sec - remainder + 3 
            
            # Kiểm tra xem đây là lượt đóng nến 1h chẵn hay chỉ là nến 15m
            # Nếu chẵn 1 tiếng (3600), ta check cả Trung Hạn
            is_hourly_candle = (int(current_time + sleep_time) % 3600) < 60
            
            print(f"[{time.strftime('%H:%M:%S')}] Đang canh me... Chờ {int(sleep_time)} giây nữa nến sẽ Đóng.")
            time.sleep(sleep_time)

            print(f"> [{time.strftime('%H:%M:%S')}] Soi nến đa khung...")
            
            # Bốc tất cả tính năng tươi của 4 khung mấu chốt
            f_15m = prep_live_features(exchange, symbol, '15m')
            f_1h = prep_live_features(exchange, symbol, '1h')
            f_4h = prep_live_features(exchange, symbol, '4h')
            f_1d = prep_live_features(exchange, symbol, '1d')

            base_price = f_15m['close']

            # ========================LUỒNG 1: SCALPING AI ========================
            features_scalping = [[
                f_15m['close'], f_15m['EMA_10_15m'], f_15m['EMA_50_15m'], f_15m['Body_15m'], f_15m['High_Shadow_15m'], f_15m['Low_Shadow_15m'],
                f_1h['EMA_10_1h'], f_1h['EMA_50_1h'], f_1h['Body_1h'],
                f_4h['EMA_10_4h'], f_4h['EMA_50_4h']
            ]]
            
            prob_scalping = max(model_scalping.predict_proba(features_scalping)[0]) * 100
            pred_scalping = model_scalping.predict(features_scalping)[0]
            
            if prob_scalping > 65.0:
                side = "LONG 🟢" if pred_scalping == 1 else "SHORT 🔴"
                msg = f"⚡ <b>TÍN HIỆU SCALPING (Đánh Nhanh)</b>\n\nCặp: <b>{symbol}</b>\nBase/Check: <b>M15 v H1</b>\nThị giá Đóng: <b>${base_price}</b>\n\n🤖 <i>Dự đoán Đánh: <b>{side}</b></i>\n🔥 <i>Tự tin Lưới AI: <b>{prob_scalping:.1f}%</b></i>"
                send_telegram_message(msg)
            else:
                 print(f"⚖️ Tiếng nói AI (Scalping): Tín hiệu nhiễu, winrate {prob_scalping:.1f}% nên bỏ qua.")


            # ========================LUỒNG 2: TRUNG HẠN AI ========================
            if is_hourly_candle:
                features_medium = [[
                    f_1h['close'], f_1h['EMA_10_1h'], f_1h['EMA_50_1h'], f_1h['Body_1h'], f_1h['High_Shadow_1h'], f_1h['Low_Shadow_1h'],
                    f_4h['EMA_10_4h'], f_4h['EMA_50_4h'], f_4h['Body_4h'],
                    f_1d['EMA_10_1d'], f_1d['EMA_50_1d']
                ]]
                
                prob_medium = max(model_medium.predict_proba(features_medium)[0]) * 100
                pred_medium = model_medium.predict(features_medium)[0]
                
                if prob_medium > 60.0:
                    side = "LONG 🟢" if pred_medium == 1 else "SHORT 🔴"
                    msg = f"🏛 <b>TÍN HIỆU TRUNG HẠN (Sóng Dài)</b>\n\nCặp: <b>{symbol}</b>\nBase/Check: <b>H1 v H4, D1</b>\nThị giá Đóng: <b>${base_price}</b>\n\n🤖 <i>Dự đoán Xu hướng: <b>{side}</b></i>\n🛡 <i>Tự tin Lưới AI: <b>{prob_medium:.1f}%</b></i>"
                    send_telegram_message(msg)
                else:
                    print(f"⚖️ Tiếng nói AI (Trung Hạn): Tín hiệu trung lập, winrate {prob_medium:.1f}% nên bỏ qua.")

        except Exception as e:
            print(f"Lỗi cục bộ đứt cáp: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_live_bot()
