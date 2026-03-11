import pandas as pd
import os
from datetime import datetime

trade = {
    'trade_id': '1773197104',
    'time_in': '2026-03-11 09:45:00',
    'symbol': 'BTC/USDT:USDT',
    'side': 'XOẠC 🔴',
    'entry': 69661.2,
    'tp': 68661.20,
    'sl': 70161.20,
    'winrate': 70.2,
    'timeframe_origin': 'M15 Scalping'
}

file_exists = os.path.isfile('trade_history.csv')

new_data = {
    'Trade_ID': str(trade['trade_id']), 'Time_In': trade['time_in'], 'Time_Out': "",
    'Symbol': trade['symbol'], 'Side': trade['side'], 'Entry': trade['entry'], 
    'TP': trade['tp'], 'SL': trade['sl'], 'Close_Price': "", 
    'Result': 'OPEN', 'PnL_Value': "0.00", 'RR_Ratio': "0.00", 'Winrate': f"{trade['winrate']:.1f}%",
    'Timeframe_Origin': trade['timeframe_origin']
}

if not file_exists:
    df = pd.DataFrame([new_data])
    df.to_csv('trade_history.csv', index=False, encoding='utf-8')
else:
    df = pd.read_csv('trade_history.csv', dtype=str)
    if str(trade['trade_id']) in df['Trade_ID'].values:
        idx = df.index[df['Trade_ID'] == str(trade['trade_id'])].tolist()[0]
        for k, v in new_data.items():
            df.at[idx, k] = str(v)
    else:
        df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
    df.to_csv('trade_history.csv', index=False, encoding='utf-8')
    
print(f"📝 Đã CHÈN LỆNH {trade['trade_id']} vào trade_history.csv")
