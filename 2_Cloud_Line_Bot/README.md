# ☁️ Cloud Line Bot (雲端推播與後端)

本目錄負責將本地端算好的數據，透過 LINE 傳遞到手機上，並提供一個簡易的網頁介面來管理追蹤清單。

在開發此模組時，為了應付 LINE Webhook 的時間限制以及圖表讀取的順暢度，採用了非同步的架構來實作。

---

## 🌟 主要功能實作

1. **LINE Flex Message 推播**
   * 讀取本地端產出的 CSV 總表，透過 LINE Messaging API 將股票代號、現價、防守價組裝成容易閱讀的輪播圖卡。
2. **非同步後端伺服器 (Quart)**
   * 替換掉原本的 Flask，確保在處理多個請求或背景更新時，伺服器不會發生 I/O 阻塞。
3. **LIFF 簡易追蹤清單**
   * 在 `templates/` 底下實作了一個搭配 Bootstrap 的 HTML 前端。
   * 透過 LINE LIFF 開啟，並搭配 SQLite 建立一個簡單的資料庫，用於紀錄個人正在追蹤的標的與設定的停損價。
4. **簡易背景監控**
   * 透過 Python 的 `schedule` 套件實作排程，定時觸發價格檢查，若跌破設定價位則發送 LINE 通知。

> **⚠️ 設定檔提醒**
> 上傳的 `config.py` 為空殼範本，實際的 LINE Channel Secret 與 Token 皆已移除。