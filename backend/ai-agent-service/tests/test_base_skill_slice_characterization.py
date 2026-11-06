# case_ids: MC-320
"""`base_skill.py` 切片（issue #8725 最后一档）的**行为 characterization**：四面逐字节冻结。

## 为什么先写它（CP-1）

切片 = 大面积搬移。它能全绿通过、却把某个**词表**、某条**日志字段**、某个 **fail-open 分支**
悄悄改掉 —— 现有用例（`test_tool_denial_semantics.py` / `test_graph_skills.py` /
`test_capability_denial_guard.py` / `test_skill_skills/test_base_skill.py` …）驱的是**点状断言**，
覆盖不到「同一批输入 ⇒ 输出逐字节相同」。本文件补的就是这一步。

## 四面（= 搬到四个新单元的四个族）

| 面 | 冻什么（逐字节） |
|---|---|
| `denial` | 10 组词表常量（含正则 pattern/flags）+ 34 条文本 × `capability_denial_text_hit` / `_product_image_denial_hit` / `_scope_misattribution_hit` / `_is_ordering_withdrawal` / `_has_ordering_intent` / `_normalize_clause` / `_negation_positions` / `_clause_is_self_line`；7 组假注册表 × 6 条能力事实判据；5 条纠偏话术原文；`_capability_denial_reason` 的 reason/summary 分别判定 |
| `order_flow` | `_has_inflight_interactive_card` 的 5 条消息形态 + `_flow_state_in_progress` 4 组状态 + `_load_session_facts` / `_order_flow_started` / `_order_flow_in_progress` / `_release_order_lock_on_withdrawal` 的**真值表**（含显式撤回优先）+ `_route_cross_skill_target` 的 fail-safe 分支 |
| `phone` | `raw_phones_in` / `mask_variants`（11 字符 × 10 种填充形态）/ `_is_mask_shaped` / `_phone_args`（嵌套/深度/非号码字段）/ `_norm_ws` / `_should_code_close_loop` 真值表 / `_is_customer_role` / 已知值记忆的**提交内容** |
| `injection` | `card_fingerprint` / `user_supplied_param` / `_accepted_param_names` / `_clear_write_input_error` / `_stated_purchase_quantities` + 6 段注入块的 `(tool_call, result_str, result_dict)` 三元组（拦下 = 逐字节回放真值；放行 = `None`）|

## golden 的来源纪律（这一条最容易做错）

golden **录制于未切片代码**（`origin/main` 的 `base_skill.py` = 4,317 行），`_meta.recorded_base_skill_lines`
记下当时的行数。切片后**不带** `BASE_SKILL_SLICE_GOLDEN_UPDATE` 复核 —— 必须逐字节相同。
⚠️ **不许**在切片后录一遍让两边一致：那会让「行为 diff = 0」变成**同义反复**（实证教训见 PR #8800 的红证 D）。

## 已知非确定性字段

本面**没有** `requestId` / `timestamp` 一类每次调用都变的字段（这四族都是纯判据 + 注入文本），
故不需要占位符归一 —— 若将来引入，必须在这里归一并写明理由，不许直接把字段删掉。
"""
import asyncio
import json
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

GOLDEN = Path(__file__).with_name("golden") / "base_skill_slice_golden.json"
UPDATE = os.environ.get("BASE_SKILL_SLICE_GOLDEN_UPDATE") == "1"


# ── 假件（**确定性**是 golden 的前提：不连库、不连网、不读时钟）────────────────
class _FakeStore:
    """`SessionStateStore` 的替身：进程内 dict，`load` 返回**深拷贝**（防被测代码原地改）。"""

    DATA: dict = {}

    def __init__(self, *a, **k):
        pass

    async def load(self, session_id):
        return json.loads(json.dumps(self.DATA.get(session_id) or {}))

    async def commit(self, session_id, full):
        self.DATA[session_id] = json.loads(json.dumps(full))


class _FakeSessionMemory:
    CALLS: list = []

    def __init__(self, *a, **k):
        pass

    async def set_pending_skill(self, session_id, value):
        _FakeSessionMemory.CALLS.append([session_id, value])


