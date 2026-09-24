"""识别内核：图 → 结构化字段（+ 逐字段来源标注）。

本模块是**纯确定性管道**（vision 调用之外没有随机性）：

```
图片 URL ──normalize──▶ 多模态消息 ──vision──▶ JSON 文本 ──extract_fields──▶ 字段表
```

「字段表」是**唯一**的出口形状，两个入口（页面快通道 / Agent 深通道）都消费它：

```python
{"key": "name", "label": "商品名称", "value": "雪尼尔遮光窗帘",
 "source": "[图片识别]", "reason": None}
{"key": "door_width", "label": "门幅", "value": None,
 "source": None, "reason": "图片未标注门幅"}
```

三条硬规则（issue #5321）：

1. **`[图片识别]` 标注**（`FIELD_MARKER`）：值非空 ⇒ `source` 必为该串。
   这是用户判断「该信哪一格」的**唯一依据**（现有约定见
   `backend/ai-agent-service/app/graph/skills/product_skill.py`）。
2. **不确定的宁可不填**：空值 / 置信度低于该 target 的阈值 ⇒ 留空**并给理由**，绝不猜。
   订单侧另有两道**形状硬闸**（放在置信度闸之前 —— 形状错时置信度高只说明"抄得清楚"）：
   手机号必须是 11 位有效号码；**尺寸**（帘宽 / 帘高，issue #5349）必须是**能直接进推导链的数**
   （`2.8×2.4` 这种没写明宽高方向的写法**不猜顺序**，一格都不填）。
3. 🔴 **不落库、不提交**：本模块不 import 任何写入缝（会话记忆 / DB / admin-api），
   `recognize()` 的返回体只有「填哪几格」——**提交永远是人的动作**。
   机械判据：`backend/ai-agent-service/tests/test_vision_recognize.py::TestNoWriteBoundary`
   （静态扫描 + 扫描器判别力红证 + 端点返回体恰好三个键）。
"""
import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage
from loguru import logger

from app.llm import LLMFactory
from app.vision.pipeline import normalize_image_urls
from app.vision.targets import (
    TARGET_FIELDS,
    TARGET_POLICY,
    TARGET_SIDE_LABEL,
    TargetField,
)

#: 逐字段来源标注（现有约定，务必保留原样）
FIELD_MARKER = "[图片识别]"

#: 单次 vision 调用上限（与对话路径的 LLM_CALL_TIMEOUT_S 同量级；页面入口是同步等待）
VISION_CALL_TIMEOUT_S = 60.0

