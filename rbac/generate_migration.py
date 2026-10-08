# case_ids: MC-043, MC-044, MC-045
"""RBAC 迁移的**单一生成器**（跟踪单 issue #5699 的 P5 / P6 / I4；机制 = 设计真值源 §5.2 的 **M3**）。

本文件由 `rbac/manifest.json`（声明）＋迁移链推演（`rbac/derive.py` 的 P5 段）**渲染**三份**已落盘**的迁移：

| 产物 | 阶段 | 内容（值全部来自清单，散文来自本文件的模板） |
|---|---|---|
| `db/migration/V136__converge_builtin_role_permissions.sql` | **P5** | 把「清单声明里有、迁移链上没给」的 `(岗位, 码)` 逐条幂等补齐（现取差集 = admin 的 11 码）+ 终态对账 `DO` 块 |
| `db/migration/V137__formalize_legacy_roles.sql` | **P6（出口 i）** | `product_manager` / `knowledge_editor` **正式定义**：建 `roles` 行 + 按清单授权 + 终态对账 |
| `db/migration/V138__add_production_execute_permission.sql` | **I4** | 新写码 `production:execute`：目录行 + 授予今日持 `order:list` 的四个岗位 + **快照等价回填**（谓词逐字见文件头）+ 终态对账 |

## 为什么是「生成器 + 新鲜度判据」（而不是手写迁移）

🔴 用户的裁定逐字：「**不要打补丁了**」「给存量 `admin` 补 11 行的幂等迁移会**再增加一处需要维护的真值**」。
⇒ 迁移**不许**成为第二份手写事实：它的**值**（岗位、码、名单）一律由清单渲染 ⇒ 手改产物必红
（`test_generated_migrations_are_fresh`），清单改了没重渲染也必红。

## 用法（两条命令，与 `generate_readings.py` 同款）

```
python3 rbac/generate_migration.py            # 重新渲染三份迁移（改完清单后跑）
python3 rbac/generate_migration.py --check    # 只读：产物 vs 当场渲染，非零退出 = 陈旧（CI 同款口径）
```

## 边界（照实登记，**不是**「已覆盖」）

① **散文在模板里，值在清单里** —— 判据只保证「值没漂」，不保证「散文说对了」（散文的正确性靠评审）；
② 渲染**不读库**：差集由迁移链推演（`derive.convergence_diff`），推演的边界逐条写在 `rbac/derive.py` 的 P5 段；
③ V138 的**快照回填谓词**是模板里的常量（`order:list` → `production:execute`）：它由
   `tests/unit_ci_workflows/test_rbac_endpoint_write_codes.py` 的 I4 台账**逐字**对账（台账改了这个不改 ⇒ 红）；
④ 本生成器**不改** Java 侧（种子矩阵 / 回退 switch / 注解）：那些是 co-located 真值（设计 §2.2），
   由各自的判据守着。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "db" / "migration"

DERIVE_MODULE = "migao_rbac_derive_for_migration"


def load_derive():
    """加载派生器（`rbac/derive.py`；**同一份实现**给生成器与判据共用，本文件不复制它的推演逻辑）。"""
    mod = sys.modules.get(DERIVE_MODULE)
    if mod is not None:
        return mod
    path = REPO_ROOT / "rbac" / "derive.py"
    assert path.is_file(), f"派生器不存在：{path}（路径漂移 ⇒ 红）"
    spec = importlib.util.spec_from_file_location(DERIVE_MODULE, path)
    assert spec and spec.loader, f"无法为 {path} 建立加载器（fail-closed）"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[DERIVE_MODULE] = mod
    spec.loader.exec_module(mod)
    return mod


# ── 三份产物的常量（版本号 / 文件名 / I4 的码与端点）──────────────────────────────────────────────
P5_VERSION = 136
P6_VERSION = 137
I4_VERSION = 138

#: P5 的收敛射程 = **五个原有内置岗位**（`product_manager` / `knowledge_editor` 由 V137 自己建行授权）。
P5_ROLES = ("admin", "customer_service", "finance", "operator", "sales")

#: P6 正式定义的两个历史岗位码（值取自清单 `roles.seed`；名字取自 `frontend/bmini-app` 的角色名映射）。
P6_ROLES = {
    "product_manager": ("商品管理员", "商品与加工项管理（POC 期历史岗位，issue #5699 的 P6 正式定义）"),
    "knowledge_editor": ("知识编辑", "知识库编辑（POC 期历史岗位，issue #5699 的 P6 正式定义）"),
}

#: I4：新写码 + 它把守的四个**真写**端点 + 改前守卫的**读**码 + 今日能过它们的岗位。
I4_CODE = "production:execute"
I4_CODE_NAME = "生产执行"
I4_CODE_DESC = "建加工单/报工/打任务卡/发货"
I4_OLD_CODE = "order:list"
I4_ENDPOINTS = (
    "POST /api/admin/production/orders/{}/instantiate",
    "POST /api/admin/production/orders/{}/operations/{}/report",
    "POST /api/admin/production/orders/{}/print",
    "POST /api/admin/production/orders/{}/ship",
)
I4_ROLES = ("customer_service", "operator", "sales", "finance")

#: V138 的**授权名单** = 今日持旧读码的四个岗位 **+ `admin`**：`admin` 运行时恒 `["*"]`（不靠这行生效），
#: 但**岗位权限页的回填**读的是 `role_permissions` ⇒ 不补行的话「存量租户管理员岗位缺新码」这个
#: P5 刚治好的一格会在新码上原样复发（与 V129 / V132 对 admin 的同款处理逐字同因）。
I4_GRANT_ROLES = ("admin",) + I4_ROLES

#: 快照列的原值形态（`AdminUserController` 用 `OBJECT_MAPPER.writeValueAsString(list)` 写）：
#: **紧凑 JSON 字符串数组**。谓词取严格形态 ⇒ 保证 `::jsonb` 不会在脏数据上炸（见 V138 文件头）。
_SNAPSHOT_JSON_ARRAY = r"^\[(\"[^\"]*\")(,\"[^\"]*\")*\]$"


def _sql_list(codes) -> str:
    return ", ".join(f"'{c}'" for c in codes)


def _grant_stmt(role_predicate: str, codes) -> str:
    """一条幂等授权语句（形态与 V43/V111/V124/V125/V129/V132 逐字同款）。"""
    return (
        "INSERT INTO role_permissions (id, tenant_id, role_id, permission_id, created_at, deleted)\n"
        "SELECT gen_random_uuid()::text, r.tenant_id, r.id, p.id, NOW(), 0\n"
        "FROM roles r\n"
        "JOIN permissions p ON p.tenant_id = r.tenant_id\n"
        f"WHERE {role_predicate} AND r.deleted = 0\n"
        f"  AND p.code IN ({_sql_list(codes)})\n"
        "ON CONFLICT (role_id, permission_id) DO NOTHING;"
    )


def _ledger_rows(pairs) -> str:
    """SQL 里的 `(VALUES …)` 行（多行、**仅供 SQL 语句内部**使用）。"""
    return ",\n        ".join(f"('{role}', '{code}')" for role, code in pairs)


def _comment_rows(pairs) -> str:
    """**注释里**引用的同一份 `(role, code)` 清单：逐行带 `--` 前缀。

    🔴 为什么必须单独一个函数：`_ledger_rows` 返回**多行**字符串 —— 直接塞进注释块会让
    只有第一行是注释、其余行变成**裸 SQL** ⇒ 整份迁移 `BadSqlGrammarException`
    （实测：`语法错误 在 "'admin'" 或附近的`；`MigrationRunnerLiveChainRealDbTest` 当场抓到）。
    """
    return ",\n".join(f"--        ('{role}', '{code}')" for role, code in pairs)


# ══════════════════════════════════════════════════════════════════════════════
# 一、P5：存量租户的内置岗位权限收敛到清单
# ══════════════════════════════════════════════════════════════════════════════


#: 🔴 **已发布迁移的冻结清单快照**（issue #5979 / #5988 引入）。
#:
#: `V136` / `V137` **已经跑在所有环境上** ⇒ 它们受两条**同等强制**的约束，且二者在「清单前进」时冲突：
#:   ① `Danger Scan (破坏性变更检测)`：**已发布迁移不可重写**（重渲染 = 改已应用的迁移 ⇒ blocker）；
#:   ② 本生成器的新鲜度判据：产物必须 == 当场渲染（否则判红 ⇒ 落 main 后每个 PR 都会红）。
#: ⇒ 消解方式 = **把这两份产物的渲染输入钉在它们发布时刻的清单上** —— 它们从此是**历史事实的产物**，
#: 不再随 `rbac/manifest.json` 前进而变形。**清单之后新增的授权由新迁移（V145）承担**，
#: 收敛不变量（`convergence_problems`：链累计 == 清单声明）仍用**活清单**判 ⇒ 两条约束同时成立。
#: 两份快照**今日逐字节相同**（同一个发布时刻），但**有意分开命名**：将来清单再前进时，
#: 各产物各自的发布日期不同 ⇒ 共享一份会重新引入「改 A 变形 B」的同一个病。
#: 🔴 **快照一旦写出即历史，永不修改**；新情形 = **新增**一份快照文件名。
FROZEN_SNAPSHOTS: dict[str, Path] = {
    f"V{P5_VERSION}": REPO_ROOT / "rbac" / "manifest-published-at-V136.json",
    f"V{P6_VERSION}": REPO_ROOT / "rbac" / "manifest-published-at-V137.json",
}


def load_frozen_snapshot(version: str) -> dict:
    """读某份**已发布**迁移的冻结清单快照（缺文件 ⇒ 抛错，fail-closed，不静默回落到活清单）。"""
    path = FROZEN_SNAPSHOTS[version]
    assert path.is_file(), (
        f"{version} 的冻结清单快照不存在：{path}（路径漂移 ⇒ 红，不得静默回落到活清单）"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def p5_missing(manifest: dict, root: Path | None = None) -> dict[str, list[str]]:
    """P5 的**差集**（清单声明 − **V136 之前**的迁移链累计），只取 P5 射程内的五个岗位。"""
    derive = load_derive()
    diff = derive.convergence_diff(
        manifest, root, upto=P5_VERSION - 1, skip_introduced_after=P5_VERSION
    )
    out: dict[str, list[str]] = {}
    for role in P5_ROLES:
        entry = diff["roles"][role]
        out[role] = list(entry["missing"])
    return {role: codes for role, codes in out.items() if codes}


def render_p5(manifest: dict, root: Path | None = None) -> str:
    """渲染 `V136`（**已发布 ⇒ 输入钉在发布时刻的清单快照上**，见 `FROZEN_SNAPSHOTS`）。

    `manifest` 入参**有意不使用**（保留形参只为与 `ARTIFACTS` 的 `{rel: renderer}` 同形）。
    改活清单**不会**改动本产物 —— 这正是「已发布迁移不可重写」与「生成物必须新鲜」的消解点。
    """
    manifest = load_frozen_snapshot(f"V{P5_VERSION}")
    missing = p5_missing(manifest, root)
    pairs = [(role, code) for role, codes in sorted(missing.items()) for code in codes]
    assert pairs, "P5 的差集为空 ⇒ 这份迁移没有内容可渲染（清单与链已收敛时应当删掉本产物，而不是渲染空文件）"
    body = "\n\n".join(
        f"-- ── {role}：链上缺 {len(codes)} 个码 ──\n" + _grant_stmt(f"r.code = '{role}'", codes)
        for role, codes in sorted(missing.items())
    )
    listed = "".join(f"--   · `{role}` ← " + "、".join(f"`{c}`" for c in codes) + "\n" for role, codes in sorted(missing.items()))
    return f"""-- 存量租户内置岗位的权限收敛到清单（issue #5699 的 **P5**；设计真值源 `docs/design/rbac-single-source.md` §4 的 P5 行 / §2.7）
