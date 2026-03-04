"""解析 Tagesschau 20 Uhr Podcast RSS feed，取得最新一集的 metadata 並下載 MP3。"""

import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests

import config

logger = logging.getLogger(__name__)

# 德國時區 CET/CEST
CET = timezone(timedelta(hours=1))


def parse_feed(url: str) -> feedparser.FeedParserDict:
    """解析 RSS feed，回傳 feedparser 結果。"""
    feed = feedparser.parse(url)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"RSS 解析失敗：{feed.bozo_exception}")
    return feed


def get_latest_episode(feed: feedparser.FeedParserDict) -> dict:
    """從 feed 取出最新一集的 metadata。"""
    if not feed.entries:
        raise RuntimeError("RSS feed 沒有任何集數")
    entry = feed.entries[0]

    # 解析 pubDate（struct_time → datetime）
    pub_struct = entry.get("published_parsed")
    if pub_struct:
        pub_dt = datetime(*pub_struct[:6], tzinfo=CET)
    else:
        pub_dt = None

    # 取得 enclosure URL
    enclosure_url = ""
    enclosure_type = ""
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure":
            enclosure_url = link.get("href", "")
            enclosure_type = link.get("type", "")
            break
    if not enclosure_url and hasattr(entry, "enclosures") and entry.enclosures:
        enc = entry.enclosures[0]
        enclosure_url = enc.get("href", enc.get("url", ""))
        enclosure_type = enc.get("type", "")

    return {
        "title": entry.get("title", ""),
        "pub_date": pub_dt,
        "description": entry.get("summary", entry.get("description", "")),
        "enclosure_url": enclosure_url,
        "enclosure_type": enclosure_type,
        "duration": entry.get("itunes_duration", ""),
        "guid": entry.get("id", ""),
        "link": entry.get("link", ""),
    }


def is_today(pub_dt: datetime) -> bool:
    """檢查 pub_date 是否為今天（CET 時區）。"""
    if pub_dt is None:
        return False
    now_cet = datetime.now(CET)
    return pub_dt.date() == now_cet.date()


def download_mp3(url: str, output_dir: Path) -> Path:
    """下載 MP3 到指定目錄，回傳本地檔案路徑。"""
    filename = url.split("/")[-1]
    filepath = output_dir / filename
    logger.info(f"下載 MP3：{url}")
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"MP3 已儲存：{filepath}（{filepath.stat().st_size / 1024 / 1024:.1f} MB）")
    return filepath


def fetch_podcast() -> dict:
    """主函式：取得今天的 Podcast metadata 並下載 MP3。

    含重試機制：若最新集不是今天的，等待後重試。
    設定環境變數 SKIP_DATE_CHECK=1 可跳過日期檢查（測試用）。

    回傳 dict 包含：
        title, pub_date, description, audio_url, video_url,
        duration, guid, mp3_path, topics
    """
    skip_date = os.getenv("SKIP_DATE_CHECK", "") == "1"

    for attempt in range(1, config.MAX_RETRIES + 1):
        logger.info(f"嘗試取得 Podcast（第 {attempt}/{config.MAX_RETRIES} 次）")

        # 解析 Audio 和 Video feed
        audio_feed = parse_feed(config.AUDIO_RSS_URL)
        video_feed = parse_feed(config.VIDEO_RSS_URL)

        audio_ep = get_latest_episode(audio_feed)
        video_ep = get_latest_episode(video_feed)

        if skip_date:
            logger.info(f"跳過日期檢查，使用最新集數：{audio_ep['title']}")
            break

        if is_today(audio_ep["pub_date"]):
            logger.info(f"找到今天的集數：{audio_ep['title']}")
            break

        if attempt < config.MAX_RETRIES:
            logger.warning(
                f"最新集日期 {audio_ep['pub_date']} 不是今天，"
                f"{config.RETRY_INTERVAL_SEC} 秒後重試..."
            )
            time.sleep(config.RETRY_INTERVAL_SEC)
    else:
        # 所有重試都失敗，仍使用最新的一集
        logger.warning("重試次數已用完，使用最新可用的集數")

    # 下載 MP3
    mp3_path = download_mp3(audio_ep["enclosure_url"], config.OUTPUT_DIR)

    # 從 description 擷取主題列表（逗號分隔）
    desc = audio_ep["description"]
    topics = [t.strip() for t in desc.split(",") if t.strip()]
    # 移除最後的「Das Wetter」和 Hinweis 開頭的項目
    topics = [t for t in topics if not t.startswith("Hinweis") and not t.startswith("\n")]

    return {
        "title": audio_ep["title"],
        "pub_date": audio_ep["pub_date"],
        "description": audio_ep["description"],
        "audio_url": audio_ep["enclosure_url"],
        "video_url": video_ep["enclosure_url"],
        "duration": audio_ep["duration"],
        "guid": audio_ep["guid"],
        "link": audio_ep["link"],
        "mp3_path": mp3_path,
        "topics": topics,
    }
