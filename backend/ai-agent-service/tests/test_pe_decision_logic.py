"""
防线 1: P&E 决策逻辑单元测试

测试 should_use_plan_execute() 的各种输入场景，
确保简单操作不被误判为复杂流程，复杂创建不被漏掉。

纯函数测试，不依赖 LLM/DB/网络。
"""

import pytest
from langchain_core.messages import HumanMessage

from app.graph.plan_executor import should_use_plan_execute


def _make_state(msg: str, skill: str = "product") -> dict:
    """构造最小 AgentState，仅包含 messages 和 skill"""
    return {
        "messages": [HumanMessage(content=msg)],
        "agent_type": "mibao",
        "tenant_id": 1,
        "user_id": "test",
        "session_id": "test_session",
        "role": "admin",
    }


# ============ 简单单步操作 — 应该跳过 P&E ============

@pytest.mark.parametrize("msg", [
    "上架这个商品",
    "把这个商品下架",
    "上架",
    "下架那个窗帘",
])
def test_toggle_status_skips_pe(msg):
    """上架/下架是单步 toggle_status，不应走 P&E"""
    state = _make_state(msg)
    assert should_use_plan_execute(state, "product") is False


@pytest.mark.parametrize("msg", [
    "修改价格为200",
    "价格改成200元",
    "把价格调整到150",
    "更新价格为99",
    "变更售价为88",
    "价格改为100",
    "修改下价格，200",
    "单价调整成50",
    "把售价改成120",
])
def test_price_update_skips_pe(msg):
    """修改价格是单步 update，不应走 P&E"""
    state = _make_state(msg)
    assert should_use_plan_execute(state, "product") is False


@pytest.mark.parametrize("msg", [
    "库存调到100",
    "库存改成50",
    "把库存调整到200",
    "库存设为300",
])
def test_inventory_update_skips_pe(msg):
    """调整库存是单步操作，不应走 P&E"""
    state = _make_state(msg)
    assert should_use_plan_execute(state, "product") is False


@pytest.mark.parametrize("msg", [
    "分类改成窗帘布艺",
    "分类改为配件",
    "换个分类",
    "分类调整到布料",
])
def test_category_change_skips_pe(msg):
    """改分类是单步 update，不应走 P&E"""
    state = _make_state(msg)
    assert should_use_plan_execute(state, "product") is False


# ============ 复杂创建 — 应该走 P&E ============

@pytest.mark.parametrize("msg,skill", [
    ("创建一个窗帘商品", "product"),
    ("新增商品", "product"),
    ("新建一个商品", "product"),
    ("添加商品", "product"),
    ("录入新商品", "product"),
    ("上架一个新品", "product"),  # "上架" 在 create_kw 里，复杂度检测不拦截
    ("创建订单", "order"),
    ("新增订单", "order"),
    ("创建一个售后工单", "aftersales"),
    ("新建售后", "aftersales"),
    ("添加一个工单", "aftersales"),
])
def test_complex_create_triggers_pe(msg, skill):
    """多步创建操作应走 P&E"""
    state = _make_state(msg)
    assert should_use_plan_execute(state, skill) is True


# ============ 关键词含"修改"但实际是复杂操作 ============

@pytest.mark.parametrize("msg,skill", [
    ("修改商品描述和价格", "product"),     # 修改但涉及多字段
    ("编辑商品信息", "product"),           # "编辑" 可能触发多步
    ("更新商品", "product"),              # 模糊的更新
])
def test_vague_update_may_trigger_pe(msg, skill):
    """模糊的"更新/编辑商品"可能仍需 P&E"""
    state = _make_state(msg)
    # 当前逻辑：只要不是简单单步，模糊更新也触发 P&E
    assert should_use_plan_execute(state, skill) is True


# ============ 非写操作 — 不应走 P&E ============

@pytest.mark.parametrize("msg,skill", [
    ("查下我的订单", "order"),
    ("这个商品多少钱", "product"),
    ("最近有什么新品", "product"),
    ("怎么看经营数据", "data"),
    ("你好", "general"),
    ("帮我看看库存", "product"),
])
def test_read_operations_skip_pe(msg, skill):
    """查询/问候不应走 P&E"""
    state = _make_state(msg)
    assert should_use_plan_execute(state, skill) is False


# ============ 边界 case ============

def test_empty_message():
    """空消息不应触发 P&E"""
    state = _make_state("")
    assert should_use_plan_execute(state, "product") is False


def test_unknown_skill():
    """未知 skill 不触发 P&E"""
    state = _make_state("创建订单")
    assert should_use_plan_execute(state, "inventory") is False


def test_multimodal_message():
    """多模态消息（图片+文本）也能正确识别"""
    content = [
        {"type": "text", "text": "创建一个窗帘"},
        {"type": "image_url", "image_url": {"url": "https://example.com/img.jpg"}},
    ]
    state = {
        "messages": [HumanMessage(content=content)],
        "agent_type": "mibao",
        "tenant_id": 1, "user_id": "test",
        "session_id": "test", "role": "admin",
    }
    assert should_use_plan_execute(state, "product") is True


def test_order_creation_triggered_in_both_skills():
    """含"创建"关键词的消息在两个 Skill 中都能触发 P&E"""
    state = _make_state("创建一个订单", skill="product")
    # product skill：关键词匹配"创建"→ True（虽然有歧义，但宁可多触发不少触发）
    assert should_use_plan_execute(state, "product") is True

    state = _make_state("创建一个订单", skill="order")
    assert should_use_plan_execute(state, "order") is True


def test_order_query_skips_pe():
    """纯订单查询不走 P&E"""
    state = _make_state("查下订单", skill="order")
    assert should_use_plan_execute(state, "order") is False


def test_product_with_selling_methods():
    """带售卖方式的创建仍触发 P&E"""
    state = _make_state("创建一个窗帘，散剪和整卷都要")
    assert should_use_plan_execute(state, "product") is True
