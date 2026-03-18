# -*- coding: utf-8 -*-
# config.py - 完整設定檔 (已修正對接新版 AllInOne)
import os
import sys

class Config:
    # ==========================================
    # 1. LINE BOT 金鑰 & LIFF
    # ==========================================
    LINE_ACCESS_TOKEN = '********************************************************************************'
    LINE_SECRET = '*********************************'
    LIFF_ID = '*********************'
    ADMIN_USER_ID = '**************************'

    # ==========================================
    # 2. 伺服器與 NGROK 設定
    # ==========================================
    # ★ 您的固定網址 (請確認 ngrok 視窗是 .app 還是 .dev)
    BASE_URL = "https://**********************.dev"
    PORT = 5006
    TEST_MODE = False

    # ==========================================
    # 3. 路徑設定 (自動判斷 雲端/電腦)
    # ==========================================
    # ★★★ 修正 1：腳本名稱改為新版 (沒有 _old) ★★★
    DAILY_SCRIPT = "Strategy_A_Daily_Ops_Twin_v3_5_AllInOne.py"

    if sys.platform.startswith('linux'):
        # GCP 雲端環境路徑
        BASE_ROOT = "/home/??????/stock_bot1"
    else:
        # Windows 本機測試路徑 (自動抓當前資料夾)
        BASE_ROOT = os.path.dirname(os.path.abspath(__file__))

    # --- 以下路徑基於 BASE_ROOT 自動延伸 ---

    # 資料庫
    DB_FILE = os.path.join(BASE_ROOT, "stock_bot.db")

    # 備份檔路徑
    BACKUP_FILE = os.path.join(BASE_ROOT, "backup", "Stock_Bot_Backup.xlsx")

    # Twin 輸出資料夾 (新架構)
    OUTPUT_DASHBOARD = os.path.join(BASE_ROOT, "output_dashboard")

    # ★★★ 修正 2：圖表資料夾名稱修正為 Signal_Charts ★★★
    # (注意：run_server1.py 會自動去 output_dashboard/<日期>/Signal_Charts 找)
    CHART_DIR = os.path.join(OUTPUT_DASHBOARD, "Signal_Charts")

    # 原始數據資料夾 (K線與結構)
    # 修正為 stock_data 以符合新版邏輯，雖然新版程式碼有自己定義，但這裡保持一致比較好
    UPLOADED_DATA = os.path.join(BASE_ROOT, "stock_data")

    # 確保備份資料夾存在
    BACKUP_DIR = os.path.join(BASE_ROOT, "backup")
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)