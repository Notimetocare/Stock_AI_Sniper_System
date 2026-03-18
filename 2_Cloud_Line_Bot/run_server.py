# -*- coding: utf-8 -*-
import sys
import os
import shutil
import asyncio
import logging
import sqlite3
import json
import traceback
import pandas as pd
import glob
import subprocess
from scheduler import start_scheduler
import time
from datetime import datetime
from quart import Quart, request, abort, jsonify, render_template, send_file
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage, PushMessageRequest, FlexMessage, FlexContainer,
    BroadcastRequest
)
# ★ 補上 PostbackEvent
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent
from config import Config

# 強制路徑導航
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path: sys.path.append(current_dir)
from stock_service import StockService, find_latest_dynamic_csv

# 設定 Log
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==========================================
# 🔐 安全設定
# ==========================================
ADMIN_USER_ID = Config.ADMIN_USER_ID

app = Quart(__name__)
configuration = Configuration(access_token=Config.LINE_ACCESS_TOKEN)
handler = WebhookHandler(Config.LINE_SECRET)
stock_service = StockService(db_file=Config.DB_FILE)

CHART_DIR = os.path.join(Config.OUTPUT_DASHBOARD, "Signal_Charts")
if not os.path.exists(CHART_DIR): os.makedirs(CHART_DIR, exist_ok=True)


# ==========================================
# 💾 備份與資料庫工具
# ==========================================
def export_backup():
    try:
        backup_name = f"{Config.DB_FILE}.bak"
        shutil.copy(Config.DB_FILE, backup_name)
    except Exception as e:
        logger.error(f"備份失敗: {e}")


# ==========================================
# 🚨 核心新功能：自動盯盤與停損通知
# ==========================================
async def monitor_inventory_loop():
    """背景常駐程式：每 5 分鐘掃描一次庫存，跌破停損即發送推播"""
    logger.info("啟動自動盯盤監控服務...")
    while True:
        try:
            with sqlite3.connect(Config.DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute(
                    "SELECT id, user_id, symbol, stop_loss, stock_name, cost_price FROM inventory WHERE status='ACTIVE' AND stop_loss > 0")
                items = c.fetchall()

            if items:
                symbols = list(set([item['symbol'] for item in items]))
                prices = stock_service.get_realtime_prices(symbols)

                for item in items:
                    sym = item['symbol']

                    # ★ 終極防呆：處理使用者留白或亂打字導致的「爆紅」當機
                    try:
                        sl = float(item['stop_loss']) if item['stop_loss'] else 0.0
                    except:
                        sl = 0.0

                    # 如果停損是 0 (或留白)，直接跳過不處理
                    if sl <= 0:
                        continue

                    uid = item['user_id']
                    item_id = item['id']

                    current_price = float(prices.get(sym, 0.0))

                    if current_price > 0 and current_price <= sl:
                        # 1. 抓取成本與名稱來計算損益 (加入防呆)
                        try:
                            cost = float(item['cost_price']) if item['cost_price'] else 0.0
                        except:
                            cost = 0.0

                        stock_name = item['stock_name'] if item['stock_name'] else sym
                        loss_pct = ((current_price - cost) / cost) * 100 if cost > 0 else 0.0

                        # 2. 呼叫我們在 line_service 寫好的紅色警戒圖卡
                        from line_service import push_stop_loss_alert
                        push_stop_loss_alert(uid, sym, stock_name, current_price, sl, loss_pct)

                        # 3. 更新資料庫狀態為已警告 (防洗版)
                        with sqlite3.connect(Config.DB_FILE) as update_conn:
                            update_conn.execute("UPDATE inventory SET status='ALERTED' WHERE id=?", (item_id,))
                            update_conn.commit()
                        logger.info(f"已發送停損圖卡給 {uid} (股票: {sym})")

        except Exception as e:
            logger.error(f"監控迴圈發生錯誤: {traceback.format_exc()}")

        await asyncio.sleep(300)


@app.before_serving
async def startup():
    app.add_background_task(monitor_inventory_loop)
    start_scheduler()


# ==========================================
# ✉️ 訊息推播工具
# ==========================================
def send_push_sync(user_id, messages):
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            msg_obj = [TextMessage(text=messages)] if isinstance(messages, str) else (
                messages if isinstance(messages, list) else [messages])

            if user_id:
                line_bot_api.push_message(PushMessageRequest(to=user_id, messages=msg_obj))
            else:
                line_bot_api.broadcast(BroadcastRequest(messages=msg_obj))
    except Exception as e:
        logger.error(f"Push Error: {e}")


async def send_push(user_id, messages):
    await asyncio.get_running_loop().run_in_executor(None, send_push_sync, user_id, messages)


# ==========================================
# 🎨 中文圖卡產生器
# ==========================================
def create_flex_carousel(df):
    timestamp = int(time.time())
    bubbles = []
    for index, row in df.head(12).iterrows():
        symbol = str(row.get('Symbol', 'N/A')).strip().upper()
        stock_name = stock_service.get_stock_name(symbol)
        price = row.get('Signal_Price') or row.get('Close') or 0
        sl = row.get('Stop_Loss') or row.get('Ref_Low') or 0
        ai_win_rate = row.get('AI_WinRate_Pct', row.get('Score', 0))

        chart_url = f"{Config.BASE_URL}/api/stock_chart/{symbol}?v={timestamp}"

        bubble = {
            "type": "bubble",
            "hero": {
                "type": "image",
                "url": chart_url,
                "size": "full",
                "aspectRatio": "20:13",
                "aspectMode": "cover",
                "action": {"type": "uri", "uri": chart_url}
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": f"{symbol} {stock_name}" if stock_name.upper() != symbol.upper() else symbol,
                        "weight": "bold", "size": "xl", "color": "#1DB446"
                    },
                    {
                        "type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm",
                        "contents": [
                            {
                                "type": "box", "layout": "baseline", "spacing": "sm",
                                "contents": [
                                    {"type": "text", "text": "現價", "color": "#aaaaaa", "size": "sm", "flex": 2},
                                    {"type": "text", "text": f"{float(price):.2f}", "wrap": True, "color": "#666666",
                                     "size": "sm", "flex": 4}
                                ]
                            },
                            {
                                "type": "box", "layout": "baseline", "spacing": "sm",
                                "contents": [
                                    {"type": "text", "text": "防守", "color": "#aaaaaa", "size": "sm", "flex": 2},
                                    {"type": "text", "text": f"{float(sl):.2f}", "wrap": True, "color": "#ff3333",
                                     "size": "sm", "flex": 4}
                                ]
                            },
                            {
                                "type": "box", "layout": "baseline", "spacing": "sm",
                                "contents": [
                                    {"type": "text", "text": "AI勝率", "color": "#aaaaaa", "size": "sm", "flex": 2},
                                    {"type": "text", "text": f"{float(ai_win_rate):.2f}%", "wrap": True,
                                     "color": "#d32f2f",
                                     "weight": "bold", "size": "sm", "flex": 4}
                                ]
                            }
                        ]
                    }
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical", "spacing": "sm",
                "contents": [
                    {
                        "type": "button", "style": "primary", "height": "sm",
                        "action": {"type": "message", "label": "加入監控", "text": f"加入 {symbol}"},
                        "color": "#00ba9d"
                    }
                ],
                "flex": 0
            }
        }
        bubbles.append(bubble)

    if not bubbles: return None
    return FlexMessage(alt_text="今日買訊報表",
                       contents=FlexContainer.from_json(json.dumps({"type": "carousel", "contents": bubbles})))


