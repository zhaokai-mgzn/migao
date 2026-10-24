# case_ids: BM-028
"""B 端快捷入口（黄金策六格 + 工具类入口）必须是**权限事实的机械投影**（issue #7358）。

## 这一条要治什么

`GET /api/chat/quick-actions` 改前是**静态清单**：7 条入口对**所有岗位**原样下发。
与 `rbac/manifest.json` 的 8 个内置岗位默认权限比对实测：**56 格里 27 格是死的**
（admin/operator 7/7；product_manager、sales 5/7；customer_service、knowledge_editor 4/7；
finance 3/7；**inspector 1/7**）—— 质检员打开黄金策，看到 7 个建议，点 6 个都做不到。

而 `docs/agent-feature-design.md` §九 早把该形态列为反模式（「❌ 静态示例（不管页面 / 角色 / 历史）」），
红线是：**引导了却做不到，比不引导更伤**。

## 判据（五条，逐条可红）

1. **能力锚成立**：每条入口的 `tool` 必须是真实注册的工具（`app/tools/*.py` 的类级 `name = "..."`）。
2. **权限锚存在**：每条入口的工具必须**声明** `required_permissions` —— 没有权限码的入口，
   过滤就无从判起，等于又回到静态清单。
3. **过滤真的接在端点上**：`get_quick_actions` 必须调用 `_quick_action_visible`，且该函数必须调用
   `check_permission` —— **与工具执行同一个谓词**（不允许出现第二份权限口径）。
4. **投影非空且无死项**：对每个内置岗位，过滤后**至少可见 1 条**；且每条入口**至少有一个岗位可见**
   （否则它就是所有岗位的死入口，该删）。
5. **上述四条都能红**：喂合成世界做注入式自证（见 `TestInjectionProof`），并带负控（未注入 ⇒ 绿）。

## 覆盖不到什么（照实登记）

- 判不了「这个岗位**应该**看到哪几条」（那是业务口径，归评审）；本判据只判**可执行性**。
- 判不了运行时的 `c_end_reachable` 分支（C 端 JWT 无权限码；本端点只被 B 端 admin-web / bmini-app 消费）。
- 不查 GitHub / 不联网；纯静态（`ci workflow helper unit tests` job 只装 `pytest` + `pyyaml`，
  故此处**不 import** `app.*`，全部用 AST 解析 —— 运行时行为由
  `backend/ai-agent-service/tests/test_chat.py::TestQuickActions` 承担）。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAT_PY = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "api" / "chat.py"
TOOLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "tools"
MANIFEST_PATH = REPO_ROOT / "rbac" / "manifest.json"

#: 与 `app/tools/base.py` 同值的 C 端角色集合（本判据只判 B 端面，见文件头「覆盖不到什么」）
CUSTOMER_ONLY_ROLES = frozenset({"customer", "agent"})


# ────────────────────────── 解析 ──────────────────────────


def _shortcuts_from_source(text: str) -> tuple[list[dict], list[dict]]:
    """从 `chat.py` 的模块级字面量取 `QUICK_ACTIONS` / `TOOL_SHORTCUTS`。

    用 AST 而不是 import：本判据跑在 `ci workflow helper unit tests`（无 app 依赖）。
    """
    tree = ast.parse(text)
    found: dict[str, list[dict]] = {}
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in {"QUICK_ACTIONS", "TOOL_SHORTCUTS"}:
            continue
        if node.value is None:
            continue
        found[target.id] = [
            ast.literal_eval(elt) if isinstance(elt, ast.Dict)
            else {kw.arg: ast.literal_eval(kw.value) for kw in elt.keywords if kw.arg}
            for elt in node.value.elts
        ]
    missing = {"QUICK_ACTIONS", "TOOL_SHORTCUTS"} - set(found)
    assert not missing, f"chat.py 里找不到入口清单：{sorted(missing)}（判据在空跑）"
    return found["QUICK_ACTIONS"], found["TOOL_SHORTCUTS"]


def _tool_decls_from_source(text: str) -> dict[str, list[str] | None]:
    """从工具模块取 `name` → `required_permissions`（`None` = 未声明）。"""
    tree = ast.parse(text)
    decls: dict[str, list[str] | None] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        name: str | None = None
        required: list[str] | None = None
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                target = stmt.targets[0]
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "name" and isinstance(stmt.value, ast.Constant):
                    name = stmt.value.value
                elif target.id == "required_permissions":
                    try:
                        required = list(ast.literal_eval(stmt.value))
                    except (ValueError, TypeError):
                        required = None
        if name:
            decls[name] = required
    return decls


def _calls_in(tree: ast.AST, func: str) -> set[str]:
    """`func` 函数体内被调用的名字集合（`f(...)` 与 `obj.f(...)` 都算）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == func:
            called: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    target = sub.func
                    if isinstance(target, ast.Name):
                        called.add(target.id)
                    elif isinstance(target, ast.Attribute):
                        called.add(target.attr)
            return called
    return set()


