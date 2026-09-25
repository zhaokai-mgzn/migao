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

依赖方向：本模块顶层只依赖标准库 `json` + `loguru`（与 `app/tools/*` 同款日志），
`app.tools.*` / `app.graph.skills.*` 单向依赖它，不制造跨层反向 import。

merge 后新增（F19/F22 侧，issue #4037）：`confirm_card_fields` 末尾追加订单**金额字段**，
口径单点 = `order_create.order_facts_of`。该依赖是**同层**（`app.tools` → `app.tools`）、
**函数级**（调用期才 import，不参与模块导入）+ 失败非致命，故不改变上面的依赖方向，
也不触碰 `test_tools_layer_does_not_import_skill_layer`（只禁 `app.graph.*`）。
"""

import json
from decimal import Decimal, InvalidOperation

from loguru import logger

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
    # 改价预览（issue #5303 / A 档可逆写补回）：`before_price` 是**改前价声明**，
    # 卡片上必须与人话标签成对出现 —— 否则商家看到的只是一个孤零零的"价格"，
    # 「改前 → 改后」的"改前"整个缺失（= 没有预览就让人确认改钱）。
    "before_price": "改前价",
    # 批量上下架预览（issue #5314）：与 `before_price` **同一形态的镜像** ——
    # 批量 `product_status` 的预览必须成对呈现「改前状态 → 改后状态」，
    # 而 `old_value` 同时是撤销（revert）的唯一依据 ⇒ 卡片上不能只出现改后状态。
    "before_status": "改前状态",
}

#: 改价预览里 `price` 的语义是**改后价**。仅在 `before_price` 在场时生效
#: （其余工具如 `product_manage` 的 `price` 仍是「价格」—— 口径只对改价这一对收窄）。
_PRICE_AFTER_LABEL = "改后价"

#: 同款镜像（issue #5314 的批量上下架）：`status` 在 `before_status` 在场时读作**改后状态**。
#: 判据必须在**本模块**（字段投影的单一源）里，否则批量预览就会另立第二份投影。
_STATUS_AFTER_LABEL = "改后状态"


def price_preview_missing(args: dict) -> str:
    """改价写调用的**预览前置**判据（单一源，issue #5303）：合规返回 ""，否则返回缺失原因。

    `price`（改后价）在场而 `before_price`（改前价）缺席 ⇒ 确认卡只能呈现"改后"，
    "改前 → 改后"从未被展示过 ⇒ 写工具 fail-closed（禁止无预览直接写）。

    两个消费方共用本函数，避免"两侧各写一份口径"漂移：
      · 写工具 `product_update` / `sku_update` 的执行前校验；
      · 门禁话术 `base_skill._confirm_card_fields_hint`（告诉模型下一步该补什么）。
    """
    a = args or {}
    if a.get("price") is None:
        return ""
    if a.get("before_price") is None:
        return "本次改价没有带 before_price（改前价）"
    return ""


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
    # 金额字段（issue #4037 / F22）**追加在末尾**：改前投影只有 商品/数量，卡上写多少钱
    # 全凭模型自由发挥 ⇒ "卡上的钱"没有机器可读的那一份，¥498 的卡配 ¥133.80 的落库
    # 无人发现。口径单点 = `order_create.order_facts_of`。
    # ⚠️ 只在**金额算得出来**时追加（每行都有数量与单价），否则会渲染出顾客可见的
    # 「小计 0 / 合计 0」假金额（R5：禁止新增静默失效形态）。
    try:
        from app.tools.order_create import order_facts_of
        _facts = json.loads(order_facts_of(a) or "{}")
        _fitems = _facts.get("items") or []
        if _fitems and all(isinstance(it.get("qty"), (int, float))
                           and isinstance(it.get("price"), (int, float)) for it in _fitems):
            for label, key in (("单价", "price"), ("小计", "subtotal")):
                vals = [f"{it[key]:g}" for it in _fitems]
                fields.append({"label": label, "value": "、".join(vals[:3])})
            fields.append({"label": "合计", "value": f"{_facts['total']:g}"})
    except Exception as e:
        logger.debug(f"[confirm-card] 金额字段渲染跳过（非致命）: {e}")
    if not fields:
        # 控制键是动作指令/路由元数据，不是"要执行的内容"，不进卡片回显
        # （issue #3882：action/operation/op/target_tool/target_action/params/
        #   component/title 等）；label 优先给可读中文（_CONFIRM_FIELD_LABELS），
        # 未登记键回退原键名。改价（issue #5303）：`before_price` 在场 ⇒ `price`
        # 渲染成「改后价」，与「改前价」成对（单点口径，见 `_PRICE_AFTER_LABEL`）。
        _after_label = (_PRICE_AFTER_LABEL if a.get("before_price") is not None else None)
        _status_after_label = (_STATUS_AFTER_LABEL if a.get("before_status") is not None else None)
        for key, value in a.items():
            if key in _CONFIRM_CARD_CONTROL_KEYS or value is None:
                continue
            if isinstance(value, (dict, list)):
                rendered = json.dumps(value, ensure_ascii=False, default=str)
            else:
                rendered = str(value)
            label = _CONFIRM_FIELD_LABELS.get(key, key)
            if key == "price" and _after_label:
                label = _after_label
            if key == "status" and _status_after_label:
                label = _status_after_label
            fields.append({"label": label, "value": rendered})
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


# ══════════ 「被确认的值」的按值核对（issue #5414）══════════
# 病根：确认记录此前只记**工具名**（`confirmed_write_tool`）⇒ 门禁证明的是"确认过某个工具"，
# 不是"看过哪个价"：商家点了价 A 的卡，写失败（记录未清），下一轮模型改价 B 照样被放行。
# 口径**不另立**：跨语言的唯一实现是 Java 侧 `AgentWriteValues.sameValue`（#5317 建），
# 本模块是它在 Python 侧的同语义投影；两侧各自的测试跑**同一份语料**
# `backend/admin-api/src/test/resources/agent-write-values-corpus.json` 钉住一致性。

#: 涉钱面**值事实**的字段集：与 `base_skill._card_only_confirmation` 的入面口径同源 ——
#: 声明 `before_price` 的改价工具取价对（`before_price` + `price`）；声明
#: `card_only_actions` 的批量动作取 `batch_id`（钱在批次行里，参数里只有批号）。
CARD_ONLY_VALUE_FIELDS = ("price", "before_price", "batch_id")

#: **按值**比对（数字不比字符串写法）的字段词。工具参数用 `price` / `before_price`，
#: 线上字段用 `basePrice`（Java `FIELD_BASE_PRICE`）—— 词不同、语义必须同一。
PRICE_FIELD_WORDS = frozenset({"price", "before_price", "basePrice"})


def same_value(field, given, current) -> bool:
    """两侧是否**同一个值** —— 语义与 Java `AgentWriteValues.sameValue` 逐条对齐。

      · 价格字段（`PRICE_FIELD_WORDS`）：按**值**比对（`10.0` 与 `10.00` 是同一个价）；
        非法数字 / 带空白 / 非有限数 ⇒ `False`（Java `BigDecimal` 同样直接抛 ⇒ 口径一致）；
      · 非价格字段：字面比对，**只 trim 左侧**（与 Java `given.trim().equals(current)` 一致）；
      · 任一侧缺失 ⇒ `False` —— **fail-closed**：绝不为"没法比对"放行。
    """
    if given is None or current is None:
        return False
    if field in PRICE_FIELD_WORDS:
        try:
            raw_left, raw_right = str(given), str(current)
            if any((ch.isspace() or ch == "_") for ch in raw_left + raw_right):
                # Java `BigDecimal(String)` 对空白/下划线**直接抛**；而 Python `Decimal`
                # 会**静默**吃掉它们（`Decimal(" 168") == Decimal("168")`）⇒ 不显式挡掉就是
                # 跨语言口径漂移（本单实测到的第一处，由共享语料当场抓到）。
                return False
            left, right = Decimal(raw_left), Decimal(raw_right)
        except (InvalidOperation, ValueError, TypeError):
            return False
        if not (left.is_finite() and right.is_finite()):
            return False
        return left == right
    return str(given).strip() == str(current)


def write_value_facts(args: dict) -> dict:
    """写调用参数 → 「本次要执行的值」清单（只取 `CARD_ONLY_VALUE_FIELDS` 里在场的字段）。

    缺字段**不进清单**（不是"记一个空值"）：是否构成不符由 `values_match` 判 ——
    判定权只在一处，避免"两个函数各有一套缺失语义"。
    """
    a = args or {}
    return {f: a[f] for f in CARD_ONLY_VALUE_FIELDS if a.get(f) is not None}


def values_match(prior: dict, now: dict) -> bool:
    """「被确认的值」×「本次调用的值」**逐值核对**（issue #5414，放行侧唯一判据）。

    只核**本次调用带的值**：
      · 本次带的值在记录里缺失或不等 ⇒ `False`（只记了工具名的旧形态记录 ⇒ 涉钱面调用
        一律要求新卡 = fail-closed，不把"没法比对"当"对得上"）；
      · 本次值面上什么都没有（改名/上下架等非涉钱面调用）⇒ 不构成不符，交回既有语义
        （本单只收窄"值"这一维，不回退 #5317 的其它形态）。
    """
    for field, value in (now or {}).items():
        if not same_value(field, (prior or {}).get(field), value):
            return False
    return True


# ══════════ 卡值 ↔ 落库值的**覆盖面台账**（issue #4025 / F22 判据层收口）══════════
# F22 的病灶是「全系统无一处校验卡值与落库值一致」。判据**本体**已经存在
# （订单事实面 = `order_create.order_confirmation_verdict`；涉钱值面 = 上面的 `values_match`），
# 缺的是"**下一条落库路径**凭什么会被登记进这套比对" —— 没有面，新写路径默默落地、
# 零信号（本仓库反复批判的"未表态即静默"形态，同
# `tests/test_write_tool_confirm_gate_invariant.py` 的 `CONFIRM_GATE_EXEMPT_WRITE_TOOLS`）。
#
# 故：**每条会落库的写路径**必须在此显式表态 ——
#   ① `amount_guarded` / `value_guarded`：声明它归哪一套比对载体管辖；
#   ② `undecidable`：**结构上判不了**，必须带 `reason` + `issue` + `owner`（缺口不许匿名）。
# **未登记即红、陈旧条目即红、声明与源码不符即红** ——
# 判据 = `backend/ai-agent-service/tests/test_card_db_consistency_guard.py`。
#
# 名册**现取**（不写死条数）：`app/tools/*.py` 里 `read_only = False` 且有类属性 `name` 的文件。
# 复算：`python -m pytest tests/test_card_db_consistency_guard.py -q -s -k census`

#: 比对载体的两种谱系（值 = `stance` 的取值）。
AMOUNT_GUARDED = "amount_guarded"   # 订单事实串（手机号 + 逐行 名称/数量/单价/小计/加工费/合计）
VALUE_GUARDED = "value_guarded"     # 涉钱面**按值**比对（`CARD_ONLY_VALUE_FIELDS`）
UNDECIDABLE = "undecidable"         # 结构上无从比对（**显式登记**，不静默跳过）

#: 未登记进本台账的写路径在调用侧得到的判据 —— 与"一致"**绝不同形**（fail-loud）。
VERDICT_UNENROLLED = "unenrolled"

#: 写路径 → 表态。键集必须与源码面名册**双向相等**（缺一个 / 多一个都红）。
CARD_DB_CONSISTENCY_LEDGER: dict = {
    # ── ① 有比对载体 ─────────────────────────────────────────────────────────
    "order_create": {
        "stance": AMOUNT_GUARDED,
        "guard": "app.tools.order_create.order_confirmation_verdict",
        "anchor": "#4037",
        "note": "订单事实串与确认卡投影同口径；不一致 ⇒ 落库前拦截（拦截点 react_turn）",
    },
    "product_update": {
        "stance": VALUE_GUARDED,
        "guard": "app.tools.confirm_value.values_match",
        "anchor": "#5414",
        "note": "价对（before_price → price）按值比对；改价另受 #5303「改前→改后」预览前置约束",
    },
    "sku_update": {
        "stance": VALUE_GUARDED,
        "guard": "app.tools.confirm_value.values_match",
        "anchor": "#5414",
        "note": "声明 before_price ⇒ 与 product_update 同一套价对比对",
    },
    "product_batch_update": {
        "stance": VALUE_GUARDED,
        "guard": "app.tools.confirm_value.values_match",
        "anchor": "#5314",
        "note": "钱在批次行里、参数只带 batch_id ⇒ 按值比对的对象就是 batch_id（与 #5414 同口径）",
    },
    "product_manage": {
        "stance": VALUE_GUARDED,
        "guard": "app.tools.confirm_value.values_match",
        "anchor": "#5414",
        "note": "`price` 属 CARD_ONLY_VALUE_FIELDS ⇒ 建品调用带该字段即入按值比对（该比对与工具无关）",
    },
    # ── ② 结构上不可判定（逐条给理由，**不静默跳过**）──────────────────────────
    "order_manage": {
        "stance": UNDECIDABLE,
        "anchor": "#4025",
        "issue": "#4025",
        "owner": "订单域写路径 owner（order_manage）",
        "reason": "退款走 `refund_amount`，**不在** CARD_ONLY_VALUE_FIELDS（price/before_price/"
                  "batch_id）里 ⇒ 没有卡值比对载体：卡上的退款金额由模型自由书写，"
                  "机器侧没有可与之核对的那一份",
    },
    "aftersale_create": {
        "stance": UNDECIDABLE,
        "anchor": "#4025",
        "issue": "#4025",
        "owner": "售后域写路径 owner（aftersale_create）",
        "reason": "同上（`refund_amount` 无按值核对载体）；该工具的建单金额由服务端按订单实收派生",
    },
    "processing_item_manage": {
        "stance": UNDECIDABLE,
        "anchor": "#4882",
        "issue": "#4025",
        "owner": "加工域写路径 owner（processing_item_manage）",
        "reason": "参数面已无金额字段（加工项单价 / 计价方式随 #4882 整体移除，"
                  "快照键族收缩为 id/name/quantity/unit）⇒ 无值可比；加工费只在订单面有载体",
    },
    "processing_order_generate": {
        "stance": UNDECIDABLE,
        "anchor": "#4025",
        "issue": "#4025",
        "owner": "加工域写路径 owner（processing_order_generate）",
        "reason": "批量生成加工单：参数只有 `order_ids`，金额（加工费）在订单行里；"
                  "且该动作由**已确认流程派生**（订单 confirmed → producing）⇒ 无卡值可核对",
    },
    "processing_order_update": {
        "stance": UNDECIDABLE,
        "anchor": "#4025",
        "issue": "#4025",
        "owner": "加工域写路径 owner（processing_order_update）",
        "reason": "参数面（id/action/processor/expected_delivery_date/reason）无金额字段"
                  "⇒ 无值可比对",
    },
    "human_handoff": {
        "stance": UNDECIDABLE,
        "anchor": "#5247",
        "issue": "#5247",
        "owner": "客服域写路径 owner（human_handoff）",
        "reason": "工具已退场（deprecated、不在 create_default_registry、不在任何 skill 工具集）"
                  "⇒ 无活着的落库路径；条目保留以对齐**源码面**名册口径"
                  "（与 tests/test_write_audit_action_semantics.py 的 WRITE_TOOL_INVENTORY 同口径）",
    },
}


def _undecidable_verdict(tool_name: str, stance: str, reason: str) -> dict:
    """不可判定形态的统一构造（`confirmed` / `actual` 留空 = 两侧都没得比）。"""
    return {"tool": tool_name, "stance": stance, "verdict": UNDECIDABLE,
            "reason": reason, "confirmed": "", "actual": ""}


def card_db_verdict(tool_name: str, *, args: dict = None,
                    prior_order_facts: str = "",
                    prior_values: dict = None) -> dict:
    """「卡上给用户看的值」× 「真正要落库的值」——**逐路径判据分发**（issue #4025 / F22）。

    Returns:
        dict: `{"tool", "stance", "verdict", "reason", "confirmed", "actual"}`；
        `verdict` 取 match / mismatch / undecidable / **unenrolled**。

    • 未登记进台账的写路径 ⇒ `unenrolled`（**绝不**返回 match）：台账漏登记的路径
      在**调用侧**也拿不到"绿"，与判据侧的"未登记即红"两侧同时兜住。
    • 分发**不另立口径**：`amount_guarded` 走 `order_create.order_confirmation_verdict`，
      `value_guarded` 走本模块的 `values_match`（与放行侧同一实现）。
    """
    entry = CARD_DB_CONSISTENCY_LEDGER.get(str(tool_name or ""))
    if entry is None:
        return {
            "tool": str(tool_name or ""), "stance": "", "verdict": VERDICT_UNENROLLED,
            "reason": (f"写落库路径 {tool_name} 未登记进卡值↔落库比对台账（F22 类级元守卫）"
                       f"⇒ 判为**未覆盖**，不视为一致；请登记比对载体或登记为不可判定"),
            "confirmed": "", "actual": "",
        }
    stance = entry.get("stance")
    if stance == AMOUNT_GUARDED:
        from app.tools.order_create import order_confirmation_verdict
        return {"tool": tool_name, "stance": stance,
                **order_confirmation_verdict(args or {}, prior_order_facts)}
    if stance == VALUE_GUARDED:
        from app.tools.order_create import (
            ORDER_VERDICT_MATCH, ORDER_VERDICT_MISMATCH, ORDER_VERDICT_UNDECIDABLE,
        )
        now = write_value_facts(args or {})
        if not now:
            return _undecidable_verdict(
                tool_name, stance,
                f"本次调用不带涉钱面值字段（CARD_ONLY_VALUE_FIELDS={CARD_ONLY_VALUE_FIELDS}）"
                f"⇒ 本次没有可比对的值")
        prior = {k: v for k, v in (prior_values or {}).items() if k in now}
        if not prior:
            return _undecidable_verdict(
                tool_name, stance,
                "会话里没有这张卡的**值**快照（旧形态记录 / 未点卡）⇒ 无从比对")
        if values_match(prior, now):
            return {"tool": tool_name, "stance": stance, "verdict": ORDER_VERDICT_MATCH,
                    "reason": f"本次要落库的值与顾客点过的卡上的值逐项一致：{now}",
                    "confirmed": json.dumps(prior, ensure_ascii=False, sort_keys=True),
                    "actual": json.dumps(now, ensure_ascii=False, sort_keys=True)}
        return {"tool": tool_name, "stance": stance, "verdict": ORDER_VERDICT_MISMATCH,
                "reason": (f"涉钱面被拦截：本次要落库的值与顾客点过的**卡上的值**不一致。"
                           f"卡上是 {json.dumps(prior, ensure_ascii=False, sort_keys=True)}，"
                           f"本次是 {json.dumps(now, ensure_ascii=False, sort_keys=True)}。"
                           f"（价面字段按**值**比对，10.0 与 10.00 是同一个价。）"
                           f"确实要改，就**重新发一张确认卡**让顾客再点一次。"),
                "confirmed": json.dumps(prior, ensure_ascii=False, sort_keys=True),
                "actual": json.dumps(now, ensure_ascii=False, sort_keys=True)}
    if stance == UNDECIDABLE:
        return _undecidable_verdict(
            tool_name, stance,
            str(entry.get("reason") or "已登记为不可判定（台账未写理由 ⇒ 由判据判红）"))
    # 台账里出现了未定义的 stance ⇒ 不静默（判据侧同样会红）
    return _undecidable_verdict(
        tool_name, str(stance or ""),
        f"台账条目 {tool_name} 的 stance 不认识：{stance!r} ⇒ 判为不可判定")