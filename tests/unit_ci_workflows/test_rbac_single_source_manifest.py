# case_ids: MC-026
"""RBAC **单一真值源** P1：清单落地 + **只读对账**（跟踪单 issue #5699；设计真值源
`docs/design/rbac-single-source.md` 的 §4 的 P1 行与 §5.2 的 M1 / M2 / M3）。

## 这一条判据要治什么

同一事实（角色 → 码 / 码 → 元数据 / 页面 → 码 / 端点 → 码）在仓里**有 20 处副本**（设计 §1.1），
副本之间靠**注释、绊线与只许缩短的台账**维持同步 ⇒ 每次分叉都靠人发现（设计 §1.4 的六条实例）。
本文件落的是 §5.2 的四件机制里属 P1 的三件：

| 机制 | 本文件的判据 | 判红形态 |
|---|---|---|
| **M1 副本登记表（未登记即红）** | `test_every_copy_face_hit_is_registered` + `…reverse_is_stale` | 「有人手抄了第 N 份」⇒具名红；登记了却已不命中 ⇒ 陈旧红 |
| **M2 台账只许缩短** | `test_ledger_counts_only_shrink` | 任一现取台账条数 > 上限（= 今天的现取数）⇒红；清单里的条数与现取不符 ⇒红 |
| **M3 单一生成器 + 生成物新鲜度** | `test_generated_readings_are_fresh` | 手改生成物 / 改源码没重生成 ⇒红 |
| （P1 的主判据）**零 delta 只读对账** | `test_manifest_matches_generated_readings` | 清单任一项与现值不等 ⇒ **具名报出完整不一致清单**（不是「数量相等」） |

## 🔴 零 delta 是本阶段**唯一**的验收口径（违反即返工）

P1 的定义 = **清单落地 + 只读对账**（设计 §4）⇒ 生成物必须与现值**逐值相等**。若实测出 delta，
**只报告、不修**（那是 P4/P5 的活，且必须由人在知悉差量后点头）⇒ 因此本文件的对账判据在
「不等」时输出的是**完整的不一致清单**（每个字段一行：清单值 vs 现值），**不是**一个布尔量。

## 三个机制的覆盖面（**覆盖不到什么**，与设计 §5.3 逐条对齐）

- **M1 只覆盖「用了约定形态」的副本**：角色矩阵若写成 `Map.of(...)`、YAML、或从
  `@ConfigurationProperties` 注入 ⇒ 扫描器**看不见**（假绿方向）。
- **M1 不覆盖「同一事实写在副本的注释里」**（散文）：没有任何扫描器能判「读者理解对了没有」。
- **M2 的「只许缩短」不保证条目正确**，只保证它不增长：把一条真违反写成「有意」并登记，
  与把它修好，在 M2 眼里一样（补偿靠每条目的 reason/owner，那是人类可读性，不是机械判据）。
- **M3 不覆盖「清单本身就写错了」**：生成物 == 现值只保证**零 delta**，不保证现值**对**。
- **M1/M2/M3 都不覆盖 `users.permissions` 快照**（实例数据，不是声明）。

## 红证的机具纪律（本仓已固化，实测代价换来的）

判据一律是**纯函数**（输入 = 清单 / 读数 / 源码文本 / 命中集，输出 = 问题清单），注入式红证
**当场在内存里构造坏形态**并把变异体**直接作为判据入参** —— 不靠「改磁盘文件再跑」。
（实测教训：改磁盘的变异**可能不被读到** ⇒ 那种红证在 CI 上可能**永远绿 = 空断言**。）
另每条红证配**对照读数**：「只改注释 / 不改真东西」必须**不红**。
"""
from __future__ import annotations

import copy
import functools
import importlib.util
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RBAC_DIR = REPO_ROOT / "rbac"
MANIFEST_PATH = RBAC_DIR / "manifest.json"
READINGS_PATH = RBAC_DIR / "readings.json"
SOURCES_PATH = RBAC_DIR / "sources.json"
GENERATOR_PATH = RBAC_DIR / "generate_readings.py"

UNIT_CI_DIR = REPO_ROOT / "tests" / "unit_ci_workflows"
if str(UNIT_CI_DIR) not in sys.path:  # 共享解析实现（`_source_parsing` / `_sql_schema`）的唯一家
    sys.path.insert(0, str(UNIT_CI_DIR))

import _source_parsing as SP  # noqa: E402  （判据面唯一一份「引号感知」的词法走查）
from _sql_schema import strip_sql_comments  # noqa: E402  （判据面唯一一份 SQL 剥注释）

#: 清单里**被对账覆盖**的段（结构化冻结：新增一个手写段 ⇒ 必须先在本判据的 diff 里显式登记）。
#: 下划线开头的是**元字段 / 散文**（`_note` / `_boundary`），有意不进对账 —— 它们不是声明。
RECONCILED_SEGMENTS = (
    "schema",
    "issue",
    "stage",
    "codes",
    "roles",
    "menus",
    "menu_nodes",
    "route_guard",
    "ledger_counts",
)

#: 台账「只许缩短」的**上限**（= 落地时的现取条数；要放宽必须改本判据，diff 里看得见）。
#: P2（issue #5699）新增两张，**上限已于 2026-09-27 随人类裁定「退役 A7 的目录外码」降到 0**：
#: `A7_CODES_BEYOND_CATALOG`（A7 授予但不在目录里的码）与 `A7_VS_MIRROR_DIVERGENCES`
#: （A7 与 ai-agent 镜像对同一角色给出不同码集的对数）—— 这两条是 §5.3 里「M2 的覆盖面在 P2 扩大」的落点：
#: 退役前现取分别是 **4 / 2**，退役后 **0 / 0**。🔴 **上限只许缩短** ⇒ 现在**任何**「给 A7 重新加一个
#: 目录外的码」或「让两面再次不一致」都会立刻判红（涨回 1 就超上限）—— 这正是「退役不等于放任复活」。
LEDGER_CEILINGS = {
    "MENU_READ_PARITY_RESIDUALS": 6,
    "MULTI_READ_ENDPOINT_PAGES": 3,
    "READ_WRITE_EXCEPTIONS": 0,
    "ROLE_FALLBACK_DIVERGENCES": 0,
    "AUTHORIZATION_CENSUS": 15,
    "UNANNOTATED_ENDPOINTS": 21,
    "REGISTERED_RESIDUALS": 9,
    "A7_CODES_BEYOND_CATALOG": 0,
    "A7_VS_MIRROR_DIVERGENCES": 0,
}

