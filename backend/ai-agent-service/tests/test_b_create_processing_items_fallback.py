# case_ids: PR-014, PR-016
"""B 端**建品**「漏问加工项」代码兜底测试（issue #3320）。

背景：C 端（下单/售后）已有事实驱动兜底 `_plan_processing_items_rewrite`
——「有加工项却漏问、直接发 confirm 卡」⇒ 把 confirm 卡改写为加工项多选卡，
但它**只对 C 端生效**（`if skill_name in ("customer_order", "customer_aftersales")`），
且数据源是 `product_detail.processing_items`（要求商品**已存在**）。

B 端建品时商品还没建出来 ⇒ 上一条兜底既不在白名单里、也没有数据源。
PR-014 失效轨迹（run 34873715194 家族）实拍形态就是「跳过加工项询问、直接发 confirm 卡」，
全程无 `interact(component=choice, multiSelect=true)`。

本 PR 补一条**同构**的兜底，事实源换成**本会话真实调用过的 `processing_item_query` 返回**，
触发判据全是**状态事实**（不看话术关键词、不看 skill 名白名单）：
① 会话状态 `pending_validated_input` = product_manage/create（建品在办）
② 消息里有成功的 `processing_item_query` 结果且条目非空
③ 本会话未问过加工项；④ 本轮正发 confirm 卡；⑤ 顾客没拒绝、没答过

**双向红证**：正向（有事实 ⇒ 改写为 multiSelect 卡，选项取真实 tool 返回）+
反向（已问过 / 无事实 / 用户拒绝 / 已答过 / 非 create ⇒ 行为**不变**）。
"""

import json

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.graph.skills.base_skill import (
    _b_create_processing_items_not_asked,
    _has_processing_choice_in_turn,
    _plan_b_create_processing_items_rewrite,
)
from app.tools.processing_item_query import ProcessingItemQueryTool

# 真实 admin-api 记录 → 真实 tool 的格式化产物（夹具不手写字段名，跟真契约走）
_RAW_RECORDS = [
    {"id": "pi_a1b2c3d4", "name": "纳米圈打孔", "unitPrice": 8.0, "unit": "米",
     "pricingMethod": "per_meter"},
    {"id": "pi_q7r8s9t0", "name": "韩式折边", "unitPrice": 12.0, "unit": "米",
     "pricingMethod": "per_meter"},
]


def _items():
    return [ProcessingItemQueryTool._format_item(r) for r in _RAW_RECORDS]


def _result(name, data, success=True):
    return ({"name": name, "args": {}, "id": "x"},
            json.dumps({"success": success, "data": data}, ensure_ascii=False),
            {"success": success, "data": data})


def _query_msg(items=None):
    items = _items() if items is None else items
    payload = {"success": True, "data": {"items": items, "total": len(items)}}
    return ToolMessage(content=json.dumps(payload, ensure_ascii=False),
                       tool_call_id="q1", name="processing_item_query")


def _confirm_card():
    return _result("interact", {"component": "confirm", "fields": [],
                                "confirmValue": "确认创建商品 测试窗帘"})


def _user(text):
    return HumanMessage(content=text)


# ── ① 正向：有真实事实 + 正发 confirm 卡 ⇒ 改写为 multiSelect choice 卡 ──

def test_rewrites_confirm_to_multiselect_choice_from_real_query():
    """红证（正向）：改前 B 端 confirm 卡原样下发（该函数不存在）；改后改写为多选卡。"""
    confirm = _confirm_card()
    plan = _plan_b_create_processing_items_rewrite(
        [confirm], [_user("分类选窗帘"), _query_msg(), _user("颜色米白色")])
    assert plan, "有真实加工项目录却漏问 ⇒ 必须改写为加工项卡"
    idx, data = plan
    assert idx == 0
    assert data["component"] == "choice"
    assert data["multiSelect"] is True, "建品加工项卡必须多选（PR-014 核心断言）"
    assert len(data["options"]) == 2
    assert {o["value"] for o in data["options"]} == {"proc_item_pi_a1b2c3d4",
                                                     "proc_item_pi_q7r8s9t0"}