--
-- ## 一句话
--   把「**清单声明里有、迁移链上没给**」的 `(岗位, 码)` **逐条幂等补齐** ——
--   收敛「存量租户的 `role_permissions` = 该租户历史跑过的迁移之并集」这条**路径依赖**。
--
-- ## 🔴 本文件是**生成物**，不是手写真值（用户裁定逐字：「不要打补丁了」）
--   文件头与语句的**值**全部由 `rbac/generate_migration.py` 从 `rbac/manifest.json` + 迁移链推演渲染：
--   `python3 rbac/generate_migration.py`（手改本文件 ⇒ `rbac` 判据判红；清单改了没重渲染 ⇒ 亦判红）。
--   ⇒ 「存量岗位该有哪些码」这件事**仍然只有一处真值**（清单），迁移只是它的一次**物化**（设计 §2.7）。
--
-- ## 现取差集（渲染时刻的读数，由推演给出而不是手抄）
{listed}--   逐角色逐码读数（可复算）：
--   `python3 -c "import sys;sys.path.insert(0,'rbac');import derive,json;print(derive.convergence_diff(derive.load_manifest()))"`
--
-- ## 为什么需要一条迁移（只改 Java 不够）
--   新租户走 `RegistrationService.initializeDefaultRolesAndPermissions` 全量 seed；存量租户的
--   **目录**由 `PermissionService.ensureFullPermissionCatalog` 懒补种，而 **`role_permissions`
--   没有任何 Java 路径会给既有岗位补码** ⇒ 上面这批 `(岗位, 码)` 在老租户上**永久缺失**
--   （`V43`/`V111`/`V124`/`V125` 四条迁移引入新码时都**没给** `admin` 授码，实测 `grep -c "r.code = 'admin'"`
--   对这四个文件 = 0 —— 这就是本迁移要治的存量差距，见设计 §3.1）。
--   **运行时零影响**（`RoleService.getUserPermissions` 对 `admin` 首行短路返回 `["*"]`），
--   受影响的是**岗位权限页的回填**与**员工弹窗按岗位预填**（UI 可见、授权面可见）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · 每条语句都是 `INSERT … SELECT … WHERE NOT EXISTS` 形态的**授权补齐**，
--     冲突由唯一索引 `uq_role_permissions (role_id, permission_id)` 兜住：`ON CONFLICT … DO NOTHING`；
--   · 本文件**只 INSERT**，不改/不删任何既有行 ⇒ 第二遍的每条语句都是 0 行，结果与第一遍相同。
--
-- ## 停止条件（fail-closed）
--   终态对账（文末 `DO` 块）：每个**已有权限目录**的租户里，上表每一对 `(岗位, 码)` 都必须有
--   `role_permissions` 行；缺任何一对 ⇒ `RAISE EXCEPTION` 并回滚本迁移（不硬推）。
--
-- ## 显式事务（同 V97 / V102 / V107 / V108 / V111 / V124 的实测口径）
--   `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条 autocommit**
--   ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。两条执行路径必须同语义。
--
-- ## 回滚（**新迁移，不删本文件**）
--   ```sql
--   -- V136__rollback.sql（本单只登记，不落码）：只删本迁移**补出来**的那些行
--   DELETE FROM role_permissions rp USING roles r, permissions p
--    WHERE rp.role_id = r.id AND rp.permission_id = p.id
--      AND (r.code, p.code) IN (VALUES
{_comment_rows(pairs)});
--   ```
--   **回滚是收窄**：会把管理员岗位在这批码上的勾选一并删掉（岗位权限页的勾选与岗位默认权限同表）⇒
--   属**有意**（宁可回到「缺码」，也不要留下指向不存在权限的悬空授权）。
--
-- ## bootstrap 终态（如实登记）
--   `backend/admin-api/src/main/resources/db/init/schema.sql`（新建库路径**不跑迁移链**）
--   不含任何 `role_permissions` 种子行（`INSERT INTO role_permissions` 在该文件 **0 命中**）⇒ 本迁移无需同步它。

BEGIN;

{body}

-- ══════════════════════════════════════════════════════════════════════════════════════
-- 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「差集没补齐」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    scoped_tenants INTEGER;
    missing_links  INTEGER;
BEGIN
    -- 射程 = 「已有权限目录」的租户（不以 tenants 为全集：尚未初始化的租户不在本迁移射程内，同 V124 口径）
    SELECT COUNT(*) INTO scoped_tenants
      FROM tenants t WHERE EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id);
    IF scoped_tenants = 0 THEN
        RAISE NOTICE 'V{P5_VERSION}：没有任何租户持有权限目录 ⇒ 本迁移为空操作（全新库）';
    END IF;

    SELECT COUNT(*) INTO missing_links
      FROM tenants t
      JOIN roles r ON r.tenant_id = t.id AND r.deleted = 0
      JOIN permissions p ON p.tenant_id = t.id
      JOIN (VALUES
        {_ledger_rows(pairs)}
      ) AS want(role_code, perm_code) ON want.role_code = r.code AND want.perm_code = p.code
     WHERE NOT EXISTS (
            SELECT 1 FROM role_permissions rp
             WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.deleted = 0
       );
    IF missing_links > 0 THEN
        RAISE EXCEPTION 'V{P5_VERSION} 终态对账失败：仍有 % 对 (岗位, 码) 没有 role_permissions 行 —— 回滚本迁移', missing_links;
    END IF;
    RAISE NOTICE 'V{P5_VERSION} 终态对账通过：存量内置岗位的清单差集已补齐（射程内租户 % 个）', scoped_tenants;
END $$;

COMMIT;
"""


# ══════════════════════════════════════════════════════════════════════════════
# 二、P6（出口 i）：两个历史岗位码正式定义
# ══════════════════════════════════════════════════════════════════════════════


def p6_codes(manifest: dict, role: str) -> list[str]:
    declared = manifest["roles"]["seed"][role]
    derive = load_derive()
    return sorted(derive.expand_role_codes(manifest, declared))


def render_p6(manifest: dict) -> str:
    """渲染 `V137`（**已发布 ⇒ 输入钉在发布时刻的清单快照上**，见 `FROZEN_SNAPSHOTS`；同 `render_p5`）。"""
    manifest = load_frozen_snapshot(f"V{P6_VERSION}")
    for role in P6_ROLES:
        assert role in manifest["roles"]["seed"], f"P6 的出口 (i) 要求 `{role}` 进种子矩阵（现取缺失 ⇒ 不渲染）"
        fallback = manifest["roles"]["fallback"].get(role)
        assert fallback is not None and sorted(fallback) == p6_codes(manifest, role), (
            f"`{role}` 的种子与回退**必须逐值相等**（P6 出口 i 的收口判据）："
            f"seed={p6_codes(manifest, role)} fallback={sorted(fallback or [])}"
        )
    rows = "\n\n".join(
        f"""-- ── {role}（{P6_ROLES[role][0]}）：{len(p6_codes(manifest, role))} 个码 ──
INSERT INTO roles (id, tenant_id, name, code, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '{P6_ROLES[role][0]}', '{role}', '{P6_ROLES[role][1]}', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND r.code = '{role}' AND r.deleted = 0);

{_grant_stmt(f"r.code = '{role}'", p6_codes(manifest, role))}"""
        for role in sorted(P6_ROLES)
    )
    want_rows = ",\n        ".join(
        f"('{role}', '{code}')" for role in sorted(P6_ROLES) for code in p6_codes(manifest, role)
    )
    return f"""-- 两个历史岗位码的**正式定义**（issue #5699 的 **P6**，出口 (i)；设计真值源 §2.6 / §4 的 P6 行）
--
-- ## 一句话
--   `product_manager`（商品管理员）/ `knowledge_editor`（知识编辑）此前**不是岗位**：
--   不在种子里、迁移链一条谓词都不提（⇒ **没有 `roles` 行**）、岗位权限页**无法编辑**，
--   只靠 `RoleService.getPermissionCodesForRole` 的 `switch` 一行 `case` 拿 {len(p6_codes(manifest, "product_manager"))} / {len(p6_codes(manifest, "knowledge_editor"))} 个码。
--   本迁移把它们**正式定义**为岗位：**建 `roles` 行**（幂等）＋**按清单授权**（幂等）＋终态对账。
--
-- ## 🔴 为什么账号的**有效权限集合逐值不变**（本迁移的兼容性判据）
--   两个角色码的默认码集**一字未改**（值取自清单 `roles.seed`，与 `roles.fallback` **逐值相等**，
--   由 `rbac` 判据与 `test_agent_permission_parity.py` 判据 14 同时守着）⇒
--   · 走**回退路径**（无 `role_permissions` 记录）的账号：仍然是同一批码；
--   · 走 **`role_permissions` 路径**（本迁移之后）：拿到的是**同一批码**。
--   ⇒ 差别只在**可管理性**（岗位权限页首次能编辑它们）与**可分配性**（员工弹窗首次能选它们）——
--   两者都是产品面变化，归 P6 的人类裁定（2026-09-27 已裁定出口 (i)）。
--
-- ## 幂等（`MigrationRunner` 硬要求）
--   · `roles`：`WHERE NOT EXISTS (同租户同 code 有效行)`（与 V29/V32 的既有写法同款）；
--   · `role_permissions`：`ON CONFLICT (role_id, permission_id) DO NOTHING`；
--   · 只 INSERT，不改/不删既有行 ⇒ 第二遍 0 行。
--
-- ## 停止条件（fail-closed）
--   终态对账：每个**已有权限目录**的租户里，两个岗位码都必须有 `roles` 行，且清单里的每一对
--   `(岗位, 码)` 都必须有 `role_permissions` 行；否则 `RAISE EXCEPTION`。
--
-- ## 边界（照实登记）
--   ① 本迁移**不**回填 `users.permissions` 快照（设计 §2.9：快照是最终权限，回填 = 静默改授权）——
--      但两角色的码集未变 ⇒ 快照面**本来就不需要**回填；
--   ② 黄金策 `allowed_roles`（`backend/ai-agent-service/app/agents/agents/mibao.py`）与 bmini 角色名映射
--      （`frontend/bmini-app/src/pages/profile/index/index.tsx`）引用的是**角色名**：正式定义后仍逐字成立
--      （读数见 PR body），本迁移**不**动它们。

BEGIN;

{rows}

-- ══════════════════════════════════════════════════════════════════════════════════════
-- 终态对账（缺角色行 / 缺授权行 ⇒ 回滚，不硬推）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing_roles INTEGER;
    missing_links INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_roles
      FROM tenants t
      CROSS JOIN (VALUES ('{sorted(P6_ROLES)[0]}'), ('{sorted(P6_ROLES)[1]}')) AS want(role_code)
     WHERE NOT EXISTS (
            SELECT 1 FROM roles r
             WHERE r.tenant_id = t.id AND r.code = want.role_code AND r.deleted = 0
       );
    IF missing_roles > 0 THEN
        RAISE EXCEPTION 'V{P6_VERSION} 终态对账失败：% 个历史岗位码没有 roles 行 —— 回滚本迁移', missing_roles;
    END IF;

    SELECT COUNT(*) INTO missing_links
      FROM tenants t
      JOIN roles r ON r.tenant_id = t.id AND r.deleted = 0
      JOIN permissions p ON p.tenant_id = t.id
      JOIN (VALUES
        {want_rows}
      ) AS want(role_code, perm_code) ON want.role_code = r.code AND want.perm_code = p.code
     WHERE NOT EXISTS (
            SELECT 1 FROM role_permissions rp
             WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.deleted = 0
       );
    IF missing_links > 0 THEN
        RAISE EXCEPTION 'V{P6_VERSION} 终态对账失败：仍有 % 对 (岗位, 码) 没有 role_permissions 行 —— 回滚本迁移', missing_links;
    END IF;
    RAISE NOTICE 'V{P6_VERSION} 终态对账通过：两个历史岗位码已正式定义（roles 行 + 授权）';
END $$;

COMMIT;
"""


# ══════════════════════════════════════════════════════════════════════════════
# 三、I4：新写码 `production:execute` + 快照等价回填
# ══════════════════════════════════════════════════════════════════════════════


def render_i4(manifest: dict) -> str:
    catalog = manifest["codes"]["registration"]
    assert I4_CODE in catalog, f"`{I4_CODE}` 必须在清单目录里（现取缺失 ⇒ 不渲染）"
    assert I4_CODE_NAME == manifest["codes"]["names"][I4_CODE], "码名与清单 `codes.names` 不一致（值只有一处真值）"
    for role in I4_ROLES:
        assert I4_CODE in manifest["roles"]["seed"][role], f"`{I4_CODE}` 必须已授给 `{role}`（清单 seed）"
        assert I4_CODE in manifest["roles"]["fallback"][role], f"`{I4_CODE}` 必须已授给 `{role}`（清单 fallback）"
    endpoints = "\n".join(f"--   · `{e}`" for e in I4_ENDPOINTS)
    return f"""-- 新写码 `{I4_CODE}`（issue #5699 的 **I4**；设计真值源 §3.4 问题 2 / §4 的 P4 行）
--
-- ## 一句话
--   四个**真写**端点此前**只由读码 `{I4_OLD_CODE}` 把守**（`ProductionController` 的类级注解）：
{endpoints}
--   ⇒ 现在改挂**写码** `{I4_CODE}`（注解改动在 `ProductionController`，本迁移只补**存量数据面**）：
--   ① 目录里加 `{I4_CODE}`；② 授予**今日持 `{I4_OLD_CODE}` 的四个岗位**（`admin` 恒 `*`，无需补行）；
--   ③ **快照等价回填**（见下节）。
--
-- ## 🔴 为什么 (2) 是「自洽」而不是「放宽」
--   改前这四个端点的**生效码**就是四个人人可读的 `{I4_OLD_CODE}`（它授给 `admin` · 客服 · 运营 · 销售 · 财务）
--   ⇒ 这四岗**今天就能**建加工单 / 报工 / 打任务卡 / 发货。改挂写码后若不补授权，它们会**当场 403**
--   （现场停线）⇒ 补授权 = 让**有效权限集合逐值不变**；新码**只把守这 4 个端点**（别处一律不挂）
--   ⇒ 不存在「多开了哪扇门」。逐端点的「改前能过 / 改后能过」读数见 PR body 与
--   `tests/unit_ci_workflows/test_rbac_endpoint_write_codes.py` 的 I4 台账。
--
-- ## 🔴 快照等价回填（设计 §2.9 的**具名窄例外**，逐字条件见下）
--   `RoleService.getUserPermissions` 对**有 `users.permissions` 快照**的账号**提前返回快照**
--   ⇒ 只补 `role_permissions` **不够**：快照里没有新码的账号照样 403。回填的**谓词**必须**逐字**是：
--     ① 快照是**严格 JSON 字符串数组**（`AdminUserController` 的 `writeValueAsString(list)` 形态）；
--     ② 含**旧守卫码** `"{I4_OLD_CODE}"`（该账号今天本来就过得了这 4 个端点）；
--     ③ 不含新码（幂等）。
--   **不含旧码的账号一个字节都不动**（它今天也过不去 ⇒ 不补 = 不放宽）。
--   ⇒ 有效权限集合**逐值不变**：这不是「给更多人开门」，是「守卫码改名时把有效集合钉住」。
--   ⚠️ 这条是 §2.9「不回填快照」的**窄例外**（理由 / 谓词 / 边界 / 判据见设计 §2.9 的同批补记），
--   **不是**放宽该原则：例外只覆盖「旧码在场」的快照，且迁移末尾有 fail-closed 断言**证明**没有越界。
--
-- ## 只读的事前 / 事后核对 SQL（接上真库后人工复核用；本迁移**不**执行它们）
--   ```sql
--   -- 事前：受影响的账号数（快照含旧码、不含新码）—— 本机无真库 ⇒ 报告里必须写「未知 + 本 SQL」
--   SELECT COUNT(*) FROM users
--    WHERE permissions LIKE '%"{I4_OLD_CODE}"%' AND permissions NOT LIKE '%"{I4_CODE}"%';
--   -- 事前：按岗位分布（受影响面到底是哪些岗位）
--   SELECT role, COUNT(*) FROM users
--    WHERE permissions LIKE '%"{I4_OLD_CODE}"%' AND permissions NOT LIKE '%"{I4_CODE}"%' GROUP BY role ORDER BY 2 DESC;
--   -- 事后：应当逐值等于事前（每行 +1 个码，行数不变）；且**没有任何**行是「有新码、无旧码」
--   SELECT COUNT(*) FROM users WHERE permissions LIKE '%"{I4_CODE}"%';
--   SELECT COUNT(*) FROM users
--    WHERE permissions LIKE '%"{I4_CODE}"%' AND permissions NOT LIKE '%"{I4_OLD_CODE}"%';   -- 必须 = 0
--   ```
--
-- ## 幂等（`MigrationRunner` 硬要求）
--   · `permissions`：`WHERE NOT EXISTS (同租户同码)`；
--   · `role_permissions`：`ON CONFLICT (role_id, permission_id) DO NOTHING`；
--   · 快照 `UPDATE`：带**「不含新码」谓词** ⇒ 第二遍匹配 0 行；
--   · 只 INSERT + 一条定值 `UPDATE`，不删任何行 ⇒ 第二遍结果与第一遍相同。
--
-- ## 停止条件（fail-closed）
--   终态对账（文末 `DO` 块）：① 每个已有权限目录的租户都有 `{I4_CODE}` 行；
--   ② 四个岗位对它的 `role_permissions` 链接齐备；③ **没有**任何快照「有新码、无旧码」（越界即回滚）。
--
-- ## bootstrap 终态（如实登记）
--   `backend/admin-api/src/main/resources/db/init/schema.sql` 不含 `permissions` 种子行
--   （`INSERT INTO permissions` 在该文件 **0 命中**）⇒ 本迁移无需同步它；新库的目录由 Java seed 产出。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 权限目录：一个新**写**码（同租户同码已存在即跳过）
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '{I4_CODE_NAME}', '{I4_CODE}', 'production', 'execute', '{I4_CODE_DESC}', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = '{I4_CODE}');

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 岗位授权：今日持 `{I4_OLD_CODE}` 的四个岗位（有效权限集合逐值不变）
-- ══════════════════════════════════════════════════════════════════════════════════════
{_grant_stmt("r.code IN (" + _sql_list(I4_GRANT_ROLES) + ")", [I4_CODE])}

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 快照等价回填：**只**动「含旧码、不含新码」的严格 JSON 数组快照（逐字条件见文件头）
-- ══════════════════════════════════════════════════════════════════════════════════════
UPDATE users
   SET permissions = (permissions::jsonb || '["{I4_CODE}"]'::jsonb)::text
 WHERE permissions ~ '{_SNAPSHOT_JSON_ARRAY}'
   AND permissions LIKE '%"{I4_OLD_CODE}"%'
   AND permissions NOT LIKE '%"{I4_CODE}"%';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- 终态对账（缺目录行 / 缺授权行 / **快照越界** ⇒ 回滚，不硬推）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing_codes INTEGER;
    missing_links INTEGER;
    widened      INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_codes
      FROM tenants t
     WHERE EXISTS (SELECT 1 FROM permissions p0 WHERE p0.tenant_id = t.id)
       AND NOT EXISTS (SELECT 1 FROM permissions p WHERE p.tenant_id = t.id AND p.code = '{I4_CODE}');
    IF missing_codes > 0 THEN
        RAISE EXCEPTION 'V{I4_VERSION} 终态对账失败：% 个租户缺 {I4_CODE} 目录行 —— 回滚本迁移', missing_codes;
    END IF;

    SELECT COUNT(*) INTO missing_links
      FROM tenants t
      JOIN roles r ON r.tenant_id = t.id AND r.deleted = 0
      JOIN permissions p ON p.tenant_id = t.id AND p.code = '{I4_CODE}'
      JOIN (VALUES ('customer_service'), ('operator'), ('sales'), ('finance')) AS want(role_code)
        ON want.role_code = r.code
     WHERE NOT EXISTS (
            SELECT 1 FROM role_permissions rp
             WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.deleted = 0
       );
    IF missing_links > 0 THEN
        RAISE EXCEPTION 'V{I4_VERSION} 终态对账失败：% 个岗位没有 {I4_CODE} 授权行 —— 回滚本迁移', missing_links;
    END IF;

    SELECT COUNT(*) INTO widened
      FROM users
     WHERE permissions LIKE '%"{I4_CODE}"%' AND permissions NOT LIKE '%"{I4_OLD_CODE}"%';
    IF widened > 0 THEN
        RAISE EXCEPTION 'V{I4_VERSION} 终态对账失败：% 个快照「有新码、无旧码」= 越界放宽 —— 回滚本迁移', widened;
    END IF;
    RAISE NOTICE 'V{I4_VERSION} 终态对账通过：写码目录 + 岗位授权 + 快照等价回填齐备';
END $$;

COMMIT;
"""


# ══════════════════════════════════════════════════════════════════════════════
# 四、入口
# ══════════════════════════════════════════════════════════════════════════════

#: `{产物路径: 渲染函数}` —— 顺序即文件名顺序（`--check` 的输出顺序稳定）。
ARTIFACTS = {
    f"backend/admin-api/src/main/resources/db/migration/V{P5_VERSION}__converge_builtin_role_permissions.sql": render_p5,
    f"backend/admin-api/src/main/resources/db/migration/V{P6_VERSION}__formalize_legacy_roles.sql": render_p6,
    f"backend/admin-api/src/main/resources/db/migration/V{I4_VERSION}__add_production_execute_permission.sql": render_i4,
}


def render_all(manifest: dict | None = None) -> dict[str, str]:
    """渲染三份迁移（纯函数；注入式红证 = 喂改过的清单）。"""
    derive = load_derive()
    manifest = manifest if manifest is not None else derive.load_manifest()
    return {rel: renderer(manifest) for rel, renderer in ARTIFACTS.items()}


def main(argv: list[str]) -> int:
    check = "--check" in argv
    artifacts = render_all()
    problems: list[str] = []
    for rel, text in artifacts.items():
        path = REPO_ROOT / rel
        if check:
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current != text:
                problems.append(
                    f"{rel}: {'文件不存在' if current is None else '内容与当场渲染不一致'}"
                    " ⇒ 跑 `python3 rbac/generate_migration.py` 重新渲染（手改生成物 = 红）"
                )
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {rel}")
    if problems:
        print("\n".join(problems))
        return 1
    if check:
        print(f"OK：{len(artifacts)} 份迁移与当场渲染逐字节相同")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
