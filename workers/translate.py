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
CEFR_MAX_RETRIES = 3


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


def fix_json_newlines(text: str) -> str:
    """修復 JSON 字串值中的未轉義換行符（LLM 常見問題）。"""
    result = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and in_string and i + 1 < len(text):
            # 保留轉義序列
            result.append(ch)
            result.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
        elif ch == "\n" and in_string:
            result.append("\\n")
        elif ch == "\r" and in_string:
            pass
        elif ch == "\t" and in_string:
            result.append("\\t")
        else:
            result.append(ch)
        i += 1
    return "".join(result)


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

    for attempt in range(1, 3):
        result = call_ollama(prompt, model=config.OLLAMA_MODEL_FAST, num_predict=8192)
        try:
            start_idx = result.index("[")
            end_idx = result.rindex("]") + 1
            translated = json.loads(result[start_idx:end_idx])
            return translated
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"翻譯 JSON 解析失敗（第 {attempt}/2 次）：{e}")
            logger.error(f"原始回應：{result[:500]}")

    # 全部失敗，降級處理
    logger.error("翻譯重試全部失敗，使用降級處理")
    return [
        {"start": s["start"], "end": s["end"], "de": s["text"], "zh": "[翻譯失敗]"}
        for s in segments
    ]


def merge_split_strings(text: str) -> str:
    """修復 LLM 把一個 JSON 字串值拆成多個逗號分隔字串的問題。

    常見於 summary_zh 欄位：
      "summary_zh": "第一條",\n"第二條",\n"第三條",\n  "A1": ...
    修復為：
      "summary_zh": "第一條\\n第二條\\n第三條",\n  "A1": ...
    """
    # 匹配模式：一個 key 後面跟著多個逗號分隔的裸字串（不帶 key）
    # "key": "val1",\n"val2",\n"val3"  →  "key": "val1\nval2\nval3"
    def fix_match(m):
        key_part = m.group(1)  # "key": 的部分
        raw = m.group(2)       # "val1",\n"val2",\n"val3" 的部分
        # 提取每個引號內的字串
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', raw)
        merged = "\\n".join(parts)
        return f'{key_part}"{merged}"'

    # 偵測 "key": "...",\n"..." 的連續模式（後面接的不是 key:value 而是裸字串）
    pattern = r'("(?:summary_zh|[^"]*)":\s*)((?:"(?:[^"\\]|\\.)*"\s*,\s*\n?\s*){2,}"(?:[^"\\]|\\.)*")'
    return re.sub(pattern, fix_match, text)


def parse_llm_json(text: str) -> dict:
    """解析 LLM 回傳的 JSON，依序嘗試多種修復策略。"""
    # 1. 直接解析
    try:
        start_idx = text.index("{")
        end_idx = text.rindex("}") + 1
        return json.loads(text[start_idx:end_idx])
    except (ValueError, json.JSONDecodeError):
        pass

    # 2. 修復字串內的未轉義換行符（LLM 最常見問題）
    try:
        fixed = fix_json_newlines(text)
        start_idx = fixed.index("{")
        end_idx = fixed.rindex("}") + 1
        return json.loads(fixed[start_idx:end_idx])
    except (ValueError, json.JSONDecodeError):
        pass

    # 3. 合併被拆散的字串（如 summary_zh 被拆成多行）
    try:
        merged = merge_split_strings(text)
        fixed = fix_json_newlines(merged)
        start_idx = fixed.index("{")
        end_idx = fixed.rindex("}") + 1
        return json.loads(fixed[start_idx:end_idx])
    except (ValueError, json.JSONDecodeError):
        pass

    # 4. 全部修復 + 修復截斷
    try:
        merged = merge_split_strings(text)
        fixed = fix_json_newlines(merged)
        repaired = repair_json(fixed)
        return json.loads(repaired)
    except (ValueError, json.JSONDecodeError):
        pass

    raise json.JSONDecodeError("所有修復方式都失敗", text[:200], 0)


