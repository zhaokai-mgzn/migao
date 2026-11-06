"""`<interact>` 协议解析（`chat.py` 切片单元，issue #8725 第三档）。

## 单一职责
模型幻觉输出的 `<interact>…</interact>` 伪代码块 → 交互载荷（choice / confirm / form）：
标签取值、块解析、整块剥离、**「本来没有块」与「有块但解析失败」的可区分**（后者留痕），
以及引用对齐过滤（只保留回复文本真正提到的商品）。

## 搬运口径
定义逐行搬自 `app/api/chat.py`（issue #3036 / #3959 / #3009 的注释逐行跟走）。
`chat.py` 保留同名 re-export ⇒ 既有调用点与外部 import 面零改动。
"""

import re
from typing import (
    Any,
    Dict,
    List,
    Optional,
)
from loguru import logger


# ──────────────── LLM 幻觉 <interact> XML 伪代码块剥离/解析（issue #3036 / UI-032） ────────────────

_INTERACT_XML_RE = re.compile(r"<interact>.*?</interact>", re.DOTALL)


def _extract_tag_value(xml_text: str, tag: str) -> Optional[str]:
    """从 XML 片段中提取首个 <tag>…</tag> 的文本（宽松匹配，允许空白与换行）"""
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml_text, re.DOTALL)
    if not m:
        return None
    return m.group(1).strip()


def _extract_tags(xml_text: str, tag: str) -> List[str]:
    """提取全部 <tag>…</tag> 片段（用于 options/fields/formFields 列表项）"""
    return [m.group(1).strip() for m in re.finditer(rf"<{tag}>(.*?)</{tag}>", xml_text, re.DOTALL)]


def _parse_interact_xml(block: str) -> Optional[Dict[str, Any]]:
    """解析 <interact>…</interact> XML 块为 SSE interactive payload。

    支持 LLM 幻觉输出的三种组件（与 interact 工具同协议）：
    - choice: <options><option><label>..</label><value>..</value><description>..</description></option>…</options>
    - confirm: <fields><field><label>..</label><value>..</value></field>…</fields> + confirmLabel/cancelLabel/confirmValue/cancelValue
    - form: <formFields><field><key>..</key><label>..</label><value>..</value>…</field>…</formFields> + submitLabel

    解析失败/字段缺失返回 None（调用方仅剥离 XML 块，不下发残缺 payload）。
    """
    component = _extract_tag_value(block, "component")
    if component not in ("choice", "confirm", "form"):
        return None
    title = _extract_tag_value(block, "title") or "请确认"
    payload: Dict[str, Any] = {"component": component, "title": title}

    if component == "choice":
        option_blocks = _extract_tags(block, "option")
        options = []
        for ob in option_blocks:
            label = _extract_tag_value(ob, "label")
            value = _extract_tag_value(ob, "value") or label
            if not label:
                continue
            option: Dict[str, str] = {"label": label, "value": value}
            desc = _extract_tag_value(ob, "description")
            if desc:
                option["description"] = desc
            options.append(option)
        if not options:
            return None
        payload["options"] = options

    elif component == "confirm":
        field_blocks = _extract_tags(block, "field")
        fields = []
        for fb in field_blocks:
            label = _extract_tag_value(fb, "label")
            value = _extract_tag_value(fb, "value")
            if label is None or value is None:
                continue
            fields.append({"label": label, "value": value})
        if not fields:
            return None
        payload["fields"] = fields
        for key in ("confirmLabel", "cancelLabel", "confirmValue", "cancelValue"):
            v = _extract_tag_value(block, key)
            if v:
                payload[key] = v

    elif component == "form":
        field_blocks = _extract_tags(block, "field")
        form_fields = []
        for fb in field_blocks:
            key = _extract_tag_value(fb, "key")
            label = _extract_tag_value(fb, "label")
            if not key or not label:
                continue
            field: Dict[str, Any] = {"key": key, "label": label}
            for sub in ("value", "placeholder"):
                v = _extract_tag_value(fb, sub)
                if v:
                    field[sub] = v
            req = _extract_tag_value(fb, "required")
            if req and req.lower() == "true":
                field["required"] = True
            form_fields.append(field)
        if not form_fields:
            return None
        payload["formFields"] = form_fields
        v = _extract_tag_value(block, "submitLabel")
        if v:
            payload["submitLabel"] = v

    return payload


def _strip_interact_xml(text: str) -> str:
    """剥离文本中全部 <interact>…</interact> 块（保留其余文本）"""
    return _INTERACT_XML_RE.sub("", text)


def _parse_interact_block_or_report(
    text: str, session_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """从文本中解析首个 <interact>…</interact> 块为 payload；本来没有块返回 None。

    issue #3959：**「本来没有块」与「有块但解析失败」必须可区分** —— 两者返回值都是 None，
    但后者意味着模型本想发卡却写残了。此前调用点无法区分，两者都走同一条
    `_strip_interact_xml` 路径 ⇒ 块被静默剥掉、不发卡、**零日志**（用户侧表现为
    「该弹的卡没了，只剩文字」，评测侧只能归因成「agent 不干活」）。
    故解析失败时打一条 warning 留痕；`_parse_interact_xml` 的 fail-closed 语义不变
    （仍不下发残缺 payload）。
    """
    m = _INTERACT_XML_RE.search(text)
    if not m:
        return None
    block = m.group(0)
    payload = _parse_interact_xml(block)
    if payload is None:
        # 只留截断片段（防大块刷爆日志），标记 [interact-xml] 便于稳定检索
        logger.warning(
            "[interact-xml] 解析失败，剥离前留痕（模型可能本想发卡）| "
            f"session={session_id} component={_extract_tag_value(block, 'component')} "
            f"len={len(block)} snippet={block[:120]!r}"
        )
    return payload


def _filter_products_by_reference(content: str, products: Any) -> List[Dict[str, Any]]:
    """引用对齐过滤：只保留回复文本中实际引用的商品（按 name/id 子串匹配）。

    背景（issue #3009 / case PR-018）：B 端黄金策「低库存清单」等分析型查询里，
    LLM 用 product_search 取数据做推断并在文本中给出筛选结论；此前的卡片把
    工具原始返回全量渲染，出现「文本 5 件、卡片 20 件」的两层皮。本函数在
    LLM 文本生成后按引用过滤，未被文本提及的商品一律不渲染。

    Args:
        content: LLM 最终回复文本（引用匹配依据）
        products: 商品管理，兼容裸数组与 card.data（{"products": [...]}）两种形态

    Returns:
        被文本引用的商品子集；文本为空或未引用任何商品时返回 []（不发卡）。
    """
    if not content:
        return []
    if isinstance(products, dict):
        products = products.get("products") or []
    if not isinstance(products, list):
        return []
    kept: List[Dict[str, Any]] = []
    for p in products:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "")
        pid = str(p.get("id") or "")
        if (name and name in content) or (pid and pid in content):
            kept.append(p)
    return kept
