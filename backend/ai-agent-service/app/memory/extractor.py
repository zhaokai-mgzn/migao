"""
AI 智能客服系统 - 用户记忆自动提取

每次对话结束后，异步调用轻量模型从对话中提取值得记住的信息。
写入 user_memories 表，下次对话时注入 System Prompt。

issue #2815（C 端长期记忆系统）改造：
- agent_type 分流：仅 xiaobu（C 端）提取落库；mibao（B 端）直接跳过
- C 端受控词表 CEND_MEMORY_KEYS：LLM 只能产出词表内 key，消灭语义漂移/去重失效
- PII 变体拦截：key 词根匹配（40+ 变体）而非精确黑名单；值含手机号/邮箱一律不落库
- context 去 PII：不再写原始 user_message 明文，仅存会话标识
"""

import json
import re
from typing import Optional, List, Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

# 模块级导入（供测试 patch 模块属性 + 避免函数内重复导入）
from app.memory.session_state_store import SessionStateStore
from app.memory.user_memory import UserMemoryManager


# ── C 端受控词表（issue #2815：LLM 只能选词表内 key）──
# 画像维度：风格/颜色/遮光/尺寸/预算/安装/加工/购买方式/复购意向
# 会话态/一次性 key（订单号、数量、状态、意图、待办）一律不在词表内 → 自动丢弃
CEND_MEMORY_KEYS: frozenset[str] = frozenset({
    "curtain_style",      # 风格偏好（奶油风/简约/欧式）
    "curtain_color",      # 颜色偏好
    "shade_requirement",  # 遮光需求
    "window_size",        # 常用尺寸（宽×高）
    "curtain_length",     # 窗帘长度习惯
    "budget_range",       # 预算区间
    "install_method",     # 安装方式（罗马杆/轨道/免打孔）
    "processing_style",   # 加工偏好（打孔/挂钩/帘头）
    "purchase_unit",      # 购买单位（按米/按件）
    "repurchase_intent",  # 复购意向
    "fabric_preference",  # 面料偏好（雪尼尔/棉麻/遮光布）
    "room_type",          # 使用场景（客厅/卧室/儿童房）
})

