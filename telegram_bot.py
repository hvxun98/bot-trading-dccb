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
    """Luồng phụ chạy ngầm mỗi 15s để Check Cảnh báo Giá + TP/SL + Quét Kèo M5/H1 Realtime"""
    print("🔔 Radar Siêu Tốc (15s/lần) đã khởi động! [Cooldown + RSI + Vol + EMA Filter]")
    exchange = ccxt.okx({'enableRateLimit': True})
    last_price = None
    last_m5_ts = 0   # Timestamp nến M5 cuối cùng đã xử lý (Chống Bắn Trùng)
    last_h1_ts = 0   # Timestamp nến H1 cuối cùng đã xử lý (Chống Bắn Trùng)
    
    while True:
        try:
            alerts = get_price_alerts()
            ticker = exchange.fetch_ticker(symbol)
            cur_price = ticker['last']
            
            if last_price is not None:
                # 1. Check Cảnh báo Alert Thủ công
                triggered = []
                for a in alerts:
                    # Rút râu lên đâm qua mốc
                    if last_price < a and cur_price >= a:
                        triggered.append(a)
                        send_telegram_message(f"🚨 <b>BÁO ĐỘNG TẾT</b> 🚨\n\nKiều nữ {symbol.split('/')[0]} vừa đấm TUNG NÓC mốc cản <b>${a}</b>!\n(Giá update: ${cur_price})")
                    # Đạp xuống gãy mốc
                    elif last_price > a and cur_price <= a:
                        triggered.append(a)
                        send_telegram_message(f"🚨 <b>BÁO ĐỘNG ĐEN</b> 🚨\n\nKiều nữ {symbol.split('/')[0]} vừa gãy sập thủng đáy <b>${a}</b>!\n(Giá update: ${cur_price})")
                
                if triggered:
                    for t in triggered:
                        remove_price_alert(t)

                # 2. Check Chốt lời / Cắt Lỗ TỰ ĐỘNG cho lệnh đang chạy (Real-time)
                global ACTIVE_TRADE_SCALP, ACTIVE_TRADE_MEDIUM
                
                # Hàm check chung
                def process_realtime_tp_sl(trade):
                    if trade is None: return None
                    side, entry, tp, sl = trade['side'], trade['entry'], trade['tp'], trade['sl']
                    
                    hit_tp, hit_sl = False, False
                    if side == "LÔNG 🟢":
                        if cur_price >= tp: hit_tp = True
                        elif cur_price <= sl: hit_sl = True
                    else:
                        if cur_price <= tp: hit_tp = True
                        elif cur_price >= sl: hit_sl = True

                    if hit_tp:
                        close_price = tp
                        rr = abs(tp - entry) / abs(sl - entry)
                        close_pnl = (close_price - entry) if side == "LÔNG 🟢" else (entry - close_price)
                        msg = f"⚡✅ <b>BÚ TP REALTIME RỒI ANH EM</b> 🎉\n\nID: <b>{trade['trade_id']}</b>\nCặp: <b>{trade['symbol']}</b> (<i>{trade.get('timeframe_origin', '')}</i>)\nSide: <b>{side}</b>\nEntry: <b>${entry}</b>\nChốt tại: <b>${close_price}</b>\n\n💰 Lợi nhuận: <b>+{close_pnl:.2f} giá</b>\n⚖️ Tỉ lệ RR: <b>1:{rr:.2f}</b>\n\n<i>Boss sắm Mẹc nhé! Bắt đầu rình mồi mới luồng này...</i>"
                        send_telegram_message(msg)
                        log_trade(trade, status='WIN', close_price=close_price, result='WIN', pnl=close_pnl, rr=rr)
                        return None
                    elif hit_sl:
                        close_price = sl
                        rr = -1.0 # Thua luôn mất 1R
                        close_pnl = (close_price - entry) if side == "LÔNG 🟢" else (entry - close_price)
                        msg = f"⚡❌ <b>SẬP HẦM CHẠM SL (Realtime)</b> 🩸\n\nID: <b>{trade['trade_id']}</b>\nCặp: <b>{trade['symbol']}</b> (<i>{trade.get('timeframe_origin', '')}</i>)\nSide: <b>{side}</b>\nEntry: <b>${entry}</b>\nDừng lỗ tại: <b>${close_price}</b>\n\n📉 Âm lòi: <b>{close_pnl:.2f} giá</b>\n\n<i>Cú lừa của cá mập... Em đi kiếm kèo luồng này gỡ đây!</i>"
                        send_telegram_message(msg)
                        log_trade(trade, status='LOSS', close_price=close_price, result='LOSS', pnl=close_pnl, rr=rr)
                        return None
                    
                    return trade # Trả lại nguyên gốc nếu chưa chạm mức nào
                
                # Áp dụng hàm Check Realtime cho cả 2 Não
                # Áp dụng hàm Check Realtime cho cả 2 Não
                ACTIVE_TRADE_SCALP = process_realtime_tp_sl(ACTIVE_TRADE_SCALP)
                ACTIVE_TRADE_MEDIUM = process_realtime_tp_sl(ACTIVE_TRADE_MEDIUM)
            
            # 3. QUÉT KÈO THƠM (PRICE ACTION M5) NẾU ĐANG RẢNH TAY SCALP
            if ACTIVE_TRADE_SCALP is None:
                try:
                    # Kéo 60 cây nến M5 để tính RSI, EMA, Volume
                    ohlcv_5m = exchange.fetch_ohlcv(symbol, '5m', limit=60)
                    if len(ohlcv_5m) >= 3 and ohlcv_5m[-2][0] != last_m5_ts:
                        last_m5_ts = ohlcv_5m[-2][0] # Đánh dấu nến này đã xử lý
                        
                        # Tính RSI(14), EMA(50), Volume MA(20) trên chuỗi nến M5
                        df_m5 = pd.DataFrame(ohlcv_5m, columns=['ts','open','high','low','close','volume'])
                        df_m5['rsi'] = calc_rsi(df_m5['close'], 14)
                        df_m5['ema50'] = df_m5['close'].ewm(span=50, adjust=False).mean()
                        df_m5['vol_ma20'] = df_m5['volume'].rolling(20).mean()
                        
                        rsi_val = df_m5['rsi'].iloc[-2]
                        ema50_val = df_m5['ema50'].iloc[-2]
                        vol_val = df_m5['volume'].iloc[-2]
                        vol_ma = df_m5['vol_ma20'].iloc[-2]
                        
                        prev_candle = ohlcv_5m[-2] # Nến vừa đóng hoàn toàn
                        open_p, high_p, low_p, close_p = prev_candle[1], prev_candle[2], prev_candle[3], prev_candle[4]
                        
                        body_size = abs(close_p - open_p)
                        upper_shadow = high_p - max(open_p, close_p)
                        lower_shadow = min(open_p, close_p) - low_p
                        candle_range = high_p - low_p
                        
                        signal = None
                        entry_price = cur_price
                        sl_price = 0
                        filter_info = ""
                        
                        # Điều kiện Pinbar Đảo Chiều Tăng (Bullish Pinbar)
                        if lower_shadow > body_size * 2 and upper_shadow < body_size and candle_range > 0:
                            signal = "LÔNG 🟢"
                            sl_price = low_p * 0.999
                            msg_reason = "Búa Cước Xanh (Bullish Pinbar) rút râu cực mạnh dưới đáy."
                        
                        # Điều kiện Pinbar Đảo Chiều Giảm (Bearish Pinbar)
                        elif upper_shadow > body_size * 2 and lower_shadow < body_size and candle_range > 0:
                            signal = "XOẠC 🔴"
                            sl_price = high_p * 1.001
                            msg_reason = "Búa Rớt Náo (Bearish Pinbar) xả dao cắm đầu từ đỉnh."
                        
                        # Engulfing (Nhấn chìm)
                        if signal is None:
                            prev2_candle = ohlcv_5m[-3]
                            open_p2, close_p2 = prev2_candle[1], prev2_candle[4]
                            if close_p2 < open_p2 and close_p > open_p:
                                if open_p <= close_p2 and close_p > open_p2:
                                    signal = "LÔNG 🟢"
                                    sl_price = min(low_p, prev2_candle[3]) * 0.999
                                    msg_reason = "Nến Xanh Nhấn Chìm Đỏ (Bullish Engulfing)."
                            elif close_p2 > open_p2 and close_p < open_p:
                                if open_p >= close_p2 and close_p < open_p2:
                                    signal = "XOẠC 🔴"
                                    sl_price = max(high_p, prev2_candle[2]) * 1.001
                                    msg_reason = "Nến Đỏ Nhấn Chìm Xanh (Bearish Engulfing)."
                        
                        # BỘ LỌC AN TOÀN: RSI + Volume + EMA Trend
                        if signal is not None:
                            vol_ok = pd.notna(vol_ma) and vol_val >= vol_ma * 0.8
                            if signal == "LÔNG 🟢":
                                rsi_ok = pd.notna(rsi_val) and rsi_val < 70
                                ema_ok = pd.notna(ema50_val) and cur_price >= ema50_val
                            else:
                                rsi_ok = pd.notna(rsi_val) and rsi_val > 30
                                ema_ok = pd.notna(ema50_val) and cur_price <= ema50_val
                            
                            if not rsi_ok:
                                print(f"❌ M5 bị RSI chặn ({rsi_val:.1f}). Bỏ qua.")
                                signal = None
                            elif not vol_ok:
                                print(f"❌ M5 Volume quá nhỏ ({vol_val:.0f} < MA20 {vol_ma:.0f}). Bỏ qua.")
                                signal = None
                            elif not ema_ok:
                                print(f"❌ M5 giá ngược EMA50 ({ema50_val:.2f}). Bỏ qua.")
                                signal = None
                            else:
                                filter_info = f"RSI={rsi_val:.1f} | Vol={vol_val:.0f} | EMA50=${ema50_val:.2f}"
                        
                        # Nếu đã đậu bộ lọc -> Vô Kèo
                        # Nếu đã đậu bộ lọc -> Vô Kèo
                        if signal is not None:
                            # Ban đầu tính TP theo RR 1:1.5 từ râu nến
                            tp_price = entry_price + (entry_price - sl_price) * 1.5 if signal == "LÔNG 🟢" else entry_price - (sl_price - entry_price) * 1.5
                            
                            # Hard filter: Bắt buộc cài biên chốt lãi tối thiểu là 1000 giá cho kèo Scalp
                            diff_tp = abs(tp_price - entry_price)
                            is_hard_fixed = False
                            if diff_tp < 1000:
                                
                                # -- THẨM ĐỊNH XÁC SUẤT KHẢ THI (FEASIBILITY CHECK) --
                                is_feasible = True
                                target_tp = entry_price + 1000 if signal == "LÔNG 🟢" else entry_price - 1000
                                
                                # Tìm Kháng Cự / Hỗ Trợ trong 60 nến M5 qua
                                local_high = df_m5['high'].max()
                                local_low = df_m5['low'].min()
                                
                                # Tính lực nến (Momentum) của 3 cây nến gần nhất (Dồn Volume)
                                recent_vol = df_m5['volume'].iloc[-4:-1].sum()
                                avg_vol_x3 = vol_ma * 3
                                has_momentum = recent_vol > avg_vol_x3 * 1.2 # Lực đẩy gấp 1.2 lần trung bình
                                
                                if signal == "LÔNG 🟢":
                                    # Nếu có Kháng cự (local_high) nằm tr chắn đường TP 1000 giá
                                    if local_high < target_tp and entry_price < local_high:
                                        dist_to_res = local_high - entry_price
                                        if dist_to_res < 500 and not has_momentum:
                                            print(f"❌ M5 bị chặn bởi Kháng Cự ${local_high:.0f} (cách {dist_to_res:.0f} giá) + Lực Yếu. Bỏ kèo.")
                                            is_feasible = False
                                elif signal == "XOẠC 🔴":
                                    # Nếu có Hỗ trợ (local_low) nằm chắn đường TP 1000 giá
                                    if local_low > target_tp and entry_price > local_low:
                                        dist_to_sup = entry_price - local_low
                                        if dist_to_sup < 500 and not has_momentum:
                                            print(f"❌ M5 bị chặn bởi Hỗ Trợ ${local_low:.0f} (cách {dist_to_sup:.0f} giá) + Lực Yếu. Bỏ kèo.")
                                            is_feasible = False

                                if is_feasible:
                                    is_hard_fixed = True
                                    tp_price = target_tp
                                    sl_price = entry_price - (1000 / 1.5) if signal == "LÔNG 🟢" else entry_price + (1000 / 1.5)
                                else:
                                    signal = None # Hủy kèo nếu không khả thi
                                    
                        # Xác nhận lệnh Cuối cùng
                        if signal is not None:
                            trade_id = str(int(time.time()))
                            ACTIVE_TRADE_SCALP = {
                                "trade_id": trade_id, "symbol": symbol,
                                "timeframe_origin": "M5 Tốc Chiến", "side": signal,
                                "entry": entry_price, "tp": tp_price, "sl": sl_price,
                                "winrate": 0,
                                "time_in": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }
                            
                            msg_scalp = f"⚡ <b>TÍN HIỆU KÈO THƠM (SCALP M5) ĐÃ BẮN!</b> ⚡\n\n"
                            msg_scalp += f"🔍 Tín hiệu: <b>{msg_reason}</b>\n"
                            msg_scalp += f"📊 Bộ lọc: <i>{filter_info}</i>\n\n"
                            msg_scalp += f"Cặp: <b>{symbol}</b> | Chiều: <b>{signal}</b>\n"
                            msg_scalp += f"Entry: <b>${entry_price:.2f}</b>\n"
                            msg_scalp += f"SL: <b>${sl_price:.2f}</b> | TP: <b>${tp_price:.2f}</b> (RR 1:1.5)\n"
                            if is_hard_fixed:
                                msg_scalp += f"⚠️ <i>(Đã ép biên độ TP tối thiểu dãn đủ 1000 giá)</i>\n\n"
                            else:
                                msg_scalp += "\n"
                            msg_scalp += f"<i>(Bot tự ôm lệnh Scalp - gồng luôn cho tới bến!)</i>"
                            
                            send_telegram_message(msg_scalp)
                            log_trade(ACTIVE_TRADE_SCALP, status='OPEN')
                            
                except Exception as ex_m5:
                    print(f"Lỗi rình mồi M5: {ex_m5}")
                    
            # 4. QUÉT KÈO TRUNG HẠN (H1 HỢP LƯU H4) NẾU ĐANG RẢNH TAY
            if ACTIVE_TRADE_MEDIUM is None:
                try:
                    # Kéo 60 cây nến H1 để tính RSI, EMA, Volume
                    ohlcv_1h = exchange.fetch_ohlcv(symbol, '1h', limit=60)
                    ohlcv_4h = exchange.fetch_ohlcv(symbol, '4h', limit=3)
                    
                    if len(ohlcv_1h) >= 3 and len(ohlcv_4h) >= 2 and ohlcv_1h[-2][0] != last_h1_ts:
                        last_h1_ts = ohlcv_1h[-2][0] # Chống bắn trùng
                        
                        # Tính RSI(14), EMA(50), Volume MA(20) trên H1
                        df_h1 = pd.DataFrame(ohlcv_1h, columns=['ts','open','high','low','close','volume'])
                        df_h1['rsi'] = calc_rsi(df_h1['close'], 14)
                        df_h1['ema50'] = df_h1['close'].ewm(span=50, adjust=False).mean()
                        df_h1['vol_ma20'] = df_h1['volume'].rolling(20).mean()
                        
                        rsi_h1 = df_h1['rsi'].iloc[-2]
                        ema50_h1 = df_h1['ema50'].iloc[-2]
                        vol_h1 = df_h1['volume'].iloc[-2]
                        vol_ma_h1 = df_h1['vol_ma20'].iloc[-2]
                        
                        h1_prev = ohlcv_1h[-2]
                        h1_o, h1_h, h1_l, h1_c = h1_prev[1], h1_prev[2], h1_prev[3], h1_prev[4]
                        
                        h4_prev = ohlcv_4h[-2]
                        h4_o, h4_h, h4_l, h4_c = h4_prev[1], h4_prev[2], h4_prev[3], h4_prev[4]
                        
                        h1_body = abs(h1_c - h1_o)
                        h1_up_shadow = h1_h - max(h1_o, h1_c)
                        h1_dn_shadow = min(h1_o, h1_c) - h1_l
                        h1_range = h1_h - h1_l
                        
                        h4_body = abs(h4_c - h4_o)
                        h4_up_shadow = h4_h - max(h4_o, h4_c)
                        h4_dn_shadow = min(h4_o, h4_c) - h4_l
                        
                        signal = None
                        entry_price = cur_price
                        sl_price = 0
                        msg_reason = ""
                        filter_info = ""
                        
                        # 4.1 BẮT ĐÁY (LONG)
                        is_h1_bull_pinbar = h1_dn_shadow > h1_body * 2 and h1_up_shadow < h1_body and h1_range > 0
                        is_h1_bull_engulfing = False
                        h1_prev2 = ohlcv_1h[-3]
                        if not is_h1_bull_pinbar:
                            if h1_prev2[4] < h1_prev2[1] and h1_c > h1_o:
                                if h1_o <= h1_prev2[4] and h1_c > h1_prev2[1]:
                                    is_h1_bull_engulfing = True
                        
                        h4_bull_confirm = (h4_c > h4_o) or (h4_dn_shadow > h4_body * 1.5)
                        if (is_h1_bull_pinbar or is_h1_bull_engulfing) and h4_bull_confirm:
                            signal = "LÔNG 🟢"
                            sl_price = min(h1_l, h1_prev2[3]) * 0.997
                            msg_reason = "H1 Búa/Nhấn chìm Đáy, H4 xác nhận Đỡ Lực."
                        
                        # 4.2 BẮT ĐỈNH (SHORT)
                        is_h1_bear_pinbar = h1_up_shadow > h1_body * 2 and h1_dn_shadow < h1_body and h1_range > 0
                        is_h1_bear_engulfing = False
                        if not is_h1_bear_pinbar and signal is None:
                            if h1_prev2[4] > h1_prev2[1] and h1_c < h1_o:
                                if h1_o >= h1_prev2[4] and h1_c < h1_prev2[1]:
                                    is_h1_bear_engulfing = True
                        h4_bear_confirm = (h4_c < h4_o) or (h4_up_shadow > h4_body * 1.5)
                        if (is_h1_bear_pinbar or is_h1_bear_engulfing) and h4_bear_confirm and signal is None:
                            signal = "XOẠC 🔴"
                            sl_price = max(h1_h, h1_prev2[2]) * 1.003
                            msg_reason = "H1 Búa ngược/Nhấn chìm Đỉnh, H4 xác nhận Chặn giá."
                        
                        # BỘ LỌC AN TOÀN H1: RSI + Volume + EMA
                        if signal is not None:
                            vol_ok = pd.notna(vol_ma_h1) and vol_h1 >= vol_ma_h1 * 0.8
                            if signal == "LÔNG 🟢":
                                rsi_ok = pd.notna(rsi_h1) and rsi_h1 < 70
                                ema_ok = pd.notna(ema50_h1) and cur_price >= ema50_h1
                            else:
                                rsi_ok = pd.notna(rsi_h1) and rsi_h1 > 30
                                ema_ok = pd.notna(ema50_h1) and cur_price <= ema50_h1
                            
                            if not rsi_ok:
                                print(f"❌ H1 bị RSI chặn ({rsi_h1:.1f}). Bỏ qua.")
                                signal = None
                            elif not vol_ok:
                                print(f"❌ H1 Volume quá nhỏ. Bỏ qua.")
                                signal = None
                            elif not ema_ok:
                                print(f"❌ H1 giá ngược EMA50 (${ema50_h1:.2f}). Bỏ qua.")
                                signal = None
                            else:
                                filter_info = f"RSI={rsi_h1:.1f} | Vol={vol_h1:.0f} | EMA50=${ema50_h1:.2f}"
                            
                        # VÔ LỆNH TRUNG HẠN
                        if signal is not None:
                            tp_price = entry_price + (entry_price - sl_price) * 2.5 if signal == "LÔNG 🟢" else entry_price - (sl_price - entry_price) * 2.5
                            trade_id = str(int(time.time()))
                            ACTIVE_TRADE_MEDIUM = {
                                "trade_id": trade_id, "symbol": symbol,
                                "timeframe_origin": "H1 Hợp Lưu H4", "side": signal,
                                "entry": entry_price, "tp": tp_price, "sl": sl_price,
                                "winrate": 0,
                                "time_in": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }
                            
                            msg_med = f"🦅 <b>KÈO ĐẠI BÀNG TRUNG HẠN (H1/H4) ĐÃ CẤT CÁNH!</b> 🦅\n\n"
                            msg_med += f"🔍 Tín hiệu: <b>{msg_reason}</b>\n"
                            msg_med += f"📊 Bộ lọc: <i>{filter_info}</i>\n\n"
                            msg_med += f"Cặp: <b>{symbol}</b> | Chiều: <b>{signal}</b>\n"
                            msg_med += f"Entry: <b>${entry_price:.2f}</b>\n"
                            msg_med += f"SL: <b>${sl_price:.2f}</b> | TP: <b>${tp_price:.2f}</b> (RR 1:2.5)\n\n"
                            msg_med += f"<i>(Dao rơi trúng đỉnh, rìu bổ trúng đáy!)</i>"
                            
                            send_telegram_message(msg_med)
                            log_trade(ACTIVE_TRADE_MEDIUM, status='OPEN')
                            
                except Exception as ex_med:
                    print(f"Lỗi rình mồi H1/H4: {ex_med}")

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

