# case_ids: MC-065, MC-071
"""`nav_guide` 工具面判据（issue #5989 · P1）—— 注册 / 门面 / 只读 / 纯本地 / skill 绑定 / 执行语义。

## 与哪个判据分工（**不是重复**）

| 面 | 承载体 |
|---|---|
| **跨包结构面**（`menus.ts` 镜像、权限目录、别名接地、默认拒绝、裁剪、citation、无 steps 结构） | `tests/unit_ci_workflows/test_menu_navigator.py` |
| **工具自身面**（本文件） | 注册表 / 门面导出 / `read_only` / 零 admin-api 调用点 / skill 可达 / **真跑 `execute` 的返回形状**（`success` 与 `error` 的口径、`data` 键白名单、会话权限裁剪在工具层的落点） |

为什么必须有本文件：`growth_gate` 的**缺测**判定按工具文件名找配套测试（`tests/test_nav_guide.py` /
`tests/test_tools_nav_guide.py`）—— 缺了它 `blocker_count` **不为 0**（这是门禁，不是风格）。

## 明确边界（照实登记）

- **不判 LLM 行为**（是否真的引用了 citation / 真的没编步骤）—— 那是 `MC-065` 的行为面，
  本文件只判**结构**（工具**没有能力**返回步骤：`data` 键白名单里不存在 `steps`）。
- **不重复** `tests/unit_ci_workflows/test_agent_permission_parity.py` 的四源对账（工具码 ↔ 端点码 ↔
  菜单节点 ↔ 岗位）：本工具是**纯本地**工具（零 admin-api 调用点）⇒ 按 `LOCAL_ONLY_TOOLS` 口径
  **不声明权限码**，那条对账在**工具层**结构性不适用；授权面落在**答案级**裁剪（下面判据 4）。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.context import menu_navigator as nav
from app.graph.skills.general_agent import GENERAL_TOOLS
from app.tools.base import ToolContext
from app.tools.nav_guide import NavGuideTool
from app.tools.registry import get_tool_registry

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL_SOURCE = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "tools" / "nav_guide.py"

#: `data` 的键白名单（结构面：`steps` 这类字段**进不来**）。
ALLOWED_DATA_KEYS = frozenset(
    {"registered", "featureId", "label", "pages", "deniedMenuNames", "citation"}
)


def _ctx(permissions, role: str = "admin") -> ToolContext:
    return ToolContext(tenant_id=1, user_id="u1", role=role, permissions=list(permissions))


class TestToolSurface:
    def test_registered_and_read_only(self):
        tool = get_tool_registry().get_tool("nav_guide")
        assert getattr(tool, "name", None) == "nav_guide", "nav_guide 未注册 ⇒ 模型不可达"
        assert tool.read_only is True
        assert tool.destructive is False
        assert list(tool.required_permissions) == [], (
            "纯本地工具（零 admin-api 调用点）不声明权限码 —— 与 `interact` / `image_recognize` 同口径"
        )

    def test_is_pure_local_no_http_call_points(self):
        """AST 面：模块里**没有** `client.get/post` 调用点（真值源在仓内，不查业务数据）。"""
        tree = ast.parse(TOOL_SOURCE.read_text(encoding="utf8"))
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "get_admin_api_client" not in TOOL_SOURCE.read_text(encoding="utf8")
        assert not ({"get", "post", "put", "patch", "delete"} & calls), (
            f"nav_guide 里出现 HTTP 调用形态 {sorted(calls)} —— 它必须是纯本地工具"
        )

    def test_bound_to_a_b_side_skill(self):
        assert "nav_guide" in GENERAL_TOOLS, "没绑任何 B 端 skill ⇒ 模型拿不到（能力谎报）"

    def test_parameters_carry_the_question(self):
        tool = NavGuideTool()
        assert tool.parameters["properties"]["question"]["type"] == "string"
        assert tool.parameters["required"] == ["question"]


class TestExecuteSemantics:
    @pytest.mark.asyncio
    async def test_registered_question_returns_path_and_citation(self):
        result = await NavGuideTool().execute(_ctx(["production:view"]), question="企业基础设置在哪")
        assert result.success is True
        payload = result.data
        assert set(payload) == ALLOWED_DATA_KEYS
        assert [p["path"] for p in payload["pages"]] == ["/settings"]
        assert payload["citation"].startswith("登记项 #settings → 菜单节点")

    @pytest.mark.asyncio
    async def test_unregistered_question_is_a_failure_with_no_pages(self):
        # ⚠️ 样本换成「一个已登记说法都不含」的问句：`怎么导出订单 Excel` 含了 #6062 登记的
        # 口语说法「订单」⇒ 它现在**有**登记项（返回订单列表页 + 如实说没有步骤级指引）。
        # 判据本身（未登记 ⇒ success=False / 零路径）一字未动，只换样本 —— 静态面同步
        # `tests/unit_ci_workflows/test_menu_navigator.py` 的 `UNREGISTERED_QUESTIONS`。
        result = await NavGuideTool().execute(_ctx(["*"]), question="皮料怎么算价")
        assert result.success is False
        assert result.error == "nav_not_registered"
        assert result.data["pages"] == []
        assert result.data["registered"] is False
        assert nav.NAV_NOT_REGISTERED_NOTICE in (result.message or "")

    @pytest.mark.asyncio
    async def test_permission_trimming_happens_in_the_tool(self):
        """**授权面在工具层**：无权角色拿不到路径与权限码（只有菜单名 + citation）。"""
        result = await NavGuideTool().execute(_ctx(["order:list"]), question="企业基础设置在哪")
        blob = json.dumps(result.data, ensure_ascii=False)
        assert result.data["pages"] == []
        assert "/settings" not in blob
        assert "production:view" not in blob
        assert result.data["deniedMenuNames"] == ["企业基础设置"]

    @pytest.mark.asyncio
    async def test_client_supplied_role_is_not_read(self):
        """裁剪**只**看服务端会话的 `permissions` —— role 换成什么都一样。"""
        for role in ("admin", "customer", "agent", "operator"):
            result = await NavGuideTool().execute(
                _ctx(["order:list"], role=role), question="企业基础设置在哪"
            )
            assert result.data["pages"] == [], f"role={role!r} 时竟拿到页面 ⇒ 裁剪读了 role"

    @pytest.mark.asyncio
    async def test_no_steps_field_and_no_step_wording_in_replies(self):
        """结构 + 文本：返回里既没有 `steps` 字段，也没有受控步骤词。"""
        step_words = ("第一步", "第二步", "步骤如下", "点击", "按钮", "输入框", "下拉框", "依次")
        tool = NavGuideTool()
        for question in [f.label for f in nav.NAV_FEATURES] + ["怎么导出订单"]:
            result = await tool.execute(_ctx(["*"]), question=question)
            blob = json.dumps(
                {"m": result.message, "s": result.suggestion, "d": result.data}, ensure_ascii=False
            )
            hits = [w for w in step_words if w in blob]
            assert hits == [], f"「{question}」的返回里出现步骤词 {hits}"
            assert "steps" not in json.dumps(result.data or {}, ensure_ascii=False)
            assert "没有步骤级指引" in blob, f"「{question}」没有如实告知「没有步骤级指引」"

    @pytest.mark.asyncio
    async def test_employee_account_phrasing_resolves_without_steps(self):
        """🔴 **实测失败样例的真跑判据**（issue #6062；2026-10-02 B 端真实评测 `normal` 档）。

        修前：用户问「怎么给员工开账号」⇒ 登记面没有这条常见说法 ⇒ `nav_guide` 返回
        `success=False` / `error="nav_not_registered"`（fail-closed 是对的，但对用户没用）。
        修后：命中「员工开账号」这条登记说法 ⇒ 给出**页面位置**（`/employees`），
        并仍然**不给操作步骤**（导航类口径）、不假承诺改账号。

        前置（前置不成立时本用例应先在登记面判据上红）：「员工管理」页在 `config/menu.ts`
        的导航节点里存在（key=employees / path=/employees / 码=employee:list）。
        """
        result = await NavGuideTool().execute(_ctx(["employee:list"]), question="怎么给员工开账号")
        assert result.success is True, f"仍未登记（实测失败的复现）：error={result.error!r}"
        assert [p["path"] for p in result.data["pages"]] == ["/employees"]
        assert result.data["featureId"] == "employees"
        assert result.data["citation"] == "登记项 #employees → 菜单节点 菜单组「员工管理」"
        # 权限不足时不许泄露路径（与既有裁剪口径同一条）
        blind = await NavGuideTool().execute(_ctx(["order:list"]), question="怎么给员工开账号")
        assert blind.data["pages"] == []
        assert "/employees" not in json.dumps(blind.data, ensure_ascii=False)
        # 导航口径：不给步骤、不给「我帮你开」这类写承诺的假承诺
        blob = json.dumps(
            {"m": result.message, "s": result.suggestion, "d": result.data}, ensure_ascii=False
        )
        step_words = ("第一步", "第二步", "步骤如下", "点击", "按钮", "输入框", "下拉框", "依次")
        assert [w for w in step_words if w in blob] == [], "导航答案里出现步骤词"
        assert "没有步骤级指引" in blob
        assert "employee:list" in blob
