import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import joblib

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

def load_and_prep_tf(tf_name):
    """Đọc CSV một khung thời gian và tính toán các đặc trưng (Features) cơ bản"""
    try:
        df = pd.read_csv(f'data/historical_{tf_name}.csv')
    except Exception:
        return None
        
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.sort_values('timestamp', inplace=True)
    
    # Tính các chỉ báo kỹ thuật cơ bản
    df[f'EMA_10_{tf_name}'] = df['close'].ewm(span=10, adjust=False).mean()
    df[f'EMA_50_{tf_name}'] = df['close'].ewm(span=50, adjust=False).mean()
    
    df[f'Body_{tf_name}'] = df['close'] - df['open']
    df[f'High_Shadow_{tf_name}'] = df['high'] - df[['open', 'close']].max(axis=1)
    df[f'Low_Shadow_{tf_name}'] = df[['open', 'close']].min(axis=1) - df['low']
    
    # Tính toán ATR để chuẩn hóa TP/SL khi huấn luyện
    df['prev_close'] = df['close'].shift(1)
    df['tr0'] = df['high'] - df['low']
    df['tr1'] = (df['high'] - df['prev_close']).abs()
    df['tr2'] = (df['low'] - df['prev_close']).abs()
    df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df[f'ATR_{tf_name}'] = df['tr'].rolling(window=14).mean()
    
    # Tính các chỉ báo Tối thượng (RSI & ADX & Đột biến Khối lượng)
    df[f'RSI_{tf_name}'] = calc_rsi(df['close'], period=14)
    df[f'ADX_{tf_name}'] = calc_adx(df, period=14)
    df[f'Vol_Spike_{tf_name}'] = df['volume'] / df['volume'].rolling(window=20).mean() # Khối lượng so với MA20
    
    # Giữ lại các cột quan trọng
    cols_to_keep = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 
                    f'EMA_10_{tf_name}', f'EMA_50_{tf_name}', f'Body_{tf_name}', 
                    f'High_Shadow_{tf_name}', f'Low_Shadow_{tf_name}', f'ATR_{tf_name}',
                    f'RSI_{tf_name}', f'ADX_{tf_name}', f'Vol_Spike_{tf_name}']
    return df[cols_to_keep].dropna()

def build_model(base_df, features, model_name, tf_name, tp_min):
    """Hàm lõi để Training Rừng Ngẫu Nhiên và xuất Model"""
    print(f"Xử lý gán nhãn Win/Loss bằng cách quét giá tương lai (TP/SL)...")
    closes = base_df['close'].values
    highs = base_df['high'].values
    lows = base_df['low'].values
    atrs = base_df[f'ATR_{tf_name}'].values
    
    n = len(closes)
    targets = np.full(n, 2, dtype=int)
    
    for i in range(n - 1):
        entry = closes[i]
        atr = atrs[i]
        if pd.isna(atr): continue
            
        tp_dist = max(atr * 3.0, tp_min)
        sl_dist = tp_dist / 2.0 # SL không quá nửa quãng đường tới TP
        
        long_tp = entry + tp_dist; long_sl = entry - sl_dist
        short_tp = entry - tp_dist; short_sl = entry + sl_dist
        
        target = 2
        for j in range(i + 1, min(i + 100, n)):
            h = highs[j]; l = lows[j]
            long_hit_sl = l <= long_sl; long_hit_tp = h >= long_tp
            short_hit_sl = h >= short_sl; short_hit_tp = l <= short_tp
            
            if long_hit_tp and not long_hit_sl: target = 1; break
            if short_hit_tp and not short_hit_sl: target = 0; break
            if long_hit_sl and short_hit_sl: target = 2; break
                
        targets[i] = target

    base_df['Target'] = targets
    base_df = base_df[base_df['Target'] != 2].copy() # Bỏ các tín hiệu nhiễu không trúng TP
    base_df.dropna(inplace=True)
    
    X = base_df[features]
    y = base_df['Target']
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, shuffle=False)
    
    print(f"\n🧠 Bắt đầu Train Mô hình {model_name}...")
    model = RandomForestClassifier(n_estimators=300, random_state=42, max_depth=12)
    model.fit(X_train, y_train)
    
    acc = accuracy_score(y_test, model.predict(X_test))
    print(f"✅ Tỉ lệ Winrate (Mô hình {model_name}): {acc * 100:.2f}%")
    
    joblib.dump(model, f'{model_name}.pkl')
    print(f"💾 Đã lưu tệp AI vào: {model_name}.pkl")
    return model