def test_options_carry_real_name_price_unit():
    """选项取**真实 tool 返回**（名称 + 单价 + 单位），不臆造。"""
    plan = _plan_b_create_processing_items_rewrite(
        [_confirm_card()], [_user("分类选窗帘"), _query_msg()])
    assert plan
    labels = [o["label"] for o in plan[1]["options"]]
    assert "纳米圈打孔 ¥8.0/米" in labels
    assert "韩式折边 ¥12.0/米" in labels
    prices = {o["value"]: o["unitPrice"] for o in plan[1]["options"]}
    assert prices["proc_item_pi_a1b2c3d4"] == 8.0


def test_rewrite_works_cross_turn():
    """查询与 confirm 跨轮（PR-014 实拍：R2/R3 查、R5 才发 confirm 卡）。"""
    msgs = [_user("录入这个商品，名称测试窗帘，价格 100"), _user("分类选窗帘"),
            _query_msg(), _user("颜色米白色，货号 TEST-001"), _user("确认")]
    plan = _plan_b_create_processing_items_rewrite([_confirm_card()], msgs)
    assert plan and len(plan[1]["options"]) == 2


def test_options_capped():
    items = [ProcessingItemQueryTool._format_item(
        {"id": f"pi{i}", "name": f"加工{i}", "unitPrice": i, "unit": "米"})
        for i in range(20)]
    plan = _plan_b_create_processing_items_rewrite(
        [_confirm_card()], [_user("分类选窗帘"), _query_msg(items)])
    assert plan and len(plan[1]["options"]) <= 6


# ── ② 反向守卫：这些形态下行为必须**不变**（去掉任一状态门就该红） ──

def test_no_rewrite_when_query_result_empty():
    """guard：`processing_item_query` 查回来是空 ⇒ **绝不伪造卡**（无事实可依）。"""
    plan = _plan_b_create_processing_items_rewrite(
        [_confirm_card()], [_user("分类选窗帘"), _query_msg(items=[])])
    assert not plan, "无真实加工项事实时不得伪造 choice 卡"


def test_no_rewrite_without_any_query_result():
    """guard：本会话从没查过加工项 ⇒ 不改写。"""
    plan = _plan_b_create_processing_items_rewrite(
        [_confirm_card()], [_user("分类选窗帘"), _user("确认")])
    assert not plan


def test_no_rewrite_without_confirm_card():
    """guard：本轮没发 confirm 卡（如直接调 product_manage 写）⇒ 不改写。"""
    msgs = [_user("分类选窗帘"), _query_msg()]
    plan = _plan_b_create_processing_items_rewrite(
        [_result("product_manage", {"id": "p1"})], msgs)
    assert not plan


def test_no_rewrite_when_processing_choice_already_emitted():
    """guard：本轮已发过加工项 choice 卡 ⇒ 不改写（与 C 端同口径）。"""
    choice = _result("interact", {"component": "choice", "multiSelect": True,
                                  "title": "这款商品支持以下加工项，需要哪些呢？（可多选）",
                                  "options": [{"label": "纳米圈打孔 ¥8.0/米",
                                               "value": "proc_item_pi_a1b2c3d4"}]})
    plan = _plan_b_create_processing_items_rewrite(
        [choice, _confirm_card()], [_user("分类选窗帘"), _query_msg()])
    assert not plan


def test_no_rewrite_when_user_declined():
    """guard：用户明确说不需要加工项 ⇒ 不硬弹卡。"""
    plan = _plan_b_create_processing_items_rewrite(
        [_confirm_card()], [_user("分类选窗帘"), _query_msg(), _user("不需要加工项")])
    assert not plan


def test_no_rewrite_when_user_already_answered():
    """guard：用户已经在文本里答过加工项 ⇒ 不得重问一遍（C 端踩过的重复提问陷阱）。"""
    plan = _plan_b_create_processing_items_rewrite(
        [_confirm_card()],
        [_user("分类选窗帘"), _query_msg(), _user("已选加工项：纳米圈打孔")])
    assert not plan


# ── ③ 状态门（异步）：只有「建品在办 + 未问过」才允许改写 ──

class _FakeStore:
    def __init__(self, full):
        self._full = full

    async def load(self, session_id):
        return dict(self._full)

    async def commit(self, session_id, full):
        self._full = dict(full)


