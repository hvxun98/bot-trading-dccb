import ccxt
import time
import pandas as pd
import joblib
import requests
import sys
import csv
import os
import threading
import json
from datetime import datetime

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calc_adx(df, period=14):
    up = df['high'] - df['high'].shift(1)
    down = df['low'].shift(1) - df['low']
    pdm = np.where((up > down) & (up > 0), up, 0)
    ndm = np.where((down > up) & (down > 0), down, 0)
    
    tr = df['tr'].rolling(window=period).sum()
    pdi = 100 * pd.Series(pdm, index=df.index).rolling(window=period).sum() / tr
    ndi = 100 * pd.Series(ndm, index=df.index).rolling(window=period).sum() / tr
    
    dx = 100 * (abs(pdi - ndi) / (pdi + ndi))
    return dx.rolling(window=period).mean()

# ==========================================================
# CẤU HÌNH BOT TELEGRAM
# ==========================================================
# Khởi tạo biến quản lý lệnh (Global State đa luồng)
ACTIVE_TRADE_SCALP = None
ACTIVE_TRADE_MEDIUM = None 
# Hàm hỗ trợ ghi log CSV (Cập nhật Trạng thái Lệnh)
def log_trade(trade, status='OPEN', close_price=0, result='OPEN', pnl=0, rr=0):
    file_exists = os.path.isfile('trade_history.csv')
    
    time_out = "" if status == 'OPEN' else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_data = {
        'Trade_ID': str(trade['trade_id']), 'Time_In': trade['time_in'], 'Time_Out': time_out,
        'Symbol': trade['symbol'], 'Side': trade['side'], 'Entry': trade['entry'], 
        'TP': trade['tp'], 'SL': trade['sl'], 'Close_Price': close_price if status != 'OPEN' else "", 
        'Result': result, 'PnL_Value': f"{pnl:.2f}", 'RR_Ratio': f"{rr:.2f}", 'Winrate': f"{trade['winrate']:.1f}%",
        'Timeframe_Origin': trade.get('timeframe_origin', 'Unknown')
    }

    if not file_exists:
        df = pd.DataFrame([new_data])
        df.to_csv('trade_history.csv', index=False, encoding='utf-8')
    else:
        df = pd.read_csv('trade_history.csv', dtype=str)
        if str(trade['trade_id']) in df['Trade_ID'].values: # Đã tồn tại -> Update Dòng
            idx = df.index[df['Trade_ID'] == str(trade['trade_id'])].tolist()[0]
            for k, v in new_data.items():
                df.at[idx, k] = str(v)
        else: # Thêm Mới Dòng
            df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
        df.to_csv('trade_history.csv', index=False, encoding='utf-8')
        
        
    print(f"📝 Đã cập nhật lịch sử lệnh {trade['trade_id']} ({result}) vào trade_history.csv")

# ==========================================================
# CƠ SỞ DỮ LIỆU CẢNH BÁO GIÁ (PRICE ALERTS)
# ==========================================================
ALERT_FILE = 'price_alerts.txt'

def get_price_alerts():
    if not os.path.isfile(ALERT_FILE): return []
    try:
        with open(ALERT_FILE, 'r') as f:
            lines = [line.strip() for line in f if line.strip()]
            return [float(x) for x in lines]
    except Exception:
        return []

def save_price_alerts(alerts):
    with open(ALERT_FILE, 'w') as f:
        for a in sorted(alerts):
            f.write(f"{a}\n")

def add_price_alert(price):
    alerts = get_price_alerts()
    if price in alerts:
        return False, f"⚠️ Mốc <b>${price}</b> đã có sẵn trong danh sách theo dõi rồi Sếp!"
    alerts.append(price)
    save_price_alerts(alerts)
    return True, f"✅ Đã gài bẫy Cảnh báo Giá tại mốc: <b>${price}</b>"

def remove_price_alert(price):
    alerts = get_price_alerts()
    if price not in alerts:
        return False, f"⚠️ Kẻng <b>${price}</b> không tồn tại trong danh sách."
    alerts.remove(price)
    save_price_alerts(alerts)
    return True, f"🗑 Đã gỡ bỏ bẫy Cảnh báo Giá tại mốc: <b>${price}</b>"

