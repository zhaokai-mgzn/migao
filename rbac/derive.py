"""RBAC 派生器：由 `rbac/manifest.json` 派生「角色 → 码」「码目录」与「**页面 → 码**」三类事实。

跟踪单 issue #5699；设计真值源 `docs/design/rbac-single-source.md` 的 §2.4（各消费面怎么派生）、
§4 的 **P2** 行（本文件第二段）与 **P3** 行（本文件第四段：页面 → 码）、§2.5 / §3.4 问题 3 末注
（逐页 `any|all`、**默认 `all`（fail-closed）**）。
判据 = `tests/unit_ci_workflows/test_rbac_derived_roles_and_catalog.py`（P2）与
`tests/unit_ci_workflows/test_rbac_derived_pages.py`（P3）。

## 它是什么，不是什么

- ✅ 它是**派生的唯一实现**：把清单里的声明投影成**各消费面应当长成的样子** ——
  P2 段（A1 种子 / A2 回退 / A7 登录面 / A3·B3·B4 ai-agent 镜像 / B1·B2 目录）
  + P3 段（`pages[]` → C1 节点码 / C4 守卫码 / 第一屏码 / 多码页 / 残留页 / 可见性投影），
  外加**值级**原语（「授予的码里哪些不在目录」「两个面对同一角色的码集分歧」「持码的岗位」），
  由生成器（喂**现值**）与判据（喂**派生值**）**共用同一份实现**。
- ✅ 它是**纯函数**（输入 = 清单 dict 或两张表，输出 = 可 JSON 化的普通结构）：注入式红证就是喂改过的输入。
  唯一的例外形状是 `page_present(parity, sources)` —— 它**必须**拿既有解析器模块当参数传进来
  （而不是 import），因为解析器的唯一家在 `tests/unit_ci_workflows/test_agent_permission_parity.py`，
  而本文件要被生成器与判据**同时**加载（谁 import 谁都会造出第二份实现）。
- ❌ 它**不**落盘任何生成物。P2/P3 的消费面（`backend/**` / `frontend/**` / ai-agent 镜像）在本阶段
  **照旧读自己的副本**（P2/P3 都不改行为）⇒ 落一个没人读的生成物只会多出一份**会陈旧的真值**
  （本仓已有 `test_dead_capability_meta_guard.py` 在治这一类）。派生在判据里**当场算**，
  ⇒ 设计 §5.2 的 **M3 新鲜度**在这里是**结构性质**：没有落盘产物，就没有「陈旧」这种状态。
- ❌ 它**不判现值对不对**（那是 P4/P5/P6 的人类裁定）；它只保证**派生结果 == 现值**（零 delta）。

## 「现值」从哪来（**一律沿用仓内既有解析器**，不另造第二套）

| 面 | 现值来源 |
|---|---|
| A1 种子 / A2 回退 / A7 登录面 | `tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `parse_role_defaults` / `parse_role_fallback`（后者传 `anchor=` 复用同一实现读 A7） |
| B1 / B2 目录（码 + 名称） | 同文件的 `parse_catalog_rows`（与 `parse_catalog` **同一份正则**，多取四列） |
| A3 / B3 / B4 ai-agent 镜像 | `ast.literal_eval` 读那三个模块级字面量（**Python 标准库**，不是第二套 Java 解析器）。为什么不能 import：该模块 `from app.tools.base import …` ⇒ 要装 ai-agent 依赖，而 `ci workflow helper unit tests` job 只装 pytest ⇒ import 失败即静默 skip（= 没跑）。 |
| **页面 → 码**（P3） | 同文件的 `parse_menu_ts_nodes` / `parse_menus` / `parse_route_guard` / `parse_frontend_api_calls` / `_effective_codes` + 它的页面锚点表 `MENU_READ_ENDPOINT_ANCHORS`（四跳现取，见 `page_present()`） |

## 边界（**覆盖不到什么**，照实登记）

① 只覆盖**能被既有解析器读到**的形态（`case "x" -> List.of(…)` / 五列目录行 / Python 字面量 /
   约定形态的菜单表）。同一事实若写成 `Map.of(...)`、YAML、或从 `@ConfigurationProperties` 注入 ⇒ **看不见**
   （与设计 §5.3 的 M1 边界同源）；
② **不覆盖 A4（迁移链的 `role_permissions` 授权）**：它是「存量租户一次性」的**谓词**，
   与「角色 → 默认码」不是同一个读数（设计 §3.1 已登记该差距）；本模块**不**把它算进派生目标；
③ **不覆盖 A5（`users.permissions` 快照）**：实例数据，不是声明（设计 §1.1 逐字）；
④ `*`（通配）**只在本模块里展开成目录全集**用于比较与分类；它**不改**任何消费面看到的字面量；
⑤ 本模块**不判断面之间的分歧该以哪一面为准** —— 它只**具名报出**分歧（那是授权决定）；
⑥ **P3 段的岗位全集只有 种子 ∪ 回退**（`role_tables()`）：租户自建的岗位在库里、仓内读不到
   ⇒ 可见性投影对它们**未取证**（设计 §3.4 问题 3 第 1 行的 `/dashboard` delta 正落在这里）；
   且 C2（`MenuController`）的**节点集**不属「页面 → 码」面（只判码列，见 P3 判据的 `NON_DERIVED_FACES`）。
"""
from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: ai-agent 侧的三个手抄镜像（设计 §1.1 的 **A3** / **B3** / **B4**）—— P2 的「生成物 == 现值」要读它们的现值。
AI_MIRROR_PATH = REPO_ROOT / "backend" / "ai-agent-service" / "tests" / "test_tool_permission_codes.py"
AI_LABELS_PATH = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "skills" / "base_skill.py"

#: 通配码（`admin` / `super_admin` 用它表示「全部权限」）。
WILDCARD = "*"

