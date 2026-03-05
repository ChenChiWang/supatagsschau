"""主流程：每日自動處理 Tagesschau Podcast。

排程建議：crontab -e
30 19 * * * cd /path/to/workers && python main.py >> /var/log/tagesschau.log 2>&1
（UTC 19:30 = CET 20:30 = 台灣 03:30）

環境變數：
  RESUME_FROM=<step>  從指定步驟恢復（跳過之前的步驟，使用快取資料）
                      可選值：2（跳過 podcast）、3（跳過轉錄）、4（跳過翻譯）、5（只推送）
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 確保 workers 目錄在 Python path 中
sys.path.insert(0, str(Path(__file__).parent))

import config
from podcast import fetch_podcast
from transcribe import transcribe
from translate import translate_and_analyze
from generate import generate_post
from git_ops import publish_post

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 中間結果快取路徑
CACHE_DIR = config.OUTPUT_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_PODCAST = CACHE_DIR / "podcast_meta.json"
CACHE_SEGMENTS = CACHE_DIR / "segments.json"
CACHE_TRANSLATION = CACHE_DIR / "translation_result.json"


def save_cache(path: Path, data):
    """儲存中間結果到 JSON 快取。"""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"  快取已儲存：{path}")


def load_cache(path: Path):
    """從 JSON 快取載入中間結果。"""
    if not path.exists():
        raise FileNotFoundError(f"快取不存在：{path}（需要先完整跑過一次）")
    data = json.loads(path.read_text(encoding="utf-8"))
    logger.info(f"  從快取載入：{path}")
    return data


def serialize_podcast_meta(meta: dict) -> dict:
    """將 podcast_meta 轉為可 JSON 序列化的 dict。"""
    d = dict(meta)
    if isinstance(d.get("pub_date"), datetime):
        d["pub_date"] = d["pub_date"].isoformat()
    d["mp3_path"] = str(d["mp3_path"])
    return d


def deserialize_podcast_meta(data: dict) -> dict:
    """從 JSON 還原 podcast_meta。"""
    d = dict(data)
    if d.get("pub_date"):
        d["pub_date"] = datetime.fromisoformat(d["pub_date"])
    return d


def main():
    resume_from = int(os.getenv("RESUME_FROM", "0"))
    if resume_from:
        logger.info(f"=== Tagesschau 從步驟 {resume_from} 恢復 ===")
    else:
        logger.info("=== Tagesschau 每日處理開始 ===")

    # 1. 取得 Podcast metadata + 下載 MP3
    if resume_from >= 2:
        logger.info("📡 Step 1: 載入快取...")
        podcast_meta = deserialize_podcast_meta(load_cache(CACHE_PODCAST))
    else:
        logger.info("📡 Step 1: 取得 Podcast...")
        podcast_meta = fetch_podcast()
        save_cache(CACHE_PODCAST, serialize_podcast_meta(podcast_meta))
    logger.info(f"  標題：{podcast_meta['title']}")
    logger.info(f"  音訊：{podcast_meta['audio_url']}")
    logger.info(f"  影片：{podcast_meta['video_url']}")

    # 2. Whisper 轉錄
    if resume_from >= 3:
        logger.info("🎙️ Step 2: 載入快取...")
        segments = load_cache(CACHE_SEGMENTS)
    else:
        logger.info("🎙️ Step 2: Whisper 轉錄...")
        segments = transcribe(podcast_meta["mp3_path"])
        save_cache(CACHE_SEGMENTS, segments)
    logger.info(f"  共 {len(segments)} 個 segments")

    # 3. 翻譯 + CEFR 分析
    if resume_from >= 4:
        logger.info("🤖 Step 3: 載入快取...")
        translation_result = load_cache(CACHE_TRANSLATION)
    else:
        logger.info("🤖 Step 3: 翻譯 + CEFR 分析...")
        translation_result = translate_and_analyze(segments)
        save_cache(CACHE_TRANSLATION, translation_result)
    logger.info(f"  翻譯 segments：{len(translation_result['segments'])}")
    for level in ["A1", "A2", "B1"]:
        data = translation_result["levels"].get(level, {})
        v = len(data.get("vocabulary", []))
        g = len(data.get("grammar", []))
        p = len(data.get("patterns", []))
        logger.info(f"  {level}：{v} 單字 / {g} 文法 / {p} 句型")

    # 4. 產生 Hugo Markdown
    logger.info("📄 Step 4: 產生 Hugo 文章...")
    md_path = generate_post(podcast_meta, translation_result)

    # 5. 推送到 Git repo
    if resume_from > 5:
        pass
    elif config.HUGO_SITE_REPO:
        logger.info("📤 Step 5: 推送到 Git repo...")
        pub_date_str = podcast_meta["pub_date"].strftime("%Y-%m-%d")
        publish_post(md_path, pub_date_str)
    else:
        logger.info("⏭️ Step 5: 未設定 HUGO_SITE_REPO，跳過 git push")
        logger.info(f"  文章位於：{md_path}")

    # 6. 清理暫存 MP3（完整跑才清理）
    if not resume_from:
        mp3_path = Path(podcast_meta["mp3_path"])
        if mp3_path.exists():
            mp3_path.unlink()
            logger.info(f"🗑️ 已刪除暫存 MP3：{mp3_path}")

    logger.info("=== 處理完成 ===")


if __name__ == "__main__":
    main()
