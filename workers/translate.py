"""用 Ollama 翻譯逐字稿並分析 CEFR 學習內容。
翻譯用量化版模型（快），CEFR 分析用 fp16（精準）。"""

import json
import logging
import os
import re

import requests

import config

logger = logging.getLogger(__name__)

# 每批次最大 segment 數（約 2-3 分鐘的內容）
BATCH_SIZE = 8

# CEFR 分析需要更大的 context 和 output
CEFR_NUM_CTX = 32768
CEFR_NUM_PREDICT = 16384
CEFR_MAX_RETRIES = 2


def call_ollama(
    prompt: str,
    temperature: float = 0.3,
    model: str = None,
    num_ctx: int = 8192,
    num_predict: int = 8192,
) -> str:
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
                "num_predict": num_predict,
                "num_ctx": num_ctx,
            },
        },
        timeout=1800,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def repair_json(text: str) -> str:
    """嘗試修復不完整的 JSON（截斷造成的未關閉括號）。"""
    # 移除 markdown code block 標記
    text = re.sub(r"^```json\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())

    # 找到最外層 { 的位置
    start = text.find("{")
    if start == -1:
        return text

    text = text[start:]

    # 計算未關閉的括號
    stack = []
    in_string = False
    escape = False
    last_valid = 0

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(ch)
            last_valid = i
        elif ch in "}]":
            if stack:
                stack.pop()
            last_valid = i

    if not stack:
        # JSON 已完整，直接回傳
        return text

    # 截斷到最後一個完整的 value 結尾（逗號或括號之後）
    # 然後補上缺少的關閉括號
    truncated = text[:last_valid + 1]

    # 移除尾部不完整的 key-value（如 "word": "abc 被截斷）
    # 往回找到最後一個完整的結構結束點
    truncated = re.sub(r',\s*"[^"]*"?\s*:?\s*("([^"\\]|\\.)*)?$', "", truncated)
    truncated = re.sub(r',\s*\{[^}]*$', "", truncated)
    truncated = re.sub(r',\s*$', "", truncated)

    # 重新計算需要補上的括號
    stack2 = []
    in_str2 = False
    esc2 = False
    for ch in truncated:
        if esc2:
            esc2 = False
            continue
        if ch == "\\":
            esc2 = True
            continue
        if ch == '"':
            in_str2 = not in_str2
            continue
        if in_str2:
            continue
        if ch in "{[":
            stack2.append(ch)
        elif ch in "}]":
            if stack2:
                stack2.pop()

    # 補上關閉括號
    closing = ""
    for opener in reversed(stack2):
        closing += "]" if opener == "[" else "}"

    repaired = truncated + closing
    return repaired


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
    """分析全文，按 CEFR 等級提取學習內容。含重試和 JSON 修復。"""
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

另外，請在 JSON 最外層加一個 "summary_zh" 欄位，以 Markdown 條列式整理本集新聞重點摘要：
- 每則新聞主題一個條目，用 `- **主題關鍵詞**：一句話摘要` 格式
- 涵蓋所有報導主題，不限條數
- 必須使用繁體中文（台灣用語）

請只輸出 JSON，不要加 markdown code block 標記，格式如下：
{{
  "summary_zh": "- **主題一**：摘要內容\\n- **主題二**：摘要內容\\n...",
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

    fallback = {
        "summary_zh": "",
        "A1": {"vocabulary": [], "grammar": [], "patterns": []},
        "A2": {"vocabulary": [], "grammar": [], "patterns": []},
        "B1": {"vocabulary": [], "grammar": [], "patterns": []},
    }

    for attempt in range(1, CEFR_MAX_RETRIES + 1):
        logger.info(f"CEFR 分析第 {attempt}/{CEFR_MAX_RETRIES} 次嘗試...")
        result = call_ollama(
            prompt,
            temperature=0.2,
            num_ctx=CEFR_NUM_CTX,
            num_predict=CEFR_NUM_PREDICT,
        )

        # 第一次嘗試：直接解析
        try:
            start_idx = result.index("{")
            end_idx = result.rindex("}") + 1
            data = json.loads(result[start_idx:end_idx])
            logger.info("CEFR JSON 解析成功")
            summary_zh = data.pop("summary_zh", "")
            return {"summary_zh": summary_zh, "levels": data}
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"CEFR JSON 直接解析失敗：{e}")

        # 第二次嘗試：修復 JSON
        try:
            repaired = repair_json(result)
            data = json.loads(repaired)
            logger.info("CEFR JSON 修復後解析成功")
            summary_zh = data.pop("summary_zh", "")
            return {"summary_zh": summary_zh, "levels": data}
        except (ValueError, json.JSONDecodeError) as e2:
            logger.warning(f"CEFR JSON 修復後仍失敗：{e2}")
            logger.error(f"原始回應前 500 字：{result[:500]}")

    logger.error("CEFR 分析全部重試失敗，使用空白降級處理")
    summary_zh = fallback.pop("summary_zh", "")
    return {"summary_zh": summary_zh, "levels": fallback}


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