def _permits(required: list[str] | None, role: str, permissions: frozenset[str]) -> bool:
    """`BaseTool.check_permission` 的**B 端分支**复述（本文件的判据世界用；运行时真值在 base.py）。

    与真值的一致性由判据 3（结构：必须调 `check_permission`）+ `test_chat.py::TestQuickActions`
    （行为：逐角色实跑）两侧共同钉住 —— 这里不假装自己就是真值。
    """
    if not required:  # 未声明权限码 ⇒ 落角色层，本判据不建模（判据 2 已先禁掉这种入口）
        return True
    if role in CUSTOMER_ONLY_ROLES:
        return False
    if "*" in permissions:
        return True
    return any(code in permissions for code in required)


# ────────────────────────── 世界 ──────────────────────────


class World:
    """可注入的判据世界：入口清单 × 工具权限 × 岗位种子。"""

    def __init__(
        self,
        quick_actions: list[dict],
        tool_shortcuts: list[dict],
        tools: dict[str, list[str] | None],
        roles: dict[str, list[str]],
    ) -> None:
        self.quick_actions = quick_actions
        self.tool_shortcuts = tool_shortcuts
        self.tools = tools
        self.roles = roles

    @property
    def entries(self) -> list[dict]:
        return [*self.quick_actions, *self.tool_shortcuts]

    def visible_ids(self, role: str) -> list[str]:
        permissions = frozenset(self.roles[role])
        return [
            e["id"]
            for e in self.entries
            if _permits(self.tools.get(e["tool"]), role, permissions)
        ]

    def audit(self) -> list[str]:
        """判据 1/2/4 —— 返回具名违规（空 = 绿）。"""
        offenders: list[str] = []
        for entry in self.entries:
            tool = self.tools.get(entry["tool"])
            if tool is None and entry["tool"] not in self.tools:
                offenders.append(f"{entry['id']}：tool {entry['tool']!r} 未注册")
                continue
            if not tool:
                offenders.append(
                    f"{entry['id']}：tool {entry['tool']!r} 未声明 required_permissions（过滤无从判起）"
                )
        for role in sorted(self.roles):
            if not self.visible_ids(role):
                offenders.append(f"岗位 {role!r} 过滤后一条入口都不剩（空态无处回退）")
        for entry in self.entries:
            if not any(entry["id"] in self.visible_ids(role) for role in self.roles):
                offenders.append(f"{entry['id']}：对任何内置岗位都不可见（该删的死入口）")
        return offenders

    def filter_wired(self, chat_source: str) -> list[str]:
        """判据 3 —— 端点真的接上了「与工具层同一个谓词」的过滤。"""
        tree = ast.parse(chat_source)
        endpoint = _calls_in(tree, "get_quick_actions")
        predicate = _calls_in(tree, "_quick_action_visible")
        offenders: list[str] = []
        if "_quick_action_visible" not in endpoint:
            offenders.append("get_quick_actions 没有调用 _quick_action_visible（静态清单回来了）")
        if "check_permission" not in predicate:
            offenders.append(
                "_quick_action_visible 没有调用 check_permission（入口与工具各判一套 ⇒ 第二份权限口径）"
            )
        return offenders


def real_world() -> World:
    quick_actions, tool_shortcuts = _shortcuts_from_source(CHAT_PY.read_text(encoding="utf-8"))
    tools: dict[str, list[str] | None] = {}
    for path in sorted(TOOLS_DIR.glob("*.py")):
        tools.update(_tool_decls_from_source(path.read_text(encoding="utf-8")))
    seed = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["roles"]["seed"]
    return World(quick_actions, tool_shortcuts, tools, {code: list(codes) for code, codes in seed.items()})


# ────────────────────────── 判据（真语料） ──────────────────────────


def test_every_entry_has_a_real_tool_and_a_permission_code() -> None:
    """判据 1 + 2：能力锚必须是真实注册的工具，且该工具必须声明权限码。"""
    world = real_world()
    anchor_offenders = [o for o in world.audit() if "未注册" in o or "未声明" in o]
    assert not anchor_offenders, "快捷入口的能力/权限锚不成立：\n" + "\n".join(anchor_offenders)


