# case_ids: MC-043, MC-044
"""RBAC 单一真值源 **P5 + P6**：存量的迁移链收敛 + 两个历史岗位码的正式定义（跟踪单 issue #5699）。

设计真值源 = `docs/design/rbac-single-source.md` 的 §4（P5 行 / P6 行）、§2.7（迁移路径）、§2.6（幽灵角色三出口）。
本文件判两件事，**都判「结构」，不判「现值对不对」**：

## P5（`MC-043`）：存量租户的内置岗位权限**收敛到清单**

- **产物新鲜度**：`backend/admin-api/src/main/resources/db/migration/V136__converge_builtin_role_permissions.sql`
  是 `rbac/generate_migration.py` 由清单**渲染**的生成物 ⇒ 手改、或改清单没重渲染 ⇒ 红（M3）。
- **收敛不变量**：把**整条迁移链**（V29…V138）推演一遍后，每个内置岗位累计拿到的码 **== 清单声明的码集**
  （`*` 展开成目录全集）⇒ 「新租户（Java seed）与存量租户（迁移链）逐值相等」这条验收口径**由判据常驻**。
- **差集是现取**：`V136` 的**内容**必须逐字等于「清单声明 − V136 之前的链累计」这个当场算出来的差集
  （现取 = `admin` 的 11 个码；其余四个岗位 ∅）—— 手写一张清单之外的码表 ⇒ 红。

## P6（`MC-044`）：`product_manager` / `knowledge_editor` **正式定义**（人类 2026-09-27 裁定：出口 (i)）

- 两个角色码必须**在种子矩阵里**（`RegistrationService` 建 roles 行 + 授默认码），且 **seed == fallback 逐值**
  （两条口径同时成立由本判据与 `test_agent_permission_parity.py` 判据 14 一起守）。
- 存量租户由 `V137__formalize_legacy_roles.sql` 建 `roles` 行并授权 ⇒ 判据核对**该迁移的语句与清单逐值相符**。
- 收口后 `LEGACY_ROLES_IN_FALLBACK` **必须是空表**（销账）：两个角色不再是「种子外的历史角色」，
  留着一张不空的表 = 留两套真相。

## inspector（issue #5652，本文件新增）：质检员岗位的**收敛 + 存量迁移**

- **收敛不变量**（`convergence_problems`，**本单之前它是红的**）：`inspector` 的**链累计**码集必须
  **逐值等于**清单 `roles.seed.inspector`（= `production:view` + **新写码** `production:inspect` ——
  后者**只**授给本岗位，见下节「为什么不是复用 `production:execute`」）
  ⇒ 「新租户（Java seed）与存量租户（迁移链）逐值相等」这条口径对新岗位同样常驻可判。
- **存量迁移逐值**（`inspector_migration_problems`）：`V158__create_inspector_role.sql` 的建行语句 +
  授权语句 + 终态对账的 `(岗位, 码)` 清单，三者都必须与**活清单**逐值相等
  （多授 = 绕过岗位权限页的放宽；少授 = 存量租户拿不到）。
- **渲染输入**：`V136` / `V137` 是**已发布**迁移 ⇒ 输入钉在发布时刻的清单快照（改活清单**不**动它们）；
  `V157` **尚未发布** ⇒ 输入 = **活清单**（清单前进即须重渲染）。两个方向都有红证
  （`test_live_artifacts_follow_the_live_manifest` 证其「跟着活清单走」；
  `test_frozen_artifacts_do_not_follow_the_live_manifest` 证已发布产物「不跟着漂」）。

## 红证（每条断言都有，且都在内存里构造）

| 断言 | 变异 | 命中分支 |
|---|---|---|
| 生成物新鲜度（V136 / **V157**，参数化两例） | 手工往产物里塞一个字 / 改清单不重渲染 | `freshness_problems` 的 `!=` 分支 |
| 收敛不变量 | 给清单某岗位**加一个链上没有的码** | `convergence_problems` 的 `missing` 分支（具名报出该码） |
| 差集是现取 | 同上（差集随之变化 ⇒ 与固定读数不符） | `census_problems` 的逐值比较分支 |
| P6 seed == fallback | 从清单 seed 里删掉一个角色 | `p6_problems` 的「不在种子里」分支 |
| P6 迁移语句逐值 | 把 V137 的授权语句改掉一个码 | `p6_migration_problems` 的差集分支 |
| **V157 授权语句逐值**（issue #5652） | 把 V157 的 `p.code IN (…)` 改掉一个码 | `inspector_migration_problems` 的逐值比较分支 |
| **活清单 vs 冻结快照的边界**（issue #5652） | 改清单 `roles.seed.inspector` 的一个码 | 活产物**必须**跟着变（`live_artifacts_follow`）；已发布产物**必须**不变（`frozen_artifacts_drift`） |
| 只改散文 ⇒ 不红（对照） | 只改清单 `_note` | 三条判据都必须不红 |

**覆盖面边界（照实登记）**：本判据算的是**声明面推演**，不是真库读数（设计 §6.1）；
推演规则与边界逐条写在 `rbac/derive.py` 的 P5 段（只认约定 SQL 形态、不推演懒补种、不推演取消授权）。
"""
from __future__ import annotations