class _Tool:
    """工具替身。`execute` 的**显式签名**是 `_accepted_param_names` 的真值源 ——
    参数名集合会按 `type(tool).__qualname__` 缓存，故下面每个形态单独一个子类
    （同名替身共用缓存会互相串味，这是 `_accepted_param_names` 自己的注释里记着的坑）。
    """

    name = "tool"
    destructive = False
    requires_confirmation = False
    parameters = None
    read_only = False

    def execute(self, **kwargs):  # 默认 = 接受任意参数（None 分支）
        return kwargs


class _ToolA(_Tool):
    def execute(self, a, context=None):
        return a


class _ToolAImage(_Tool):
    def execute(self, a, image, context=None):
        return a


class _ToolAImages(_Tool):
    def execute(self, a, images, context=None):
        return a


class _ToolAPrice(_Tool):
    def execute(self, a, price, context=None):
        return a


class _ToolOrder(_Tool):
    def execute(self, items, sms_code, context=None):
        return items


class _ToolInteract(_Tool):
    def execute(self, component, title=None, context=None):
        return component


def _tool(cls, name, **kw):
    t = cls()
    t.name = name
    for k, v in kw.items():
        setattr(t, k, v)
    return t


class _Registry:
    def __init__(self, tools):
        self._tools = list(tools)

    def get_tool(self, name):
        for t in self._tools:
            if t.name == name:
                return t
        return None

    def get_all_tools(self):
        return list(self._tools)


class _BoomRegistry:
    def get_tool(self, name):
        raise RuntimeError("boom")

    def get_all_tools(self):
        raise RuntimeError("boom")


@pytest.fixture()
def fake_env(monkeypatch):
    """把两处惰性 import 的存储换成假件（**不 patch 生产模块的属性**，只换惰性 import 的落点）。"""
    import app.memory.session_memory as sm
    import app.memory.session_state_store as sss

    _FakeStore.DATA = {}
    _FakeSessionMemory.CALLS = []
    monkeypatch.setattr(sss, "SessionStateStore", _FakeStore)
    monkeypatch.setattr(sm, "SessionMemory", _FakeSessionMemory)
    yield


# ── 输入语料（固定，不许随实现改动）──────────────────────────────────────────
DENIAL_TEXTS = [
    "好的，已为您下单。",
    "我这边没有权限帮您下单。",
    "我没有办法帮您下单，请联系人工。",
    "抱歉，该商品落不了单。",
    "这单要落单，请回「转人工」。",
    "您需要协助下单的话可以联系客服。",
    "顾客需要协助下单。",
    "顾客表示不想要了，我这边帮他取消订单。",
    "该商品缺货，下不了单。",
    "我帮不了您下单，但可以帮您查库存。",
    "这个功能我做不到，请您到后台操作。",
    "您可以自己提交订单。",
    "改商品图片属于商品编辑操作，我这边没有这个能力。",
    "商品主图我改不了排版。",
    "我这边没有这个工具改商品主图。",
    "我这边没有权限查别的租户的订单。",
    "主图已更新，请查收。",
    "已为您设置主图。",
    "\u200b我\u3000没有办法下单。",
    "",
    "算了，先不落单了。",
    "我不是要下单，只是问问价格。",
    "别结算了。",
    "帮我取消订单 X。",
    "回归测试取消Z03 这个商品怎么样",
    "客户不要了 / 不买了",
    "我要下单，窗帘 3 米。",
    "确认下单",
    "好的，就按这个来。",
    "我这边暂时办不了，请转人工。",
    "这件商品我们不能落单。",
    "这边确实没办法代您提交订单。",
    "权限不足",
    "无法代为提交订单",
]

REASON_CASES = [
    {"reason": "顾客需要协助下单", "summary": ""},
    {"reason": "", "summary": "无法代为提交订单"},
    {"reason": "顾客要求人工核价", "summary": "顾客情绪激动"},
    {"reason": "", "summary": ""},
    {"reason": "顾客需协助", "summary": "无法代为提交订单"},
    {"reason": "我这边没有权限帮您下单", "summary": "顾客想买窗帘"},
]

STATES = [
    {},
    {"role": "customer"},
    {"role": "admin"},
    {"role": "CUSTOMER"},
    {"pending_interact_skill": "order"},
    None,
]

