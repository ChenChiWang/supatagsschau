# 每日德語 — tagesschau 新聞學德文

自動化德語學習平台：每天擷取 [tagesschau 20 Uhr](https://www.tagesschau.de/) Podcast，用 AI 產生逐字稿、繁中翻譯和 CEFR 分級學習內容。

## 架構

```
┌──────────────────────────────────────────────────────┐
│  GPU 伺服器 (Docker)                                  │
│  ┌─────────────────┐  ┌───────────────────────────┐  │
│  │  Ollama :11434   │  │  WhisperX :9000           │  │
│  │  qwen3:32b-fp16  │  │  whisper-large-v3 (GPU)   │  │
│  └─────────────────┘  └───────────────────────────┘  │
└──────────────────────────────────────────────────────┘
         ▲                        ▲
         │ 翻譯 + CEFR 分析       │ 語音轉錄
         │                        │
┌──────────────────────────────────────────────────────┐
│  NAS / 排程伺服器                                     │
│  ┌──────────────────────────────────────────────────┐│
│  │  Python Workers (每天 UTC 19:30 / 台灣 03:30)    ││
│  │  podcast.py → transcribe.py → translate.py       ││
│  │  → generate.py → git_ops.py                      ││
│  └──────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────┘
         │
         │ git push
         ▼
┌──────────────────────────────────────────────────────┐
│  GitHub                                               │
│  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │  main branch     │→ │  GitHub Actions           │  │
│  │  Hugo site +     │  │  Hugo build → Pages 部署  │  │
│  │  Workers 原始碼  │  │                            │  │
│  └──────────────────┘  └──────────────────────────┘  │
└──────────────────────────────────────────────────────┘
         │
         ▼
    deutsch.example.com
```

## 快速啟動

### 1. GPU 伺服器

```bash
# 啟動 Ollama + Whisper
cd gpu
docker compose -f docker-compose.gpu.yml up -d

# 拉取 Ollama 模型
docker exec ollama ollama pull qwen3:32b-fp16

# 測試 Whisper API
curl http://localhost:9000/health

# 測試 Ollama
curl http://localhost:11434/api/tags
```

### 2. NAS / 排程伺服器

```bash
# 安裝 Python 依賴
cd workers
pip install -r requirements.txt

# 設定環境變數
cp ../.env.example ../.env
# 編輯 .env 填入正確的 GPU 伺服器 IP、Git repo 等

# 手動測試一次
python main.py

# 設定 cron 排程（UTC 19:30 = CET 20:30 = 台灣 03:30）
crontab -e
# 30 19 * * * cd /path/to/workers && source ../.env && python main.py >> /var/log/tagesschau.log 2>&1
```

### 3. GitHub Pages

1. 在 GitHub repo Settings → Pages → Source 選擇 **GitHub Actions**
2. 設定自訂域名 CNAME（如 `deutsch.example.com`）
3. Push 到 main branch，GitHub Actions 會自動建置並部署

### 4. 本地預覽 Hugo 網站

```bash
cd site
hugo server -D
# 瀏覽 http://localhost:1313
```

## 環境變數

| 變數 | 說明 | 預設值 |
|------|------|--------|
| `WHISPER_API_URL` | Whisper API 位址 | `http://localhost:9000` |
| `OLLAMA_API_URL` | Ollama API 位址 | `http://localhost:11434` |
| `OLLAMA_MODEL` | LLM 模型名稱 | `qwen3:32b-fp16` |
| `HUGO_SITE_REPO` | Hugo 網站 Git repo SSH URL | - |
| `HUGO_SITE_DIR` | Hugo site 本地路徑 | `./output/site` |
| `SSH_KEY_PATH` | SSH Deploy Key 路徑 | - |
| `OUTPUT_DIR` | 暫存輸出目錄 | `./output` |

## 版本

| 元件 | 版本 |
|------|------|
| Ollama | `0.17.5` |
| WhisperX (Blackwell) | `mekopa/whisperx-blackwell:latest` |
| Ollama 模型 | `qwen3:32b-fp16` |
| Hugo Extended | `0.157.0` |
| PaperMod 主題 | `v8.0` |

## 版權聲明

- 音訊/影片內容來自 [ARD tagesschau](https://www.tagesschau.de/)，透過 Podcast 嵌入播放器連回原始來源
- 逐字稿由 Whisper AI 自動產生
- 翻譯和學習內容由 AI 原創生成
- 本站僅供語言學習用途，不代表 ARD/tagesschau 立場
