"""出站整形：发什么卡 / 给顾客看什么字（`chat.py` 切片单元，issue #8725 第三档）。

## 单一职责
「模型与工具的原始结果 → 顾客真正收到的东西」这一段**唯一**的整形面：
- **发不发卡**：卡型判定（工具名 → 卡型）、门槛（空态/缺文案/缺图不许发）、订单卡归一（单/多单）；
- **给顾客看什么**：C 端脱敏（手机号）、双端内部路由清洗、卡片可见字段脱敏（协议值**不动**）；
- **文字声称**：模型把顾客指向一个不存在的控件时的判据与改写（收尾守卫的纯函数半边）。

不含流式时序、不含落库、不含会话归属 —— 那些在 `chat.py` 与 `app/api/chat_history.py`。

## 搬运口径
定义逐行搬自 `app/api/chat.py`（注释逐行跟走，`_CARD_*` 的正则口径一字未改）。
`chat.py` 保留同名 re-export ⇒ 既有调用点与外部 import 面零改动。
"""

import re
from typing import (
    Any,
    Dict,
    Optional,
)
from loguru import logger
from app.utils.route_hygiene import strip_internal_routes


def _detect_card_type(tool_name: str, result: Dict[str, Any]) -> Optional[str]:
    """
    根据 Tool 名称和结果检测应该发送的卡片类型
    
    Returns:
        Optional[str]: 卡片类型或 None
    """
    if tool_name == "product_search":
        return "product_list"
    elif tool_name == "product_detail":
        return "product_detail"
    elif tool_name == "marketing_poster":
        # 营销海报卡（issue #7351）：工具返回的 `data` 就是卡载荷
        # （`{product: {...}, copy: {title, selling_points}}`），前端渲染成 750×1000 PNG。
        return "marketing_poster"
    elif tool_name == "product_image_generate":
        # 商品图生成卡（issue #7541）：工具返回的 `data` 就是卡载荷
        # （`{image_url, model, product: {id, name, kind}}`），前端预览 + PC 下载 / 手机存相册。
        return "generated_image"
    elif tool_name in ("logistics_track", "customer_logistics_track"):
        return "logistics"
    elif tool_name in ("order_query", "customer_order_query"):
        return "order"
    elif tool_name == "curtain_calc":
        return "quotation"
    elif tool_name == "production_progress_query":
        # 生产进度卡（M4-G-3 / issue #3997 已交付的顾客端卡片）。
        # issue #4016 P14：此前**只有卡片、没有发射点** ⇒ 组件永不渲染
        # （「交付物在 main ≠ 能力可达」）。用户 2026-09-18 裁定走「补发射点」：该工具返回的
        # `data` 正是卡载荷（progress_percent / current_operation / expected_delivery_date / positions）。
        return "production_progress"
    elif tool_name == "payment_qrcode_query":
        # 收款二维码卡（M3-F-3 / issue #3990 已交付的顾客端卡片）。
        # issue #4085 第 1 项：与 production_progress 同构的「有卡片、零发射点」形态
        # （#4016 P14 当时以「工具层没有数据源」裁掉了 C 端渲染分支）——用户 2026-09-18
        # 裁定走「补发射点」：`payment_qrcode_query` 返回的 `data` 正是卡载荷
        # （{"payment_qrcodes": {"wechat": {...}, "alipay": {...}}}，见该工具 execute 返回段）。
        return "payment"
    elif tool_name == "batch_stock_query":
        # 批次账 / 省料度量卡（issue #5188）。工具返回的 `data` 就是卡载荷：
        # 四个 action 各自带 `action` 判别键 + **服务端读面原样透传**
        # （batches：批次行；distribution：四档；saving_board / saving_trend：
        # 省料度量），前端按 `action` 分支渲染，不重算任何米数/金额/占比。
        return "batch_stock"
    return None


