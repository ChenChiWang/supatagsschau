"""比對音訊與影片音軌，計算時間偏移量（秒）。

用 ffmpeg 提取前 120 秒的原始 PCM，再用 cross-correlation 找出影片相對於音訊的偏移。
正值表示影片內容比音訊晚（影片有片頭），負值表示影片比音訊早。
"""

import logging
import subprocess

import numpy as np

logger = logging.getLogger(__name__)

# 取樣參數（單聲道、16kHz 足以做對齊）
SAMPLE_RATE = 16000
DURATION_SEC = 120


def extract_pcm(media_path: str, duration: int = DURATION_SEC) -> np.ndarray:
    """用 ffmpeg 從媒體檔提取原始 PCM（mono, 16kHz, int16）。"""
    cmd = [
        "ffmpeg", "-i", media_path,
        "-t", str(duration),
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-v", "quiet",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    return np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32)


def compute_offset(audio_path: str, video_path: str) -> float:
    """計算影片相對於音訊的時間偏移（秒）。

    回傳值：影片播放時，時間戳需要加上此值才能對齊。
    例如回傳 5.0 表示影片比音訊多了 5 秒片頭。
    """
    logger.info("提取音訊 PCM...")
    audio_pcm = extract_pcm(audio_path)
    logger.info("提取影片音軌 PCM...")
    video_pcm = extract_pcm(video_path)

    if len(audio_pcm) == 0 or len(video_pcm) == 0:
        logger.warning("PCM 資料為空，無法計算偏移，回傳 0")
        return 0.0

    # 正規化
    audio_pcm = audio_pcm / (np.max(np.abs(audio_pcm)) + 1e-8)
    video_pcm = video_pcm / (np.max(np.abs(video_pcm)) + 1e-8)

    # Cross-correlation（用 FFT 加速）
    n = len(audio_pcm) + len(video_pcm) - 1
    fft_size = 1
    while fft_size < n:
        fft_size *= 2

    fft_audio = np.fft.rfft(audio_pcm, fft_size)
    fft_video = np.fft.rfft(video_pcm, fft_size)
    correlation = np.fft.irfft(fft_audio * np.conj(fft_video), fft_size)

    # 找最大相關的位移
    max_idx = np.argmax(np.abs(correlation))

    # 將 index 轉為秒數
    if max_idx > fft_size // 2:
        lag_samples = max_idx - fft_size
    else:
        lag_samples = max_idx

    offset_sec = -lag_samples / SAMPLE_RATE

    # 合理範圍檢查（超過 15 秒的偏移不太可能）
    if abs(offset_sec) > 15:
        logger.warning(f"偵測到異常偏移 {offset_sec:.2f}s，可能比對失敗，回傳 0")
        return 0.0

    logger.info(f"偵測到影片偏移：{offset_sec:.2f} 秒")
    return round(offset_sec, 2)


def download_and_align(audio_source: str, video_url: str) -> float:
    """計算音訊與影片的時間偏移。

    音訊來源可以是本地檔案路徑或 URL，ffmpeg 都能直接讀取。

    Args:
        audio_source: 音訊 MP3 路徑或 URL
        video_url: 影片 URL

    Returns:
        偏移秒數
    """
    logger.info("從音訊和影片 URL 提取 PCM 進行對齊...")
    # ffmpeg 可直接從 URL 讀取，不需先下載
    return compute_offset(audio_source, video_url)