#: 读 ai-agent 镜像时取的模块级字面量（名字即设计真值源里的编号）。
MIRROR_LITERALS = ("ROLE_PERMISSIONS", "PERMISSION_CATALOG", "PERMISSION_LABELS")


# ══════════════════════════════════════════════════════════════════════════════
# 一、读「现值」：ai-agent 镜像（AST；纯标准库）
# ══════════════════════════════════════════════════════════════════════════════


class _UnwrapLiteralConstructors(ast.NodeTransformer):
    """把 `frozenset({…})` / `set(…)` / `tuple(…)` / `list(…)` 拆成它们的字面量参数。

    为什么需要：镜像里 `ROLE_PERMISSIONS` 的每个角色码集都写成 `frozenset({…})`
    ⇒ 直接 `ast.literal_eval` 会在嵌套的 `Call` 上抛「malformed node」。
    只拆**单参数且参数为字面量**的调用；别的形态原样留下（由 `literal_eval` fail-closed 抛错）。
    """

    _WRAPPERS = frozenset({"frozenset", "set", "tuple", "list"})
    #: 零参数形态（镜像里 `"customer": frozenset()` 就是这样写的）⇒ 换成对应的空字面量。
    _EMPTY = {"frozenset": ast.Set, "set": ast.Set, "tuple": ast.Tuple, "list": ast.List}

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        func = node.func
        if not (isinstance(func, ast.Name) and func.id in self._WRAPPERS) or node.keywords:
            return node
        if len(node.args) == 1:
            return node.args[0]
        if not node.args:
            return self._EMPTY[func.id](elts=[], ctx=ast.Load())
        return node


def module_literals(path: Path, names: tuple[str, ...]) -> dict[str, object]:
    """按 **AST** 取模块级字面量赋值（`ast.literal_eval`；嵌套的 `frozenset({…})` 先拆一层）。

    名字找不到 / 求值失败 ⇒ 抛错（fail-closed：读不到不得退化成空集恒绿）。
    """
    assert path.is_file(), f"ai-agent 镜像不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):  # `ROLE_PERMISSIONS: dict[...] = {…}`（带注解的赋值）
            name, value = getattr(node.target, "id", None), node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            name, value = getattr(node.targets[0], "id", None), node.value
        else:
            continue
        if name not in names or value is None:
            continue
        unwrapped = _UnwrapLiteralConstructors().visit(value)
        found[name] = ast.literal_eval(ast.fix_missing_locations(unwrapped))
    missing = sorted(set(names) - set(found))
    assert not missing, f"{path.name} 里读不到这些模块级字面量：{missing}（fail-closed）"
    return found