def _should_send_card(tool_name: str, result: Dict[str, Any]) -> bool:
    """判断是否应该发送卡片事件"""
    if not result.get("success", False):
        return False
    
    # 商品搜索有结果时发送卡片
    if tool_name == "product_search":
        data = result.get("data", {})
        products = data.get("products", [])
        return len(products) > 0
    
    # 商品详情有结果时发送卡片
    if tool_name == "product_detail":
        data = result.get("data", {})
        return data.get("product") is not None

    # 营销海报（issue #7351）：**文案缺一不发卡** —— 载荷必须同时有商品事实与商家确认的文案，
    # 否则前端会渲染一张没有主标题的海报（「空头海报」= 误导）。
    if tool_name == "marketing_poster":
        data = result.get("data", {})
        if not isinstance(data, dict):
            return False
        copy = data.get("copy")
        return (
            isinstance(data.get("product"), dict)
            and isinstance(copy, dict)
            and bool(str(copy.get("title") or "").strip())
            and bool(copy.get("selling_points"))
        )
    
    # 商品图生成（issue #7541）：**成功且真有图才发卡** —— 失败或空图一律不发，
    # 否则前端会渲染一个空图片框（「说好了生成、却没有图」= 凭空承诺）。
    if tool_name == "product_image_generate":
        data = result.get("data", {})
        if not isinstance(data, dict):
            return False
        return bool(str(data.get("image_url") or "").strip())

    # 物流查询有结果时发送卡片
    # - B 端 logistics_track: 单笔物流（data.tracking_number）
    # - C 端 customer_logistics_track: 在途订单列表（data.logistics_list 非空；卡片取第一笔 data.logistics）
    if tool_name == "logistics_track":
        data = result.get("data", {})
        return data.get("tracking_number") is not None

    if tool_name == "customer_logistics_track":
        data = result.get("data", {})
        logistics_list = data.get("logistics_list")
        return isinstance(logistics_list, list) and len(logistics_list) > 0
    
    # 订单查询有结果时发送卡片（支持单订单和列表两种格式；C 端 customer_order_query 同规则）
    if tool_name in ("order_query", "customer_order_query"):
        data = result.get("data", {})
        has_order = data.get("order") is not None
        orders = data.get("orders")  # action=list 返回 orders 数组
        items = data.get("items")    # 兼容旧格式
        order_list = orders if isinstance(orders, list) else (items if isinstance(items, list) else [])
        has_list = len(order_list) > 0
        should_send = has_order or has_list
        logger.info(
            f"[chat/card] {tool_name} check | has_order={has_order} orders_count={len(order_list)} "
            f"should_send={should_send} data_keys={list(data.keys()) if isinstance(data, dict) else 'N/A'}"
        )
        return should_send

    # 算料报价有结果时发送报价单卡片
    if tool_name == "curtain_calc":
        data = result.get("data", {})
        return data.get("total") is not None

    # 生产进度有结果时发送进度卡（issue #4016 P14 补发射点）
    # 判据 = **工具契约事实**：`production_progress_query` 成功时保证 `data` 是非空 dict
    # （空 dict 走 success=False/NOT_FOUND 分支，见该工具第 145 行），且**无加工单也 success=true**
    # （0%/空工序是合法结果）⇒ 不能用「有工序」当判据，否则「暂无生产进度」空态永远看不到卡
    # （UI-045 明写「空态（无工序）显示『暂无生产进度』，不显示假进度、不空白」）。
    if tool_name == "production_progress_query":
        data = result.get("data", {})
        return isinstance(data, dict) and len(data) > 0

    # 收款码有结果时发送支付卡（issue #4085 第 1 项补发射点）
    # 判据 = **工具契约事实**：`payment_qrcode_query` 成功时保证 `data` 至少有
    # `payment_qrcodes` 一个键（查询失败/权限不足走 success=False，见该工具 execute），
    # 且**商家没配收款码也是 success=true**（空 dict 是合法答案）⇒ 不能用「有码」当判据，
    # 否则「商家暂未设置收款码」空态永远看不到卡（ST-011 明写「无收款码时展示降级提示
    # （PaymentCard 空态）」）。
    if tool_name == "payment_qrcode_query":
        data = result.get("data", {})
        return isinstance(data, dict) and len(data) > 0

    # 批次 / 省料卡（issue #5188 补发射点）
    # 判据 = **工具契约事实**：`batch_stock_query` 成功时 `data` 必带 `action` 判别键
    # （四个 action 都有；失败走 success=False，见该工具 execute）——**空结果也要发卡**：
    # 「无数据」是合法答案，且必须看得见（判据 5：无数据不冒充 0，也不许静默什么都不显示）。
    if tool_name == "batch_stock_query":
        data = result.get("data", {})
        return isinstance(data, dict) and bool(data.get("action"))

    return False


