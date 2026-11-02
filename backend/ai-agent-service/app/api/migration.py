"""旧 ERP 客户表头 → 规范客户字段 的映射建议（内部接口，issue #8295）。

本端点只回答「哪一列对应哪个规范字段」，**不落库、不读库、不执行导入**：
响应体恰好三个键（`mappings` / `degraded` / `message`），没有任何客户数据回传，
也没有写入痕迹 —— 真正的导入动作与采纳决定都在 admin-api / 商家页面。

安全口径（PII 不进模型上下文、也不进日志）：
- 样本值在**进入提示词之前**脱敏：手机号只留前 3 后 2（`13800138000` → `138******00`）、
  邮箱整体打码（`***@***`）、超长值截断（>40 字只留前 20 字 + `…`）；
- 日志只记**表头数 / 映射数 / 是否降级**，绝不记样本值，也不记「表头 + 值」的组合
  （表头本身是列名、值才是客户数据；两者一起打就是可识别信息）；
- 目标字段白名单 = 请求里的 `fields[].key`，模型编出来的字段一律丢弃（**不发明字段**）。

降级口径：模型不可用 / 未配置 Key / 超时 / 解析失败 ⇒ `degraded=true` + 空映射 + 一句中文说明，
HTTP 仍是 200 —— 这是**建议**能力而不是写操作，调用方据此提示人工调整映射，不该把迁移流程打断。
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from typing import Any, List, Optional, Sequence, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from app.api.response_models import make_response
from app.llm.factory import LLMFactory
from app.utils.auth import verify_service_token

router = APIRouter()

# 提示词预算（不是业务口径，纯粹防「一次塞进几百列」把成本/延迟打爆）。
# 超限 ⇒ 400 fail-closed；**不静默截断** —— 截断会让 `source_index` 与真实列号错位。
MAX_HEADERS = 200
MAX_FIELDS = 50
# 样本只作「列语义」提示：3 行足够区分「名称 / 电话 / 地址」，再多只是重复同样的 PII。
MAX_SAMPLE_ROWS = 3

# 样本值的展示上限：>40 字截到 20 字 + 省略号。
VALUE_MAX_CHARS = 40
VALUE_KEEP_CHARS = 20

# 中国大陆手机号：加**数字边界**，避免把订单号/身份证号里的 11 位片段当手机号打码。
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_DECODER = json.JSONDecoder()

_INVALID_INPUT_CODE = "MIGRATION_CUSTOMER_MAPPING_INVALID_INPUT"

_MSG_TIMEOUT = "AI 映射服务响应超时，请稍后重试或手工调整映射"
_MSG_UNAVAILABLE = "AI 映射服务暂不可用，请手工调整映射"
_MSG_UNPARSEABLE = "AI 返回内容无法解析为映射结果，请手工调整映射"
_MSG_NO_MAPPING = "AI 未给出可用映射，请手工调整映射"

_SYSTEM_PROMPT = (
    "你是 ERP 客户数据迁移的表头映射助手。任务：把旧 ERP 客户 Excel 的表头列，"
    "映射到给定的规范客户字段。\n"
    "规则（务必遵守）：\n"
    "1. `target_field` 只能取「目标字段」里给出的 key：禁止发明新字段，"
    "禁止把同一列映射到多个字段，禁止把同一字段映射到多列。\n"
    "2. 宁缺勿滥：拿不准就不给映射，不要为了凑数猜。\n"
    "3. `source_index` 用「源表头」方括号里的数字（从 0 开始）。\n"
    "4. `confidence` 是 0~1 的小数；`reason` 用一句中文说明依据（不超过 40 字）。\n"
    "5. 样本值已在进入提示词前脱敏（手机号/邮箱打码、超长截断），只用于判断列语义。\n"
    "输出要求：只输出一个 JSON 对象，不要解释文字、不要 Markdown 代码块。格式：\n"
    '{"mappings": [{"source_index": 0, "target_field": "displayName", "confidence": 0.95, '
    '"reason": "购货单位是客户名称的常见旧 ERP 表头"}]}'
)


# ============ 请求 / 响应模型 ============


class MigrationField(BaseModel):
    """一个规范客户字段（映射的目标白名单项）。

    `label` / `type` / `aliases` 都按**可选**处理：旧系统迁移的表单里缺 `type` 或
    `aliases` 是常态，缺了不影响映射判断（`label` 回落 `key`），不值得 422 打断迁移。
    """

    key: str = Field(..., min_length=1, description="规范字段 key（响应里 target_field 只能取它）")
    label: str = ""
    required: bool = False
    type: str = "string"
    aliases: Optional[List[str]] = Field(None, description="该字段的常见旧表头别名")


class CustomerMappingRequest(BaseModel):
    """旧 ERP 客户表头映射建议请求（字段名 snake_case，与 admin-api 内部调用同形）。"""

    headers: List[str] = Field(default_factory=list, description="旧 ERP 客户 Excel 的表头（顺序即 source_index）")
    samples: List[List[Any]] = Field(
        default_factory=list,
        description="样例行（与 headers 对齐；只取前 MAX_SAMPLE_ROWS 行，进提示词前脱敏）",
    )
    fields: List[MigrationField] = Field(default_factory=list, description="规范客户字段白名单")


class MappingSuggestion(BaseModel):
    """一条表头 → 字段的映射建议。`source_header` 一律取自请求（不信任模型回显）。"""

    source_index: int
    source_header: str
    target_field: str
    confidence: float
    reason: str = ""


class _RawMapping(BaseModel):
    """模型输出的一条映射（Pydantic 先做形态校验，再做白名单/去重/钳位）。"""

    source_index: int
    target_field: str
    confidence: float = 0.0
    reason: str = ""


# ============ PII 脱敏（提示词前） ============


def _mask_value(value: Any) -> str:
    """样本值 → 可进提示词的脱敏串。

    顺序有讲究：先打码手机号/邮箱，再按**打码后**的长度判断是否截断 —— 否则一个 200 字的
    长文本里恰好藏着手机号时，前 20 字可能刚好切在号码中间，脱敏就没做全。
    """
    text = "" if value is None else str(value).strip()
    # 手机号：保留前 3 后 2（`13800138000` → `138******00`）；固定 6 个星号，避免长度泄露位数。
    text = _PHONE_RE.sub(lambda m: m.group()[:3] + "*" * 6 + m.group()[-2:], text)
    # 邮箱：本地部分与域名都打掉（域名也可能暴露供应商/门店信息）。
    text = _EMAIL_RE.sub("***@***", text)
    if len(text) > VALUE_MAX_CHARS:
        return text[:VALUE_KEEP_CHARS] + "…"
    return text


def _one_line(value: Any, max_chars: int = 40) -> str:
    """表头 / 标签 / 别名进提示词前的单行化 + 限长。

    换行压成空格：这些都是上游给的字符串，压不成单行就等于把「多行指令」塞进提示词。
    """
    text = "" if value is None else str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:max_chars]


# ============ 提示词 ============


def _build_messages(request: CustomerMappingRequest) -> list:
    """紧凑提示词：目标字段白名单 + 源表头 + **已脱敏**样本值。

    不把整份 Excel 发出去，也不发 id / 租户等无关上下文 —— 映射只依赖列名与列的取值形态。
    """
    field_lines: List[str] = []
    for field in request.fields:
        label = _one_line(field.label) or field.key
        aliases = "、".join(a for a in (_one_line(x, 20) for x in (field.aliases or [])) if a) or "无"
        field_lines.append(
            f"- key={field.key}；名称={label}；必填={'是' if field.required else '否'}；"
            f"类型={_one_line(field.type) or 'string'}；别名={aliases}"
        )

    header_lines = [f"[{index}] {_one_line(header)}" for index, header in enumerate(request.headers)]

    sample_lines: List[str] = []
    for index, _header in enumerate(request.headers):
        values: List[str] = []
        for row in request.samples[:MAX_SAMPLE_ROWS]:
            if index < len(row):
                masked = _mask_value(row[index])
                if masked and masked not in values:
                    values.append(masked)
        if values:
            sample_lines.append(f"[{index}] " + " / ".join(values))

    human = (
        "目标字段（target_field 只能取这些 key）：\n"
        + "\n".join(field_lines)
        + "\n\n源表头（source_index = 方括号里的数字）：\n"
        + "\n".join(header_lines)
        + ("\n\n样本值（已脱敏，仅供判断列语义）：\n" + "\n".join(sample_lines) if sample_lines else "")
        + "\n\n请输出映射 JSON。"
    )

    from langchain_core.messages import HumanMessage, SystemMessage

    return [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human)]


# ============ 模型输出解析（防御式） ============


def _is_mapping_payload(data: Any) -> bool:
    """这个 JSON 值像不像映射结果：`{"mappings": ...}` 或「元素里有对象的数组」。

    为什么要它：模型常在 JSON 前后夹人话（「参考列号 [0] 后，结果如下：…」），
    而 `[0]` 本身就是**合法 JSON** —— 只按「第一段能 parse 的东西」取值会把噪声当结果。
    """
    if isinstance(data, dict):
        return "mappings" in data
    if isinstance(data, list):
        return any(isinstance(item, dict) for item in data)
    return False


def _load_json(text: str) -> Any:
    """解析模型输出：纯 JSON / ```json 代码块 / 夹在说明文字里的对象或数组。

    `None` = 完全拿不到 JSON（调用方据此判「无法解析」而不是「没有匹配」）。
    说明文字里夹 JSON 时**优先取「像映射结果」的那一段**（见 `_is_mapping_payload`），
    都不像才退回第一段可解析值（此时由上层判「没有可用映射」）。
    """
    text = (text or "").strip()
    if not text:
        return None

    candidates: List[str] = [text]
    fence = _FENCE_RE.search(text)
    if fence:
        candidates.append(fence.group(1).strip())

    first_parsed: Any = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if _is_mapping_payload(data):
            return data
        if first_parsed is None:
            first_parsed = data

    # 逐位置扫描 `{` / `[`：`raw_decode` 能从任意起点解析出完整 JSON 值，且不受后文干扰。
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            data, _end = _DECODER.raw_decode(text, index)
        except ValueError:
            continue
        if _is_mapping_payload(data):
            return data
        if first_parsed is None:
            first_parsed = data
    return first_parsed


def _mappings_from_data(
    data: Any, headers: Sequence[str], field_keys: Set[str]
) -> List[MappingSuggestion]:
    """把解析后的 JSON 变成**可执行**的映射表：白名单 + 范围 + 去重 + 置信度钳位。

    丢弃规则（每条都是**静默丢弃而不是报错**：模型输出不是契约，错一条不该让整次建议失败）：
    - `target_field` 不在请求的 `fields[].key` 里（不发明字段）；
    - `source_index` 越界 / 不是整数（`bool` 不算整数 —— `True` 会被当成 1）；
    - 同一条源列或同一个目标字段已出现过（**一列一字段，不许重映射**）。
    """
    if isinstance(data, list):
        raw_items = data
    elif isinstance(data, dict):
        raw_items = data.get("mappings")
    else:
        raw_items = None
    if not isinstance(raw_items, list):
        return []

    seen_sources: Set[int] = set()
    seen_targets: Set[str] = set()
    mappings: List[MappingSuggestion] = []
    for item in raw_items:
        if not isinstance(item, dict) or isinstance(item.get("source_index"), bool):
            continue
        try:
            parsed = _RawMapping(**item)
        except ValidationError:
            continue

        index = parsed.source_index
        target = (parsed.target_field or "").strip()
        if index in seen_sources or not 0 <= index < len(headers):
            continue
        if target not in field_keys or target in seen_targets:
            continue

        confidence = parsed.confidence
        if not math.isfinite(confidence):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))

        seen_sources.add(index)
        seen_targets.add(target)
        mappings.append(
            MappingSuggestion(
                source_index=index,
                source_header=str(headers[index]),
                target_field=target,
                confidence=confidence,
                reason=str(parsed.reason or "")[:200],
            )
        )
    return mappings


# ============ 建议生成（LLM + 降级） ============


async def suggest_customer_mapping(
    request: CustomerMappingRequest,
) -> Tuple[List[MappingSuggestion], bool, str]:
    """调模型出映射建议；任何失败都返回 `([], True, 中文说明)`，**绝不抛给调用方**。"""
    headers = [str(header) for header in request.headers]
    field_keys = {field.key for field in request.fields}
    try:
        llm = LLMFactory.create_mapping_llm()
        response = await llm.ainvoke(_build_messages(request))
        content = getattr(response, "content", None) or ""
    except asyncio.TimeoutError:
        logger.warning(
            "[migration] mapping degraded: headers={}, mappings=0, degraded=True, error=Timeout",
            len(headers),
        )
        return [], True, _MSG_TIMEOUT
    except Exception as e:  # 未配置 Key / 网络 / 供应商 4xx5xx —— 一律降级，不 500
        logger.warning(
            "[migration] mapping degraded: headers={}, mappings=0, degraded=True, error={}",
            len(headers),
            type(e).__name__,
        )
        return [], True, _MSG_UNAVAILABLE

    data = _load_json(content)
    if data is None:
        logger.warning(
            "[migration] mapping degraded: headers={}, mappings=0, degraded=True, error=Unparseable",
            len(headers),
        )
        return [], True, _MSG_UNPARSEABLE

    mappings = _mappings_from_data(data, headers, field_keys)
    if not mappings:
        logger.warning(
            "[migration] mapping degraded: headers={}, mappings=0, degraded=True, error=NoValidMapping",
            len(headers),
        )
        return [], True, _MSG_NO_MAPPING
    return mappings, False, ""


# ============ 内部端点 ============


def _bad_request(message: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"success": False, "error": {"code": _INVALID_INPUT_CODE, "message": message}},
    )


def _validate_request(request: CustomerMappingRequest) -> None:
    """入参非法是**调用方 bug** ⇒ 400 fail-closed（不降级掩盖、也不空跑一次 LLM）。"""
    if not request.headers:
        raise _bad_request("headers 不能为空：没有可映射的旧系统表头")
    if not request.fields:
        raise _bad_request("fields 不能为空：没有可映射的规范客户字段")
    if len(request.headers) > MAX_HEADERS:
        raise _bad_request(
            f"表头过多（{len(request.headers)} 列 > 上限 {MAX_HEADERS}）⇒ 请拆分后分批请求"
            "（不静默截断：截断会让 source_index 与真实列号错位）"
        )
    if len(request.fields) > MAX_FIELDS:
        raise _bad_request(
            f"目标字段过多（{len(request.fields)} 个 > 上限 {MAX_FIELDS}）⇒ 请分批请求"
        )


@router.post("/customer-mapping")
async def customer_mapping(
    request: CustomerMappingRequest,
    authorized: bool = Depends(verify_service_token),
):
    """旧 ERP 客户表头 → 规范客户字段的映射建议（`POST /api/internal/migration/customer-mapping`）。

    调用路径：`admin-web 客户导入向导` → `admin-api CustomerImportController`
    （JWT + 权限码，经 `CustomerImportAiClient`）→ **本端点**（Service Token），与
    `/internal/registration/review` / `/internal/vision/recognize` 同一套内部调用范式。

    🔴 **只给建议，不落库、不执行导入、不回传客户数据**：响应 `data` 恰好三个键
    `mappings` / `degraded` / `message`；`mappings[]` 每条只有
    `source_index` / `source_header` / `target_field` / `confidence` / `reason`。

    - `source_index` 是**请求 headers 的下标**（0 起）；`source_header` 由服务端按该下标的
      **请求值**回填，不采信模型回显（模型回显的字符串可能是它自己编的列名）。
    - 模型编出来的字段 / 越界下标 / 同一源列或同一目标字段的重复映射一律丢弃；
      `confidence` 钳到 `0~1`。
    - 模型不可用 / 未配置 Key / 超时 / 输出不是合法 JSON ⇒ `degraded=True` + `mappings=[]`
      + 一句中文说明，HTTP 仍是 **200**（建议能力失败不打断迁移流程，由页面提示人工调整）。
    - 入参非法（headers/fields 为空、超过提示词预算）⇒ **400**（`success=false` + 稳定 error code），
      且**不调用模型**。
    """
    _validate_request(request)
    mappings, degraded, message = await suggest_customer_mapping(request)
    # 只记数量与降级态：不记样本值，也不记「表头 + 值」（两者一起打就是可识别信息）。
    logger.info(
        "[migration] customer-mapping: headers={}, mappings={}, degraded={}",
        len(request.headers),
        len(mappings),
        degraded,
    )
    return make_response(
        True,
        data={
            "mappings": [mapping.model_dump() for mapping in mappings],
            "degraded": degraded,
            "message": message,
        },
    )
