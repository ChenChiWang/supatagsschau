import os
from pathlib import Path

# GPU 伺服器
WHISPER_API_URL = os.getenv("WHISPER_API_URL", "http://localhost:9000")
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:32b-fp16")

# Whisper 模型（Speaches 用 HuggingFace 模型名稱）
WHISPER_MODEL = "Systran/faster-whisper-large-v3"

# Hugo 網站 Git Repo
HUGO_SITE_REPO = os.getenv("HUGO_SITE_REPO", "")
HUGO_SITE_DIR = Path(os.getenv("HUGO_SITE_DIR", "./output/site"))
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH", "")

# 暫存目錄
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Podcast RSS Feed URLs
AUDIO_RSS_URL = "https://www.tagesschau.de/multimedia/sendung/tagesschau_20_uhr/podcast-ts2000-audio-100~podcast.xml"
VIDEO_RSS_URL = "https://www.tagesschau.de/multimedia/sendung/tagesschau_20_uhr/podcast-ts2000-video-100~podcast.xml"

# 重試設定
MAX_RETRIES = 6
RETRY_INTERVAL_SEC = 300  # 5 分鐘
