"""主流程：每日自動處理 Tagesschau Podcast。

排程建議：crontab -e
30 19 * * * cd /path/to/workers && python main.py >> /var/log/tagesschau.log 2>&1
（UTC 19:30 = CET 20:30 = 台灣 03:30）
"""

import logging
import sys
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


def main():
    logger.info("=== Tagesschau 每日處理開始 ===")

    # 1. 取得 Podcast metadata + 下載 MP3
    logger.info("📡 Step 1: 取得 Podcast...")
    podcast_meta = fetch_podcast()
    logger.info(f"  標題：{podcast_meta['title']}")
    logger.info(f"  音訊：{podcast_meta['audio_url']}")
    logger.info(f"  影片：{podcast_meta['video_url']}")

    # 2. Whisper 轉錄
    logger.info("🎙️ Step 2: Whisper 轉錄...")
    segments = transcribe(podcast_meta["mp3_path"])
    logger.info(f"  共 {len(segments)} 個 segments")

    # 3. 翻譯 + CEFR 分析
    logger.info("🤖 Step 3: 翻譯 + CEFR 分析...")
    translation_result = translate_and_analyze(segments)
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
    if config.HUGO_SITE_REPO:
        logger.info("📤 Step 5: 推送到 Git repo...")
        pub_date_str = podcast_meta["pub_date"].strftime("%Y-%m-%d")
        publish_post(md_path, pub_date_str)
    else:
        logger.info("⏭️ Step 5: 未設定 HUGO_SITE_REPO，跳過 git push")
        logger.info(f"  文章位於：{md_path}")

    # 6. 清理暫存 MP3
    mp3_path = Path(podcast_meta["mp3_path"])
    if mp3_path.exists():
        mp3_path.unlink()
        logger.info(f"🗑️ 已刪除暫存 MP3：{mp3_path}")

    logger.info("=== 處理完成 ===")


if __name__ == "__main__":
    main()