def test_endpoint_filters_with_the_tool_predicate() -> None:
    """判据 3：过滤接线 + 谓词单一（结构）。删掉过滤 ≡ 本判据红。"""
    offenders = real_world().filter_wired(CHAT_PY.read_text(encoding="utf-8"))
    assert not offenders, "快捷入口的权限投影没接上：\n" + "\n".join(offenders)


def test_no_role_is_left_with_an_empty_menu_and_no_entry_is_globally_dead() -> None:
    """判据 4：每岗至少 1 条、每条至少 1 岗可见（对 8 个内置岗位现取，不写死数量）。"""
    offenders = real_world().audit()
    assert not offenders, "权限投影的形状不成立：\n" + "\n".join(offenders)


def test_inspector_is_neither_starved_nor_over_served() -> None:
    """实例判据（改前 6/7 死）：质检员恰好可见「交付风险」那一条。

    钉的是**投影方向**：按权限**减**，不是按岗位**加** —— inspector 持 `production:view`，
    故只剩这一条；若哪天它变成 0 或 7，判据 4 与这条会同时说话。
    """
    world = real_world()
    assert world.visible_ids("inspector") == ["delivery_risk"]


# ────────────────────────── 判据 5：注入式红证 ──────────────────────────


def _ok_world() -> World:
    """四岗四入口的最小世界（脱离真语料，专供注入）。"""
    return World(
        quick_actions=[
            {"id": "a", "tool": "tool_a"},
            {"id": "b", "tool": "tool_b"},
        ],
        tool_shortcuts=[{"id": "c", "tool": "tool_c"}],
        tools={"tool_a": ["perm:a"], "tool_b": ["perm:b"], "tool_c": ["perm:c"]},
        roles={"r1": ["perm:a", "perm:b"], "r2": ["perm:c"], "r3": ["*"]},
    )


def test_world_control_is_green() -> None:
    """负控：未注入 ⇒ 合成世界与真语料都必须绿（否则下面的红证是空跑）。"""
    assert _ok_world().audit() == []
    assert real_world().audit() == []


def test_missing_permission_declaration_goes_red() -> None:
    """判据 2 红证：把某个工具的 required_permissions 抹掉 ⇒ 具名判红。"""
    world = _ok_world()
    world.tools["tool_a"] = None
    offenders = world.audit()
    assert any("a：tool 'tool_a' 未声明 required_permissions" in o for o in offenders), offenders


def test_unregistered_tool_goes_red() -> None:
    """判据 1 红证：入口指向不存在的工具 ⇒ 具名判红。"""
    world = _ok_world()
    del world.tools["tool_c"]
    offenders = world.audit()
    assert any("c：tool 'tool_c' 未注册" in o for o in offenders), offenders


def test_starved_role_goes_red() -> None:
    """判据 4 红证之一：某岗位被过滤到 0 条 ⇒ 具名判红。"""
    world = _ok_world()
    world.roles["r2"] = []
    offenders = world.audit()
    assert any("岗位 'r2' 过滤后一条入口都不剩" in o for o in offenders), offenders


def test_globally_dead_entry_goes_red() -> None:
    """判据 4 红证之二：某条入口对所有岗位都不可见 ⇒ 具名判红。

    先让没有 `*` 的岗位各自有别的入口可看（否则会同时触发「岗位被饿死」那条，遮住本证）。
    """
    world = _ok_world()
    world.roles.update({"r2": ["perm:a"], "r3": ["perm:a", "perm:b"]})
    world.tools["tool_c"] = ["perm:zzz"]
    offenders = world.audit()
    assert any("c：对任何内置岗位都不可见" in o for o in offenders), offenders


def test_unwired_filter_goes_red() -> None:
    """判据 3 红证：把端点改回静态清单（不调 `_quick_action_visible`）⇒ 判红。"""
    static_source = '''
async def get_quick_actions(current_user):
    actions = [{k: v for k, v in a.items()} for a in QUICK_ACTIONS]
    return actions
'''
    offenders = _ok_world().filter_wired(static_source)
    assert any("没有调用 _quick_action_visible" in o for o in offenders), offenders


def test_second_permission_predicate_goes_red() -> None:
    """判据 3 红证：入口自己写一套权限判断（不调 `check_permission`）⇒ 判红。"""
    own_predicate = '''
def _quick_action_visible(action, current_user):
    return "product:list" in (current_user.permissions or [])

async def get_quick_actions(current_user):
    return [a for a in QUICK_ACTIONS if _quick_action_visible(a, current_user)]
'''
    offenders = _ok_world().filter_wired(own_predicate)
    assert any("没有调用 check_permission" in o for o in offenders), offenders