import copy
import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RBAC_DIR = REPO_ROOT / "rbac"
MANIFEST_PATH = RBAC_DIR / "manifest.json"
GENERATOR_PATH = RBAC_DIR / "generate_migration.py"
DERIVE_PATH = RBAC_DIR / "derive.py"
PARITY_GUARD = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_agent_permission_parity.py"

#: P5 的**固定读数**（渲染时刻的现取差集）—— 改它必须同时改 `V136` 并说明为什么。
P5_EXPECTED_DIFF: dict[str, tuple[str, ...]] = {
    "admin": (
        "after_sales:view", "agent:session:manage", "customer:create", "finance:create",
        "inbound:create", "inbound:view", "knowledge:view", "order:create", "order:update",
        "processing:update", "processing:view",
    ),
    # issue #5979 / #5988（人类 2026-10-02 裁定「应允许」）：三个岗位各补一个本职码，
    # 声明面（`roles.seed`）前进 ⇒ **现取差集随之变化**（本读数就是那条「差集是现取」的读数：
    # 它变了不是 bug，而是声明改了 —— 同步它是本判据的**必须动作**）。
    # 消解去向：`V136` 由同一份清单渲染（`rbac/generate_migration.py`）⇒ 三个岗位的授权语句
    # 已同批出现在 `V136` 里，**存量租户由 V136 + V145 双保险回填**（两处都 `ON CONFLICT DO NOTHING`）。
    # `knowledge_editor` 不在 P5 射程（它不是「五个原有内置岗位」之一）⇒ 仍为空。
    "customer_service": ("order:refund",),
    "finance": ("customer:view",),
    "operator": (),
    "sales": ("order:create",),
}

#: P6 正式定义的两个角色码（**逐值取自回退 switch**，见设计 §2.6 的现取事实表）。
P6_ROLES = ("knowledge_editor", "product_manager")


def _load(mod_name: str, path: Path):
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    assert path.is_file(), f"被复用的模块不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec and spec.loader, f"无法为 {path} 建立加载器（fail-closed）"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_derive():
    return _load("migao_rbac_derive_p5", DERIVE_PATH)


def load_generator():
    return _load("migao_rbac_generate_migration_p5", GENERATOR_PATH)


def load_parity_guard():
    return _load("migao_rbac_parity_p5", PARITY_GUARD)


def load_manifest() -> dict:
    return load_derive().load_manifest(MANIFEST_PATH)


# ══════════════════════════════════════════════════════════════════════════════
# 判据（纯函数：喂清单 / 源文本 / 链文件，返回问题清单 ⇒ 注入式红证就是喂改过的输入）
# ══════════════════════════════════════════════════════════════════════════════