def monitor_price_alerts(symbol='BTC/USDT:USDT'):
    """Luồng phụ chạy ngầm mỗi 15s để Check Cảnh báo Giá Realtime"""
    print("🔔 Radar Cảnh báo Giá (15s/lần) đã khởi động!")
    exchange = ccxt.okx({'enableRateLimit': True})
    last_price = None
    
    while True:
        try:
            alerts = get_price_alerts()
            if not alerts:
                time.sleep(15)
                continue
                
            ticker = exchange.fetch_ticker(symbol)
            cur_price = ticker['last']
            
            if last_price is not None:
                triggered = []
                for a in alerts:
                    # Rút râu lên đâm qua mốc
                    if last_price < a and cur_price >= a:
                        triggered.append(a)
                        send_telegram_message(f"🚨 <b>BÁO ĐỘNG ĐỎ</b> 🚨\n\nKiều nữ {symbol.split('/')[0]} vừa đấm TUNG NÓC mốc cản <b>${a}</b>!\n(Giá update: ${cur_price})")
                    # Đạp xuống gãy mốc
                    elif last_price > a and cur_price <= a:
                        triggered.append(a)
                        send_telegram_message(f"🚨 <b>BÁO ĐỘNG ĐEN</b> 🚨\n\nKiều nữ {symbol.split('/')[0]} vừa gãy sập thủng đáy <b>${a}</b>!\n(Giá update: ${cur_price})")
                
                # Xoá các mốc đã hú còi
                if triggered:
                    for t in triggered:
                        remove_price_alert(t)
            
            last_price = cur_price
            time.sleep(15)
            
        except Exception as e:
            print(f"⚠️ Radar Alert nhiễu sóng: {e}")
            time.sleep(15)
    
TELEGRAM_TOKEN = "8729643641:AAEZAtdagjwN-dfxmRzpd9WNkooJtEmyN6w" 
TELEGRAM_CHAT_ID = "-1003402240606"  

