"""用 Jinja2 模板產生 Hugo Markdown 文章。"""

import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

import config

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def generate_post(podcast_meta: dict, translation_result: dict) -> Path:
    """產生 Hugo Markdown 文章。

    Args:
        podcast_meta: fetch_podcast() 的回傳值
        translation_result: translate_and_analyze() 的回傳值

    Returns:
        產生的 Markdown 檔案路徑
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )
    template = env.get_template("post.md.j2")

    pub_date: datetime = podcast_meta["pub_date"]
    date_str = pub_date.strftime("%Y-%m-%d")
    date_german = pub_date.strftime("%d.%m.%Y")
    date_iso = pub_date.strftime("%Y-%m-%dT%H:%M:%S+01:00")

    # 判斷哪些等級有內容
    active_levels = []
    levels = translation_result.get("levels", {})
    for level in ["A1", "A2", "B1"]:
        data = levels.get(level, {})
        has_content = (
            data.get("vocabulary")
            or data.get("grammar")
            or data.get("patterns")
        )
        if has_content:
            active_levels.append(level)

    rendered = template.render(
        title=podcast_meta["title"],
        date_iso=date_iso,
        date_german=date_german,
        topics=podcast_meta["topics"],
        active_levels=active_levels,
        video_url=podcast_meta["video_url"],
        audio_url=podcast_meta["audio_url"],
        link=podcast_meta["link"],
        segments=translation_result["segments"],
        levels=levels,
    )

    output_path = config.OUTPUT_DIR / f"{date_str}-tagesschau.md"
    output_path.write_text(rendered, encoding="utf-8")
    logger.info(f"Hugo 文章已產生：{output_path}")
    return output_path
