# -*- coding: utf-8 -*-
"""
51_Orchestrator_Unified_Switchable_Multicore.py
-------------------------------------------------
[戰略總指揮官 - 旗艦修復版 (Fix Body_Bottom Error)]
戰場: D:\Stock_HP_new\AI_TRAIN22
功能:
  1. [Fix]: 修復 worker_structure 未計算 Body_Bottom 導致的 KeyError。
  2. [Switchable]: 可自由開關每個步驟。
  3. [Multicore]: 真多工平行運算。
-------------------------------------------------
"""

import os
import sys
import time
import glob
import pandas as pd
import importlib.util
import warnings
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import subprocess

# 強制 Matplotlib 不顯示視窗
import matplotlib

matplotlib.use('Agg')

warnings.filterwarnings("ignore")

# ==============================================================================
# 🎛️ 中央控制面板 (SWITCH BOARD)
# ==============================================================================
# True = 執行該步驟 | False = 跳過 (沿用舊檔)

ENABLE_STEP_1_DOWNLOAD = False  # 1. 下載數據
ENABLE_STEP_2_SUPPORT = True  # 2. 計算支撐
ENABLE_STEP_3_PRESSURE = True  # 3. 計算壓力 (若已跑完可設 False)
ENABLE_STEP_4_STRUCTURE = True  # 4. 計算結構 (★ 必須重跑，已修復 KeyError)
ENABLE_STEP_5_STRATEGY = True  # 5. 產出買訊

# ==========================================
# ⚙️ 檔案配置
# ==========================================
BASE_ROOT = r"D:\Stock_HP_new\AI_TRAIN23"
EXCEL_PATH = os.path.join(BASE_ROOT, "STOCK.xlsx")

SCRIPTS = {
    "S1": "2_fetch_data_unified_YF_Adj.py",
    "S2": "auto_label_support_lineview_v3_2_EngulfingRescue.py",
    "S3": "auto_label_pressure_band_v3_6_BreakdownMark_MODERATE_ONLY.py",
    "S4": "structure_event_v569_Switchable.py",
    "STRATEGY": "Strategy_A_Commander_v146_Broken_Latch.py"
}

# 效能設定
CPU_CORES = max(1, os.cpu_count() - 1)
DOWNLOAD_THREADS = 8

# ==========================================
# 📂 路徑定義
# ==========================================
DIR_PROJECT = os.path.join(BASE_ROOT, "stock_process_US_SCAN_WATCHLIST")
DIR_RAW_WEEK = os.path.join(DIR_PROJECT, "structure")
DIR_SUPPORT = os.path.join(DIR_PROJECT, "Support_LineView_v3_2_EngulfingRescue")
DIR_PRESSURE_ROOT = os.path.join(DIR_PROJECT, "PRESSURE_BAND_V3_6_BreakdownMark")
DIR_PRESSURE_MOD = os.path.join(DIR_PRESSURE_ROOT, "MODERATE")
DIR_STRUCTURE = os.path.join(DIR_PRESSURE_MOD, "STRUCTURE_EVENT_v569_Switchable")
DIR_DAY_DATA = os.path.join(DIR_PRESSURE_MOD, "DAY_DATA")

for d in [DIR_RAW_WEEK, DIR_SUPPORT, DIR_PRESSURE_MOD, DIR_STRUCTURE, DIR_DAY_DATA]:
    os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(d, "_plot"), exist_ok=True)
    if "PRESSURE" in d or "STRUCTURE" in d:
        os.makedirs(os.path.join(d, "_reports"), exist_ok=True)


# ==========================================
# 🛠️ 動態載入模組
# ==========================================
def load_module(script_name):
    path = os.path.join(BASE_ROOT, script_name)
    if not os.path.exists(path):
        if os.path.exists(script_name):
            path = script_name
        else:
            raise FileNotFoundError(f"❌ 找不到腳本: {path}")

    module_name = script_name.replace(".py", "")
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    print("📥 正在載入運算模組...")

try:
    if ENABLE_STEP_1_DOWNLOAD: MOD_S1 = load_module(SCRIPTS["S1"])
    if ENABLE_STEP_2_SUPPORT:  MOD_S2 = load_module(SCRIPTS["S2"])
    if ENABLE_STEP_3_PRESSURE: MOD_S3 = load_module(SCRIPTS["S3"])
    if ENABLE_STEP_4_STRUCTURE: MOD_S4 = load_module(SCRIPTS["S4"])
    if __name__ == "__main__": print("✅ 模組載入完成。")
