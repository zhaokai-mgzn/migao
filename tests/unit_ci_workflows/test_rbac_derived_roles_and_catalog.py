# case_ids: MC-029, MC-030
"""RBAC 单一真值源 **P2**：由清单**派生**「角色 → 码」与「码目录」+ **A7 消费面取证**
（跟踪单 issue #5699；设计真值源 `docs/design/rbac-single-source.md` 的 §4 与 §2.4）。

## 这一条判据要治什么

P1 把「角色 → 码 / 码目录」的**现值**搬进清单并对账（清单 == 生成物 == 现值）。但清单当时只覆盖
**两面**（种子 A1 / 回退 A2），还有两处**根本没有声明**：

- **A7**（`backend/admin-api/src/main/java/com/migao/admin/service/UserService.java` 的
  `getRolePermissions(String roleCode)`，登录面）—— 设计 §1.4 的补登注：它授予的四个码在权限目录里
  **各 0 命中**，是「角色 → 码」的第 8 份副本，而**没有任何机制**与 A1/A2 同步；
- **码目录的名称列**（B 类的元数据）—— 它是 ai-agent 的 `PERMISSION_LABELS`（B3）唯一的对照面。

P2 做两件事，**都不改行为**（零 delta）：

| 面 | 派生（本文件的被测对象） | 现值（对照） |
|---|---|---|
| A1 种子 / A2 回退 / **A7 登录面** | 清单 `roles.seed` / `roles.fallback` / `roles.login` | `parse_role_defaults` / `parse_role_fallback`（A7 传 `anchor=` **复用同一个**解析函数） |
| **A3 / B3 / B4**（ai-agent 三个手抄镜像） | `derive_mirror_roles` / `codes.names` / 目录码列 | `ast.literal_eval` 读那三个模块级字面量 |
| B1 / B2 目录（码 + 名称） | `codes.registration` / `codes.permission_service` / `codes.names` | `parse_catalog_rows`（与 `parse_catalog` **同一份正则**） |
| 码目录（码 → 名称 + 持有角色） | `derive_catalog`（`*` 展开成目录全集） | 由现值角色面反查（`catalog_view` —— **与派生共用同一份实现**） |

## 🔴 零 delta 是本阶段唯一的验收口径（违反即返工）

派生结果与现值必须**逐值相等**、**逐项点名**（不许用「数量相等」充数）。若不等 ⇒ **只报告、不修**
（那是 P4/P5 的活，且必须由人在知悉差量后点头）⇒ 故本文件的判据在「不等」时输出的是
**完整不一致清单**（每项一行），不是一个布尔量。

## ② A7 的消费面取证 → 人类裁定「**退役**」（2026-09-27）

「保留 or 退役」是**行为问题**，先取证、再由人类裁定（设计 §6 第 7 条）。**裁定 = A. 退役**
（消除全仓唯一一处「授予目录外的码」，与 ai-agent 镜像对齐）⇒ 本文件把**裁定前后的读数**都钉住：

1. `getRolePermissions` 在**仓内**（`backend/**/src/main`）的调用方**只有** `loadUserByUsername`；
2. A7 的四个码在**判定面**（`backend/**/src/main` + `backend/ai-agent-service/app` + `frontend/**`）
   退役前**只有声明本体自己**（⇒ 没有任何授权判定读它们）、退役后**一处都没有**；
3. 它的授予面**在仓内不可达**：全仓没有 `AuthenticationManager` 的 `authenticate(...)` 调用
   ⇒ `UserDetailsService` 那条线没有调用方（**机制存活读数**：谁哪天把它接上，本判据立刻变红）；
4. 身份面按**角色**判而不是按码判（`ServiceTokenFilter.C_END_ROLES` / `SecurityConfig` 的拒绝角色集 /
   ai-agent 的 `CUSTOMER_ONLY_ROLES`）⇒ 与 A7 的码**不相交**；
5. **存废已裁定**（2026-09-27，人类选「退役」）⇒ 现取读数：判定面命中 = 空、
   `A7_CODES_BEYOND_CATALOG` = 0（上限 0，**只许缩短**）、`A7_VS_MIRROR_DIVERGENCES` = 0、
   `manifest.roles.login` 只剩 `super_admin` / `admin` 的 `"*"`（通配符**不是**目录码，本次不动）。

## 覆盖面（**覆盖不到什么**，与设计 §5.3 逐条对齐）

- 派生只覆盖**能被既有解析器读到**的形态：同一事实若写成 `Map.of(...)` / YAML /
  从 `@ConfigurationProperties` 注入 ⇒ **看不见**（与 M1 的边界同源）；
- **不覆盖 A4**（迁移链的存量 `role_permissions` 授权）：它是「存量租户一次性」的谓词，
  与「角色 → 默认码」不是同一个读数（设计 §3.1 已登记该差距，归 P5）；
- **不覆盖 A5**（`users.permissions` 快照）：实例数据，不是声明；
- A7 的**运行时真值**（`customer` / `agent` 账号登录后实际拿到的 authority 集）**未取证**：
  本机没有可跑的 `admin-api`/真库环境（设计 §6 第 1 条同款）⇒ 重启条件写在设计文档里，
  **不得**把本文件读成「A7 已验收」；
- A7 的**存废已裁定**（退役，2026-09-27）—— 本文件把裁定钉成三条**只许缩短 / 零容忍**的读数（见上 5）；
  运行时可复算的「退役安全性」前提（该授予面不可达）由第 3 条的机制存活读数持续守着。

## 红证的机具纪律（本仓已固化）

判据一律是**纯函数**（输入 = 清单 / 现值读数 / 源码文本，输出 = 问题清单），注入式红证**当场在内存里
构造坏形态**并把变异体**直接作为判据入参**；涉及**改磁盘文件**的变异还要额外证明**变异真的被读到**
（本文件的「只改注释」对照读数就是干这个的：注释里写一个 A7 的码 ⇒ 现值读数**逐值不变**）。
"""
from __future__ import annotations

