"""
AI 智能客服系统 - 订单创建 Tool

创建新订单，调用 admin-api 的 POST /api/admin/orders 接口。

安全（#518）:
- 客户创建订单前必须通过手机号 SMS 验证码验证身份
- 管理员/客服帮客户下单无需 SMS 验证
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import uuid
from functools import lru_cache
from typing import Any, Dict, List, Optional
from loguru import logger

from app.tools.base import admin_api_failure, BaseTool, ToolContext, ToolResult
from app.utils.http_client import get_admin_api_client
from app.utils.redis_client import RedisClient


# SMS 验证码 Redis key 前缀
_OTP_KEY_PREFIX = "sms:otp:"
_OTP_TTL_SECONDS = 300  # 5分钟有效期
_OTP_VALID_PATTERN = re.compile(r"^\d{4,6}$")  # 4-6位数字验证码
_PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")  # 中国大陆手机号

# 数值参数解析（issue #3586）：允许货币符号前缀 + 单位后缀（"¥168.00" / "3米" / "2.8 米"）。
# 用户口语里的"3米"就是数量 3 —— 带单位的合法输入不得被当成非法值拦掉。
_NUMERIC_PREFIX_PATTERN = re.compile(r"^[¥￥$]?\s*(?P<num>[+-]?\d+(?:\.\d+)?)")

# 枚举合法值（issue #3622）。单一事实源在 admin-api 侧，工具侧照抄，别名归一化刻意不做：
# - sellingMethod: `product_skus.selling_method` = bulk_cut(散剪) / full_roll(整卷)；
#   `OrderService:1435` 回退匹配时按**字面** eq 比较 → 拼写变体静默匹配不到
#   → 库存校验/销量统计静默丢失（#3621 同源）。
# - pricingMethod: `ProcessingItemService:298` 只认 per_meter/per_set/fixed/per_area
#   （per_piece 按个不支持，issue #3005）。
_SELLING_METHODS = ("bulk_cut", "full_roll")
_PRICING_METHODS = ("per_meter", "per_set", "fixed", "per_area")

# ── 工艺规格（craft spec）枚举闸门（issue #4346 包 1 / 设计文档 §4.2 · §4.8）────────
# `processing_info` 是**整体透传**的（本工具不重拼字段）⇒ 新键不会丢；但**错值**会一路到
# 服务端 —— 部位/工艺错了会取到**错误工序路线**（实证 V58：纱帘订单拿到布帘的 11 道工序，
# 工序与工资全错）。故在工具侧 fail-fast：拒绝 + 点名合法值，让 LLM 下一轮自愈。
# ⚠️ 刻意**不**做别名归一化（同 `_SELLING_METHODS` 口径）：`韩式褶`→`韩褶` 这类归一
# 会把契约藏进工具层，而静默接受的代价是**静默取错路线**。
# - curtainType: `production_routings.curtain_type`（布帘/纱帘/帘头）
# - craft:       `production_routings.craft`（韩褶/打孔/四爪钩/穿杆/平幔）——
#                与 `mounting`（eyelet/s_hook/hook/roman）是**两层**，禁止互相推导
# - componentRole: 明细行角色（主布/配布边/纱），设计文档 §4.8
# - style:       款式（单色/拼色），真值源 `curtain-production-rules.md` §8
# - metersSource: 配布边米数来源（跟随主布/人工指定），设计文档 §4.8
_CURTAIN_TYPES = ("布帘", "纱帘", "帘头")
_CRAFTS = ("韩褶", "打孔", "四爪钩", "穿杆", "平幔")
_COMPONENT_ROLES = ("主布", "配布边", "纱")
_STYLES = ("单色", "拼色")
_METERS_SOURCES = ("跟随主布", "人工指定")

# ── 写侧补全：加工类型 / 打开方式 / 算料输出来源（issue #4374 包 4a / 设计文档 §4.2 · §4.3）──
# 加工类型 = 算料侧 `formula_used` 的两态口径（设计文档 §4.2：`fixed_height*` → 定高买宽；
# `fixed_width*` / `roman_panel` → 定宽买高）。**与 `mounting`（悬挂方式）是两层**，不互相推导。
_CUTTING_MODES = ("定高买宽", "定宽买高")
# 打开方式开数：单开/双开/四开（`curtain_calc` 的 `open_count`）。**数值枚举**，只认这三个数。
_OPEN_COUNTS = (1, 2, 4)
# 算料输出的取值来源（真值源 `docs/curtain-fabric-quote-rules.md` §8 原文口径：
# 「折数/用料必须带来源（公式计算 / 人工指定 / 客户自报），防止多渠道不一致」）。
_SOURCES = ("公式计算", "人工指定", "客户自报")
# 算料输出键 → 字段标签（负值闸门的报错要**点名**是哪个字段）。
# 键名一律 snake_case，与 `curtain_calc` 输出**逐字一致**（设计文档 §4.5：改它 = 改契约）。
_CALC_OUTPUT_LABELS = (
    ("fabric_meters", "面料米数"),
    ("pleat_count", "折数"),
    ("per_panel_pleats", "每片折数"),
    ("panels", "幅数"),
    ("fullness", "理论褶倍"),
    ("fullness_actual", "实际褶倍"),
)
# 工艺规格数值键 → 字段标签（同上）。
_CRAFT_SPEC_NUMBERS = (
    ("pleatSpacing", "褶距"),
    ("patternRepeat", "花距"),
)

# 万能验证码 bypass（POC/测试阶段，对齐 admin-api 的 sms.bypass-code 机制）。
# 空字符串 = 禁用 bypass（生产安全默认）。POC 部署时设置 SMS_BYPASS_CODE=123456 与 admin-api 对齐。
SMS_BYPASS_CODE = os.getenv("SMS_BYPASS_CODE", "")


# ══ 非幂等写的幂等键（issue #4037 / F19；作用域 = **会话**，issue #4195；维度 = **操作**，issue #4212）══
# 事实：HTTP 客户端超时 **25s**（`AdminApiClient(timeout=25.0)`）< 工具超时 **30s**
# （`_execute_tool_safe`）⇒「**订单已落库但客户端报失败**」窗口客观存在；而失败话术原文
# 写着「确认后**重试**」⇒ LLM 重试 = 重复下单 = 直接资金损失。
# 幂等键 = 「同一个**逻辑写请求**在**同一个重试窗**内取值相同」：服务端按
# `(tenant_id, clientRequestId)` 去重并回放首次结果（admin-api `ClientRequestIdService.claim`）；
# 跨窗换新值 ⇒ 顾客真的想再下一单时不会被当成重试吞掉（R2）。刻意**不做**"按内容哈希永久
# 去重"——那会把合法复购（同一款窗帘做两个房间）永久拒掉，等于用一个更糟的缺陷换一个缺陷。
#
# ⚠️ 作用域必须是**会话**（issue #4195，P0）：键里只有窗口号时取值是**进程全局**的
# ——同进程 10 分钟窗内所有会话共用一个 `X-Client-Request-Id`，服务端便把第 2 位顾客的下单
# 当成第 1 位的重试**回放**（判定 run 35295494688：OR-011/OR-014/OR-028 都拿到 OR-010 的
# 订单号「20260918485580004 / 张三 / 13812345678」，OR-017/018/019 同样拿到别人的单）。
# 修法：键 = 窗口 + **作用域 token**（`session_id`，缺省回退 `user_id`）+ 每窗随机串。
# F19 语义不变：**同一会话**内的重试仍在同一窗内取到同一键 ⇒ 服务端仍只落一单。
#
# ⚠️ 键还必须标识「**哪一次逻辑写请求**」（issue #4212）—— 服务端去重键 = `(tenant_id,
# client_request_id)`，**不含 endpoint**（`V50__create_client_request_keys.sql` 的
# `UNIQUE (tenant_id, client_request_id)`；表里 `endpoint` 列不进唯一键）。于是同一会话
# 10 分钟窗内**先建订单、再建售后工单**（或反之）会共用一把键 ⇒ 第二次 `claim` 命中已占位 ⇒
# `AgentAfterSalesController` 按**本端点自己的类型** `replay(..., AfterSalesDetailResponse.class)`
# 反序列化**别人端点的快照** ⇒ 必然失败 ⇒ `orElseThrow(409, "本次未重复建单")`
# —— 用户只请求了一次却被拒，文案还指向"重复提交"（归因误导）。
# 修法：键里加**操作维度** = 下面三个常量（`order` / `aftersale` / `handoff`）。
# ⚠️ 刻意在**客户端键**里加维度、不去改服务端唯一键：后者会变更 DB 契约与既有数据语义
#    （`endpoint` 列现在是诊断线索，进唯一键后同一 message 的语义翻转）。
# ⚠️ 三个常量是**单一事实源**：另两条写路径 `from app.tools.order_create import <常量>`
#    （就地定义/写字面量 = 三处口径各自漂移，接线锁在
#    `tests/test_idempotency_key_session_scope.py`）。
_IDEMPOTENCY_WINDOW_SECONDS = 600.0
CLIENT_REQUEST_ID_HEADER = "X-Client-Request-Id"

#: 幂等键的**操作维度**取值（issue #4212）。改这些值 = 部署窗口内同一次重试的键轮换
#: （旧 pod 与新 pod 算出不同键 ⇒ 灰度期间那一笔可能重复落库）——不是随手可改的字面量。
ORDER_CREATE_OP = "order"
AFTERSALE_CREATE_OP = "aftersale"
HUMAN_HANDOFF_OP = "handoff"

#: `_window_id` 的缓存容量。作用域/操作进缓存键后条目数 ≈ 一个窗口内的活跃会话数 × 3
#: （三个写路径各一份）；容量不足 ⇒ 同窗内旧条目被 LRU 挤出 ⇒ 重试取到**新键** ⇒ 服务端
#: 无从去重（F19 静默失效）。故容量随操作维度**同步 ×3**（4096 → 12288 ≈ 1.2 MB 级）：
#: 「每窗可容纳的**写请求数**」这才与 #4195 时一致 —— 沿用旧值等于把 F19 的余量静默缩到 1/3。
_IDEMPOTENCY_CACHE_SIZE = 12288

#: 无身份（`context` 缺失 / 两端都为空）时键里的回退标记 —— 见 `_request_window_id`：
#: 该分支**不去重**（每次一个新键），故它绝不是一个可被两个调用方共用的作用域值。
_NO_IDENTITY_TOKEN = "noid"


def _scope_token(scope: str) -> str:
    """作用域 / 操作 → 定长、URL 安全的 token（幂等键要进 HTTP 头）。

    用 sha256 而不是"把非法字符替换成 `-`"：替换会把 `a/b`、`a b`、`a-b` 折叠成同一个 token
    ⇒ 两个不同会话又共用一把键（正是本单要修的形态）。哈希**抗碰撞**（48 bit 前缀，会话量级下
    可忽略），顺带不把 session_id 原文写进服务端 `client_request_keys` 表/日志。

    操作维度（issue #4212）**走同一函数**：服务端 `ClientRequestIdService.normalize()` 对
    `> 128` **抛错拒绝**（400 级）——把 op 直接拼进键会让超长/含非法字符的 op 把写请求打成 400；
    哈希后键长恒定且字符集合法（判据见 `tests/test_idempotency_key_session_scope.py`）。
    """
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:12]


def _idempotency_scope(context: Optional[ToolContext]) -> Optional[str]:
    """幂等键的**作用域**：谁在写（issue #4195）。

    首选 `session_id`（重试的单位是**会话** —— F19 的语义正是"同一会话内的重试"），
    缺省回退 `user_id`（会话号缺失时至少按人隔离）。
    返回 `None` = **无身份可依** ⇒ 调用方走 `_request_window_id` 里登记的回退口径，
    **不得**退回进程全局键（那正是 #4195 的 P0）。
    """
    if context is None:
        return None
    return (context.session_id or "").strip() or (context.user_id or "").strip() or None


@lru_cache(maxsize=_IDEMPOTENCY_CACHE_SIZE)
def _window_id(window: int, scope: str, *, op: str) -> str:
    """某个 (重试窗, 作用域, 操作) 的幂等键（缓存键是**这三个** ⇒ 同窗同作用域同操作取值相同、跨窗换新）。

    ⚠️ 缓存键缺一不可（三条都是实测踩过的形态）：
    - 漏掉窗口号（写成 `@lru_cache` 无参函数：lru_cache 的键是"调用参数"、不是返回值）
      ⇒ **首次**算出的键被永久冻结 ⇒ 幂等键永不轮换 ⇒ 顾客的合法复购全被当成重试吞掉；
    - 漏掉作用域（issue #4195 的病灶）⇒ 键**进程全局** ⇒ 同一进程内跨会话串单
      （把别人的订单号/姓名/手机号回放给顾客）；
    - 漏掉操作（issue #4212 的病灶）⇒ 同一会话内跨端点共用一把键 ⇒ 服务端按**本端点类型**
      回放别人端点的快照 ⇒ 409「本次未重复建单」（用户只请求了一次却被拒）。

    ⚠️ `op` 是**关键字限定**参数：`lru_cache` 把 `f(w, s, op)` 与 `f(w, s, op=op)` 当成**两条
    不同条目** ⇒ 两种调用形态并存时同一次重试会取到两把键（F19 静默失效）。关键字限定让这个
    形态**不可表达**（生产调用点与判据一律写 `op=`）。
    """
    return f"{window}-{_scope_token(scope)}-{_scope_token(op)}-{uuid.uuid4().hex[:12]}"


def _request_window_id(context: Optional[ToolContext] = None, *, op: str) -> str:
    """当前 (重试窗, 会话作用域, 操作) 的幂等键 —— 三个写路径（订单/售后/转人工）的**唯一入口**。

    三个调用点都必须把本会话的 `ToolContext` **和本文件的操作常量**递进来（接线锁：
    `tests/test_idempotency_key_session_scope.py`）。`op` 刻意**无默认值**：新增写路径必须
    声明自己的操作维度，否则 TypeError（fail-closed）—— 给个默认值会让新端点静默继承
    `"order"` 的键，正是 #4212 的形态原地复发。

    **缺省回退口径（显式登记，禁止静默退回旧行为）**：拿不到任何身份（`context` 缺失、
    或 `session_id`/`user_id` 都为空）⇒ **不去重**：每次调用一个新键。取舍是"两害相权"——
    缺身份时复用一把键 = 把别人的订单回放给顾客（#4195 的 P0，资金/信任级）；
    而"不去重"最坏只是这次重试多落一单，且三个生产调用点都传 context（该分支不可达）。
    `op` 同样进该分支的键（否则键的构成随"有无身份"而变，是下一处漂移源）。
    """
    window = int(time.time() // _IDEMPOTENCY_WINDOW_SECONDS)
    scope = _idempotency_scope(context)
    if scope is None:
        logger.warning(
            "[idempotency] 拿不到会话/用户身份 ⇒ 本次**不去重**（每次新键）："
            "调用方应把本会话的 ToolContext 递进来（issue #4195）")
        return f"{window}-{_NO_IDENTITY_TOKEN}-{_scope_token(op)}-{uuid.uuid4().hex[:12]}"
    return _window_id(window, scope, op=op)


# ══ 确认卡↔落库一致性（issue #4037 / F22）—— 纯函数，零 LLM、零 IO ══════════
# 线上实证：顾客点确认卡看到 ¥498（10 米/3 加工项），落库 ¥133.80（1 米/2 加工项+优惠）。
# 根因不是"某处算错"，而是**卡上的事实与写工具参数是两份独立产物**（fields 与 items
# 都由模型自由书写，中间只有 prompt 的口头约定）—— 全系统无一处校验两者一致。
# 修法：顾客确认那一刻把金额事实快照进会话状态（`confirmed_order_facts`），本工具在
# **调用服务端之前**重算并与快照比对，不一致 ⇒ 拦截（fail-closed + 可行动话术）。
# 事实只取驱动金额与库存的**规范值**：手机号 + 每行 名称/数量/单价/加工费。
#   · 不取 subtotal/total：服务端本就按 `quantity×unitPrice`(+加工明细)重算
#     （`createOrderForAgent`），纳入比对只会制造假红；
#   · 不取地址/备注/尺寸：确认后补这些是**正常流程**，纳入比对 = 把合法输入拦掉（R2）；
#   · 加工费按服务端口径（Σ unitPrice×quantity），不信模型声明的 processingFee。
def _entry_processing_fee(entry: Any) -> float:
    """单行加工费（服务端口径）：Σ processingItems[].unitPrice × quantity。"""
    pinfo = entry.get("processing_info") if isinstance(entry, dict) else None
    if not isinstance(pinfo, dict):
        return 0.0
    raw_items = pinfo.get("processingItems")
    if not isinstance(raw_items, list):
        return 0.0
    total = 0.0
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        up = OrderCreateTool._parse_positive_number(it.get("unitPrice"))
        qty = OrderCreateTool._parse_positive_number(it.get("quantity"))
        if up is not None and qty is not None:
            total += up * qty
    return round(total, 2)


def order_facts_of(payload: Any) -> str:
    """订单 payload → 一致性事实串（确认卡投影与本工具共用**同一口径**）。

    同一份订单**永远得到同一个串**（JSON sort_keys + 数值归一到 2 位小数），
    因此"写法差异"（168 / "168.00" / 168.0）不会被误判为不一致。
    无 items ⇒ 返回 ""（无从核对，调用方据此跳过）。
    """
    if not isinstance(payload, dict):
        return ""
    items = payload.get("items")
    if not isinstance(items, list):
        return ""
    lines = []
    for it in items:
        if not isinstance(it, dict):
            continue
        qty = OrderCreateTool._parse_positive_number(it.get("quantity"))
        price = OrderCreateTool._parse_positive_number(it.get("unit_price"))
        fee = _entry_processing_fee(it)
        lines.append({
            "name": str(it.get("product_name") or it.get("name") or "").strip(),
            "qty": round(qty, 2) if qty is not None else None,
            "price": round(price, 2) if price is not None else None,
            # 小计 = 数量×单价（服务端落库口径的**派生值**，不读模型声明的 subtotal）
            "subtotal": round((qty or 0) * (price or 0), 2),
            "fee": fee,
        })
    if not lines:
        return ""
    return json.dumps({
        "phone": str(payload.get("customer_phone") or "").strip(),
        "items": lines,
        "total": round(sum((l["subtotal"] or 0) + (l["fee"] or 0) for l in lines), 2),
    }, ensure_ascii=False, sort_keys=True)


def order_confirmation_mismatch(payload: Any, confirmed_facts: Any) -> str:
    """落库前核对：**顾客确认过的事实** vs **本次真正要执行的事实**。

    Returns:
        str: 不一致时的可行动描述；一致 / 无从核对（快照为空）时返回 ""（放行）。

    fail-closed 边界（刻意保守，避免把合法输入拦掉）：
      · 没记过确认快照（老会话 / 非确认路径）⇒ 放行 —— 本函数**只比对"确认过什么"**，
        不替代确认门禁（门禁在 base_skill，各自职责不重叠）；
      · 确认快照里没有 items（写工具不是下单，或快照只有手机号）⇒ 放行。
    """
    confirmed = str(confirmed_facts or "").strip()
    if not confirmed:
        return ""
    actual = order_facts_of(payload)
    if not actual:
        return ""
    try:
        prior_items = json.loads(confirmed).get("items") or []
    except (ValueError, TypeError, AttributeError):
        return ""  # 快照形态不认识 ⇒ 不臆断（拒绝比放行安全的前提是"读得懂"，读不懂就不猜）
    if not prior_items:
        return ""
    if actual == confirmed:
        return ""
    return (
        f"下单被拦截：本次要执行的订单明细与**顾客确认卡上的明细不一致**。"
        f"顾客确认的是 {confirmed}，本次要落库的是 {actual}。"
        f"确认过的数量/单价/加工项/手机号一旦变化，顾客点过的确认即失效"
        f"（线上实证：卡上 ¥498（10 米/3 加工项）落库成 ¥133.80（1 米/2 加工项））。"
        f"请把明细改回顾客确认过的值；确实要改，就**重新发一张确认卡**让顾客再确认一次，"
        f"不要直接落库。"
    )


class OrderCreateTool(BaseTool):
    """订单创建 Tool

    通过调用 admin-api 创建新订单。

    使用场景：
    - 客服帮客户下单
    - 客户通过聊天直接创建订单

    安全规则（#518）:
    - customer 角色：必须提供 sms_code，且通过手机号验证
    - admin/agent/tenant_admin 角色：无需 SMS 验证（帮客户下单）
    """

    name = "order_create"
    description = (
        "【触发】创建订单。用户说'创建订单''下单'时调用。"
        "【前置】必须先调 product_detail 查 SKU，多 SKU 必须让用户选规格（颜色/售卖方式/门幅）。单 SKU 直接用。"
        "必填: customer_name + customer_phone + items(product_name+quantity+unit_price+subtotal)。"
        # 契约面必须与运行时判据一致（issue #4011）：运行时对「商品有多个不同 SKU 价」要求
        # 指定规格，而 schema 只声明 4 个必填、描述也没说 ⇒ LLM 无从知道 ⇒ 死锁
        # （OR-014 首跑 13 次 order_create 无一成功，连正确库价 @168 也被拒）。
        "【规格必填】商品有**多个不同 SKU 价**（分色/规格差价）时，items[i].processing_info "
        "必须带 skuId，或 colorName/skuCode（取 product_detail 的 skus[].id / color_name / sku_code）；"
        # 规格键族契约（issue #4090）：服务端库存匹配读的就是这几个键 —— 供应商（本工具）必须
        # 声明模型**真能拿到**的键，且键族要与服务端一致（否则库存校验/扣减/销量会被拒绝或走偏）。
        "**规格键族**：服务端按 skuId → skuCode → colorId+sellingMethod+doorWidth → "
        "colorName+sellingMethod+doorWidth 定位 SKU（库存校验/扣减/销量都按它走）。"
        "优先传 skuId（product_detail 的 skus[].id，最精确）；用 skuCode/colorName 时必须与 "
        "skus[] 原值逐字一致，并**同时给 sellingMethod 与 doorWidth** —— "
        "只给颜色（或规格与库内对不上、命中多行）会因无法唯一定位 SKU 被拒绝（issue #4090）。"
        "**不要臆造规格键**（尤其 colorId：product_detail 不返回该字段，填错会让下单被拒）。"
        "单价必须落在商品库价集合内（商品 price 或某个 SKU 价），编造价一律拦截。"
        "【单价铁律】items[i].unit_price **必须等于商品库价**（product_detail 的 price，"
        "或所选 SKU 的 skus[].price；库中无分色差价时所有颜色同价）——"
        "禁止编造分色/规格价（如库价 168 却报「米白 150」），"
        "报价/确认卡/落单三者单价必须一致；系统会在调用前按库价校验，不一致会被拦截并回填库价。"
        "【不议价】agent 路径不允许偏离商品库价；顾客要议价/优惠时不要改单价，请引导走后台。"
        "售卖方式/门幅/颜色等规格信息放入 items[i].processing_info（字段：skuId/skuCode/colorName/sellingMethod/doorWidth），"
        "不要平铺在 items 顶层（平铺会被丢弃）。"
        # 工艺规格落库（issue #4346 / 设计文档 §4.9）：引导清单**已经问到了**这些工艺参数，
        # 但此前下单时全被丢弃 ⇒ 加工单只能靠加工项名**猜**部位（实证 V58：纱帘订单拿到布帘的
        # 11 道工序，工序与工资全错）。故要求随单落库。
        "【工艺规格·必带】引导清单/顾客已明确的工艺参数必须写进 items[i].processing_info（**顶层键**）："
        "curtainType（部位：布帘/纱帘/帘头）、craft（安装工艺：韩褶/打孔/四爪钩/穿杆/平幔 —— "
        "**与 mounting 是两层，不要互相推导**）、isShaped（是否定型）、style（单色/拼色）、"
        "cuttingMode（加工类型：定高买宽/定宽买高）、openCount（打开方式开数：1/2/4）、"
        "pleatSpacing（褶距，米）、hasPattern + patternRepeat（是否对花 + 花距，米）、"
        "specialOptions（下单勾选的特殊选项，如 拼1次/加铅块/加花边/抱枕/布绑带）。"
        "**枚举必须逐字一致**（「韩式褶」非法，应为「韩褶」）—— 错值会让加工单取到**错误工序路线**。"
        "**顾客没说就不填**：不要猜、不要补默认值。"
        # 算料输出透传（issue #4374 / 设计文档 §4.3）：这些键的**唯一来源**是 curtain_calc 的输出，
        # 且键名 snake_case 与它**逐字一致**（设计文档 §4.5：改键名 = 改契约）。
        # 红线 = 不发明数字：缺就不填（不补 0、不自己乘倍数推算）——自己推算会让
        # 「报价单展示的米数」≠「订单落库的米数」，对顾客的承诺与履约不一致。
        "【算料输出·原样透传】已调用 curtain_calc 算料时，把它的输出**原样透传**进 "
        "items[i].processing_info（**顶层键**，键名逐字一致，**不要自己推算**）："
        "fabric_meters（面料米数）、pleat_count（总褶数）、per_panel_pleats（每片折数）、"
        "panels（幅数）、fullness（理论褶倍）、fullness_actual（实际褶倍）、"
        "source（取值来源：curtain_calc 的 formula → 「公式计算」/ manual → 「人工指定」/ "
        "customer_quoted → 「客户自报」）。"
        "**没算料 / 输出里没有该键 ⇒ 就不要填**（**不要补 0**、不要按倍数自己乘）——"
        "算料数字只有一个真值源，自己推算会让报价单与订单对不上。"
        "【双拼·主布/配布边】拼色（双拼）时一扇窗拆**两条明细行**：主布行带 componentRole=主布 "
        "与全部工艺规格；配布边行带 componentRole=配布边 + craftLineId=主布行的行标识"
        "（绑成一组，否则加工单会把一扇窗算成两扇、折数/开数/工序/计件全部翻倍），"
        "并带 metersSource（跟随主布/人工指定）。**加工项只挂主布行**。"
        "【加工费米数】加工费按**主布米数**算（配布边米数不参与）—— 米数由算料（curtain_calc）给出，"
        "**不要自己推算**。"
        "【铁律·加工项】product_detail 返回的加工项（processing_items）非空时，**必须先调用 "
        "interact(component=choice, multiSelect=true) 主动询问顾客要不要加工项**（列出名称与单价），"
        "把所选写入 items[i].processing_info.processingItems、合计写入 processingFee 并计入金额；"
        "顾客说不需要可跳过；加工项为空才可告知无可用加工项。"
        "**未询问就直接建单 = 漏收加工费 = 订单金额错误**，属禁止行为。"
        # 口径规则放工具描述而非 system prompt（issue #3521）：
        #   ① 这是**参数语义**（processingItems 的 quantity 怎么来），与字段定义同处最合适；
        #   ② C 端下单 prompt 已顶到长度守卫上限（3592/3600），加规则必须先删旧规则——
        #      在 bug 修复里改别人行为域的措辞风险更大，故走零预算的加法路径。
        # 实证：CH-010 首跑 `总额 311.4 ≠ Σ小计71.4+加工费252.0=323.4` —— 小计 71.4=3×23.8，
        #   落库总额 311.4=71.4+240（服务端按 processingItems 的 unitPrice×quantity 重算），
        #   而模型声明的 processingFee=252（把按面积的刺绣工艺算成 30×8.4）。同一个订单两份数字。
        "【铁律·加工数量口径】processingItems[i].quantity 必须按 pricingMethod 推导，不许凭感觉："
        "per_meter(按米)=面料米数；per_area(按面积)=门幅(米)×面料米数（㎡，**可为小数**，如 2.8×3=8.4）；"
        "per_set(按套)=套数；fixed(一口价)=1（单价即该项总价）。"
        "items[i].quantity 是**订单数量**（驱动库存/销量），必须是**不小于 1 的数**"
        "（口径 per_meter=米数、per_set=件数、per_area=宽×高；如 1、2.5、8.4），"
        "<1 会被本地拒绝——服务端库存/销量按**整数件**计，0.5 会被算成 0 件（不扣库存、销量 +0，"
        "订单却照样成交）。服务端按 DECIMAL(10,2) 保真落库，不得自行取整。"
        "**processingFee 必须等于 Σ(processingItems[i].unitPrice × quantity)**（容差 0.01）——"
        "服务端只按这个明细口径计总额，两处不一致时顾客在确认卡上看到的总额 ≠ 实际落库/收款金额。"
        "【反例】跳过 SKU 选择直接下单；把 sellingMethod/doorWidth 平铺进 items；"
        "臆造规格键（如自己编 colorId/skuId）或只给颜色不给门幅就下单（服务端无法定位 SKU ⇒ 拒绝）；"
        "凭 product_search 列表断言'该商品无加工项'（列表本就查不到，必须查详情）。修改订单用 order_manage。WRITE"
    )
    allowed_roles = ["admin", "agent", "tenant_admin", "customer"]

    read_only = False
    destructive = False
    # GB/T 47746-2026 承诺边界：下单即与顾客达成交易合同（金额/履约承诺），
    # 含 B 端客服代顾客下单——必须先向用户展示订单确认卡并取得明确确认后才能执行。
    requires_confirmation = True
    idempotent = False  # 每次调用创建新订单

    # 关联校验工具
    related_tools = ["validate_input"]

    parameters = {
        "type": "object",
        "properties": {
            "customer_name": {
                "type": "string",
                "description": "客户姓名（必填）",
            },
            "customer_phone": {
                "type": "string",
                "description": "客户电话（必填）",
            },
            "sms_code": {
                "type": "string",
                "description": "短信验证码，4-6位数字。customer角色必填，admin/agent不需要",
            },
            "customer_address": {
                "type": "string",
                "description": "客户收货地址（可选）",
            },
            "remark": {
                "type": "string",
                "description": "订单备注（可选）",
            },
            "items": {
                "type": "array",
                "description": "商品明细列表（必填，至少一项）",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_name": {
                            "type": "string",
                            "minLength": 1,
                            "description": "商品名称（必填，不得为空；与 product_detail 返回一致）",
                        },
                        "quantity": {
                            "type": "number",
                            "minimum": 1,
                            "description": (
                                "订单数量（必填，**不得小于 1**，可为小数；<1 会被本地拒绝）。"
                                "为什么下限是 1（issue #3682）：服务端库存/销量按整数件计，"
                                "数量 0.5 → 需求算成 0 件 → 不扣库存、销量 +0，订单却成交（账实不符）。"
                                "口径按计价方式：per_meter=面料米数（如 2.5）；"
                                "per_set=件数；per_area=宽×高（㎡，如 2.8×3=8.4）；fixed=1"
                            ),
                        },
                        "unit_price": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "description": "单价（必填，必须大于 0 元）",
                        },
                        "subtotal": {
                            "type": "number",
                            "minimum": 0,
                            "description": "小计 = 数量 × 单价 + 加工费（必填，不得为负）",
                        },
                        "product_id": {
                            "type": "string",
                            "description": "商品 32 位 UUID（可选）。当用户明确指定商品时传入。不传时服务端通过 product_name 自动匹配",
                        },
                        "width": {
                            "type": "number",
                            "minimum": 0,
                            "description": "宽度（米，可选，不得为负；可传 2.8 或「2.8米」）",
                        },
                        "height": {
                            "type": "number",
                            "minimum": 0,
                            "description": "高度（米，可选，不得为负；可传 2.0 或「2.0米」）",
                        },
                        "processing_info": {
                            "type": "object",
                            "description": "商品销售信息（选了颜色/门幅后必填）：skuId(SKU主键，来自商品详情 skus[].id，**首选键**)、skuCode(SKU编码)、colorName(颜色名称)、sellingMethod(售卖方式: bulk_cut散剪/full_roll整卷)、doorWidth(门幅如2.8米)、processingItems(加工项列表)、processingFee(加工费合计)。"
                                           "服务端按 skuId → skuCode → colorId+sellingMethod+doorWidth → colorName+sellingMethod+doorWidth 定位 SKU（库存校验/扣减/销量都按它走）；"
                                           "⚠️商品有**多个不同 SKU 价**时 skuId 或 colorName/skuCode **必填**（取 product_detail 的 skus[]）——"
                                           "缺规格则无法确定该行库价、下单会被拒绝（issue #4011）；规格与库内原值对不上或无法唯一定位（只给颜色、命中多行）同样会被拒绝（issue #4090）。",
                            "properties": {
                                "skuId": {"type": "string", "description": "SKU 主键（取 product_detail skus[].id 原值）——**首选规格键**：服务端按它唯一定位 SKU，不依赖名称/门幅的书写归一化"},
                                "colorId": {"type": "string", "description": "颜色ID（**product_detail 不返回该字段**：Agent 路径不要臆造；需要 ID 族请用 skuId）"},
                                "colorName": {"type": "string", "minLength": 1,
                                              "description": "颜色名称（取 product_detail skus[].color_name 原值）。商品有多个不同 SKU 价时必填"},
                                "sellingMethod": {
                                    "type": "string",
                                    "enum": ["bulk_cut", "full_roll"],
                                    "description": "售卖方式，取 product_detail skus[].selling_method 原值：bulk_cut(散剪) / full_roll(整卷)。拼写变体（散剪/bulkCut）会被本地拒绝",
                                },
                                "doorWidth": {"type": "string", "description": "门幅"},
                                # ── 工艺规格（issue #4346 / 设计文档 §4.2 · §4.8 · §4.9）──────────
                                # 引导清单已问到的工艺参数**必须随单落库** —— 否则加工单只能靠
                                # 关键字猜部位（实证 V58：纱帘订单拿到布帘的 11 道工序，工序与工资全错）。
                                # 枚举一律与库侧逐字一致；**顾客没说就不填**（不猜、不补默认值）。
                                "curtainType": {
                                    "type": "string",
                                    "enum": ["布帘", "纱帘", "帘头"],
                                    "description": "部位/帘种（引导清单已采集）。错值会取到**错误工序路线**；顾客没说 ⇒ 不填",
                                },
                                "craft": {
                                    "type": "string",
                                    "enum": ["韩褶", "打孔", "四爪钩", "穿杆", "平幔"],
                                    "description": "安装工艺（引导清单已采集，须与工序库枚举**逐字一致**）。与 mounting（eyelet/s_hook/hook/roman）是**两层**，**不要互相推导**（「韩式褶」不是合法值，应为「韩褶」）",
                                },
                                "isShaped": {
                                    "type": "boolean",
                                    "description": "是否定型（引导清单已采集：布帘/帘头默认是、纱帘默认否）",
                                },
                                "style": {
                                    "type": "string",
                                    "enum": ["单色", "拼色"],
                                    "description": "款式。拼色（双拼）时见 componentRole/craftLineId",
                                },
                                "specialOptions": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "下单勾选的**特殊选项**（部位级，19 项，如 拼1次/加铅块/加花边/抱枕/布绑带）——影响车间条件工序与计件系数",
                                },
                                "componentRole": {
                                    "type": "string",
                                    "enum": ["主布", "配布边", "纱"],
                                    "description": "明细行角色（设计文档 §4.8）。缺省视为「主布」（存量单兼容）。双拼 = 主布行 + 配布边行**两条明细行**",
                                },
                                "craftLineId": {
                                    "type": "string",
                                    "description": "**同一扇窗的绑组标识**：配布边行填主布行的行标识 ⇒ 加工单只生成一个部位（否则一扇窗被算成两扇，折数/开数/工序/计件全部翻倍）",
                                },
                                "metersSource": {
                                    "type": "string",
                                    "enum": ["跟随主布", "人工指定"],
                                    "description": "配布边米数来源：默认「跟随主布」；顾客/商家改过米数 ⇒ 「人工指定」（防事后分不清是系统算的还是人改的）",
                                },
                                "processingMeters": {
                                    "type": "number",
                                    "description": "加工费米数（= **主布行**米数，配布边米数不参与）。由算料给出，**不要自己推算**",
                                },
                                # ── 工艺规格补全（issue #4374 包 4a / 设计文档 §4.2）────────────
                                # 包 1（#4346）只声明了 9 个键 ⇒ 加工类型/打开方式/褶距/对花既不在
                                # schema、也不在「必带」指令里 ⇒ LLM 大概率不写 ⇒ 订单/加工单面看不到。
                                "cuttingMode": {
                                    "type": "string",
                                    "enum": ["定高买宽", "定宽买高"],
                                    "description": "加工类型（= 算料侧 `curtain_calc` 的 `formula_used`：`fixed_height*` → 定高买宽，`fixed_width*`/`roman_panel` → 定宽买高）。与 mounting（悬挂方式）是**两层**，不要互相推导；顾客没说 ⇒ 不填",
                                },
                                "openCount": {
                                    "type": "integer",
                                    "enum": [1, 2, 4],
                                    "description": "打开方式开数：1 单开 / 2 双开 / 4 四开（引导清单已采集）。折数整除校验与算料余量按它走；顾客没说 ⇒ 不填",
                                },
                                "pleatSpacing": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "褶距（米，引导清单已采集，默认 0.1）。用于折数/褶距换算与可行性校验",
                                },
                                "hasPattern": {
                                    "type": "boolean",
                                    "description": "是否对花（大花型面料；定宽买高时每幅加 1 个花距）。顾客没说 ⇒ 不填",
                                },
                                "patternRepeat": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "花距（米，对花时有效，常见 0.3~0.6）。须与 hasPattern 同时给",
                                },
                                # ── 算料输出（issue #4374 包 4a / 设计文档 §4.3 · §4.5）──────────
                                # 唯一来源 = `curtain_calc` 的输出，**原样透传**；缺就不填（不补 0、不推算）。
                                # 键名一律 snake_case（与 `curtain_calc` 输出逐字一致 —— 改它 = 改契约）。
                                "fabric_meters": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "面料米数（**原样取 `curtain_calc` 输出的 `fabric_meters`**，不要自己推算、缺就不填）",
                                },
                                "pleat_count": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "总褶数（**原样取 `curtain_calc` 输出的 `pleat_count`**，不要自己推算、缺就不填）",
                                },
                                "per_panel_pleats": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "每片折数（**原样取 `curtain_calc` 输出的 `per_panel_pleats`**，不要自己推算、缺就不填）",
                                },
                                "panels": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "幅数（**原样取 `curtain_calc` 输出的 `panels`**；只有定宽买高才有该键 —— 缺就不填，不要补 0）",
                                },
                                "fullness": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "**理论**褶倍（**原样取 `curtain_calc` 输出的 `fullness`**，随工艺档位走；不要自己推算）",
                                },
                                "fullness_actual": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "**实际**褶倍（**原样取 `curtain_calc` 输出的 `fullness_actual`**，随用料走；与 fullness 语义不同，两个都要原样透传）",
                                },
                                "source": {
                                    "type": "string",
                                    "enum": list(_SOURCES),
                                    "description": "折数/用料的取值来源（真值源 §8：必须带来源，防多渠道不一致）。`curtain_calc` 的 source 为 formula → 「公式计算」/ manual → 「人工指定」/ customer_quoted → 「客户自报」",
                                },
                                "skuCode": {"type": "string", "minLength": 1,
                                            "description": "SKU编码（取 product_detail skus[].sku_code 原值）。商品有多个不同 SKU 价时必填（与 colorName 二选一）"},
                                "processingFee": {
                                    "type": "number",
                                    "minimum": 0,
                                    "description": "加工费合计（不得为负）= Σ(processingItems[i].unitPrice × quantity)",
                                },
                                "processingItems": {
                                    "type": "array",
                                    "description": "加工项列表",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "name": {"type": "string"},
                                            "unitPrice": {"type": "number", "minimum": 0},
                                            "quantity": {
                                                "type": "number",
                                                # 刻意**不设 ≥1 下限**（issue #3682 边界裁定）：
                                                # 加工数量不驱动库存/销量（只进 Σ unitPrice×quantity
                                                # 的加工费数学），且 per_area 的面积可以合法 <1 ㎡
                                                # （如 0.8×0.9=0.72 ㎡）——设 1 会误伤小面积加工单。
                                                # 负值仍由 _validate_processing_info 拒绝（#3622）。
                                                "minimum": 0,
                                                "description": (
                                                    "加工数量，按 pricingMethod 推导：per_meter=面料米数；"
                                                    "per_area=宽×高（㎡，可为小数如 8.4，可小于 1）；per_set=套数；fixed=1"
                                                ),
                                            },
                                            "unit": {"type": "string"},
                                            "pricingMethod": {
                                                "type": "string",
                                                "enum": ["per_meter", "per_set", "fixed", "per_area"],
                                                "description": "计价方式，取 product_detail processing_items[].pricing_method 原值：per_meter(按米)/per_set(按套)/fixed(一口价)/per_area(按面积)；per_piece(按个)不支持",
                                            },
                                            "subtotal": {"type": "number", "minimum": 0},
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "required": ["product_name", "quantity", "unit_price", "subtotal"],
                },
            },
        },
        "required": ["customer_name", "customer_phone", "items"],
    }

    @staticmethod
    def _parse_positive_number(raw: Any) -> Optional[float]:
        """解析数值参数（数量/单价/小计），容忍 LLM 常见形态并**拒绝非正数**。

        契约（issue #3586）：
        - 数值型直接取用；字符串数字（"3"）与**带单位**的合法输入（"3米"、"¥168.00"、
          "2.8 米"）按前导数字解析——用户口语里的"3米"就是数量 3，不能因为带单位拦掉；
        - 布尔值（True/False）不算数字（Python 里 bool 是 int 子类，必须显式排除）；
        - NaN / Infinity、空值、非数字文本 → None（交由调用方给出可行动提示）。

        Returns: float 值；无法解析返回 None。
        """
        if isinstance(raw, bool) or raw is None:
            return None
        if isinstance(raw, (int, float)):
            value = float(raw)
            return value if math.isfinite(value) else None
        if isinstance(raw, str):
            m = _NUMERIC_PREFIX_PATTERN.match(raw.strip())
            if not m:
                return None
            value = float(m.group("num"))
            return value if math.isfinite(value) else None
        return None

    @staticmethod
    def _reject_quantity(i: int, raw: Any) -> Optional[ToolResult]:
        """数量校验（issue #3586 + #3666 + #3682）：必须是 **≥ 1 的数**，小数合法（2.5 米 / 8.4 ㎡）。

        为什么在工具层 fail-fast：`order_items.quantity` 是**金额与库存的乘数**——
        负数量会算出**负金额**落库（下游 `createOrder` 不做正负判断），
        0 数量产出 0 元明细；且 Agent 路径的 admin-api 入参（AgentOrderItem）
        **未做 Bean Validation**，等 HTTP 回来才拒绝等于白跑一轮且提示不可行动。

        issue #3666 起**不再要求整数**：数量口径按计价方式（docs/testing/
        acceptance-protocol.md:225）——per_meter=米数、per_set=1、per_area=宽×高（㎡）。
        per_area 的合法面积就是小数（门幅 2.8m × 3m = 8.4 ㎡，刺绣工艺 30 元/㎡
        → 252.00 元），旧实现"拒绝小数 + 服务端截断成整数"会少收 12.00 元；
        服务端 `order_items.quantity` 已同步放宽为 DECIMAL(10,2)。

        issue #3682 把下限从「> 0」收紧为「≥ 1」：服务端 `OrderService` 对
        `BigDecimal quantity` 取整数部分（`:1051` 库存充足性校验 / `:1408` `deductStock` /
        `:1409` `increaseSalesCount`）——数量 0.5 时 `needed = 0` 校验**恒通过**、
        `deductStock(0)` **不减库存**、销量 **+0**，即**订单成交但库存/销量零变动且无告警**。
        旧实现（Integer + 拒绝非整数）会在下单前挡回 0.5 并给可行动提示，故 <1 是 #3666
        放宽后**新可达**的静默漏扣。裁定（issue #3682 方案 A）：agent 路径订单数量下限 = 1，
        与 admin-web 新建订单页的 `min={1}` 同口径 —— 半米不再是「静默漏扣」而是**可行动提示**。
        注意：下限只加在**驱动库存的 `items[].quantity` 上**；加工数量
        （`processingInfo.processingItems[].quantity`，per_area 可为 <1 ㎡）不设此下限。
        """
        value = OrderCreateTool._parse_positive_number(raw)
        if value is None:
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项数量无效",
                message=(
                    f"商品明细第 {i + 1} 项的数量「{raw}」不是有效数字。"
                    f"数量必须是**不小于 1 的数**（如 1、2.5、8.4），不要带单位或写成文字。"
                ),
                suggestion=(
                    "请把 quantity 改成不小于 1 的数（按计价方式给数：per_meter 给米数如 2.5，"
                    "per_area 给宽×高如 8.4，per_set/fixed 给 1；"
                    "若同一商品有多个规格，请拆成多行而不是把数量写在一行里"
                ),
            )
        if value < 1:
            negative = value < 0
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项数量不得小于 1",
                message=(
                    f"商品明细第 {i + 1} 项的数量是 {raw}，但下单数量**不得小于 1**（米/件）。"
                    "服务端的库存与销量按**整数件**记：数量小于 1 会被算成 0 件 —— "
                    "库存不扣减、销量 +0，订单却照样成交（库存账实不符、销量漏计），"
                    "而且全程没有任何告警。"
                    + (
                        f"负数还会把订单金额算成负数（{raw} × 单价），金额/对账跟着一起错。"
                        if negative else ""
                    )
                    + "因此系统在调用服务端**之前**就拒绝。"
                ),
                suggestion=(
                    f"请把 quantity 改成**不少于 1** 的数（可为小数，如 1、2.5、8.4）；"
                    + (
                        f"负数请改为正数 —— 顾客想要 {abs(value):g} 米就填 {abs(value):g}，"
                        "不要用 -1 之类的占位值表示退款或扣减（退款请用 order_manage 的 refund）。"
                        if negative else
                        "若顾客确实只要不到 1 米/件，请先与顾客确认数量后再下单"
                        "（系统按下单数量扣减整件库存，无法受理小于 1 的订单数量）。"
                    )
                ),
            )
        # issue #3666：小数数量（≥1）是**合法**的（per_meter 米数如 2.5 / per_area 面积如 8.4）
        return None

    @staticmethod
    def _reject_non_positive_amount(i: int, field: str, raw: Any) -> Optional[ToolResult]:
        """金额类字段校验（issue #3586）：单价/小计必须是 ≥ 0 的数，单价必须 > 0。

        admin-api `OrderCreateRequest.OrderItemRequest` 对 unitPrice/subtotal 标了
        `@Positive`（必须 > 0）；工具侧提前对齐，避免"注定被拒的调用白跑一轮"。
        """
        label = "单价" if field == "unit_price" else "小计"
        value = OrderCreateTool._parse_positive_number(raw)
        if value is None:
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项{label}无效",
                message=f"商品明细第 {i + 1} 项的{label}「{raw}」不是有效数字。",
                suggestion=f"请填写数字型{label}（元），如 168 或 168.00",
            )
        if value < 0:
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项{label}不能为负数",
                message=(
                    f"商品明细第 {i + 1} 项的{label}是 {raw}，订单{label}不能为负数"
                    f"（负金额会污染订单总额与财务对账）。"
                ),
                suggestion=(
                    f"请把 {field} 改成 ≥ 0 的数；折扣请走优惠金额，不要在明细里写负数"
                ),
            )
        if field == "unit_price" and value == 0:
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项单价必须大于 0",
                message=(
                    f"商品明细第 {i + 1} 项的单价是 0，服务端要求单价必须大于 0 元"
                    f"（免费的加工项应计 0 元加工费，但面料单价必须 > 0）。"
                ),
                suggestion="请向顾客确认单价后填写大于 0 的金额（如 168）；赠品请用 0 元加工项表达，不要整行 0 元",
            )
        return None

    @staticmethod
    def _reject_subtotal_below_product(i: int, quantity: float, unit_price: float,
                                       raw: Any) -> Optional[ToolResult]:
        """小计自洽校验（issue #3586）：subtotal 不得小于「数量 × 单价」。

        口径说明（不误伤）：**不要求严格相等**——本行业 subtotal = 面料金额 + 加工费
        （先例：OR-014 的 288 = 168×? 面料 + 打孔加工费），因此只拦"比面料金额还小"的
        自相矛盾值（少收钱 + 金额对不上账）。容差 0.01 吸浮点误差。
        """
        value = OrderCreateTool._parse_positive_number(raw)
        if value is None:
            return None  # 无法解析已在 _reject_non_positive_amount 覆盖
        expected = quantity * unit_price
        if value < expected - 0.01:
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项小计与数量×单价不符",
                message=(
                    f"商品明细第 {i + 1} 项：小计 {raw} < 数量 {quantity:g} × 单价 {unit_price:g} "
                    f"= {expected:.2f}，订单金额自相矛盾（会少收钱）。"
                ),
                suggestion=(
                    f"请把 subtotal 改为「数量 × 单价 + 加工费」= {expected:.2f} 起"
                    "（含加工费时应大于该值）；顾客打折请走优惠金额字段"
                ),
            )
        return None

    @staticmethod
    def _reject_invalid_amount(where: str, field_label: str, field_key: str, raw: Any,
                               impact: str) -> Optional[ToolResult]:
        """非负数值闸门（issue #3622）：负数/不可解析 → 本地拒绝（HTTP 之前 fail-fast）。

        覆盖面：`items[].width/height`（尺寸）、`processing_info.processingFee`、
        `processing_info.processingItems[].quantity/unitPrice/subtotal`。

        为什么在工具层拦：这些值直接进入金额/面积数学 —— 服务端
        `OrderService.sumProcessingFee()`（:824-829）就是 Σ `unitPrice × quantity`
        （`extractProcessingItems` :807-811 即这两字段相乘），**任一为负 → 负加工费**
        直接加进 `totalAmount` 落库（:417）；负尺寸则让 per_area 计价算出负面积。
        Agent 路径 DTO（`AgentOrderItem`）原先零约束注解、Controller 无 `@Valid` → 后端不拦。
        """
        value = OrderCreateTool._parse_positive_number(raw)
        if value is None:
            return ToolResult(
                success=False,
                error=f"{where}{field_label}无效",
                message=f"{where}的{field_label}「{raw}」不是有效数字。",
                suggestion=(
                    f"请把 {field_key} 改成数值型{field_label}（如 2.8 / 8 / 24.00），"
                    "不要写文字或「宽2.8」这类带前后缀的文本"
                ),
            )
        if value < 0:
            return ToolResult(
                success=False,
                error=f"{where}{field_label}不能为负数",
                message=(
                    f"{where}的{field_label}是 {raw}，不能为负数 —— {impact}。"
                ),
                suggestion=(
                    f"请把 {field_key} 改成 ≥ 0 的数值；顾客要减钱请走优惠金额字段，"
                    "不要用负数代表扣减"
                ),
            )
        return None

    @staticmethod
    def _reject_invalid_enum(where: str, field_label: str, field_key: str, raw: Any,
                             legal: tuple, impact: str = "") -> Optional[ToolResult]:
        """枚举闸门（issue #3622）：售卖方式/计价方式/工艺规格必须是**后端字面认得的**枚举值。

        刻意不做别名归一化（"散剪"→bulk_cut）：后端 `OrderService:1435` 是**按字面**
        eq 匹配 SKU 的，归一化会把"这个字段到底该传什么"的契约藏进工具层；而静默接受
        变体的代价是**静默不匹配**（SKU 匹配不到 → 库存校验/销量统计静默丢失）。
        所以拒绝 + 点名合法值，让 LLM 下一轮自愈。

        `impact`（issue #4346）：**后果说明**必须与该字段的真实后果一致 —— 工艺规格的后果是
        「取到错误工序路线」，不是「SKU 匹配不到」。默认文案只对 SKU 规格族成立。

        数值枚举（issue #4374）：`openCount` 这类**数值**枚举（1/2/4）走同一条闸门 ——
        严格按「类型 + 字面」比对：字符串 `"2"` 与布尔 `True` 都**不算** 2/1
        （刻意不做类型归一化，同「不做别名归一化」口径：静默接受变体的代价是
        **静默按错的开数算折数/余量**）。
        """
        if raw is None:
            return None  # 可选字段（单 SKU 商品不一定有售卖方式）
        if isinstance(raw, str) and raw in legal:
            return None
        if not isinstance(raw, str) and not isinstance(raw, bool) and raw in legal:
            return None
        # 括号提示**按字段族**分流：只有售卖方式/计价方式才有各自的补充说明。
        # （原实现用「非 sellingMethod 即计价方式」的二分 ⇒ 给部位/工艺串上
        #  「per_piece 按个不支持」这种**串味提示**，会误导 LLM 自愈方向。）
        if field_key.endswith("sellingMethod"):
            hint = "（散剪=bulk_cut、整卷=full_roll）"
        elif field_key.endswith("pricingMethod"):
            hint = "（per_piece 按个不支持，issue #3005）"
        else:
            hint = ""
        # 取值来源**按字段族**分流：数值枚举（openCount）不来自 product_detail，
        # 照抄 SKU 规格族的「product_detail 返回的原值」会误导 LLM 去查商品详情。
        if all(isinstance(v, str) for v in legal):
            suggestion = f"请改用 product_detail 返回的**原值**：{' / '.join(legal)}{hint}"
        else:
            suggestion = (
                f"请改用合法值：{' / '.join(str(v) for v in legal)}{hint}"
                "（必须是**数值**型，字符串「2」不算 2）"
            )
        return ToolResult(
            success=False,
            error=f"{where}{field_label}无效",
            message=(
                f"{where}的{field_label}是「{raw}」，不是后端认得的合法值。"
                + (impact or (
                    "拼写变体会被**静默**当成另一个规格：SKU 匹配按字面比较 → 匹配不到 → "
                    "库存校验与销量统计静默丢失。"
                ))
            ),
            suggestion=suggestion,
        )

    @staticmethod
    def _validate_processing_info(i: int, pinfo: Any) -> Optional[ToolResult]:
        """`processing_info` 内的范围/枚举闸门（issue #3622）。

        只在 pinfo 是 dict 时校验：JSON 字符串形态是老契约（服务端 `extractProcessingItems`
        自己解析），工具侧不臆断其内容，避免误报。
        """
        if not isinstance(pinfo, dict):
            return None
        where = f"商品明细第 {i + 1} 项"
        rejected = OrderCreateTool._reject_invalid_enum(
            where, "售卖方式", "processing_info.sellingMethod",
            pinfo.get("sellingMethod"), _SELLING_METHODS)
        if rejected is not None:
            return rejected
        # 工艺规格枚举闸门（issue #4346 / 设计文档 §4.2 · §4.8）：部位/工艺错值会取到
        # **错误工序路线**（实证 V58：纱帘订单拿到布帘的 11 道工序，工序与工资全错）。
        # 键缺席一律放行（可选透传，不得变成硬门槛 —— 存量单/普通商品没有这些键）。
        craft_spec_impact = (
            "错值会让加工单取到**错误工序路线**（实证 V58：纱帘订单拿到布帘的 11 道工序，"
            "工序与工资全错）。"
        )
        for label, key, legal in (
            ("部位/帘种", "curtainType", _CURTAIN_TYPES),
            ("安装工艺", "craft", _CRAFTS),
            ("明细行角色", "componentRole", _COMPONENT_ROLES),
            ("款式", "style", _STYLES),
            ("配布边米数来源", "metersSource", _METERS_SOURCES),
            # 写侧补全（issue #4374 / 设计文档 §4.2）：加工类型与打开方式错值同样会
            # 让加工单取到**错误工序路线**（加工类型还决定定高/定宽买料口径）。
            ("加工类型", "cuttingMode", _CUTTING_MODES),
            ("打开方式", "openCount", _OPEN_COUNTS),
            # 取值来源（真值源 §8 要求「必须带来源，防多渠道不一致」）——
            # 写「formula」这类**算料侧英文**值不算带来源：落库后没人知道那是哪个口径。
            ("取值来源", "source", _SOURCES),
        ):
            rejected = OrderCreateTool._reject_invalid_enum(
                where, label, f"processing_info.{key}", pinfo.get(key), legal,
                impact=craft_spec_impact)
            if rejected is not None:
                return rejected
        # 算料输出/工艺规格的**数值键非负**（issue #4374 交付物 4）：负米数/负幅数会一路写进订单，
        # 加工单按它算数量 ⇒ 负用料。键缺席一律放行（可选透传，不得变成硬门槛）。
        for key, label in _CRAFT_SPEC_NUMBERS + _CALC_OUTPUT_LABELS:
            if pinfo.get(key) is None:
                continue
            rejected = OrderCreateTool._reject_invalid_amount(
                where, label, f"processing_info.{key}", pinfo.get(key),
                f"负{label}会让加工单按负数算料/展示（订单与算料输出自相矛盾）")
            if rejected is not None:
                return rejected
        if pinfo.get("processingFee") is not None:
            rejected = OrderCreateTool._reject_invalid_amount(
                where, "加工费", "processing_info.processingFee", pinfo.get("processingFee"),
                "负加工费会把订单总额拉低（顾客少付钱、财务对账对不上）")
            if rejected is not None:
                return rejected
        raw_items = pinfo.get("processingItems")
        if raw_items is None:
            return None
        if not isinstance(raw_items, list):
            return ToolResult(
                success=False,
                error=f"{where}加工项格式错误",
                message=(
                    f"{where}的 processing_info.processingItems 不是列表"
                    f"（{type(raw_items).__name__}），服务端解析不出加工项与加工费。"
                ),
                suggestion="请把 processingItems 写成列表，每项为对象：{name, unitPrice, quantity, pricingMethod}",
            )
        for j, entry in enumerate(raw_items):
            entry_where = f"{where}加工项第 {j + 1} 项"
            if not isinstance(entry, dict):
                return ToolResult(
                    success=False,
                    error=f"{entry_where}格式错误",
                    message=(
                        f"{entry_where}不是对象，服务端 `extractProcessingItems` 会跳过它"
                        " → 该加工费被静默丢弃（顾客少收钱）。"
                    ),
                    suggestion="请把每个加工项写成对象：{name, unitPrice, quantity, pricingMethod}",
                )
            rejected = OrderCreateTool._reject_invalid_enum(
                entry_where, "计价方式", "processingItems[].pricingMethod",
                entry.get("pricingMethod"), _PRICING_METHODS)
            if rejected is not None:
                return rejected
            for field_key, label, impact in (
                ("quantity", "数量", "负数量的加工费是负数（服务端按 unitPrice × quantity 计费）"),
                ("unitPrice", "单价", "负单价的加工费是负数（服务端按 unitPrice × quantity 计费）"),
                ("subtotal", "小计", "负小计与加工费口径自相矛盾（确认卡金额与落库金额对不上）"),
            ):
                if entry.get(field_key) is None:
                    continue
                rejected = OrderCreateTool._reject_invalid_amount(
                    entry_where, label, f"processingItems[].{field_key}",
                    entry.get(field_key), impact)
                if rejected is not None:
                    return rejected
        return None

    @staticmethod
    def _validate_item_value_bounds(i: int, item: Dict[str, Any]) -> Optional[ToolResult]:
        """单行明细的**数值语义 + 枚举**校验：在发 HTTP 之前 fail-fast。

        覆盖面（issue #3586）：quantity（≥ 1 的数，可为小数；issue #3682 收紧下限）、
        unit_price（> 0）、subtotal（≥ 0 且 ≥ 数量×单价）。
        覆盖面（issue #3622，同族残留）：product_name 非空、width/height（≥ 0）、
        processing_info 的 sellingMethod 枚举 / processingFee（≥ 0）/
        processingItems[].pricingMethod 枚举与 quantity/unitPrice/subtotal（≥ 0）。
        只做确定性判定（无 LLM、无网络），保证"注定失败的调用"不产生 HTTP 往返，
        也保证「闸门放行的值 = 服务端能接受的值」。
        """
        # 商品名称必须非空（#3622：原先只判「字段存在 or None」→ 空串可一路下单）
        raw_name = item.get("product_name")
        if isinstance(raw_name, str) and not raw_name.strip():
            return ToolResult(
                success=False,
                error=f"商品明细第 {i + 1} 项商品名称为空",
                message=(
                    f"商品明细第 {i + 1} 项的 product_name 是空字符串 —— 空商品名的订单"
                    "无法在列表/对账里定位商品，也无法作为售后凭证。"
                ),
                suggestion=(
                    "请填写顾客所选商品的名称（与 product_detail 返回的商品名一致），"
                    "不要用空串占位"
                ),
            )
        for field, label in (("quantity", "数量"), ("unit_price", "单价"), ("subtotal", "小计")):
            if field not in item or item.get(field) is None:
                return None  # 缺字段由必填检查给出提示（此处不重复报错）
        rejected = OrderCreateTool._reject_quantity(i, item.get("quantity"))
        if rejected is not None:
            return rejected
        rejected = OrderCreateTool._reject_non_positive_amount(i, "unit_price", item.get("unit_price"))
        if rejected is not None:
            return rejected
        rejected = OrderCreateTool._reject_non_positive_amount(i, "subtotal", item.get("subtotal"))
        if rejected is not None:
            return rejected
        quantity = OrderCreateTool._parse_positive_number(item.get("quantity"))
        unit_price = OrderCreateTool._parse_positive_number(item.get("unit_price"))
        rejected = OrderCreateTool._reject_subtotal_below_product(
            i, quantity or 0.0, unit_price or 0.0, item.get("subtotal")
        )
        if rejected is not None:
            return rejected
        # 尺寸（#3622，可选）：负尺寸 → per_area 负面积
        for field, label, impact in (
            ("width", "宽度", "负宽度会让按面积（per_area）计价算出负面积"),
            ("height", "高度", "负高度会让按面积（per_area）计价算出负面积"),
        ):
            if item.get(field) is None:
                continue
            rejected = OrderCreateTool._reject_invalid_amount(
                f"商品明细第 {i + 1} 项", label, field, item.get(field), impact)
            if rejected is not None:
                return rejected
        # 加工信息（#3622）：售卖方式/加工费/加工项数量与单价
        return OrderCreateTool._validate_processing_info(i, item.get("processing_info"))

    @staticmethod
    def _otp_key(phone: str, tenant_id: int) -> str:
        """构造 SMS 验证码 Redis key"""
        return f"{_OTP_KEY_PREFIX}{tenant_id}:{phone}"

    @staticmethod
    async def _verify_sms_code(phone: str, code: str, tenant_id: int) -> bool:
        """验证短信验证码

        从 Redis 读取已存储的验证码并比对。
        验证成功后删除验证码（一次性使用）。

        Args:
            phone: 客户手机号
            code: 用户输入的验证码
            tenant_id: 租户ID

        Returns:
            bool: 验证是否通过
        """
        # 万能验证码 bypass：POC/测试阶段直接通过（不碰 Redis）。
        # 生产环境须将 SMS_BYPASS_CODE 设为空以禁用。
        if SMS_BYPASS_CODE and code and code.strip() == SMS_BYPASS_CODE:
            logger.info(f"[sms_verify] Bypass code accepted: phone={phone[:3]}****{phone[-4:]}, tenant={tenant_id}")
            return True

        if not _OTP_VALID_PATTERN.match(code or ""):
            return False

        try:
            redis_client = RedisClient()
            key = OrderCreateTool._otp_key(phone, tenant_id)
            stored_code = await redis_client.get(key)

            if stored_code and stored_code.strip() == code.strip():
                # 验证成功后删除，防止重复使用
                await redis_client.delete(key)
                logger.info(f"[sms_verify] Code verified: phone={phone[:3]}****{phone[-4:]}, tenant={tenant_id}")
                return True

            logger.warning(f"[sms_verify] Code mismatch: phone={phone[:3]}****{phone[-4:]}, tenant={tenant_id}")
            return False
        except Exception as e:
            logger.error(f"[sms_verify] Redis error: {type(e).__name__}: {e}", exc_info=True)
            return False

    @staticmethod
    async def _store_sms_code(phone: str, code: str, tenant_id: int) -> bool:
        """存储短信验证码到 Redis

        由 SMS 发送工具调用，存储生成的验证码。

        Args:
            phone: 客户手机号
            code: 生成的验证码
            tenant_id: 租户ID

        Returns:
            bool: 存储是否成功
        """
        try:
            redis_client = RedisClient()
            key = OrderCreateTool._otp_key(phone, tenant_id)
            await redis_client.set(key, code, ttl=_OTP_TTL_SECONDS)
            logger.info(f"[sms_store] Code stored: phone={phone[:3]}****{phone[-4:]}, tenant={tenant_id}")
            return True
        except Exception as e:
            logger.error(f"[sms_store] Redis error: {type(e).__name__}: {e}", exc_info=True)
            return False

    # ── 确认卡↔落库一致性（issue #4037 / F22）────────────────────────────────
    # 今日线上实证：顾客点确认卡看到 **¥498（10 米/2.8 米/3 加工项）**，落库却是
    # **¥133.80（1 米/3.2 米/2 加工项 + 优惠 ¥5）**。根因不是"某处算错"，
    # 而是**卡上的事实与写工具参数是两份独立产物**：`interact(confirm, fields=…)`
    # 的 fields 由模型自由书写，`order_create` 的 items 也由模型自由书写，
    # 两者之间只有 prompt 里的口头约定 —— **全系统无一处校验两者一致**。
    # 修法（确定性层，零 LLM）：顾客确认那一刻把金额事实快照进会话状态
    # （`confirmed_order_facts`），本工具在**调用服务端之前**重算并与快照比对。
    #
    # 事实只取**驱动金额与库存的规范值**：手机号 + 每行 名称/数量/单价/加工费。
    # 为什么不取 subtotal/total：服务端**本来就按 quantity×unitPrice（+加工明细）重算**
    # （`OrderService.createOrderForAgent` 强制重算 subtotal），把重算值也塞进比对
    # 只会制造假红；金额对不对由服务端与 `amount_verify` 负责，本守护负责的是
    # **"顾客确认的那份明细 = 真正要执行的那份明细"**（这是落库前最后的确定性关口）。
    # 为什么不比对地址/备注/尺寸等非金额字段：确认后补收货地址/验证码/门幅是**正常流程**，
    # 让它们参与比对 = 把合法输入拦掉（R2 反例，OR-014 单价闸门踩过的坑）。
    def _needs_sms_verification(self, context: ToolContext) -> bool:
        """判断是否需要 SMS 验证

        只有 customer 角色需要短信验证。
        admin/agent/tenant_admin 帮客户下单时跳过。
        """
        return context.role == "customer"

    # ── 下单单价「接地」校验：工具级 fail-closed（issue OR-014，判定跑 34923425338）──
    # 红证：mibao 腿 agent 报「米白 ¥150/米」，order_create(遮光窗帘×3@150) 成功落单，
    # amount_verify 抓「单价 150 ≠ 商品库 168」。为什么改前拦不住（两处 fail-open 叠加）：
    #   ① ai-agent 闸门（base_skill 下单接地闸门）：B 端（order skill）**未接地**时
    #      unit_price_grounding_error(items, {}) 库价未知 → 放行（未接地拦截仅保留 C 端）；
    #   ② 服务端守卫（OrderService.validateAgentItemUnitPrice）：明细**只有 product_name**、
    #      无 productId + skuCode/colorName → 解析不到唯一 SKU → fail-open。
    # 本方法在**调用服务端之前**按商品库解析权威价（不依赖会话接地状态）：
    #   · 按 product_id / product_name（唯一匹配）查商品详情 → price + skus；
    #   · 分色差价（SKU 价不唯一）⇒ 必须按 items 的 processing_info.colorName/skuCode
    #     匹配 SKU；匹配不到 = 配置错误级拒绝；
    #   · unit_price ≠ 权威价（容差 0.01）⇒ 拦截并回填库价（error=unit_price_not_grounded）；
    #   · 商品库查不到该商品 / 查询失败 ⇒ 拒绝（fail-closed：拒绝比放行安全，给可行动话术）；
    #   · 加工项 customPrice / processingItems 属加工费，**不入**本校验域（只核对 unit_price）。
    _UNIT_PRICE_TOLERANCE = 0.01

    @staticmethod
    def _library_price_of(detail: dict) -> Optional[float]:
        """商品详情 → 商品级库价（price/basePrice 兼容 admin-api 两种命名）。"""
        for key in ("price", "basePrice", "base_price"):
            v = detail.get(key)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _library_skus_of(detail: dict) -> list:
        """商品详情 → SKU 扁平快照（color_name/sku_code/price），与接地快照同构。"""
        skus = []
        for sk in (detail.get("skus") or []):
            if not isinstance(sk, dict):
                continue
            skus.append({
                "color_name": str(sk.get("colorName") or sk.get("color_name") or ""),
                "sku_code": str(sk.get("skuCode") or sk.get("sku_code") or ""),
                "price": sk.get("price"),
            })
        return skus

    async def _reject_unit_price_not_grounded(self, context: ToolContext,
                                              items: List[Dict[str, Any]]) -> Optional[ToolResult]:
        """执行前按商品库校验 items 单价（fail-closed，零 LLM 确定性判定）。

        返回拦截 ToolResult（error=unit_price_not_grounded / 配置错误级拒绝），
        全部行与库价一致（或非本工具校验域的加工项）时返回 None。
        """
        # 复用**中性模块**的判据纯函数（含 SKU 匹配与回填话术），工具层只负责
        # 「从商品库解析权威快照」——同一判据单点，避免两处口径漂移。
        # 函数级 import：tools 是叶子模块，避免模块加载顺序依赖。
        # ⚠️ 判据定义在 `app/utils/sku_price.py`（中性层）：工具层**不得**反向 import
        # skill 层（`app.graph.skills.base_skill`）的私有符号（issue #4057 S7）；
        # 守卫见 tests/test_utils_sku_price.py。
        from app.utils.sku_price import unit_price_grounding_error
        from app.utils.sku_price import _match_sku_price
        from app.utils.sku_price import _library_unit_price_grounded

        client = get_admin_api_client()
        # 同单多行同商品只查一次（grounded 快照按 product_id 或 product_name 缓存）
        _grounded_cache: Dict[str, dict] = {}
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            pid = str(item.get("product_id") or "").strip()
            name = str(item.get("product_name") or "").strip()
            if not pid and not name:
                # 缺商品标识由上方必填/空名校验兜底（此处不重复报错）
                continue
            cache_key = pid or name
            grounded = _grounded_cache.get(cache_key)
            if grounded is None:
                grounded, resolve_err = await self._resolve_library_grounded(
                    context, client, pid, name)
                if resolve_err is not None:
                    return resolve_err
                if grounded is None:
                    return ToolResult(
                        success=False,
                        error="unit_price_not_grounded",
                        message=(
                            f"下单被拦截：商品「{name or pid}」在商品库中**查不到库价**，"
                            "单价无从核对（拒绝比放行安全）。"
                            "请先用 product_search / product_detail 确认商品存在及其库价，"
                            "再按库价重新下单。"
                        ),
                        suggestion=(
                            "先调 product_search(keyword=商品名) → product_detail(product_id=…)"
                            "拿到 price 后，用该价格作为 unit_price 重新下单"
                        ),
                    )
                _grounded_cache[cache_key] = grounded
            # 分色差价（SKU 价不唯一）⇒ 必须按所选规格匹配 SKU；匹配不到 = 配置错误级拒绝
            sku_prices = {
                float(s.get("price")) for s in grounded.get("skus") or []
                if isinstance(s, dict) and s.get("price") is not None
            }
            if len(sku_prices) > 1:
                pinfo = item.get("processing_info")
                has_spec = isinstance(pinfo, dict) and bool(
                    pinfo.get("colorName") or pinfo.get("skuCode"))
                if has_spec and _match_sku_price(grounded, item) is None:
                    return ToolResult(
                        success=False,
                        error="unit_price_not_grounded",
                        message=(
                            f"商品明细第 {i + 1} 项「{name}」所选规格"
                            f"（{pinfo.get('colorName') or pinfo.get('skuCode')}）"
                            "在商品库 SKU 中匹配不到 —— 配置错误级拒绝：无法确定该行库价。"
                        ),
                        suggestion="用 product_detail 返回的 skus[].color_name / sku_code 重新填写规格",
                    )
                # 未指定规格 ⇒ 「库价无从唯一确定」，**不等于**「单价编造」（issue #4011）：
                # 只要该单价确实来自商品库（商品级 price 或某个 SKU 价）就不得 fail-closed ——
                # 改前这里无条件拒绝，连正确的 @168 也拒，OR-014 首跑 13 次调用无一成功（死锁）。
                # 真编造价（不在库价集合内）不再放行，拒绝话术**列出全部库价**供模型自愈。
                if not has_spec:
                    up = self._parse_positive_number(item.get("unit_price"))
                    if up is not None and not _library_unit_price_grounded(grounded, up):
                        return ToolResult(
                            success=False,
                            error="unit_price_not_grounded",
                            message=(
                                f"商品明细第 {i + 1} 项「{name}」存在**多个规格价**"
                                f"（{'/'.join(sorted(f'{p:g}' for p in sku_prices))}，"
                                f"商品级库价 {self._library_price_of(grounded):g}），"
                                f"而该行单价 {item.get('unit_price')} **不在库价集合内** —— 编造价拒绝。"
                                "请按所选规格填写 processing_info.colorName / skuCode，"
                                "并把 unit_price 改为该规格的库价（subtotal 同步 = 数量×单价）。"
                            ),
                            suggestion=(
                                "先 product_detail 取 skus[].color_name/sku_code 与价格，"
                                "把规格填进 processing_info、单价改成所选规格库价后重新下单"
                            ),
                        )
            # 判据复用：名称/ID 匹配 + SKU 价或商品价 + 容差 + 回填话术
            err = unit_price_grounding_error([item], grounded)
            if err:
                return ToolResult(
                    success=False,
                    error="unit_price_not_grounded",
                    message=f"下单被拦截（单价与商品库不符）：{err}",
                    suggestion="把 unit_price 改为商品库价（含 subtotal 同步 = 数量 × 单价）后重新下单",
                )
        return None

    async def _resolve_library_grounded(self, context: ToolContext, client, pid: str,
                                        name: str) -> tuple:
        """从商品库解析接地快照 {product_id, name, price, skus}。

        Returns: (grounded|None, ToolResult|None)
          - grounded=None, resolve_err=None  ⇒ 商品不存在/无库价（调用方统一话术拒绝）
          - resolve_err 非 None               ⇒ 名称不唯一 / 查询失败（带具体话术拒绝）
        """
        detail = None
        try:
            if pid:
                resp = await client.get(
                    f"/api/admin/products/{pid}",
                    tenant_id=context.tenant_id, user_id=context.user_id)
                if resp.get("success"):
                    detail = resp.get("data") or {}
            elif name:
                resp = await client.get(
                    "/api/admin/products",
                    params={"keyword": name, "page": 1, "size": 10},
                    tenant_id=context.tenant_id, user_id=context.user_id)
                records = ((resp.get("data") or {}).get("items") or []) if resp.get("success") else []
                exact = [r for r in records if str(r.get("name") or "") == name]
                if len(exact) > 1:
                    return None, ToolResult(
                        success=False,
                        error="unit_price_not_grounded",
                        message=(
                            f"商品名「{name}」在商品库中**不唯一**（{len(exact)} 条），"
                            "无法确定库价。请先用 product_search / product_detail "
                            "确认 product_id 后，在下单 items 中带上 product_id 再下单。"
                        ),
                        suggestion="同名商品在库中不唯一，请先用 product_search 让用户确认具体是哪一款，再用该商品下单",
                    )
                if len(exact) == 1:
                    rid = exact[0].get("id")
                    if rid:
                        rd = await client.get(
                            f"/api/admin/products/{rid}",
                            tenant_id=context.tenant_id, user_id=context.user_id)
                        if rd.get("success"):
                            detail = rd.get("data") or {}
        except Exception as e:
            return None, ToolResult(
                success=False,
                error="unit_price_not_grounded",
                message=(
                    "下单被拦截：核对商品库价时服务异常"
                    f"（{type(e).__name__}），无法确认单价（拒绝比放行安全）。"
                    "请先 product_search / product_detail 确认商品与库价，"
                    "再核实这笔订单是否已经建好（不要盲目重复下单）。"
                ),
                suggestion="请稍后重试；重试前先用 product_search / product_detail 确认商品与库价，不要凭记忆填单价下单",
            )
        if not detail:
            return None, None
        grounded = {
            "product_id": str(detail.get("id") or pid or ""),
            "name": str(detail.get("name") or name or ""),
            "price": self._library_price_of(detail),
            "skus": self._library_skus_of(detail),
        }
        if grounded["price"] is None and not grounded["skus"]:
            return None, None
        return grounded, None

    async def execute(
        self,
        context: ToolContext,
        customer_name: str,
        customer_phone: str,
        items: List[Dict[str, Any]],
        sms_code: Optional[str] = None,
        customer_address: Optional[str] = None,
        remark: Optional[str] = None,
    ) -> ToolResult:
        """执行创建订单操作

        Args:
            context: Tool 执行上下文
            customer_name: 客户姓名
            customer_phone: 客户电话
            items: 商品明细列表
            sms_code: 短信验证码（customer角色必填）
            customer_address: 客户收货地址（可选）
            remark: 订单备注（可选）

        Returns:
            ToolResult: 创建结果
        """
        # 权限检查
        if not self.check_permission(context):
            return ToolResult(
                success=False,
                error="权限不足",
                message="您没有权限创建订单",
                suggestion="请联系管理员获取订单创建权限",
            )

        # 参数校验
        if not customer_name:
            return ToolResult(
                success=False,
                error="缺少客户姓名",
                message="创建订单时必须提供客户姓名（customer_name）",
                suggestion="请提供客户的姓名",
            )

        if not customer_phone:
            return ToolResult(
                success=False,
                error="缺少客户电话",
                message="创建订单时必须提供客户电话（customer_phone）",
                suggestion="请提供客户的联系电话",
            )

        # 对抗编程：校验手机号格式，防止 LLM 编造号码
        if not _PHONE_PATTERN.match(customer_phone.strip()):
            return ToolResult(
                success=False,
                error="手机号格式无效",
                message=f"手机号 {customer_phone} 格式不正确，请输入 11 位中国大陆手机号",
                suggestion="请确认客户手机号是否正确",
            )

        if not items or not isinstance(items, list):
            return ToolResult(
                success=False,
                error="缺少商品明细",
                message="创建订单时必须提供商品明细列表（items）",
                suggestion="请提供至少一件商品的信息（名称、数量、单价）",
                missing_params=["items"],
            )

        # 校验每个商品项
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                return ToolResult(
                    success=False,
                    error=f"商品明细第 {i + 1} 项格式错误",
                    message=f"商品明细第 {i + 1} 项必须是对象，包含 product_name、quantity、unit_price、subtotal",
                    suggestion="商品明细每项必须是对象，请按 product_name / quantity / unit_price / subtotal 重新组织后重试",
                )
            required_fields = ["product_name", "quantity", "unit_price", "subtotal"]
            for field in required_fields:
                if field not in item or item[field] is None:
                    return ToolResult(
                        success=False,
                        error=f"商品明细第 {i + 1} 项缺少 {field}",
                        message=f"商品明细第 {i + 1} 项缺少必填字段：{field}",
                        suggestion="商品明细缺必填字段，请补齐 product_name / quantity / unit_price / subtotal 后重试",
                    )
            # 数值语义闸门（issue #3586）：数量/单价/小计的正负与量级 —— 在发 HTTP 之前拒绝。
            # 负数量会算出负金额落库（下游 createOrder 不做正负判断、Agent 路径 DTO 无 Bean Validation），
            # 库存校验也会被负需求绕过；0 数量则产出 0 元明细。fail-fast 且给可行动 suggestion。
            _bounds_reject = self._validate_item_value_bounds(i, item)
            if _bounds_reject is not None:
                return _bounds_reject

        # ── 缺参的**结构化**形态（issue #4080 T3）──
        # 下面 4 个失败点（缺少商品明细 / 缺少短信验证码 / 验证码格式无效 / 验证码错误或已过期）
        # 此前是「缺哪个参数」判据的**唯一生产者**，而消费端靠**中文错误原文子串**反推
        # （`WRITE_INPUT_ERROR_PARAMS` + `key in text`）⇒ 错误文案改一个字，判据静默失效。
        # 现在每个失败点**直接带上 `missing_params`**，消费端只读结构化字段。
        # Gap-1 安全加固: SMS 验证码校验（仅 customer 角色需要）。
        # ⚠️ 顺序铁律（issue #3586）：纯本地的**确定性**校验（明细格式/数量/金额）必须排在
        # SMS 之前 —— 前者零成本零副作用，后者要读 Redis；参数本身就非法时不该先产生
        # 一次验证码往返（也不该因为「验证码错误」掩盖真正的参数错误）。
        if self._needs_sms_verification(context):
            if not sms_code:
                return ToolResult(
                    success=False,
                    error="缺少短信验证码",
                    message="为了您的账户安全，创建订单前需要验证手机号。请输入短信验证码",
                    suggestion="请先请求发送短信验证码到您的手机，然后提供收到的验证码",
                    missing_params=["sms_code"],
                )
            if not _OTP_VALID_PATTERN.match(sms_code):
                return ToolResult(
                    success=False,
                    error="验证码格式无效",
                    message="短信验证码为4-6位数字，请检查后重新输入",
                    suggestion="请输入您收到的4-6位数字验证码",
                    missing_params=["sms_code"],
                )
            verified = await self._verify_sms_code(
                phone=customer_phone,
                code=sms_code,
                tenant_id=context.tenant_id,
            )
            if not verified:
                return ToolResult(
                    success=False,
                    error="验证码错误或已过期",
                    message="短信验证码错误或已过期，请重新获取验证码",
                    suggestion="请重新请求发送短信验证码，并在5分钟内完成验证",
                    missing_params=["sms_code"],
                )

        # ── 同一张单里出现**完全相同的商品行** → fail-closed（issue #3392，DB 实证）──
        # 实证（run 34747025719）：新客用例 OR-022 期望 3 米（168×3 + 打孔 8×3 = ¥528），
        # 落库却是 ¥1584（9×168 + 9×8）与 ¥1056（6×168 + 6×8）—— 数量按**确认轮次累加**
        # （3 → 6 → 9，即 3 的倍数），顾客会被多收 2~3 倍的钱，且全链路无告警。
        # 判据取"**完全相同的行**"（名称/单价/小计/规格字段逐一相等）：正常订单里同商品
        # 不同规格（颜色/门幅）会有区分字段，完全重复只可能是重复提交/累加。
        # 为什么在工具层拦：这是**钱的正确性**，不能指望模型自己发现；拦下并明确告诉它
        # "合并成一行、数量取合计"，模型下一轮即可自愈（比静默多收钱好得多）。
        _dup_key_seen: Dict[str, int] = {}
        for _i, _it in enumerate(items):
            if not isinstance(_it, dict):
                continue
            _sig = json.dumps({
                "name": str(_it.get("product_name") or ""),
                "unit_price": str(_it.get("unit_price")),
                "subtotal": str(_it.get("subtotal")),
                "product_id": str(_it.get("product_id") or ""),
                "width": str(_it.get("width") or ""),
                "height": str(_it.get("height") or ""),
                "processing_info": json.dumps(_it.get("processing_info"), ensure_ascii=False,
                                              sort_keys=True, default=str),
            }, ensure_ascii=False, sort_keys=True)
            if _sig in _dup_key_seen:
                _first = _dup_key_seen[_sig] + 1
                return ToolResult(
                    success=False,
                    error="商品明细存在重复行",
                    message=(
                        f"商品明细第 {_i + 1} 项与第 {_first} 项**完全相同**"
                        f"（{_it.get('product_name')} ×{_it.get('quantity')}，"
                        f"单价 {_it.get('unit_price')}）—— 同一张订单里不应出现完全相同的两行，"
                        f"否则顾客会被**重复计费**。"
                        f"请把数量合并成**一行**（该行 quantity = 各行数量之和）后重新提交。"
                    ),
                    suggestion=("合并重复行：同一商品/规格只保留一行，数量取合计；"
                                "例如 3 米不要写成三行各 1 米或三行各 3 米"),
                )
            _dup_key_seen[_sig] = _i

        # ── 单价接地校验（issue OR-014，工具级 fail-closed）──
        # 判定跑 34923425338（main 7d930e34）B 端 OR-014 红证：agent 报「米白 ¥150/米」、
        # order_create(遮光窗帘×3@150) 成功落单 —— ai-agent 闸门在 B 端未接地时跳过单价
        # 校验、服务端守卫对仅商品名的明细 fail-open ⇒ 150 一路落库。此处无论会话接地
        # 状态如何，都在调用服务端**之前**按商品库解析权威价（product_id/product_name →
        # price 或所选 SKU 的 skus[].price），不一致 ⇒ 拦截并回填库价；查不到 ⇒ 拒绝。
        # 位置在全部本地确定性校验（bounds/SMS/dup）之后：网络查询只对**注定要发**的单做，
        # 不改变既有校验的 fail-fast 语义；错价单在此被拦，不再触达服务端。
        _price_reject = await self._reject_unit_price_not_grounded(context, items)
        if _price_reject is not None:
            return _price_reject

        try:
            # 构建请求体（admin-api 使用 camelCase）
            # 对抗编程：透传 LLM 提供的所有字段，避免静默丢弃 productId/width/height/processingInfo
            items_payload = []
            for item in items:
                # 数值已在上方 _validate_item_value_bounds 校验（正数/非负金额），
                # 这里用解析值而非裸 int()/float() —— 让 "3米" 这类带单位输入落成 3，
                # 避免 int("3米") 抛 ValueError 走异常兜底（错误提示不可行动）。
                # issue #3666：quantity 保留小数（旧 int() 会把 per_area 的 8.4 截断成 8）。
                entry: Dict[str, Any] = {
                    "productName": item["product_name"],
                    "quantity": self._parse_positive_number(item["quantity"]),
                    "unitPrice": self._parse_positive_number(item["unit_price"]),
                    "subtotal": self._parse_positive_number(item["subtotal"]),
                }
                # 透传可选字段 — 不信任 LLM 一定传，但传了就不能丢
                for py_key, java_key in [
                    ("product_id", "productId"),
                    ("width", "width"),
                    ("height", "height"),
                    ("processing_info", "processingInfo"),
                ]:
                    value = item.get(py_key)
                    if value is None:
                        continue
                    # 尺寸已在 _validate_item_value_bounds 里按「容忍单位」的口径解析过：
                    # 这里发**数值**（"2.8米" → 2.8），否则 Java BigDecimal 解析失败 → 白跑一轮 HTTP。
                    if py_key in ("width", "height"):
                        value = self._parse_positive_number(value)
                    entry[java_key] = value
                items_payload.append(entry)

            json_data: Dict[str, Any] = {
                "customerName": customer_name,
                "customerPhone": customer_phone,
                "items": items_payload,
            }

            if customer_address:
                json_data["customerAddress"] = customer_address
            if remark:
                json_data["remark"] = remark

            logger.info(
                f"[order-create] Creating order: customer={customer_name}, "
                f"items_count={len(items)} | tenant={context.tenant_id}"
            )

            client = get_admin_api_client()
            response = await client.post(
                "/api/admin/agent/orders",
                json_data=json_data,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                # 幂等键（issue #4037 / F19；作用域 = **会话**，issue #4195；维度 = **操作**，
                # issue #4212）：服务端按 `(tenant_id, clientRequestId)` 去重（**不含 endpoint**）。
                # 同一会话同一重试窗内取值相同 ⇒ 「落库了但报失败」后模型重试 ⇒ **只落一单**
                # （回放首次结果，见 admin-api `ClientRequestIdService`）；不同会话取值不同 ⇒
                # 不再把别人的订单当重试回放；`op=ORDER_CREATE_OP` ⇒ 不再与售后/转人工端点撞键。
                headers={CLIENT_REQUEST_ID_HEADER: _request_window_id(context, op=ORDER_CREATE_OP)},
            )

            if not response.get("success"):
                error_msg = response.get("error", {}).get("message", "创建失败")
                return admin_api_failure(response,
                    error=error_msg,
                    message=f"创建订单失败：{error_msg}",
                    suggestion="请先用 product_detail 确认商品在架与库价、并核对数量，再重新提交下单",
                )

            order_data = response.get("data", {})
            order_id = order_data.get("id") or order_data.get("orderNo") or ""
            # 顾客/客服认的是**订单号**（ORD-xxx），播报优先用它（内部 UUID 只作兜底）
            order_ref = order_data.get("orderNo") or order_id

            # 回放（同键去重命中）：这次并没有新建订单，顾客看到的仍是**同一张单**
            # —— 必须显式说清，否则模型会把重试播报成"又下了一单"（一单说成两单）。
            if order_data.get("replayed"):
                logger.info(
                    f"[order-create] 幂等回放（同 clientRequestId）：order_id={order_id} "
                    f"| tenant={context.tenant_id}"
                )
                return ToolResult(
                    success=True,
                    data=order_data,
                    message=(f"这笔订单**此前已经创建成功**（订单号：{order_ref}，客户：{customer_name}），"
                             f"刚刚的重复提交已被系统拦下，**没有重复下单**。"),
                    summary=f"订单已存在（幂等回放）: 订单号{order_ref}, 客户{customer_name}",
                    terminal=True,
                )

            logger.info(
                f"Order created: order_id={order_id}, customer={customer_name}, "
                f"items_count={len(items)} | tenant={context.tenant_id}, user={context.user_id}"
            )

            return ToolResult(
                success=True,
                data=order_data,
                message=f"订单创建成功！订单号：{order_id}，客户：{customer_name}，共 {len(items)} 件商品",
                summary=f"订单创建成功: 订单号{order_id}, 客户{customer_name}, {len(items)}件商品",
                # T2 事务终态：下单完成 → 清空订单域草稿/待确认状态（防下一轮污染）
                terminal=True,
            )

        except Exception as e:
            logger.error(
                f"[order-create] Failed: customer={customer_name}, "
                f"error={type(e).__name__}: {e}"
            )
            return ToolResult(
                success=False,
                error="tool_execution_failed",
                # 话术去「重试」（issue #4037 / F19 同一风险面）：HTTP 超时 25s < 工具超时 30s
                # ⇒ 这一次失败**可能已经落库了**，让模型重试等于让它重复下单。
                message=("创建订单没有成功返回。**先不要重复下单** —— 请先核实这笔订单是否已经建好。"),
                suggestion=("先调 order_query(action=list, customer_phone=客户手机号) 核实是否已建单："
                            "已存在就把订单号告知顾客；确实没有，再按原明细重新下单"),
            )