def freshness_problems(committed: str | None, rendered: str, rel: str) -> list[str]:
    """M3：产物必须与**当场渲染**逐字节相同（手改生成物 / 改清单没重渲染 ⇒ 红）。"""
    if committed is None:
        return [f"`{rel}` 不存在 ⇒ 生成物缺失（跑 `python3 rbac/generate_migration.py`）"]
    if committed != rendered:
        first = next(
            (i for i, (a, b) in enumerate(zip(committed.splitlines(), rendered.splitlines())) if a != b),
            min(len(committed.splitlines()), len(rendered.splitlines())),
        )
        return [
            f"`{rel}` 与当场渲染不一致（首个差异在第 {first + 1} 行）⇒ "
            "手改生成物 = 红；出口：跑 `python3 rbac/generate_migration.py` 重新渲染"
        ]
    return []


def convergence_problems(manifest: dict, root: Path | None = None) -> list[str]:
    """P5 的**收敛不变量**：整条链推演后，每个种子岗位累计 == 清单声明（`*` ⇒ 目录全集）。"""
    derive = load_derive()
    chain = derive.chain_state(manifest, root)
    catalog = set(chain["catalog"])
    state = {role: set(codes) for role, codes in chain["state"].items()}
    out: list[str] = []
    for role, declared in sorted(manifest["roles"]["seed"].items()):
        expected = set(derive.expand_role_codes(manifest, declared))
        actual = state.get(role, set()) & catalog
        missing, extra = sorted(expected - actual), sorted(actual - expected)
        if missing:
            out.append(
                f"岗位 `{role}`：清单声明里有、**迁移链累计没有**的码 {missing} ⇒ "
                "存量租户拿不到它们（「新租户有、老租户没有」的原形态）—— 补一条由生成器渲染的收敛迁移"
            )
        if extra:
            out.append(
                f"岗位 `{role}`：链累计里有、清单声明里没有的码 {extra} ⇒ "
                "链比声明更宽（要么声明漏了，要么链多授了 —— 两者都必须显式裁定）"
            )
    return out


def census_problems(manifest: dict, root: Path | None = None, expected: dict | None = None) -> list[str]:
    """P5 的**差集读数**必须是现取：`V136 之前` 的链累计 vs 声明，逐岗位逐值对固定读数。"""
    derive = load_derive()
    generator = load_generator()
    diff = derive.convergence_diff(
        manifest, root, upto=generator.P5_VERSION - 1, skip_introduced_after=generator.P5_VERSION
    )
    expected = P5_EXPECTED_DIFF if expected is None else expected
    out: list[str] = []
    for role, want in sorted(expected.items()):
        got = tuple(diff["roles"][role]["missing"])
        if got != tuple(want):
            out.append(
                f"岗位 `{role}` 的 P5 差集读数变了：现取 {list(got)} / 固定读数 {list(want)} ⇒ "
                "差集是现取（不是手抄）—— 要么链上多了/少了授权，要么有人手改了本读数"
            )
    return out


def p6_problems(manifest: dict, parity) -> list[str]:
    """P6（出口 i）：两个角色码在种子里、与回退**逐值相等**，且历史角色台账**已销账**。"""
    derive = load_derive()
    out: list[str] = []
    for role in P6_ROLES:
        if role not in manifest["roles"]["seed"]:
            out.append(
                f"P6 出口 (i)（正式定义）：`{role}` 不在清单 `roles.seed` 里 ⇒ "
                "它仍是「只活在回退 switch 里的幽灵角色码」（岗位权限页无法编辑、员工弹窗无法分配）"
            )
            continue
        seed = sorted(derive.expand_role_codes(manifest, manifest["roles"]["seed"][role]))
        fallback = sorted(manifest["roles"]["fallback"].get(role) or [])
        if not fallback:
            out.append(f"`{role}` 在回退 switch 里没有 `case` ⇒ 回退路径上的账号零权限（收窄，须人裁）")
        elif seed != fallback:
            out.append(
                f"`{role}` 的 seed 与 fallback **不逐值相等**：seed={seed} / fallback={fallback} ⇒ "
                "正式定义后两条口径必须同码（差异须具名登记 + 只许缩短）"
            )
    if parity.LEGACY_ROLES_IN_FALLBACK:
        out.append(
            f"`LEGACY_ROLES_IN_FALLBACK` 未销账（现取 {sorted(parity.LEGACY_ROLES_IN_FALLBACK)} 条）⇒ "
            "P6 出口 (i) 之后两个角色已在种子矩阵里，留着空转的登记 = 两套真相"
        )
    return out