def send_telegram_message(message, chat_id=None):
    if chat_id is None:
        chat_id = TELEGRAM_CHAT_ID

    if "ĐIỀN_TOKEN" in TELEGRAM_TOKEN:
        print("\n⚠️ [DEMO MODE] Chưa điền Token. Báo cáo nến:")
        print(message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
        print("📲 Đã bắn tín hiệu Telegram!")
    except Exception as e:
        print(f"❌ Lỗi gửi Telegram: {e}")

last_update_id = 0

def generate_and_send_report(chat_id):
    if not os.path.isfile('trade_history.csv'):
        send_telegram_message("📉 <b>Chưa có dữ liệu giao dịch nào được ghi nhận.</b>", chat_id=chat_id)
        return
        
    try:
        df = pd.read_csv('trade_history.csv')
        wins = len(df[df['Result'] == 'WIN'])
        losses = len(df[df['Result'] == 'LOSS'])
        opens = len(df[df['Result'] == 'OPEN'])
        total_closed = wins + losses
        winrate = (wins / total_closed * 100) if total_closed > 0 else 0
        total_pnl = pd.to_numeric(df['PnL_Value'], errors='coerce').sum()
        
        msg = f"📊 <b>BÁO CÁO CÔNG LÀM VIỆC LƯỚI AI</b> 📊\n\n"
        msg += f"Tổng lệnh đã chốt: <b>{total_closed}</b>\n"
        msg += f"Thắng: <b>{wins}</b> | Thua: <b>{losses}</b>\n"
        msg += f"Tỉ lệ Winrate: <b>{winrate:.1f}%</b>\n"
        msg += f"Tổng Thu nhập (PnL): <b>{total_pnl:.2f} giá</b>\n\n"
        
        
        if opens > 0:
            msg += f"<i>⏳ KẾT VỊ: Đang giữ nguyên <b>{opens}</b> vị thế đi bão chờ chốt lời/cắt lỗ (Gõ /positions)</i>\n"
        else:
            msg += f"<i>💤 Trại lính đang trống, không gồng giữ lệnh nào trên thị trường.</i>\n"
            
        if total_pnl > 0:
            msg += "\n🔥 <i>Sinh lời hiệu quả! Hệ thống rất tự hào về Sếp!</i>"
        elif total_pnl < 0:
            msg += "\n💦 <i>Đang âm vốn sếp ạ, cầu nguyện cùng em nhé!</i>"
        else:
             msg += "\n⚖️ <i>Vốn đang huề, ranh giới sinh tồn mỏng manh!</i>"
            
        send_telegram_message(msg, chat_id=chat_id)
    except Exception as e:
        print(f"Lỗi đọc file history: {e}")

def handle_market_command(chat_id, symbol='BTC/USDT:USDT'):
    try:
        send_telegram_message(f"⏳ Đang thả radar dò sóng <b>{symbol}</b>. Sếp chờ 3 giây...", chat_id=chat_id)
        exchange = ccxt.okx({'enableRateLimit': True})
        
        # Kéo Data D1 và H1 để phân tích vĩ mô (Lấy nến đóng)
        f_1h = prep_live_features(exchange, symbol, '1h')
        f_1d = prep_live_features(exchange, symbol, '1d')
        
        # Kéo giá Khớp Lệnh Tick Thời Gian Thực (Real-time) để hiển thị mặt tiền
        ticker = exchange.fetch_ticker(symbol)
        realtime_price = ticker['last']
        
        adx_1d = f_1d['ADX_1d']
        rsi_1h = f_1h['RSI_1h']
        rsi_1d = f_1d['RSI_1d']
        
        market_regime = "SIDEWAY 🐢 (Đi ngang tích lũy/Phân phối)" if adx_1d < 25 else "TRENDING 🚀 (Sóng chạy theo một hướng)"
        
        msg = f"🌍 <b>BÁO CÁO TOÀN CẢNH {symbol}</b> 🌍\n\n"
        msg += f"Giá hiện tại (Real-time): <b>${realtime_price:,.2f}</b>\n"
        msg += f"Pha Vĩ Mô (D1): <b>{market_regime}</b>\n"
        msg += f"Trương lực Trend (ADX D1): <b>{adx_1d:.1f}</b>\n\n"
        
        msg += f"Sức mạnh Phe Mua/Bán (RSI):\n"
        msg += f"• RSI theo Giờ (1H): <b>{rsi_1h:.1f}</b> "
        msg += "(Quá Mua nổ đỉnh) " if rsi_1h > 70 else ("(Quá Bán sập hầm) " if rsi_1h < 30 else "(Dưỡng Sinh)")
        msg += f"\n• RSI theo Ngày (1D): <b>{rsi_1d:.1f}</b>\n"
        
        send_telegram_message(msg, chat_id=chat_id)
    except Exception as e:
        print(f"Lỗi truy vấn Market: {e}")
        send_telegram_message("❌ Hệ thống cáp quang đo sóng bị nghẽn, sếp thử lại sau nhé!", chat_id=chat_id)

def poll_telegram_commands():
    global last_update_id
    print("👂 Phân luồng nghe lén... Đã kích hoạt radar lệnh Telegram.")
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            params = {'offset': last_update_id + 1, 'timeout': 30}
            resp = requests.get(url, params=params, timeout=35)
            data = resp.json()
            
            if data.get('ok'):
                for result in data['result']:
                    last_update_id = result['update_id']
                    
                    message = result.get('message', {})
                    text = message.get('text', '')
                    chat_id = message.get('chat', {}).get('id')
                    
                    if '/report' in text:  # Bắt /report hoặc tag kèm /report đều được
                        print("🤖 Sếp vừa gọi báo cáo tổng, gửi báo cáo ngay!")
                        generate_and_send_report(chat_id)
                        
                    elif '/positions' in text:
                        print("🤖 Sếp vừa điểm danh quân số, gửi tình trạng vị thế!")
                        if os.path.isfile('trade_history.csv'):
                            df = pd.read_csv('trade_history.csv')
                            open_trades = df[df['Result'] == 'OPEN']
                            if len(open_trades) > 0:
                                msg_pos = f"🛡 <b>ĐANG GIỮ {len(open_trades)} VỊ THẾ KÍN</b>\n\n"
                                for _, row in open_trades.iterrows():
                                    msg_pos += f"🔹 <b>{row['Side']} {row['Symbol']}</b> (<i>{row.get('Timeframe_Origin', 'Khung chưa rõ')} / {row['Trade_ID']}</i>)\n"
                                    msg_pos += f"Entry: <b>${float(row['Entry']):.2f}</b> | SL: <b>${float(row['SL']):.2f}</b> | TP: <b>${float(row['TP']):.2f}</b>\n\n"
                                msg_pos += "<i>👉 Chờ nến mới đóng để cập nhật kết quả.</i>"
                                send_telegram_message(msg_pos, chat_id=chat_id)
                            else:
                                send_telegram_message("💤 <b>Trại lính đang trống. Không có lệnh OPEN nào đang gồng dở.</b>", chat_id=chat_id)
                        else:
                            send_telegram_message("💤 <b>Trại lính đang trống. Chưa từng giao dịch lệnh nào.</b>", chat_id=chat_id)

                    elif '/market' in text:
                        print("🤖 Sếp vừa soi pha thị trường, đi lấy sóng OKX!")
                        handle_market_command(chat_id)
                    
                    elif text.startswith('/alert'):
                        parts = text.split()
                        if len(parts) >= 2:
                            try:
                                price = float(parts[1])
                                ok, msg = add_price_alert(price)
                                send_telegram_message(msg, chat_id=chat_id)
                                if ok:
                                    current_list = get_price_alerts()
                                    send_telegram_message(f"📋 <b>Danh sách Bẫy:</b>\n" + "\n".join([f"- ${p}" for p in current_list]), chat_id=chat_id)
                            except ValueError:
                                send_telegram_message("❌ Sai cú pháp. Sếp gõ kiểu: <code>/alert 69000</code> nhé.", chat_id=chat_id)
                        else:
                            alerts = get_price_alerts()
                            if alerts:
                                send_telegram_message(f"📋 <b>Danh sách Bẫy hiện có:</b>\n" + "\n".join([f"- ${p}" for p in alerts]), chat_id=chat_id)
                            else:
                                send_telegram_message("💤 Điểm danh trống. Sếp chưa gài mốc cảnh báo nào.", chat_id=chat_id)

                    elif text.startswith('/remove'):
                        parts = text.split()
                        if len(parts) >= 2:
                            try:
                                price = float(parts[1])
                                ok, msg = remove_price_alert(price)
                                send_telegram_message(msg, chat_id=chat_id)
                            except ValueError:
                                send_telegram_message("❌ Sai cú pháp. Sếp gõ kiểu: <code>/remove 69000</code> nhé.", chat_id=chat_id)
                        else:
                            send_telegram_message("❌ Thiếu Giá. Sếp gõ kiểu: <code>/remove 69000</code> nhé.", chat_id=chat_id)

        except Exception as e:
            time.sleep(5)

import numpy as np

def prep_live_features(exchange, symbol, tf):
    """Kéo dữ liệu API tươi và tính Features"""
    ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=120)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df[f'EMA_10_{tf}'] = df['close'].ewm(span=10, adjust=False).mean()
    df[f'EMA_50_{tf}'] = df['close'].ewm(span=50, adjust=False).mean()
    df[f'Body_{tf}'] = df['close'] - df['open']
    df[f'High_Shadow_{tf}'] = df['high'] - df[['open', 'close']].max(axis=1)
    df[f'Low_Shadow_{tf}'] = df[['open', 'close']].min(axis=1) - df['low']
    
    # Tính toán ATR (Average True Range)
    df['prev_close'] = df['close'].shift(1)
    df['tr0'] = df['high'] - df['low']
    df['tr1'] = (df['high'] - df['prev_close']).abs()
    df['tr2'] = (df['low'] - df['prev_close']).abs()
    df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df[f'ATR_{tf}'] = df['tr'].rolling(window=14).mean()
    
    # Tính các chỉ báo chuyên sâu (RSI, ADX, Volume Spike)
    df[f'RSI_{tf}'] = calc_rsi(df['close'], period=14)
    df[f'ADX_{tf}'] = calc_adx(df, period=14)
    df[f'Vol_Spike_{tf}'] = df['volume'] / df['volume'].rolling(window=20).mean()

    # Trả về Dòng dữ liệu của cây nến mới nhất vừa đóng cửa
    return df.iloc[-2] # iloc[-2] là lấy nến VỪA ĐÓNG. iloc[-1] là nến đang chạy dở chưa đóng hẳn.