ORDER_MSGS = [
    [],
    [HumanMessage(content="我要下单")],
    [ToolMessage(content=json.dumps({"success": True, "data": {"component": "choice"}}),
                 name="interact", tool_call_id="c1")],
    [ToolMessage(content=json.dumps({"success": True, "data": {"component": "confirm"}}),
                 name="interact", tool_call_id="c1"),
     HumanMessage(content="确认")],
    [ToolMessage(content=json.dumps({"success": True, "data": {"component": "form"}}),
                 name="interact", tool_call_id="c1")],
    [ToolMessage(content=json.dumps({"success": False, "data": {"component": "choice"}}),
                 name="interact", tool_call_id="c1")],
    [ToolMessage(content="not-json", name="interact", tool_call_id="c1")],
    [ToolMessage(content=json.dumps({"success": True, "data": {"component": "other"}}),
                 name="other_tool", tool_call_id="c2")],
]

PHONE_TEXTS = [
    "",
    "我的号码是13800138000",
    "13800138000 / 13900139000",
    "号码 1380013800 少一位",
    "订单13800138000123（超长不算）",
    "138****8000",
    "13800008000",
    "联系电话：138-0013-8000",
]

MASK_INPUTS = ["", "13800138000", "1380013800", "138001380001", "abcdefghijk",
               "13912345678", "1a2b3c4d5e6", "00000000000"]

PHONE_ARGS = [
    {},
    {"phone": "138****8000"},
    {"customer_phone": "13800008000", "name": "张三"},
    {"items": [{"contactPhone": "138****8000"}, {"phone": ""}]},
    {"a": {"b": {"c": {"phone": "138****8000"}}}},
    {"a": {"b": {"c": {"d": {"phone": "138****8000"}}}}},
    {"phone_model": "iPhone X", "phone": " 13800138000 "},
    {"PHONE": "138****8000"},
]

NORM_INPUTS = ["", "  张 三 ", "北京 市 朝阳 区", "138 0013 8000", None]

MASK_SHAPED = ["", "138****8000", "13800008000", "****", "1234567*", "123456*", "iPhone X",
               "13800138000", "138****", "abcdefg*"]

CLOSE_LOOP_CASES = [
    (None, "", False, set()),
    ({"target_tool": "order_create"}, "order_create", True, set()),
    ({"target_tool": "order_create"}, "order_create", False, set()),
    ({"target_tool": "order_create"}, "order_create", True, {"order_create"}),
    ({"target_tool": "order_create"}, "", True, set()),
    ({"target_tool": "order_create"}, "order_create", True, {"other"}),
]

USER_SUPPLIED = [
    ("sms_code", "123456"), ("sms_code", "验证码 654321"), ("sms_code", "13800138000"),
    ("sms_code", "1 2 3 4 5 6"), ("sms_code", ""), ("items", "123456"), ("other", "123456"),
    ("sms_code", "1234"), ("sms_code", "1234567"),
]

CARD_ARGS = [
    {},
    {"component": "confirm", "title": "确认下单", "fields": [{"label": "商品", "value": "A"}]},
    {"component": "choice", "title": "选一个", "options": [{"label": "a"}, {"label": "b"}]},
    {"component": "confirm", "title": "确认下单", "fields": [{"label": "商品", "value": "B"}]},
    {"component": "", "title": ""},
]

STATED_MSG_SETS = [
    [],
    [HumanMessage(content="我要 3 米")],
    [HumanMessage(content="3 米布")],
    [HumanMessage(content="窗宽 3 米")],
    [AIMessage(content="您要 5 米吗"), HumanMessage(content="5 米")],
    [HumanMessage(content="要 2.5 米、再来 1 米")],
]

SANITIZE_ARGS = [
    ({"a": 1}, _tool(_ToolAImage, "t")),
    ({"a": 1, "image": "x"}, _tool(_ToolAImage, "t")),
    ({"a": 1, "image": "x"}, _tool(_ToolA, "t")),
    ({"a": 1}, _tool(_Tool, "t")),
    ({"a": 1, "images": "x"}, _tool(_ToolA, "t", read_only=True)),
    ({"a": 1, "main_image": "x"}, _tool(_ToolA, "t")),
]


