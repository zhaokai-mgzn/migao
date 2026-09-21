"""窗帘下单澄清清单引擎（issue #3986，M3-E）

现实行业订单大量信息靠默认约定兜底（2026-09 客户强调：「缺失即需求」）。
本模块把「澄清」做成**确定性清单驱动**：哪些必问、哪些可默认（行业【标】/
商家【默】/客户记忆三层）、缺省即报、矛盾拦截、轮次上限转复尺/人工。

真值源：docs/curtain-fabric-quote-rules.md + docs/curtain-production-rules.md。
纯函数、零 IO，可单测；接线（小布 skill 澄清话术 + 会话状态）在 M3-E 后半/PR。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# ── 采集项定义（L0~L7）──
# 字段语义：
#   id / label / ui(ask|form|choice|list) / required(必填才追问)
#   default_src: industry(行业【标】) / merchant(商家【默】) / customer(客户记忆) / none
#   default: 静态默认值；default_rule: 按已收集字段推导（width/curtain_type）
CHECKLIST: List[Dict[str, Any]] = [
    {"id": "intent", "label": "意图", "ui": "choice", "default_src": "none",
     "required": True, "note": "报价/量尺/售后/知识"},
    {"id": "room", "label": "房间", "ui": "list", "default_src": "none",
     "required": True, "note": "逐扇窗；房间名用户自定义（北次卧）"},
    {"id": "window_type", "label": "窗型", "ui": "choice", "default_src": "none",
     "required": False, "note": "平开/落地/飘窗/转角/L窗——转角影响开数与片数"},
    {"id": "curtain_type", "label": "帘型", "ui": "choice", "default_src": "industry",
     "default": "布帘", "note": "布/纱/帘头/罗马帘"},
    {"id": "width", "label": "宽度", "ui": "form", "default_src": "none",
     "required": True, "note": "必问；明轨量杆长/暗轨量轨长——量的是哪到哪要澄清"},
    {"id": "height", "label": "高度", "ui": "form", "default_src": "none",
     "required": True, "note": "必问；离地默认 1~3cm"},
    {"id": "open_count", "label": "打开方式", "ui": "choice", "default_src": "industry",
     "default_rule": "width", "note": "≤2.2m 默认单开 / >2.2m 双开 / >5m 四开（可覆盖）"},
    {"id": "craft", "label": "安装工艺", "ui": "choice", "default_src": "industry",
     "default": "韩褶", "note": "韩褶/打孔/四爪钩/穿杆"},
    {"id": "is_shaped", "label": "定型", "ui": "choice", "default_src": "industry",
     "default_rule": "curtain_type", "note": "布帘默认是/纱帘默认否/帘头是（面料红线：真丝等不耐高温须不定型）"},
    # 用料公式（issue #4873，用户 2026-09-21 需求）：**替换**退役的褶距问项 ——
    # 原话「移除订单的工艺规格中的褶距字段，同时加上用料公式字段；如果选择韩褶公式，
    # 那就自动算出褶数，如果选择的是褶倍数公式，那就展示是经济档还是标准档」。
    # industry 默认 = `pleat`（韩褶公式）；值域 = 算料引擎 `curtain_calc.FORMULA_LABELS`
    # 的键（pleat 褶数法 / fullness 倍数法）。算料档位（`craftTier`）**不进清单**：
    # 它由**算料配置**决定，不是顾客的回答项。
    {"id": "formula", "label": "用料公式", "ui": "choice", "default_src": "industry",
     "default": "pleat", "note": "韩褶公式（褶数法，自动算褶数）/ 褶倍数公式（倍数法，按档位算）"},
    # 是否对花（issue #4362，S1）：此前只作为 `fabric` 的 note 一笔带过 ⇒ **没人问、也没处落库**。
    # 真值源 §1 把它列为下单行要素（实证 `是否对花: 不对花`）；定宽买高时每幅加一个花距。
    {"id": "has_pattern", "label": "是否对花", "ui": "choice", "default_src": "none",
     "required": False, "note": "对花/不对花——定宽买高时每幅加一个花距（真值源 §1 下单行要素）"},
    {"id": "fabric", "label": "面料", "ui": "choice", "default_src": "merchant",
     "required": False, "note": "品类/预算/拼色/对花"},
    {"id": "accessory", "label": "辅料安装", "ui": "choice", "default_src": "industry",
     "default": "罗马杆明装", "note": "有无窗帘盒必问一次"},
    {"id": "trade", "label": "交易", "ui": "choice", "default_src": "none",
     "required": False, "note": "预算/交期/急单——可跳过"},
]

# ── 清单字段 → 下单行要素（order_items 的 craft spec，issue #4362 S1）────────────────
# **唯一映射点**：清单字段 id（snake_case，本模块的词汇）→ `processing_info` 顶层键
# （camelCase，订单/加工单两侧既有词汇，见设计文档 order-craft-spec-design.md §4.5）。
# 两个消费面（Java `OrderLineCraftFields` 的写/读面）都按这套键名走 ⇒ 映射只在这里写一次。
#
# 为什么必须有它：真值源 §1 的下单行要素此前「**问到了却不落库**」—— 清单把值收进 collector，
# 会话结束就没了；加工单只能靠加工项名**猜**部位/工艺（实证 V58：纱帘订单拿到布帘的 11 道工序，
# 工序与计件工资全错）。`window_type` 映射到 `corner` 是因为清单里「转角」就是窗型的一项
# （note 原话：「转角影响开数与片数」），**不另开一个重复的问项**。
CHECKLIST_TO_CRAFT_SPEC: Dict[str, str] = {
    "curtain_type": "curtainType",
    "craft": "craft",
    "open_count": "openCount",
    "is_shaped": "isShaped",
    "formula": "formula",
    "has_pattern": "hasPattern",
    "window_type": "corner",
    # 房间名（issue #4390 缺口④ 的残留）：清单里 `room` 是 **`required: True`** 的问项
    # （note 原话「逐扇窗；房间名用户自定义（北次卧）」）⇒ **每单必问**；而本表此前**没收它**
    # ⇒ 答案收进 collector 后**零消费者**、会话结束即丢 —— 这正是本映射表要消灭的
    # 「问到了却不落库」形态。
    # 为什么确定是**遗漏**而非有意排除：同文件对 `cutting_mode` 的排除**写了理由**，此处一字皆无；
    # 且 admin-api 的 `ProcessingOrderService.CRAFT_SPEC_SNAPSHOT_KEYS` **白名单里有 `"room"`**
    # （其 javadoc 明写「新键不加进这里就不会进快照」）⇒ 后端**已承诺**接这个键，是写侧没送。
    "room": "room",
}

# 算料输出键：**引擎是真值源**，清单只做透传（键名已是 `CALC_INFO_KEYS` 口径，不改名）。
# ⚠️ `cutting_mode`（加工类型）**不在**此表：它的取值由算料的 `formula_used` 决定，
# 在清单层「反推」就是第二份口径 ⇒ 登记为缺口，由生产端（order_create）按算料输出携带。
CALC_OUTPUT_PASSTHROUGH_KEYS = ("fullness", "fullness_actual", "pleat_count")

# 行业红线（真值源 §1/§8）
MIN_FULLNESS = 1.5          # 褶皱倍数下限
WIDTH_SINGLE_MAX = 2.2      # 单开默认上限（2026-09 客户实证：2.05m 单开）
WIDTH_FOUR_MIN = 5.0        # 四开默认下限
VALID_CRAFTS = ("韩褶", "打孔", "四爪钩", "穿杆")
ASK_PER_ROUND = 3           # 每轮最多问 2~3 个（认知负担上限）
MAX_ROUNDS = 3              # 追问轮次上限 → 转复尺/人工


def missing_required(collector: Dict[str, Any]) -> List[str]:
    """必填且未收集的字段 id 列表（尺寸缺失必须追问，不阻塞报价流程）。"""
    return [
        item["id"]
        for item in CHECKLIST
        if item.get("required") and item["id"] not in collector
    ]


def conflicts(collector: Dict[str, Any]) -> List[str]:
    """矛盾拦截：返回可读提示列表（机器可判，供小布回复/卡片标注）。"""
    warns: List[str] = []
    width = collector.get("width")
    open_count = collector.get("open_count")
    if width is not None:
        w = float(width)
        if open_count == 1 and w > WIDTH_SINGLE_MAX:
            warns.append(f"宽度 {w}m 超过 {WIDTH_SINGLE_MAX}m，建议双开（已为您预选，可改）")
        if open_count == 4 and w < WIDTH_FOUR_MIN:
            warns.append(f"宽度 {w}m 小于 {WIDTH_FOUR_MIN}m，四开偏窄，建议双开")
    pleats = collector.get("pleat_count")
    if pleats is not None and open_count in (2, 4) and int(pleats) % int(open_count) != 0:
        warns.append(f"褶数 {pleats} 无法被开数 {open_count} 整除，将取最近可行褶数")
    craft = collector.get("craft")
    if craft is not None and craft not in VALID_CRAFTS:
        warns.append(f"工艺「{craft}」不在可选范围（韩褶/打孔/四爪钩/穿杆）")
    if craft == "打孔" and pleats is not None:
        warns.append("打孔工艺按孔数计（不按褶数），褶数信息将被忽略")
    fullness = collector.get("fullness")
    if fullness is not None and float(fullness) < MIN_FULLNESS:
        warns.append(f"褶皱倍数 {fullness} 低于行业下限 {MIN_FULLNESS}，影响美观，请选择更高倍数")
    return warns


def merged_defaults(
    collector: Dict[str, Any],
    merchant_defaults: Optional[Dict[str, Any]] = None,
    customer_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """默认三层合成：客户记忆 > 商家【默】 > 行业【标】；只对未收集字段给默认。

    Args:
        collector: 已收集字段
        merchant_defaults: 商家配置默认（admin-web 设置）
        customer_profile: 客户档案（craft_profile JSON / craft_mode）
    Returns:
        {field_id: 默认值}（不含已在 collector 中的字段）
    """
    defaults: Dict[str, Any] = {}
    craft_profile = (customer_profile or {}).get("craft_profile") or {}
    for item in CHECKLIST:
        iid = item["id"]
        if iid in collector:
            continue
        if isinstance(craft_profile, dict) and iid in craft_profile:
            defaults[iid] = craft_profile[iid]   # 客户记忆（老客户习惯）
            continue
        if merchant_defaults and iid in merchant_defaults:
            defaults[iid] = merchant_defaults[iid]  # 商家【默】
            continue
        if item.get("default") is not None:
            defaults[iid] = item["default"]         # 行业【标】静态默认
        elif item.get("default_rule") == "width" and collector.get("width"):
            w = float(collector["width"])
            defaults[iid] = 4 if w > WIDTH_FOUR_MIN else (2 if w > WIDTH_SINGLE_MAX else 1)
        elif item.get("default_rule") == "curtain_type":
            ct = collector.get("curtain_type") or "布帘"
            defaults[iid] = ct != "纱帘"            # 布帘/帘头定型，纱帘不定型
    return defaults


def to_craft_spec(
    collector: Dict[str, Any],
    calc: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """清单已收集字段（+ 算料输出）→ **下单行要素**（`processing_info` 顶层键）。

    这是「问到了却不落库」的**唯一修法**（issue #4362，S1）：清单字段此前只活在会话里
    （collector 字典），会话结束即丢 ⇒ 加工单只能靠加工项名**猜**部位/工艺。

    口径（**只做搬运，不做业务判断**）：
    - 清单字段按 {@link CHECKLIST_TO_CRAFT_SPEC} 逐项改名（snake_case → camelCase）；
    - 算料输出（`fullness` / `fullness_actual` / `pleat_count`）**原样透传**（引擎是真值源）；
    - **缺项就不放这个键**（用户裁定「部位不是必填的」⇒ 本函数不补默认值、不猜、不推导）；
    - 已在 collector 里的键**不被算料输出覆盖**（顾客/商家填的优先于算出来的）。

    Args:
        collector: 已收集字段（清单 id → 值）
        calc: 算料引擎输出（可选；键名 = `CALC_INFO_KEYS` 口径）
    Returns:
        `processing_info` 顶层键的子集（camelCase 工艺规格键 + snake_case 算料输出键）
    """
    spec: Dict[str, Any] = {}
    for field_id, key in CHECKLIST_TO_CRAFT_SPEC.items():
        value = collector.get(field_id)
        if value is not None:
            spec[key] = value
    for key in CALC_OUTPUT_PASSTHROUGH_KEYS:
        value = (calc or {}).get(key)
        if value is not None and key not in spec:
            spec[key] = value
    return spec


def ask_batch(
    collector: Dict[str, Any],
    rounds: int,
    max_rounds: int = MAX_ROUNDS,
) -> Tuple[List[str], bool]:
    """每轮返回最多 ASK_PER_ROUND 个待问项；超轮次上限返回转复尺/人工话术。

    Returns: (待问项 label 列表 或 转交话术, 是否可继续)
    """
    missing = missing_required(collector)
    if not missing:
        return [], True
    if rounds >= max_rounds:
        return [
            "您方便的话可以约师傅上门量尺，或先按大概尺寸给您一个预算区间"
        ], False
    by_id = {item["id"]: item for item in CHECKLIST}
    return [by_id[i]["label"] for i in missing[:ASK_PER_ROUND]], True
