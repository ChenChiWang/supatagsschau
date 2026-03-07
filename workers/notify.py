"""Telegram 通知模組。"""

import logging

import requests

import config

logger = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send(message: str):
    """發送 Telegram 訊息。未設定 token 時靜默跳過。"""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return

    try:
        resp = requests.post(
            API_URL.format(token=config.TELEGRAM_BOT_TOKEN),
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        if not resp.ok:
            logger.warning(f"Telegram 發送失敗：{resp.status_code} {resp.text}")
    except Exception as e:
        logger.warning(f"Telegram 發送失敗：{e}")