# ==========================================
# 📢 報表推播邏輯
# ==========================================
async def broadcast_daily_report(target_id=None):
    logger.info("Starting Daily Report Broadcast...")
    try:
        latest_file = find_latest_dynamic_csv()

        if not latest_file:
            today_str = datetime.now().strftime('%m/%d')
            await send_push(target_id, f"🍵 今日 ({today_str}) 無符合破底翻策略的標的。")
            return

        df = pd.read_csv(latest_file)
        if df.empty: return

        flex_msg = create_flex_carousel(df)
        if flex_msg:
            await send_push(target_id, flex_msg)
            liff_url = f"https://liff.line.me/{Config.LIFF_ID}"
            await send_push(target_id, f"📊 點此查看個人完整戰情室：\n{liff_url}")
    except Exception as e:
        logger.error(f"Broadcast failed: {e}")


# ==========================================
# ⚙️ 核心：執行策略程式
# ==========================================
def run_script_sync(script_path, cwd):
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run([sys.executable, script_path], cwd=cwd, env=env, capture_output=True, text=True,
                              encoding='utf-8', errors='ignore')
    except Exception as e:
        raise e


async def run_strategy_script(user_id):
    await send_push(user_id, "⚙️ 系統通知：已將洗價任務送入背景獨立運算 (預計 3-5 分鐘)，完成後將自動為您推播。")
    script_path = os.path.join(current_dir, Config.DAILY_SCRIPT)
    if not os.path.exists(script_path): return

    try:
        # 治本關鍵：改用 Popen 射後不理，釋放伺服器執行緒
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        subprocess.Popen([sys.executable, script_path], cwd=current_dir, env=env)
    except Exception as e:
        logger.error(f"Subprocess failed: {traceback.format_exc()}")