except Exception as e:
    print(f"❌ 模組載入失敗: {e}")
    sys.exit(1)


# ==========================================
# 🏗️ Workers (核心任務)
# ==========================================

def worker_download_unified(symbol):
    try:
        MOD_S1.DIR_WEEKLY = DIR_RAW_WEEK
        MOD_S1.DIR_DAILY = DIR_DAY_DATA
        MOD_S1.task_process_stock(symbol)
        return f"OK: {symbol}"
    except Exception:
        return None


def worker_support(csv_path):
    try:
        matplotlib.use('Agg')
        df = pd.read_csv(csv_path)
        if "Datetime" not in df.columns: return None
        df["Datetime"] = pd.to_datetime(df["Datetime"], errors='coerce')

        d1 = MOD_S2.detect_support(df)
        d2 = MOD_S2.build_local_bands(d1)

        base = os.path.basename(csv_path)
        sym = base.replace("_1wk_with_structure.csv", "")
        out_csv = os.path.join(DIR_SUPPORT, f"{sym}_1wk_with_AIsupport_localband_v3_2.csv")
        out_png = os.path.join(DIR_SUPPORT, "_plot", f"{sym}_support_v3_2.png")

        d2.to_csv(out_csv, index=False, encoding='utf-8-sig')
        if hasattr(MOD_S2, 'plot_support'): MOD_S2.plot_support(d2, sym, out_png)
        return out_csv
    except Exception:
        return None


def worker_pressure(csv_path):
    try:
        matplotlib.use('Agg')
        src = pd.read_csv(csv_path)
        sym = os.path.basename(csv_path).split("_1wk")[0]

        mode = "MODERATE"
        MOD_S3.OUT_ROOT = DIR_PRESSURE_ROOT

        d = MOD_S3.detect_pressure_v3_6(src, mode=mode, price_tol=MOD_S3.PRICE_TOL)
        d = MOD_S3.merge_pressure_bands(d, max_gap=MOD_S3.MAX_GAP, level_tol=MOD_S3.LEVEL_TOL)

        extra = ["Pattern", "Pattern_High", "Pattern_Low"]
        extra = [c for c in extra if c in src.columns and c not in d.columns]
        d = pd.merge(d, src[["Datetime"] + extra], on="Datetime", how="left") if extra else d

        out_csv = os.path.join(DIR_PRESSURE_MOD, f"{sym}_1wk_with_AIpressure_band_moderate.csv")
        out_png = os.path.join(DIR_PRESSURE_MOD, "_plot", f"{sym}_pressure_band_moderate.png")

        d.to_csv(out_csv, index=False, encoding="utf-8-sig")
        MOD_S3.plot_full_display(d, sym, mode, out_png)
        return out_csv
    except Exception as e:
        print(f"⚠️ P3 Error {sym}: {e}")
        return None


def worker_structure(csv_path):
    try:
        matplotlib.use('Agg')

        # ★★★ 關鍵修正：使用 MOD_S4.read_csv_v563 來讀取 ★★★
        # 這會自動計算 Body_Bottom / Body_Top
        if hasattr(MOD_S4, 'read_csv_v569'):
            df = MOD_S4.read_csv_v569(csv_path)
        else:
            # 備用方案：如果找不到函數，手動計算
            df = pd.read_csv(csv_path)
            if "Datetime" not in df.columns: return None
            df['Datetime'] = pd.to_datetime(df['Datetime'])
            df['Body_Bottom'] = df[['Open', 'Close']].min(axis=1)
            df['Body_Top'] = df[['Open', 'Close']].max(axis=1)

        if df.empty: return None

        sym = os.path.basename(csv_path).split('_')[0]

        if hasattr(MOD_S4, 'detect_structures_v569'):
            cands = MOD_S4.detect_structures_v569(df, MOD_S4.CONFIG)
        elif hasattr(MOD_S4, 'detect_structures'):
            cands = MOD_S4.detect_structures(df, MOD_S4.CONFIG)
        else:
            return None

        if cands:
            MOD_S4.PLOT_DIR = os.path.join(DIR_STRUCTURE, "_plot")
            if hasattr(MOD_S4, 'save_results'):
                MOD_S4.save_results(df, cands, sym, DIR_STRUCTURE)
            elif hasattr(MOD_S4, 'mark_and_save'):
                MOD_S4.mark_and_save(df, cands, sym)
            return sym
        return None
    except Exception as e:
        sym_debug = os.path.basename(csv_path).split('_')[0]
        print(f"⚠️ P4 Error {sym_debug}: {e}")
        return None


