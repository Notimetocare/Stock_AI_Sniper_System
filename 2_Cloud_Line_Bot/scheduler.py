# -*- coding: utf-8 -*-
# scheduler.py - 根目錄專用版
import schedule
import time
import threading
import subprocess
import os
import sys
import pandas as pd
from datetime import datetime
from config import Config
from database import get_db_connection

# ★★★ 修正重點：移除 services. 前綴 ★★★
# 原本: from services.line_service import ...
# 現在: 直接從同層目錄引用
from line_service import broadcast_daily_report
from stock_service import find_latest_dynamic_csv


def sync_stop_loss():
    """同步 Twin 停損價到資料庫"""
    csv_path = find_latest_dynamic_csv()
    if not csv_path: return
    try:
        df = pd.read_csv(csv_path)
        # 清理欄位空白
        df.columns = [c.strip() for c in df.columns]

        conn = get_db_connection()
        for _, row in df.iterrows():
            sym = str(row['Symbol']).strip()
            sl = row['Stop_Loss']
            # 更新資料庫中的停損價
            conn.execute("UPDATE inventory SET stop_loss = ? WHERE symbol = ? AND status = 'ACTIVE'", (sl, sym))
        conn.commit()
        conn.close()
        print(f"[{datetime.now()}] ✅ 已同步資料庫停損價")
    except Exception as e:
        print(f"❌ 同步停損失敗: {e}")


def run_daily_monitor():
    print(f"[{datetime.now()}] ⏰ 啟動每日掃描...")
    script = os.path.join(Config.BASE_ROOT, Config.DAILY_SCRIPT)

    if os.path.exists(script):
        try:
            # 治本關鍵：射後不理，排程器秒解脫，不卡線程
            subprocess.Popen([sys.executable, script], cwd=Config.BASE_ROOT)
            print("✅ 已將策略任務投入背景...")

        except Exception as e:
            print(f"❌ 啟動策略失敗: {e}")
    else:
        print(f"⚠️ 找不到策略腳本: {script}")


def simulate_stop_loss_check(sym, price):
    """(測試用) 模擬停損觸發"""
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM inventory WHERE symbol=? AND status='ACTIVE'", (sym,)).fetchall()
    conn.close()

    if not rows: return f"⚠️ 沒人持有 {sym}"

    msg = f"🧪 模擬 {sym} @ {price}:\n"
    for r in rows:
        sl = r['stop_loss']
        user = r['user_id'][:5]
        if sl and price <= sl:
            msg += f"- {user}... 觸發停損 (SL:{sl}) 🔴\n"
        else:
            msg += f"- {user}... 安全 (SL:{sl}) 🟢\n"
    return msg


def start_scheduler():
    # 設定排程時間
    schedule.every().day.at("08:30").do(run_daily_monitor)
    schedule.every().day.at("20:30").do(run_daily_monitor)

    # 啟動迴圈
    def loop():
        while True:
            schedule.run_pending()
            time.sleep(1)

    threading.Thread(target=loop, daemon=True).start()
    print("✅ 排程系統已啟動 (08:30, 20:30)")