_THINK_RE = re.compile(r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>")
_MOBILE_RE = re.compile(r"^1[3-9]\d{9}$")
_NON_DIGIT_RE = re.compile(r"\D")

#: 订单侧的**尺寸字段**（issue #5349）—— 推导链的原始输入。值必须能被前端 `Number()` 直接吃下：
#: 填一个 `2.8米` 进数字框 = `NaN` ⇒ 推导链 fail-closed（页面看着"填了"，实际一个推导项都不产出）。
_SIZE_FIELDS = frozenset({"curtain_width", "curtain_height"})

#: 尺寸的合理量程（米）—— 越界即视为「认错了 / 图上根本不是尺寸」。
#: 下限 0.2：比这更小的窗帘不存在；上限 20：家用 / 商用布艺的极端值，
#: 同时能抓住「漏了小数点」的形态（`2.8` → `28`）。
_SIZE_RANGE_M: Tuple[float, float] = (0.2, 20.0)

_SIZE_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

#: 留空理由：模型没给该字段 / 模型自己说看不清
_NOT_RECOGNISED = "图片未给出该字段"
#: 留空理由：模型没给置信度 —— 按最低处理（宁可留空，不冒错填的风险）
_NO_CONFIDENCE = "未给出置信度，无法判断把握程度，宁可不填"


def build_messages(target_type: str, image_urls: List[str]) -> List[HumanMessage]:
    """构造发给 vision 的多模态消息（文本提示 + 逐图 `image_url` 块）。"""
    schema = _schema_for(target_type)
    lines = [
        "你是布艺行业单据/面料图的字段录入助手。从图片中提取以下字段，**只输出 JSON**。",
        "",
        "字段清单（key：说明）：",
    ]
    for f in schema:
        lines.append(f"- {f.key}（{f.label}）：{f.hint}")
    lines += [
        "",
        "输出格式（严格遵守）：",
        '{"fields": {"<key>": {"value": <字符串或 null>, "confidence": <0~1 的小数>, '
        '"reason": "<value 为 null 时说明为什么看不清>"}}}',
        "",
        "铁律：",
        "1. 只抄图上**确实写明**的内容，不推算、不联想、不补全。",
        "2. 看不清 / 图上没有 ⇒ value 必须为 null，并在 reason 里说明原因。**宁可不填，不要猜。**",
        "3. confidence 是你对**该格**的把握程度（0~1）：抄写清楚的手写体约 0.9，"
        "潦草/模糊的低于 0.6。",
        "4. 不要输出任何解释文字，只要那一个 JSON 对象。",
    ]
    content: List[Dict[str, Any]] = [{"type": "text", "text": "\n".join(lines)}]
    content += [{"type": "image_url", "image_url": {"url": url}} for url in image_urls]
    return [HumanMessage(content=content)]


def extract_fields(target_type: str, raw_text: str) -> List[dict]:
    """`字段 → 表单` 段（**纯函数**，可写死断言 —— 固定夹具钉住 vision 输出即可测）。

    返回**固定按 schema 顺序**的整张字段表（不是"识别到什么就返回什么"）——
    页面按它逐格填、逐格标注来源。
    """
    schema = _schema_for(target_type)
    policy = TARGET_POLICY[target_type]
    parsed = _parse_json(raw_text)
    raw_fields = (parsed or {}).get("fields")
    if not isinstance(raw_fields, dict):
        raw_fields = {}

    fields: List[dict] = []
    for f in schema:
        entry = raw_fields.get(f.key)
        value, reason = _resolve(target_type, f, entry, policy)
        fields.append({
            "key": f.key,
            "label": f.label,
            "value": value,
            "source": FIELD_MARKER if value else None,
            "reason": reason,
        })
    return fields


async def recognize(
    target_type: str,
    images: Any,
    *,
    tenant_id: Optional[int] = None,
) -> dict:
    """页面路径的**唯一**入口：图 → 结构化字段。

    签名里**没有** `session_id` / 会话对象 —— 「识别内核可被页面路径独立调用」这条判据
    不是靠约定，是靠**没有可传的会话**（判据：
    `tests/test_vision_recognize.py::test_recognize_runs_without_a_conversation_session`）。

    vision 失败 / 输出不可解析 / 一格都没认出来 ⇒ `degraded=True` + 空字段表
    （**不编造、不半填**，前端据此提示「请手工填写或换一张更清晰的图片」）。
    """
    _schema_for(target_type)  # 未知 target 在此抛 ValueError（fail-closed，不做默认回落）
    urls = normalize_image_urls(images)
    if not urls:
        raise ValueError("没有可用的图片：URL 必须是 https:// 或 /api/files 开头")

    messages = build_messages(target_type, urls)
    try:
        llm = LLMFactory.create_vision_llm()
        response = await asyncio.wait_for(llm.ainvoke(messages), timeout=VISION_CALL_TIMEOUT_S)
        raw_text = _extract_content(response)
    except Exception as e:  # noqa: BLE001 —— 任何失败都降级为「没认出来」，不阻断调用方
        logger.warning(
            f"[vision] 识别调用失败，降级为空字段 | target={target_type} "
            f"tenant={tenant_id} error={e.__class__.__name__}: {e}"
        )
        return {"target_type": target_type, "fields": [], "degraded": True}

    fields = extract_fields(target_type, raw_text)
    if not any(f["value"] for f in fields):
        logger.info(
            f"[vision] 未识别到可用字段 | target={target_type} tenant={tenant_id} "
            f"text_len={len(raw_text)}"
        )
        return {"target_type": target_type, "fields": [], "degraded": True}
    return {"target_type": target_type, "fields": fields, "degraded": False}


# ── 内部：纯函数分解（便于逐个写死断言）─────────────────────────────────────
def _schema_for(target_type: str):
    if target_type not in TARGET_FIELDS:
        raise ValueError(f"不支持的识别 target: {target_type!r}")
    return TARGET_FIELDS[target_type]


def _resolve(
    target_type: str,
    field: TargetField,
    entry: Any,
    policy: Dict[str, float],
):
    """把模型对**一格**的答复解析成 `(value, reason)`。留空一律给得出理由。"""
    if not isinstance(entry, dict):
        return None, _NOT_RECOGNISED

    value = _as_text(entry.get("value"))
    if not value:
        return None, _as_text(entry.get("reason")) or _NOT_RECOGNISED

    confidence = entry.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return None, _NO_CONFIDENCE

    # 订单侧的第一道硬闸：手机号**形状**不合就留空（错填 = 货发错人）。
    # 放在置信度闸**之前**：一个「很自信地认错」的号码，置信度再高也不能填。
    if target_type == "order" and field.key == "customer_phone":
        digits = _normalise_phone(value)
        if not _MOBILE_RE.match(digits):
            return None, f"手机号「{value}」不是 11 位有效号码，宁可不填"
        value = digits

    # 订单侧的第二道硬闸（issue #5349）：**尺寸**必须是能直接进推导链的数。
    # 同样放在置信度闸**之前**：一个「很自信地抄成 `2.8×2.4`」的尺寸，置信度再高也不能填
    # —— 形状错 ⇒ 下游一定错（成品尺寸 ⇒ 米数 ⇒ 钱）。
    if target_type == "order" and field.key in _SIZE_FIELDS:
        size, size_reason = _normalise_size(value)
        if size is None:
            return None, size_reason
        value = size

    min_confidence = policy["min_confidence"]
    if confidence < min_confidence:
        return None, (
            f"置信度 {confidence} 低于{TARGET_SIDE_LABEL[target_type]}阈值 "
            f"{min_confidence}，宁可不填"
        )
    return value, None


def _normalise_size(value: str) -> Tuple[Optional[str], Optional[str]]:
    """尺寸原文 → `(规范十进制串, None)`；**不合法 ⇒ `(None, 留空理由)`**。

    三条（issue #5349；每条都有会红的夹具，见 `tests/test_vision/test_recognizer.py`）：

    1. 🔴 **没写明方向的成对写法**（`2.8×2.4` / `2.8*2.4`）⇒ 留空：手写单上「哪个是宽、哪个是高」
       的**约定不统一** ⇒ 猜顺序 = 把宽当高用（成品尺寸反了 ⇒ 米数错 ⇒ 钱错）
       ⇒ 按「不确定的宁可不填」**不猜**，请商家手工填；
    2. 读不出**唯一一个**数（没有数字 / 两个以上）⇒ 留空；
    3. 超出合理量程 ⇒ 留空（`28` 米不是窗帘，是漏了小数点）。

    归一（`2.80 米` → `2.8`、`约 2.5 米左右` → `2.5`）不是锦上添花：页面的宽高是**数字框**
    （`Number(value)`），原文带中文单位 ⇒ `NaN` ⇒ 推导链静默不发试算 —— 那比留空更糟
    （商家看着格子是"填上了"的）。
    """
    numbers = _SIZE_NUMBER_RE.findall(value)
    if len(numbers) >= 2:
        return None, (
            f"「{value}」没写明哪一个是宽、哪一个是高（手写单的宽高顺序约定不统一）"
            "⇒ 宁可不填，请手工填「帘宽」「帘高」"
        )
    if not numbers:
        return None, f"「{value}」里读不出尺寸数字 ⇒ 宁可不填"
    metres = float(numbers[0])
    low, high = _SIZE_RANGE_M
    if not low <= metres <= high:
        return None, f"「{value}」不在帘宽 / 帘高的合理量程（{low}~{high} 米）内 ⇒ 宁可不填"
    return f"{metres:g}", None


def _normalise_phone(value: str) -> str:
    """去掉分隔符与 `+86` 国家码（手写单常见 `138 0013 8000` / `+86 138-0013-8000`）。"""
    digits = _NON_DIGIT_RE.sub("", value)
    if len(digits) == 13 and digits.startswith("86"):
        digits = digits[2:]
    return digits


def _as_text(value: Any) -> str:
    """把模型给的值收成非空字符串（数字 128 也收成 "128"）；`None`/空串 ⇒ ""。"""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _parse_json(raw_text: str) -> Optional[dict]:
    """从模型输出里抠出那一个 JSON 对象（允许前后有解释文字 / ``` 围栏）。"""
    text = raw_text or ""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_content(response: Any) -> str:
    """取出模型文本（多模态 list content 拼文本块；剔思考段）。"""
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return _THINK_RE.sub("", str(content or "")).strip()