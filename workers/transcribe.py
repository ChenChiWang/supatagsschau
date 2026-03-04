"""把 MP3 送到 GPU 伺服器的 WhisperX API，取回德語逐字稿（含時間戳）。"""

import logging
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)


def format_timestamp(seconds: float) -> str:
    """將秒數轉為 MM:SS 格式。"""
    total_sec = int(seconds)
    minutes = total_sec // 60
    secs = total_sec % 60
    return f"{minutes:02d}:{secs:02d}"


def transcribe(mp3_path: Path) -> list[dict]:
    """呼叫 WhisperX API 轉錄音訊。

    回傳 segments 列表，每個 segment 包含：
        start: str (MM:SS)
        end: str (MM:SS)
        text: str (德語原文)
    """
    url = f"{config.WHISPER_API_URL}/transcribe"

    logger.info(f"送出音訊到 WhisperX API：{mp3_path}")
    with open(mp3_path, "rb") as f:
        resp = requests.post(
            url,
            files={"file": (Path(mp3_path).name, f, "audio/mpeg")},
            data={"language": "de"},
            timeout=1800,  # 30 分鐘
        )
    resp.raise_for_status()
    result = resp.json()

    raw_segments = result.get("segments", [])
    logger.info(f"轉錄完成，共 {len(raw_segments)} 個 segments")

    segments = []
    for seg in raw_segments:
        segments.append({
            "start": format_timestamp(seg["start"]),
            "end": format_timestamp(seg["end"]),
            "text": seg["text"].strip(),
        })

    return segments
