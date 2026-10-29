# case_ids: MC-120
"""页面动作登记表判据（F6 / P2-1，承接 issue #5989）—— 「怎么做」的真值源必须**可证**。

## 判什么（每条都会红）

| # | 判据 | 怎么红 |
|---|---|---|
| 1 | **路由真实性**：每条 `route` 都能在 `frontend/admin-web/src/app/**/page.tsx` 解析到 | 写一个不存在的页面路径 ⇒ 红 |
| 2 | **权限码真实性**：每条 `permission` ∈ `nav_guide` 导航真值（`menu_navigator.MENU_TREE`）现取码集 | 编一个假码 ⇒ 红 |
| 3 | **步骤非空可读**：`steps` ≥ 2 条、每条 ≥ 6 字 | 空 / 一条 / 过短 ⇒ 红 |
| 4 | **未登记必如实**：`lookup("不存在的动作") is None`；`how_to` 未命中分支含「没有步骤级指引」且不含具体步骤 | 未命中改猜 / 塞步骤 ⇒ 红 |
| 5 | **判别力自证**：合成一条指向不存在页面的登记 ⇒ 路由判据红（函数级断言） | 判据退化成恒空 ⇒ 红 |
| 6 | **命中逐字**：`how_to` 返回的 steps / preconditions / menu / route / permission 与登记表逐字相等 | 工具改写 / 补步骤 ⇒ 红 |
| 7 | **越权面**：命中但当前会话没有该页面码 ⇒ 不给 route / permission / steps | 裁剪被绕开 ⇒ 红 |

## 与既有判据的分工（**不重复**）

- 导航面（`action=navigate` 的登记表镜像 / 默认拒绝 / 裁剪 / citation / 无 steps 结构）：
  `backend/ai-agent-service/tests/test_nav_guide.py` 与 `tests/unit_ci_workflows/test_menu_navigator.py`；
- 本文件**只**判本次新增的「动作 → 步骤」注册面（真值可解析 + 未登记如实 + 命中逐字）。
- **不判 LLM 行为**（模型是否真的调了 `how_to` / 是否真的逐字转述）—— 那是用例 MC-120 的行为面。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.context.menu_navigator import MENU_GROUPS, MENU_TREE
from app.tools.base import ToolContext
from app.tools.nav_guide import NavGuideTool
from app.tools.page_actions import PAGE_ACTIONS, lookup

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_DIR = REPO_ROOT / "frontend" / "admin-web" / "src" / "app"

#: 导航真值里**现取**的页面码集合（不手抄；`MENU_TREE` 是 `menu.ts` 的镜像）。
NAV_PAGE_CODES = frozenset(node.permission_code for node in MENU_TREE if node.permission_code)
#: 导航真值里现取的菜单名 / 菜单组名（`menu` 字段必须逐字落在其中）。
NAV_MENU_LABELS = frozenset(node.label for node in MENU_TREE)
NAV_GROUP_LABELS = frozenset(label for _, label in MENU_GROUPS)

#: 首批范围（5 个高频动作）。新增动作 = 显式改这里 + 登记表（两条一起评审）。
FIRST_BATCH = {
    "product_price_update",
    "product_create",
    "customer_receiver_update",
    "employee_create",
    "processing_item_create",
}

#: `how_to` 命中时的 data 键集（结构面：多一个键就红 ⇒ 不会把内部字段漏给模型）。
HOW_TO_HIT_KEYS = frozenset(
    {
        "registered",
        "action",
        "label",
        "menu",
        "route",
        "permission",
        "steps",
        "preconditions",
    }
)


def _ctx(permissions, role: str = "admin") -> ToolContext:
    return ToolContext(tenant_id=1, user_id="u1", role=role, permissions=list(permissions))


def _route_to_pages(route: str) -> list[Path]:
    """把 `route` 解析成 admin-web 的 `page.tsx`（路由组 `(...)` 不计入路径）。"""
    assert APP_DIR.is_dir(), f"admin-web 路由根目录不存在：{APP_DIR}（路径漂移 ⇒ 红，不得静默跳过）"
    wanted = [part for part in route.strip("/").split("/") if part]
    hits: list[Path] = []
    for page in APP_DIR.rglob("page.tsx"):
        segments = [
            part
            for part in page.parent.relative_to(APP_DIR).parts
            if not (part.startswith("(") and part.endswith(")"))
        ]
        if segments == wanted:
            hits.append(page)
    return hits


def _unresolvable_routes(actions: dict) -> list[str]:
    """判据 1 的函数级实现（测试与判别力自证共用**同一份**逻辑）。"""
    return sorted(key for key, entry in actions.items() if not _route_to_pages(entry["route"]))


class TestRegistryTruth:
    """登记表本身可被机械核实（路由 / 权限码 / 菜单 / 步骤）——不依赖业务数据与网络。"""

    def test_first_batch_is_the_declared_five(self):
        assert set(PAGE_ACTIONS) == FIRST_BATCH, (
            f"首批范围漂移：{sorted(set(PAGE_ACTIONS) ^ FIRST_BATCH)} —— "
            "新增/删除动作必须显式改本判据（让范围可审计）"
        )

    def test_routes_resolve_to_real_pages(self):
        assert NAV_PAGE_CODES, "导航真值里取不到任何权限码 ⇒ 判据会空跑（fail-closed）"
        problems = _unresolvable_routes(PAGE_ACTIONS)
        assert problems == [], (
            f"这些动作的 route 在 frontend/admin-web/src/app 下解析不到 page.tsx：{problems}"
        )
        for key, entry in PAGE_ACTIONS.items():
            pages = _route_to_pages(entry["route"])
            assert len(pages) == 1, f"{key} 的 route={entry['route']!r} 命中 {len(pages)} 个 page.tsx"

    def test_route_judgement_discriminates(self):
        """判据 5：**函数级**注入 —— 不存在的 route ⇒ 红；真实 route ⇒ 不红（双向对照）。"""
        ghost = {"ghost": {"route": "/__this_page_does_not_exist__"}}
        assert _unresolvable_routes(ghost) == ["ghost"], "不存在的 route 没被判红 ⇒ 判据是空断言"
        assert _unresolvable_routes({"ok": {"route": "/products"}}) == [], (
            "真实 route 被判红 ⇒ 判据过严（路径解析口径漂移）"
        )

    def test_permissions_are_nav_truth_codes(self):
        """判据 2：权限码必须来自导航真值（现取），不能手抄/编造。"""
        for key, entry in PAGE_ACTIONS.items():
            assert entry["permission"] in NAV_PAGE_CODES, (
                f"{key} 的 permission={entry['permission']!r} 不在 nav_guide 导航真值"
                f"（MENU_TREE 现取 {sorted(NAV_PAGE_CODES)}）里 ⇒ 要么改码，要么先改菜单真值"
            )

    def test_menu_is_grounded_in_nav_truth(self):
        for key, entry in PAGE_ACTIONS.items():
            parts = [part.strip() for part in entry["menu"].split("→")]
            assert parts and parts[-1] in NAV_MENU_LABELS, (
                f"{key} 的 menu={entry['menu']!r} 末段不在 MENU_TREE 的菜单名里"
            )
            if len(parts) > 1:
                assert parts[0] in NAV_GROUP_LABELS, (
                    f"{key} 的 menu={entry['menu']!r} 首段不在 MENU_GROUPS 的组名里"
                )

    def test_steps_are_readable(self):
        """判据 3：steps ≥ 2 条、每条 ≥ 6 字（空/一条/过短都红）。"""
        for key, entry in PAGE_ACTIONS.items():
            steps = entry["steps"]
            assert len(steps) >= 2, f"{key} 的 steps 少于 2 条：{steps}"
            for step in steps:
                assert isinstance(step, str) and len(step.strip()) >= 6, (
                    f"{key} 的步骤不可读（< 6 字）：{step!r}"
                )
            assert len(set(steps)) == len(steps), f"{key} 的 steps 有重复条目：{steps}"
            assert entry["preconditions"], f"{key} 没有前置条件（至少给一条，避免「点就行」的误导）"

    def test_lookup_is_deterministic_and_fail_closed(self):
        """判据 4 的查询面：未登记 / 空串 ⇒ None；登记说法 ⇒ 命中唯一动作。"""
        assert lookup("不存在的动作") is None
        assert lookup("") is None
        assert lookup("   ") is None
        assert lookup("导出报表") is None, "没有登记的说法命中了动作 ⇒ lookup 在猜"
        hit = lookup("商品价格在哪改、具体怎么操作")
        assert hit is not None and hit["label"] == "改商品价格"
        # 最长命中：同一问句里出现两条动作的说法时，取更长的那个（不按出现顺序猜）
        assert lookup("加工项与分类")["label"] == "配置加工项"


class TestHowToProjection:
    """`nav_guide(action=how_to)` 的返回面：命中逐字 / 未登记如实 / 裁剪不放松。"""

    @pytest.mark.asyncio
    async def test_hit_returns_registry_verbatim(self):
        entry = PAGE_ACTIONS["product_price_update"]
        result = await NavGuideTool().execute(
            _ctx(["*"]), action="how_to", topic="商品价格在哪改、具体怎么操作"
        )
        assert result.success is True, f"命中登记表却失败：{result.error!r}"
        assert set(result.data) == HOW_TO_HIT_KEYS
        for field in ("steps", "preconditions", "menu", "route", "permission", "label"):
            assert result.data[field] == entry[field], f"{field} 被工具改写了（必须逐字来自登记表）"
        blob = result.message or ""
        for step in entry["steps"]:
            assert step in blob, f"message 里缺登记步骤：{step!r}"

    @pytest.mark.asyncio
    async def test_unregistered_action_is_honest(self):
        """判据 4：未登记 ⇒ 如实说没有步骤级指引，且**不得**带出任何具体步骤。"""
        result = await NavGuideTool().execute(
            _ctx(["*"]), action="how_to", topic="不存在的动作"
        )
        assert result.success is False
        assert result.error == "nav_not_registered"
        message = result.message or ""
        assert "没有步骤级指引" in message, f"未命中分支缺如实告知：{message!r}"
        assert "steps" not in (result.data or {})
        blob = json.dumps(result.data, ensure_ascii=False)
        for entry in PAGE_ACTIONS.values():
            for step in entry["steps"]:
                assert step not in blob, f"未命中分支带出了具体步骤：{step!r}"

    @pytest.mark.asyncio
    async def test_unregistered_action_still_gives_navigation_when_known(self):
        """「保持现状」的另一半：动作没登记、但功能登记过 ⇒ 给页面路径 + 说没有步骤。"""
        result = await NavGuideTool().execute(
            _ctx(["dashboard:view"]), action="how_to", topic="导出报表"
        )
        assert result.success is False and result.error == "nav_not_registered"
        assert "/reports" in json.dumps(result.data, ensure_ascii=False)
        assert "没有步骤级指引" in (result.message or "")
        assert "steps" not in (result.data or {})

    @pytest.mark.asyncio
    async def test_permission_trimming_applies_to_how_to(self):
        """判据 7：与 navigate 同一条裁剪纪律 —— 无权 ⇒ 不给路径 / 权限码 / 步骤。"""
        result = await NavGuideTool().execute(
            _ctx(["order:list"]), action="how_to", topic="商品价格在哪改"
        )
        assert result.success is False
        assert result.error == "nav_permission_denied"
        blob = json.dumps(result.data, ensure_ascii=False)
        assert "/products" not in blob
        assert "product:list" not in blob
        assert "steps" not in (result.data or {})
        assert "没有权限" in (result.message or "") or "访问权限" in (result.message or "")

    @pytest.mark.asyncio
    async def test_navigate_action_still_has_no_steps(self):
        """旧契约不回退：`action=navigate`（默认）仍然**结构上**没有 steps。"""
        result = await NavGuideTool().execute(_ctx(["*"]), question="商品管理在哪")
        assert result.success is True
        assert "steps" not in (result.data or {})
        assert "preconditions" not in (result.data or {})