#: M1 的**形态面**（副本长什么样）：每条 = 一个「事实被写下来」的形态 + 扫描它的语料。
#: ⚠️ 形态一律锚**声明形态**（`X =` / 方法签名 / `INSERT INTO`），不锚消费点（读 `node.permissionCode`
#: 的人不是副本）；文本一律**先剥注释**再匹配（注释里提一句不算副本 —— 否则判据被自己的文案喂红）。
COPY_FACES = (
    {
        "id": "role-defaults-seed",
        "shape": r"attachDefaultPermissions\s*\(",
        "trace": 'attachDefaultPermissions',
        "roots": ("backend/admin-api/src/main/java",),
        "glob": "*.java",
        "kind": "declaration",
    },
    {
        "id": "role-defaults-fallback",
        "shape": r"case\s+\"[a-z_]+\"\s*->\s*List\.of\(",
        "trace": 'case "',
        "roots": ("backend/admin-api/src/main/java",),
        "glob": "*.java",
        "kind": "declaration",
    },
    {
        "id": "catalog-registration",
        "shape": r"defaultPermissions\s*=",
        "trace": 'defaultPermissions',
        "roots": ("backend/admin-api/src/main/java",),
        "glob": "*.java",
        "kind": "declaration",
    },
    {
        "id": "catalog-lazy-seed",
        "shape": r"int\s+ensureFullPermissionCatalog\s*\(",
        "trace": 'ensureFullPermissionCatalog',
        "roots": ("backend/admin-api/src/main/java",),
        "glob": "*.java",
        "kind": "declaration",
    },
    {
        "id": "menu-tree",
        "shape": r"MENU_TREE\s*=",
        "trace": 'MENU_TREE',
        "roots": ("backend/admin-api/src/main/java",),
        "glob": "*.java",
        "kind": "declaration",
    },
    {
        "id": "menu-auth-build",
        "shape": r"private\s+List<UserInfoResponse\.MenuItem>\s+buildMenusByPermissions\s*\(",
        "trace": 'buildMenusByPermissions',
        "roots": ("backend/admin-api/src/main/java",),
        "glob": "*.java",
        "kind": "declaration",
    },
    {
        "id": "menu-frontend-nodes",
        "shape": r"permissionCode:\s*'",
        "trace": 'permissionCode',
        "roots": ("frontend/admin-web/src",),
        "glob": "*.ts",
        "kind": "declaration",
    },
    {
        "id": "route-guard-map",
        "shape": r"ROUTE_PERMISSION_MAP\s*[:=]",
        "trace": 'ROUTE_PERMISSION_MAP',
        "roots": ("frontend/admin-web/src",),
        "glob": "*.tsx",
        "kind": "declaration",
    },
    {
        "id": "sql-role-grants",
        "shape": r"INSERT\s+INTO\s+role_permissions",
        "trace": 'role_permissions',
        "roots": ("backend/admin-api/src/main/resources/db",),
        "glob": "*.sql",
        "kind": "declaration",
    },
    {
        "id": "sql-permission-rows",
        "shape": r"INSERT\s+INTO\s+permissions",
        "trace": 'INSERT',
        "roots": ("backend/admin-api/src/main/resources/db",),
        "glob": "*.sql",
        "kind": "declaration",
    },
    {
        "id": "py-role-mirror",
        "shape": r"^ROLE_PERMISSIONS\s*[:=]",
        "trace": 'ROLE_PERMISSIONS',
        "roots": ("backend/ai-agent-service",),
        "glob": "*.py",
        "kind": "mirror",
    },
    {
        "id": "py-catalog-mirror",
        "shape": r"^PERMISSION_CATALOG\s*[:=]",
        "trace": 'PERMISSION_CATALOG',
        "roots": ("backend/ai-agent-service",),
        "glob": "*.py",
        "kind": "mirror",
    },
    {
        "id": "py-permission-labels",
        "shape": r"^PERMISSION_LABELS\s*[:=]",
        "trace": 'PERMISSION_LABELS',
        "roots": ("backend/ai-agent-service",),
        "glob": "*.py",
        "kind": "mirror",
    },
    {
        "id": "bmini-surface-mirror",
        "shape": r"^export const ADMIN_SURFACES\s*[:=]",
        "trace": 'ADMIN_SURFACES',
        "roots": ("frontend/bmini-app/src",),
        "glob": "*.ts",
        "kind": "mirror",
    },
    {
        "id": "census-ledger",
        "shape": r"^AUTHORIZATION_CENSUS\s*[:=]",
        "trace": 'AUTHORIZATION_CENSUS',
        "roots": ("tests/unit_ci_workflows",),
        "glob": "*.py",
        "kind": "ledger",
    },
    {
        "id": "role-fallback-ledger",
        "shape": r"^ROLE_FALLBACK_DIVERGENCES\s*[:=]",
        "trace": 'ROLE_FALLBACK_DIVERGENCES',
        "roots": ("tests/unit_ci_workflows",),
        "glob": "*.py",
        "kind": "ledger",
    },
    {
        # P2 扩面（issue #5699）：**A7 的四个目录外码的落点**。这四个码在权限目录里各 0 命中
        # ⇒ 它们不是「权限码」，任何出现处都意味着授权面/身份面被改动 ⇒ 必须具名登记（未登记即红）。
        # 形态 = 这四个码的**字面量**，不是「某个声明形态」—— 这是 §5.3 里 M1 那句「只覆盖用了约定
        # 形态的副本」的**有意例外**：要抓的是**消费/再引入**而不是**声明**，故按码字面量扫。
        # 🔴 2026-09-27（人类裁定「退役」）：`UserService` 的授予已删、测试夹具已同步 ⇒ 现取只剩
        # 一处**与 A7 无关**的同名码字面量；本形态面从此是**再引入绊线**（谁把这四个码写回任何
        # 判定面/测试面文件，未登记即红）。
        "id": "a7-login-codes-consumer",
        "shape": r'"(?:chat:read|chat:write|customer:read|order:read)"',
        "trace": ':read',
        "roots": ("backend/admin-api/src/main", "backend/admin-api/src/test"),
        "glob": "*.java",
        "kind": "consumer",
    },
)

