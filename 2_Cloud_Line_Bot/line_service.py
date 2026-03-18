# -*- coding: utf-8 -*-
import os
import pandas as pd
from datetime import datetime
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    TextSendMessage, FlexSendMessage, BubbleContainer, BoxComponent,
    TextComponent, ButtonComponent, SeparatorComponent, PostbackAction,
    PostbackEvent, ImageComponent, URIAction, CarouselContainer, MessageAction
)
from config import Config
# 正確匯入 (這些函式現在已獨立存在)
from stock_service import find_latest_dynamic_csv, get_stock_name_zh
from database import get_db_connection, export_backup

line_bot_api = LineBotApi(Config.LINE_ACCESS_TOKEN)
handler = WebhookHandler(Config.LINE_SECRET)


def push_message_to_admin(text):
    try:
        line_bot_api.push_message(Config.ADMIN_USER_ID, TextSendMessage(text=text))
    except:
        pass


def broadcast_message(text):
    if Config.TEST_MODE:
        push_message_to_admin(f"[測試] {text}")
    else:
        try:
            line_bot_api.broadcast(TextSendMessage(text=text))
        except:
            pass


@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    user_id = event.source.user_id
    reply_token = event.reply_token

    params = dict(item.split('=') for item in data.split('&'))
    action = params.get('action')
    symbol = params.get('symbol')

    if action == 'delete' and symbol:
        try:
            conn = get_db_connection()
            conn.execute("UPDATE inventory SET status='DELETED' WHERE user_id=? AND symbol=?", (user_id, symbol))
            conn.commit()
            conn.close()
            export_backup()
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"✅ 已確認賣出，{symbol} 已移除。"))
        except Exception as e:
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"❌ 操作失敗: {e}"))


def broadcast_daily_report():
    csv_path = find_latest_dynamic_csv()
    today_str = datetime.now().strftime("%m/%d")

    if not csv_path:
        broadcast_message(f"🍵 今日 ({today_str}) 無新買訊。")
        return

    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            broadcast_message(f"🍵 今日 ({today_str}) 無買訊資料。")
            return

        bubbles = []
        timestamp = int(datetime.now().timestamp())

        for _, row in df.head(12).iterrows():
            sym = str(row.get('Symbol', '')).strip().upper()

            # 抓取數值 (若無則補 0)
            price = row.get('Signal_Price') or row.get('Close') or 0
            sl = row.get('Stop_Loss') or row.get('Ref_Low') or 0
            ai_win_rate = row.get('AI_WinRate_Pct', row.get('Score', 0))

            # 取得中文名稱
            full_name = get_stock_name_zh(sym)
            display_title = f"{sym} {full_name}" if full_name.upper() != sym.upper() else sym

            # 圖表連結 (加上 timestamp 防快取，並對齊 run_server 的路徑)
            chart_url = f"{Config.BASE_URL}/api/stock_chart/{sym}?v={timestamp}"

            bubble = BubbleContainer(
                hero=ImageComponent(
                    url=chart_url, size="full", aspectRatio="20:13", aspectMode="cover",
                    action=URIAction(uri=chart_url)
                ),
                body=BoxComponent(
                    layout="vertical",
                    contents=[
                        TextComponent(text=display_title, weight="bold", size="xl", color="#1DB446"),
                        BoxComponent(
                            layout="vertical", margin="lg", spacing="sm",
                            contents=[
                                BoxComponent(layout="baseline", spacing="sm", contents=[
                                    TextComponent(text="現價", color="#aaaaaa", size="sm", flex=2),
                                    TextComponent(text=f"{float(price):.2f}", wrap=True, color="#666666", size="sm",
                                                  flex=4)
                                ]),
                                BoxComponent(layout="baseline", spacing="sm", contents=[
                                    TextComponent(text="防守", color="#aaaaaa", size="sm", flex=2),
                                    TextComponent(text=f"{float(sl):.2f}", wrap=True, color="#ff3333", size="sm",
                                                  flex=4)
                                ]),
                                BoxComponent(layout="baseline", spacing="sm", contents=[
                                    TextComponent(text="AI勝率", color="#aaaaaa", size="sm", flex=2),
                                    TextComponent(text=f"{float(ai_win_rate):.2f}%", wrap=True, color="#d32f2f",
                                                  size="sm", flex=4, weight="bold")
                                ])
                            ]
                        )
                    ]
                ),
                footer=BoxComponent(
                    layout="vertical", spacing="sm",
                    contents=[
                        ButtonComponent(
                            style="primary", height="sm", color="#00ba9d",
                            action=MessageAction(label="加入監控", text=f"加入 {sym}")
                        )
                    ]
                )
            )
            bubbles.append(bubble)

        flex_msg = FlexSendMessage(
            alt_text=f"今日 ({today_str}) 買訊",
            contents=CarouselContainer(contents=bubbles)
        )

        if Config.TEST_MODE:
            line_bot_api.push_message(Config.ADMIN_USER_ID, flex_msg)
            push_message_to_admin("[測試模式] 報表已發送")
        else:
            line_bot_api.broadcast(flex_msg)
            # 發送完卡片後，補上戰情室連結
            liff_url = f"https://liff.line.me/{Config.LIFF_ID}"
            broadcast_message(f"📊 點此查看個人完整戰情室：\n{liff_url}")

    except Exception as e:
        print(f"Report Error: {e}")