# ==========================================
# LINE Webhook 處理
# ==========================================
@app.route("/callback", methods=['POST'])
async def callback():
    signature = request.headers.get('X-Line-Signature')
    body = await request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@app.route('/api/internal/calc_done', methods=['POST'])
async def api_calc_done():
    """治本機制：接收策略腳本算完的通知，接手後續動作"""
    logger.info("🔔 收到策略執行完畢訊號！準備同步停損與推播...")

    # 1. 同步停損價
    try:
        from scheduler import sync_stop_loss
        sync_stop_loss()
    except Exception as e:
        logger.error(f"同步停損失敗: {e}")

    # 2. 觸發報表推播
    asyncio.create_task(broadcast_daily_report(None))  # 廣播給所有人
    return jsonify({"status": "ok"})

# ★ 處理一般文字訊息
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id
    reply_text = None

    if user_id == ADMIN_USER_ID:
        if text == "強制執行":
            asyncio.create_task(run_strategy_script(user_id))
        elif text == "重新推播":
            asyncio.create_task(broadcast_daily_report(user_id))
        elif text == "推播測試":
            test_mode = getattr(Config, 'TEST_MODE', False)
            asyncio.create_task(send_push(user_id, f"✅ 系統通知：推播與監控功能正常運行中。\n當前測試模式={test_mode}"))
        elif text == "開啟測試模式":
            Config.TEST_MODE = True
            reply_text = "系統通知：測試模式已開啟"
        elif text == "關閉測試模式":
            Config.TEST_MODE = False
            reply_text = "系統通知：測試模式已關閉"
        elif text.startswith("授權 "):
            target = text.replace("授權", "").strip()
            try:
                with sqlite3.connect(Config.DB_FILE) as conn:
                    conn.cursor().execute("INSERT OR REPLACE INTO users (user_id, display_name) VALUES (?, 'User')",
                                          (target,))
                    conn.commit()
                export_backup()
                reply_text = f"系統通知：已授權 ID {target}"
            except:
                reply_text = "系統通知：資料庫錯誤"

    if text in ["庫存", "網頁", "戰情室"]:
        reply_text = f"📊 點此管理您的監控部位：\nhttps://liff.line.me/{Config.LIFF_ID}"

    elif text.startswith("加入"):
        try:
            raw_symbol = text.replace("加入", "").replace("請幫我加入", "").strip().upper()
            if raw_symbol:
                csv_info = stock_service.get_signal_info(raw_symbol)
                final_sl = round(float(csv_info.get('Stop_Loss') or csv_info.get('Ref_Low') or 0),
                                 2) if csv_info else 0.0
                final_strat = csv_info.get('Strategy_Name', 'Sniper') if csv_info else 'Manual'
                final_price = round(float(csv_info.get('Close') or csv_info.get('Signal_Price') or 0),
                                    2) if csv_info else None

                stock_service.add_stock(user_id, raw_symbol, input_price=final_price, input_sl=final_sl)

                if final_strat != 'Manual':
                    with sqlite3.connect(Config.DB_FILE) as conn:
                        conn.cursor().execute(
                            "UPDATE inventory SET strategy=? WHERE user_id=? AND symbol=? AND status='ACTIVE'",
                            (final_strat, user_id, raw_symbol))
                        conn.commit()
                export_backup()
                reply_text = None
        except Exception as e:
            reply_text = None

    elif text.startswith("刪除"):
        sym = text.replace("刪除", "").strip().upper()
        if sym:
            with sqlite3.connect(Config.DB_FILE) as conn:
                conn.cursor().execute("UPDATE inventory SET status='DELETED' WHERE user_id=? AND symbol=?",
                                      (user_id, sym))
                conn.commit()
            export_backup()
            reply_text = None

    # ★ 處理純文字的「我已賣出」
    elif text.startswith("我已賣出"):
        sym = text.replace("我已賣出", "").strip().upper()
        if sym:
            with sqlite3.connect(Config.DB_FILE) as conn:
                conn.cursor().execute("UPDATE inventory SET status='DELETED' WHERE user_id=? AND symbol=?",
                                      (user_id, sym))
                conn.commit()
            export_backup()
            reply_text = f"✅ 紀律執行完畢！\n{sym} 已從現有庫存移除，並歸檔至戰情室歷史紀錄。"

    elif text == "清單":
        items = stock_service.get_user_inventory(user_id)
        reply_text = "\n".join([
            f"🎯 {i['symbol']} {i.get('stock_name', '')} \n   現價/成本: ${i.get('current_price', 'N/A')} / ${i['cost_price']}\n   防守: ${i.get('stop_loss', '0')}"
            for i in items]) if items else "目前空手，無監控部位。"

    elif text.upper() == "ID":
        reply_text = f"您的 LINE ID:\n{user_id}"

    if reply_text:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)]))


