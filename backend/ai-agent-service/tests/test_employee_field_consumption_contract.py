"""员工管理字段消费契约 — employee_manage 下发的每个字段名必须被 AdminUserController 真正读取。

# case_ids: HR-002, HR-003, HR-004

背景（issue #3550，HIGH 假成功）：`employee_manage` 的 create/update 下发 `phone` / `roleIds`，
而 `AdminUserController.updateUser` 只读 `name`/`avatar`/`role`/`position`/`password`/`permissions`
→ `phone` / `roleIds` 被 Jackson **静默忽略**，HTTP 200 + 「更新成功」，
用户以为改了角色/手机号，库里实际未变（假成功）。

本测试是「字段名级」契约防线：不 mock 控制器，而是**解析 admin-api 控制器源码**，
断言 ai-agent 实际构造的 update/create 请求体里每个 key 都能在接收侧找到读取点。
与 `test_tool_schema_signature_contract.py`（schema ↔ execute 签名）互补：
那条管「参数名进得来」，这条管「字段名发出去有人收」。

修复前必红：`phone` / `roleIds` 在 updateUser 中无任何读取点。
"""
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTROLLER = (
    _REPO_ROOT
    / "backend/admin-api/src/main/java/com/migao/admin/controller/AdminUserController.java"
)


def _controller_source() -> str:
    assert _CONTROLLER.is_file(), f"找不到 admin-api 控制器源码: {_CONTROLLER}"
    return _CONTROLLER.read_text(encoding="utf-8")


def _method_body(source: str, signature: str) -> str:
    """粗粒度提取 Controller 方法体（按大括号配对）。"""
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[brace : i + 1]
    raise AssertionError(f"方法体未闭合: {signature}")


def _update_user_body() -> str:
    return _method_body(_controller_source(), "public ApiResponse<User> updateUser(")


def _create_user_body() -> str:
    return _method_body(_controller_source(), "public ApiResponse<User> createUser(")


def _read_keys(body: str) -> set[str]:
    """控制器从请求体读取的 key 集合：body.get("x") / body.getOrDefault("x", ...)。"""
    return set(re.findall(r'body\.(?:get|getOrDefault|containsKey)\("([^"]+)"', body))


# ---------------- update ------------------

def test_update_phone_field_is_consumed():
    """update 下发 phone → 控制器必须读取 phone（修复前无任何 phone 读取点）。"""
    keys = _read_keys(_update_user_body())
    assert "phone" in keys, (
        "AdminUserController.updateUser 未读取 phone —— ai-agent/admin-web 下发的手机号会被"
        "Jackson 静默忽略，接口仍返回 200『更新成功』（issue #3550 假成功）"
    )


def test_update_role_ids_field_is_consumed():
    """update 下发 roleIds → 控制器必须读取 roleIds（与 createUser 同语义：角色表主键）。"""
    keys = _read_keys(_update_user_body())
    assert "roleIds" in keys, (
        "AdminUserController.updateUser 未读取 roleIds —— 米宝『把某人改成某角色』会 200 假成功，"
        "user_roles 关联与 user.role 均不变（issue #3550）"
    )


def test_update_role_ids_semantics_match_create():
    """roleIds 语义必须与 createUser 一致：角色表主键 → getRoleById 解析 code。"""
    update_body = _update_user_body()
    create_body = _create_user_body()
    assert "getRoleById" in create_body, "createUser 的 roleIds 语义已变更，请同步 updateUser"
    assert "getRoleById" in update_body, (
        "updateUser 的 roleIds 未按 createUser 语义（角色表主键 getRoleById 解析 code）处理"
    )


def test_update_preserves_position_role_fallback():
    """#2969 不回归：未显式传 role 时仍按 position 解析岗位角色。"""
    body = _update_user_body()
    assert "getRoleByPosition" in body, "updateUser 丢失了 #2969『岗位=角色』兜底解析"


def test_update_preserves_permissions_snapshot_fallback():
    """#2969 不回归：permissions 快照语义 + 岗位默认权限兜底必须保留。"""
    body = _update_user_body()
    assert 'body.get("permissions")' in body, "updateUser 丢失了 permissions 快照读取"
    assert "getRolePermissions" in body, "updateUser 丢失了岗位默认权限兜底"


# ---------------- create（同族防线，防同类漂移） ------------------

def test_create_phone_and_role_ids_still_consumed():
    keys = _read_keys(_create_user_body())
    assert "phone" in keys
    assert "roleIds" in keys


# ---------------- 下发给控制器的字段集合（字段名驱动，非硬编码） ------------------
# [RETIRED #5247] employee_manage(update) 的端到端字段消费契约已退休：
#   `update` action 随 B 端只读化（用户裁定 2026-09-23）从 employee_manage 删除 ⇒
#   该用例驱动的写路径不再存在（断言无对象）。同族的 **create** 契约与静态字段断言仍保留，
#   读路径（list/detail）契约由 tests/test_tools_employee_manage.py 覆盖。