import copy
import functools
import importlib.util
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RBAC_DIR = REPO_ROOT / "rbac"
MANIFEST_PATH = RBAC_DIR / "manifest.json"
PARITY_GUARD = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_agent_permission_parity.py"
#: P1 守卫（**剥注释的唯一实现在它里面**：`strip_for` —— 本文件复用，不另写第二套剥离器）。
MANIFEST_GUARD = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_rbac_single_source_manifest.py"
DERIVE_PATH = RBAC_DIR / "derive.py"

#: 判定面 = 真能「读这些码去做决定」的代码根（测试与文档**不算**：它们不参与授权判定）。
JUDGEMENT_SURFACE_ROOTS = (
    "backend/admin-api/src/main",
    "backend/ai-agent-service/app",
    "frontend",
)

#: A7 退役前授予、**不在权限目录里**的四个码（现取：判定面**一处都不许有**）。
#: 🔴 2026-09-27 人类裁定「退役」后，`UserService` 已不再授予它们 ⇒ 本常量是**再引入绊线**：
#: 谁把这四个码写回任何判定面文件，`judgement_surface_problems` 就具名报出。
A7_CODES = ("chat:read", "chat:write", "customer:read", "order:read")
A7_WILDCARD = "*"

#: 身份面常量（按**角色**判，不按码判）—— 各自所在的文件与符号。
IDENTITY_ROLE_SETS = (
    ("backend/admin-api/src/main/java/com/migao/admin/security/ServiceTokenFilter.java",
     r'C_END_ROLES\s*=\s*Set\.of\(([^)]*)\)', "ServiceTokenFilter.C_END_ROLES"),
    ("backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java",
     r'ADMIN_API_REJECTED_ROLES\s*=\s*Set\.of\(([^)]*)\)', "SecurityConfig.ADMIN_API_REJECTED_ROLES"),
    ("backend/ai-agent-service/app/tools/base.py",
     r'CUSTOMER_ONLY_ROLES\s*=\s*frozenset\(\{([^}]*)\}\)', "base.CUSTOMER_ONLY_ROLES"),
)

#: 未覆盖面登记（**只许缩短**；照设计 §5.3 的「覆盖不到什么」写法，每条写清谁看）。
UNCOVERED_FACES: tuple[dict[str, str], ...] = (
    {
        "face": "A7 的**运行时**授予值（`customer` / `agent` 账号登录后实际拿到的 authority 集）",
        "reason": "本机没有可跑的 admin-api / 真库环境 ⇒ 只能取证**静态调用面**，不能取证运行时读数",
        "owner": "RBAC 跟踪单 #5699 的重启条件（设计 §6 第 7 条：接上真环境后复算）",
        "issue": "#5699",
    },
    {
        "face": "A7 的**存废**（保留 = 身份面专用 / 退役 = 从登录面删掉那几个码）",
        "reason": "那是**行为问题**，必须由人类裁定（设计 §6 第 7 条）；本判据只把现值登记住、不表达倾向",
        "owner": "人类裁定（P6 性质项）",
        "issue": "#5699",
    },
    {
        "face": "非约定形态的「角色 → 码」声明（`Map.of(...)` / YAML / `@ConfigurationProperties`）",
        "reason": "派生与 M1 的形态面都只认既有解析器能读到的形态；非约定形态看不见（假绿方向）",
        "owner": "RBAC 跟踪单 #5699（与 test_rbac_single_source_manifest.py 的 UNCOVERED_FACES 同源）",
        "issue": "#5699",
    },
    {
        "face": "A4 迁移链的存量授权谓词（「存量租户的角色 → 码」与种子的差距）",
        "reason": "谓词 ≠ 默认码集；设计 §3.1 已登记该差距，处置归 P5（要人点头的改行为阶段）",
        "owner": "RBAC 跟踪单 #5699 的 P5",
        "issue": "#5699",
    },
)
UNCOVERED_FACE_CAP = 4