def _patch_store(monkeypatch, full):
    import app.memory.session_state_store as sss
    monkeypatch.setattr(sss, "SessionStateStore", lambda *a, **k: _FakeStore(full))


@pytest.mark.asyncio
async def test_gate_true_for_create_flow_unasked(monkeypatch):
    _patch_store(monkeypatch, {
        "pending_validated_input": {"target_tool": "product_manage",
                                    "target_action": "create", "params": {}}})
    assert await _b_create_processing_items_not_asked("s1") is True


@pytest.mark.asyncio
async def test_gate_false_when_not_create(monkeypatch):
    """guard：其它 action（update/toggle_status 等）**行为不变**。"""
    _patch_store(monkeypatch, {
        "pending_validated_input": {"target_tool": "product_manage",
                                    "target_action": "toggle_status", "params": {}}})
    assert await _b_create_processing_items_not_asked("s1") is False


@pytest.mark.asyncio
async def test_gate_false_when_other_tool(monkeypatch):
    """guard：非 product_manage 的写流程**行为不变**。"""
    _patch_store(monkeypatch, {
        "pending_validated_input": {"target_tool": "inventory_manage",
                                    "target_action": "adjust", "params": {}}})
    assert await _b_create_processing_items_not_asked("s1") is False


@pytest.mark.asyncio
async def test_gate_false_when_no_pending(monkeypatch):
    _patch_store(monkeypatch, {})
    assert await _b_create_processing_items_not_asked("s1") is False


@pytest.mark.asyncio
async def test_gate_false_when_already_asked(monkeypatch):
    """guard：本会话已问过 ⇒ 不重复触发（防"卡循环"，OR-017 踩过）。"""
    _patch_store(monkeypatch, {
        "pending_validated_input": {"target_tool": "product_manage",
                                    "target_action": "create", "params": {}},
        "processing_items_asked": {"*": True}})
    assert await _b_create_processing_items_not_asked("s1") is False


# ── ④ 反向红证（承重证明）：把每道门"拆掉"，对应形态就必须被改写 ──
# 这不是凑数测试：它证明上面那些「应为 None」的断言不是恒真 —— 门一旦失效，
# 同一套输入就会产出改写（= 会把已经答过/无事实的流程误改写）。缺任何一道门即红。

def test_control_without_answered_guard_rewrite_happens(monkeypatch):
    """承重证明：拆掉「已答过」门 ⇒ 用户已答的形态会被误改写。"""
    import app.graph.skills.base_skill as bs

    msgs = [_user("分类选窗帘"), _query_msg(), _user("已选加工项：纳米圈打孔")]
    monkeypatch.setattr(bs, "_user_already_answered_processing", lambda *a, **k: False)
    plan = bs._plan_b_create_processing_items_rewrite([_confirm_card()], msgs)
    assert plan, "门被拆掉后必须能改写（否则说明该门不承重，上面的否定断言是恒真的假绿）"


def test_control_without_fact_guard_rewrite_happens(monkeypatch):
    """承重证明：拆掉「无事实不得伪造卡」门 ⇒ 空事实也会被改写。"""
    import app.graph.skills.base_skill as bs

    monkeypatch.setattr(bs, "_find_last_query_processing_items", lambda *a, **k: _items())
    plan = bs._plan_b_create_processing_items_rewrite(
        [_confirm_card()], [_user("分类选窗帘"), _query_msg(items=[])])
    assert plan, "门被拆掉后必须能改写（否则该门不承重）"


@pytest.mark.asyncio
async def test_control_without_asked_ledger_gate_returns_true(monkeypatch):
    """承重证明：拆掉「已问过」记账门 ⇒ 即使已问过也会再触发。"""
    import app.graph.skills.base_skill as bs

    _patch_store(monkeypatch, {
        "pending_validated_input": {"target_tool": "product_manage",
                                    "target_action": "create", "params": {}}})
    monkeypatch.setattr(bs, "_processing_items_already_asked", _false_async)
    assert await bs._b_create_processing_items_not_asked("s1") is True


async def _false_async(*a, **k):
    return False


# ── ⑤ 边界事实（改前红证的另一半）：既有兜底对 B 端建品形态**不生效** ──

