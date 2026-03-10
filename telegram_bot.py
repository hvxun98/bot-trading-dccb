import ccxt
import time
import pandas as pd
import joblib
import requests
import sys
import csv
import os
from datetime import datetime

# ==========================================================
# CẤU HÌNH BOT TELEGRAM
# ==========================================================
# Khởi tạo biến quản lý lệnh (Global State)
ACTIVE_TRADE = None 

# Hàm hỗ trợ ghi log CSV
def log_trade(trade, close_price, result, pnl, rr):
    file_exists = os.path.isfile('trade_history.csv')
    with open('trade_history.csv', mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['Time_In', 'Time_Out', 'Symbol', 'Side', 'Entry', 'TP', 'SL', 'Close_Price', 'Result', 'PnL_Percent', 'RR_Ratio'])
        
        writer.writerow([
            trade['time_in'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            trade['symbol'], trade['side'], trade['entry'], trade['tp'], trade['sl'], 
            close_price, result, f"{pnl:.2f}%", f"{rr:.2f}"
        ])
    print(f"📝 Đã ghi lịch sử lệnh {result} vào trade_history.csv")
TELEGRAM_TOKEN = "8729643641:AAEZAtdagjwN-dfxmRzpd9WNkooJtEmyN6w" 
TELEGRAM_CHAT_ID = "-1003402240606"  

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
    
    # Tính toán ATR (Average True Range) chu kỳ 14 cho khoảng giá Cắt Lỗ (Stop Loss) an toàn
    df['prev_close'] = df['close'].shift(1)
    df['tr0'] = df['high'] - df['low']
    df['tr1'] = (df['high'] - df['prev_close']).abs()
    df['tr2'] = (df['low'] - df['prev_close']).abs()
    df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df[f'ATR_{tf}'] = df['tr'].rolling(window=14).mean()

    # Trả về Dòng dữ liệu của cây nến mới nhất vừa đóng cửa
    return df.iloc[-2] # iloc[-2] là lấy nến VỪA ĐÓNG. iloc[-1] là nến đang chạy dở chưa đóng hẳn.

def run_live_bot(symbol='BTC/USDT:USDT'):
    global ACTIVE_TRADE
    print("=====================================================")
    print("🤖 HỆ THỐNG AI TỰ QUẢN LÝ QUỸ (SCALPING + TRUNG HẠN) ĐÃ BẬT")
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
            
            is_hourly_candle = (int(current_time + sleep_time) % 3600) < 60
            
            print(f"[{time.strftime('%H:%M:%S')}] Đang canh me... Chờ {int(sleep_time)} giây nữa nến sẽ Đóng.")
            time.sleep(sleep_time)

            print(f"> [{time.strftime('%H:%M:%S')}] Soi nến đa khung và Quản lý Lệnh...")
            f_15m = prep_live_features(exchange, symbol, '15m')
            base_price = f_15m['close']
            
            # ======================== KIỂM TRA LỆNH ĐANG CHẠY ========================
            if ACTIVE_TRADE is not None:
                side = ACTIVE_TRADE['side']
                entry = ACTIVE_TRADE['entry']
                tp = ACTIVE_TRADE['tp']
                sl = ACTIVE_TRADE['sl']
                
                # Check Chốt lời / Cắt lỗ ngay trong nến vừa đóng
                hit_tp = False
                hit_sl = False
                close_pnl = 0.0
                rr = 0.0
                
                if side == "LÔNG 🟢":
                    current_pnl = ((base_price - entry) / entry) * 100
                    if f_15m['high'] >= tp: hit_tp = True
                    elif f_15m['low'] <= sl: hit_sl = True
                else:
                    current_pnl = ((entry - base_price) / entry) * 100
                    if f_15m['low'] <= tp: hit_tp = True
                    elif f_15m['high'] >= sl: hit_sl = True
                
                if hit_tp:
                    close_price = tp
                    rr = abs(tp - entry) / abs(sl - entry)
                    close_pnl = ((close_price - entry) / entry * 100) if side == "LÔNG 🟢" else ((entry - close_price) / entry * 100)
                    msg = f"✅ <b>CHỐT LỜI THÀNH CÔNG (HIT TP)</b> 🎉\n\nCặp: <b>{symbol}</b>\nSide: <b>{side}</b>\nEntry: <b>${entry}</b>\nChốt tại: <b>${close_price}</b>\n\n💰 Lợi nhuận: <b>+{close_pnl:.2f}%</b>\n⚖️ Tỉ lệ RR: <b>1:{rr:.2f}</b>\n\n<i>Boss bú đẫm nhé! Bắt đầu tìm mồi mới...</i>"
                    send_telegram_message(msg)
                    log_trade(ACTIVE_TRADE, close_price, "WIN", close_pnl, rr)
                    ACTIVE_TRADE = None
                    continue # Qua vòng lặp mới săn mồi
                elif hit_sl:
                    close_price = sl
                    rr = -1.0 # Thua luôn mất 1R
                    close_pnl = ((close_price - entry) / entry * 100) if side == "LÔNG 🟢" else ((entry - close_price) / entry * 100)
                    msg = f"❌ <b>CẮT MÁU RỒI ĐẠI CA (HIT SL)</b> 🩸\n\nCặp: <b>{symbol}</b>\nSide: <b>{side}</b>\nEntry: <b>${entry}</b>\nDừng lỗ tại: <b>${close_price}</b>\n\n📉 Âm lòi: <b>{close_pnl:.2f}%</b>\n\n<i>Cú lừa của cá mập... Em đi kiếm kèo gỡ đây!</i>"
                    send_telegram_message(msg)
                    log_trade(ACTIVE_TRADE, close_price, "LOSS", close_pnl, rr)
                    ACTIVE_TRADE = None
                    continue # Bắt đầu tìm mồi mới
                
                # Nếu lệnh vẫn còn sống (Chưa chạm TP/SL), báo cáo tình hình mỗi 15 phút
                if current_pnl > 0:
                    status_msg = f"📈 <i>Lệnh đang dương <b>+{current_pnl:.2f}%</b> nhé các bé, khấn mạnh lên cho anh 🙏</i>"
                elif current_pnl < 0:
                    status_msg = f"📉 <i>Lệnh đang thở oxi <b>{current_pnl:.2f}%</b> các bé ạ 🚑💨</i>"
                else:
                    status_msg = f"⚖️ <i>Lệnh vẫn đang huề vốn, nhọc nhằn quá 😮‍💨</i>"
                
                send_telegram_message(status_msg)
                continue # Dừng luôn luồng soi kèo mới dười đây, sang nến tiếp theo kiểm tra tiếp!

            # =========================================================================

            # Nếu CHƯA CÓ LỆNH, ta báo Tình hình săn mồi
            send_telegram_message("🔎 <i>Anh vẫn đang tìm Entry cho các bé, bình tĩnh nhé! 🚬</i>")

            # Bốc tất cả tính năng tươi của 4 khung mấu chốt để xào nấu
            f_1h = prep_live_features(exchange, symbol, '1h')
            f_4h = prep_live_features(exchange, symbol, '4h')
            f_1d = prep_live_features(exchange, symbol, '1d')

            # ========================LUỒNG 1: SCALPING AI ========================
            features_scalping = [[
                f_15m['close'], f_15m['EMA_10_15m'], f_15m['EMA_50_15m'], f_15m['Body_15m'], f_15m['High_Shadow_15m'], f_15m['Low_Shadow_15m'],
                f_1h['EMA_10_1h'], f_1h['EMA_50_1h'], f_1h['Body_1h'],
                f_4h['EMA_10_4h'], f_4h['EMA_50_4h']
            ]]
            
            prob_scalping = max(model_scalping.predict_proba(features_scalping)[0]) * 100
            pred_scalping = model_scalping.predict(features_scalping)[0]
            
            if prob_scalping > 65.0:
                atr_15m = f_15m['ATR_15m']
                
                # Tạo lý do vào lệnh (Reasoning)
                reason_arr = []
                if f_15m['EMA_10_15m'] > f_15m['EMA_50_15m']: reason_arr.append("EMA10 cắt lên EMA50")
                elif f_15m['EMA_10_15m'] < f_15m['EMA_50_15m']: reason_arr.append("EMA10 cắt xuống EMA50")
                if f_15m['Low_Shadow_15m'] > f_15m['Body_15m'] * 2: reason_arr.append("Nến Rút râu dưới (Lực mua)")
                elif f_15m['High_Shadow_15m'] > f_15m['Body_15m'] * 2: reason_arr.append("Nến Rút râu trên (Lực bán)")
                if f_1h['EMA_10_1h'] > f_1h['EMA_50_1h']: reason_arr.append("Trend H1 ủng hộ Tăng")
                elif f_1h['EMA_10_1h'] < f_1h['EMA_50_1h']: reason_arr.append("Trend H1 ủng hộ Giảm")
                
                reason_str = ", ".join(reason_arr) if reason_arr else "Mô hình nến Price Action bí mật"

                if pred_scalping == 1:
                    side = "LÔNG 🟢"
                    sl_price = base_price - (atr_15m * 1.5)
                    tp_price = base_price + (atr_15m * 3.0)
                else:
                    side = "XOẠC 🔴"
                    sl_price = base_price + (atr_15m * 1.5)
                    tp_price = base_price - (atr_15m * 3.0)
                
                msg = f"⚡ <b>TÍN HIỆU SCALPING VÀO LỆNH</b>\n\nCặp: <b>{side} {symbol}</b>\nBase/Check: <b>M15 v H1</b>\nEntry: <b>${base_price}</b>\n\n🤖<i>Tỉ lệ win: <b>{prob_scalping:.1f}%</b></i>\n🛑 <i>SL: <b>${sl_price:.2f}</b></i>\n🎯 <i>TP: <b>${tp_price:.2f}</b></i>\n\n💡 <b>Lý do Bot vào lệnh:</b>\n<i>- {reason_str}.</i>"
                send_telegram_message(msg)
                
                # Cập nhật Global State
                ACTIVE_TRADE = {
                    'time_in': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'symbol': symbol, 'side': side, 'entry': base_price,
                    'tp': tp_price, 'sl': sl_price
                }
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
                    atr_1h = f_1h['ATR_1h']
                    
                    # Tạo lý do vào lệnh (Reasoning) cho H1
                    reason_arr = []
                    if f_1h['EMA_10_1h'] > f_1h['EMA_50_1h']: reason_arr.append("EMA10 cắt lên EMA50 mạnh")
                    elif f_1h['EMA_10_1h'] < f_1h['EMA_50_1h']: reason_arr.append("EMA10 cắt xuống EMA50 gắt")
                    if f_1h['Low_Shadow_1h'] > f_1h['Body_1h'] * 2: reason_arr.append("Pinbar Rút chân H1")
                    elif f_1h['High_Shadow_1h'] > f_1h['Body_1h'] * 2: reason_arr.append("Pinbar Râu trên H1")
                    if f_1d['EMA_10_1d'] > f_1d['EMA_50_1d']: reason_arr.append("Xu hướng Mùa D1 Tăng")
                    elif f_1d['EMA_10_1d'] < f_1d['EMA_50_1d']: reason_arr.append("Xu hướng Mùa D1 Giảm")
                    
                    reason_str = ", ".join(reason_arr) if reason_arr else "Hành vi giá Cá Mập đè nén"

                    if pred_medium == 1:
                        side = "LÔNG 🟢"
                        sl_price = base_price - (atr_1h * 1.5)
                        tp_price = base_price + (atr_1h * 3.0)
                    else:
                        side = "XOẠC 🔴"
                        sl_price = base_price + (atr_1h * 1.5)
                        tp_price = base_price - (atr_1h * 3.0)

                    msg = f"🏛 <b>TÍN HIỆU TRUNG HẠN VÀO LỆNH</b>\n\n<b>{side} {symbol}</b>\nBase/Check: <b>H1 v H4, D1</b>\nEntry: <b>${base_price}</b>\n\n🤖 <i>Tỉ lệ win: <b>{prob_medium:.1f}%</b></i>\n🛑 <i>SL: <b>${sl_price:.2f}</b></i>\n🎯 <i>TP: <b>${tp_price:.2f}</b></i>\n\n💡 <b>Lý do Bot vào lệnh:</b>\n<i>- {reason_str}.</i>"
                    send_telegram_message(msg)
                    
                    # Cập nhật Global State
                    ACTIVE_TRADE = {
                        'time_in': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'symbol': symbol, 'side': side, 'entry': base_price,
                        'tp': tp_price, 'sl': sl_price
                    }
                else:
                    print(f"⚖️Tín hiệu trung lập, winrate {prob_medium:.1f}% nên bỏ qua.")

        except Exception as e:
            print(f"Lỗi cục bộ đứt cáp: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_live_bot()
