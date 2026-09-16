"""
智能每日经营简报生成服务（issue #3468，设计文档 docs/design/daily-briefing-design.md v0.2）

admin-api 聚合出指标快照（纯数字 + 业务事实，无客户 PII）后调用本服务：
LLM 把快照组织成「四区块简报」——昨日回顾 / 今日必办 TOP N / 风险预警 / 优化建议。

数据安全红线（设计文档 §8，最高优先级）：
1. 输入只含聚合指标与脱敏事实，禁止任何客户 PII（手机号/地址/会话原文等）；
2. 输出条目必须带 metrics 引用（key+value），admin-api 校验层与快照对账，
   不一致即丢弃——LLM 不允许产生快照之外的任何数字。

核心不变式：LLM 只负责组织/归因/措辞/排优先级，数字全部来自快照。
"""

import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from app.llm import LLMFactory

MAX_SNAPSHOT_CHARS = 6000
MAX_TODO_ITEMS = 6
MAX_RISK_ITEMS = 4
MAX_SUGGESTION_ITEMS = 4

BRIEFING_SYSTEM_PROMPT = """你是商家经营助手的「每日简报」编辑。给你一份「商家昨日经营指标快照」（JSON，全部为聚合数字与事实条目），请生成今日简报。

简报结构（严格 JSON 对象，不要输出任何其他文字）：
{{
  "summary": "一句话经营总览（含 2-4 个关键数字，必须来自快照）",
  "review": [
    {{"label": "指标名", "value": <数字>, "unit": "单位", "change": "环比描述"}}
  ],
  "todo": [
    {{"priority": "high|medium", "title": "待办标题（含关键数字）", "reason": "为什么今天该处理（引用快照事实）",
     "link": "/after-sales?status=pending|/orders?status=confirmed|/products?low_stock=true|/knowledge",
     "metrics": [{{"key": "快照指标key", "value": <数字>}}]}}
  ],
  "risks": [
    {{"title": "风险标题", "detail": "风险说明（引用快照事实）", "severity": "high|medium",
     "metrics": [{{"key": "快照指标key", "value": <数字>}}]}}
  ],
  "suggestions": [
    {{"title": "建议标题", "detail": "建议说明（引用快照事实）",
     "metrics": [{{"key": "快照指标key", "value": <数字>}}]}}
  ]
}}

铁律：
1. **只允许使用快照中出现的数字与事实**，禁止编造任何数字、比例、结论；
2. todo/risks/suggestions 每条必须带 metrics 引用（key 必须来自快照的 key，value 必须与快照一致）；
3. todo 只选「今天真正需要人处理」的 2-5 条，按优先级排序；无待办时 todo 返回空数组；
4. 数字为 0 或不存在的事项不要写进简报（避免噪音）；
5. review 只放快照中的核心经营指标（3-6 项）。
"""


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出中容错抽取 JSON 对象。"""
    if not text:
        return None
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    brace = re.search(r"(\{.*\})", text, re.S)
    if brace:
        try:
            return json.loads(brace.group(1))
        except json.JSONDecodeError:
            pass
    return None


def _as_list(raw: Any) -> List[Dict[str, Any]]:
    return [x for x in (raw or []) if isinstance(x, dict)]


def _clean_metrics(raw: Any) -> List[Dict[str, Any]]:
    """清洗 metrics 引用：只保留 key/value 均非空的条目，value 归一化为数字。"""
    result = []
    for m in _as_list(raw):
        key = str(m.get("key") or "").strip()
        value = m.get("value")
        if not key:
            continue
        try:
            if isinstance(value, bool):
                continue
            num = float(value)
        except (TypeError, ValueError):
            continue
        result.append({"key": key[:64], "value": num})
    return result


def _clean_items(raw: Any, max_items: int) -> List[Dict[str, Any]]:
    """清洗 todo/risks/suggestions：只保留 title 非空 + 至少一个 metrics 引用的条目。"""
    result = []
    for item in _as_list(raw)[:max_items * 2]:
        title = str(item.get("title") or "").strip()
        metrics = _clean_metrics(item.get("metrics"))
        if not title or not metrics:
            continue
        result.append({
            "priority": str(item.get("priority") or "medium")[:16],
            "title": title[:200],
            "reason": str(item.get("reason") or "")[:300],
            "detail": str(item.get("detail") or "")[:300],
            "severity": str(item.get("severity") or "medium")[:16],
            "link": str(item.get("link") or "")[:128],
            "metrics": metrics[:5],
        })
        if len(result) >= max_items:
            break
    return result


def sanitize_briefing(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """清洗/归一化 LLM 输出（保留结构，数字由 admin-api 校验层最终对账）。"""
    if not raw:
        return None
    summary = str(raw.get("summary") or "").strip()[:300]
    review = []
    for item in _as_list(raw.get("review"))[:8]:
        label = str(item.get("label") or "").strip()[:64]
        if not label:
            continue
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        review.append({
            "label": label,
            "value": value,
            "unit": str(item.get("unit") or "")[:16],
            "change": str(item.get("change") or "")[:64],
        })
    return {
        "summary": summary,
        "review": review,
        "todo": _clean_items(raw.get("todo"), MAX_TODO_ITEMS),
        "risks": _clean_items(raw.get("risks"), MAX_RISK_ITEMS),
        "suggestions": _clean_items(raw.get("suggestions"), MAX_SUGGESTION_ITEMS),
    }


def _truncate_snapshot(snapshot_text: str) -> str:
    if len(snapshot_text) <= MAX_SNAPSHOT_CHARS:
        return snapshot_text
    ellipsis = "\n……（中间省略）……\n"
    budget = MAX_SNAPSHOT_CHARS - len(ellipsis)
    head = snapshot_text[: int(budget * 0.7)]
    tail = snapshot_text[-int(budget * 0.3):]
    return head + ellipsis + tail


async def generate_briefing(snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """根据聚合指标快照生成四区块简报（异常降级返回 None，不编造数据）。

    snapshot 结构：{"metrics": {key: value, ...}, "facts": [{...业务事实条目...}]}
    """
    if not snapshot:
        logger.warning("[briefing] 快照为空，跳过生成")
        return None
    try:
        snapshot_text = json.dumps(snapshot, ensure_ascii=False, default=str)
        snapshot_text = _truncate_snapshot(snapshot_text)
        prompt = (
            f"{BRIEFING_SYSTEM_PROMPT}\n\n"
            f"<经营指标快照>\n{snapshot_text}\n<快照结束>\n\n"
            "请输出简报 JSON。"
        )
        llm = LLMFactory.create_briefing_llm()
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content if isinstance(response.content, str) else ""
        raw = _extract_json_object(content)
        if raw is None:
            logger.warning("[briefing] LLM 输出无法解析为 JSON 对象，len={}", len(content))
            return None
        briefing = sanitize_briefing(raw)
        if briefing is None or not briefing["summary"]:
            logger.warning("[briefing] 清洗后简报为空")
            return None
        logger.info(
            "[briefing] 生成完成 todo={} risks={} suggestions={}",
            len(briefing["todo"]), len(briefing["risks"]), len(briefing["suggestions"]),
        )
        return briefing
    except Exception as e:
        logger.warning(f"[briefing] 生成失败，降级返回 None: {e}")
        return None
