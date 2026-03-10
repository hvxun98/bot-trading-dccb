import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import joblib

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
    
    # Giữ lại các cột quan trọng
    cols_to_keep = ['timestamp', 'close', f'EMA_10_{tf_name}', f'EMA_50_{tf_name}', f'Body_{tf_name}', f'High_Shadow_{tf_name}', f'Low_Shadow_{tf_name}']
    return df[cols_to_keep].dropna()

def build_model(base_df, features, model_name):
    """Hàm lõi để Training Rừng Ngẫu Nhiên và xuất Model"""
    # 1: Sẽ Tăng, 0: Sẽ Giảm (Dựa vào giá close của cây nến Base tiếp theo)
    base_df['Target'] = (base_df['close'].shift(-1) > base_df['close']).astype(int)
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

    features = [
        'close', 'EMA_10_15m', 'EMA_50_15m', 'Body_15m', 'High_Shadow_15m', 'Low_Shadow_15m',
        'EMA_10_1h', 'EMA_50_1h', 'Body_1h',
        'EMA_10_4h', 'EMA_50_4h'
    ]
    build_model(merged, features, 'ai_model_scalping')

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
        'EMA_10_4h', 'EMA_50_4h', 'Body_4h',
        'EMA_10_1d', 'EMA_50_1d'
    ]
    build_model(merged, features, 'ai_model_medium_term')

if __name__ == "__main__":
    train_scalping_model()
    train_medium_term_model()
    print("=====================================")
    print("🎉 HOÀN TẤT HUẤN LUYỆN 2 BỘ NÃO AI!")
    print("=====================================")
