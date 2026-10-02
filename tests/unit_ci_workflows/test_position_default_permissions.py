# case_ids: HR-012
"""岗位默认权限的**逐码期望集**＋**四处真值源逐值一致**的类级元守卫（issue #5979 / #5988）。

## 用户裁定（本判据的唯一理由，2026-10-02，逐条「应允许」）

| 岗位 | 裁定 | 补的码 |
|---|---|---|
| 客服 `customer_service` | 应允许处理售后 | `order:refund` |
| 销售 `sales` | 应允许下单 | `order:create` |
| 财务 `finance` | 应允许读客户列表 | `customer:view` |
| 知识编辑 `knowledge_editor` | 应允许维护知识库 | `knowledge:view` + `knowledge:manage` |

裁定前的实测现象：知识编辑的默认权限 = `[dashboard:view, product:list]`，**不含任何 knowledge 权限**
⇒ 该岗位打开「知识库」被守卫拦下（文案「当前账号缺少权限 knowledge:view」）、调
`/api/admin/knowledge/cards` 得 403 = **岗位做不了本职**（issue #5979）。

## 为什么要有这条判据（病根：同一事实有**四处**真值源）

岗位默认权限不是「写在一处的事实」，它同时在四处各自维护，**任何一处单独改动都不会有东西变红**：

| # | 真值源 | 载体 | 少改它的后果 |
|---|---|---|---|
| ① | **回退 switch** | `backend/admin-api/src/main/java/com/migao/admin/service/RoleService.java` 的 `getPermissionCodesForRole` | 无 `role_permissions` 的历史账号零权限 / 少码 |
| ② | **种子清单** | `rbac/manifest.json` 的 `roles.seed`（声明面，`test_rbac_migration_convergence.py` 守着它） | 新租户拿不到 |
| ③ | **注册种子** | `backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java` 的 `attachDefaultPermissions` | **新租户**拿不到（与 ② 漂移） |
| ④ | **存量迁移** | `backend/admin-api/src/main/resources/db/migration/V145__backfill_position_permissions.sql` | **存量租户**拿不到（「新租户有、老租户没有」） |

🔴 **本判据与既有判据的分工（不要读成覆盖面更大）**：
`sibling` 判据 14（`test_agent_permission_parity.py` 的 `problems_role_default_parity`）判的是
**① ⇄ ③ 逐角色码相等**（两处 Java 集合对齐）；**它判不了值本身对不对**（两处一起写错 ⇒ 它全绿，
其 docstring 边界 ③ 逐字登记了这一点）。本判据补的正是那一半：**期望值逐码点名**（判据 1）
＋ **四处来源逐值一致**（判据 2）。两条判据相交而非重复。

## 三条判据

1. **逐码期望集**：四个岗位的默认码集必须**逐码等于**裁定值（多一个 ⇒ 红：多授 = 放宽；
   少一个 ⇒ 红：岗位做不了本职）。不写「⊆」—— 那会让「漏了本职码」永远绿。
2. **四处真值源逐值一致**：①②③④ 对同一岗位必须给出**同一集合**（穷举，不抽样）。
3. **差分台账只许缩短**：`_KNOWN_SOURCE_DIVERGENCES` 登记**有意**存在的差异；
   新出现的差异必须具名登记，已消失的登记必须删除，条数**现取**上限只许缩短。
   —— 今天为空表、上限 0：四处没有一处应当不同。

## 红证（`test_guard_can_go_red`，全部在内存里注入）

| 注入 | 必须红在哪 |
|---|---|
| 从 `RoleService` 的某个 `case` 删一个码 | 判据 1 / 2 ② |
| 从 `V145` 的某个角色块删一个码 | 判据 2 ④ |
| 只给 `V145` 多授一个码（真放宽） | 判据 2 ④ |
| 往回退里加一个**别处没有**的码 | 判据 2 ② |
| 只改注释（对照） | **不红** |
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PARITY_MODULE = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_agent_permission_parity.py"
#: 迁移链 `role_permissions` 语句解析的**唯一实现**（本文件不写第二个解析器，见 `role_backfill_migration`）
DERIVE_MODULE = REPO_ROOT / "rbac" / "derive.py"

ROLE_SERVICE_REL = "backend/admin-api/src/main/java/com/migao/admin/service/RoleService.java"
REGISTRATION_REL = "backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java"
MANIFEST_REL = "rbac/manifest.json"
#: 存量回填迁移（**无租户过滤 ⇒ 对所有租户生效**，即存量租户一起回填）。
BACKFILL_MIGRATION_REL = "backend/admin-api/src/main/resources/db/migration/V145__backfill_position_permissions.sql"

#: 🔴 **人类裁定值**（2026-10-02，issue #5979 / #5988 逐条「应允许」）。
#: 这是本判据的**唯一**手写真值 —— 只登记「这四个岗位**新增**了什么」，不是全量码表
#: （全量由 `rbac/manifest.json` 承担；此处只钉裁定面，避免把整份岗位矩阵抄成第二份真值）。
EXPECTED_ADDED: dict[str, frozenset[str]] = {
    "customer_service": frozenset({"order:refund"}),
    "sales": frozenset({"order:create"}),
    "finance": frozenset({"customer:view"}),
    "knowledge_editor": frozenset({"knowledge:view", "knowledge:manage"}),
}

#: 🔴 差分台账（**只许缩短**）：四处真值源之间的差异必须逐条具名。
#: 今日为**空表**、上限 0 —— 四处对同一岗位应当逐值相等。
#: 键 = `f"{role}@{source}"`，值 = (缺失的码, 多出的码, 理由)。
_KNOWN_SOURCE_DIVERGENCES: dict[str, tuple[frozenset[str], frozenset[str], str]] = {}
_KNOWN_SOURCE_DIVERGENCE_CEILING = 0

#: 「**增量**真值源」：它们只承担「给**已有**租户/账号补差集」，**不**承担「全量岗位码表」
#: （全量在 ①②③）。⇒ 对它们的判据是「**不得**授权 ①②③ 之外的码」（子集，防真放宽），
#: **不是**逐值相等。键 = 源名，值 = 理由（人读）。
_INCREMENTAL_SOURCES: dict[str, str] = {
    "④ V145 存量回填迁移": (
        "迁移是**增量**：它只补「四个岗位新加的那几个码」，不是这四个岗位的完整码表 —— "
        "逐值相等会把「迁移必须复述整份岗位矩阵」变成第二条真值（正是本单要治的病）"
    ),
}


def _load_module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    assert path.is_file(), f"被复用的模块不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"无法为 {path} 建立加载器（fail-closed）"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _parity():
    return _load_module("migao_position_perms_parity", PARITY_MODULE)


def _derive_module():
    """`rbac/derive.py` —— 迁移链 `role_permissions` 语句的**唯一**解析实现（本文件复用它）。"""
    return _load_module("migao_position_perms_derive", DERIVE_MODULE)


def read_source(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# 四个来源的读取（①②③④）
# ══════════════════════════════════════════════════════════════════════════════


def role_fallback(java_text: str | None = None) -> dict[str, frozenset[str]]:
    """① 回退 switch —— 复用 sibling 的**同一份**解析器（不写第二个实现）。"""
    text = read_source(ROLE_SERVICE_REL) if java_text is None else java_text
    return _parity().parse_role_fallback(text)


def role_seed_java(registration_text: str | None = None) -> dict[str, frozenset[str]]:
    """③ 注册种子（`attachDefaultPermissions`）—— 同上，复用 sibling 的解析器。"""
    text = read_source(REGISTRATION_REL) if registration_text is None else registration_text
    return _parity().parse_role_defaults(text)


def role_seed_manifest(manifest: dict | None = None) -> dict[str, frozenset[str]]:
    """② 清单声明面（`rbac/manifest.json` 的 `roles.seed`）—— `*` 保留为通配。"""
    data = json.loads(read_source(MANIFEST_REL)) if manifest is None else manifest
    seed = data["roles"]["seed"]
    assert seed, "清单 `roles.seed` 为空 ⇒ 判据会空跑（fail-closed）"
    return {role: frozenset(codes) for role, codes in seed.items()}


def role_backfill_migration(sql_text: str | None = None) -> dict[str, frozenset[str]]:
    """④ 存量迁移 —— 每岗位在本次回填里拿到的码（**委托给唯一实现**，本文件不写第二个解析器）。

    🔴 为什么委托（issue #5325 的元守卫逐字要求）：「按引号扫原文取值」的解析**不许新增** ——
    它的假绿形态是「注释/docstring 里写一句看起来像声明的话就喂中」。
    `rbac/derive.py` 的 `parse_role_grants` 是**全仓唯一**的「迁移链 role_permissions 语句」解析实现
    （剥 SQL 注释 + 岗位谓词 / 码谓词，且自带「语句数 == 解析数」的 fail-closed 断言）
    ⇒ 本判据复用它，于是**同一个事实只有一份解析口径**（判据升级时不会与推演漂移）。
    """
    derive = _derive_module()
    text = read_source(BACKFILL_MIGRATION_REL) if sql_text is None else sql_text
    grants = derive.parse_role_grants(145, BACKFILL_MIGRATION_REL, text)
    assert grants, f"`{BACKFILL_MIGRATION_REL}` 解析不出任何 role_permissions 语句（fail-closed）"
    per_role: dict[str, set[str]] = {}
    for grant in grants:
        assert grant.codes is not None, (
            f"`{BACKFILL_MIGRATION_REL}` 里有一条**未显式列码**的授权（`p.code` 谓词缺失）⇒ "
            "本判据只认「逐码点名」的回填（缺码 ⇒ 授权面不可判，fail-closed）"
        )
        assert grant.roles, f"`{BACKFILL_MIGRATION_REL}`: 一条语句解析不出岗位谓词（fail-closed）"
        for role in grant.roles:
            per_role.setdefault(role, set()).update(grant.codes)
    return {role: frozenset(codes) for role, codes in per_role.items()}


# ══════════════════════════════════════════════════════════════════════════════
# 判据（纯函数：输入四份读数，输出问题清单 —— 空 = 绿）
# ══════════════════════════════════════════════════════════════════════════════


def problems_裁定面(reads: dict[str, dict[str, frozenset[str]]]) -> list[str]:
    """判据 1：四个岗位的默认码集必须**含**裁定新增的每一个码（逐码点名）。

    🔴 语义 = 「裁定面 ⊆ 现取」的**逐码**形态，不是集合相等 —— 相等会把整份岗位矩阵
    抄成第二份真值（那正是本单要治的病）。「多授」由判据 2 与 sibling 判据 14 拦。
    """
    out: list[str] = []
    for role, expected in sorted(EXPECTED_ADDED.items()):
        for source, reading in sorted(reads.items()):
            got = reading.get(role)
            if got is None:
                out.append(f"真值源 `{source}` 里**没有岗位 `{role}`** ⇒ 该岗位在它上面零权限（裁定码无法生效）")
                continue
            missing = sorted(expected - got)
            if missing:
                out.append(
                    f"岗位 `{role}` 在真值源 `{source}` 上**缺裁定新增的码** {missing} ⇒ "
                    "该岗位做不了本职（issue #5979 / #5988 的原始形态）"
                )
    return out


def problems_四处逐值一致(reads: dict[str, dict[str, frozenset[str]]]) -> list[str]:
    """判据 2：全量源（①②③）对同一岗位**逐值相等**；增量源（④）**不得授全量源之外的码**。"""
    out: list[str] = []
    roles = sorted({role for reading in reads.values() for role in reading})
    full = sorted(s for s in reads if s not in _INCREMENTAL_SOURCES)

    for role in roles:
        # ── ① 全量源之间：逐值相等 ──
        present = {s: reads[s][role] for s in full if role in reads[s]}
        if len(present) >= 2 and not any("*" in codes for codes in present.values()):
            base_source = min(present, key=full.index)
            base = present[base_source]
            for source in sorted(present):
                if source == base_source:
                    continue
                missing = sorted(base - present[source])
                extra = sorted(present[source] - base)
                if not missing and not extra:
                    continue
                key = f"{role}@{source}"
                entry = _KNOWN_SOURCE_DIVERGENCES.get(key)
                if entry is None:
                    out.append(
                        f"岗位 `{role}` 在真值源 `{source}` 与 `{base_source}` 之间**不一致**："
                        f"缺 {missing} / 多 {extra} ⇒ 同一岗位「新租户」与「存量租户 / 历史账号」行为不同"
                        "。要么对齐，要么在 `_KNOWN_SOURCE_DIVERGENCES` 里具名登记（差异集 + 理由）"
                    )
                elif entry[0] != frozenset(missing) or entry[1] != frozenset(extra):
                    out.append(
                        f"`_KNOWN_SOURCE_DIVERGENCES['{key}']` 登记的差异与**现取**不符："
                        f"缺 登记 {sorted(entry[0])} / 现取 {missing}；多 登记 {sorted(entry[1])} / 现取 {extra}"
                        " ⇒ 同步登记（差异集逐值冻结）"
                    )

        # ── ② 增量源：**不得**授全量源之外的码（子集；真放宽当场红） ──
        for source in sorted(_INCREMENTAL_SOURCES):
            got = reads[source].get(role)
            if got is None:
                continue
            allowed = frozenset().union(*present.values()) if present else frozenset()
            extra = sorted(got - allowed)
            if extra:
                key = f"{role}@{source}"
                entry = _KNOWN_SOURCE_DIVERGENCES.get(key)
                if entry is None:
                    out.append(
                        f"岗位 `{role}` 在**增量**真值源 `{source}` 里多出全量源没有的码 {extra} ⇒ "
                        "**真放宽**（迁移绕过岗位权限页给租户加权限）。本判据**不给这条登记出口**："
                        f"增量源只能是全量源的子集（{_INCREMENTAL_SOURCES[source]}）"
                    )
                elif entry[1] != frozenset(extra):
                    out.append(
                        f"`_KNOWN_SOURCE_DIVERGENCES['{key}']` 的多授登记 {sorted(entry[1])} 与现取 {extra} 不符"
                    )

    for key in sorted(set(_KNOWN_SOURCE_DIVERGENCES) - {f"{role}@{s}" for role in roles for s in reads}):
        out.append(f"`_KNOWN_SOURCE_DIVERGENCES['{key}']` 已**不再有差异** ⇒ 删掉它（台账只许缩短）")
    if len(_KNOWN_SOURCE_DIVERGENCES) > _KNOWN_SOURCE_DIVERGENCE_CEILING:
        out.append(
            f"差分台账又长回来了：{len(_KNOWN_SOURCE_DIVERGENCES)} 条 > 上限 "
            f"{_KNOWN_SOURCE_DIVERGENCE_CEILING} ⇒ 新增差异不是「登记一下」就能过关的"
        )
    return out


def all_reads() -> dict[str, dict[str, frozenset[str]]]:
    """四处真值源的现取读数（①②③④）。"""
    return {
        "① RoleService 回退 switch": role_fallback(),
        "② rbac/manifest.json roles.seed": role_seed_manifest(),
        "③ RegistrationService 种子": role_seed_java(),
        "④ V145 存量回填迁移": role_backfill_migration(),
    }


def all_problems(reads: dict[str, dict[str, frozenset[str]]]) -> list[str]:
    return problems_裁定面(reads) + problems_四处逐值一致(reads)


# ══════════════════════════════════════════════════════════════════════════════
# 断言
# ══════════════════════════════════════════════════════════════════════════════


def test_position_default_permissions_are_green_on_the_current_tree():
    """现取四处真值源：裁定面逐码在、四处逐值一致（红 = 岗位做不了本职 / 已漂移）。"""
    problems = all_problems(all_reads())
    assert problems == [], "岗位默认权限判据未通过：\n" + "\n".join(f"  - {p}" for p in problems)


def test_guard_can_go_red():
    """注入式红证：四种坏形态**各自**判红 + 一条「只改注释 ⇒ 不红」的对照读数。"""
    base = all_reads()
    assert all_problems(base) == [], "前提：当前树必须全绿（否则红证分不清是注入还是真是红的）"

    # ① 从回退 switch 的**客服** case 删一个码 ⇒ 判据 1 与判据 2 同时红
    import re as _re

    java = read_source(ROLE_SERVICE_REL)
    anchor = '"dashboard:view", "order:list", "order:detail", "customer:view", "agent:session",'
    assert anchor in java, "注入锚点失配（RoleService 的客服 case 变了）—— 同步本判据"
    injected = java.replace(anchor, '"dashboard:view", "order:list", "order:detail", "customer:view",', 1)
    assert injected != java, "变异注入未生效（自证失败）"
    reads = dict(base)
    reads["① RoleService 回退 switch"] = role_fallback(injected)
    hits = all_problems(reads)
    assert any("customer_service" in h and "agent:session" in h for h in hits), f"回退删码没被判红：{hits}"

    # ② 从 V145 的客服块删一个码 ⇒ 判据 1 必须红（裁定码在**存量侧**消失）
    sql = read_source(BACKFILL_MIGRATION_REL)
    assert "'order:refund'" in sql, "注入锚点失配（V145 里没有 order:refund）—— 同步本判据"
    reads = dict(base)
    reads["④ V145 存量回填迁移"] = role_backfill_migration(sql.replace("'order:refund'", "'order:detail'", 1))
    hits = all_problems(reads)
    assert any("customer_service" in h and "order:refund" in h and "V145" in h for h in hits), (
        f"V145 少授没被判红：{hits}"
    )

    # ③ 只给 V145 多授一个码（真放宽）⇒ 判据 2 的**增量源子集**段必须红
    reads = dict(base)
    reads["④ V145 存量回填迁移"] = role_backfill_migration(
        sql.replace("'order:refund'", "'order:refund', 'system:manage'", 1)
    )
    hits = all_problems(reads)
    assert any("customer_service" in h and "system:manage" in h for h in hits), f"V145 多授没被判红：{hits}"

    # ④ 往回退 switch 的**客服** case 加一个**别处没有**的码 ⇒ 判据 2 必须红（真放宽）
    reads = dict(base)
    reads["① RoleService 回退 switch"] = role_fallback(
        _re.sub(
            r'(case "customer_service" -> List\.of\(.*?)\n(\s*\);)',
            r'\1\n                    "ghost:code"\n\2',
            java,
            count=1,
            flags=_re.S,
        )
    )
    hits = all_problems(reads)
    assert any("customer_service" in h and "ghost:code" in h for h in hits), f"回退多授没被判红：{hits}"

    # ⑤ 对照：只改注释 ⇒ 一条都不红（判据读的是语义，不是文件变没变）
    reads = dict(base)
    reads["① RoleService 回退 switch"] = role_fallback(java.replace("//", "// 只改注释 ", 1))
    assert all_problems(reads) == [], "只改注释竟判红 ⇒ 判据在读文本而不是在读语义"