def p6_migration_problems(manifest: dict, text: str | None) -> list[str]:
    """P6 的存量迁移必须**逐值**等于**它发布时刻的清单快照**（少一个码 / 多一个码都红）。

    🔴 **`manifest` 入参已不使用（issue #5979 / #5988 改判）**——`V137` 是**已发布**迁移
    ⇒ `Danger Scan` 判「已发布迁移不可重写」，它的内容**不得**随活清单前进而变形。
    生成器把它的渲染输入钉在 `rbac/manifest-published-at-V137.json`（`FROZEN_SNAPSHOTS`）上，
    本判据**读同一份快照**做逐值比较，于是「P6 的内容 ≡ 它自己发布时刻的声明」这条不变量**照旧成立**。

    🔴 **改判后本判据的射程变了（如实登记，别读成覆盖面更大）**：它**不再**判「活清单声明 == V137」。
    那一半（含清单之后新增的 `knowledge:view` / `knowledge:manage` 等）由**同一文件的**
    `convergence_problems`（链累计 == 活清单声明，逐岗位逐码具名）承担 —— 两条判据合起来
    才等价于改判前的射程，**任何一条单独都不完整**。
    """
    derive = load_derive()
    generator = load_generator()
    # 与生成器 render_p6 **同源**：同一份冻结快照（避免两处各写一个「发布时刻」口径）
    manifest = generator.load_frozen_snapshot(f"V{generator.P6_VERSION}")
    rel = next(r for r in generator.ARTIFACTS if "formalize_legacy_roles" in r)
    if text is None:
        return [f"`{rel}` 不存在 ⇒ P6 的存量侧没有物化（新租户有、老租户没有）"]
    out: list[str] = []
    for role in P6_ROLES:
        declared = sorted(derive.expand_role_codes(manifest, manifest["roles"]["seed"][role]))
        # 迁移里的授权语句：`r.code = '<role>'` + `p.code IN (...)`
        needle_role = f"r.code = '{role}'"
        if needle_role not in text:
            out.append(f"`{rel}` 里没有 `{role}` 的授权语句 ⇒ 存量租户拿不到它的默认码")
            continue
        block = text[text.index(needle_role):]
        block = block[: block.index("ON CONFLICT")]
        found = sorted(set(re.findall(r"'([a-z_]+:[a-z_:]+)'", block)))
        if sorted(declared) != found:
            missing = [code for code in declared if code not in found]
            extra = [code for code in found if code not in declared]
            out.append(
                f"`{rel}` 的 `{role}` 授权语句与清单声明**不逐值相等**：漏 {missing} / 多 {extra} ⇒ "
                "（多授 = 绕过岗位权限页的放宽；少授 = 存量租户拿不到）"
            )
        if f"'{role}'" not in text:
            out.append(f"`{rel}` 里没有建 `roles` 行（找不到 `'{role}'`）⇒ 岗位权限页仍然看不到它")
    return out


