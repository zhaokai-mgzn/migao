"""
工具下发字段名 ↔ admin-api 请求类型字段契约（跨服务写请求边界）
# case_ids: AS-004, CU-004

① 契约层（docs/testing/interaction-verification.md「① 契约层」）：确定性、零 LLM、
mock 客户端 + 静态解析 Java 源码 —— 拦「工具下发的字段名与 API 接收类型字段不一致」
这类**跨端字段丢失**缺陷（纯单测和 Gate 都抓不到：HTTP 200、无异常、数据不落库）。

背景（两类同源缺陷，本文件是该层的落地）：
- issue #3540（首个登记域）：ai-agent 下发 `{"status", "reason"}`，admin-api
  `dto/AfterSalesStatusUpdateRequest.java` 只声明 `status`/`remark`；
- issue #3551（本 PR 新增域）：ai-agent 下发 `{"name": ...}`，admin-api
  `entity/CustomerProfile.java` 没有 `name` 列（姓名存 `wechatNickname`）。
  两例的共同机制：Spring Boot 默认 ObjectMapper 忽略未知属性
  （FAIL_ON_UNKNOWN_PROPERTIES=false）→ 请求 200、部分字段落库、信息静默丢失、无任何报错。

规则（新增/修改写工具时必须满足）：
  工具写请求 body 的每个 key，都必须能在目标的 Java **接收类型**中解析到同名字段；
  业务内容值必须落到该类型已声明字段上（禁止「多发一个别名字段」凑数，避免双写分叉）。
  改字段名时两端一起改（Java 类型 / 工具 payload），只改一端本测试即红。

## 如何新增一个域（增量登记步骤）

1. 在 `REGISTRY` 追加一条 `WriteContract`，填齐：
   - **工具/调用点**：`tool_module` + `client_method` + `endpoint` + `tool_kwargs`
     （`tool_kwargs` 要带上**会被下发**的业务内容字段，不是随便一个成功路径的入参）；
   - **接收类型**：`receiver_type` = admin-api 的请求 DTO **或**实体类名
     （Java 源码是「接收端可读键」的单一事实源，不维护第二份字段清单）；
   - **接收端可读键来源**：`receiver_key_source`（当前仅 `java-source`：静态解析
     `backend/admin-api/.../{receiver_type}.java` 的实例字段）；
   - **未映射键白名单**：`unmapped_key_allowlist` = {键: "理由（归属）"}，默认空。
     只有接收端确实尚未声明、但业务上合法的键才登记，并写清理由与归属人；
     空挂/过期的白名单会被本文件判红（逃逸口必须真实且最小）；
   - **业务内容值**：`content_value` = 必须落在接收端已声明字段上的那个值。
2. 若工具侧字段名与接收端不一致（如 `name` vs `wechatNickname`），**改工具侧下发 canonical 字段名**，
   不要新增别名/双写（口径见 #3540/#3545：别名会让实体绑定的其它未知键继续静默丢弃）。
3. 跑本文件即验证；不需要真实 LLM、不需要起服务（§16.1 的 L0/L1 层）。
"""
from __future__ import annotations

import importlib
import inspect
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Mapping
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.base import BaseTool

_REPO_ROOT = Path(__file__).resolve().parents[3]
_JAVA_MAIN = _REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"

# 请求 DTO 实例字段：`private String remark;` / `private List<String> images;`
# / `private Integer page = 1;`（带初值的字段同样是 Jackson 可绑定字段，漏解析会误报「键被丢弃」）
# （排除 static 常量与 final 常量 / serialVersionUID）
_FIELD_RE = re.compile(
    r"^\s*private\s+(?!static\b)(?!final\b)[\w.<>,\[\]\s]+\s+(\w+)\s*(?:=[^;]*)?;", re.MULTILINE
)