def push_stop_loss_alert(user_id, symbol, stock_name, current_price, stop_loss, loss_pct):
    """
    發送紅色警報卡片，包含 K線圖 與「確認賣出」按鈕
    """
    header_color = "#D32F2F"  # 深紅

    # 取得最新圖卡網址 (對齊 BASE_URL 並加上時間戳防快取)
    timestamp = int(datetime.now().timestamp())
    chart_url = f"{Config.BASE_URL}/api/stock_chart/{symbol}?v={timestamp}"

    bubble = BubbleContainer(
        hero=ImageComponent(
            url=chart_url,
            size="full",
            aspectRatio="20:13",
            aspectMode="cover",
            action=URIAction(uri=chart_url)
        ),
        header=BoxComponent(
            layout='vertical',
            backgroundColor=header_color,
            contents=[
                TextComponent(text="⚠️ 觸發停損警報", weight='bold', color='#FFFFFF', size='lg'),
                TextComponent(text=f"{symbol} 跌破防線", color='#FFFFFF', size='xs', margin='sm')
            ]
        ),
        body=BoxComponent(
            layout='vertical',
            contents=[
                TextComponent(text=stock_name, weight='bold', size='xl', wrap=True),
                SeparatorComponent(margin='md'),
                BoxComponent(
                    layout='vertical', margin='md', spacing='sm',
                    contents=[
                        BoxComponent(
                            layout='baseline', spacing='sm',
                            contents=[
                                TextComponent(text="現價", color='#aaaaaa', size='sm', flex=1),
                                TextComponent(text=f"{current_price}", weight='bold', color='#000000', size='sm',
                                              flex=2)
                            ]
                        ),
                        BoxComponent(
                            layout='baseline', spacing='sm',
                            contents=[
                                TextComponent(text="停損", color='#aaaaaa', size='sm', flex=1),
                                TextComponent(text=f"{stop_loss}", weight='bold', color='#D32F2F', size='sm', flex=2)
                            ]
                        ),
                        BoxComponent(
                            layout='baseline', spacing='sm',
                            contents=[
                                TextComponent(text="損益", color='#aaaaaa', size='sm', flex=1),
                                TextComponent(text=f"{loss_pct:.2f}%", weight='bold', color='#D32F2F', size='sm',
                                              flex=2)
                            ]
                        )
                    ]
                ),
                SeparatorComponent(margin='lg'),
                TextComponent(text="紀律是交易的靈魂。請確認是否已執行賣出？", size='xs', color='#aaaaaa', wrap=True,
                              margin='md')
            ]
        ),
        footer=BoxComponent(
            layout='vertical', spacing='sm',
            contents=[
                ButtonComponent(
                    style='primary',
                    color='#D32F2F',
                    height='sm',
                    action=PostbackAction(
                        label='💔 確認賣出 (移除庫存)',
                        data=f"action=delete&symbol={symbol}",
                        display_text=f"我已賣出 {symbol}"
                    )
                )
            ]
        )
    )

    try:
        msg = FlexSendMessage(alt_text=f"⚠️ {symbol} 停損警報", contents=bubble)
        line_bot_api.push_message(user_id, msg)
        print(f"🚨 已推送精美停損圖卡給 {user_id}")
    except Exception as e:
        print(f"❌ 推送警報失敗: {e}")