#: M1 的**射程声明**（结构化；与 `scanned_files()` 的实际枚举集互相钉住 —— 见
#: `test_copy_face_scope_equals_actual_scan`）。收窄射程或扩大剪枝都得先改这里，diff 里看得见。
#: 🔴 P2 扩面（issue #5699）：加 `backend/admin-api/src/test` —— 设计 §1.3 的 A 类副本清单里
#: 明写了「各岗位的 `RoleServiceTest` / `test_tool_permission_codes` 逐码点名断言」，
#: 而 P1 的射程只到 `src/main` ⇒ 那些手抄件**在当时根本不在射程内**（假绿方向）。
COPY_FACE_SCOPE = {
    "roots": (
        "backend/admin-api/src/main",
        "backend/admin-api/src/test",
        "backend/ai-agent-service",
        "frontend/admin-web/src",
        "frontend/bmini-app/src",
        "tests/unit_ci_workflows",
    ),
    "globs": ("*.java", "*.ts", "*.tsx", "*.sql", "*.py"),
    "exclude_dirs": (
        ".git", "node_modules", ".venv", "venv", "site-packages", ".next", "dist", "build",
        "coverage", "__pycache__",
    ),
}

#: 射程的**冻结下界**（**不取自** `COPY_FACE_SCOPE`）：这些文件是「事实载体」——收窄射程若把它们
#: 排除在外，`test_copy_face_scope_equals_actual_scan` 必红。这正是 #5284 的形态：**代码与台账
#: 一起收窄**时，「声明 == 实测」两边同时变小 ⇒ 自查不出来，只有一份**冻结的**语料成员能报出。
FROZEN_CORPUS_MEMBERS = (
    "backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java",
    "backend/admin-api/src/main/java/com/migao/admin/service/RoleService.java",
    "backend/admin-api/src/main/java/com/migao/admin/service/PermissionService.java",
    "backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java",
    "backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java",
    "backend/admin-api/src/main/java/com/migao/admin/service/UserService.java",
    "backend/ai-agent-service/app/graph/skills/base_skill.py",
    "backend/ai-agent-service/tests/test_tool_permission_codes.py",
    "frontend/admin-web/src/config/menu.ts",
    "frontend/admin-web/src/app/(dashboard)/layout.tsx",
    "frontend/bmini-app/src/utils/adminPermission.ts",
    "tests/unit_ci_workflows/test_agent_permission_parity.py",
)

#: M1 的**未覆盖面台账**（只许缩短）：形态面扫不到的面，照实登记而不是假装覆盖（设计 §5.3）。
UNCOVERED_FACES: tuple[dict[str, str], ...] = (
    {
        "face": "backend/** 的角色矩阵若写成 Map.of(...) / @ConfigurationProperties / YAML",
        "reason": "M1 的形态集只认约定形态（List.of / switch case / 数组字面量 / INSERT）；非约定形态看不见",
        "owner": "RBAC 跟踪单 #5699 的 P2 阶段（派生落地后副本形态收敛，届时收紧）",
        "issue": "#5699",
    },
    {
        "face": "副本注释里的散文（「与 X 逐值同步」这类句子）",
        "reason": "没有任何扫描器能判「读者理解对了没有」；这一类只能靠把事实从散文搬进结构",
        "owner": "RBAC 跟踪单 #5699 的 P1（清单已把事实搬进结构：rbac/manifest.json）",
        "issue": "#5699",
    },
    {
        "face": "frontend/worker-h5/**",
        "reason": "裁定 13（不重写工人端）；工人端不走 /api/admin/** ⇒ 不在本设计的四类事实内（设计 §2.9）",
        "owner": "裁定 13",
        "issue": "#5699",
    },
)
UNCOVERED_FACE_CAP = 3

#: 登记表里 `derived_from == "UNRESOLVED"` 的副本上限（**只许缩短**）：这些是**设计真值源尚未登记**
#: 的副本（只登记 + 报告，不修行为）⇒ 条数是一个「燃尽靶子」，涨了必须显式改这里。
#: 现取 = **0**：唯一一条（`UserService.getRolePermissions`，设计 §1.1 已补登为 **A7**）已于 2026-09-27
#: 归类（主体 → P2；码的存废 → 人类裁定项）⇒ 按「只许缩短」销账。
UNRESOLVED_COPY_CAP = 0


# ══════════════════════════════════════════════════════════════════════════════
# 一、读盘（清单 / 生成物 / 登记表）—— 缺文件一律 fail-closed，不静默当空
# ══════════════════════════════════════════════════════════════════════════════