def _extract_grant_codes(text: str, role: str) -> list[str]:
    """从一段迁移文本里取**某个岗位**授权语句的 `p.code IN (…)` 码集（升序去重）。

    口径 = `p6_migration_problems` 的同一段切片（`r.code = '<role>'` … `ON CONFLICT`），
    本函数只是把它抽出来给 `inspector_migration_problems` **复用**（不写第二套正则）。
    """
    needle = f"r.code = '{role}'"
    start = text.index(needle)
    block = text[start:]
    block = block[: block.index("ON CONFLICT")]
    return sorted(set(re.findall(r"'([a-z_]+:[a-z_:]+)'", block)))


def inspector_migration_problems(manifest: dict, text: str | None) -> list[str]:
    """issue #5652：`V157` 的建行 / 授权 / 终态对账三处必须**逐值**等于**活清单**的 `inspector`。

    🔴 与 `p6_migration_problems` 的**有意差异**：`V137` 已发布 ⇒ 比的是**发布时刻快照**；
    `V157` **尚未发布** ⇒ 比的是**活清单**（清单前进即须重渲染，否则本判据判红）。
    """
    derive = load_derive()
    generator = load_generator()
    role = generator.INSPECTOR_CODE
    rel = next(r for r in generator.ARTIFACTS if "create_inspector_role" in r)
    if text is None:
        return [f"`{rel}` 不存在 ⇒ 质检员岗位的存量侧没有物化（新租户有、老租户没有）"]
    declared = sorted(derive.expand_role_codes(manifest, manifest["roles"]["seed"][role]))
    out: list[str] = []
    if f"r.code = '{role}'" not in text:
        out.append(f"`{rel}` 里没有 `{role}` 的授权语句 ⇒ 存量租户拿不到它的默认码")
    if f"code = '{role}'" not in text:
        out.append(f"`{rel}` 里没有建 `roles` 行（找不到 code = '{role}'）⇒ 岗位权限页看不到它")
    if f"r.code = '{role}'" in text:
        found = _extract_grant_codes(text, role)
        if found != declared:
            out.append(
                f"`{rel}` 的 `{role}` 授权语句与**活清单**声明不逐值相等："
                f"漏 {sorted(set(declared) - set(found))} / 多 {sorted(set(found) - set(declared))} ⇒ "
                "（多授 = 绕过岗位权限页的放宽；少授 = 存量租户拿不到）"
            )
    # 终态对账块里的 `(岗位, 码)` 清单必须与授权语句**同一份值**（两处各写一份 ⇒ 必然漂移）。
    # 🔴 只在**对账块的 `VALUES` 段**里取（从 `SELECT COUNT(*) INTO missing_links` 起、到
    #    `AS want(role_code, perm_code)` 止）—— 文件头的回滚注释与授权语句里各有一处同名值，
    #    全局子串检索会读到它们（实测：会被回滚注释喂中 ⇒ 漏报，不会假红）。
    ledger = _extract_ledger_pairs(text)
    for code in declared:
        if (role, code) not in ledger:
            out.append(f"`{rel}` 的终态对账块里缺 `('{role}', '{code}')` ⇒ 对账判不到这一对")
    return out


def _extract_ledger_pairs(text: str) -> set[tuple[str, str]]:
    """取**终态对账块**里 `(岗位, 码)` 的 `VALUES` 清单（只认那一段，不看散文 / 授权语句）。"""
    marker = "SELECT COUNT(*) INTO missing_links"
    assert marker in text, "对账块锚点失配（迁移形态变了）⇒ 无法判定，fail-closed"
    block = text[text.index(marker):]
    end = "AS want(role_code, perm_code)"
    assert end in block, "对账块 `VALUES` 的收尾锚点失配（fail-closed）"
    block = block[: block.index(end)]
    return set(re.findall(r"\('([a-z_]+)', '([a-z_:]+)'\)", block))


