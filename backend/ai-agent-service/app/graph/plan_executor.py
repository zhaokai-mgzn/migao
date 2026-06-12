"""
Product creation utility functions — smart defaults, category inference, field extraction.

P&E (Plan-and-Execute) 已移除。商品创建现在通过 ReAct + 完整 Tool Schema 处理。
本文件仅保留纯逻辑工具函数，不包含任何 Plan/状态机/流程控制。
"""

import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.llm import LLMFactory


# ── 中文字段名 → 英文 key 映射 ──

_FIELD_NAME_MAP = {
    "名称": "name", "商品名称": "name", "名字": "name",
    "价格": "price", "售价": "price", "单价": "price",
    "库存": "stock_quantity", "库存数量": "stock_quantity", "数量": "stock_quantity",
    "描述": "description", "详情": "description", "介绍": "description",
    "分类": "category_id",
    "货号": "sku_code", "商品货号": "sku_code", "编码": "sku_code",
    "售卖方式": "selling_methods", "销售方式": "selling_methods",
    "规格尺寸": "door_widths", "门幅": "door_widths", "尺寸": "door_widths",
    "单位": "unit", "计价单位": "unit",
    "品牌": "brand", "商标": "brand",
    "颜色": "colors", "色号": "colors",
    "图片": "images", "图片链接": "images", "图片URL": "images",
    "计价方式": "pricing_type", "定价方式": "pricing_type",
    "客户姓名": "customer_name", "联系人": "customer_name",
    "电话": "customer_phone", "手机号": "customer_phone", "手机": "customer_phone",
    "地址": "customer_address", "收货地址": "customer_address",
    "备注": "remark", "说明": "remark",
    "商品": "product_name", "产品": "product_name",
    "数量": "quantity", "个数": "quantity",
    "加工项": "processing_item_ids",
    "折扣": "discount", "优惠": "discount",
    "问题类型": "issue_type", "售后类型": "issue_type",
    "原因": "reason", "问题描述": "reason",
    "订单号": "order_no", "订单编号": "order_no",
}


# ── 分类推断 ──

_CATEGORY_KEYWORDS = {
    "窗帘": "窗帘布艺", "窗纱": "窗纱", "卷帘": "卷帘",
    "柔纱帘": "柔纱帘", "百叶": "百叶帘", "罗马帘": "罗马帘",
    "床品": "床品", "抱枕": "抱枕", "靠垫": "靠垫",
    "桌布": "桌布", "桌旗": "桌旗", "沙发垫": "沙发垫",
}


def infer_category_hint(product_name: str) -> str:
    """从商品名推断分类关键词"""
    for kw, cat in _CATEGORY_KEYWORDS.items():
        if kw in product_name:
            return cat
    return product_name[:4] if product_name else ""


def match_category_from_tree(tree: list, hint: str) -> Optional[dict]:
    """在分类树中匹配最接近的分类名"""
    best = None
    for node in tree:
        name = node.get("name", "")
        if hint in name or name in hint:
            return {"id": node.get("id", ""), "name": name}
        if re.search(hint[:2], name):
            best = best or {"id": node.get("id", ""), "name": name}
    return best


# ── 字段提取（LLM）──

async def extract_fields(user_text: str, fields: List[str], context: dict = None) -> Dict[str, Any]:
    """LLM 从自然语言中提取结构化字段"""
    if not fields or not user_text:
        return {}

    field_hints = []
    for f in fields:
        cn = next((k for k, v in _FIELD_NAME_MAP.items() if v == f), f)
        field_hints.append(f"  - {f} ({cn})")

    prompt = (
        f"从以下用户消息中提取字段值，返回纯 JSON:\n"
        f"用户消息: {user_text}\n\n"
        f"需要的字段:\n" + "\n".join(field_hints) + "\n\n"
        f"只输出 JSON，不要其他内容。未提及的字段不要编造。"
    )
    if context:
        prompt += f"\n已有上下文（不要重复已确定的值）: {json.dumps(context, ensure_ascii=False)}"

    try:
        raw = await LLMFactory.invoke_text_safe([
            SystemMessage(content="你是字段提取器。只输出 JSON。"),
            HumanMessage(content=prompt),
        ], enable_thinking=False)
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start:end + 1])
    except Exception as e:
        logger.warning(f"[utils] extract_fields failed: {e}")
    return {}


# ── 用户选择匹配 ──

