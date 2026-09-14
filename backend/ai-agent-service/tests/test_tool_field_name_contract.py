"""
工具下发字段名 ↔ admin-api 请求 DTO 字段契约（跨服务写请求边界）
# case_ids: AS-004, CU-004

① 契约层（docs/testing/interaction-verification.md「① 契约层」）：确定性、零 LLM、
mock 客户端 + 静态解析 Java 源码 —— 拦「工具下发的字段名与 API DTO 字段不一致」
这类**跨端字段丢失**缺陷（纯单测和 Gate 都抓不到：HTTP 200、无异常、数据不落库）。

背景（issue #3540，AS-004 断言恒不可满足的根因）：
- ai-agent: `app/tools/after_sales_manage.py` `_update_status` 下发 `{"status", "reason"}`；
- admin-api: `dto/AfterSalesStatusUpdateRequest.java` 只声明 `status`/`remark`；
- Spring Boot 默认 ObjectMapper 忽略未知属性（FAIL_ON_UNKNOWN_PROPERTIES=false）
  → 请求 200、`closedAt` 落库、`closeReason` 恒为空：信息静默丢失，无任何报错。

规则（新增/修改写工具时必须满足；新增写端点时在 REGISTRY 登记一条）：
  工具写请求 body 的每个 key，都必须能在目标 Java 请求 DTO 中解析到同名字段；
  业务内容值必须落到 DTO 已声明字段上（禁止「多发一个别名字段」凑数，避免双写分叉）。
  改字段名时两端一起改（DTO / 工具 payload），只改一端本测试即红。
"""
from __future__ import annotations

import importlib
import inspect
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.base import BaseTool

_REPO_ROOT = Path(__file__).resolve().parents[3]
_JAVA_MAIN = _REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"

# 请求 DTO 实例字段：`private String remark;` / `private List<String> images;`
# （排除 static 常量与 serialVersionUID）
_FIELD_RE = re.compile(
    r"^\s*private\s+(?!static\b)(?!final\b)[\w.<>,\[\]\s]+\s+(\w+)\s*;", re.MULTILINE
)


@lru_cache(maxsize=None)
def _dto_fields(class_name: str) -> frozenset[str]:
    """解析 admin-api 请求 DTO 的实例字段名（单一事实源 = Java 源码，不维护第二份清单）。"""
    if not _JAVA_MAIN.is_dir():
        pytest.skip(f"admin-api Java 源码不存在（{_JAVA_MAIN}），无法校验跨服务字段契约")
    matches = sorted(_JAVA_MAIN.rglob(f"{class_name}.java"))
    assert matches, (
        f"未找到 DTO {class_name}.java —— REGISTRY 登记的契约类已改名/删除；"
        f"请同步更新 {__file__} 的 REGISTRY"
    )
    src = matches[0].read_text(encoding="utf-8")
    fields = frozenset(_FIELD_RE.findall(src))
    assert fields, f"{class_name}.java 未解析到任何字段（正则需适配）：{matches[0]}"
    return fields


@dataclass(frozen=True)
class WriteContract:
    """一条「工具 action → admin-api 写端点」的字段契约登记。"""

    tool_module: str          # 工具模块（app.tools.xxx）
    tool_kwargs: dict         # execute 参数（含要落库的业务内容字段）
    client_method: str        # admin api client 方法：post / put / patch
    endpoint: str             # 期望的 admin-api 路径
    dto_class: str            # 目标 Java 请求 DTO 类名
    content_value: str        # 必须落到「DTO 已声明字段」上的业务内容值


REGISTRY: tuple[WriteContract, ...] = (
    # AS-004「更新工单状态 - 关闭」：关闭原因必须经 `remark` 下发
    # （Java 侧 `updateTicketStatus` 用 request.getRemark() 写入 closeReason）
    WriteContract(
        tool_module="app.tools.after_sales_manage",
        tool_kwargs={
            "action": "update_status",
            "ticket_id": "t1",
            "status": "closed",
            "reason": "客户取消订单",
        },
        client_method="put",
        endpoint="/api/admin/after-sales/t1/status",
        dto_class="AfterSalesStatusUpdateRequest",
        content_value="客户取消订单",
    ),
    # CU-004「更新客户资料」：姓名经 `wechatNickname` 下发
    # （CustomerProfile 无 `name` 列；下发 `name` 即静默丢弃 = 假成功，issue #3551）
    WriteContract(
        tool_module="app.tools.customer_manage",
        tool_kwargs={
            "action": "update",
            "customer_id": "c1",
            "data": {"name": "李四", "phone": "13900001111"},
        },
        client_method="put",
        endpoint="/api/admin/customers/c1",
        dto_class="CustomerProfile",
        content_value="李四",
    ),
)


def _tool_instance(module_name: str) -> BaseTool:
    """取模块内注册的 BaseTool 子类实例（与 test_tool_schema_signature_contract 同口径）。"""
    mod = importlib.import_module(module_name)
    for obj in vars(mod).values():
        if (
            inspect.isclass(obj)
            and obj.__module__ == mod.__name__
            and issubclass(obj, BaseTool)
            and isinstance(getattr(obj, "name", None), str)
            and obj.name
        ):
            return obj()
    raise AssertionError(f"{module_name} 未定义有效的 BaseTool 子类")


@pytest.mark.parametrize(
    "contract", REGISTRY, ids=lambda c: f"{c.tool_module.split('.')[-1]}:{c.tool_kwargs['action']}"
)
async def test_write_payload_keys_declared_in_api_dto(contract, admin_tool_context):
    """工具写请求 body 的字段名 ⊆ 目标 DTO 字段名，且业务内容落在已声明字段上。

    修复前（issue #3540）：payload={"status","reason"}，DTO 字段={"status","remark"}
    → `reason` 被 Spring 静默丢弃 → closeReason 不落库 → 本测试红。
    """
    tool = _tool_instance(contract.tool_module)
    client = AsyncMock()
    setattr(client, contract.client_method, AsyncMock(return_value={"success": True}))

    with patch(f"{contract.tool_module}.get_admin_api_client", return_value=client):
        result = await tool.execute(context=admin_tool_context, **contract.tool_kwargs)

    assert result.success is True, f"工具执行失败：{result.error} / {result.message}"

    call = getattr(client, contract.client_method).call_args
    assert call.args[0] == contract.endpoint, f"写端点漂移：{call.args[0]}"
    payload = call.kwargs["json_data"]
    dto_fields = _dto_fields(contract.dto_class)

    dropped = sorted(set(payload) - set(dto_fields))
    assert not dropped, (
        f"{contract.tool_module} action={contract.tool_kwargs['action']} 下发字段 {dropped} "
        f"未在 {contract.dto_class} 中声明（该 DTO 字段：{sorted(dto_fields)}）"
        f" → admin-api 静默丢弃（Spring 默认忽略未知属性，HTTP 200 但数据不落库）"
    )

    carriers = sorted(
        k for k, v in payload.items() if v == contract.content_value and k in dto_fields
    )
    assert carriers, (
        f"业务内容 {contract.content_value!r} 未落到 {contract.dto_class} 的任何已声明字段上，"
        f"实际 payload={payload}"
    )