def _tools():
    return [
        _tool(_ToolOrder, "order_create", destructive=True,
              parameters={"properties": {"items": {}, "sms_code": {}}}),
        _tool(_ToolInteract, "interact", requires_confirmation=True,
              parameters={"properties": {"component": {}}}),
        _tool(_ToolAImages, "product_manage",
              parameters={"properties": {"images": {}, "detail_images": {}}}),
        _tool(_ToolAPrice, "product_manage_noimg", parameters={"properties": {"price": {}}}),
        _tool(_ToolA, "logistics_track", parameters={"properties": {"order_id": {}}}),
        _tool(_Tool, "plain"),
    ]


def _jsonable(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, frozenset):
        return sorted(_jsonable(x) for x in v)
    return repr(v)


def _rx(bs, name):
    rx = getattr(bs, name)
    return {"pattern": rx.pattern, "flags": rx.flags} if hasattr(rx, "pattern") else _jsonable(rx)


# ── 四面 ────────────────────────────────────────────────────────────────────
def _denial_surface(bs):
    out = {"wordlists": {n: _rx(bs, n) for n in [
        "_ORDER_ACTION_WORDS", "_ORDER_UNABLE_RE", "_INABILITY_STEMS", "_ABILITY_WORDS",
        "_PERMISSION_NEGATIONS", "_SCOPE_HANDOFF_MARKERS", "_SELF_SCOPE_COMPOUNDS",
        "CAPABILITY_DENIAL_PATTERNS", "_AGENT_SELF_WORDS", "_NON_SELF_SUBJECT_WORDS",
        "_CLAUSE_SPLIT_RE", "_PRODUCT_IMAGE_ACTION_WORDS",
        "_PRODUCT_IMAGE_CAPABILITY_NEGATION_RE", "_PRODUCT_IMAGE_UNABLE_RE",
        "_ORDER_WITHDRAWAL_ANCHORS", "_ORDER_WITHDRAWAL_NEGATIONS", "_ORDER_WITHDRAWAL_WINDOW",
        "_STALL_CORRECTIVE", "_TEXT_DENIAL_CORRECTIVE", "_TEXT_DENIAL_CORRECTIVE_MIDORDER",
        "_TEXT_DENIAL_CORRECTIVE_BIZ", "_TEXT_DENIAL_CORRECTIVE_PRODUCT_IMAGE",
        "_LOGISTICS_CHAIN_CORRECTIVE", "ORDER_WRITE_TOOL", "PRODUCT_IMAGE_WRITE_TOOL",
    ]}}
    texts = {}
    for t in DENIAL_TEXTS:
        norm = bs._normalize_clause(t)
        texts[t] = {
            "hit": bs.capability_denial_text_hit(t),
            "hit_assist": bs.capability_denial_text_hit(t, include_assist=True),
            "img": bs._product_image_denial_hit(t),
            "scope": bs._scope_misattribution_hit(t),
            "withdraw": bs._is_ordering_withdrawal(t),
            "order_intent": bs._has_ordering_intent(t),
            "normalized": norm,
            "neg_pos": _jsonable(bs._negation_positions(norm, False)),
            "neg_pos_assist": _jsonable(bs._negation_positions(norm, True)),
            "clauses": [
                {"clause": c, "self_line": bs._clause_is_self_line(c)}
                for c in bs._CLAUSE_SPLIT_RE.split(t) if c
            ],
        }
    out["texts"] = texts
    out["reasons"] = [bs._capability_denial_reason(a) for a in REASON_CASES]
    out["stall_progress"] = [
        bs._stall_has_progress(x) for x in
        [[], [{"name": "order_query"}], [{"name": "validate_input"}],
         [{"name": "interact"}], [{"name": "order_create"}], [None, {"name": ""}], None]
    ]
    out["logistics"] = {
        "corrective": bs._logistics_chain_corrective(["SO-1"]),
        "corrective_empty": bs._logistics_chain_corrective([]),
        "incomplete": [
            bs._logistics_chain_incomplete(intent_name=i, registry=_Registry(_tools()),
                                           order_nos=o, executed_tools=e)
            for i, o, e in [("logistics_track", ["SO-1"], set()),
                            ("logistics_track", [], set()),
                            ("logistics_track", ["SO-1"], {"logistics_track"}),
                            ("order_query", ["SO-1"], set()),
                            ("logistics_track", ["SO-1"], None)]
        ],
    }
    regs = {"full": _Registry(_tools()), "empty": _Registry([]), "none": None,
            "boom": _BoomRegistry()}
    facts = {}
    for label, reg in regs.items():
        facts[label] = {
            "has_order_create": bs._registry_has_tool(reg, "order_create"),
            "has_logistics": bs._registry_has_tool(reg, "logistics_track"),
            "order_write_here": bs._order_write_tool_here(reg),
            "cap_available": [bs._order_capability_available(reg, order_in_progress=x)
                              for x in (False, True)],
            "img_available": bs._product_image_capability_available(reg),
            "confirm_write": bs._registry_has_confirm_write_tool(reg),
            "handoff": [_jsonable(bs._handoff_guard_applies(
                reg, order_in_progress=o, denial_reason_hit=d))
                for o, d in [(False, ""), (True, ""), (False, "hit")]],
        }
    facts["img_registry_params"] = [
        bs._product_image_capability_available(r) for r in [
            _Registry([_tool(_ToolA, "product_manage",
                             parameters={"properties": {"images": {}}})]),
            _Registry([_tool(_ToolA, "product_manage",
                             parameters={"properties": {"detail_images": {}}})]),
            _Registry([_tool(_ToolA, "product_manage",
                             parameters={"properties": {"price": {}}})]),
            _Registry([_tool(_ToolA, "product_manage", parameters=None)]),
            _Registry([_tool(_ToolA, "product_manage", parameters={"properties": None})]),
            _Registry([_tool(_ToolA, "product_manage", parameters={})]),
        ]
    ]
    out["facts"] = facts
    return out