def test_existing_c_side_fallback_does_not_cover_b_create():
    """改前红证的另一半：origin/main 上**唯一**存在的加工项兜底（C 端那条）
    对 B 端建品形态**返回 None** ⇒ 建品 confirm 卡原样下发（= 卡必发无保证）。

    它为什么为 None：数据源是 `product_detail.processing_items`（`_find_last_product_processing_items`），
    而建品时商品还没建出来 ⇒ 拿不到 items ⇒ 不改写。这条断言把"B 端无覆盖"钉住；
    若哪天有人把 C 端那条的白名单放宽到 product，本条会红（提醒：数据源不同，必须另立事实源）。
    """
    from app.graph.skills.base_skill import _plan_processing_items_rewrite

    confirm = _confirm_card()
    # B 端建品形态：有真实 processing_item_query 结果、无 product_detail
    msgs = [_user("录入这个商品，名称测试窗帘，价格 100"), _user("分类选窗帘"),
            _query_msg(), _user("颜色米白色，货号 TEST-001")]
    assert not _plan_processing_items_rewrite([confirm], msgs), (
        "C 端兜底按 product_detail 取事实源 ⇒ 对 B 端建品形态必然不生效（故本 PR 另立 processing_item_query 事实源）")


# ── ⑥ 记账判据：模型**自己**发出的加工项卡也要被识别（记账时机回归锁） ──
# 背景：调用点原先把「已问过」记账**嵌在改写分支内** ⇒ 模型自己发卡（`_bp_plan` 为 None）时不记账
# ⇒ 本会话后续轮次的 confirm 卡会被兜底重问一遍（PR-014 data_check「未再次询问加工项」要防的形态）。
# 记账判据本身复用既有纯函数 `_has_processing_choice_in_turn`（本次之前是**未使用的死代码**）。

def test_has_processing_choice_in_turn_detects_model_emitted_card():
    """模型自己发的加工项多选卡 → 必须被判为"本轮已问过"（据此记账）。"""
    card = _result("interact", {"component": "choice", "multiSelect": True,
                                "title": "测试窗帘 — 选择加工项（可多选，也可跳过）",
                                "options": [{"label": "纳米圈打孔 ¥8/米",
                                             "value": "proc_item_pi_a1b2c3d4"}]})
    assert _has_processing_choice_in_turn([_confirm_card(), card]) is True


def test_has_processing_choice_in_turn_ignores_unrelated_or_failed_cards():
    """非加工项卡、以及失败（未真正下发）的卡都不算"已问过"。"""
    other = _result("interact", {"component": "choice", "title": "请选择售卖方式",
                                 "options": [{"label": "散剪", "value": "bulk_cut"}]})
    failed = _result("interact", {"component": "choice", "title": "选择加工项",
                                  "options": [{"value": "proc_item_x"}]}, success=False)
    assert _has_processing_choice_in_turn([_confirm_card(), other, failed]) is False


def test_control_marking_inside_rewrite_branch_is_skipped_on_model_card():
    """承重证明（记账时机的红证）：模型**自己**发加工项卡时，改写计划必然为 None
    ⇒ 若记账嵌在改写分支内（= main 上的形态），记账**永不执行**；而记账判据此时为真。

    本 PR 把记账改为与改写分支**并列**，正是为了消除这个"模型自己问过、却记不上账"的洞
    （否则本会话后续轮次的 confirm 卡会被兜底重问一遍 = PR-014 data_check 要防的形态）。
    """
    model_card = _result("interact", {"component": "choice", "multiSelect": True,
                                      "title": "请选择要关联的加工项（可多选，也可跳过）",
                                      "options": [{"label": "纳米圈打孔 ¥8/米",
                                                   "value": "proc_item_pi_a1b2c3d4"}]})
    results = [model_card, _confirm_card()]
    plan = _plan_b_create_processing_items_rewrite(
        results, [_user("分类选窗帘"), _query_msg()])
    assert not plan, "本轮已发过加工项卡 ⇒ 改写计划返回 None（旧嵌套下记账被跳过）"
    assert _has_processing_choice_in_turn(results) is True, \
        "记账判据必须为真 ⇒ 应当记账（本 PR 的修法）"
