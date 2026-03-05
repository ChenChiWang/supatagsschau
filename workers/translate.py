"""用 Ollama 翻譯逐字稿並分析 CEFR 學習內容。
翻譯用量化版模型（快），CEFR 分析用 fp16（精準）。"""

import json
import logging
import os

import requests

import config

logger = logging.getLogger(__name__)

# 每批次最大 segment 數（約 2-3 分鐘的內容）
BATCH_SIZE = 8


def call_ollama(prompt: str, temperature: float = 0.3, model: str = None) -> str:
    """呼叫 Ollama API（chat endpoint），回傳生成的文字。"""
    use_model = model or config.OLLAMA_MODEL
    resp = requests.post(
        f"{config.OLLAMA_API_URL}/api/chat",
        json={
            "model": use_model,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": 8192,
                "num_ctx": 8192,
            },
        },
        timeout=1800,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def translate_batch(segments: list[dict]) -> list[dict]:
    """翻譯一批 segments（德 → 繁體中文）。"""
    segments_text = "\n".join(
        f"[{s['start']} - {s['end']}] {s['text']}" for s in segments
    )

    prompt = f"""你是專業的德中翻譯員。請將以下德語新聞逐字稿翻譯為繁體中文。

規則：
- 必須使用繁體中文（台灣用語）
- 保持每段的時間戳對應
- 翻譯要自然流暢，適合台灣讀者閱讀
- 專有名詞保留德文原文並附中文翻譯

請只輸出 JSON 陣列，格式如下：
[
  {{"start": "MM:SS", "end": "MM:SS", "de": "德語原文", "zh": "繁體中文翻譯"}}
]

德語逐字稿：
{segments_text}"""

    result = call_ollama(prompt, model=config.OLLAMA_MODEL_FAST)

    # 從回應中擷取 JSON
    try:
        start_idx = result.index("[")
        end_idx = result.rindex("]") + 1
        translated = json.loads(result[start_idx:end_idx])
    except (ValueError, json.JSONDecodeError) as e:
        logger.error(f"翻譯結果 JSON 解析失敗：{e}")
        logger.error(f"原始回應：{result[:500]}")
        # 降級處理：保留原文，翻譯標記為失敗
        translated = [
            {"start": s["start"], "end": s["end"], "de": s["text"], "zh": "[翻譯失敗]"}
            for s in segments
        ]

    return translated


def analyze_cefr(timestamped_transcript: str) -> dict:
    """分析全文，按 CEFR 等級提取學習內容。"""
    prompt = f"""你是專業的德語教學專家。請分析以下德語新聞逐字稿，按 CEFR 等級提取學習內容。

分級標準：
- A1（初學者）：最基礎的詞彙和句型（sein/haben、現在式、W-Fragen、基本語序 SVO）
- A2（初級）：日常生活進階（Perfekt/Präteritum、weil/dass 從句、Dativ 介詞、反身動詞）
- B1（中級）：新聞理解所需（Konjunktiv II、Passiv、zu+Infinitiv、間接引語、複雜從句）

提取目標：
- 單字 Wortschatz：A1 約 5 個、A2 約 6 個、B1 約 6 個
- 文法 Grammatik：A1 約 2 個、A2 約 3 個、B1 約 3 個
- 句型 Satzmuster：A1 約 2 個、A2 約 2 個、B1 約 2 個

重要：
- 必須使用繁體中文（台灣用語）
- 所有例句必須來自逐字稿原文
- 如果某等級找不到好例子，寧可少放也不要硬湊
- 名詞務必標注性別（der/die/das）
- 每個例句必須附上對應的時間戳（time 欄位，格式 MM:SS），從逐字稿的時間標記中取得
- 文法術語一律使用德文原文：Nominativ、Akkusativ、Dativ、Genitiv（不要用「第一格、第二格、第三格、第四格」）
- 動詞搭配格位時寫法範例：「接 Akkusativ」「與 Dativ 搭配」「支配 Genitiv」

另外，請在 JSON 最外層加一個 "summary_zh" 欄位，用 3-5 句繁體中文摘要本集新聞重點。

請只輸出 JSON，格式如下：
{{
  "summary_zh": "本集新聞的繁體中文摘要（3-5 句）",
  "A1": {{
    "vocabulary": [
      {{"word": "德文單字", "article": "der/die/das（名詞才需要）", "meaning": "中文意思", "example": "逐字稿中的例句", "example_zh": "例句翻譯", "time": "MM:SS"}}
    ],
    "grammar": [
      {{"rule": "文法規則名稱（德文＋中文）", "german": "逐字稿中的例句", "chinese": "中文翻譯", "explanation": "詳細解說（繁體中文）", "time": "MM:SS"}}
    ],
    "patterns": [
      {{"pattern": "句型結構（如 Subjekt + Verb + Objekt）", "example": "逐字稿中的例句", "translation": "中文翻譯", "note": "使用情境說明", "time": "MM:SS"}}
    ]
  }},
  "A2": {{ ... }},
  "B1": {{ ... }}
}}

德語新聞逐字稿（含時間戳）：
{timestamped_transcript}"""

    result = call_ollama(prompt, temperature=0.2)

    try:
        start_idx = result.index("{")
        end_idx = result.rindex("}") + 1
        data = json.loads(result[start_idx:end_idx])
    except (ValueError, json.JSONDecodeError) as e:
        logger.error(f"CEFR 分析結果 JSON 解析失敗：{e}")
        logger.error(f"原始回應：{result[:500]}")
        data = {
            "summary_zh": "",
            "A1": {"vocabulary": [], "grammar": [], "patterns": []},
            "A2": {"vocabulary": [], "grammar": [], "patterns": []},
            "B1": {"vocabulary": [], "grammar": [], "patterns": []},
        }

    # 分離 summary_zh 和等級資料
    summary_zh = data.pop("summary_zh", "")
    return {"summary_zh": summary_zh, "levels": data}


def translate_and_analyze(segments: list[dict]) -> dict:
    """主函式：翻譯逐字稿並產生 CEFR 學習內容。

    回傳 dict：
        segments: 翻譯後的 segments（含 de + zh）
        levels: CEFR 學習內容（A1, A2, B1）
    """
    # 測試模式：限制批次數
    max_batches = int(os.getenv("MAX_BATCHES", "0")) or None

    # 分批翻譯
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

    # 組合帶時間戳的全文送 CEFR 分析
    timestamped_transcript = "\n".join(
        f"[{s['start']}] {s['text']}" for s in segments
    )
    logger.info("開始 CEFR 學習內容分析...")
    cefr_result = analyze_cefr(timestamped_transcript)

    return {
        "segments": all_translated,
        "levels": cefr_result["levels"],
        "summary_zh": cefr_result["summary_zh"],
    }