def check_manage_trade(trade, f_15m, base_price, is_hourly_candle):
    if trade is None: return None
    side, entry, tp, sl = trade['side'], trade['entry'], trade['tp'], trade['sl']
    hit_tp, hit_sl, close_pnl, rr = False, False, 0.0, 0.0
    
    if side == "LÔNG 🟢":
        current_pnl = base_price - entry
        if f_15m['high'] >= tp: hit_tp = True
        elif f_15m['low'] <= sl: hit_sl = True
    else:
        current_pnl = entry - base_price
        if f_15m['low'] <= tp: hit_tp = True
        elif f_15m['high'] >= sl: hit_sl = True
    
    if hit_tp:
        close_price = tp
        rr = abs(tp - entry) / abs(sl - entry)
        close_pnl = (close_price - entry) if side == "LÔNG 🟢" else (entry - close_price)
        msg = f"✅ <b>CHỐT LỜI THÀNH CÔNG (HIT TP)</b> 🎉\n\nID: <b>{trade['trade_id']}</b>\nCặp: <b>{trade['symbol']}</b> (<i>{trade.get('timeframe_origin', '')}</i>)\nSide: <b>{side}</b>\nEntry: <b>${entry}</b>\nChốt tại: <b>${close_price}</b>\n\n💰 Lợi nhuận: <b>+{close_pnl:.2f} giá</b>\n⚖️ Tỉ lệ RR: <b>1:{rr:.2f}</b>\n\n<i>Boss bú đẫm nhé! Bắt đầu tìm mồi mới luồng này...</i>"
        send_telegram_message(msg)
        log_trade(trade, status='WIN', close_price=close_price, result='WIN', pnl=close_pnl, rr=rr)
        return None
    elif hit_sl:
        close_price = sl
        rr = -1.0 # Thua luôn mất 1R
        close_pnl = (close_price - entry) if side == "LÔNG 🟢" else (entry - close_price)
        msg = f"❌ <b>CẮT MÁU RỒI ĐẠI CA (HIT SL)</b> 🩸\n\nID: <b>{trade['trade_id']}</b>\nCặp: <b>{trade['symbol']}</b> (<i>{trade.get('timeframe_origin', '')}</i>)\nSide: <b>{side}</b>\nEntry: <b>${entry}</b>\nDừng lỗ tại: <b>${close_price}</b>\n\n📉 Âm lòi: <b>{close_pnl:.2f} giá</b>\n\n<i>Cú lừa của cá mập... Em đi kiếm kèo luồng này gỡ đây!</i>"
        send_telegram_message(msg)
        log_trade(trade, status='LOSS', close_price=close_price, result='LOSS', pnl=close_pnl, rr=rr)
        return None
    
    if is_hourly_candle:
        t_id = trade['trade_id']
        if current_pnl > 0:
            send_telegram_message(f"📈 <i>Lệnh {trade.get('timeframe_origin', '')} [ID: {t_id}] đang dương <b>+{current_pnl:.2f} giá</b> nhé các bé...</i>")
        elif current_pnl < 0:
            send_telegram_message(f"📉 <i>Lệnh {trade.get('timeframe_origin', '')} [ID: {t_id}] đang thở oxi <b>{current_pnl:.2f} giá</b> các bé ạ 🚑💨</i>")
        else:
            send_telegram_message(f"⚖️ <i>Lệnh {trade.get('timeframe_origin', '')} [ID: {t_id}] vẫn đang huề vốn...</i>")
    
    return trade