# ★ 處理隱藏按鈕訊號 (PostbackEvent)
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    user_id = event.source.user_id
    reply_token = event.reply_token

    try:
        params = dict(item.split('=') for item in data.split('&'))
        action = params.get('action')
        sym = params.get('symbol')

        if action == 'delete' and sym:
            with sqlite3.connect(Config.DB_FILE) as conn:
                conn.cursor().execute("UPDATE inventory SET status='DELETED' WHERE user_id=? AND symbol=?",
                                      (user_id, sym))
                conn.commit()
            export_backup()

            # 推播成功訊息
            reply_text = f"✅ 紀律執行完畢！\n{sym} 已從現有庫存移除，並歸檔至戰情室歷史紀錄。"
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=reply_text)])
                )
    except Exception as e:
        logger.error(f"按鈕處理失敗: {e}")


# ==========================================
# API 路由區
# ==========================================
@app.route('/')
async def index(): return "Stock Monitor Server is running smoothly!"


@app.route('/inventory')
async def inventory_page(): return await render_template('inventory.html', liff_id=Config.LIFF_ID)


@app.route('/api/get_inventory', methods=['POST'])
async def api_get_inventory():
    d = await request.get_json()
    return jsonify({"active": stock_service.get_user_inventory(d.get('userId')),
                    "history": stock_service.get_deleted_inventory(d.get('userId'))})


@app.route('/api/get_market_prices', methods=['POST'])
async def api_get_market_prices():
    d = await request.get_json()
    return jsonify(stock_service.get_realtime_prices(d.get('symbols', [])))


@app.route('/api/stock_info', methods=['POST'])
async def api_stock_info():
    d = await request.get_json()
    s = d.get('symbol')
    i = stock_service.get_signal_info(s) or {}
    return jsonify({"found": True, "symbol": s, "stock_name": stock_service.get_stock_name(s),
                    "price": i.get('Signal_Price') or i.get('Close') or i.get('Current') or 0,
                    "stop_loss": i.get('Stop_Loss') or i.get('Ref_Low') or 0})


@app.route('/api/stock_chart/<symbol>')
async def api_stock_chart(symbol):
    p = stock_service.get_chart_path(symbol)
    if p: return await send_file(p, mimetype='image/png')

    # ★ 效能升級：把耗時的畫圖工作丟給背景執行緒，避免伺服器塞車引發 502 Bad Gateway
    loop = asyncio.get_running_loop()
    b = await loop.run_in_executor(None, stock_service.generate_stock_chart, symbol)

    if b: return await send_file(b, mimetype='image/png')
    return "No Chart", 404


# ★ 舊版相容：補上舊版 v19_chart 的路由，避免 LINE 讀取舊對話時發生 404 報錯
@app.route('/api/v19_chart/<symbol>')
async def api_v19_chart_fallback(symbol):
    return await api_stock_chart(symbol)


@app.route('/api/update_inventory', methods=['POST'])
async def api_update_inventory():
    try:
        if request.content_type and 'multipart/form-data' in request.content_type:
            f = await request.form
            fs = await request.files
            a, u, s = f.get('action'), f.get('userId'), f.get('symbol')
            p, q, sl = f.get('price'), f.get('qty'), f.get('stop_loss')
            if fs.get('image'): await fs.get('image').save(os.path.join(CHART_DIR, f"{s}.png"))
        else:
            d = await request.get_json()
            a, u, s, p, q, sl = d.get('action'), d.get('userId'), d.get('symbol'), d.get('price'), d.get('qty'), d.get(
                'stop_loss')
            item_id = d.get('id')

        with sqlite3.connect(Config.DB_FILE) as conn:
            c = conn.cursor()
            if a == 'add':
                stock_service.add_stock(u, s, input_price=p, input_qty=q, input_sl=sl)
            elif a == 'delete':
                # ★ 修正：從認 symbol 改為認 item_id，精準刪除單一卡片
                c.execute("UPDATE inventory SET status='DELETED' WHERE user_id=? AND id=?", (u, item_id))
            elif a == 'update':
                c.execute(
                    "UPDATE inventory SET cost_price=?, quantity=?, stop_loss=?, status='ACTIVE' WHERE user_id=? AND id=?",
                    (p, q, sl, u, item_id))
            elif a == 'restore':
                # ★ 修正：從認 symbol 改為認 item_id，精準復原單一紀錄
                c.execute("UPDATE inventory SET status='ACTIVE' WHERE user_id=? AND id=?", (u, item_id))

        export_backup()
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"API Update Error: {e}")
        return jsonify({'status': 'error', 'msg': str(e)}), 500


if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    app.run(host='0.0.0.0', port=Config.PORT)