async def _order_flow_surface(bs):
    out = {"inflight": [bs._has_inflight_interactive_card(m) for m in ORDER_MSGS]}
    out["flow_state"] = [bs._flow_state_in_progress(s) for s in STATES]
    out["load_facts"] = [await bs._load_session_facts(s) for s in (None, "", "sess-1")]
    # 真值表：跨轮事实 × 状态 × 本轮消息
    rows = []
    for facts in ({}, {"grounded_product_detail": True},
                  {"pending_validated_input": {"target_tool": "order_create"}},
                  {"pending_validated_input": {"target_tool": "other"}}):
        for state in ({"pending_interact_skill": "order"}, {}):
            for msg in ("我要下单", "好的，就按这个来", "我不是要下单", ""):
                _FakeStore.DATA["sess-t"] = json.loads(json.dumps(facts))
                rows.append({
                    "facts": sorted(facts), "state": sorted(state), "msg": msg,
                    "started": await bs._order_flow_started("sess-t", state),
                    "in_progress": await bs._order_flow_in_progress("sess-t", state, msg),
                })
    out["truth_table"] = rows
    # 显式撤回 ⇒ 解除跨轮锁（只在置位时动作；写失败非致命）
    rel = []
    for state in ({"ordering_withdrawn": True}, {"ordering_withdrawn": False}, {}, None):
        _FakeSessionMemory.CALLS = []
        rel.append({"state": _jsonable(state),
                    "ret": await bs._release_order_lock_on_withdrawal("sess-r", state),
                    "calls": _jsonable(_FakeSessionMemory.CALLS)})
    out["release"] = rel
    out["release_no_session"] = await bs._release_order_lock_on_withdrawal(
        None, {"ordering_withdrawn": True})
    # `_route_cross_skill_target` 的 fail-safe 分支（不改任何状态、返回空串）
    out["route_failsafe"] = [
        await bs._route_cross_skill_target(None, {}, "order_create"),
        await bs._route_cross_skill_target("sess-1", {}, ""),
    ]
    return out