def analyze_cefr(timestamped_transcript: str) -> dict:
    """分析全文，按 CEFR 等級提取學習內容。含重試和 JSON 修復。"""
    prompt = f"""你是專業的德語教學專家，目標讀者是台灣的德語學習者。
請分析以下德語新聞逐字稿，按 CEFR 等級提取學習內容。

⚠️ 最重要的規則 — 違反即為失敗：
1. summary_zh 必須是繁體中文，禁止出現任何德文或英文
2. 所有 meaning、example_zh、chinese、explanation、translation、note 欄位必須是繁體中文
3. 只有 word、example、german、pattern 這些「德語原文」欄位才用德文

分級標準：
- A1（初學者）：最基礎的詞彙和句型（sein/haben、現在式、W-Fragen、基本語序 SVO）
- A2（初級）：日常生活進階（Perfekt/Präteritum、weil/dass 從句、Dativ 介詞、反身動詞）
- B1（中級）：新聞理解所需（Konjunktiv II、Passiv、zu+Infinitiv、間接引語、複雜從句）

提取目標（盡量填滿，從逐字稿中多找例子）：
- 單字 Wortschatz：A1 約 8 個、A2 約 10 個、B1 約 10 個
- 文法 Grammatik：A1 約 3 個、A2 約 4 個、B1 約 4 個
- 句型 Satzmuster：A1 約 3 個、A2 約 4 個、B1 約 4 個

其他要求：
- 所有例句必須來自逐字稿原文
- 如果某等級找不到好例子，寧可少放也不要硬湊
- 名詞務必標注性別（der/die/das）
- 每個例句必須附上對應的時間戳（time 欄位，格式 MM:SS），從逐字稿的時間標記中取得
- 文法術語一律使用德文原文：Nominativ、Akkusativ、Dativ、Genitiv（不要用「第一格、第二格、第三格、第四格」）
- 動詞搭配格位時寫法範例：「接 Akkusativ」「與 Dativ 搭配」「支配 Genitiv」

另外，請在 JSON 最外層加一個 "summary_zh" 欄位：
- 用繁體中文條列式整理本集新聞重點摘要（⚠️ 必須全部是繁體中文，不可以有德文）
- 每則新聞主題一個條目，格式：「- **中文主題關鍵詞**：一句話中文摘要」
- 涵蓋所有報導主題，不限條數
- summary_zh 的值是一個字串，用 \\n 分隔每個條目
- 正確範例：「- **中東戰爭**：伊朗對以色列發動攻擊」
- 錯誤範例：「- **Nahostkrieg**：Iran greift Israel an」← 這是錯的！

請只輸出合法 JSON（不要 markdown code block），字串中的換行用 \\n 表示：
{{
  "summary_zh": "- **中東局勢**：摘要內容\\n- **德國政治**：摘要內容",
  "A1": {{
    "vocabulary": [
      {{"word": "德文單字", "article": "der/die/das", "meaning": "繁體中文意思", "example": "逐字稿例句", "example_zh": "繁體中文翻譯", "time": "MM:SS"}}
    ],
    "grammar": [
      {{"rule": "文法規則（德文＋中文）", "german": "逐字稿例句", "chinese": "繁體中文翻譯", "explanation": "繁體中文詳細解說", "time": "MM:SS"}}
    ],
    "patterns": [
      {{"pattern": "句型結構", "example": "逐字稿例句", "translation": "繁體中文翻譯", "note": "繁體中文使用情境說明", "time": "MM:SS"}}
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

        try:
            data = parse_llm_json(result)
            # 驗證結果完整性
            has_content = any(
                data.get(level, {}).get("vocabulary")
                for level in ["A1", "A2", "B1"]
            )
            if not has_content:
                logger.warning("CEFR JSON 解析成功但內容為空，重試中...")
                continue
            # 驗證 summary_zh 是中文（偵測德文輸出）
            summary_zh = data.pop("summary_zh", "")
            if summary_zh:
                # 計算中文字元比例（CJK Unified Ideographs）
                cjk_chars = sum(1 for c in summary_zh if '\u4e00' <= c <= '\u9fff')
                total_alpha = sum(1 for c in summary_zh if c.isalpha())
                cjk_ratio = cjk_chars / max(total_alpha, 1)
                if cjk_ratio < 0.3:
                    logger.warning(f"summary_zh 中文比例過低（{cjk_ratio:.0%}），疑似德文輸出，重試中...")
                    continue
            logger.info("CEFR JSON 解析成功且內容完整")
            return {"summary_zh": summary_zh, "levels": data}
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"CEFR JSON 解析失敗：{e}")
            logger.error(f"原始回應前 500 字：{result[:500]}")

    logger.error("CEFR 分析全部重試失敗，使用空白降級處理")
    summary_zh = fallback.pop("summary_zh", "")
    return {"summary_zh": summary_zh, "levels": fallback}