def get_trend_status(df, tf, cur_price):
    try:
        ema50 = df[f'EMA_50_{tf}']
        rsi = df[f'RSI_{tf}']
        
        # Nếu giá chênh lệch với EMA50 quá nhỏ (< 0.1%) -> Sideway
        diff_pct = abs(cur_price - ema50) / ema50 * 100
        
        if diff_pct < 0.15 or (40 <= rsi <= 60):
            return "🐢 SIDEWAY (Tích lũy)"
        elif cur_price > ema50 and rsi > 50:
            return "🟢 TĂNG (Up)"
        elif cur_price < ema50 and rsi < 50:
            return "🔴 GIẢM (Down)"
        else:
            return "🐢 SIDEWAY (Giằng co)"
    except:
        return "❓ Không rõ"

def handle_market_command(chat_id, symbol='BTC/USDT:USDT'):
    try:
        exchange = ccxt.okx({'enableRateLimit': True})
        ticker = exchange.fetch_ticker(symbol)
        realtime_price = ticker['last']
        
        timeframes = ['5m', '15m', '1h', '4h', '1d']
        features = {}
        for tf in timeframes:
            try:
                features[tf] = prep_live_features(exchange, symbol, tf)
            except Exception as e:
                print(f"Lỗi kéo TF {tf}: {e}")
                features[tf] = None

        msg = f"🌍 <b>BÁO CÁO TOÀN CẢNH {symbol}</b> 🌍\n\n"
        msg += f"Giá hiện tại (Real-time): <b>${realtime_price:,.2f}</b>\n\n"
        
        msg += f"📊 <b>BẢN ĐỒ XU HƯỚNG MÀU CỜ SẮC ÁO:</b>\n"
        
        for tf in timeframes:
            if features[tf] is not None:
                trend = get_trend_status(features[tf], tf, realtime_price)
                rsi_val = features[tf][f'RSI_{tf}']
                msg += f"• Khung <b>{tf.upper()}</b>: {trend} <i>(RSI: {rsi_val:.0f})</i>\n"
            else:
                msg += f"• Khung <b>{tf.upper()}</b>: ⚠️ Lỗi Data\n"
        
        msg += "\n💡 <i>Mẹo: Đồng màu H1/H4/D1 thì mạnh tay, lệch màu thì đánh hold bé lại!</i>"
        
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
                                try:
                                    exchange = ccxt.okx({'enableRateLimit': True})
                                    for _, row in open_trades.iterrows():
                                        sym = row['Symbol']
                                        cur_price = exchange.fetch_ticker(sym)['last']
                                        side = row['Side']
                                        entry = float(row['Entry'])
                                        tp = float(row['TP'])
                                        sl = float(row['SL'])
                                        
                                        if "LÔNG" in side:
                                            pnl = cur_price - entry
                                            dist_tp = tp - cur_price
                                            dist_sl = cur_price - sl
                                        else:
                                            pnl = entry - cur_price
                                            dist_tp = cur_price - tp
                                            dist_sl = sl - cur_price
                                            
                                        pnl_str = f"+{pnl:.2f} giá 🟢" if pnl > 0 else f"{pnl:.2f} giá 🔴"
                                        
                                        msg_pos += f"🔹 <b>{side} {sym}</b> (<i>{row.get('Timeframe_Origin', 'Khung chưa rõ')} / ID: {row['Trade_ID']}</i>)\n"
                                        msg_pos += f"Entry: <b>${entry:.2f}</b> | Giá hiện tại: <b>${cur_price:.2f}</b>\n"
                                        msg_pos += f"🎯 PnL Tạm tính: <b>{pnl_str}</b>\n"
                                        msg_pos += f"Cách TP (${tp:.2f}): <b>{max(0, dist_tp):.2f} giá</b>\n"
                                        msg_pos += f"Cách SL (${sl:.2f}): <b>{max(0, dist_sl):.2f} giá</b>\n\n"
                                    send_telegram_message(msg_pos, chat_id=chat_id)
                                except Exception as e:
                                    print(f"Lỗi lấy giá /positions: {e}")
                                    send_telegram_message("❌ Hệ thống cáp quang đang nghẽn, không check tạm ứng được!", chat_id=chat_id)

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

def check_manage_trade(trade, base_price, is_hourly_candle):
    if trade is None: return None
    side, entry = trade['side'], trade['entry']
    
    current_pnl = (base_price - entry) if side == "LÔNG 🟢" else (entry - base_price)
    
    # Chỉ làm nhiệm vụ báo cáo trạng thái Âm/Dương mỗi giờ, xoá phần cắt lỗ uỷ nhiệm cho luồng 15s.
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
            
            # ======================== KIỂM TRA BÁO CÁO LỆNH (Mỗi 1h) ========================
            if ACTIVE_TRADE_SCALP is not None:
                ACTIVE_TRADE_SCALP = check_manage_trade(ACTIVE_TRADE_SCALP, base_price, is_hourly_candle)
            
            if ACTIVE_TRADE_MEDIUM is not None:
                ACTIVE_TRADE_MEDIUM = check_manage_trade(ACTIVE_TRADE_MEDIUM, base_price, is_hourly_candle)
            
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