async def _phone_surface(bs):
    out = {
        "constants": {n: _jsonable(getattr(bs, n)) for n in
                      ["KNOWN_RAW_PHONES_KEY", "KNOWN_ADDRESS_KEY",
                       "_MASK_PLACEHOLDER_CHARS", "_MASK_FILLER_CHARS"]},
        "phones_in": {t: sorted(bs.raw_phones_in(t)) for t in PHONE_TEXTS},
        "variants": {v: sorted(bs.mask_variants(v)) for v in MASK_INPUTS},
        "mask_shaped": {v: bs._is_mask_shaped(v) for v in MASK_SHAPED},
        "phone_args": [_jsonable(bs._phone_args(a)) for a in PHONE_ARGS],
        "norm_ws": [_jsonable(bs._norm_ws(v)) for v in NORM_INPUTS],
        "close_loop": [bs._should_code_close_loop(*c) for c in CLOSE_LOOP_CASES],
        "is_customer": [bs._is_customer_role(s) for s in STATES],
    }
    # 已知真值记忆：提交内容逐字节（只增不减 / 幂等）
    _FakeStore.DATA["sess-p"] = {"known_raw_phones": ["13900139000"]}
    steps = []
    for key, value in [("known_raw_phones", "13800138000"), ("known_raw_phones", "13800138000"),
                       ("known_customer_address", " 北京 市 朝阳 区 "), ("known_customer_address", "")]:
        await bs._remember_known_value("sess-p", key, value)
        steps.append(json.loads(json.dumps(_FakeStore.DATA["sess-p"])))
    out["remember_known_value"] = steps
    _FakeStore.DATA["sess-q"] = {"known_raw_phones": ["13900139000"]}
    remembered = []
    for phones in ({"13800138000"}, {"13800138000", "13700137000"}, set()):
        await bs._remember_raw_phones("sess-q", phones)
        remembered.append(json.loads(json.dumps(_FakeStore.DATA["sess-q"])))
    out["remember_raw_phones"] = remembered
    _FakeStore.DATA["sess-q"] = {"known_raw_phones": ["13900139000"]}
    out["known_raw_phones"] = [
        sorted(await bs._known_raw_phones("sess-q", state, msg))
        for state, msg in [({}, ""),
                           ({"messages": [HumanMessage(content="打 13800138000")]}, ""),
                           ({}, "号码 13700137000"),
                           (None, None)]
    ]
    return out