# PII key 词根（LLM 自由生成 key 的变体拦截，数据实证 40+ 变体全漏过精确黑名单）
_PII_KEY_PATTERN = re.compile(
    r"phone|mobile|address|email|name|contact|wechat|id_?card|idcard|"
    r"province|city|district|detail_info|recipient|deliver|postal|zip|qq",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def _filter_pii(memories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """过滤含个人隐私信息的记忆（key 词根变体 + 值手机号/邮箱），PII 不落库。

    issue #2815：从「6 个精确 key 黑名单」升级为「词根匹配」，
    覆盖 LLM 自由生成的 40+ 变体（customer_phone/phone_numbers/shipping_address/
    recipient_name 等），并对 value 与 context 做手机号/邮箱正则拦截。
    """
    if not memories:
        return memories
    out = []
    for m in memories:
        key = str(m.get('key', '')).lower()
        value = str(m.get('value', ''))
        context = str(m.get('context', '') or '')
        if _PII_KEY_PATTERN.search(key):
            continue
        if _PHONE_RE.search(value) or _EMAIL_RE.search(value):
            continue
        if _PHONE_RE.search(context) or _EMAIL_RE.search(context):
            # context 去 PII：命中则丢弃该条（数据实证：context 曾明文存手机号/地址）
            continue
        out.append(m)
    return out


def _filter_vocabulary(memories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """受控词表过滤：只保留 key 在 CEND_MEMORY_KEYS 内的记忆。

    消灭「同一语义 40 个变体 key」导致的 upsert 去重失效（issue #2815 数据实证）。
    """
    if not memories:
        return memories
    return [m for m in memories if str(m.get('key', '')).strip() in CEND_MEMORY_KEYS]


EXTRACTION_PROMPT = """你是一个记忆提取器。从以下客服对话中提取值得记住的用户信息（仅 C 端消费者画像）。

只提取**明确表达**的内容，不要编造或推测。

记忆类型：
- preference: 用户偏好（喜欢的风格、颜色、预算范围、遮光需求等）
- fact: 关键事实（常用尺寸、购买单位等）

**key 必须从以下受控词表中选择，禁止发明新 key**：
{allowed_keys}

禁止提取的内容：
1. 手机号、地址、邮箱、姓名等个人隐私信息（记忆系统不保存 PII）
2. 一次性会话信息：订单号、订单数量、订单状态、物流、售后单号、操作意图、待办事项
3. 重复已明确的信息

评分要求：
- importance 0-1：明确且长期有效的偏好 0.7-0.9，一般事实 0.5-0.7
- 如果对话中没有值得记住的信息，返回空数组

输出格式（纯 JSON 数组，不要其他内容）：
[{{"type": "preference", "key": "curtain_style", "value": "奶油风", "importance": 0.8}}]"""


def _parse_extraction_result(text: str) -> List[Dict[str, Any]]:
    """从 LLM 响应中解析记忆列表"""
    text = text.strip()

    # 尝试直接解析 JSON
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 JSON 数组
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    return []


async def extract_memories_from_turn(
    user_message: str,
    assistant_reply: str,
    session_id: str = "",
    agent_type: str = "xiaobu",
) -> List[Dict[str, Any]]:
    """从一轮对话中提取用户记忆

    issue #2815：agent_type 分流——仅 xiaobu（C 端）提取；mibao（B 端）直接返回 []，
    不调 LLM、不落库。

    Args:
        user_message: 用户消息
        assistant_reply: AI 回复
        session_id: 会话 ID（用于日志与 context 溯源）
        agent_type: Agent 类型（"xiaobu"/"mibao"）；非 xiaobu 不提取

    Returns:
        记忆列表 [{type, key, value, importance, context}]
    """
    # B 端不提取（issue #2815：米宝暂不对接长期记忆）
    if agent_type != "xiaobu":
        return []

    # 跳过太短的对话（问候、感谢等）
    if len(user_message) < 4 and len(assistant_reply) < 20:
        return []

    prompt = (
        f"用户消息: {user_message[:500]}\n"
        f"AI 回复: {assistant_reply[:500]}\n\n"
        f"请提取值得记住的用户信息（纯 JSON 数组）。"
    )

    try:
        from app.llm import LLMFactory
        llm = LLMFactory.create_suggestion_llm()  # 复用 suggestion 的轻量模型
        system_content = EXTRACTION_PROMPT.format(
            allowed_keys="、".join(sorted(CEND_MEMORY_KEYS))
        )
        response = await llm.ainvoke([
            SystemMessage(content=system_content),
            HumanMessage(content=prompt),
        ])
        content = response.content if isinstance(response.content, str) else ""
        items = _filter_pii(_filter_vocabulary(_parse_extraction_result(content)))

        if items:
            # context 去 PII（issue #2815 数据实证：曾明文存手机号/地址）：
            # 仅存会话标识与角色意图摘要，不写原始 user_message
            for item in items:
                if "context" not in item:
                    item["context"] = f"session={session_id} | agent=xiaobu"
            logger.info(
                f"[memory-extractor] Extracted {len(items)} memories | "
                f"session={session_id} keys={[i.get('key','?') for i in items]}"
            )
        return items

    except Exception as e:
        logger.warning(
            f"[memory-extractor] Extraction failed | session={session_id} error={e}"
        )
        return []


async def extract_and_save(
    tenant_id: int,
    user_id: str,
    user_message: str,
    assistant_reply: str,
    session_id: str = "",
    agent_type: str = "xiaobu",
) -> int:
    """提取记忆并保存到 user_memories 表

    issue #2815：agent_type 透传——mibao 不提取不落库；xiaobu 提取结果带
    agent_type 写入（供注入时按 Agent 过滤）。

    Args:
        tenant_id: 租户 ID
        user_id: 用户 ID
        user_message: 用户消息
        assistant_reply: AI 回复
        session_id: 会话 ID
        agent_type: Agent 类型（"xiaobu"/"mibao"）；非 xiaobu 直接返回 0

    Returns:
        成功保存的记忆条数
    """
    if agent_type != "xiaobu":
        return 0

    items = await extract_memories_from_turn(
        user_message, assistant_reply, session_id, agent_type=agent_type
    )
    if not items:
        return 0

    try:
        manager = UserMemoryManager()
        count = await manager.batch_upsert(
            tenant_id, user_id, items, agent_type=agent_type
        )
        logger.info(
            f"[memory-extractor] Saved {count}/{len(items)} memories | "
            f"tenant={tenant_id} user={user_id} agent={agent_type}"
        )
        return count
    except Exception as e:
        logger.error(f"[memory-extractor] Save failed: {e}")
        return 0


# ── 会话末聚合（issue #2815）──
# 每轮提取候选记忆累积到 session_states.state.memory_candidates（按 key 去重、
# 高 importance 胜出），会话关闭时 flush 批量落库——减少落库次数、避免每轮碎片化写入。
#
# 候选载荷结构（打包 tenant/user/agent，flush 无需调用方传参）：
#   state["memory_candidates"] = {
#       "tenant_id": 1, "user_id": "u1", "agent_type": "xiaobu",
#       "items": [{"type", "key", "value", "importance", "context"}, ...],
#   }

async def extract_and_accumulate(
    tenant_id: int,
    user_id: str,
    agent_type: str,
    session_id: str,
    user_message: str,
    assistant_reply: str,
) -> int:
    """提取记忆并累积到会话工作状态（不直接落库）。

    - 仅 xiaobu（C 端）累积；mibao 返回 0
    - 候选按 key 合并：同 key 保留 importance 更高者（key 受控后不再同义堆积）
    - 累积存于 session_states.state["memory_candidates"]，由 flush_memories 在会话关闭时落库

    Returns:
        本轮新增/更新的候选条数（失败返回 0，不抛）
    """
    if agent_type != "xiaobu":
        return 0
    items = await extract_memories_from_turn(
        user_message, assistant_reply, session_id, agent_type=agent_type
    )
    if not items:
        return 0
    try:
        store = SessionStateStore()
        state = (await store.load(session_id)) or {}
        payload = state.get("memory_candidates") or {}
        by_key: Dict[str, Dict[str, Any]] = {}
        for c in payload.get("items", []):
            by_key[str(c.get("key", ""))] = c
        merged = 0
        for item in items:
            key = str(item.get("key", ""))
            prev = by_key.get(key)
            if prev is None or (item.get("importance", 0) or 0) > (prev.get("importance", 0) or 0):
                by_key[key] = item
                merged += 1
        state["memory_candidates"] = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "agent_type": agent_type,
            "items": list(by_key.values()),
        }
        await store.commit(session_id, state)
        logger.debug(
            f"[memory-extractor] Accumulated {merged} candidates | "
            f"session={session_id} total={len(by_key)}"
        )
        return merged
    except Exception as e:
        logger.warning(f"[memory-extractor] Accumulate failed | session={session_id} error={e}")
        return 0


async def flush_memories(session_id: str) -> int:
    """会话关闭时：把累积的候选记忆批量写入 user_memories 并清空候选。

    候选载荷自带 tenant_id/user_id/agent_type（extract_and_accumulate 打包），
    调用方（会话关闭路径）无需传身份参数。

    Args:
        session_id: 会话 ID

    Returns:
        实际落库条数（无候选/异常返回 0，不抛）
    """
    try:
        store = SessionStateStore()
        state = (await store.load(session_id)) or {}
        payload = state.get("memory_candidates") or {}
        items = payload.get("items") or []
        if not items:
            return 0
        tenant_id = payload.get("tenant_id")
        user_id = payload.get("user_id")
        agent_type = payload.get("agent_type", "xiaobu")
        manager = UserMemoryManager()
        count = await manager.batch_upsert(
            tenant_id, user_id, items, agent_type=agent_type
        )
        # 清空候选（保留其余状态字段）
        state.pop("memory_candidates", None)
        await store.commit(session_id, state)
        logger.info(
            f"[memory-extractor] Flushed {count}/{len(items)} memories | "
            f"session={session_id} agent={agent_type}"
        )
        return count
    except Exception as e:
        logger.warning(f"[memory-extractor] Flush failed | session={session_id} error={e}")
        return 0