def _normalize_order_card_data(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """归一化 order 卡片载荷，避免前端渲染出空「订单」盒子。

    根因（会话反馈）：order_query(action=list) 的 Tool 结果永远返回
    {orders: [...], total, page, ...} 容器；此前原样作为 card 数据下发，
    前端 OrderCard 只认 data.order，取不到 orderNo 后渲染出只剩
    「订单」二字的空盒子（无法理解、无法点击）。

    归一化规则：
      - data.order（单订单）           → {"order": <order>}（原样）
      - data.orders / data.items 单条  → {"order": <order>}（前端按单订单渲染）
      - data.orders / data.items 多条  → {"orders": [...]}（前端按列表渲染）
      - 无有效订单                      → None（不下发卡片）
    """
    if not isinstance(data, dict):
        return None

    if data.get("order") is not None:
        return {"order": data["order"]}

    order_list = data.get("orders")
    if not isinstance(order_list, list):
        order_list = data.get("items")  # 兼容旧格式
    if not isinstance(order_list, list) or len(order_list) == 0:
        return None

    if len(order_list) == 1:
        return {"order": order_list[0]}
    return {"orders": order_list}


def _card_payload(tool_name: str, result: Dict[str, Any]) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """统一计算要下发的卡片类型与载荷。

    Returns:
        (card_type, data)：不需要下发时返回 (None, None)。
        order 卡片做归一化（单订单→{"order": ...}，多订单→{"orders": [...]}）。
    """
    card_type = _detect_card_type(tool_name, result)
    if not card_type or not _should_send_card(tool_name, result):
        return None, None

    data = result.get("data", {})
    if card_type == "order":
        data = _normalize_order_card_data(data)
        if data is None:
            return None, None
    return card_type, data

def _mask_for_customer(text: str, context) -> str:
    """C 端**出站文本**统一脱敏（issue #3379 P2-2 的真正收敛点）。

    为什么必须在流式桥这一层：C 端回复有**两个生产者** ——
      · `final_answer`（技能收尾，已在 base_skill 脱敏）；
      · **`text_before_tools`**（模型调工具前的中间文本，由本文件直接流给顾客）。
    实测 OR-017 R2（run 34735574206，复现型失败）泄露的正是中间文本那条路径，
    在收尾处脱敏永远追不上已经流出去的文本。故把脱敏放到**唯一出站口**，
    覆盖全部文本路径（中间文本 / 收尾文本 / 落库历史）。
    B 端（商家/客服）不脱敏 —— 客服要照实号码联系顾客。
    """
    if str(getattr(context, "role", "") or "").lower() != "customer" or not text:
        return text
    try:
        from app.utils.pii_mask import mask_pii
        return mask_pii(text)
    except Exception:
        return text


def _sanitize_outbound_text(text: str, context) -> str:
    """**出站文本单一收口**：C 端脱敏 + 双端内部路由清洗（issue #7236）。

    与 `_mask_for_customer` 的分工：脱敏只对 C 端（B 端客服要照实号码联系顾客），
    内部路由清洗**双端都要**——商家同样看不懂技术路径原文（2026-10-18 实测：黄金策回复
    『发货需要在后台「销售订单」页…找到该订单』把前端路由当成了展示文案；
    页面 2026-10-20 由「订单列表」正名为「销售订单」，issue #7354）。追加这一层
    **不改变**脱敏语义（先脱敏、后清洗；清洗只动前端路由 token，不动手机号掩码）。

    清洗点必须在下发/落库**之前**：SSE 是边流边发，收尾再清追不上已经流出去的气泡；
    落库侧在写前清洗 ⇒ 历史回放（读库）不会把路由再带出来。
    """
    return strip_internal_routes(_mask_for_customer(text, context))


def _mask_card_for_customer(data: dict, context) -> dict:
    """**出站**卡片脱敏（issue #3379）：顾客看到的卡片字段脱敏，模型上下文保持原值。

    与工具层脱敏的区别（本轮实测踩到的坑）：
      · 工具层脱敏 → 污染模型上下文与 `confirmValue`（顾客回传要精确匹配）→ 流程被搞坏；
      · 出站层脱敏 → 只有顾客看到脱敏值，模型/状态/匹配链全程用真值。
    只打**可见文本**：title / fields.label|value / formFields.label|value / options.label；
    `options[].value` 与 `confirmValue` 是协议值，**不动**（回传要靠它们）。
    """
    if str(getattr(context, "role", "") or "").lower() != "customer" or not isinstance(data, dict):
        return data
    try:
        from app.utils.pii_mask import mask_pii
    except Exception:
        return data
    out = dict(data)
    if isinstance(out.get("title"), str):
        out["title"] = mask_pii(out["title"])

    def _items(items, keys):
        res = []
        for it in items or []:
            if not isinstance(it, dict):
                res.append(it)
                continue
            node = dict(it)
            for k in keys:
                if isinstance(node.get(k), str):
                    node[k] = mask_pii(node[k])
            res.append(node)
        return res

    # confirm 卡：fields[].value 是**纯展示**（点击回传的是 confirmValue）→ 可脱敏
    if isinstance(out.get("fields"), list):
        out["fields"] = _items(out["fields"], ("label", "value"))
    # ⚠️ form 卡：**只脱敏 label，绝不碰 value**（issue #3379 关键修正）
    # 前端提交表单会把所有字段值原样回传 —— 出站脱敏 value 等于让顾客提交回
    # `138****8000`：CI 实证 `validate_input({"customer_phone": "138****8000", …})`
    # → **订单会用掩码号码创建**，比"明文回显"严重得多。
    if isinstance(out.get("formFields"), list):
        out["formFields"] = _items(out["formFields"], ("label",))
    if isinstance(out.get("options"), list):
        out["options"] = _items(out["options"], ("label",))
    return out


# 收尾守卫（issue #3929 → #3967 → #4013 A7）：模型文本把顾客**指向一个控件**，但本轮
# 既没发交互载荷、也没调 interact 工具 ⇒ 顾客侧无卡可点（生产实证：黄金策 flash 频繁
# 只说「请点下方确认卡片」而不发卡）。命中时把声称片段改写为「回复『确认』」纯文本指引，
# 只影响落库/后续上下文文本（assistant_content），full_response 原值不动。
#
# 判据主体（#4013 A7）= **事实 × 意图**：
#   · 事实：本轮确实没卡 —— `last_interactive_payload is None` + 本轮无 `interact` 调用
#     （调用点显式命名 `_card_absent`；判据不再兼职回答"这轮到底发没发卡"）；
#   · 意图：文本把顾客指向控件 —— ① 控件手势（纯文本做不到的动作）/ ② 动作 ⟷ 控件实物
#     近邻 / ③ 交付声称（「表单已发出」）/ ④ 交付声称 + 要求回复『确认』（协议事实）。
# 刻意**不再用整句措辞语料**（旧 `_CARD_CLAIM_PHRASES` 靠"逐字喂"兜边界 —— 全句不含
# 「卡片/卡」的措辞必然漏检：2026-09-17 残留 2/2「开单表单已发出」「…回复『确认』已发出」
# 三条判据全不命中，顾客看到的"已发出"背后没有可点控件）。判据改绑**结构关系**后，
# 新措辞自动覆盖：「表单已发出」「请点击选择（可多选）」「勾选加工项」都不必再进语料。
#
# 适用域：仅本文件收尾守卫（`_agent_stream_to_sse` 落库 `save_message` 之前）。
# 不适用域（负例，`tests/test_api_chat_helpers.py` 钉住）：合法提及（「请查看上方结果卡片」
# 「下方列表」）与**可用文字完成**的动作（「请您选择需要的加工项」）不得命中。
# 误判代价可控（只在「本轮确实没发卡」时生效，最坏是改写话术），且**补卡分支严格 gated**
# （见 _pending_confirm_action / _reissue_confirm_card），不得凭空造卡。
_CARD_ACTION_WORDS = "点击|点选|勾选|选择|点"
# ⚠️ 「卡」不得越过**颜色词**：布艺域高频词「卡其色」（用户 2026-10-19 报障的形态）里也有
# 「卡」⇒ 裸 `卡` 会让「选择卡其色」被判成「指向卡片」、进而被改写成「回复『确认』其色」。
# 用负向前瞻排除「卡其」、用**后顾**排除「色卡」（布艺域另一个高频词：语料里 16 处「色卡建品」）
# —— 否则「请选择色卡上的米白色」会被改成「请回复『确认』上的米白色」。其余含「卡」的词仍按卡片名词处理。
_CARD_NOUNS = "卡片|(?<!色)卡(?!其)"
# 控件实物名词（本系统真会渲染成可点控件的实体）：「表单已发出」形态**不含"卡"字**
_CARD_WIDGET_NOUNS = "表单|卡片|(?<!色)卡(?!其)|控件|按钮|选项"
_CARD_DELIVERED_VERBS = "发出|调出|弹出|展示|生成|下发|推送|提供|显示"
# 近邻窗口（字）：`(?:动作){0,8}` 的量词作用在**零宽分组**上 ⇒ 等价"零个动作词"，
# 故必须写成**有界通配** `[\s\S]{0,8}`（历史踩坑：写成量词后只要句中出现卡片实物就命中）。
_CARD_ACTION_GAP = 8
# ① 控件手势：纯文本回复**做不到**的动作（点/点击/勾选）——刻意不含「选择/确认」，
#    它们可用文字完成（负例「请您选择需要的加工项」不得命中）。
#    「点确认/点确定」是手势的省略写法（= 点确认按钮），既有「请点确认。」形态。
# ⚠️ 「点确认」也可能是**页面动作**（「点击确认收货」/「点确认订单」——用户 2026-10-19 报障
# 的形态之一）：那不是"指向聊天卡片"，不该被改写成「回复『确认』」+ 追加"确认卡片未显示"提示。
# 负向前瞻排除已知的**业务宾语**（收货/签收/订单/付款/支付/发货/到货/评价）；「点确认。」这类
# 无宾语的形态仍然命中（它才真是"请点确认按钮"的省略写法）。
_CARD_POINT_RE = re.compile(
    r"点(?:击)?(?:确认|确定)(?!收货|签收|订单|付款|支付|发货|到货|评价)")
_CARD_GESTURE_RE = re.compile("|".join((
    rf"点击[\s\S]{{0,4}}?(?:选择|多选|选项|加工项|表单|按钮|{_CARD_NOUNS})",
    rf"勾选[\s\S]{{0,4}}?(?:加工项|选项|{_CARD_NOUNS})",
    _CARD_POINT_RE.pattern)))
# ② 动作词 ⟷ 控件实物**近邻共现**（窗口 ≤ _CARD_ACTION_GAP 字、双向）
#    ——「请点下方确认卡片」「点击上方卡片勾选加工项」「选择卡片里的选项」。
#    动作词表**有意小**（点/点击/点选/勾选/选择）："核对/查看/打开"不算指向控件。
_CARD_ACTION_RE = re.compile(
    rf"(?:{_CARD_ACTION_WORDS})[\s\S]{{0,{_CARD_ACTION_GAP}}}?(?:{_CARD_NOUNS})"
    rf"|(?:{_CARD_NOUNS})[\s\S]{{0,{_CARD_ACTION_GAP}}}?(?:{_CARD_ACTION_WORDS})")
# ③ 交付声称：**控件实物 + 已+交付动词**（「开单表单已发出」「确认卡已发出」）。
#    刻意要求控件名词：单独的「已发出」与业务事实同形（「物流已发出」）——判据必须靠
#    控件名词消歧，否则会误改正常物流话术（R2 负例）。
_CARD_DELIVERED_RE = re.compile(
    rf"(?:{_CARD_WIDGET_NOUNS})已(?:{_CARD_DELIVERED_VERBS})")
# ④ 交付声称 + **要求回复『确认』**（系统自产的确认指令）：没有控件名词可消歧的交付句
#    （实测残留「规格回复『确认』已发出」）靠"它在要求顾客确认"这一**协议事实**识别；
#    单独的交付动词（「物流已发出」）仍不命中 —— 判据必须能被业务事实证伪。
#    只进判据、不进改写：这类句子没有可安全替换的控件声称片段，命中后无待确认动作时
#    只留痕（见收尾守卫的"无可改写声称"分支），有则补发真卡。
_CARD_DELIVERED_CONFIRM_RE = re.compile(
    rf"已(?:{_CARD_DELIVERED_VERBS})[\s\S]{{0,12}}?回复[『「\"]?确认"
    rf"|回复[『「\"]?确认[\s\S]{{0,12}}?已(?:{_CARD_DELIVERED_VERBS})")
# 判据（＝①②③④，可改写片段 ⊆ 判据）：回答"该不该在收尾动作"
_CARD_GUARD_RE = re.compile("|".join(
    p.pattern for p in (_CARD_GESTURE_RE, _CARD_ACTION_RE, _CARD_DELIVERED_RE,
                        _CARD_DELIVERED_CONFIRM_RE)))
# 可改写片段（＝②③ + 「点确认」手势）：只改写**指向控件存在**的声称。
# 「点击选择（可多选）」「勾选加工项」这类**指令**不含控件名词 ⇒ 判据命中但不改写
# —— 那种情形真正该说的下一步是"回复您要的加工项"，硬改成"回复『确认』"只会把顾客
# 引到错的下一步（补卡分支另有事实 gating，不靠改写兜）。
_CARD_CLAIM_RE = re.compile("|".join(
    p.pattern for p in (_CARD_ACTION_RE, _CARD_DELIVERED_RE, _CARD_POINT_RE)))
# #3883：误导性建议「刷新页面/重新进入对话」掩盖"没发卡"真因 → 命中整句剥离
_CARD_MISLEAD_RE = re.compile(r"（[^）]*(?:刷新页面|重新进入对话)[^）]*）")


def _has_card_claim(text: str) -> bool:
    """文本是否把顾客**指向一个控件**（判据，不改写）。

    "这轮到底发没发卡"由调用点用**事实**回答（`last_interactive_payload` + 本轮
    `interact` 调用）；本函数只回答**意图**：文本里的动作/交付是否指向控件。
    合法提及「卡片」而无动作/交付指向（「请查看上方结果卡片」「下方列表」）不得命中。
    """
    if not text:
        return False
    # 归一：字符间空白不改变语义（「请 点 击 上 方 卡 片」与「请点击上方卡片」同判）
    return bool(_CARD_GUARD_RE.search(re.sub(r"\s+", "", text)))


def _rewrite_card_claims(text: str) -> str:
    """把「指向不存在控件」的声称改写为纯文本确认指引，并剥离 #3883 误导建议。

    幂等纯函数（无匹配则原样返回）；由 `_agent_stream_to_sse` 收尾守卫在
    「事实=本轮无卡 × 意图=命中」时启用（issue #3929 → #4013 A7）。

    覆盖三类片段：动作 ⟷ 卡片实物（「点下方确认卡片」）、「点确认」手势、
    **控件交付声称**（「开单表单已发出」——#4013 A7 的漏检形态，此前不含"卡"字全漏）。
    """
    if not text:
        return text
    rewritten = _CARD_CLAIM_RE.sub("回复『确认』", text)
    if rewritten == text:
        # 字符间空白（模型逐字加空格，实测形态「请 点 击 上 方 卡 片」）会挡住片段匹配：
        # 判据在**归一**文本上命中，改写就必须跟得上（否则"判得出来却改不掉"）。
        normalized = re.sub(r"\s+", "", text)
        if _CARD_CLAIM_RE.search(normalized):
            rewritten = _CARD_CLAIM_RE.sub("回复『确认』", normalized)
    return _CARD_MISLEAD_RE.sub("", rewritten).strip()