async def _injection_surface(bs):
    out = {
        "constants": {n: _jsonable(getattr(bs, n)) for n in
                      ["WRITE_INPUT_ERROR_KEY", "_INPUT_PARAM_LABELS", "RECOGNIZABLE_INPUT_PARAMS",
                       "CARD_EMIT_COUNTS_KEY", "CARD_EMIT_LIMIT", "_PREFILL_FIDELITY_FIELDS",
                       "_QUANTITY_FRAME_WORDS", "_QUANTITY_INTENT", "_QUANTITY_PLAIN",
                       "_DIMENSION_SEMANTIC"]},
        "user_supplied": [bs.user_supplied_param(p, m) for p, m in USER_SUPPLIED],
        "accepted_names": [_jsonable(bs._accepted_param_names(t)) for t in _tools()],
        "clear_write_input_error": [_jsonable(bs._clear_write_input_error(x)) for x in
                                   [{}, None, {"k": 1}, {"last_write_input_error": {"a": 1},
                                                         "k": 2}]],
        "card_fingerprint": [bs.card_fingerprint(a) for a in CARD_ARGS],
        "stated_quantities": [sorted(bs._stated_purchase_quantities(m)) for m in STATED_MSG_SETS],
        "sanitize": [{
            "args": _jsonable(a),
            "out": _jsonable(bs._sanitize_tool_args(t, a)),
            "guidance": bs._dropped_args_guidance(t, a),
        } for a, t in SANITIZE_ARGS],
    }
    # 六段注入块：拦下 = 回放真值（三元组逐字节）；放行 = None
    calls = {
        "_quantity_choice_block": [
            ("interact", {"options": [{"label": "3 米"}, {"label": "6 米"}], "title": "选用量"},
             {"name": "interact"}, {"role": "customer", "messages": [HumanMessage(content="我要 3 米")]}),
            ("interact", {"options": [{"label": "3 米"}], "title": "选"},
             {"name": "interact"}, {"role": "customer", "messages": [HumanMessage(content="我要 3 米")]}),
            ("interact", {"options": [{"label": "6 米"}], "title": "用量"},
             {"name": "interact"}, {"role": "admin", "messages": [HumanMessage(content="我要 3 米")]}),
            ("other", {"options": [{"label": "6 米"}], "title": "用量"}, {}, {}),
        ],
        "_form_prefill_fidelity_block": [
            ("interact", {"component": "form",
                          "formFields": [{"key": "customer_phone", "value": "13800008000"}]},
             {"name": "interact"}, {"role": "customer"}),
            ("interact", {"component": "choice"}, {}, {"role": "customer"}),
            ("interact", {"component": "form",
                          "formFields": [{"key": "customer_phone", "value": ""}]},
             {}, {"role": "admin"}),
        ],
        "_masked_phone_write_block": [
            ("order_create", {"phone": "138****8000"}, {"name": "order_create"},
             {"role": "customer"}),
            ("order_create", {"phone": "13800138000"}, {"name": "order_create"},
             {"role": "customer"}),
            ("order_create", {"name": "张三"}, {}, {"role": "customer"}),
        ],
        "_write_input_recovery_block": [
            ("order_create", {}, {"name": "order_create"}, {}),
            ("interact", {"component": "confirm"}, {"name": "interact"}, {}),
            ("other_tool", {}, {}, {}),
        ],
        "_card_loop_block": [
            ("interact", {"component": "confirm", "title": "确认下单"}, {"name": "interact"}, {}),
            ("other", {"component": "confirm"}, {}, {}),
        ],
    }
    sessions = {"_quantity_choice_block": "sess-q", "_form_prefill_fidelity_block": "sess-f",
                "_masked_phone_write_block": "sess-m", "_write_input_recovery_block": "sess-w",
                "_card_loop_block": "sess-c"}
    fixture_facts = {
        "_form_prefill_fidelity_block": {"known_customer_address": ["北京市朝阳区"],
                                         "known_raw_phones": ["13800138000"]},
        "_write_input_recovery_block": {"last_write_input_error":
                                        {"param": "sms_code", "tool": "order_create",
                                         "message": "缺少短信验证码"}},
        "_card_loop_block": {"card_emit_counts": {"__none__": 1}},
    }
    blocks = {}
    for fn_name, rows in calls.items():
        sid = sessions[fn_name]
        fn = getattr(bs, fn_name)
        results = []
        for tool_name, args, tool_call, state in rows:
            _FakeStore.DATA[sid] = json.loads(json.dumps(fixture_facts.get(fn_name, {})))
            if fn_name == "_write_input_recovery_block":
                results.append(_jsonable(await fn(tool_name, args, tool_call, sid, "order",
                                                  last_user_msg="")))
            elif fn_name == "_card_loop_block":
                results.append(_jsonable(await fn(tool_name, args, tool_call, sid, "order")))
            else:
                results.append(_jsonable(await fn(tool_name, args, tool_call, sid, "order",
                                                  state=state)))
        # 重发阈值：同一张卡第 3 次
        if fn_name == "_card_loop_block":
            fp = bs.card_fingerprint({"component": "confirm", "title": "确认下单"})
            _FakeStore.DATA[sid] = {"card_emit_counts": {fp: bs.CARD_EMIT_LIMIT}}
            results.append(_jsonable(await fn("interact", {"component": "confirm",
                                                           "title": "确认下单"},
                                              {"name": "interact"}, sid, "order")))
            _FakeStore.DATA[sid] = {"card_emit_counts": {fp: bs.CARD_EMIT_LIMIT - 1}}
            results.append(_jsonable(await fn("interact", {"component": "confirm",
                                                           "title": "确认下单"},
                                              {"name": "interact"}, sid, "order")))
        # 缺参已补齐 ⇒ 清账并放行
        if fn_name == "_write_input_recovery_block":
            _FakeStore.DATA[sid] = {"last_write_input_error":
                                    {"param": "sms_code", "tool": "order_create"}}
            results.append(_jsonable(await fn("order_create", {}, {"name": "order_create"},
                                              sid, "order", last_user_msg="123456")))
            blocks[fn_name] = {"results": results, "store": json.loads(
                json.dumps(_FakeStore.DATA.get(sid) or {}))}
            continue
        if fn_name == "_card_loop_block":
            blocks[fn_name] = {"results": results, "store": json.loads(
                json.dumps(_FakeStore.DATA.get(sid) or {}))}
            continue
        blocks[fn_name] = {"results": results}
    out["blocks"] = blocks
    out["inject_write_input_recovery"] = []
    for facts in ({}, {"last_write_input_error": {"param": "sms_code", "tool": "order_create"}},
                  {"last_write_input_error": {"param": "", "tool": "order_create"}},
                  {"last_write_input_error": "not-a-dict"}):
        _FakeStore.DATA["sess-i"] = json.loads(json.dumps(facts))
        out["inject_write_input_recovery"].append(
            await bs._inject_write_input_recovery("SYS", {"session_id": "sess-i"}, ""))
    _FakeStore.DATA["sess-i"] = {"last_write_input_error":
                                 {"param": "sms_code", "tool": "order_create"}}
    out["inject_write_input_recovery"].append(
        await bs._inject_write_input_recovery("SYS", {"session_id": "sess-i"}, "123456"))
    out["inject_write_input_recovery"].append(
        await bs._inject_write_input_recovery("SYS", {}, ""))
    return out