def train_scalping_model():
    print("-------------------------------------------------")
    print("📊 XÂY DỰNG MÔ HÌNH SCALPING (Base: M15 | Vĩ mô: H1, H4)")
    
    df_m15 = load_and_prep_tf('15m')
    df_h1 = load_and_prep_tf('1h')
    df_h4 = load_and_prep_tf('4h')
    
    if df_m15 is None or df_h1 is None or df_h4 is None:
        print("❌ Thiếu dữ liệu CSV. Vui lòng chạy fetch_data.py trước!")
        return

    # Ghép nối Dữ liệu bằng merge_asof (Tìm kiếm lùi về quá khứ gần nhất)
    # Nghĩa là tại thời điểm nến M15, AI sẽ biết nến H1 và H4 hiện hành đang thế nào
    merged = pd.merge_asof(df_m15, df_h1, on='timestamp', direction='backward', suffixes=('', '_drop'))
    merged = pd.merge_asof(merged, df_h4, on='timestamp', direction='backward', suffixes=('', '_drop'))
    merged.dropna(inplace=True)

    # Thêm Khung 1D vào mâm cơm để lấy ADX Vĩ Mô cho Scalping (Không dùng D1 để tính Sóng M15, chỉ dùng để check Sideway)
    df_d1 = load_and_prep_tf('1d')
    merged = pd.merge_asof(merged, df_d1[['timestamp', 'ADX_1d']], on='timestamp', direction='backward')
    merged.dropna(inplace=True)

    features = [
        'close', 'EMA_10_15m', 'EMA_50_15m', 'Body_15m', 'High_Shadow_15m', 'Low_Shadow_15m',
        'RSI_15m', 'Vol_Spike_15m',
        'EMA_10_1h', 'EMA_50_1h', 'Body_1h', 'RSI_1h',
        'EMA_10_4h', 'EMA_50_4h',
        'ADX_1d'
    ]
    build_model(merged, features, 'ai_model_scalping', '15m', tp_min=1000)

def train_medium_term_model():
    print("-------------------------------------------------")
    print("📈 XÂY DỰNG MÔ HÌNH TRUNG HẠN (Base: H1 | Vĩ mô: H4, D1)")
    
    df_h1 = load_and_prep_tf('1h')
    df_h4 = load_and_prep_tf('4h')
    df_d1 = load_and_prep_tf('1d')
    
    if df_h1 is None or df_h4 is None or df_d1 is None:
        print("❌ Thiếu dữ liệu CSV. Vui lòng chạy fetch_data.py trước!")
        return

    merged = pd.merge_asof(df_h1, df_h4, on='timestamp', direction='backward', suffixes=('', '_drop'))
    merged = pd.merge_asof(merged, df_d1, on='timestamp', direction='backward', suffixes=('', '_drop'))
    merged.dropna(inplace=True)

    features = [
        'close', 'EMA_10_1h', 'EMA_50_1h', 'Body_1h', 'High_Shadow_1h', 'Low_Shadow_1h',
        'RSI_1h', 'Vol_Spike_1h',
        'EMA_10_4h', 'EMA_50_4h', 'Body_4h', 'RSI_4h',
        'EMA_10_1d', 'EMA_50_1d', 'ADX_1d'
    ]
    build_model(merged, features, 'ai_model_medium_term', '1h', tp_min=2000)

if __name__ == "__main__":
    train_scalping_model()
    train_medium_term_model()
    print("=====================================")
    print("🎉 HOÀN TẤT HUẤN LUYỆN 2 BỘ NÃO AI!")
    print("=====================================")