def all_problems(manifest: dict, root: Path | None = None, parity=None) -> list[str]:
    """三条判据的合流（红证/对照都走这一条入口）。"""
    derive, generator, parity = load_derive(), load_generator(), parity or load_parity_guard()
    out: list[str] = []
    rendered = generator.render_all(manifest)
    for rel, text in rendered.items():
        path = (root or REPO_ROOT) / rel
        out += freshness_problems(path.read_text(encoding="utf-8") if path.is_file() else None, text, rel)
    out += convergence_problems(manifest, root)
    out += census_problems(manifest, root)
    out += p6_problems(manifest, parity)
    rel_p6 = next(r for r in generator.ARTIFACTS if "formalize_legacy_roles" in r)
    p6_path = (root or REPO_ROOT) / rel_p6
    out += p6_migration_problems(manifest, p6_path.read_text(encoding="utf-8") if p6_path.is_file() else None)
    # issue #5652：质检员 `inspector` 的存量迁移（V157）也必须与活清单逐值相符
    rel_v157 = next(r for r in generator.ARTIFACTS if "create_inspector_role" in r)
    v157_path = (root or REPO_ROOT) / rel_v157
    out += inspector_migration_problems(
        manifest, v157_path.read_text(encoding="utf-8") if v157_path.is_file() else None
    )
    del derive
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 断言（正例 + 红证 + 对照）
# ══════════════════════════════════════════════════════════════════════════════


def test_p5_p6_invariants_are_green_on_the_current_tree():
    problems = all_problems(load_manifest())
    assert problems == [], "P5/P6 判据未通过：\n" + "\n".join(f"  - {p}" for p in problems)


def test_hand_edited_migration_is_red():
    """红证：手改生成物一个字 ⇒ 新鲜度判据必须红（命中 `freshness_problems` 的逐字节分支）。"""
    generator, manifest = load_generator(), load_manifest()
    rendered = generator.render_all(manifest)
    rel = next(r for r in generator.ARTIFACTS if "converge_builtin_role_permissions" in r)
    assert freshness_problems(rendered[rel], rendered[rel], rel) == [], "前提：原样 ⇒ 不红"
    tampered = rendered[rel].replace("BEGIN;", "BEGIN; -- 手改一个字", 1)
    assert tampered != rendered[rel], "变异注入未生效（自证失败）"
    problems = freshness_problems(tampered, rendered[rel], rel)
    assert any("与当场渲染不一致" in p for p in problems), f"手改生成物没被判红：{problems}"


def test_a_code_declared_but_missing_on_the_chain_is_red():
    """红证：清单声明里加一个**链上没有**的码 ⇒ 收敛不变量必须**具名**报出（`missing` 分支）。"""
    derive, manifest = load_derive(), load_manifest()
    mutated = copy.deepcopy(manifest)
    mutated["roles"]["seed"]["sales"] = sorted(mutated["roles"]["seed"]["sales"] + ["system:manage"])
    problems = convergence_problems(mutated)
    assert any("`sales`" in p and "system:manage" in p for p in problems), (
        f"声明了链上没有的码却没被判红：{problems}"
    )
    assert convergence_problems(manifest) == [], "对照组：现取清单必须全绿"
    del derive


def test_diff_census_is_recomputed_not_handwritten():
    """差集的固定读数必须是**现取**：改一处链上授权（等价于改清单声明）⇒ 读数变化即红。"""
    manifest = load_manifest()
    assert census_problems(manifest) == [], "前提：现取差集 == 固定读数"
    mutated = copy.deepcopy(manifest)
    mutated["roles"]["seed"]["finance"] = sorted(mutated["roles"]["seed"]["finance"] + ["employee:create"])
    problems = census_problems(mutated)
    assert any("`finance`" in p and "employee:create" in p for p in problems), (
        f"差集读数与现取不符却没被判红：{problems}"
    )