def match_user_choice(user_msg: str, results: list) -> Optional[dict]:
    """从用户回复匹配查询结果中的选项（编号/名称/ID）"""
    if not results or not user_msg:
        return None
    nums = re.findall(r'\d+', user_msg)
    if nums:
        ids, names = [], []
        for n in nums:
            idx = int(n) - 1
            if 0 <= idx < len(results):
                item = results[idx]
                if "id" in item:
                    ids.append(item["id"])
                if "name" in item:
                    names.append(item["name"])
        if ids:
            return {"id": ids[0] if len(ids) == 1 else ids,
                    "name": names[0] if len(names) == 1 else names,
                    "ids": ids, "names": names}
    for item in results:
        name = item.get("name", "")
        if name and name in user_msg:
            return {"id": item.get("id"), "name": name}
    return None


# ── 智能默认值（同类商品统计）──

async def fetch_smart_defaults(
    category_id: str,
    category_name: str,
    tool_names: List[str],
    ctx,
) -> Dict[str, Any]:
    """查询同类商品，提取常见属性值"""
    from app.tools.registry import get_tool_registry, set_tool_context

    if "product_search" not in tool_names:
        return {}
    set_tool_context(ctx)
    registry = get_tool_registry()
    tool = registry.get_tool("product_search")
    if not tool:
        return {}

    try:
        result = await tool.execute(ctx, keyword=category_name, size=10)
        if not result.success or not result.data:
            return {}
        products = result.data.get("products") or result.data.get("items") or []
        if len(products) < 2:
            return {}

        sm_counter, dw_counter, unit_counter = {}, {}, {}
        prices, color_counter, pricing_counter = [], {}, {}
        spec_counter, brand_counter, proc_items = {}, {}, {}

        for p in products:
            for sm in (p.get("sellingMethods") or p.get("selling_methods") or []):
                if isinstance(sm, str) and sm:
                    sm_counter[sm] = sm_counter.get(sm, 0) + 1
            for dw in (p.get("doorWidths") or p.get("door_widths") or []):
                if isinstance(dw, str) and dw:
                    dw_counter[dw] = dw_counter.get(dw, 0) + 1
            unit = p.get("unit", "")
            if unit:
                unit_counter[unit] = unit_counter.get(unit, 0) + 1
            price = p.get("price")
            if price is not None:
                try:
                    prices.append(float(price))
                except (ValueError, TypeError):
                    pass
            colors = p.get("colors") or []
            if isinstance(colors, list):
                for c in colors:
                    name = c.get("colorName") or c.get("name") or str(c)
                    if name:
                        color_counter[name] = color_counter.get(name, 0) + 1
            pt = p.get("pricingType") or p.get("pricing_type") or ""
            if pt:
                pricing_counter[pt] = pricing_counter.get(pt, 0) + 1
            specs = p.get("specifications") or {}
            if isinstance(specs, dict):
                for sk, sv in specs.items():
                    spec_counter.setdefault(sk, {})[str(sv)] = spec_counter.get(sk, {}).get(str(sv), 0) + 1
            brand = p.get("brand", "")
            if brand:
                brand_counter[brand] = brand_counter.get(brand, 0) + 1
            for pi in (p.get("processingItems") or p.get("processingItemConfigs") or []):
                pid = pi.get("processingItemId") or pi.get("id")
                if pid and pid not in proc_items:
                    proc_items[pid] = pi.get("name", pid)

        total = len(products)
        threshold = max(1, int(total * 0.3))

        def top(counter, limit=5):
            return [k for k, v in sorted(counter.items(), key=lambda x: -x[1])[:limit] if v >= threshold]

        return {
            "category_name": category_name,
            "sample_count": total,
            "common_selling_methods": top(sm_counter),
            "common_door_widths": top(dw_counter),
            "common_unit": top(unit_counter, 1),
            "common_pricing_type": top(pricing_counter, 1),
            "common_colors": top(color_counter, 10),
            "common_brands": top(brand_counter, 3),
            "common_specifications": {sk: max(sv, key=sv.get) for sk, sv in spec_counter.items()},
            "common_processing_items": [{"id": pid, "name": name} for pid, name in list(proc_items.items())[:5]],
            "price_range": {"min": min(prices) if prices else None, "max": max(prices) if prices else None},
        }
    except Exception as e:
        logger.warning(f"[utils] Smart defaults failed: {e}")
        return {}


# auto_fill_category_and_defaults 已迁移到 ReAct:
# LLM 看到 category_manage/processing_item_query schema 后自行调用
# infer_category_hint + match_category_from_tree + fetch_smart_defaults 保留供未来使用