def run_live_bot(symbol='BTC/USDT:USDT'):
    global ACTIVE_TRADE_SCALP, ACTIVE_TRADE_MEDIUM
    print("=====================================================")
    print("🤖 HỆ THỐNG AI TỰ QUẢN LÝ QUỸ (SCALPING + TRUNG HẠN) ĐÃ BẬT")
    print("=====================================================")
    
    # Kích hoạt vệ sĩ Radar nghe ngóng lệnh chat từ Sếp trên 1 luồng riêng
    threading.Thread(target=poll_telegram_commands, daemon=True).start()
    # Kích hoạt Radar mồi giá Alert mỗi 15 giây
    threading.Thread(target=monitor_price_alerts, args=(symbol,), daemon=True).start()
    
    
    try:
        model_scalping = joblib.load('ai_model_scalping.pkl')
        model_medium = joblib.load('ai_model_medium_term.pkl')
        print("✅ Đã NẠP THÀNH CÔNG 2 Não Dữ Liệu!")
    except FileNotFoundError:
        print("❌ Chưa tìm thấy File Brain AI (.pkl)! Hãy ấn 'python train_model.py' trước để máy học!")
        sys.exit(1)

    # Khôi phục trạng thái gồng lệnh từ DB (Phòng hờ tắt Bot bật lại)
    if os.path.isfile('trade_history.csv'):
        try:
            df_hist = pd.read_csv('trade_history.csv', dtype=str)
            open_trades = df_hist[df_hist['Result'] == 'OPEN']
            if len(open_trades) > 0:
                for _, last_open in open_trades.iterrows():
                    trade_obj = {
                        'trade_id': last_open['Trade_ID'],
                        'time_in': last_open['Time_In'],
                        'symbol': last_open['Symbol'],
                        'side': last_open['Side'],
                        'entry': float(last_open['Entry']),
                        'tp': float(last_open['TP']),
                        'sl': float(last_open['SL']),
                        'winrate': float(last_open['Winrate'].replace('%', '') if '%' in str(last_open['Winrate']) else last_open['Winrate']),
                        'timeframe_origin': last_open.get('Timeframe_Origin', 'Unknown')
                    }
                    if 'Scalping' in trade_obj['timeframe_origin']:
                        ACTIVE_TRADE_SCALP = trade_obj
                        print(f"🔄 Đã KHÔI PHỤC lệnh SCALP từ CSV: ID [{trade_obj['trade_id']}]")
                    else:
                        ACTIVE_TRADE_MEDIUM = trade_obj
                        print(f"🔄 Đã KHÔI PHỤC lệnh TRUNG HẠN từ CSV: ID [{trade_obj['trade_id']}]")
        except Exception as e:
            print(f"⚠️ Lỗi khôi phục lệnh: {e}")

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
            if ACTIVE_TRADE_SCALP is not None:
                ACTIVE_TRADE_SCALP = check_manage_trade(ACTIVE_TRADE_SCALP, f_15m, base_price, is_hourly_candle)
            
            if ACTIVE_TRADE_MEDIUM is not None:
                ACTIVE_TRADE_MEDIUM = check_manage_trade(ACTIVE_TRADE_MEDIUM, f_15m, base_price, is_hourly_candle)
            
            # =========================================================================

            # Nếu CHƯA CÓ LỆNH Ở CẢ 2 LUỒNG, ta báo Tình hình săn mồi MỖI 1 GIỜ
            if ACTIVE_TRADE_SCALP is None and ACTIVE_TRADE_MEDIUM is None:
                if is_hourly_candle:
                    send_telegram_message("🔎 <i>Anh vẫn đang tìm Entry cho các bé, bình tĩnh nhé! 🚬</i>")

            # Bốc tất cả tính năng tươi của 4 khung mấu chốt để xào nấu
            f_1h = prep_live_features(exchange, symbol, '1h')
            f_4h = prep_live_features(exchange, symbol, '4h')
            f_1d = prep_live_features(exchange, symbol, '1d')
            
            adx_d1 = f_1d['ADX_1d']
            market_regime = "SIDEWAY 🐢" if adx_d1 < 25 else "TRENDING 🚀"

            # ========================LUỒNG 1: SCALPING AI ========================
            if ACTIVE_TRADE_SCALP is None:
                features_scalping = [[
                    f_15m['close'], f_15m['EMA_10_15m'], f_15m['EMA_50_15m'], f_15m['Body_15m'], f_15m['High_Shadow_15m'], f_15m['Low_Shadow_15m'],
                    f_15m['RSI_15m'], f_15m['Vol_Spike_15m'],
                    f_1h['EMA_10_1h'], f_1h['EMA_50_1h'], f_1h['Body_1h'], f_1h['RSI_1h'],
                    f_4h['EMA_10_4h'], f_4h['EMA_50_4h'],
                    f_1d['ADX_1d']
                ]]
                
                prob_scalping = max(model_scalping.predict_proba(features_scalping)[0]) * 100
                pred_scalping = model_scalping.predict(features_scalping)[0]
                
                if prob_scalping > 65.0:
                    atr_15m = f_15m['ATR_15m']
                    
                    # Tính khoảng cách TP/SL, bắt buộc TP cách bét nhất 1000 giá
                    tp_dist = max(atr_15m * 3.0, 1000)
                    sl_dist = tp_dist / 2.0
                    
                    # Tạo lý do vào lệnh (Reasoning)
                    reason_arr = []
                    if f_15m['EMA_10_15m'] > f_15m['EMA_50_15m']: reason_arr.append("EMA10 cắt lên EMA50")
                    elif f_15m['EMA_10_15m'] < f_15m['EMA_50_15m']: reason_arr.append("EMA10 cắt xuống EMA50")
                    if f_15m['Low_Shadow_15m'] > f_15m['Body_15m'] * 2: reason_arr.append("Nến Rút râu dưới (Lực mua)")
                    elif f_15m['High_Shadow_15m'] > f_15m['Body_15m'] * 2: reason_arr.append("Nến Rút râu trên (Lực bán)")
                    if f_1h['EMA_10_1h'] > f_1h['EMA_50_1h']: reason_arr.append("Trend H1 ủng hộ Tăng")
                    elif f_1h['EMA_10_1h'] < f_1h['EMA_50_1h']: reason_arr.append("Trend H1 ủng hộ Giảm")
                    
                    reason_str = "\n- ".join(reason_arr) if reason_arr else "Tín hiệu AI hội tụ"
                    
                    # Rút gọn symbol (Ví dụ BTC/USDT:USDT -> BTC)
                    base_coin = symbol.split('/')[0]
    
                    if pred_scalping == 1:
                        side = "LÔNG 🟢"
                        sl_price = base_price - sl_dist
                        tp_price = base_price + tp_dist
                    else:
                        side = "XOẠC 🔴"
                        sl_price = base_price + sl_dist
                        tp_price = base_price - tp_dist
                    
                    trade_id = str(int(time.time()))
                    msg = f"⚡ <b>TÍN HIỆU SCALPING CHẠM BIẾN</b>\n\nID: <b>{trade_id}</b>\n🌍 Bối cảnh D1: <b>{market_regime} (ADX: {adx_d1:.1f})</b>\n\n<b>{side} {base_coin}</b>\nBase/Check: <b>M15 v H1</b>\nEntry: <b>${base_price}</b>\n\n🤖<i>Tỉ lệ win: <b>{prob_scalping:.1f}%</b></i>\n🛑 <i>SL: <b>${sl_price:.2f}</b></i>\n🎯 <i>TP: <b>${tp_price:.2f}</b></i>\n\n💡 <b>Lập luận:</b>\n<i>- {reason_str}.</i>"
                    send_telegram_message(msg)
                    
                    # Cập nhật Global State
                    ACTIVE_TRADE_SCALP = {
                        'trade_id': trade_id,
                        'time_in': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'symbol': symbol, 'side': side, 'entry': base_price,
                        'tp': tp_price, 'sl': sl_price, 'winrate': prob_scalping,
                        'timeframe_origin': 'M15 Scalping'
                    }
                    log_trade(ACTIVE_TRADE_SCALP, status='OPEN', result='OPEN')
                    
                else:
                     print(f"⚖️ Tiếng nói AI (Scalping): Tín hiệu nhiễu, winrate {prob_scalping:.1f}% nên bỏ qua.")


            # ========================LUỒNG 2: TRUNG HẠN AI ========================
            if is_hourly_candle and ACTIVE_TRADE_MEDIUM is None:
                features_medium = [[
                    f_1h['close'], f_1h['EMA_10_1h'], f_1h['EMA_50_1h'], f_1h['Body_1h'], f_1h['High_Shadow_1h'], f_1h['Low_Shadow_1h'],
                    f_1h['RSI_1h'], f_1h['Vol_Spike_1h'],
                    f_4h['EMA_10_4h'], f_4h['EMA_50_4h'], f_4h['Body_4h'], f_4h['RSI_4h'],
                    f_1d['EMA_10_1d'], f_1d['EMA_50_1d'], f_1d['ADX_1d']
                ]]
                
                prob_medium = max(model_medium.predict_proba(features_medium)[0]) * 100
                pred_medium = model_medium.predict(features_medium)[0]
                
                if prob_medium > 60.0:
                    atr_1h = f_1h['ATR_1h']
                    
                    # Tính khoảng cách TP/SL, bắt buộc TP cách bét nhất 2000 giá
                    tp_dist = max(atr_1h * 3.0, 2000)
                    sl_dist = tp_dist / 2.0
                    
                    # Tạo lý do vào lệnh (Reasoning) cho H1
                    reason_arr = []
                    if f_1h['EMA_10_1h'] > f_1h['EMA_50_1h']: reason_arr.append("EMA10 cắt lên EMA50 mạnh")
                    elif f_1h['EMA_10_1h'] < f_1h['EMA_50_1h']: reason_arr.append("EMA10 cắt xuống EMA50 gắt")
                    if f_1h['Low_Shadow_1h'] > f_1h['Body_1h'] * 2: reason_arr.append("Pinbar Rút chân H1")
                    elif f_1h['High_Shadow_1h'] > f_1h['Body_1h'] * 2: reason_arr.append("Pinbar Râu trên H1")
                    if f_1d['EMA_10_1d'] > f_1d['EMA_50_1d']: reason_arr.append("Xu hướng Mùa D1 Tăng")
                    elif f_1d['EMA_10_1d'] < f_1d['EMA_50_1d']: reason_arr.append("Xu hướng Mùa D1 Giảm")
                    
                    reason_str = "\n- ".join(reason_arr) if reason_arr else "Tín hiệu siêu sóng hội tụ"
                    
                    # Rút gọn symbol cho nến H1
                    base_coin = symbol.split('/')[0]
    
                    if pred_medium == 1:
                        side = "LÔNG 🟢"
                        sl_price = base_price - sl_dist
                        tp_price = base_price + tp_dist
                    else:
                        side = "XOẠC 🔴"
                        sl_price = base_price + sl_dist
                        tp_price = base_price - tp_dist
    
                    trade_id = str(int(time.time()))
                    msg = f"🏛 <b>TÍN HIỆU TRUNG HẠN SÓNG DÀI</b>\n\nID: <b>{trade_id}</b>\n🌍 Bối cảnh D1: <b>{market_regime} (ADX: {adx_d1:.1f})</b>\n\n<b>{side} {base_coin}</b>\nBase/Check: <b>H1 v H4, D1</b>\nEntry: <b>${base_price}</b>\n\n🤖 <i>Tỉ lệ win: <b>{prob_medium:.1f}%</b></i>\n🛑 <i>SL: <b>${sl_price:.2f}</b></i>\n🎯 <i>TP: <b>${tp_price:.2f}</b></i>\n\n💡 <b>Lập luận:</b>\n<i>- {reason_str}.</i>"
                    send_telegram_message(msg)
                    
                    # Cập nhật Global State
                    ACTIVE_TRADE_MEDIUM = {
                        'trade_id': trade_id,
                        'time_in': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'symbol': symbol, 'side': side, 'entry': base_price,
                        'tp': tp_price, 'sl': sl_price, 'winrate': prob_medium,
                        'timeframe_origin': 'H1 Trung Hạn'
                    }
                    log_trade(ACTIVE_TRADE_MEDIUM, status='OPEN', result='OPEN')
                    
                else:
                    print(f"⚖️Tín hiệu trung lập, winrate {prob_medium:.1f}% nên bỏ qua.")

        except Exception as e:
            print(f"Lỗi cục bộ đứt cáp: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_live_bot()
