# -*- coding: utf-8 -*-
import os
import glob
import logging
import sqlite3
import pandas as pd
import yfinance as yf
# ★ 救命關鍵：強制 Matplotlib 使用無頭模式 (Agg)，禁止開啟 GUI 視窗，徹底解決多執行緒閃退問題
import matplotlib
matplotlib.use('Agg')
import mplfinance as mpf
import io
import urllib.request
import json
from datetime import datetime, timedelta
from cachetools import TTLCache
from config import Config

# 設定 Log
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ==========================================
# 🔍 核心搜尋邏輯
# ==========================================
def find_latest_dynamic_csv():
    try:
        base = Config.OUTPUT_DASHBOARD
        search_pattern = os.path.join(base, "**", "Today_Global_Buy_Signals.csv")
        files = glob.glob(search_pattern, recursive=True)

        if not files:
            search_pattern_backup = os.path.join(base, "**", "Today_Global_Buy_Signals_ops.csv")
            files = glob.glob(search_pattern_backup, recursive=True)

        if not files:
            return None

        latest_file = max(files, key=os.path.getmtime)
        return latest_file
    except Exception as e:
        logger.error(f"尋找 CSV 失敗: {e}")
        return None


def get_stock_name_zh(symbol):
    """★ 終極進化：利用 Yahoo 聯想詞 API 達成台美股通吃，無延遲不卡死"""
    try:
        sym_str = str(symbol).strip().upper()
        url = f"https://tw.stock.yahoo.com/_td-stock/api/resource/AutocompleteService;query={sym_str}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode('utf-8'))
            results = data.get('ResultSet', {}).get('Result', [])
            for res in results:
                res_sym = res.get('symbol', '').upper()
                # 精準比對代號 (例如 AAPL 或 2330)
                if res_sym == sym_str or res_sym == f"{sym_str}.TW" or res_sym == f"{sym_str}.TWO":
                    return res.get('name', sym_str)
        return sym_str
    except Exception:
        return str(symbol)


class StockService:
    # ... (保留其他不變的程式碼) ...

    def get_chart_path(self, symbol):
        """★ 修正：優先抓取最新策略產出的 _BUY.png，避免抓到歷史幽靈圖"""
        try:
            base = Config.OUTPUT_DASHBOARD
            # 1. 最優先：找新版策略畫出來的 _BUY.png
            files = glob.glob(os.path.join(base, "**", f"{symbol}_BUY.png"), recursive=True)

            # 2. 如果沒有，才找完全同名的 (可能是 mpf 生成的或舊版的)
            if not files:
                files = glob.glob(os.path.join(base, "**", f"{symbol}.png"), recursive=True)

            if files:
                latest_img = max(files, key=os.path.getmtime)
                return latest_img
            return None
        except Exception as e:
            logger.error(f"找圖失敗: {e}")
            return None