def mirror_present_values() -> dict[str, object]:
    """ai-agent 三个镜像的**现值**（规范化成普通结构，键名即设计真值源的编号）。"""
    role = module_literals(AI_MIRROR_PATH, ("ROLE_PERMISSIONS", "PERMISSION_CATALOG"))
    labels = module_literals(AI_LABELS_PATH, ("PERMISSION_LABELS",))
    return {
        "A3": {r: sorted(codes) for r, codes in sorted(role["ROLE_PERMISSIONS"].items())},
        "B4": sorted(role["PERMISSION_CATALOG"]),
        "B3": dict(sorted(labels["PERMISSION_LABELS"].items())),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 二、值级原语（纯函数；生成器喂现值、判据喂派生值 —— **同一份实现**）
# ══════════════════════════════════════════════════════════════════════════════


def codes_beyond_catalog(granted: Mapping[str, Iterable[str]], catalog: Iterable[str]) -> list[str]:
    """某个面授予、但**不在权限目录里**的码（升序、去重、`*` 不算）。

    P2 用它算 A7 的台账（设计 §1.4 的 A7 补登注：它授予的四个码在目录里**各 0 命中**）。
    """
    known = set(catalog)
    got = {code for codes in granted.values() for code in codes}
    return sorted(got - known - {WILDCARD})


def role_set_divergences(
    left: Mapping[str, Iterable[str]],
    right: Mapping[str, Iterable[str]],
    left_label: str = "left",
    right_label: str = "right",
) -> list[str]:
    """**逐名报出**「同一角色在两个面上的码集不一致」（只报告，**不修**）。

    只在**两面都有**的角色上比（面之间的角色集不同是**语义差异**，不是分歧：
    例如种子面没有 `product_manager`，那是「它不在种子里」，不是「它的码不一致」）。
    """
    out = []
    for role in sorted(set(left) & set(right)):
        a, b = sorted(left[role]), sorted(right[role])
        if a != b:
            out.append(f"{left_label} {role} = {a} / {right_label} = {b}")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 三、派生（纯函数：输入清单，输出各消费面应当长成的样子）
# ══════════════════════════════════════════════════════════════════════════════

#: 清单 `roles` 段里的四个面（**语义不同**，故分开存、不合表）。
ROLE_FACES = ("seed", "fallback", "login", "mirror_placeholders")


def _role_section(manifest: dict, key: str) -> dict[str, list[str]]:
    section = manifest["roles"][key]
    assert isinstance(section, dict), f"清单 roles.{key} 必须是「角色 → 码列表」的对象（fail-closed）"
    for role, codes in section.items():
        assert isinstance(codes, list), f"清单 roles.{key}.{role} 必须是列表（fail-closed）"
    return {role: sorted(codes) for role, codes in sorted(section.items())}


def catalog_codes(manifest: dict, key: str = "permission_service") -> list[str]:
    """目录码列（默认取 **B2 懒补种**那一列）。"""
    codes = manifest["codes"][key]
    assert codes, f"清单 codes.{key} 为空 ⇒ 派生会空跑（fail-closed）"
    return sorted(codes)


def derive_roles(manifest: dict) -> dict[str, dict[str, list[str]]]:
    """**派生：角色 → 码**（四个面合并后的规范化表：角色 → {它出现在哪些面: 各自的码}）。

    合并**不等于**互相一致 —— 面之间的不一致由 `role_set_divergences()` 具名报出，不在这里抹平。
    """
    faces = {name: _role_section(manifest, name) for name in ROLE_FACES}
    roles = sorted({role for face in faces.values() for role in face})
    return {role: {name: face[role] for name, face in faces.items() if role in face} for role in roles}


def derive_mirror_roles(manifest: dict) -> dict[str, list[str]]:
    """**派生：A3 镜像应当长成的样子** = 种子 ∪ 回退 ∪ 镜像占位（后者码集为空 —— 身份面角色）。

    口径出自设计 §1.1 A3 行：五个种子岗位取 seed 口径、两个历史遗留角色取回退口径；
    镜像里另有**不承载商户权限码**的占位角色（`customer` / `agent` / `tenant_admin`）。
    """
    out: dict[str, list[str]] = {}
    for name in ("seed", "fallback", "mirror_placeholders"):
        out.update(_role_section(manifest, name))
    return dict(sorted(out.items()))


def catalog_view(
    codes: Iterable[str],
    names: Mapping[str, str],
    role_maps: Iterable[Mapping[str, Iterable[str]]],
) -> dict[str, dict[str, object]]:
    """**码目录视图**（码 → 名称 + 持有它的角色）—— `derive_catalog` 与现值投影**共用同一份实现**。

    `holders` 由传入的**角色面**反查；`*`（通配）展开成目录全集（`admin` 恒全部权限 ——
    设计 §3.1 的现取口径）。不在这里的角色面（例如 A7 登录面）**不参与** holders：
    A7 的码不在目录里，混进来会让「谁持有这个码」答错人。
    """
    ordered = sorted(codes)
    holders: dict[str, list[str]] = {code: [] for code in ordered}
    for role_map in role_maps:
        for role in sorted(role_map):
            own = list(role_map[role])
            for code in (ordered if WILDCARD in own else own):
                if code in holders and role not in holders[code]:
                    holders[code].append(role)
    return {
        code: {"name": names.get(code), "holders": sorted(holders[code])} for code in ordered
    }


def derive_catalog(manifest: dict) -> dict[str, dict[str, object]]:
    """**派生：码目录**（码 → 名称 + 持有它的角色），由清单的 `seed` / `fallback` 两面反查。"""
    return catalog_view(
        catalog_codes(manifest),
        manifest["codes"]["names"],
        (_role_section(manifest, "seed"), _role_section(manifest, "fallback")),
    )


def consumer_surfaces(manifest: dict) -> dict[str, object]:
    """**P2 的全部派生结果**（设计 §2.4 的逐消费面投影）—— 判据拿它与现值逐项比对。"""
    return {
        "A1": _role_section(manifest, "seed"),
        "A2": _role_section(manifest, "fallback"),
        "A7": _role_section(manifest, "login"),
        "A3": derive_mirror_roles(manifest),
        "B1": catalog_codes(manifest, "registration"),
        "B2": catalog_codes(manifest, "permission_service"),
        "B3": {code: entry["name"] for code, entry in derive_catalog(manifest).items()},
        "B4": catalog_codes(manifest, "permission_service"),
    }


def present_ledger_counts(
    login_present: Mapping[str, Iterable[str]],
    catalog_present: Iterable[str],
    mirror_roles_present: Mapping[str, Iterable[str]],
    page_visibility_gaps: int,
) -> dict[str, int]:
    """P2/P3 新增的**只许缩短**台账的**现取**条数（设计 §5.2 的 M2 覆盖面在 P2/P3 的扩大）。

    - `A7_CODES_BEYOND_CATALOG`：A7 授予但不在目录里的码数（现取 4）；
    - `A7_VS_MIRROR_DIVERGENCES`：A7 与 ai-agent 镜像对**同一角色**给出不同码集的对数（现取 2）。
    - `PAGE_VISIBILITY_GAPS`（**P3 新增**）：可见性**投影复现不了现值**的页面数 —— 即
      `required_visibility_rule()` 判成 `node-code` 的那些页（现取 3：`/production/pool`、
      `/production/saving-board`、`/production/processing`）。🔴 只许缩短。
      它是**必填位置参数而不是带默认值的关键字参数**：默认 0 会让调用方忘记喂它 ⇒ 台账静默归零（假绿）。
    """
    return {
        "A7_CODES_BEYOND_CATALOG": len(codes_beyond_catalog(login_present, catalog_present)),
        "A7_VS_MIRROR_DIVERGENCES": len(
            role_set_divergences(login_present, mirror_roles_present, "A7(login)", "A3(镜像)")
        ),
        "PAGE_VISIBILITY_GAPS": int(page_visibility_gaps),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 四、P3 派生：「页面 → 码」（设计 §4 的 **P3** 行 / §2.4 的 C1~C4 投影 / §2.5 与 §3.4 的可见性规则）
# ══════════════════════════════════════════════════════════════════════════════
#
# P3 的**单一真值源** = 清单的 `pages[]` 段（每页：`gate` 菜单可见码 + `units` 第一屏读码 → 端点
# + `visibility_rule` 逐页投影规则）。本段把它投影成各消费面**应当长成的样子**：
#   C1 `menu_node_codes` / C3 `auth_menu_codes` / C4 `route_guard_codes` / 第一屏码 + 多码页 + 残留页
#   + 可见性（按规则把 units 投影成「看得见该菜单的岗位集」）。
# 现值一律由既有解析器现取（`page_present()`，只调 `test_agent_permission_parity.py` 的既有函数）。
# 🔴 与 P2 同款：**不落盘任何生成物**（新鲜度是结构性质），派生在判据里当场算。

#: 逐页可见性规则（设计 §3.4 问题 3 末注的裁定：`pages[]` 必须支持**逐页** `any|all`，
#: 且**默认 `all`（fail-closed）** —— 「允许半个页面可见」会造出新的「看得见做不了」，
#: 故**不**默认 OR；这条正是第 6 条残留（`/settings`）自我推翻上一稿结论的地方）。
VISIBILITY_ALL = "all"
VISIBILITY_ANY = "any"
#: **未收敛**：该页的可见性仍由手写节点码（`gate`）决定 —— `∩` / `∪` 两种投影**都复现不了现值**
#: ⇒ 必须具名登记（清单 `ledger_counts.PAGE_VISIBILITY_GAPS`，只许缩短），出口由 P4 逐条人裁定。
VISIBILITY_NODE_CODE = "node-code"
VISIBILITY_RULES = (VISIBILITY_ALL, VISIBILITY_ANY, VISIBILITY_NODE_CODE)
DEFAULT_VISIBILITY_RULE = VISIBILITY_ALL

#: 生效码为 `None` 的端点（未被任何权限码把守）在 `units` 里的组键。它**不是权限码** ⇒
#: 显式与码空间分开（`page_unit_codes()` 排除它；那批端点由判据 8 的 `UNANNOTATED_ENDPOINTS` 台账管）。
UNANNOTATED_UNIT_KEY = "__unannotated__"


def role_tables(manifest: dict) -> tuple[dict[str, list[str]], ...]:
    """可见性投影用的**两个岗位来源**（种子 / 硬编码回退）—— 与设计 §3.3(b) 的「持码的岗位」同口径。

    🔴 **不含** `roles` 表里租户自建的岗位（**不可从仓内读到**）：那是本段的**覆盖面边界**，
    逐条登记在 P3 判据的 `UNCOVERED_FACES` 里（含设计 §3.4 问题 3 第 1 行的 `/dashboard` delta）。
    """
    return (_role_section(manifest, "seed"), _role_section(manifest, "fallback"))


def all_role_names(*tables: Mapping[str, Iterable[str]]) -> list[str]:
    """岗位全集（**角色名去重**）：各来源里出现过的全部角色。"""
    return sorted({role for table in tables for role in table})


def code_holders(code: str | None, *tables: Mapping[str, Iterable[str]]) -> list[str]:
    """持该码的岗位（角色名去重、升序；`*` 通配恒真 = 该来源的全部角色）。

    与既有守卫 `_holder_roles` 的口径差**只有一处且是具名的**：那边带 `@seed` / `@fallback` 后缀
    （设计 §3.3(b) 要区分来源），本函数按设计 §3.4 差量表的「按角色去重」口径。
    """
    if code is None:
        return []
    out: set[str] = set()
    for table in tables:
        for role, codes in table.items():
            if WILDCARD in codes or code in codes:
                out.add(role)
    return sorted(out)


def page_unit_codes(page: Mapping[str, object]) -> list[str]:
    """该页 `units` 里的**权限码**（升序；排除未注解端点组）。多码页 ⟺ 本列表长度 ≥ 2。"""
    units = page["units"]
    assert isinstance(units, dict), (
        f"清单 pages[] 的 `units` 必须是「码 → 端点列表」的对象（fail-closed）：path={page.get('path')!r}"
    )
    return sorted(str(code) for code in units if code != UNANNOTATED_UNIT_KEY)


def effective_visibility_rule(page: Mapping[str, object]) -> str:
    """逐页规则；**字段缺失 / 为空 ⇒ `all`（fail-closed 默认）**（设计 §3.4 问题 3 末注）。

    默认值走**函数**而不是「取值时 `.get(…, 'all')` 散在各处」：这样「默认是 fail-closed 的」
    本身可被判据单测（红证 = 删掉字段后投影必须按 `all` 算，而不是按 `any` 或当空）。
    """
    rule = page.get("visibility_rule") or DEFAULT_VISIBILITY_RULE
    assert rule in VISIBILITY_RULES, (
        f"pages[] 的 `visibility_rule` = {rule!r} 不在 {VISIBILITY_RULES} 里（fail-closed："
        f"未登记的规则名不许静默当默认）：path={page.get('path')!r}"
    )
    return str(rule)


def project_visibility(
    rule: str,
    unit_codes: Iterable[str],
    tables: Iterable[Mapping[str, Iterable[str]]],
) -> list[str] | None:
    """把 units 按规则投影成「看得见该菜单的岗位集」。

    - `all`：**每个** unit 的码都持有（`∩`）—— fail-closed 默认；
    - `any`：**任一** unit 的码持有（`∪`）；
    - `node-code`：**不由 units 决定** ⇒ 返回 `None`（该页的可见性现取口径 = 手写节点码 `gate`）；
    - 一个码都没有（第一屏全落在未注解端点）⇒ 同样返回 `None`（投影无输入，不许把空集当答案）。
    """
    codes = list(unit_codes)
    if rule == VISIBILITY_NODE_CODE or not codes:
        return None
    sets = [set(code_holders(code, *tables)) for code in codes]
    combined = set.intersection(*sets) if rule == VISIBILITY_ALL else set.union(*sets)
    return sorted(combined)


def required_visibility_rule(
    unit_codes: Iterable[str],
    present_roles: Iterable[str],
    tables: Iterable[Mapping[str, Iterable[str]]],
) -> str:
    """**现值要求**的逐页规则：能复现现值岗位集的规则里取 fail-closed 优先的那个。

    优先级 = `all` > `any` > `node-code`（设计 §3.4 问题 3 末注的「默认 `all`（fail-closed）」）：
    两种投影都能复现时（单码页 / 两个码的持有者集合逐值相同，如 `/production/routings`）**取 `all`**；
    只有 `∪` 能复现时取 `any`；都复现不了 ⇒ `node-code`（**未收敛** ⇒ 进 gap 台账）。
    现取结果：`all` **17** 页 / `any` **0** 页 / `node-code` **4** 页。
    """
    present = set(present_roles)
    for rule in (VISIBILITY_ALL, VISIBILITY_ANY):
        projected = project_visibility(rule, unit_codes, tables)
        if projected is not None and set(projected) == present:
            return rule
    return VISIBILITY_NODE_CODE


def visible_roles(
    page: Mapping[str, object],
    rule: str,
    tables: Iterable[Mapping[str, Iterable[str]]],
    known_roles: Iterable[str],
) -> list[str]:
    """「**谁看得见这个菜单**」—— `visibility_rule` 投影；`node-code` 时退回手写节点码的口径。

    `node-code` 页的读数不是「算不出来」（那是 `roles = null`），而是**今天实际生效的那套**：
    `gate` 为空（有意无码）⇒ 全员可见；否则 = 持 `gate` 者。这样派生与现值在**同一个键**上可比，
    而「规则是 `node-code`」这件事由 `visibility.<path>.rule` 单独表达（两者的分工是判据可判的）。
    """
    projected = project_visibility(rule, page_unit_codes(page), tables)
    if projected is not None:
        return projected
    gate = page["gate"]
    return code_holders(str(gate), *tables) if gate else sorted(set(known_roles))


def page_units_view(page: Mapping[str, object]) -> dict[str, list[str]]:
    """规范化一页的 `units`（码 → 升序端点列表）—— 生成器、判据、清单三边共用同一份投影。"""
    units = page["units"]
    assert isinstance(units, dict), f"pages[] 的 `units` 必须是对象：path={page.get('path')!r}"
    return {str(code): sorted(str(e) for e in endpoints) for code, endpoints in sorted(units.items())}


def normalize_page(raw: Mapping[str, object]) -> dict[str, object]:
    """把「一页」规范化成可逐值比对的形态（生成器与判据共用，避免两边各写一份键序）。"""
    return {
        "key": raw["key"],
        "name": raw["name"],
        "path": raw["path"],
        "gate": raw["gate"],
        "units": page_units_view(raw),
        "visibility_rule": effective_visibility_rule(raw),
    }


def derive_pages(manifest: dict) -> list[dict[str, object]]:
    """**派生：页面表**（清单 `pages[]` 的规范化投影，按 `path` 升序）。"""
    pages = manifest["pages"]
    assert isinstance(pages, list) and pages, "清单 pages[] 为空 ⇒ 派生会空跑（fail-closed）"
    return [normalize_page(page) for page in sorted(pages, key=lambda p: str(p["path"]))]


def derive_page_faces(manifest: dict) -> dict[str, object]:
    """**P3 的全部派生结果**（判据拿它与现值逐项比对）—— 每一面都是清单 `pages[]` 的投影。

    | 面 | 投影规则 | 对照的现值 |
    |---|---|---|
    | `menu_node_codes` | 带 `path` 的节点 → 该页 `gate`；组头（无 `path`）→ `null` | C1（`parse_menu_ts_nodes`）|
    | `auth_menu_codes` | `gate` 非空的页 → `gate`（登录菜单只下发有码的节点） | C3（`parse_menus()['auth']`）|
    | `route_guard_codes` | 每页 `path → gate`（全 21 页；比对面过滤别名/例外，见判据台账） | C4（`parse_route_guard`）|
    | `first_screen_codes` | 每页 `units` 的码集 | 判据 12 的四跳现取 |
    | `units` | 每页 码 → 端点列表 | 同上（逐端点） |
    | `multi_code_pages` | 码集长度 ≥ 2 的页 → 码集 | `MULTI_READ_ENDPOINT_PAGES`（3 条，逐值冻结） |
    | `parity_residual_pages` | 「存在某个第一屏码 ≠ 该页 `gate`」的页 | `MENU_READ_PARITY_RESIDUALS`（6 条，只许缩短） |
    | `visibility` | 每页 `visibility_rule` + 按它投影出的岗位集 | 现值岗位集（`seed` ∪ `fallback` 的持码者） |
    """
    pages = derive_pages(manifest)
    tables = role_tables(manifest)
    by_path = {str(page["path"]): page for page in pages}

    menu_node_codes: dict[str, str | None] = {}
    for node in manifest["menu_nodes"]:
        if node["path"] is None:
            menu_node_codes[str(node["name"])] = None
            continue
        page = by_path.get(str(node["path"]))
        assert page is not None, (
            f"菜单节点『{node['name']}』（`{node['path']}`）在清单 `pages[]` 里没有声明 ⇒ "
            "「页面 → 码」面漏了一页（fail-closed；未登记即红）"
        )
        assert page["name"] == node["name"], (
            f"清单 `pages[]` 的 `{node['path']}` 写的是『{page['name']}』，而 `menu_nodes` 是"
            f"『{node['name']}』（路径 ↔ 节点漂移 ⇒ 锚错人）"
        )
        menu_node_codes[str(node["name"])] = page["gate"]

    first_screen_codes = {path: page_unit_codes(page) for path, page in by_path.items()}
    known_roles = all_role_names(*tables)
    return {
        "menu_node_codes": dict(sorted(menu_node_codes.items())),
        "route_guard_codes": {path: page["gate"] for path, page in sorted(by_path.items())},
        "first_screen_codes": dict(sorted(first_screen_codes.items())),
        "units": {path: dict(page["units"]) for path, page in sorted(by_path.items())},
        "multi_code_pages": {
            path: codes for path, codes in sorted(first_screen_codes.items()) if len(codes) >= 2
        },
        "parity_residual_pages": sorted(
            path
            for path, page in by_path.items()
            if any(code != page["gate"] for code in first_screen_codes[path])
        ),
        "visibility": {
            path: {
                "rule": page["visibility_rule"],
                "roles": visible_roles(page, str(page["visibility_rule"]), tables, known_roles),
            }
            for path, page in sorted(by_path.items())
        },
    }


def page_present(parity, sources: Mapping[str, str] | None = None) -> dict[str, object]:
    """**「页面 → 码」的现值**（只调既有解析器；`parity` = `test_agent_permission_parity` 模块）。

    四跳现取（与判据 12 逐字同口径，**不另造解析器**）：菜单节点 → 页面锚点 → `lib/api.ts` 的 URL
    → Java 端的**生效码**（方法级优先）。角色面走现值 `parse_role_defaults` / `parse_role_fallback`。

    返回 `pages`（21 页，含**现值要求的** `visibility_rule`）/ C1 / C3 / C4（源序）/ 可见性现值。
    """
    src = sources if sources is not None else parity._source_map()
    world = parity.build_world(src)
    nodes = parity.parse_menu_ts_nodes(src["menu:frontend"])
    api_calls = parity.parse_frontend_api_calls(src["frontend:api.ts"])
    tables = (
        {role: sorted(codes) for role, codes in parity.parse_role_defaults(
            src["java:service/RegistrationService.java"]).items()},
        {role: sorted(codes) for role, codes in parity.parse_role_fallback(
            src["java:service/RoleService.java"]).items()},
    )
    known_roles = all_role_names(*tables)

    pages: list[dict[str, object]] = []
    for node in nodes:
        if node.path is None:
            continue
        anchor = parity.MENU_READ_ENDPOINT_ANCHORS.get(node.path)
        assert anchor is not None, (
            f"菜单节点『{node.name}』（`{node.path}`）没有登记第一屏锚点 ⇒ 现值无从现取（fail-closed）"
        )
        grouped: dict[str, set[str]] = {}
        for call in anchor.calls:
            obj, fn = call.split(".", 1)
            target = api_calls.get((obj, fn))
            assert target is not None, f"`{call}` 在 `lib/api.ts` 里解析不出 URL（fail-closed）"
            verb, url = target
            effective = parity._effective_codes(world, verb, url)
            assert effective is not None, f"`{call}` → `{verb} {url}` 在端点表里查不到（fail-closed）"
            endpoint = f"{verb} {parity._norm_endpoint_url(url)}"
            for code in effective:
                grouped.setdefault(code or UNANNOTATED_UNIT_KEY, set()).add(endpoint)
        units = {code: sorted(endpoints) for code, endpoints in sorted(grouped.items())}
        unit_codes = sorted(code for code in units if code != UNANNOTATED_UNIT_KEY)
        present_roles = code_holders(node.code, *tables) if node.code else list(known_roles)
        pages.append(
            {
                "key": node.key,
                "name": node.name,
                "path": node.path,
                "gate": node.code,
                "units": units,
                "visibility_rule": required_visibility_rule(unit_codes, present_roles, tables),
            }
        )
    pages.sort(key=lambda page: str(page["path"]))
    by_path = {str(page["path"]): page for page in pages}
    first_screen_codes = {path: page_unit_codes(page) for path, page in by_path.items()}
    return {
        "pages": pages,
        "menu_node_codes": {node.name: node.code for node in nodes},
        "menu_controller_codes": {
            name: code for name, code in parity.parse_menus(src)["controller"].items()
        },
        "auth_menu_codes": {
            name: code for name, code in parity.parse_menus(src)["auth"].items() if code is not None
        },
        "route_guard": [
            [prefix, code] for prefix, code in parity.parse_route_guard(src["route:layout.tsx"])
        ],
        # 下面四面是**现值页面表的投影**（与派生侧同一套规则 ⇒ 逐值比对的键空间一致）；
        # 它们的**独立对照**另有其人：多码页 / 残留页 = 既有守卫的两张冻结表，units / 第一屏码 = 四跳现取。
        "units": {path: dict(page["units"]) for path, page in sorted(by_path.items())},
        "first_screen_codes": dict(sorted(first_screen_codes.items())),
        "multi_code_pages": {
            path: codes for path, codes in sorted(first_screen_codes.items()) if len(codes) >= 2
        },
        "parity_residual_pages": sorted(
            path
            for path, page in by_path.items()
            if any(code != page["gate"] for code in first_screen_codes[path])
        ),
        "visibility": {
            path: {
                "rule": page["visibility_rule"],
                "roles": visible_roles(
                    page, str(page["visibility_rule"]), tables, known_roles
                ),
            }
            for path, page in sorted(by_path.items())
        },
    }


def load_manifest(path: Path | None = None) -> dict:
    """读声明真值源（`rbac/manifest.json`）；缺文件 ⇒ 抛错（fail-closed，不静默当空）。"""
    target = path or (REPO_ROOT / "rbac" / "manifest.json")
    assert target.is_file(), f"声明真值源不存在：{target}（fail-closed）"
    return json.loads(target.read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════════
# 五、P5 段：「存量租户」的 A4 迁移链 → 「清单 vs 各迁移累计」的差集
# ══════════════════════════════════════════════════════════════════════════════
#
# **本段的定位**（设计真值源 §4 的 **P5** 行 / §2.7 / §3.1）：P5 = 「存量收敛」。存量租户的
# `role_permissions` 是「该租户**历史跑过的迁移**的并集」（路径依赖）⇒ 要判断某个内置岗位在存量库上
# **实际拿到哪些码**，只能把迁移链（A4）当作**谓词序列**推演一遍（本机无真库，设计 §6.1 已登记）。
#
# 🔴 **它算的是「声明面」，不是真库读数**：本段**不连库** —— 输入 = 清单（岗位声明）+ 迁移文件的
# 授权谓词，输出 = 「每个内置岗位在链上累计拿到哪些码」。真库复算的重启条件写在本段的边界 ③。
#
# 🔴 **它不判现值对不对**：差集非空 = 「链上漏了声明里有的码」；消解它是**授权动作**（P5 的迁移由人批准）。
# 本段只做两件事：① 把差集**算准**（生成器与判据共用这一份实现）；② 让「漏码」在判据里**具名报出**。
#
# ## 推演规则（逐条写清，避免被读成覆盖面更大的东西）
#
# 链上每一条 `INSERT INTO role_permissions … SELECT … FROM roles r JOIN permissions p …` 被解析成四元：
#   · `roles`   = 显式岗位谓词（`r.code = 'x'` / `r.code IN (…)`）；
#   · `codes`   = 显式码谓词（`p.code = 'x'` / `p.code IN (…)`，JOIN 里或 WHERE 里都收）；
#                 **缺省 = `None`** ⇒ 「该租户目录里的**全部**码」（V29/V32 授 admin 的那句）。
#   · `when_has`= **条件授权**（`EXISTS (… p0.code = 'Y' …)`）：该语句还授给「**此刻**已持 `Y` 的岗位」
#                 （V129 的 ②-a/②-b 就是这个形态：授给「原本持管理码」的岗位）。
#   · `version` = 迁移号（排序键）。
# 推演按 `(version, 路径)` 顺序累加：`state[role] |= codes`；`codes is None` 时取 **`available_at(version)`**
# = 「清单目录里，引入版本 ≤ 本版本（或**不由链引入**）的那些码」—— 这条规则的作用是：
# **后加的码不会被早先那句「全部码」白送**（否则「存量 admin 缺 11 码」这个事实会被推演抹掉）。
#
# ## 边界（照实登记）
# ① **只认约定形态**（与设计 §5.3 的 M1 形态面同源）：`Map.of` / YAML / 动态拼 SQL 的授权**看不见** ——
#    但「语句数 == 解析数」是硬断言（`parse_role_grants` 末行），**读不懂的新语句不会静默放过**；
# ② **不推演目录的懒补种**（`PermissionService.ensureFullPermissionCatalog` 的调用时刻仓内答不了）
#    ⇒ 目录模型 = 清单的码目录，**不是**「某租户此刻的真实目录」；
# ③ **不推演取消授权**：链上只有 `INSERT … ON CONFLICT DO NOTHING`；租户在「岗位权限」页手工取消的勾选
#    （= 删 `role_permissions` 行）**不在射程** ⇒ 差集是「链应当给而没给」的量，**不是**「租户此刻缺什么」
#    的量。后者只能真库复算（重启条件 = 设计 §6.1 第 1 条：接上真库后逐租户逐岗位复算）；
# ④ 目录外的授权（`agent:quickreply` 这类历史码）**不参与**差集，单独作为读数返回（`beyond_catalog`）。

#: 迁移链的两个目录（`migration-archive` 是「已归档但仍属链上历史」的那一半；两者**都**在射程）。
MIGRATION_DIRS = (
    "backend/admin-api/src/main/resources/db/migration",
    "backend/admin-api/src/main/resources/db/migration-archive",
)

_ROLE_GRANT_MARKER = "INSERT INTO role_permissions"


@dataclass(frozen=True)
class RoleGrant:
    """链上一条「岗位 ← 码」授权语句（**解析结果**，不是原文）。"""

    version: int
    file: str
    roles: frozenset[str]
    #: 显式码谓词；`None` = 「该租户目录的全部码」（推演时按 `available_at(version)` 展开）。
    codes: frozenset[str] | None
    #: 条件授权的码（`EXISTS (… p0.code = 'Y' …)`）：另授给「此刻已持 Y」的岗位。
    when_has: frozenset[str]


def _strip_sql_comments(text: str) -> str:
    """剥 SQL 注释（**唯一实现**在 `tests/unit_ci_workflows/_sql_schema.py`；本函数只是它的加载器）。"""
    import importlib.util
    import sys as _sys

    name = "migao_sql_schema_for_derive"
    mod = _sys.modules.get(name)
    if mod is None:
        path = REPO_ROOT / "tests" / "unit_ci_workflows" / "_sql_schema.py"
        assert path.is_file(), f"SQL 剥注释的唯一实现不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader, f"无法为 {path} 建立加载器（fail-closed）"
        mod = importlib.util.module_from_spec(spec)
        _sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod.strip_sql_comments(text)


def migration_files(root: Path | None = None) -> list[tuple[int, str, str]]:
    """链上全部迁移：`[(版本号, 仓库相对路径, 原文)]`，按 `(版本号, 路径)` 升序。

    版本号解析不出 ⇒ 抛错（fail-closed）：一条**读不出号**的迁移会让「顺序」变成猜测。
    """
    base = root or REPO_ROOT
    out: list[tuple[int, str, str]] = []
    for rel in MIGRATION_DIRS:
        directory = base / rel
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("V*.sql")):
            match = re.match(r"V(\d+)__", path.name)
            assert match, f"迁移文件名不合 `V<数字>__…` 形态：{path.name}（顺序无法确定 ⇒ fail-closed）"
            out.append(
                (int(match.group(1)), path.relative_to(base).as_posix(), path.read_text(encoding="utf-8"))
            )
    assert out, "迁移链解析出 0 个文件 ⇒ 差集会恒为空（空断言，fail-closed）"
    return sorted(out)


def parse_role_grants(version: int, rel_path: str, sql: str) -> list[RoleGrant]:
    """把一份迁移文本里的 `INSERT INTO role_permissions` 语句解析成 `RoleGrant`（见本段「推演规则」）。"""
    code = _strip_sql_comments(sql)
    out: list[RoleGrant] = []
    idx = 0
    while True:
        start = code.find(_ROLE_GRANT_MARKER, idx)
        if start < 0:
            break
        end = code.find(";", start)
        assert end > start, f"{rel_path}: `{_ROLE_GRANT_MARKER}` 语句没有以 `;` 收尾（解析不了 ⇒ fail-closed）"
        stmt = code[start:end]
        idx = end + 1
        roles = set(re.findall(r"r\.code\s*=\s*'([a-z_]+)'", stmt))
        for group in re.findall(r"r\.code\s+IN\s*\(([^)]*)\)", stmt):
            roles.update(re.findall(r"'([a-z_]+)'", group))
        explicit = set(re.findall(r"(?<![A-Za-z0-9_])p\.code\s*=\s*'([a-z_:]+)'", stmt))
        for group in re.findall(r"(?<![A-Za-z0-9_])p\.code\s+IN\s*\(([^)]*)\)", stmt):
            explicit.update(re.findall(r"'([a-z_:]+)'", group))
        when_has = set(re.findall(r"p0\.code\s*=\s*'([a-z_:]+)'", stmt))
        assert roles, f"{rel_path}: 一条 role_permissions 语句解析不出任何岗位谓词（fail-closed）"
        out.append(
            RoleGrant(
                version=version,
                file=rel_path,
                roles=frozenset(roles),
                codes=frozenset(explicit) if explicit else None,
                when_has=frozenset(when_has),
            )
        )
    raw = len(re.findall(_ROLE_GRANT_MARKER, code))
    assert raw == len(out), (
        f"{rel_path}: `{_ROLE_GRANT_MARKER}` 语句数 {raw} ≠ 解析数 {len(out)}"
        "（有语句没被读进来 ⇒ 推演会漏授权，fail-closed）"
    )
    return out


def catalog_introduction(root: Path | None = None) -> dict[str, int]:
    """链上「某个码**首次**进入目录」的版本号（`INSERT INTO permissions` 里出现的码字面量）。"""
    intro: dict[str, int] = {}
    for version, _rel, sql in migration_files(root):
        code = _strip_sql_comments(sql)
        for match in re.finditer(r"INSERT INTO permissions[^;]*;", code, re.S):
            for found in re.findall(r"'([a-z_]+:[a-z_:]+)'", match.group(0)):
                intro.setdefault(found, version)
    return intro


def chain_state(manifest: dict, root: Path | None = None, upto: int | None = None) -> dict[str, object]:
    """推演迁移链：每个岗位**累计**拿到哪些码（返回结构化读数：状态 / 目录外授权 / 语句）。

    `upto` = 只看**版本号 ≤ upto** 的迁移：渲染 `V<n>` 这份产物时必须传 `n - 1`，
    否则「产物自己在链上」会让差集恒为空（自证式空断言）。
    """
    catalog = sorted(set(manifest["codes"]["registration"]))
    catalog_set = set(catalog)
    intro = catalog_introduction(root)
    grants: list[RoleGrant] = []
    for version, rel, sql in migration_files(root):
        if upto is not None and version > upto:
            continue
        grants.extend(parse_role_grants(version, rel, sql))

    def available_at(version: int) -> set[str]:
        return {c for c in catalog if intro.get(c) is None or intro[c] <= version}

    state: dict[str, set[str]] = {}
    beyond: dict[str, set[str]] = {}
    for grant in grants:
        target_roles = set(grant.roles)
        for condition in sorted(grant.when_has):
            target_roles |= {role for role, codes in state.items() if condition in codes}
        codes = available_at(grant.version) if grant.codes is None else set(grant.codes)
        for role in sorted(target_roles):
            state.setdefault(role, set()).update(codes)
            beyond.setdefault(role, set()).update(codes - catalog_set)
    return {
        "state": {role: sorted(codes & catalog_set) for role, codes in sorted(state.items())},
        "beyond_catalog": {role: sorted(codes) for role, codes in sorted(beyond.items()) if codes},
        "grants": grants,
        "catalog": catalog,
        "introduction": intro,
    }


def expand_role_codes(manifest: dict, codes: Iterable[str]) -> frozenset[str]:
    """把声明里的码集展开：`*` ⇒ 清单目录全集（与 `derive_roles` 同一口径）。"""
    materialized = set(codes)
    if "*" in materialized:
        return frozenset(manifest["codes"]["registration"])
    return frozenset(materialized)


def convergence_diff(
    manifest: dict,
    root: Path | None = None,
    upto: int | None = None,
    skip_introduced_after: int | None = None,
) -> dict[str, object]:
    """**「清单 vs 各迁移累计」的差集**（P5 的核心读数 = `声明 − 链累计`，现取、不手写）。

    `skip_introduced_after` = 把「版本号比它更晚才进入目录」的码排除出差集：
    渲染 `V136` 时必须传 `136` —— 否则它会去授**尚未存在**的码（`V138` 才引入的
    `production:execute` 会在 `V136` 里被白列一行，靠「权限目录里没有这一行 ⇒ JOIN 空集」侥幸无害）。
    """
    chain = chain_state(manifest, root, upto)
    catalog = set(chain["catalog"])
    state = {role: set(codes) for role, codes in chain["state"].items()}
    intro = chain["introduction"]
    per_role: dict[str, dict[str, list[str]]] = {}
    for role, declared in sorted(manifest["roles"]["seed"].items()):
        expected = set(expand_role_codes(manifest, declared))
        if skip_introduced_after is not None:
            expected = {
                code for code in expected
                if intro.get(code) is None or intro[code] <= skip_introduced_after
            }
        actual = state.get(role, set()) & catalog
        per_role[role] = {
            "declared": sorted(expected),
            "chain": sorted(actual),
            "missing": sorted(expected - actual),
            "extra": sorted(actual - expected),
        }
    return {
        "roles": per_role,
        "missing_total": sum(len(entry["missing"]) for entry in per_role.values()),
        "beyond_catalog": chain["beyond_catalog"],
        "grants": chain["grants"],
    }
