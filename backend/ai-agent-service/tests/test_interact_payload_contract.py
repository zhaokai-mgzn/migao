"""
interact 交互组件 payload 契约 — 后端字段白名单
# case_ids: PP-001, PR-010, OR-001

防「后端发了前端不认识 / 前端声明了后端不发」的跨端字段断裂。

背景（sess_fba38395ed094a9d 系列，issue #2892/#2894/#2896）：
- interact schema 的 pageMeta/multiSelect 曾与 execute 签名不一致（已由
  test_tool_schema_signature_contract.py 拦截 execute 层）；
- 本测试锁 interact 工具 → SSE 的 payload 字段集合，须与前端
  frontend/admin-web/src/types/index.ts 的 InteractiveComponent 字段对齐。

字段白名单（= 前端 InteractiveComponent 可消费的全部字段）：
  component, title, options, fields, formFields, submitLabel,
  confirmLabel, confirmValue, cancelLabel, cancelValue,
  pageMeta, multiSelect
"""
import pytest

from app.tools.interact import InteractTool

# 前端 types/index.ts InteractiveComponent 字段全集（新增字段两端同步更新）
FRONTEND_INTERACTIVE_FIELDS = {
    "component",
    "title",
    "options",
    "fields",
    "formFields",
    "submitLabel",
    "confirmLabel",
    "confirmValue",
    "cancelLabel",
    "cancelValue",
    "pageMeta",
    "multiSelect",
}


@pytest.fixture
def tool():
    return InteractTool()


def _emit_keys(data: dict) -> set:
    """SSE interactive payload 实际字段 = type + data 键（type 由 route 注入）"""
    return set(data.keys())


async def test_choice_payload_within_contract(tool, sample_tool_context):
    """choice 组件（含 pageMeta/multiSelect）payload 字段必须在白名单内"""
    result = await tool.execute(
        context=sample_tool_context,
        component="choice",
        title="请选择加工项",
        options=[{"label": "打孔", "value": "hole"}],
        pageMeta={
            "current": 1, "total": 2, "totalCount": 15,
            "tool": "processing_item_query",
            "params": '{"page":1,"size":10}',
        },
        multiSelect=True,
    )
    keys = _emit_keys(result.data)
    assert keys <= FRONTEND_INTERACTIVE_FIELDS, (
        f"choice payload 含前端未声明字段: {keys - FRONTEND_INTERACTIVE_FIELDS}"
    )


async def test_confirm_payload_within_contract(tool, sample_tool_context):
    """confirm 组件 payload 字段必须在白名单内"""
    result = await tool.execute(
        context=sample_tool_context,
        component="confirm",
        title="确认创建商品？",
        fields=[{"label": "商品名称", "value": "遮光窗帘"}],
        confirmLabel="确认创建商品",
        cancelLabel="再想想",
        confirmValue="确认创建商品遮光窗帘",
        cancelValue="取消创建",
    )
    keys = _emit_keys(result.data)
    assert keys <= FRONTEND_INTERACTIVE_FIELDS, (
        f"confirm payload 含前端未声明字段: {keys - FRONTEND_INTERACTIVE_FIELDS}"
    )


async def test_form_payload_within_contract(tool, sample_tool_context):
    """form 组件 payload 字段必须在白名单内"""
    result = await tool.execute(
        context=sample_tool_context,
        component="form",
        title="新建商品",
        formFields=[{"key": "name", "label": "商品名称"}],
        submitLabel="提交",
    )
    keys = _emit_keys(result.data)
    assert keys <= FRONTEND_INTERACTIVE_FIELDS, (
        f"form payload 含前端未声明字段: {keys - FRONTEND_INTERACTIVE_FIELDS}"
    )


async def test_all_contract_fields_emittable(tool, sample_tool_context):
    """白名单字段都应是 interact 可发出的（防前端声明了后端永不发）"""
    # choice 发: component/title/options/pageMeta/multiSelect
    choice = await tool.execute(
        context=sample_tool_context, component="choice", title="t",
        options=[{"label": "a", "value": "b"}],
        pageMeta={"current": 1, "total": 1, "totalCount": 1, "tool": "x", "params": "{}"},
        multiSelect=True,
    )
    # confirm 发: fields/confirmLabel/confirmValue/cancelLabel/cancelValue
    confirm = await tool.execute(
        context=sample_tool_context, component="confirm", title="t",
        fields=[{"label": "a", "value": "b"}],
        confirmLabel="c", confirmValue="d", cancelLabel="e", cancelValue="f",
    )
    # form 发: formFields/submitLabel
    form = await tool.execute(
        context=sample_tool_context, component="form", title="t",
        formFields=[{"key": "a", "label": "b"}], submitLabel="c",
    )
    emitted = (
        set(choice.data)
        | set(confirm.data)
        | set(form.data)
    )
    assert emitted == FRONTEND_INTERACTIVE_FIELDS, (
        f"白名单字段未被 interact 全量覆盖，缺: {FRONTEND_INTERACTIVE_FIELDS - emitted}"
    )