"""來源媒體品質檢查：用 ffprobe 驗證音訊/影片時長是否合理。"""

import logging
import subprocess

logger = logging.getLogger(__name__)

# tagesschau 20 Uhr 通常 15~21 分鐘
MIN_DURATION_SEC = 600  # 10 分鐘以下視為異常
MAX_DURATION_DIFF_SEC = 30  # 音訊與影片時長差距上限


def get_media_duration(url: str) -> float | None:
    """用 ffprobe 取得媒體時長（秒），失敗回傳 None。"""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            logger.warning(f"ffprobe 失敗：{result.stderr.strip()}")
            return None
        return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError) as e:
        logger.warning(f"ffprobe 錯誤：{e}")
        return None


def validate_sources(audio_url: str, video_url: str) -> dict:
    """檢查音訊和影片來源品質。

    回傳 dict：
        ok: bool — 是否通過檢查
        audio_duration: float | None
        video_duration: float | None
        errors: list[str] — 錯誤訊息
    """
    errors = []

    audio_dur = get_media_duration(audio_url)
    video_dur = get_media_duration(video_url)

    logger.info(f"音訊時長：{audio_dur:.1f}s" if audio_dur else "音訊時長：無法取得")
    logger.info(f"影片時長：{video_dur:.1f}s" if video_dur else "影片時長：無法取得")

    if audio_dur is None:
        errors.append("無法取得音訊時長")
    elif audio_dur < MIN_DURATION_SEC:
        errors.append(f"音訊過短：{audio_dur:.0f}s（門檻 {MIN_DURATION_SEC}s）")

    if video_dur is None:
        errors.append("無法取得影片時長")
    elif video_dur < MIN_DURATION_SEC:
        errors.append(f"影片過短：{video_dur:.0f}s（門檻 {MIN_DURATION_SEC}s）")

    if audio_dur and video_dur:
        diff = abs(audio_dur - video_dur)
        if diff > MAX_DURATION_DIFF_SEC:
            errors.append(
                f"音訊與影片時長差距過大：{diff:.1f}s（門檻 {MAX_DURATION_DIFF_SEC}s）"
            )

    return {
        "ok": len(errors) == 0,
        "audio_duration": audio_dur,
        "video_duration": video_dur,
        "errors": errors,
    }