def test_p6_formal_definition_is_load_bearing():
    """P6 红证：把角色从种子里删掉 / 让目录里的授权语句少一个码 ⇒ 必须红。"""
    generator, manifest, parity = load_generator(), load_manifest(), load_parity_guard()
    assert p6_problems(manifest, parity) == [], "前提：现取清单 + 判据侧台账必须全绿"
    mutated = copy.deepcopy(manifest)
    mutated["roles"]["seed"].pop("knowledge_editor")
    problems = p6_problems(mutated, parity)
    assert any("knowledge_editor" in p and "不在清单 `roles.seed` 里" in p for p in problems), (
        f"角色从种子矩阵消失却没被判红：{problems}"
    )
    rel = next(r for r in generator.ARTIFACTS if "formalize_legacy_roles" in r)
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    tampered = text.replace("'product:list'", "'product:list', 'order:list'", 1)
    assert tampered != text
    problems = p6_migration_problems(manifest, tampered)
    assert any("不逐值相等" in p and "order:list" in p for p in problems), f"迁移多授一个码没被判红：{problems}"
    # 台账销账是**承载字段**：把它塞回一条 ⇒ 必须红
    saved = dict(parity.LEGACY_ROLES_IN_FALLBACK)
    try:
        parity.LEGACY_ROLES_IN_FALLBACK["product_manager"] = "夹具：塞回一条"
        problems = p6_problems(manifest, parity)
        assert any("未销账" in p for p in problems), f"台账未销账没被判红：{problems}"
    finally:
        parity.LEGACY_ROLES_IN_FALLBACK.clear()
        parity.LEGACY_ROLES_IN_FALLBACK.update(saved)


def test_comment_only_change_is_not_red():
    """**对照读数**：只改清单的散文（`_note`）⇒ 三条判据都不红（判的是语义，不是文件变没变）。"""
    manifest = load_manifest()
    prose = copy.deepcopy(manifest)
    prose["_note"] = str(prose["_note"]) + "（只改散文的一句）"
    assert prose != manifest, "散文变异注入未生效（自证失败）"
    assert all_problems(prose) == [], "只改散文竟判红 ⇒ 判据在读文本而不是在读语义"


def test_inspector_role_is_covered_by_the_chain_and_its_migration():
    """issue #5652：质检员 `inspector` 的**链累计 == 清单声明**，且 `V157` 三处与清单逐值相符。"""
    manifest = load_manifest()
    role = load_generator().INSPECTOR_CODE
    assert role in manifest["roles"]["seed"], "质检员必须已在清单 `roles.seed` 里（否则判据空跑）"
    # ① 收敛不变量：把整条链推演一遍，质检员的累计码 == 清单声明（本单之前这里是红的）
    diff = load_derive().convergence_diff(manifest)["roles"][role]
    assert diff["missing"] == [], f"质检员的链累计缺码 {diff['missing']} ⇒ 存量租户拿不到（红）"
    assert diff["extra"] == [], f"质检员的链累计多码 {diff['extra']} ⇒ 链比声明更宽（红）"
    assert diff["chain"] == diff["declared"] == ["production:inspect", "production:view"]
    # ② 存量迁移逐值：V157 的授权语句 + 终态对账清单 + 建行语句
    rel = next(r for r in load_generator().ARTIFACTS if "create_inspector_role" in r)
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert inspector_migration_problems(manifest, text) == [], "V157 与活清单不符（红）"


