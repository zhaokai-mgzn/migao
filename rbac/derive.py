"""RBAC **P2 派生器**：由 `rbac/manifest.json` 派生「角色 → 码」与「码目录」两类事实。

跟踪单 issue #5699；设计真值源 `docs/design/rbac-single-source.md` 的 §2.4（各消费面怎么派生）
与 §4 的 **P2** 行。判据 = `tests/unit_ci_workflows/test_rbac_derived_roles_and_catalog.py`。

## 它是什么，不是什么

- ✅ 它是 **P2 派生的唯一实现**：把清单里的声明投影成**各消费面应当长成的样子**
  （A1 种子 / A2 回退 / A7 登录面 / A3·B3·B4 ai-agent 镜像 / B1·B2 目录），
  外加两条**值级**原语（「授予的码里哪些不在目录」「两个面对同一角色的码集分歧」），
  由生成器（喂**现值**）与判据（喂**派生值**）**共用同一份实现**。
- ✅ 它是**纯函数**（输入 = 清单 dict 或两张表，输出 = 可 JSON 化的普通结构）：注入式红证就是喂改过的输入。
- ❌ 它**不**落盘任何生成物。P2 的消费面（`backend/**` / `frontend/**` / ai-agent 镜像）在本阶段
  **照旧读自己的副本**（P2 不改行为）⇒ 落一个没人读的生成物只会多出一份**会陈旧的真值**
  （本仓已有 `test_dead_capability_meta_guard.py` 在治这一类）。派生在判据里**当场算**，
  ⇒ 设计 §5.2 的 **M3 新鲜度**在这里是**结构性质**：没有落盘产物，就没有「陈旧」这种状态。
- ❌ 它**不判现值对不对**（那是 P4/P5/P6 的人类裁定）；它只保证**派生结果 == 现值**（零 delta）。

## 「现值」从哪来（**一律沿用仓内既有解析器**，不另造第二套）

| 面 | 现值来源 |
|---|---|
| A1 种子 / A2 回退 / A7 登录面 | `tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `parse_role_defaults` / `parse_role_fallback`（后者传 `anchor=` 复用同一实现读 A7） |
| B1 / B2 目录（码 + 名称） | 同文件的 `parse_catalog_rows`（与 `parse_catalog` **同一份正则**，多取四列） |
| A3 / B3 / B4 ai-agent 镜像 | `ast.literal_eval` 读那三个模块级字面量（**Python 标准库**，不是第二套 Java 解析器）。为什么不能 import：该模块 `from app.tools.base import …` ⇒ 要装 ai-agent 依赖，而 `ci workflow helper unit tests` job 只装 pytest ⇒ import 失败即静默 skip（= 没跑）。 |

## 边界（**覆盖不到什么**，照实登记）

① 只覆盖**能被既有解析器读到**的形态（`case "x" -> List.of(…)` / 五列目录行 / Python 字面量）。
   同一事实若写成 `Map.of(...)`、YAML、或从 `@ConfigurationProperties` 注入 ⇒ **看不见**
   （与设计 §5.3 的 M1 边界同源）；
② **不覆盖 A4（迁移链的 `role_permissions` 授权）**：它是「存量租户一次性」的**谓词**，
   与「角色 → 默认码」不是同一个读数（设计 §3.1 已登记该差距）；本模块**不**把它算进派生目标；
③ **不覆盖 A5（`users.permissions` 快照）**：实例数据，不是声明（设计 §1.1 逐字）；
④ `*`（通配）**只在本模块里展开成目录全集**用于比较与分类；它**不改**任何消费面看到的字面量；
⑤ 本模块**不判断面之间的分歧该以哪一面为准** —— 它只**具名报出**分歧（那是授权决定）。
"""
from __future__ import annotations

import ast
import json
from collections.abc import Iterable, Mapping
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
) -> dict[str, int]:
    """P2 新增的两张**只许缩短**台账的**现取**条数（设计 §5.2 的 M2 覆盖面在 P2 的扩大）。

    - `A7_CODES_BEYOND_CATALOG`：A7 授予但不在目录里的码数（现取 4）；
    - `A7_VS_MIRROR_DIVERGENCES`：A7 与 ai-agent 镜像对**同一角色**给出不同码集的对数（现取 2）。
    """
    return {
        "A7_CODES_BEYOND_CATALOG": len(codes_beyond_catalog(login_present, catalog_present)),
        "A7_VS_MIRROR_DIVERGENCES": len(
            role_set_divergences(login_present, mirror_roles_present, "A7(login)", "A3(镜像)")
        ),
    }


def load_manifest(path: Path | None = None) -> dict:
    """读声明真值源（`rbac/manifest.json`）；缺文件 ⇒ 抛错（fail-closed，不静默当空）。"""
    target = path or (REPO_ROOT / "rbac" / "manifest.json")
    assert target.is_file(), f"声明真值源不存在：{target}（fail-closed）"
    return json.loads(target.read_text(encoding="utf-8"))