def load_json(path: Path) -> dict:
    """读一个 JSON 产物；缺文件 / 非对象 ⇒ 红（**不是**静默跳过：缺清单 = 无人管，不是「无需对账」）。"""
    assert path.is_file(), (
        f"{path.relative_to(REPO_ROOT).as_posix()} 不存在 ⇒ 本判据 fail-closed（缺产物不是「通过」）"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data, f"{path.name} 必须是**非空对象**（空 ⇒ 判据在空集上恒真）"
    return data


def load_generator():
    """按路径加载**单一生成器**（`rbac/generate_readings.py`）—— 生成物由它产出，判据复用它。"""
    name = "migao_rbac_readings_generator"
    if name in sys.modules:
        return sys.modules[name]
    assert GENERATOR_PATH.is_file(), f"单一生成器不存在：{GENERATOR_PATH}（M3 的前提）"
    spec = importlib.util.spec_from_file_location(name, GENERATOR_PATH)
    assert spec and spec.loader, f"无法为 {GENERATOR_PATH} 建立加载器（fail-closed）"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据本体（纯函数：输入注入，输出问题清单 —— 空 = 绿）
# ══════════════════════════════════════════════════════════════════════════════


def _walk(value: object, prefix: str = "") -> list[tuple[str, object]]:
    """把嵌套结构摊平成 `(路径, 值)` 清单（**逐项点名**的对账口径：不用「数量相等」充数）。"""
    if isinstance(value, dict):
        out: list[tuple[str, object]] = []
        for key in sorted(value):
            out.extend(_walk(value[key], f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list):
        out = []
        for i, item in enumerate(value):
            out.extend(_walk(item, f"{prefix}[{i}]"))
        return out
    return [(prefix, value)]


def reconcile(manifest: dict, readings: dict) -> list[str]:
    """**零 delta 只读对账**：清单（声明）与生成物（现值）**逐值**比对 ⇒ 完整不一致清单。

    每个不一致项一行，逐项点名到叶（例：`roles.seed.operator: 清单=['a'] / 现值=['a','b']`），
    ⇒ 「不一致即报告，不修」（设计 §4 P1 的验收口径）。

    🔴 **下划线开头的键不进对账**（`_note` / `_boundary` 是元字段与散文）—— 否则「改一句说明」
    会被判成「改了一项事实」，而那正好是设计 §1.4 五条实例里的读错对象形态。
    """
    out: list[str] = []
    want = dict(_walk({k: v for k, v in manifest.items() if not k.startswith("_")}))
    got = dict(_walk({k: v for k, v in readings.items() if not k.startswith("_")}))
    for key in sorted(set(want) | set(got)):
        if key not in want:
            out.append(f"[现值多出] {key} = {got[key]!r}（清单里没有这一项 ⇒ 现值有、声明无）")
        elif key not in got:
            out.append(f"[清单多出] {key} = {want[key]!r}（生成物里没有这一项 ⇒ 声明有、现值无）")
        elif want[key] != got[key]:
            out.append(f"[值不等] {key}: 清单={want[key]!r} / 现值={got[key]!r}")
    return out


def freshness_problems(committed: str, regenerated: str) -> list[str]:
    """**M3 生成物新鲜度**：已提交的生成物 vs 当场重新生成 ⇒ 不等即「陈旧/手改」。"""
    if committed == regenerated:
        return []
    committed_lines = committed.splitlines()
    regenerated_lines = regenerated.splitlines()
    first = next(
        (
            i
            for i in range(max(len(committed_lines), len(regenerated_lines)))
            if committed_lines[i : i + 1] != regenerated_lines[i : i + 1]
        ),
        0,
    )
    return [
        "生成物与现取不符（手改了生成物，或改了源码/清单后没重生成）",
        f"  首个差异在第 {first + 1} 行：",
        f"    已提交：{committed_lines[first] if first < len(committed_lines) else '<文件结束>'}",
        f"    现  取：{regenerated_lines[first] if first < len(regenerated_lines) else '<文件结束>'}",
        "  出口（真可行动）：跑 `python3 rbac/generate_readings.py` 并提交生成物；**不要手改生成物**。",
    ]


def unreconciled_segments(manifest: dict, readings: dict) -> list[str]:
    """清单里**没被对账覆盖**的段 ⇒ 红（防止清单长出「手写但无人核」的新段 = 新的并行真值）。"""
    def segments(doc: dict) -> set[str]:
        return {k for k in doc if not k.startswith("_")}

    out: list[str] = []
    frozen = set(RECONCILED_SEGMENTS)
    for label, doc in (("清单", manifest), ("生成物", readings)):
        extra = sorted(segments(doc) - frozen)
        if extra:
            out.append(
                f"{label}里出现了**未被对账覆盖**的段 {extra} ⇒ 那是新的并行真值："
                "要么让生成器也产出它（进 RECONCILED_SEGMENTS），要么删掉"
            )
    missing = sorted(frozen - segments(manifest))
    if missing:
        out.append(f"清单缺段 {missing}（RECONCILED_SEGMENTS 里登记的段必须都真的存在）")
    return out


@lru_cache(maxsize=1)
def repo_copy_face_hits() -> tuple[dict, ...]:
    """仓库**当前语料**上的形态面命中（缓存：多条判据共用同一次扫描）。"""
    return tuple(copy_face_hits(read_corpus()))


def unregistered_copies(hits: list[dict], registry: dict) -> list[str]:
    """**M1 未登记即红**：形态面命中却不在 `rbac/sources.json` 里 ⇒ 具名红。"""
    registered = {(e["face"], e["file"]) for e in registry["sources"]}
    return [
        f"副本未登记：{h['face']} @ {h['file']}（命中 {h['count']} 处）"
        " —— 出口：① 在 `rbac/sources.json` 登记（写清 kind / derived_from / note）；"
        "② 或改用派生（P2/P3 的生成器）"
        for h in hits
        if (h["face"], h["file"]) not in registered
    ]


def copy_hit_count_drift(hits: list[dict], registry: dict) -> list[str]:
    """**M1 的 P2 硬化**：登记的 `hits` 必须 == 现取（否则那个数字会变成**没人核的散文**）。

    P1 只判「这处副本还在不在」；`hits` 字段当时**没有任何判据读它** —— 而它恰恰是最容易腐烂的一格
    （2026-09-27 退役 A7 的两个 `case` 时，`UserService` 的 `role-defaults-fallback` 命中数由 4 变 2，
    旧口径**一声不响**）。⇒ 现口径：涨或跌都报出，并在同 PR 更新登记表（diff 里看得见）。
    """
    current = {(h["face"], h["file"]): h["count"] for h in hits}
    return [
        f"登记命中数漂移：{e['face']} @ {e['file']} 登记 {e['hits']} 处 / 现取 {current[(e['face'], e['file'])]} 处"
        "（涨跌都要在同 PR 更新 `rbac/sources.json`）"
        for e in registry["sources"]
        if (e["face"], e["file"]) in current and current[(e["face"], e["file"])] != e["hits"]
    ]


def stale_registrations(hits: list[dict], registry: dict) -> list[str]:
    """**M1 反向**：登记了却已不命中 ⇒ 陈旧条目 ⇒ 红（台账只许缩短）。"""
    present = {(h["face"], h["file"]) for h in hits}
    return [
        f"陈旧登记：{e['face']} @ {e['file']}（形态面已不命中 ⇒ 销账）"
        for e in registry["sources"]
        if (e["face"], e["file"]) not in present
    ]


def ledger_count_drift(manifest: dict, counts: dict) -> list[str]:
    """清单里登记的台账条数必须 == 现取（涨跌都要在同 PR 更新 ⇒ diff 里看得见）。"""
    return [
        f"清单 ledger_counts.{name} = {manifest['ledger_counts'].get(name)!r} 与现取 {value} 不符"
        for name, value in sorted(counts.items())
        if manifest["ledger_counts"].get(name) != value
    ]


def ledger_growth_problems(counts: dict, ceilings: dict) -> list[str]:
    """**M2 台账只许缩短**：现取条数 > 上限 ⇒ 红（上限是落地时的现取数，放宽要改判据）。"""
    out: list[str] = []
    for name in sorted(set(counts) | set(ceilings)):
        if name not in counts:
            out.append(f"台账 {name} 不在现取里（清单里的条目已陈旧 ⇒ 销账）")
            continue
        if name not in ceilings:
            out.append(f"台账 {name} 没有上限登记 ⇒ 它的增长无人管（补 LEDGER_CEILINGS）")
            continue
        if counts[name] > ceilings[name]:
            out.append(
                f"台账 {name} 现取 {counts[name]} 条 > 上限 {ceilings[name]} 条"
                "（只许缩短；要放宽必须显式改本判据的 LEDGER_CEILINGS，diff 里看得见）"
            )
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 三、M1 的扫描器（纯函数：输入 {相对路径: 文本} ⇒ 命中清单）
# ══════════════════════════════════════════════════════════════════════════════


def strip_for(suffix: str, text: str) -> str:
    """按扩展名**剥注释**（判据面唯一一份实现：Java/TS 走 `_source_parsing.java_code`，
    Python 走 `code_without_comments`，SQL 走 `_sql_schema.strip_sql_comments`）。"""
    if suffix in (".java", ".ts", ".tsx"):
        return SP.java_code(text)
    if suffix == ".py":
        return SP.code_without_comments(text, "<copy-face-scan>")
    if suffix == ".sql":
        return strip_sql_comments(text)
    raise AssertionError(f"未登记的扩展名 {suffix!r} ⇒ M1 的剥注释口径不明 ⇒ 红（fail-closed）")


def copy_face_hits(files: dict[str, str], faces=COPY_FACES) -> list[dict]:
    """形态面命中（**纯函数**）：`{文件相对路径: 源码文本}` ⇒ `[{face, file, count}, …]`。

    先剥注释再匹配 ⇒「只在注释里提一句」**不命中**（对照读数见 `test_copy_face_comment_only_is_not_a_hit`）。
    """
    out: list[dict] = []
    for face in faces:
        rx = re.compile(face["shape"], re.M)
        for rel in sorted(files):
            if Path(rel).suffix not in {f".{g.lstrip('*.')}" for g in (face["glob"],)}:
                continue
            raw = files[rel]
            if face["trace"] not in raw:  # 性能预筛（不是判定）：剥注释只删文本 ⇒ 命中必留痕
                continue
            body = strip_for(Path(rel).suffix, raw)
            found = rx.findall(body)
            if found:
                out.append({"face": face["id"], "file": rel, "count": len(found)})
    return out


def scanned_files(scope: dict = COPY_FACE_SCOPE, root: Path | None = None) -> set[str]:
    """M1 **实际**枚举的语料集（与 `COPY_FACES` 的 roots×glob 取并；`Path.rglob` 实现）。"""
    base = root or REPO_ROOT
    exclude = set(scope["exclude_dirs"])
    out: set[str] = set()
    globs = set(scope["globs"])
    for face in COPY_FACES:
        globs.add(face["glob"])
    for r in scope["roots"]:
        for pattern in sorted(globs):
            for p in (base / r).rglob(pattern):
                if exclude & set(p.parts):
                    continue
                if p.is_file():
                    out.add(p.resolve().relative_to(base.resolve()).as_posix())
    return out


def walk_scope(scope: dict, root: Path | None = None) -> set[str]:
    """按**声明**独立走一遍语料（`os.walk` 剪枝，剪枝发生在下降之前）—— 与被测实现互为镜像。"""
    base = root or REPO_ROOT
    exclude = set(scope["exclude_dirs"])
    out: set[str] = set()
    for r in scope["roots"]:
        for dirpath, dirnames, filenames in os.walk(base / r):
            dirnames[:] = sorted(d for d in dirnames if d not in exclude)
            for name in sorted(filenames):
                if Path(name).suffix in {f".{g.lstrip('*.')}" for g in scope["globs"]}:
                    out.add((Path(dirpath) / name).resolve().relative_to(base.resolve()).as_posix())
    return out


@lru_cache(maxsize=1)
def read_corpus() -> dict[str, str]:
    """读入 M1 的全语料（文本，不剥注释 —— 剥注释是 `copy_face_hits` 的事，保持单一实现）。

    `lru_cache`：语料 ~2000 文件，本文件有 4 条判据要用它 —— 不缓存会把该 job 的成本推到分钟级
    （实测：未缓存时本文件 53s；`ci workflow helper unit tests` 的预算是 8 分钟，见 issue #5151 的教训）。
    """
    files: dict[str, str] = {}
    for rel in sorted(scanned_files(COPY_FACE_SCOPE)):
        try:
            files[rel] = (REPO_ROOT / rel).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:  # pragma: no cover - 语料里不该有二进制
            raise AssertionError(f"{rel} 不是 UTF-8 文本（M1 语料必须可读）") from exc
    return files


# ══════════════════════════════════════════════════════════════════════════════
# 四、判据（每条配注入式红证 + 对照读数）
# ══════════════════════════════════════════════════════════════════════════════


def test_manifest_matches_generated_readings():
    """**P1 主判据（零 delta）**：清单（声明）与生成物（现值）**逐值相等**，逐项点名。

    红证（注入式，见 `test_reconcile_names_each_mismatch`）：删掉清单里角色的一个码 ⇒
    输出必须**具名**那一项。不等时本判据输出**完整不一致清单**（那是「发现 delta」的正常交付，
    **不改**、只报告 —— 设计 §4 的 P1 口径）。
    """
    manifest, readings = load_json(MANIFEST_PATH), load_json(READINGS_PATH)
    print("── 零 delta 逐项点名（清单 == 生成物 == 现值）──")
    counted = 0
    for name in RECONCILED_SEGMENTS:
        print(f"  [{name}]")
        for key, value in _walk(manifest[name], name):
            counted += 1
            leaf = value if not isinstance(value, list) else f"{len(value)} 项 {value[:4]}{'…' if len(value) > 4 else ''}"
            print(f"    {key} = {leaf}")
    print(
        f"── 逐值比对项数 = {counted}（**口径**：六个对账段摊平到叶的 `(路径, 值)` 对总数 —— "
        "列表按元素下标逐个展开，如 codes 每码一项、menu_nodes 每节点四项、route_guard 每前缀两项；"
        "两条读数必须互为镜像）；不一致 = 0 ──"
    )
    problems = reconcile(manifest, readings)
    assert problems == [], (
        f"清单与现值**不一致**（共 {len(problems)} 项）—— 🔴 本阶段只报告、不修（P4/P5 的活）：\n"
        + "\n".join(f"  · {p}" for p in problems)
    )


def test_manifest_segments_are_all_reconciled():
    """清单不得长出「手写但无人核」的段（= 新的并行真值）：段集必须 == 冻结的 `RECONCILED_SEGMENTS`。

    红证：往清单加一个段（生成物里没有）⇒ 必红（见 `test_unreconciled_segment_is_red`）。
    """
    manifest, readings = load_json(MANIFEST_PATH), load_json(READINGS_PATH)
    problems = unreconciled_segments(manifest, readings)
    assert problems == [], "清单/生成物的段集不合规：\n" + "\n".join(f"  · {p}" for p in problems)


def test_generated_readings_are_fresh():
    """**M3**：`rbac/readings.json` 必须等于「当场重新生成」的结果（手改生成物 / 没重生成 ⇒ 红）。"""
    gen = load_generator()
    committed = READINGS_PATH.read_text(encoding="utf-8")
    regenerated = gen.dumps(gen.build_readings())
    problems = freshness_problems(committed, regenerated)
    assert problems == [], "\n".join(problems)


def test_ledger_counts_only_shrink():
    """**M2**：既有台账的现取条数 ≤ 上限，且清单里的条数 == 现取（涨跌都要在同 PR 更新）。"""
    manifest = load_json(MANIFEST_PATH)
    gen = load_generator()
    counts = gen.build_readings()["ledger_counts"]
    problems = ledger_growth_problems(counts, LEDGER_CEILINGS) + ledger_count_drift(manifest, counts)
    print(f"现取台账条数：{counts}")
    assert problems == [], "台账不合规：\n" + "\n".join(f"  · {p}" for p in problems)


def test_every_copy_face_hit_is_registered():
    """**M1 未登记即红**：形态面命中 ⟺ `rbac/sources.json` 条目（两个方向都判）。

    红证：造一个命中形态却未登记的命中项 ⇒ 具名红；反向：登记了却已不命中 ⇒ 陈旧红
    （见 `test_registry_detects_unregistered_and_stale`）。
    """
    hits = list(repo_copy_face_hits())
    registry = load_json(SOURCES_PATH)
    print(f"M1 形态面命中 {len(hits)} 处；登记 {len(registry['sources'])} 条")
    for h in hits:
        print(f"  {h['face']:26s} {h['file']}")
    problems = (
        unregistered_copies(hits, registry)
        + stale_registrations(hits, registry)
        + copy_hit_count_drift(hits, registry)
    )
    problems += [
        f"登记条目缺 {key!r}（必须写清每处副本的来源与去向）：{e.get('file')}"
        for e in registry["sources"]
        for key in ("face", "file", "kind", "derived_from", "note")
        if not e.get(key)
    ]
    unresolved = [e for e in registry["sources"] if e["derived_from"] == "UNRESOLVED"]
    print(f"未裁决副本（UNRESOLVED）= {len(unresolved)} 条 / 上限 {UNRESOLVED_COPY_CAP}")
    if len(unresolved) > UNRESOLVED_COPY_CAP:
        problems.append(
            f"未裁决副本 {len(unresolved)} 条 > 上限 {UNRESOLVED_COPY_CAP} 条（只许缩短）："
            f"{[e['file'] for e in unresolved]}"
        )
    assert problems == [], "副本登记表不合规：\n" + "\n".join(f"  · {p}" for p in problems)


def test_copy_face_scope_equals_actual_scan():
    """**M1 的射程元判据**（设计 §5.4 的范式）：声明（`COPY_FACE_SCOPE`）== 判据**实际**枚举的语料集，
    且**冻结的事实载体**必须仍在射程内。

    红证（两条，各自单独变红）：① 只改声明（或只改实现）⇒ 必红（两边不等）；
    ② **两边一起收窄** ⇒ 由 `FROZEN_CORPUS_MEMBERS` 报出（#5284 的形态：一起变窄时
    「声明 == 实测」自查不出来）。见 `test_narrowed_copy_face_scope_is_caught`。
    """
    actual = scanned_files()
    declared = walk_scope(COPY_FACE_SCOPE)
    assert actual, "M1 语料枚举为空 ⇒ 判据在空集上恒真（fail-closed）"
    dropped = sorted(set(FROZEN_CORPUS_MEMBERS) - actual)
    assert dropped == [], (
        f"冻结的「事实载体」已不在 M1 射程内（射程被收窄 ⇒ 那些副本从此无人看）：{dropped}\n"
        "  出口：把它们所在的目录放回 `COPY_FACE_SCOPE.roots`（收窄射程 = 放弃覆盖，必须显式改本判据）"
    )
    assert actual == declared, (
        "M1 声称的射程 != 实际扫描集：\n"
        f"  声称有而实际没扫 = {sorted(declared - actual)[:6]}\n"
        f"  实际扫了而没声称 = {sorted(actual - declared)[:6]}\n"
        f"（声称 {len(declared)} 个 / 实际 {len(actual)} 个）"
    )


def test_copy_face_uncovered_ledger_only_shrinks_and_stays_live():
    """**M1 的未覆盖面台账**（设计 §5.3）：条数 ≤ 上限，每条须有 face/reason/owner/issue。"""
    problems: list[str] = []
    if len(UNCOVERED_FACES) > UNCOVERED_FACE_CAP:
        problems.append(
            f"未覆盖面 {len(UNCOVERED_FACES)} 条 > 上限 {UNCOVERED_FACE_CAP} 条（只许缩短）"
        )
    for face in UNCOVERED_FACES:
        for key in ("face", "reason", "owner", "issue"):
            if not face.get(key):
                problems.append(f"未覆盖面条目缺 {key!r}（必须写清「谁看」）：{face}")
    assert problems == [], "未覆盖面台账不合规：\n" + "\n".join(f"  · {p}" for p in problems)


# ══════════════════════════════════════════════════════════════════════════════
# 五、注入式红证（**当场在内存里构造坏形态**，变异体直接作为判据入参）
# ══════════════════════════════════════════════════════════════════════════════


def test_reconcile_names_each_mismatch():
    """主判据的红证：三类坏形态各**单独**变红，且报出的是**具名**项（不是「数量不等」）。

    ① 删掉清单里 `roles.seed.operator` 的一个码（值不等）；
    ② 清单里加一个现值没有的角色（清单多出）；
    ③ 生成物里加一项（现值多出）。
    对照组（**应当不红**）：只改清单的 `_note` 散文（元字段不进对账）。
    """
    manifest, readings = load_json(MANIFEST_PATH), load_json(READINGS_PATH)
    assert reconcile(manifest, readings) == [], "落地态必须零不一致（否则本红证的前提不成立）"
    baseline_codes = manifest["roles"]["seed"]["operator"]
    assert len(baseline_codes) > 1, "对照组前提：operator 的码不止一个（否则删一个不成形态）"

    m1 = copy.deepcopy(manifest)
    m1["roles"]["seed"]["operator"] = baseline_codes[:-1]
    p1 = reconcile(m1, readings)
    assert any("roles.seed.operator" in x for x in p1), f"删码没被具名报出：{p1}"

    m2 = copy.deepcopy(manifest)
    m2["roles"]["seed"]["ghost_role"] = ["dashboard:view"]
    p2 = reconcile(m2, readings)
    assert any("ghost_role" in x and "清单多出" in x for x in p2), f"清单多出项没被报出：{p2}"

    r3 = copy.deepcopy(readings)
    r3["roles"]["seed"]["ghost_role"] = ["dashboard:view"]
    p3 = reconcile(manifest, r3)
    assert any("ghost_role" in x and "现值多出" in x for x in p3), f"现值多出项没被报出：{p3}"

    m4 = copy.deepcopy(manifest)
    m4["_note"] = "（只改散文：不进对账）"
    assert reconcile(m4, readings) == [], "只改元字段散文却判红 ⇒ 对账把散文当事实读（对照读数失败）"


def test_unreconciled_segment_is_red():
    """段集判据的红证：往清单加一个生成物没有的段 ⇒ 必红；只加下划线元字段 ⇒ 不红（对照）。"""
    manifest, readings = load_json(MANIFEST_PATH), load_json(READINGS_PATH)
    m = copy.deepcopy(manifest)
    m["hand_written_extra"] = {"a": 1}
    assert any("hand_written_extra" in x for x in unreconciled_segments(m, readings)), (
        "加了未对账的段却没红 ⇒ 清单可以长出无人核的新真值源"
    )
    m2 = copy.deepcopy(manifest)
    m2["_hand_written_prose"] = "说明性元字段"
    assert unreconciled_segments(m2, readings) == [], "下划线元字段不该判红（它不是声明）"


def test_freshness_detects_hand_edited_artifact():
    """M3 的红证：生成物被手改一个字 ⇒ 必红（且报出首个差异行）；原样 ⇒ 不红（对照）。"""
    gen = load_generator()
    text = gen.dumps(gen.build_readings())
    assert freshness_problems(text, text) == [], "原样比对竟报陈旧 ⇒ 新鲜度判据是空断言"
    mutated = text.replace('"stage": "', '"stage": "hand-edited-', 1)
    assert mutated != text, "变异注入未生效（自证失败 ⇒ 本红证是空断言）"
    problems = freshness_problems(mutated, text)
    assert problems and "首个差异在第" in problems[1], f"手改生成物没被报出：{problems}"


def test_registry_detects_unregistered_and_stale():
    """M1 的红证：未登记命中 ⇒ 具名红；陈旧登记 ⇒ 红；真实态 ⇒ 不红（对照）。"""
    hits = list(repo_copy_face_hits())
    registry = load_json(SOURCES_PATH)
    assert unregistered_copies(hits, registry) == [], "落地态有未登记副本（前提不成立）"
    assert stale_registrations(hits, registry) == [], "落地态有陈旧登记（前提不成立）"

    injected = hits + [{"face": "menu-frontend-nodes", "file": "frontend/admin-web/src/config/menu2.ts", "count": 3}]
    problems = unregistered_copies(injected, registry)
    assert any("menu2.ts" in x for x in problems), f"未登记副本没被具名报出：{problems}"

    ghost = copy.deepcopy(registry)
    ghost["sources"] = ghost["sources"] + [
        {"face": "menu-frontend-nodes", "file": "frontend/admin-web/src/config/ghost.ts",
         "hits": 1, "kind": "declaration", "derived_from": "manifest.menu_nodes", "note": "红证注入"}
    ]
    stale = stale_registrations(hits, ghost)
    assert any("ghost.ts" in x and "陈旧登记" in x for x in stale), f"陈旧登记没被具名报出：{stale}"


def test_registry_hit_count_drift_is_red():
    """**M1 的 P2 硬化红证**：登记的 `hits` 与现取不符 ⇒ 必红（两个方向）；原样 ⇒ 不红（对照）。"""
    hits = list(repo_copy_face_hits())
    registry = load_json(SOURCES_PATH)
    assert copy_hit_count_drift(hits, registry) == [], "落地态命中数已漂移（前提不成立）"
    target = hits[0]
    drifted = copy.deepcopy(registry)
    for entry in drifted["sources"]:
        if (entry["face"], entry["file"]) == (target["face"], target["file"]):
            entry["hits"] = target["count"] + 1
    assert any(target["file"] in x and "命中数漂移" in x for x in copy_hit_count_drift(hits, drifted)), (
        "登记的命中数被改却没被报出"
    )


def test_copy_face_comment_only_is_not_a_hit():
    """M1 的**对照读数**：「只改注释 / 不改真东西」必须**不红**（否则判据被自己的文案喂红）。

    形态面在**剥注释后**的代码上匹配 ⇒ 注释里写一行同形的 `permissionCode: 'x',`
    不得算副本；真写进代码才算（同一输入里两者都有，只有后者命中）。
    """
    files = {
        "frontend/admin-web/src/config/menu_comment_only.ts": (
            "// 说明：这里曾经有 permissionCode: 'product:list',（已迁走）\n"
            "export const X = 1;\n"
        ),
        "frontend/admin-web/src/config/menu_real.ts": (
            "export const items = [{ permissionCode: 'product:list' }];\n"
        ),
    }
    hits = copy_face_hits(files)
    got = {h["file"] for h in hits}
    assert "frontend/admin-web/src/config/menu_real.ts" in got, f"真写了码却没命中：{hits}"
    assert "frontend/admin-web/src/config/menu_comment_only.ts" not in got, (
        f"只写在注释里却被读成副本（判据被文案喂红）：{hits}"
    )


def test_copy_face_scan_reads_the_declared_corpus():
    """M1 扫描器的判别力自证：把真语料喂进去 ⇒ 必须命中原样登记的那几处（不是合成输入）。

    本判据证明的是「**变异真的被读到**」的另一面：同一份扫描器在**真实语料**上产出命中，
    而这批命中与登记表逐条相等（由 `test_every_copy_face_hit_is_registered` 判）。
    """
    corpus = read_corpus()
    assert corpus, "语料为空 ⇒ 扫描器是空跑（fail-closed）"
    hits = copy_face_hits(corpus)
    by_face = {h["face"] for h in hits}
    for expected in ("role-defaults-seed", "role-defaults-fallback", "menu-tree", "sql-role-grants"):
        assert expected in by_face, f"真语料里没扫到 {expected}（形态写错或语料没读到）：{sorted(by_face)}"


def test_narrowed_copy_face_scope_is_caught():
    """射程元判据的红证：把**声明**收窄而实现照旧 ⇒ 必红（「声称 != 实际」的形态本身）。"""
    narrowed = copy.deepcopy(COPY_FACE_SCOPE)
    narrowed["roots"] = ("tests/unit_ci_workflows",)
    declared = walk_scope(narrowed)
    actual = scanned_files()
    assert declared != actual, "收窄声明后竟与实现一致 ⇒ 本红证无判别力"
    assert declared - actual == set(), "收窄声明应是实现的子集（前提）"
    assert len(actual - declared) > 0, f"收窄后没暴露「实际扫了而没声称」：{sorted(actual - declared)[:6]}"


def test_ledger_growth_and_count_drift_are_red():
    """**M2 的红证**（三类坏形态各自单独变红 + 一组对照读数）。

    ① 某张台账现取条数 > 上限 ⇒ 红（命中 `ledger_growth_problems` 的「只许缩短」分支）；
    ② 台账没有上限登记 ⇒ 红（命中「没有上限登记」分支）；
    ③ 清单里的条数与现取不符（**涨或跌**都算）⇒ 红（命中 `ledger_count_drift`）；
    对照：现取 == 上限、且清单 == 现取 ⇒ **不红**。
    """
    gen = load_generator()
    counts = gen.build_readings()["ledger_counts"]
    manifest = load_json(MANIFEST_PATH)
    assert ledger_growth_problems(counts, LEDGER_CEILINGS) == [], "落地态已超上限（前提不成立）"
    assert ledger_count_drift(manifest, counts) == [], "落地态清单与现取不符（前提不成立）"

    grown = dict(counts, ROLE_FALLBACK_DIVERGENCES=counts["ROLE_FALLBACK_DIVERGENCES"] + 1)
    p1 = ledger_growth_problems(grown, LEDGER_CEILINGS)
    assert any("ROLE_FALLBACK_DIVERGENCES" in x and "只许缩短" in x for x in p1), f"条数增长没被报出：{p1}"

    p2 = ledger_growth_problems(dict(counts, ZZ_NEW_TABLE=1), LEDGER_CEILINGS)
    assert any("ZZ_NEW_TABLE" in x and "没有上限登记" in x for x in p2), f"未登记上限没被报出：{p2}"

    drifted = copy.deepcopy(manifest)
    drifted["ledger_counts"]["AUTHORIZATION_CENSUS"] = counts["AUTHORIZATION_CENSUS"] + 1
    p3 = ledger_count_drift(drifted, counts)
    assert any("AUTHORIZATION_CENSUS" in x for x in p3), f"清单条数漂移没被报出：{p3}"