def test_inspector_migration_red_proofs():
    """红证（issue #5652）：`V157` 少一个码 / 多一个码 / 终态对账缺一对 ⇒ 各自具名判红。"""
    manifest = load_manifest()
    generator = load_generator()
    rel = next(r for r in generator.ARTIFACTS if "create_inspector_role" in r)
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert inspector_migration_problems(manifest, text) == [], "前提：现取产物必须全绿"

    only_view = _extract_grant_codes(text, generator.INSPECTOR_CODE)
    assert len(only_view) == 2, f"前提：质检员必须恰好两个码（现取 {only_view}）"

    # ① 少授一个码（`production:view` 从授权语句里删掉；终态对账块仍留着它）
    tampered = text.replace("'production:inspect', 'production:view'", "'production:inspect'", 1)
    assert tampered != text, "变异注入未生效（自证失败）"
    problems = inspector_migration_problems(manifest, tampered)
    assert any("不逐值相等" in p and "production:view" in p for p in problems), (
        f"授权少一个码没被判红：{problems}"
    )

    # ② 多授一个码（真放宽：清单里没有的码）
    widened = text.replace("'production:inspect', 'production:view'",
                           "'production:inspect', 'production:view', 'system:manage'", 1)
    assert widened != text, "变异注入未生效（自证失败）"
    problems = inspector_migration_problems(manifest, widened)
    assert any("不逐值相等" in p and "system:manage" in p for p in problems), (
        f"授权多一个码没被判红：{problems}"
    )

    # ③ 终态对账块里删掉一对 ⇒ 判据必须报「对账块里缺」（**只动对账块**，授权语句保持原样 ⇒
    #    不会先命中「授权语句不逐值相等」那条 ⇒ 这一条断言判的确实是「对账块」）。
    #    锚点 = 该缩进形态**唯一**指向对账块 `VALUES` 的那一行（文件头的回滚注释行以 `));` 收尾，不匹配）。
    ledger_line = "        ('inspector', 'production:view')\n"
    assert text.count(ledger_line) == 1, f"注入锚点失配（出现 {text.count(ledger_line)} 次，期望 1）"
    dropped = text.replace(ledger_line, "", 1)
    assert dropped != text, "变异注入未生效（自证失败）"
    assert _extract_grant_codes(dropped, load_generator().INSPECTOR_CODE) == [
        "production:inspect", "production:view",
    ], "前提：授权语句必须**原样**（本注入只动对账块）"
    problems = inspector_migration_problems(manifest, dropped)
    assert any("终态对账块里缺" in p and "production:view" in p for p in problems), (
        f"终态对账缺一对没被判红：{problems}"
    )


def test_live_artifacts_follow_the_live_manifest():
    """红证（issue #5652）：改清单 `roles.seed.inspector` 的一个码 ⇒ **活清单产物（V157）必须跟着变**。

    这是「V157 的渲染输入 = 活清单」的正面读数 —— 若有人把它也钉进 `FROZEN_SNAPSHOTS`，本判据判红。
    """
    generator, manifest = load_generator(), load_manifest()
    role = generator.INSPECTOR_CODE
    rel_live = next(r for r in generator.ARTIFACTS if "create_inspector_role" in r)
    mutated = copy.deepcopy(manifest)
    mutated["roles"]["seed"][role] = sorted(set(mutated["roles"]["seed"][role]) | {"order:list"})
    mutated["roles"]["fallback"][role] = sorted(set(mutated["roles"]["fallback"][role]) | {"order:list"})
    assert generator.render_all(mutated)[rel_live] != generator.render_all(manifest)[rel_live], (
        "改了活清单而 V157 未变 ⇒ 它被钉成了冻结产物（本单要求它跟着活清单走）"
    )


def test_frozen_artifacts_do_not_follow_the_live_manifest():
    """对照（issue #5652）：同一处活清单变异 ⇒ **已发布**产物（V136 / V137）**不得**跟着变。"""
    generator, manifest = load_generator(), load_manifest()
    role = generator.INSPECTOR_CODE
    mutated = copy.deepcopy(manifest)
    mutated["roles"]["seed"][role] = sorted(set(mutated["roles"]["seed"][role]) | {"order:list"})
    mutated["roles"]["fallback"][role] = sorted(set(mutated["roles"]["fallback"][role]) | {"order:list"})
    before, after = generator.render_all(manifest), generator.render_all(mutated)
    for rel in (r for r in generator.ARTIFACTS if r != next(
        a for a in generator.ARTIFACTS if "create_inspector_role" in a
    )):
        assert before[rel] == after[rel], (
            f"`{rel}` 跟着活清单漂了 ⇒ 已发布迁移被重写（Danger Scan 的 blocker）"
        )
