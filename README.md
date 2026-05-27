# 多角色教學輔助系統

一個可直接部署的 Gemini API 教學聊天網站，支援三種教學角色與 SSE 即時逐字輸出。

## 功能

- 聊天系統
- 前端切換教學角色
  - 老師（嚴格）
  - 家教老師（引導）
  - 課後輔導員（輕鬆）
- 後端呼叫 Gemini API
- Server-Sent Events 串流回應
- 可部署到 Render、Railway、Fly.io、Google Cloud Run、Azure App Service 等 Node.js 平台

## 本機執行（Python，推薦給目前這台電腦）

```bash
cp .env.example .env
```

在 `.env` 填入：

```bash
GEMINI_API_KEY=你的_Gemini_API_Key
GEMINI_MODEL=gemini-2.5-flash-lite
PORT=3000
```

啟動：

```bash
python run.py
```

開啟：

```text
http://localhost:3000
```

## 本機執行（Node.js）

若部署平台使用 Node.js，或你的電腦已安裝 Node 18+，也可以啟動：

```bash
npm start
```

開啟：

```text
http://localhost:3000
```

## 雲端部署

### Python 平台

- Build command：不需要，或留空
- Start command：`python run.py`
- Environment variables：
  - `GEMINI_API_KEY`
  - `GEMINI_MODEL`，可選，預設 `gemini-2.5-flash-lite`
  - `PORT`，多數平台會自動提供

### Node.js 平台

- Build command：不需要，或留空
- Start command：`npm start`
- Environment variables：
  - `GEMINI_API_KEY`
  - `GEMINI_MODEL`，可選，預設 `gemini-2.5-flash-lite`
  - `PORT`，多數平台會自動提供

## API

### `GET /api/health`

檢查服務與 Gemini API key 是否已設定。

### `POST /api/chat`

回傳 `text/event-stream`。

Request body：

```json
{
  "role": "strict_teacher",
  "messages": [
    {
      "role": "user",
      "content": "請教我二次函數配方法"
    }
  ]
}
```

SSE events：

- `token`：逐字或分段文字
- `done`：完成
- `error`：錯誤訊息
