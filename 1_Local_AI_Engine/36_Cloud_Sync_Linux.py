"""
36_Cloud_Sync_Linux.py
[本地機器人更新 & 雲端同步工具 - AI 4.0 周線補給版 (日期區隔)]

功能：
1. 穿透搜尋 AI_TRAIN 產出的最新「Pending」與「Buy_Signals」名單。
2. 提取名單中的所有股票，精準抓取 569 結構檔 AND 1wk 周線檔。
3. 搬運到 LINE Bot 資料夾 (依日期區隔)，確保彈藥絕對 100% 更新。
4. 全面同步上傳至 Linux 遠端主機對應目錄。
"""
import os
import glob
import sys
import shutil
import pandas as pd
from datetime import datetime

try:
    import paramiko
    from scp import SCPClient
except ImportError:
    print("❌ 缺少套件！請執行：pip install paramiko scp")
    sys.exit(1)

# ==========================================
# ★★★ 雲端上傳開關 ★★★
# ==========================================
ENABLE_CLOUD_UPLOAD = True

# ==========================================
# 1. 路徑設定 (AI_TRAIN 總指揮基地)
# ==========================================
# 注意：這裡請確保路徑指向你產生名單的地方 (AI_TRAIN22 或 23)
SRC_CMD_DIR = r"D:\Stock_HP_new\AI_TRAIN23\stock_process_US_SCAN_WATCHLIST\PRESSURE_BAND_V3_6_BreakdownMark\MODERATE\Analysis_Result_Strategy_A_Sniper_RealCombat_900_Hybrid_v137\Daily_Summary_Reports"
SRC_STRUCT_DIR = r"D:\Stock_HP_new\AI_TRAIN23\stock_process_US_SCAN_WATCHLIST\PRESSURE_BAND_V3_6_BreakdownMark\MODERATE\STRUCTURE_EVENT_v569_Switchable"
SRC_WEEKLY_DIR = r"D:\Stock_HP_new\AI_TRAIN23\stock_process_US_SCAN_WATCHLIST\PRESSURE_BAND_V3_6_BreakdownMark\MODERATE" # 周線檔所在位置

# [目標] 本地 LINE 機器人的家
LOCAL_BOT_DIR = r"D:\Stock_HP_new\AI_LINE4\stcok_bot1"
BOT_CMD_DIR = os.path.join(LOCAL_BOT_DIR, "commander_input")
DATE_STR = datetime.now().strftime('%Y%m%d')
BOT_STRUCT_DIR = os.path.join(LOCAL_BOT_DIR, "structure_data", DATE_STR)
BOT_WEEKLY_DIR = os.path.join(LOCAL_BOT_DIR, "weekly_data", DATE_STR) # 👑 加上日期區隔

# [目標] Linux 雲端機器人的家
LINUX_HOST = "35.208.41.205"
LINUX_USER = "cutes5566"
LINUX_PASSWORD = "StockBot1234"
REMOTE_BOT_DIR = "/home/cutes5566/stock_bot1"
REMOTE_CMD_DIR = f"{REMOTE_BOT_DIR}/commander_input"
REMOTE_STRUCT_DIR = f"{REMOTE_BOT_DIR}/structure_data/{DATE_STR}"
REMOTE_WEEKLY_DIR = f"{REMOTE_BOT_DIR}/weekly_data/{DATE_STR}" # 👑 加上日期區隔


def get_latest_file(base_dir, filename):
    """穿透搜尋並找出最新的檔案"""
    pattern = os.path.join(base_dir, "**", filename)
    files = glob.glob(pattern, recursive=True)
    if files:
        return max(files, key=os.path.getmtime)
    return None


