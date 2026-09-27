# case_ids: MC-026
"""RBAC 清单的**单一生成器**（issue #5699 的 P1 起；机制 = 设计真值源 §5.2 的 **M3**）。

P2（同一跟踪单）在本文件上**加**两段现取，不改任何既有取值：`codes.names`（目录名称列，
B3 的唯一对照面）与 `roles.login`（**A7** 登录面，由既有 `parse_role_fallback` 传 `anchor=` 复用）；
`ledger_counts` 另加 P2 的两张只许缩短台账（计数委托 `rbac/derive.py` 的**同一份**值级原语）。

P3（同一跟踪单）再加 `pages` 段（**页面 → 码**：`gate` + 第一屏读码 `units` + 逐页可见性规则），
现取全部委托 `rbac/derive.py` 的 `page_present()`（四跳：菜单节点 → 页面锚点 → `lib/api.ts` → Java
生效码，与判据 12 同一口径）；`ledger_counts` 另加 P3 的 `PAGE_VISIBILITY_GAPS`（只许缩短）。

## 它是什么，不是什么

- ✅ 它是**生成物** `rbac/readings.json` 的唯一产出点：用**仓内既有解析器**（`tests/unit_ci_workflows/`
  `test_agent_permission_parity.py` 的 `_source_map` / `build_world` / `parse_role_defaults` /
  `parse_role_fallback` / `parse_catalog` / `parse_menus` / `parse_menu_ts_nodes` / `parse_route_guard`）
  对**现值**做一次只读取数。
- ❌ 它**不是**第二套解析器（设计真值源 §1 的机具说明逐字要求「沿用同一套」）：本文件一行源码解析都
  没有 —— 它只负责「调既有解析器 + 规范化 + 落盘」。解析器的唯一家在
  `tests/unit_ci_workflows/test_agent_permission_parity.py`（该文件头部逐字记录着 #3570 的教训）。
- ❌ 它**不是**声明真值源。声明在 `rbac/manifest.json`（人可改）；本文件的产物是**读数快照**
  （机器现取）。两者的关系是「**生成物 == 现值**」（M3 新鲜度）与「**清单 == 生成物**」（零 delta 对账）。

## 用法（两条命令）

```
python3 rbac/generate_readings.py            # 重新生成 rbac/readings.json（改完清单/源码后跑）
python3 rbac/generate_readings.py --check    # 只读：现取 vs 已提交，非零退出 = 陈旧（CI 同款口径）
```

## 为什么是「生成物 + 新鲜度判据」而不是「运行时读清单」（设计真值源 §2.8）

零运行时依赖：`backend/**` 不需要知道 `rbac/` 的存在，P2/P3 才让各消费面由清单派生。本阶段（P1）
清单**只被对账读**，不被任何运行时或前端读 —— 这是「零 delta、不改行为」的结构保证。

## 边界（照实登记，**不是**「已覆盖」）

① 本生成器覆盖的**只有** §1 二十处真值源里能被既有解析器读到的那些（码目录两处 / 岗位种子的码集 /
   岗位回退的码集 / 三处菜单源 + 第四处的「已删」读数 / `menu.ts` 节点表 / 路由守卫表 /
   **P3 的页面表：`gate` + 第一屏读码 → 端点 + 逐页可见性规则（`pages` 段）**）。
   `D1` 端点注解与 `D3` 工具声明是 **co-located 真值**（设计 §2.2 有意不搬），**不在**生成物里；
② 它**不判对错**，只搬运现值。「现值对不对」是授权决定（P4/P5/P6 由人裁定）；
③ 它不读库、不连网、不 import `app.*`（必须能在只装 pytest 的 `ci workflow helper unit tests`
   job 里 import —— 引了别的依赖就会 import 失败 ⇒ 静默 skip = 没跑）；
④ `pages` 段的 `visibility_rule` 是**现值要求的**那个规则（由 `required_visibility_rule` 按现值岗位集算），
   不是「清单声明了什么」的副本 —— 清单若声明了别的规则，两边**必然不等** ⇒ 零 delta 判据判红。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PARITY_GUARD = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_agent_permission_parity.py"
READINGS_PATH = REPO_ROOT / "rbac" / "readings.json"
RBAC_DIR = REPO_ROOT / "rbac"

#: P2 的派生器（**同一份实现**给生成器与判据共用：值级原语 `codes_beyond_catalog` /
#: `role_set_divergences` / `present_ledger_counts`；本文件**不复制**它们）。
DERIVE_MODULE = "migao_rbac_derive"

#: 既有解析器的**唯一家**（本文件与守卫都从这一处加载；`sys.modules` 先注册是 `@dataclass`
#: 解析 `cls.__module__` 的前提 —— 不注册会 `AttributeError: 'NoneType' object has no attribute '__dict__'`）。
_PARITY_MODULE = "migao_rbac_parity_guard"

#: 对账用的**台账表名**（都是既有守卫里的现取表，本文件只读它们的条数）。
LEDGER_TABLES = (
    "MENU_READ_PARITY_RESIDUALS",
    "MULTI_READ_ENDPOINT_PAGES",
    "READ_WRITE_EXCEPTIONS",
    "ROLE_FALLBACK_DIVERGENCES",
    "AUTHORIZATION_CENSUS",
    "UNANNOTATED_ENDPOINTS",
    "REGISTERED_RESIDUALS",
)


def load_parity_guard():
    """按路径加载既有守卫模块（**唯一**入口；不复制它的任何实现）。"""
    if _PARITY_MODULE in sys.modules:
        return sys.modules[_PARITY_MODULE]
    assert PARITY_GUARD.is_file(), f"既有解析器所在文件不存在：{PARITY_GUARD}（路径漂移 ⇒ 红）"
    spec = importlib.util.spec_from_file_location(_PARITY_MODULE, PARITY_GUARD)
    assert spec and spec.loader, f"无法为 {PARITY_GUARD} 建立加载器（fail-closed）"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_PARITY_MODULE] = mod
    spec.loader.exec_module(mod)
    return mod


def load_derive():
    """按路径加载 **P2 派生器**（`rbac/derive.py`；同款加载纪律，避免与别的 `derive` 同名模块撞车）。"""
    if DERIVE_MODULE in sys.modules:
        return sys.modules[DERIVE_MODULE]
    path = RBAC_DIR / "derive.py"
    assert path.is_file(), f"P2 派生器不存在：{path}（路径漂移 ⇒ 红）"
    spec = importlib.util.spec_from_file_location(DERIVE_MODULE, path)
    assert spec and spec.loader, f"无法为 {path} 建立加载器（fail-closed）"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[DERIVE_MODULE] = mod
    spec.loader.exec_module(mod)
    return mod


def _sorted_role_map(table: dict[str, frozenset[str]]) -> dict[str, list[str]]:
    """角色码 → 码清单（`frozenset` 无固有顺序 ⇒ 排序后落盘，保证生成物逐字节可复现）。"""
    assert table, "岗位表解析出 0 个角色 ⇒ 生成物会空跑（fail-closed）"
    return {role: sorted(codes) for role, codes in sorted(table.items())}


def build_readings(sources: dict[str, str] | None = None, parity=None) -> dict:
    """**现取读数**（纯函数：输入源码表，输出可 JSON 化的字典；注入式红证就是喂改过的源码表）。

    键序 = 落盘顺序（`json.dumps` 不排序 ⇒ 生成物逐字节稳定，`--check` 才有意义）。

    P2 新增两段现取（设计 §4 的 P2 行）：
    - `codes.names` —— 权限目录的**名称列**（B1；与 `parse_catalog` 同一份正则的另四列投影）；
    - `roles.login` —— **A7**（`UserService.getRolePermissions`，登录面）的角色 → 码，
      由既有 `parse_role_fallback` 传 `anchor=` 读取（**复用**，不另写解析器）。

    P3 再加一段现取（设计 §4 的 P3 行）：
    - `pages` —— **页面 → 码**（21 页：`gate` 菜单可见码 + `units` 第一屏读码 → 端点
      + **现值要求的** `visibility_rule`），全部委托 `rbac/derive.py` 的 `page_present()`
      （四跳现取，与判据 12 同一口径 ⇒ 不另造第二套解析）。
    """
    p = parity if parity is not None else load_parity_guard()
    d = load_derive()
    src = sources if sources is not None else p._source_map()
    cat_rows_reg, cat_rows_perm = p.parse_catalog_rows(
        src["java:service/RegistrationService.java"],
        src["java:service/PermissionService.java"],
    )
    cat_reg = tuple(row[1] for row in cat_rows_reg)
    cat_perm = tuple(row[1] for row in cat_rows_perm)
    login = _sorted_role_map(
        p.parse_role_fallback(src["java:service/UserService.java"], anchor=p.ROLE_SWITCH_ANCHOR_USER_SERVICE)
    )
    mirror = d.mirror_present_values()
    nodes = p.parse_menu_ts_nodes(src["menu:frontend"])
    assert nodes, "`menu.ts` 解析出 0 个节点 ⇒ 生成物会空跑（fail-closed）"
    pages = d.page_present(p, src)["pages"]
    assert pages, "「页面 → 码」现值解析出 0 页 ⇒ 生成物会空跑（fail-closed）"
    return {
        "schema": 1,
        "issue": "#5699",
        "stage": "P3",
        "_note": (
            "生成物（机制 M3）：由 `rbac/generate_readings.py` 调既有解析器现取。"
            "**不得手改** —— 判据 test_generated_readings_are_fresh 会重新生成并逐字节比对。"
        ),
        "codes": {
            "registration": list(cat_reg),
            "permission_service": list(cat_perm),
            "names": {row[1]: row[0] for row in cat_rows_reg},
        },
        "roles": {
            "seed": _sorted_role_map(p.parse_role_defaults(src["java:service/RegistrationService.java"])),
            "fallback": _sorted_role_map(p.parse_role_fallback(src["java:service/RoleService.java"])),
            "login": login,
        },
        "menus": {
            label: {name: code for name, code in nodes_.items()}
            for label, nodes_ in p.parse_menus(src).items()
        },
        "menu_nodes": [
            {"key": n.key, "name": n.name, "path": n.path, "code": n.code} for n in nodes
        ],
        "route_guard": [[prefix, code] for prefix, code in p.parse_route_guard(src["route:layout.tsx"])],
        "pages": pages,
        "ledger_counts": {
            **{table: len(getattr(p, table, None)) for table in LEDGER_TABLES},
            # P2/P3 新增的只许缩短台账（**现取**口径：喂的是现值，不是清单）—— 派生器提供唯一一份实现。
            **d.present_ledger_counts(
                login,
                cat_perm,
                mirror["A3"],
                sum(1 for page in pages if page["visibility_rule"] == d.VISIBILITY_NODE_CODE),
            ),
        },
    }


def dumps(readings: dict) -> str:
    """规范化落盘形态（`ensure_ascii=False` + 2 空格缩进 + 行尾换行 ⇒ 逐字节可比）。"""
    return json.dumps(readings, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    text = dumps(build_readings())
    if "--check" in args:
        committed = READINGS_PATH.read_text(encoding="utf-8") if READINGS_PATH.is_file() else ""
        if committed == text:
            print(f"✓ 生成物新鲜：{READINGS_PATH.relative_to(REPO_ROOT)} 与现取逐字节相等")
            return 0
        print(
            f"❌ 生成物陈旧或与现值不符：{READINGS_PATH.relative_to(REPO_ROOT)}\n"
            "   出口：跑 `python3 rbac/generate_readings.py` 并提交生成物（不要手改生成物）。"
        )
        return 1
    READINGS_PATH.write_text(text, encoding="utf-8")
    print(f"✓ 已生成 {READINGS_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
