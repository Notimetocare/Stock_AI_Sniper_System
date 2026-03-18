import os
import pandas as pd
import yfinance as yf
import time
import random
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# ⚙️ V51 系統參數設定 (Yahoo Finance 終極版)
# ==========================================

# 1. 檔案路徑
EXCEL_PATH = r"D:\Stock_HP_new\AI_TRAIN23\STOCK.xlsx"
DIR_WEEKLY = r"D:\Stock_HP_new\AI_TRAIN23\stock_process_US_SCAN_WATCHLIST\structure"
DIR_DAILY = r"D:\Stock_HP_new\AI_TRAIN23\stock_process_US_SCAN_WATCHLIST\PRESSURE_BAND_V3_6_BreakdownMark\MODERATE\DAY_DATA"

# 2. 下載設定
# YF 不太擋 IP，我們可以開快一點
DOWNLOAD_WORKERS = 6  # 8核心全速下載
SAFE_SLEEP_TIME = 1.7  # 只需要極短的休息

print(f"🚀 [Yahoo Finance 終極還原版] 啟動")
print(f"🔥 核心: auto_adjust=True (自動還原股價，無缺口)")
print(f"⚡ 狀態: 免 Token / 免 IP 限制 / 極速下載")


# ==========================================
# 🛠️ V51 格式強制執法者 (Format Enforcer)
# ==========================================
def enforce_v51_format(df):
    """
    將 YF 下載的資料強制轉換為 V51 標準格式
    """
    # 1. 欄位正規化
    df.columns = [c.lower() for c in df.columns]

    # 2. 欄位對應
    rename_map = {
        'date': 'Datetime', 'datetime': 'Datetime',
        'open': 'Open', 'high': 'High', 'low': 'Low',
        'close': 'Close', 'volume': 'Volume'
    }
    df.rename(columns=rename_map, inplace=True)

    # 3. 完整性檢查
    required_cols = ['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']
    if not all(col in df.columns for col in required_cols):
        return None

    # 4. 強制排序與清洗
    df = df[required_cols].copy()

    # 處理時區問題 (YF 會有時區，需移除)
    if df['Datetime'].dt.tz is not None:
        df['Datetime'] = df['Datetime'].dt.tz_localize(None)

    for c in ['Open', 'High', 'Low', 'Close', 'Volume']:
        df[c] = pd.to_numeric(df[c], errors='coerce')

    df.dropna(inplace=True)
    return df


# ==========================================
# 核心下載任務 (YF)
# ==========================================
def task_process_stock(symbol):
    path_week = os.path.join(DIR_WEEKLY, f"{symbol}_1wk_with_structure.csv")
    path_daily = os.path.join(DIR_DAILY, f"{symbol}_daily.csv")

    if os.path.exists(path_week) and os.path.getsize(path_week) > 1000 and \
            os.path.exists(path_daily) and os.path.getsize(path_daily) > 1000:
        print(f"⏩ {symbol} 資料已齊全，跳過。")
        return

    time.sleep(SAFE_SLEEP_TIME * random.uniform(0.8, 1.2))

    try:
        # 處理代碼 (台股需加 .TW 或 .TWO)
        yf_sym = symbol
        # YF 對台股的代號判定有時需要嘗試
        # 這裡我們使用一個內部 helper 來抓取

        df = pd.DataFrame()

        # 定義抓取函數 (開啟自動還原!)
        def fetch_yf(ticker):
            # ★★★ 關鍵：auto_adjust=True ★★★
            # 這會自動把除權息缺口補平，得到完美的連續 K 線
            return yf.Ticker(ticker).history(start="2020-01-01", interval="1d", auto_adjust=True)

        # 1. 嘗試直接抓
        df = fetch_yf(yf_sym)

        # 2. 如果是台股且沒抓到，嘗試切換 TW/TWO
        if df.empty and ('.TW' in yf_sym or '.TWO' in yf_sym):
            alt_sym = yf_sym.replace('.TW', '.TWO') if '.TW' in yf_sym else yf_sym.replace('.TWO', '.TW')
            df = fetch_yf(alt_sym)

        if df.empty:
            print(f"❌ {symbol}: YF 無資料")
            return

        # 重設 Index 以取得 Date 欄位
        df.reset_index(inplace=True)

        # --- 格式化 ---
        df = enforce_v51_format(df)
        if df is None: return

        df.set_index('Datetime', inplace=True)
        df.sort_index(inplace=True)

        # --- 輸出 A: 日線 ---
        if not df.empty:
            df.reset_index().to_csv(path_daily, index=False)

        # --- 輸出 B: 週線 (Resample) ---
        logic = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
        df_week = df.resample('W-FRI').agg(logic)
        df_week.dropna(inplace=True)
        df_week.reset_index(inplace=True)

        # V51 週線對齊邏輯 (對齊週一)
        df_week['Datetime'] = df_week['Datetime'] - pd.to_timedelta(df_week['Datetime'].dt.dayofweek, unit='D')

        if not df_week.empty:
            df_week.to_csv(path_week, index=False)

        print(f"✅ {symbol} 完成 (YF-Adj) | 速度:快")

    except Exception as e:
        print(f"❌ {symbol} 錯誤: {e}")


# ==========================================
# 主程式入口
# ==========================================
def main():
    if not os.path.exists(DIR_WEEKLY): os.makedirs(DIR_WEEKLY)
    if not os.path.exists(DIR_DAILY): os.makedirs(DIR_DAILY)

    try:
        df_list = pd.read_excel(EXCEL_PATH)
        symbols = df_list.iloc[:, 0].dropna().astype(str).unique().tolist()
        print(f"📈 讀取清單成功，共 {len(symbols)} 檔標的。")
    except Exception as e:
        print(f"❌ 讀取 Excel 失敗: {e}")
        return

    # 多執行緒全速運轉
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as exe:
        list(exe.map(task_process_stock, symbols))

    print(f"\n✨ 全部下載完成！(Yahoo Finance 還原版)")


if __name__ == "__main__":
    main()