"""主流程：每日自動處理 Tagesschau Podcast。

排程建議：crontab -e
30 19 * * * cd /path/to/workers && python main.py >> /var/log/tagesschau.log 2>&1
（UTC 19:30 = CET 20:30 = 台灣 03:30）

環境變數：
  RESUME_FROM=<step>  從指定步驟恢復（跳過之前的步驟，使用快取資料）
                      可選值：2（跳過 podcast）、3（跳過轉錄）、
                             3.5（跳過翻譯，只重跑 CEFR）、
                             4（跳過翻譯+CEFR）、5（只推送）
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
from translate import translate_batch, analyze_cefr, BATCH_SIZE
from generate import generate_post
from git_ops import publish_post
from align import download_and_align

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
CACHE_TRANSLATED = CACHE_DIR / "translated_segments.json"
CACHE_CEFR = CACHE_DIR / "cefr_result.json"
# 舊版合併快取（相容用）
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


def run_translation(segments: list[dict]) -> list[dict]:
    """分批翻譯所有 segments。"""
    max_batches = int(os.getenv("MAX_BATCHES", "0")) or None
    all_translated = []
    for i in range(0, len(segments), BATCH_SIZE):
        batch = segments[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(segments) + BATCH_SIZE - 1) // BATCH_SIZE
        if max_batches and batch_num > max_batches:
            logger.info(f"測試模式：已達 {max_batches} 批上限，跳過剩餘批次")
            break
        logger.info(f"翻譯第 {batch_num}/{total_batches} 批（{len(batch)} segments）")
        translated = translate_batch(batch)
        all_translated.extend(translated)
    return all_translated


def main():
    resume_from = float(os.getenv("RESUME_FROM", "0"))
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

    # 1b. 計算影片偏移量（快取中有值且不需重算才跳過）
    if podcast_meta.get("video_offset") is not None and resume_from >= 3:
        video_offset = podcast_meta["video_offset"]
        logger.info(f"  影片偏移：{video_offset}s（從快取）")
    else:
        logger.info("🔀 Step 1b: 計算影片偏移量...")
        try:
            video_offset = download_and_align(
                str(podcast_meta["mp3_path"]),
                podcast_meta["video_url"],
            )
        except Exception as e:
            logger.warning(f"偏移計算失敗，使用 0：{e}")
            video_offset = 0.0
        podcast_meta["video_offset"] = video_offset
        save_cache(CACHE_PODCAST, serialize_podcast_meta(podcast_meta))
        logger.info(f"  影片偏移：{video_offset}s")

    # 2. Whisper 轉錄
    if resume_from >= 3:
        logger.info("🎙️ Step 2: 載入快取...")
        segments = load_cache(CACHE_SEGMENTS)
    else:
        logger.info("🎙️ Step 2: Whisper 轉錄...")
        segments = transcribe(podcast_meta["mp3_path"])
        save_cache(CACHE_SEGMENTS, segments)
    logger.info(f"  共 {len(segments)} 個 segments")

    # 3a. 翻譯
    if resume_from >= 3.5:
        # 跳過翻譯，從快取或舊合併快取載入
        logger.info("🔤 Step 3a: 載入翻譯快取...")
        if CACHE_TRANSLATED.exists():
            translated_segments = load_cache(CACHE_TRANSLATED)
        elif CACHE_TRANSLATION.exists():
            old_cache = load_cache(CACHE_TRANSLATION)
            translated_segments = old_cache["segments"]
            logger.info("  （從舊版合併快取提取翻譯）")
        else:
            raise FileNotFoundError("找不到翻譯快取，請先跑完翻譯")
    else:
        logger.info("🔤 Step 3a: 翻譯...")
        translated_segments = run_translation(segments)
        save_cache(CACHE_TRANSLATED, translated_segments)
    logger.info(f"  翻譯 segments：{len(translated_segments)}")

    # 3b. CEFR 分析
    if resume_from >= 4:
        logger.info("📊 Step 3b: 載入 CEFR 快取...")
        cefr_result = load_cache(CACHE_CEFR)
    else:
        logger.info("📊 Step 3b: CEFR 學習內容分析...")
        timestamped_transcript = "\n".join(
            f"[{s['start']}] {s['text']}" for s in segments
        )
        cefr_result = analyze_cefr(timestamped_transcript)
        save_cache(CACHE_CEFR, cefr_result)

    for level in ["A1", "A2", "B1"]:
        data = cefr_result["levels"].get(level, {})
        v = len(data.get("vocabulary", []))
        g = len(data.get("grammar", []))
        p = len(data.get("patterns", []))
        logger.info(f"  {level}：{v} 單字 / {g} 文法 / {p} 句型")

    # 合併翻譯結果
    translation_result = {
        "segments": translated_segments,
        "levels": cefr_result["levels"],
        "summary_zh": cefr_result.get("summary_zh", ""),
    }

    # 4. 產生 Hugo Markdown
    logger.info("📄 Step 4: 產生 Hugo 文章...")
    podcast_meta["video_offset"] = video_offset
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