def _surface(kind):
    import app.graph.skills.base_skill as bs
    if kind == "denial":
        return _denial_surface(bs)
    if kind == "order_flow":
        return asyncio.run(_order_flow_surface(bs))
    if kind == "phone":
        return asyncio.run(_phone_surface(bs))
    if kind == "injection":
        return asyncio.run(_injection_surface(bs))
    raise AssertionError(kind)


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True)


def _load_golden():
    assert GOLDEN.is_file(), (
        f"golden 不存在：{GOLDEN}（它**录制于未切片代码**，不许在切片后补录 —— 那会让 diff = 0 变成同义反复）")
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _assert_face(kind):
    actual = _surface(kind)
    if UPDATE:
        data = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.is_file() else {}
        data.setdefault("_meta", {"recorded_base_skill_lines": _base_skill_lines()})
        data[kind] = actual
        GOLDEN.write_text(_dump(data) + "\n", encoding="utf-8")
        pytest.skip(f"{kind}: 已写入 golden（录制轮，仅限**未切片**代码）")
    want = _load_golden()[kind]
    got_txt, want_txt = _dump(actual), _dump(want)
    if got_txt != want_txt:
        for i, (a, b) in enumerate(zip(got_txt.splitlines(), want_txt.splitlines())):
            if a != b:
                raise AssertionError(
                    f"[{kind}] 切片后行为漂移（逐字节不相同）：行{i + 1}: got={a!r} want={b!r}")
        raise AssertionError(f"[{kind}] 长度不同：got={len(got_txt)} want={len(want_txt)}")
    assert got_txt == want_txt


def _base_skill_lines():
    return len((Path(__file__).resolve().parents[1] / "app/graph/skills/base_skill.py")
               .read_text(encoding="utf-8").splitlines())


def test_meta_golden_was_recorded_on_unsliced_code():
    """golden 的**来源自证**：必须录在未切片代码上（切片前 = 4317 行）。

    这条判据不是"形式主义"：若有人把 golden 在切片后重录一遍，另外四条会全绿，
    而「行为 diff = 0」就退化成同义反复（PR #8800 红证 D 的教训）。
    切片后本文件的行数会变小 ⇒ 本判据**仍然**读 `_meta.recorded_base_skill_lines`，
    它一旦被改成切片后的行数就说明 golden 是被重录的 ⇒ 红。
    """
    meta = _load_golden()["_meta"]
    assert meta["recorded_base_skill_lines"] == 4317, (
        f"golden 声称录制于 {meta['recorded_base_skill_lines']} 行的 base_skill.py，"
        f"而录制基线是 4317 行（未切片）—— 疑似在切片后重录（diff = 0 会变成同义反复）")


def test_denial_face_is_byte_identical_after_slice():
    _assert_face("denial")


def test_order_flow_face_is_byte_identical_after_slice():
    _assert_face("order_flow")


def test_phone_face_is_byte_identical_after_slice():
    _assert_face("phone")


def test_injection_face_is_byte_identical_after_slice():
    _assert_face("injection")