def sync_to_local_bot():
    print(f"\n📂 [Local Sync] 正在為 LINE 機器人裝填彈藥 (名單 + 結構檔 + 周線檔)...")
    for d in [BOT_CMD_DIR, BOT_STRUCT_DIR, BOT_WEEKLY_DIR]:
        os.makedirs(d, exist_ok=True)

    all_symbols = set()
    synced_cmd_files = []
    synced_struct_files = []
    synced_weekly_files = []

    # --- A. 無死角穿透搜尋最新的名單 ---
    src_pending = get_latest_file(SRC_CMD_DIR, "Pending_Setup_Candidates.csv")
    src_buy = get_latest_file(SRC_CMD_DIR, "Today_Global_Buy_Signals.csv")

    files_to_copy = []
    if src_pending: files_to_copy.append(src_pending)
    if src_buy: files_to_copy.append(src_buy)

    if not files_to_copy:
        print(f"   ⚠️ 在 {SRC_CMD_DIR} 內完全找不到任何名單，請確認總指揮是否已產出！")
        return [], [], []

    for f in files_to_copy:
        target_path = os.path.join(BOT_CMD_DIR, os.path.basename(f))
        shutil.copy2(f, target_path)
        synced_cmd_files.append(target_path)

        # 讀取裡面的股票代號
        try:
            df = pd.read_csv(f)
            if 'Symbol' in df.columns:
                syms = [str(s).replace('.TW', '').replace('_daily', '').strip() for s in df['Symbol']]
                all_symbols.update(syms)
        except:
            pass

    print(f"   ✅ commander_input (成功抓取並更新 {len(synced_cmd_files)} 份最新名單)")

    # --- B. 依據所有收集到的代號，抓取 569 結構檔 AND 周線檔 ---
    if not all_symbols:
        print("   ⚠️ 名單內找不到任何股票代號，略過更新。")
        return synced_cmd_files, synced_struct_files, synced_weekly_files

    for sym in all_symbols:
        # 1. 精準抓結構檔 (避免 CENT 抓到 CENTA，強制加上 _ 或 .TW_)
        struct_pattern1 = os.path.join(SRC_STRUCT_DIR, f"{sym}_structure_v*.csv")
        struct_pattern2 = os.path.join(SRC_STRUCT_DIR, f"{sym}.TW_structure_v*.csv")
        s_files = glob.glob(struct_pattern1) + glob.glob(struct_pattern2)

        if s_files:
            s_files.sort(reverse=True)  # 確保抓到最新版本
            target_struct = os.path.join(BOT_STRUCT_DIR, os.path.basename(s_files[0]))
            shutil.copy2(s_files[0], target_struct)
            synced_struct_files.append(target_struct)

        # 2. 👑 精準抓周線檔 (AI 4.0 必須)
        wk_pattern1 = os.path.join(SRC_WEEKLY_DIR, f"{sym}_1wk_*.csv")
        wk_pattern2 = os.path.join(SRC_WEEKLY_DIR, f"{sym}.TW_1wk_*.csv")
        w_files = glob.glob(wk_pattern1) + glob.glob(wk_pattern2)

        if w_files:
            w_files.sort(reverse=True)
            target_wk = os.path.join(BOT_WEEKLY_DIR, os.path.basename(w_files[0]))
            shutil.copy2(w_files[0], target_wk)
            synced_weekly_files.append(target_wk)

    print(f"   ✅ structure_data (更新了 {len(synced_struct_files)} 份 569 結構檔)")
    print(f"   ✅ weekly_data    (更新了 {len(synced_weekly_files)} 份 AI 專用周線檔)")
    print(f"   (🚀 LINE Bot 本地彈藥裝填完畢！)")

    return synced_cmd_files, synced_struct_files, synced_weekly_files


def upload_to_linux(cmd_files, struct_files, weekly_files):
    print(f"\n☁️ [Cloud Sync] 準備連線至 Linux 主機: {LINUX_HOST} ...")
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(LINUX_HOST, username=LINUX_USER, password=LINUX_PASSWORD, timeout=10)

        # 1. 確保遠端目錄存在
        ssh.exec_command(f"mkdir -p {REMOTE_CMD_DIR}")
        ssh.exec_command(f"mkdir -p {REMOTE_STRUCT_DIR}")
        ssh.exec_command(f"mkdir -p {REMOTE_WEEKLY_DIR}")

        # 2. 透過 SCP 批次上傳
        with SCPClient(ssh.get_transport()) as scp:
            if cmd_files:
                print(f"   📤 正在上傳 {len(cmd_files)} 份策略名單...")
                scp.put(cmd_files, remote_path=REMOTE_CMD_DIR)

            if struct_files:
                print(f"   📤 正在上傳 {len(struct_files)} 份結構檔...")
                scp.put(struct_files, remote_path=REMOTE_STRUCT_DIR)

            if weekly_files:
                print(f"   📤 正在上傳 {len(weekly_files)} 份 AI 周線檔...")
                scp.put(weekly_files, remote_path=REMOTE_WEEKLY_DIR)

        print(f"   ✅ 上傳成功！Linux 機器人雲端彈藥庫 (含 AI 燃料) 已 100% 同步完畢。")
        ssh.close()
    except Exception as e:
        print(f"   ❌ 上傳失敗: {e}")


def main():
    print("=" * 60)
    print("🚀 [資料發佈與同步系統 - AI 周線補給版] 啟動")
    print("=" * 60)

    cmd_files, struct_files, weekly_files = sync_to_local_bot()

    if not ENABLE_CLOUD_UPLOAD:
        print("\n🔕 [Cloud Sync] 上傳功能已關閉 (ENABLE_CLOUD_UPLOAD = False)")
        return

    if not cmd_files and not struct_files and not weekly_files:
        print("\n🔕 [Cloud Sync] 沒有新的檔案需要上傳。")
        return

    upload_to_linux(cmd_files, struct_files, weekly_files)


if __name__ == "__main__":
    main()