def _balanced_brace_block(src: str, open_idx: int) -> str:
    """取 `{` 开始的整段配平代码块（内部类解析用）。"""
    depth = 0
    for i in range(open_idx, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[open_idx : i + 1]
    return src[open_idx:]


def _source_of_receiver_type(class_name: str) -> str | None:
    """定位接收类型的源码：优先同名文件，其次**内部类**（无独立文件）。

    内部类形态真实存在：`SettingsController.java:323` 的
    `public static class ChangePasswordRequest` 就是 `PUT /api/admin/settings/password`
    的 `@RequestBody` 类型 —— 只按文件名找会解析不到（跨模块门禁曾因此报「接收类型无法解析」）。
    """
    matches = sorted(_JAVA_MAIN.rglob(f"{class_name}.java"))
    if matches:
        return matches[0].read_text(encoding="utf-8")
    pat = re.compile(rf"\b(?:class|record)\s+{re.escape(class_name)}\b[^{{;]*\{{")
    for path in sorted(_JAVA_MAIN.rglob("*.java")):
        src = path.read_text(encoding="utf-8")
        m = pat.search(src)
        if m:
            return _balanced_brace_block(src, src.index("{", m.start()))
    return None


@lru_cache(maxsize=None)
def _receiver_fields_from_java(class_name: str) -> frozenset[str]:
    """解析 admin-api 接收类型（请求 DTO / 实体 / 内部类）的实例字段名。

    单一事实源 = Java 源码，不维护第二份清单。
    """
    if not _JAVA_MAIN.is_dir():
        pytest.skip(f"admin-api Java 源码不存在（{_JAVA_MAIN}），无法校验跨服务字段契约")
    src = _source_of_receiver_type(class_name)
    assert src is not None, (
        f"未找到接收类型 {class_name}（既无 {class_name}.java，也无同名内部类）——"
        f"REGISTRY 登记的契约类已改名/删除；请同步更新 {__file__} 的 REGISTRY"
    )
    fields = frozenset(_FIELD_RE.findall(src))
    assert fields, f"{class_name} 未解析到任何字段（正则需适配；来源源码片段如下）：\n{src[:400]}"
    return fields


# 「接收端可读键来源」注册表：新增来源时在此登记 resolver，未登记的来源在测试里会**显式报错**
# （而不是被静默跳过 —— 静默跳过正是本文件要消灭的那类失效）。
RECEIVER_KEY_SOURCES = {
    "java-source": _receiver_fields_from_java,
}


@dataclass(frozen=True)
class WriteContract:
    """一条「工具调用点 → admin-api 写端点」的字段契约登记（字段含义见文件头步骤 1）。"""

    tool_module: str          # 工具模块（app.tools.xxx）
    tool_kwargs: dict         # execute 参数（须含要落库的业务内容字段）
    client_method: str        # admin api client 方法：post / put / patch
    endpoint: str             # 期望的 admin-api 路径（工具调用点）
    receiver_type: str        # 接收端 Java 类型（请求 DTO 或实体）
    content_value: str        # 必须落到「接收端已声明字段」上的业务内容值
    receiver_key_source: str = "java-source"   # 接收端可读键来源（见 RECEIVER_KEY_SOURCES）
    # 未映射键 → 「理由（归属）」：仅当接收端尚未声明该键、且业务上确属合法时登记
    unmapped_key_allowlist: Mapping[str, str] = field(default_factory=dict)


REGISTRY: tuple[WriteContract, ...] = (
    # AS-004「更新工单状态 - 关闭」：关闭原因必须经 `remark` 下发
    # （Java 侧 `updateTicketStatus` 用 request.getRemark() 写入 closeReason）——issue #3540
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
        receiver_type="AfterSalesStatusUpdateRequest",
        content_value="客户取消订单",
    ),
    # CU-004「更新客户资料」：姓名必须经 `wechatNickname` 下发
    # （`CustomerProfile` 无 `name` 列 → 下发 `name` 被静默丢弃 = 米宝谎报「已更新客户姓名」，issue #3551）
    WriteContract(
        tool_module="app.tools.customer_manage",
        tool_kwargs={
            "action": "update",
            "customer_id": "c1",
            "data": {"name": "李四", "phone": "13900001111"},
        },
        client_method="put",
        endpoint="/api/admin/customers/c1",
        receiver_type="CustomerProfile",
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
    """工具写请求 body 的字段名 ⊆ 接收类型字段名，且业务内容落在已声明字段上。

    修复前（issue #3540）：payload={"status","reason"}，DTO 字段={"status","remark"} → `reason` 丢失；
    修复前（issue #3551）：payload={"name"}，`CustomerProfile` 无 `name` → 姓名丢失。
    两例都是 HTTP 200 + 数据不落库，本测试红。
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

    resolver = RECEIVER_KEY_SOURCES.get(contract.receiver_key_source)
    assert resolver, (
        f"未实现的接收端可读键来源 {contract.receiver_key_source!r}"
        f"（已登记：{sorted(RECEIVER_KEY_SOURCES)}）—— 未登记来源必须显式报错，禁止静默跳过"
    )
    receiver_fields = resolver(contract.receiver_type)
    declared = set(receiver_fields)

    # 白名单是「接收端尚未声明但仍合法」的逃逸口：必须写理由，且不得空挂/过期
    for key, reason in contract.unmapped_key_allowlist.items():
        assert reason and reason.strip(), (
            f"{contract.receiver_type} 的 unmapped_key_allowlist[{key!r}] 缺理由/归属 —— "
            f"逃逸口必须可追溯（理由（归属人/issue））"
        )
    allowlisted = set(contract.unmapped_key_allowlist)
    stale = sorted((allowlisted & declared) | (allowlisted - set(payload)))
    assert not stale, (
        f"{contract.receiver_type} 的 unmapped_key_allowlist 已过期/空挂：{stale}"
        f"（已声明字段无需白名单；白名单里的键必须真的出现在 payload 里）"
    )

    dropped = sorted(set(payload) - declared - allowlisted)
    assert not dropped, (
        f"{contract.tool_module} action={contract.tool_kwargs['action']} 下发字段 {dropped} "
        f"未在 {contract.receiver_type} 中声明（该类型字段：{sorted(declared)}）"
        f" → admin-api 静默丢弃（Spring 默认忽略未知属性，HTTP 200 但数据不落库）。"
        f"改工具侧下发 canonical 字段名；若该键确属接收端未声明的合法字段，"
        f"请在 REGISTRY 的 unmapped_key_allowlist 登记「理由（归属）」"
    )

    carriers = sorted(
        k for k, v in payload.items() if v == contract.content_value and k in declared
    )
    assert carriers, (
        f"业务内容 {contract.content_value!r} 未落到 {contract.receiver_type} 的任何已声明字段上，"
        f"实际 payload={payload}"
    )


def test_receiver_parser_is_not_vacuous():
    """哨兵自身不能空转：解析器必须只返回 Java 类型声明的列。

    `CustomerProfile` 的姓名列是 `wechatNickname`（无 `name`）—— 这既是本域登记的依据，
    也是「解析器若退化成"什么都返回"则本文件失去拦截力」的自检（#3551）。
    """
    fields = _receiver_fields_from_java("CustomerProfile")
    assert "wechatNickname" in fields
    assert "name" not in fields, "CustomerProfile 没有 name 列，解析器/断言口径已漂移"