# ==========================================
# 📦 StockService 類別 (資料庫與圖表)
# ==========================================
class StockService:
    def __init__(self, db_file):
        self.db_file = db_file
        self.price_cache = TTLCache(maxsize=1000, ttl=60)
        self.name_cache = {}
        self.init_db()

    def init_db(self):
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, display_name TEXT, note TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT, symbol TEXT, stock_name TEXT,
                cost_price REAL, quantity INTEGER, stop_loss REAL,
                strategy TEXT, note TEXT, status TEXT DEFAULT 'ACTIVE',
                date_added TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB Init Error: {e}")

    def add_stock(self, user_id, symbol, input_price=None, input_qty=None, input_sl=None):
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            stock_name = self.get_stock_name(symbol)
            c.execute(
                "INSERT INTO inventory (user_id, symbol, stock_name, cost_price, quantity, stop_loss) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, symbol, stock_name, input_price, input_qty, input_sl))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Add Stock Error: {e}")
            return False

    def generate_stock_chart(self, symbol):
        try:
            ticker = f"{symbol}.TW" if symbol.isdigit() else symbol
            df = yf.download(ticker, period="3mo", progress=False)
            if df.empty: return None

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df.rename(columns={'Date': 'Datetime'})
            df.columns = [c.capitalize() for c in df.columns]
            required = ['Open', 'High', 'Low', 'Close', 'Volume']
            if not all(col in df.columns for col in required): return None

            # ★ 修正型態報錯：強制將所有需要的欄位轉為數字 (遇到非數字直接變 NaN)，再把 NaN 濾掉
            for col in required:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df = df.dropna(subset=required)

            # 如果濾完沒資料了就放棄
            if df.empty: return None

            mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
            s = mpf.make_mpf_style(marketcolors=mc)
            buf = io.BytesIO()
            mpf.plot(df, type='candle', style=s, title=f"{symbol}", volume=True, savefig=buf)
            buf.seek(0)
            return buf
        except Exception as e:
            logger.error(f"Generate Chart Error: {e}")
            return None

    @classmethod
    def get_chart_path(cls, symbol):
        import os
        import glob

        # 1. 動態搜尋：尋找所有日期資料夾下的目標圖檔
        # 這會自動配對類似: output_dashboard/20260316/Signal_Charts/3703_AI_BUY.png
        search_pattern = os.path.join(Config.OUTPUT_DASHBOARD, "*", "Signal_Charts", f"{symbol}_AI_BUY.png")
        matched_files = glob.glob(search_pattern)

        if matched_files:
            # 如果好幾天都有這檔股票的圖，我們只抓最新的一天 (排序後取最後一個)
            return sorted(matched_files)[-1]

        # 2. 備案：舊路徑防呆機制
        # 使用 getattr 避免 AttributeError (500錯誤)
        chart_dir = getattr(cls, 'CHART_DIR', os.path.join(Config.OUTPUT_DASHBOARD, "Signal_Charts"))
        legacy_path = os.path.join(chart_dir, f"{symbol}.png")

        if os.path.exists(legacy_path):
            return legacy_path

        return None

    def get_signal_info(self, symbol):
        try:
            csv_path = find_latest_dynamic_csv()
            if not csv_path: return {}
            df = pd.read_csv(csv_path)
            df['Symbol_Str'] = df['Symbol'].astype(str).str.strip().str.upper()
            target = str(symbol).strip().upper()
            row = df[df['Symbol_Str'] == target]
            if not row.empty:
                return row.iloc[0].to_dict()
            return {}
        except Exception as e:
            logger.error(f"get_signal_info error: {e}")
            return {}

    def get_stock_name(self, symbol):
        return get_stock_name_zh(symbol)

    def get_user_inventory(self, user_id):
        try:
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            # 👇 改成這樣，把 ALERTED 也包進來！
            c.execute(
                "SELECT * FROM inventory WHERE user_id=? AND status IN ('ACTIVE', 'ALERTED') ORDER BY created_at DESC",
                (user_id,))
            rows = [dict(r) for r in c.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"get_user_inventory error: {e}")
            return []

    def get_deleted_inventory(self, user_id):
        try:
            conn = sqlite3.connect(self.db_file)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM inventory WHERE user_id=? AND status='DELETED' ORDER BY created_at DESC",
                      (user_id,))
            rows = [dict(r) for r in c.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"get_deleted_inventory error: {e}")
            return []

    def get_realtime_prices(self, symbols):
        """★ 修正：退回前端看得懂的單純數字格式，解決 [object Object] 當機"""
        if not symbols: return {}
        # 預設回傳 0.0，避免前端出錯
        res = {sym: 0.0 for sym in symbols}

        try:
            ticker_map = {}
            for sym in symbols:
                if str(sym).isdigit():
                    ticker_map[f"{sym}.TW"] = sym
                    ticker_map[f"{sym}.TWO"] = sym  # 上市櫃通吃
                else:
                    ticker_map[sym] = sym

            tickers = list(ticker_map.keys())
            if tickers:
                df = yf.download(tickers, period="1mo", progress=False)
                if not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        if 'Close' in df.columns.levels[0]:
                            close_df = df['Close']
                            for t in tickers:
                                if t in close_df.columns:
                                    s = close_df[t].dropna()
                                    if not s.empty:
                                        res[ticker_map[t]] = round(float(s.iloc[-1]), 2)
                    else:
                        s = df['Close'].dropna()
                        if not s.empty:
                            res[ticker_map[tickers[0]]] = round(float(s.iloc[-1]), 2)
        except Exception as e:
            logger.error(f"get_realtime_prices error: {e}")

        return res