# ==========================================
# 🚀 主程式
# ==========================================
def main():
    if sys.platform.startswith('win'):
        import multiprocessing
        multiprocessing.freeze_support()

    print(f"🚀 V51 總指揮官 - 旗艦修復版 (Fix Body_Bottom)")
    print(f"📂 戰場: {BASE_ROOT}")

    if not os.path.exists(EXCEL_PATH):
        print("❌ 找不到 STOCK.xlsx")
        return
    df_list = pd.read_excel(EXCEL_PATH)
    symbols = df_list.iloc[:, 0].dropna().astype(str).unique().tolist()
    print(f"📋 目標清單: {len(symbols)} 檔")

    t_total_start = time.time()

    # --- Phase 1: 下載 ---
    if ENABLE_STEP_1_DOWNLOAD:
        print("\n=== Phase 1: YF 極速下載 (Multi-Thread) ===")
        t_p1 = time.time()
        with ThreadPoolExecutor(max_workers=DOWNLOAD_THREADS) as exe:
            list(exe.map(worker_download_unified, symbols))
        print(f"⏱️ P1 完成: {time.time() - t_p1:.1f} 秒")
    else:
        print("\n⏭️ [跳過] Phase 1 下載")

    files_week = glob.glob(os.path.join(DIR_RAW_WEEK, "*_1wk_with_structure.csv"))

    # --- Phase 2: 支撐 ---
    if ENABLE_STEP_2_SUPPORT and files_week:
        print("\n=== Phase 2: 計算支撐 (Multi-Core) ===")
        t_p2 = time.time()
        with ProcessPoolExecutor(max_workers=CPU_CORES) as exe:
            results = list(exe.map(worker_support, files_week))
            files_support = [f for f in results if f]
        print(f"⏱️ P2 完成: {len(files_support)} 檔")
    elif not ENABLE_STEP_2_SUPPORT:
        print("\n⏭️ [跳過] Phase 2 支撐")
        files_support = glob.glob(os.path.join(DIR_SUPPORT, "*_with_AIsupport_localband_v3_2.csv"))
    else:
        files_support = []

    # --- Phase 3: 壓力 ---
    if ENABLE_STEP_3_PRESSURE and files_support:
        print("\n=== Phase 3: 計算壓力 (Multi-Core) ===")
        t_p3 = time.time()
        with ProcessPoolExecutor(max_workers=CPU_CORES) as exe:
            results = list(exe.map(worker_pressure, files_support))
            files_pressure = [f for f in results if f]
        print(f"⏱️ P3 完成: {len(files_pressure)} 檔")
    elif not ENABLE_STEP_3_PRESSURE:
        print("\n⏭️ [跳過] Phase 3 壓力")
        files_pressure = glob.glob(os.path.join(DIR_PRESSURE_MOD, "*_with_AIpressure_band_moderate.csv"))
    else:
        files_pressure = []

    # --- Phase 4: 結構 ---
    if ENABLE_STEP_4_STRUCTURE and files_pressure:
        print("\n=== Phase 4: 計算結構 V569 (Multi-Core) ===")
        t_p4 = time.time()
        with ProcessPoolExecutor(max_workers=CPU_CORES) as exe:
            results = list(exe.map(worker_structure, files_pressure))
            valid_symbols = [s for s in results if s]
        print(f"⏱️ P4 完成: 發現結構 {len(valid_symbols)} 檔")
    elif not ENABLE_STEP_4_STRUCTURE:
        print("\n⏭️ [跳過] Phase 4 結構")

    # --- Phase 5: 策略 ---
    if ENABLE_STEP_5_STRATEGY:
        print("\n=== Phase 5: 狙擊手出擊 (V124 Ultimate) ===")
        strategy_path = os.path.join(BASE_ROOT, SCRIPTS["STRATEGY"])
        if os.path.exists(strategy_path):
            subprocess.run([sys.executable, strategy_path], check=True)
        else:
            print(f"❌ 找不到策略腳本: {strategy_path}")
    else:
        print("\n⏭️ [跳過] Phase 5 策略")

    print(f"\n🎉 流程結束！總耗時: {(time.time() - t_total_start) / 60:.1f} 分鐘")


if __name__ == "__main__":
    main()