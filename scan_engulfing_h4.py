"""
Quét tìm các cặp nến Nhấn Chìm (Engulfing) trên khung H4 - BTC/USDT
Bao gồm: Bullish Engulfing (Nhấn chìm tăng) + Bearish Engulfing (Nhấn chìm giảm)
Thời gian: 1 năm trở lại đây
"""
import pandas as pd
from datetime import datetime, timedelta, timezone

# Đọc dữ liệu H4
df = pd.read_csv('data/historical_4h.csv')
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Chuyển múi giờ từ UTC sang UTC+7 (Giờ Việt Nam)
utc_plus_7 = timezone(timedelta(hours=7))
df['timestamp'] = df['timestamp'] + timedelta(hours=7)

# Lọc 1 năm trở lại đây
one_year_ago = datetime.now() - timedelta(days=365)
df = df[df['timestamp'] >= one_year_ago].reset_index(drop=True)

print(f"📊 Tổng số nến H4 trong 1 năm qua: {len(df)}")
print(f"📅 Từ: {df['timestamp'].iloc[0]} → Đến: {df['timestamp'].iloc[-1]}")
print("=" * 90)

results = []

for i in range(1, len(df)):
    prev = df.iloc[i - 1]  # Nến trước
    curr = df.iloc[i]      # Nến hiện tại

    prev_open, prev_close = prev['open'], prev['close']
    curr_open, curr_close = curr['open'], curr['close']

    prev_body = abs(prev_close - prev_open)
    curr_body = abs(curr_close - curr_open)

    # Bỏ qua nến body quá nhỏ (doji)
    if prev_body < 10 or curr_body < 10:
        continue

    signal = None
    
    # BULLISH ENGULFING (Nhấn chìm tăng):
    # Nến trước: Đỏ (close < open)
    # Nến hiện tại: Xanh (close > open)
    # Body nến xanh bao trùm hoàn toàn body nến đỏ
    if prev_close < prev_open and curr_close > curr_open:
        if curr_open <= prev_close and curr_close >= prev_open:
            signal = "🟢 BULLISH ENGULFING (Nhấn chìm TĂNG)"

    # BEARISH ENGULFING (Nhấn chìm giảm):
    # Nến trước: Xanh (close > open)
    # Nến hiện tại: Đỏ (close < open)
    # Body nến đỏ bao trùm hoàn toàn body nến xanh
    elif prev_close > prev_open and curr_close < curr_open:
        if curr_open >= prev_close and curr_close <= prev_open:
            signal = "🔴 BEARISH ENGULFING (Nhấn chìm GIẢM)"

    if signal:
        # Tính thêm thống kê
        body_ratio = curr_body / prev_body if prev_body > 0 else 0
        price_change = curr_close - prev_close
        vol_change = curr['volume'] / prev['volume'] if prev['volume'] > 0 else 0

        results.append({
            'timestamp': curr['timestamp'],
            'signal': signal,
            'prev_open': prev_open,
            'prev_close': prev_close,
            'curr_open': curr_open,
            'curr_close': curr_close,
            'curr_high': curr['high'],
            'curr_low': curr['low'],
            'body_ratio': body_ratio,
            'volume': curr['volume'],
            'vol_ratio': vol_change,
            'price_change': price_change,
        })

# Tạo DataFrame kết quả
df_results = pd.DataFrame(results)

bull_count = len(df_results[df_results['signal'].str.contains('BULLISH')])
bear_count = len(df_results[df_results['signal'].str.contains('BEARISH')])

print(f"\n🔍 TỔNG SỐ CẶP NẾN NHẤN CHÌM TÌM THẤY: {len(df_results)}")
print(f"   🟢 Bullish Engulfing (Tăng): {bull_count}")
print(f"   🔴 Bearish Engulfing (Giảm): {bear_count}")
print("=" * 90)

# In chi tiết từng cặp
for idx, row in df_results.iterrows():
    ts = row['timestamp'].strftime('%Y-%m-%d %H:%M')
    sig = row['signal']
    strength = "💪 MẠNH" if row['body_ratio'] >= 1.5 and row['vol_ratio'] >= 1.2 else "📌 Bình thường"
    
    print(f"\n{'─' * 70}")
    print(f"  📅 {ts}  |  {sig}")
    print(f"  Nến trước: Open ${row['prev_open']:.1f} → Close ${row['prev_close']:.1f}")
    print(f"  Nến nhấn:  Open ${row['curr_open']:.1f} → Close ${row['curr_close']:.1f}  (H: ${row['curr_high']:.1f} / L: ${row['curr_low']:.1f})")
    print(f"  Body Ratio: x{row['body_ratio']:.2f} | Vol Ratio: x{row['vol_ratio']:.2f} | Chất lượng: {strength}")

print(f"\n{'=' * 90}")
print(f"📊 TỔNG KẾT: {bull_count} Bullish + {bear_count} Bearish = {len(df_results)} cặp Engulfing trong 1 năm")

# Lưu kết quả ra CSV
output_file = 'data/engulfing_h4_results.csv'
df_results.to_csv(output_file, index=False, encoding='utf-8')
print(f"\n💾 Đã lưu kết quả chi tiết vào: {output_file}")