# ══════════════════════════════════════════════════════════════════════════════
# 一、读盘（清单 / 派生器 / 既有解析器）—— 缺任一 ⇒ fail-closed，不静默当空
# ══════════════════════════════════════════════════════════════════════════════


def _load_module(name: str, path: Path):
    """按路径加载模块（`sys.modules` 先注册：`@dataclass` 解析 `cls.__module__` 的前提）。"""
    if name in sys.modules:
        return sys.modules[name]
    assert path.is_file(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"无法为 {path} 建立加载器（fail-closed）"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_manifest() -> dict:
    assert MANIFEST_PATH.is_file(), f"声明真值源不存在：{MANIFEST_PATH}（fail-closed）"
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data, "清单必须是**非空对象**（空 ⇒ 判据在空集上恒真）"
    return data


def load_parity_guard():
    """既有解析器的**唯一家**（P2 沿用 P1 的同一套机具；不另造第二套）。"""
    return _load_module("migao_rbac_parity_guard", PARITY_GUARD)


def load_derive():
    """P2 派生器（`rbac/derive.py`；生成器与判据共用同一份实现）。"""
    return _load_module("migao_rbac_derive", DERIVE_PATH)


def load_manifest_guard():
    """P1 守卫（**只为复用它的 `strip_for`** —— 剥注释的唯一实现在那里）。"""
    return _load_module("migao_rbac_p1_guard", MANIFEST_GUARD)


#: 判定面语料里要读的扩展名（与 M1 的语料口径同族：只读**代码**，不读文档）。
JUDGEMENT_FILE_GLOBS = ("*.java", "*.ts", "*.tsx", "*.py")

#: 读语料时剪掉的目录（构建产物 / 依赖树）。
CORPUS_EXCLUDE_DIRS = frozenset(
    {"node_modules", ".next", "dist", "build", ".venv", "venv", "coverage", "__pycache__"}
)


@functools.lru_cache(maxsize=1)
def read_judgement_files() -> dict[str, str]:
    """读**判定面**的语料（`{仓库相对路径: 文本}`）—— 缓存：四条判据共用同一次读盘。"""
    out: dict[str, str] = {}
    for root in JUDGEMENT_SURFACE_ROOTS:
        base = REPO_ROOT / root
        assert base.is_dir(), f"判定面的根不存在：{root}（路径漂移 ⇒ 红，不得静默跳过）"
        for suffix in JUDGEMENT_FILE_GLOBS:
            for path in base.rglob(suffix):
                if CORPUS_EXCLUDE_DIRS & set(path.parts):
                    continue
                rel = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
                out[rel] = path.read_text(encoding="utf-8")
    assert out, "判定面语料为空 ⇒ 判据在空集上恒真（fail-closed）"
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 二、现值（**全部走既有解析器 / 标准库 AST**；注入式红证就是替换这里的某一项文本）
# ══════════════════════════════════════════════════════════════════════════════


def present_values(sources: dict[str, str] | None = None, parity=None, derive=None) -> dict:
    """八个消费面的**现值**（纯函数：喂改过的源码表 ⇒ 读数必须跟着变）。"""
    p = parity if parity is not None else load_parity_guard()
    d = derive if derive is not None else load_derive()
    src = sources if sources is not None else p._source_map()
    mirror = d.mirror_present_values()
    rows_reg, rows_perm = p.parse_catalog_rows(
        src["java:service/RegistrationService.java"],
        src["java:service/PermissionService.java"],
    )
    return {
        "A1": _sorted_map(p.parse_role_defaults(src["java:service/RegistrationService.java"])),
        "A2": _sorted_map(p.parse_role_fallback(src["java:service/RoleService.java"])),
        "A7": _sorted_map(
            p.parse_role_fallback(
                src["java:service/UserService.java"], anchor=p.ROLE_SWITCH_ANCHOR_USER_SERVICE
            )
        ),
        "A3": mirror["A3"],
        "B1": sorted(row[1] for row in rows_reg),
        "B2": sorted(row[1] for row in rows_perm),
        "B3": mirror["B3"],
        "B4": mirror["B4"],
    }


def present_catalog_names(sources: dict[str, str] | None = None, parity=None) -> dict[str, dict[str, str]]:
    """两处目录的**名称列**现值（`{B1: {码: 名}, B2: {码: 名}}`）—— 只作目录对账的对照，不是消费面。"""
    p = parity if parity is not None else load_parity_guard()
    src = sources if sources is not None else p._source_map()
    rows_reg, rows_perm = p.parse_catalog_rows(
        src["java:service/RegistrationService.java"],
        src["java:service/PermissionService.java"],
    )
    return {
        "B1": {row[1]: row[0] for row in rows_reg},
        "B2": {row[1]: row[0] for row in rows_perm},
    }


def _sorted_map(table: dict) -> dict[str, list[str]]:
    assert table, "岗位表解析出 0 个角色 ⇒ 判据会空跑（fail-closed）"
    return {role: sorted(codes) for role, codes in sorted(table.items())}


def present_catalog(present: dict, names: dict, derive) -> dict[str, dict[str, object]]:
    """由**现值**反查的码目录（与派生共用 `catalog_view` ⇒ 两边不会各写一份投影规则）。"""
    return derive.catalog_view(present["B2"], names["B1"], (present["A1"], present["A2"]))


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据本体（纯函数：输入注入，输出问题清单 —— 空 = 绿）
# ══════════════════════════════════════════════════════════════════════════════


def _flatten(value: object, prefix: str = "") -> list[tuple[str, object]]:
    """把嵌套结构摊平成 `(路径, 值)` 清单（**逐项点名**的对账口径：不用「数量相等」充数）。"""
    if isinstance(value, dict):
        out: list[tuple[str, object]] = []
        for key in sorted(value, key=str):
            out.extend(_flatten(value[key], f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list):
        out = []
        for i, item in enumerate(value):
            out.extend(_flatten(item, f"{prefix}[{i}]"))
        return out
    return [(prefix, value)]


def reconcile_surfaces(derived: dict, present: dict) -> list[str]:
    """**零 delta 逐项点名**：每个面的派生值 vs 现值，逐叶比对 ⇒ 完整不一致清单。

    每个不一致项一行（例：`A7.agent[0]: 派生='chat:read' / 现值='…'`），
    ⇒ 「不一致即报告，不修」（设计 §4 的 P2 验收口径）。面的**全集**也要相等：
    派生多出一个面 / 少一个面 ⇒ 具名报出（否则「漏了一个面」会静默通过）。
    """
    out: list[str] = []
    for surface in sorted(set(derived) | set(present)):
        if surface not in derived:
            out.append(f"[现值多出] 面 {surface}（清单里没有 ⇒ 声明有、派生无）")
            continue
        if surface not in present:
            out.append(f"[派生多出] 面 {surface}（现值里没有 ⇒ 派生了一个不存在的面）")
            continue
        want = dict(_flatten({surface: derived[surface]}))
        got = dict(_flatten({surface: present[surface]}))
        for key in sorted(set(want) | set(got)):
            if key not in got:
                out.append(f"[派生多出] {key} = {want[key]!r}（现值里没有这一项）")
            elif key not in want:
                out.append(f"[现值多出] {key} = {got[key]!r}（派生里没有这一项）")
            elif want[key] != got[key]:
                out.append(f"[值不等] {key}: 派生={want[key]!r} / 现值={got[key]!r}")
    return out


def catalog_problems(derived: dict, present: dict) -> list[str]:
    """码目录（码 → 名称 + 持有角色）的零 delta 对账（逐码逐值）。"""
    out: list[str] = []
    for code in sorted(set(derived) | set(present)):
        if code not in present:
            out.append(f"[派生多出] 码 {code}（现值目录里没有）")
            continue
        if code not in derived:
            out.append(f"[现值多出] 码 {code}（派生目录里没有）")
            continue
        for field in ("name", "holders"):
            if derived[code][field] != present[code][field]:
                out.append(
                    f"[值不等] {code}.{field}: 派生={derived[code][field]!r} / "
                    f"现值={present[code][field]!r}"
                )
    return out


def catalog_name_divergences(names: dict[str, dict[str, str]]) -> list[str]:
    """两处目录（B1 建库 / B2 懒补种）的**名称列**必须一致（码列由既有判据 9② 判）。"""
    return [
        f"{code}: B1(RegistrationService)={names['B1'].get(code)!r} / "
        f"B2(PermissionService)={names['B2'].get(code)!r}"
        for code in sorted(set(names["B1"]) | set(names["B2"]))
        if names["B1"].get(code) != names["B2"].get(code)
    ]


# ── ② A7 消费面取证（机器可判的那部分）────────────────────────────────────────


def strip_comments(rel: str, text: str) -> str:
    """按扩展名剥注释（**复用** P1 守卫里那份唯一实现 `strip_for`，不另写第二套剥离器）。

    为什么必须剥：本判据的射程含 `src/main/**` 的**散文**（javadoc 里正记着这次退役的原委，
    逐字写着那四个码）⇒ 不剥注释就会被**自己的说明文字**喂红（本仓已固化的那一类反模式）。
    """
    return load_manifest_guard().strip_for(Path(rel).suffix, text)


def a7_code_hits(files: dict[str, str], roots=JUDGEMENT_SURFACE_ROOTS) -> dict[str, list[str]]:
    """判定面里出现 A7 码的文件 → 命中的码（**纯函数**：喂 `{相对路径: 文本}` ⇒ 命中表）。

    **先剥注释再匹配**（`strip_comments`）—— 注释里提一句不算「判定面在读它」。
    """
    out: dict[str, list[str]] = {}
    for rel in sorted(files):
        if not any(rel.startswith(root + "/") for root in roots):
            continue
        body = strip_comments(rel, files[rel])
        found = sorted({code for code in A7_CODES if f'"{code}"' in body})
        if found:
            out[rel] = found
    return out


def judgement_surface_problems(hits: dict[str, list[str]]) -> list[str]:
    """判定面出现 A7 的四个目录外码 ⇒ **一律**具名报出（退役后**零容忍**，无豁免文件）。

    为什么零容忍：这四个码不在权限目录里（`codes_beyond_catalog` 现取 = 0 是**退役的结果**），
    任何一处重新出现都等于「又造了一处授予/读取目录外码的地方」⇒ 必须由人重新裁定
    （设计真值源 §1.6 (d) 的三条出口），**不许**由实现者顺手放回去。
    """
    return [
        f"判定面出现 A7 的目录外码：{rel} → {codes}"
        "（这四个码已由人类裁定退役、不在权限目录里；重新引入要先过人裁定，见设计 §1.6）"
        for rel, codes in sorted(hits.items())
    ]


def sole_caller_problems(text: str) -> list[str]:
    """`getRolePermissions` 的定义/调用点越出「声明本体 + `loadUserByUsername`」⇒ 报出。

    口径 = **词法**（先剥 Java 注释，再找 `getRolePermissions(` 的出现行），
    ⇒ 注释里提一句不算调用（对照读数见 `test_comment_only_mutation_is_inert`）。
    """
    p = load_parity_guard()
    code = p.java_code(text)
    out = []
    for line in code.splitlines():
        if "getRolePermissions(" not in line:
            continue
        head = line.strip()
        if head.startswith("public List<String> getRolePermissions(") or head.startswith("private "):
            continue  # 定义本体
        if "this.getRolePermissions(" in head or "getRolePermissions(role)" in head:
            continue  # 声明本体内部的唯一调用点（loadUserByUsername）
        out.append(f"`getRolePermissions` 出现在非预期位置：{head}")
    return out


def authenticate_call_problems(texts: dict[str, str]) -> list[str]:
    """全仓（`backend/**`）不得出现 `AuthenticationManager` 的 `authenticate(...)` 调用。

    现取 = 0 ⇒ **A7 的授予面在仓内不可达**（`UserDetailsService` 那条线没有调用方）。
    这是一条**机制存活读数**：谁哪天把它接上（哪怕只是一行），A7 就从「登记住的旧副本」
    变成「活着的授权面」⇒ 本判据立刻变红，必须重新取证。
    """
    return [
        f"{rel}: 出现 `AuthenticationManager` 的 authenticate 调用（A7 的授予面被接上了 ⇒ 重新取证）"
        for rel, text in sorted(texts.items())
        if re.search(r"authenticationManager\s*\.\s*authenticate\s*\(", strip_comments(rel, text))
    ]


def identity_role_set_problems(texts: dict[str, str]) -> list[str]:
    """身份面必须按**角色**判：三个角色集合常量都要在，且与 A7 的码**不相交**。"""
    out: list[str] = []
    for rel, pattern, label in IDENTITY_ROLE_SETS:
        text = texts.get(rel)
        if text is None:
            out.append(f"{label}：文件读不到（{rel}）⇒ 身份面口径不明（fail-closed）")
            continue
        m = re.search(pattern, text)
        if not m:
            out.append(f"{label}：常量找不到（口径漂移 ⇒ 红）")
            continue
        roles = {token.strip().strip('"').strip("'") for token in m.group(1).split(",")}
        roles.discard("")
        if roles & set(A7_CODES):
            out.append(f"{label} 的内容与 A7 的码相交：{sorted(roles & set(A7_CODES))}（判定口径混淆）")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 四、判据（每条配注入式红证 + 对照读数）
# ══════════════════════════════════════════════════════════════════════════════


def test_derived_surfaces_match_present_values():
    """**P2 主判据（零 delta）**：八个消费面的派生结果与现值**逐值相等**，逐项点名。

    不等时输出**完整不一致清单**（「发现 delta」是正常交付，**不改**、只报告 —— 设计 §4 的 P2 口径）。
    """
    manifest, derive = load_manifest(), load_derive()
    present = present_values(derive=derive)
    derived = derive.consumer_surfaces(manifest)

    print("── P2 零 delta 逐项点名（派生 == 现值）──")
    counted = 0
    for surface in sorted(derived):
        for key, value in _flatten({surface: derived[surface]}):
            counted += 1
            print(f"  {key} = {value!r}")
    print(
        f"── 逐值比对项数 = {counted}（**口径**：八个消费面的派生结果摊平到叶的 `(路径, 值)` 对总数 —— "
        "角色表按「角色 → 逐码」展开（每个码一项，如 `A1.operator[3]`）、目录码列逐个码一项、"
        "B3 按「码 → 名称」逐码一项；两条读数必须互为镜像）；不一致 = 0 ──"
    )
    problems = reconcile_surfaces(derived, present)
    assert problems == [], (
        f"派生结果与现值**不一致**（共 {len(problems)} 项）—— 🔴 本阶段只报告、不修"
        "（P4/P5 的活，且须人点头）：\n" + "\n".join(f"  · {p}" for p in problems)
    )


def test_derived_catalog_matches_present_values():
    """**码目录**（码 → 名称 + 持有角色）派生 == 现值，逐码逐值；两处目录的名称列也必须一致。"""
    manifest, derive = load_manifest(), load_derive()
    present = present_values(derive=derive)
    names = present_catalog_names()
    derived = derive.derive_catalog(manifest)
    got = present_catalog(present, names, derive)
    print(f"── 码目录：派生 {len(derived)} 码 / 现值 {len(got)} 码 ──")
    problems = catalog_problems(derived, got) + catalog_name_divergences(names)
    assert problems == [], "码目录不合规：\n" + "\n".join(f"  · {p}" for p in problems)


def test_a7_codes_are_absent_from_judgement_surface():
    """**② A7 消费面取证（裁定后）**：判定面里 A7 的四个目录外码**一处都没有**。

    取证结论（退役前）= 九处消费方无一读它们；裁定（2026-09-27）= **退役** ⇒ 现取必须为**空**。
    红证见 `test_a7_new_consumer_is_named`。边界：测试与文档**不在**判定面内（它们不参与授权判定），
    但它们由 M1 的 `a7-login-codes-consumer` 形态面登记（`rbac/sources.json`）⇒ 再引入同样会红。
    """
    files = read_judgement_files()
    assert files, "判定面语料为空 ⇒ 本判据在空集上恒真（fail-closed，不是「干净」）"
    hits = a7_code_hits(files)
    print(f"判定面命中 A7 目录外码的文件：{json.dumps(hits, ensure_ascii=False)}（现取应为 {{}}）")
    problems = judgement_surface_problems(hits)
    assert problems == [], "A7 的目录外码出现在判定面：\n" + "\n".join(f"  · {p}" for p in problems)


def test_a7_grants_no_code_outside_catalog():
    """**退役已生效**：A7 授予的码里**没有**任何一个在权限目录之外（`*` 是通配符，不算）。

    这条把人类的裁定钉成读数：退役前现取 = 4（`chat:read` / `chat:write` / `customer:read` / `order:read`），
    退役后 = 0。红证 = M2 台账上限（0，只许缩短）+ 清单零 delta。
    """
    manifest, derive = load_manifest(), load_derive()
    present = present_values(derive=derive)
    beyond = derive.codes_beyond_catalog(present["A7"], present["B2"])
    print(f"A7 授予但不在目录里的码：{beyond}（现取应为 []）")
    assert beyond == [], (
        f"A7 又授予了目录外的码：{beyond} —— 🔴 它们已于 2026-09-27 由人类裁定**退役**"
        "（设计真值源 §1.6 (d)）；重新引入必须先过人裁定"
    )


def test_a7_declaration_has_exactly_one_in_repo_caller():
    """A7 的调用点只在声明本体内部（`loadUserByUsername`）；且**授予面在仓内不可达**。

    后半句 = 全仓 `backend/**` 没有 `AuthenticationManager` 的 `authenticate(...)` 调用
    （现取 0）—— 这是**机制存活读数**：接上它 ⇒ 红（那时 A7 才是活授权面）。
    """
    p = load_parity_guard()
    src = p._source_map()
    problems = sole_caller_problems(src["java:service/UserService.java"])
    texts = {
        rel: (REPO_ROOT / rel).read_text(encoding="utf-8")
        for rel in ("backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java",
                    "backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java")
    }
    problems += authenticate_call_problems(texts)
    assert problems == [], "A7 的调用面不合规：\n" + "\n".join(f"  · {p}" for p in problems)


def test_identity_faces_are_role_based_not_code_based():
    """身份面（C 端 / 工人端 / 拒绝集合）按**角色**判，与 A7 的码**不相交**（口径不混淆）。"""
    p = load_parity_guard()
    src = p._source_map()
    texts = dict(src)
    for rel, _pattern, _label in IDENTITY_ROLE_SETS:
        texts.setdefault(rel, (REPO_ROOT / rel).read_text(encoding="utf-8"))
    problems = identity_role_set_problems(texts)
    assert problems == [], "身份面口径不合规：\n" + "\n".join(f"  · {p}" for p in problems)


def test_uncovered_faces_only_shrink_and_stay_live():
    """覆盖面登记（设计 §5.3）：条数 ≤ 上限，每条须有 face/reason/owner/issue。"""
    problems: list[str] = []
    if len(UNCOVERED_FACES) > UNCOVERED_FACE_CAP:
        problems.append(f"未覆盖面 {len(UNCOVERED_FACES)} 条 > 上限 {UNCOVERED_FACE_CAP} 条（只许缩短）")
    for face in UNCOVERED_FACES:
        for key in ("face", "reason", "owner", "issue"):
            if not face.get(key):
                problems.append(f"未覆盖面条目缺 {key!r}（必须写清「谁看」）：{face}")
    assert problems == [], "未覆盖面台账不合规：\n" + "\n".join(f"  · {p}" for p in problems)


# ══════════════════════════════════════════════════════════════════════════════
# 五、注入式红证（**当场在内存里构造坏形态**，变异体直接作为判据入参）
# ══════════════════════════════════════════════════════════════════════════════


def test_reconcile_names_each_surface_mismatch():
    """主判据的红证：三类坏形态各**单独**变红，且报出的是**具名**项。

    ① 改清单 `roles.login.agent` 的一个码（A7 面，值不等）；
    ② 改清单 `codes.names` 的一个名字（B3 面，值不等）；
    ③ 往清单加一个现值没有的角色（现值多出）。
    对照组（**应当不红**）：只改清单的 `_note` 散文（元字段不进派生）。
    """
    manifest, derive = load_manifest(), load_derive()
    present = present_values(derive=derive)
    assert reconcile_surfaces(derive.consumer_surfaces(manifest), present) == [], (
        "落地态必须零不一致（否则本红证的前提不成立）"
    )

    m1 = copy.deepcopy(manifest)
    m1["roles"]["login"]["agent"] = ["chat:read"]  # 退役后 A7 已不给 agent 任何码 ⇒ 这是「派生多出」
    p1 = reconcile_surfaces(derive.consumer_surfaces(m1), present)
    assert any("A7.agent" in x for x in p1), f"改 A7 面没被具名报出：{p1}"

    m2 = copy.deepcopy(manifest)
    first_code = sorted(m2["codes"]["names"])[0]
    m2["codes"]["names"][first_code] = "被改过的名字"
    p2 = reconcile_surfaces(derive.consumer_surfaces(m2), present)
    assert any("B3" in x and first_code in x for x in p2), f"改目录名称没被具名报出：{p2}"

    m3 = copy.deepcopy(manifest)
    m3["roles"]["login"]["ghost_role"] = ["dashboard:view"]
    p3 = reconcile_surfaces(derive.consumer_surfaces(m3), present)
    assert any("ghost_role" in x and "派生多出" in x for x in p3), f"派生多出项没被报出：{p3}"

    m4 = copy.deepcopy(manifest)
    m4["_note"] = "（只改散文：不进派生）"
    assert reconcile_surfaces(derive.consumer_surfaces(m4), present) == [], (
        "只改元字段散文却判红 ⇒ 派生把散文当事实读（对照读数失败）"
    )


def test_catalog_mismatch_is_named():
    """码目录对账的红证：改一个持有角色 / 删一个码 ⇒ 具名红；原样 ⇒ 不红（对照）。"""
    manifest, derive = load_manifest(), load_derive()
    present = present_values(derive=derive)
    got = present_catalog(present, present_catalog_names(), derive)
    assert catalog_problems(derive.derive_catalog(manifest), got) == [], "落地态已不一致（前提不成立）"

    target = sorted(got)[0]
    mutated = copy.deepcopy(got)
    mutated[target]["holders"] = ["ghost_role"]
    p1 = catalog_problems(derive.derive_catalog(manifest), mutated)
    assert any(target in x and "holders" in x for x in p1), f"持有角色被改没被报出：{p1}"

    mutated2 = copy.deepcopy(got)
    mutated2[target] = {"name": "被改过的名字", "holders": []}
    p2 = catalog_problems(derive.derive_catalog(manifest), mutated2)
    assert any(target in x and "name" in x for x in p2), f"名称被改没被报出：{p2}"


def test_a7_new_consumer_is_named():
    """A7 取证的红证：判定面**新增**一处读 A7 码的代码 ⇒ 具名红（命中「判定面出现 A7 的码」分支）。

    内存构造（**不落盘**）：真实语料 + 一个假想的新 controller。
    """
    real = read_judgement_files()
    assert judgement_surface_problems(a7_code_hits(real)) == [], "落地态已报红（前提不成立）"

    injected = dict(real)
    injected["backend/admin-api/src/main/java/com/migao/admin/controller/GhostController.java"] = (
        '@RequirePermission("chat:read")\npublic class GhostController {}\n'
    )
    problems = judgement_surface_problems(a7_code_hits(injected))
    assert any("GhostController" in x and "chat:read" in x for x in problems), (
        f"判定面新增消费方没被具名报出：{problems}"
    )


def test_a7_wired_authentication_manager_is_red():
    """机制存活读数的红证：把 `AuthenticationManager` 的 `authenticate(...)` 接上 ⇒ 必红。"""
    clean = {"backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java": "// 无调用\n"}
    assert authenticate_call_problems(clean) == [], "干净输入竟报红 ⇒ 判据是空断言"
    injected = dict(clean)
    injected["backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java"] = (
        "Authentication auth = authenticationManager.authenticate(token);\n"
    )
    problems = authenticate_call_problems(injected)
    assert any("AuthService.java" in x for x in problems), f"接上授予面没被报出：{problems}"


def test_comment_only_mutation_is_inert():
    """**对照读数**：只改注释 ⇒ 派生与现值**逐值不变**（证明「变异真的被读到」的另一半）。

    内存构造两份 `UserService.java` 文本：一份在注释里写 A7 的码与一行假的 `getRolePermissions(` 调用
    ⇒ 既有解析器的读数必须**逐值不变**（它先剥注释再取字面量）。这是「改磁盘文件的变异可能不被读到」
    那条教训的正向用法：**先证明探针会被读到，再说「不红」有意义**。
    """
    p = load_parity_guard()
    base = p._source_map()
    real = base["java:service/UserService.java"]
    injected = real.replace(
        "public class UserService implements UserDetailsService {",
        "// 举例（注释，不是声明）：case \"agent\" -> List.of(\"chat:read\");\n"
        "// this.getRolePermissions(\"ghost\");\n"
        "public class UserService implements UserDetailsService {",
        1,
    )
    assert injected != real, "变异注入未生效（锚点失配 ⇒ 本对照是空断言）"
    assert '"chat:read"' in injected, "注入的码不在文本里（自证失败）"

    sources = dict(base)
    sources["java:service/UserService.java"] = injected
    assert present_values(sources=sources, parity=p)["A7"] == present_values(sources=base, parity=p)["A7"], (
        "只改注释却改变了 A7 的读数 ⇒ 解析器把注释读成了声明"
    )
    assert sole_caller_problems(injected) == [], "注释里的假调用被读成了真调用"
    # 同族的另一半：**注释里写这四个码**不得被读成「判定面在读它」（否则判据被自己的说明文字喂红）。
    assert a7_code_hits({
        "backend/admin-api/src/main/java/com/migao/admin/controller/Commented.java":
            '// 说明：这里曾经要求 "chat:read"（已退役）\npublic class Commented {}\n',
        "backend/admin-api/src/main/java/com/migao/admin/controller/Real.java":
            '@RequirePermission("chat:read")\npublic class Real {}\n',
    }, roots=("backend/admin-api/src/main",)) == {
        "backend/admin-api/src/main/java/com/migao/admin/controller/Real.java": ["chat:read"]
    }, "注释里的码被读成了判定面命中（判据被自己的文案喂红）"
    assert authenticate_call_problems({
        "backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java":
            "// 注意：这里**没有** authenticationManager.authenticate(...) 调用\nclass X {}\n"
    }) == [], "注释里提到的 authenticate 被读成了真调用"
