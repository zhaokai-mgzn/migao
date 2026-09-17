"""确认卡 `confirmValue` 的**单一派生平**（issue #4054；源头是「关联 #4043」的 S1 条）。

为什么要单独立模块：这个值有**两个消费方**，此前**各写一份**派生逻辑 ——

  · `app/tools/interact.py` 的 confirm 分支 —— 顾客**看到**的那张卡、点击后原样回传的原文；
  · 门禁侧（`app/api/chat.py` 的补卡、`execution/finalize_turn.py` 的 8.3b 补卡、
    `base_skill._is_card_confirm_value` 的比对基准值）——
    判据是「用户消息**精确等于**最近一次确认卡的 `confirmValue`」。

任一侧改一行（前缀 / 分隔符 / 排序口径），门禁与卡值就漂移 ⇒ **顾客明明点了卡仍判「未确认」**
⇒ 确认死循环、写操作落不了库；而两侧各自自洽 ⇒ **没有任何测试会红**。

故：派生逻辑**只此一处**；`app/graph/skills/base_skill.py` 原样再导出同名符号
（既有 import 路径零改动）。算法**逐字搬迁**、未改口径 —— 逐字节等价证据见
`tests/test_tools_confirm_value.py`。

依赖方向：本模块是**叶子**（只依赖标准库 `json`），`app.tools.*` / `app.graph.skills.*`
单向依赖它，不制造跨层反向 import。
"""

import json

# 控制键：动作指令 / 路由元数据，不是"要执行的内容"，不进卡片回显。
_CONFIRM_CARD_CONTROL_KEYS = frozenset({
    "action", "operation", "op", "target_tool", "target_action",
    "params", "component", "title",
})

# B 端写参数 → 卡片字段的可读 label（未登记键回退原键名）
_CONFIRM_FIELD_LABELS = {
    "product_id": "商品ID",
    "item_id": "加工项ID",
    "category_id": "分类ID",
    "name": "名称",
    "price": "价格",
    "status": "状态",
    "description": "描述",
    "unit": "单位",
    "sku_code": "货号",
    "stock_quantity": "库存",
    "pricing_method": "计价方式",
}


def confirm_card_fields(args: dict) -> list:
    """从**写调用参数**整理出确认卡字段（只回显、不新增事实）。

    单一源：既供门禁话术的"字段骨架"提示，也供代码兜底**真正发卡**（issue #3445）。

    通用兜底（issue #3882）：订单字段提取为空时（B 端写参数如
    `product_manage.action=toggle_status` / `processing_item_manage.action=delete_item`
    没有 items/customer_* 键），把 args 中**除控制键之外**的键值对转成字段 ——
    否则 B 端被拦写操作产空字段 ⇒ `build_confirm_interact_xml` 返回 ""，卡发不出去。
    """
    a = args or {}
    fields = []
    items = a.get("items") or []
    if isinstance(items, list) and items:
        names = [str((it or {}).get("product_name") or (it or {}).get("name") or "")
                 for it in items if isinstance(it, dict)]
        names = [n for n in names if n]
        if names:
            fields.append({"label": "商品", "value": "、".join(names[:3])})
        qtys = [str((it or {}).get("quantity")) for it in items
                if isinstance(it, dict) and (it or {}).get("quantity") is not None]
        if qtys:
            fields.append({"label": "数量", "value": "、".join(qtys[:3])})
    for key, label in (("customer_name", "收货人"), ("customer_phone", "手机号"),
                       ("customer_address", "地址")):
        if a.get(key):
            fields.append({"label": label, "value": str(a.get(key))})
    if not fields:
        # 控制键是动作指令/路由元数据，不是"要执行的内容"，不进卡片回显
        # （issue #3882：action/operation/op/target_tool/target_action/params/
        #   component/title 等）；label 优先给可读中文（_CONFIRM_FIELD_LABELS），
        # 未登记键回退原键名。
        for key, value in a.items():
            if key in _CONFIRM_CARD_CONTROL_KEYS or value is None:
                continue
            if isinstance(value, (dict, list)):
                rendered = json.dumps(value, ensure_ascii=False, default=str)
            else:
                rendered = str(value)
            fields.append({"label": _CONFIRM_FIELD_LABELS.get(key, key),
                           "value": rendered})
    return fields


def confirm_value_for_fields(fields: list) -> str:
    """由字段**确定性**派生 confirmValue（issue #3406：字段顺序不影响取值）。

    **全仓唯一**的派生实现（issue #4054）：门禁比对的就是这个值，`interact` 工具下发的
    卡值也由它产出 —— 口径只此一处，不存在"两侧必须一致"这种要靠人记的约定。
    """
    facts = []
    for f in (fields or []):
        if isinstance(f, dict):
            facts.append(f"{f.get('label') or ''}={f.get('value') or ''}")
        else:
            facts.append(str(f))
    return ("确认：" + "；".join(sorted(facts))) if facts else ""