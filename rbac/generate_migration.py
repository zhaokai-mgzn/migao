# case_ids: MC-043, MC-044, MC-045
"""RBAC 迁移的**单一生成器**（跟踪单 issue #5699 的 P5 / P6 / I4；机制 = 设计真值源 §5.2 的 **M3**）。

本文件由 `rbac/manifest.json`（声明）＋迁移链推演（`rbac/derive.py` 的 P5 段）**渲染**五份**已落盘**的迁移：

| 产物 | 阶段 | 内容（值全部来自清单，散文来自本文件的模板） |
|---|---|---|
| `db/migration/V136__converge_builtin_role_permissions.sql` | **P5** | 把「清单声明里有、迁移链上没给」的 `(岗位, 码)` 逐条幂等补齐（现取差集 = admin 的 11 码）+ 终态对账 `DO` 块 |
| `db/migration/V137__formalize_legacy_roles.sql` | **P6（出口 i）** | `product_manager` / `knowledge_editor` **正式定义**：建 `roles` 行 + 按清单授权 + 终态对账 |
| `db/migration/V138__add_production_execute_permission.sql` | **I4** | 新写码 `production:execute`：目录行 + 授予今日持 `order:list` 的四个岗位 + **快照等价回填**（谓词逐字见文件头）+ 终态对账 |
| `db/migration/V158__create_inspector_role.sql` | **#5652** | 新岗位 `inspector`（质检员）**正式定义**：建 `roles` 行 + 按清单授权（`production:view` / `production:inspect`）+ 终态对账 |
| `db/migration/V161__refresh_default_role_descriptions.sql` | **#7111** | 8 个内置岗位的**描述**刷新成「职责 + 默认可用模块」（值 = 清单 `roles.descriptions`）：**只改仍是旧默认文案的行**（商家自定义一律不动）+ 终态对账 |
| `db/migration/V162__strip_default_role_module_lists.sql` | **#7146** | 内置岗位描述**去掉「默认可用模块」散文**（模块清单改为派生：一份权限码 → 后台 + 手机端）；谓词 = V161 写下的文案（商家自定义一律不动）+ 终态对账 |

🔴 **两份「渲染输入从哪来」是有意不同的**：`V136` / `V137` **已发布** ⇒ 输入钉在发布时刻的清单快照
（`FROZEN_SNAPSHOTS`，活清单前进**不**动它们）；`V138` / `V158` 的对应关系由各自的发布时点决定，
`V158` 尚未发布 ⇒ 输入 = **活清单**（清单前进即重渲染，手改产物即判红）。

## 为什么是「生成器 + 新鲜度判据」（而不是手写迁移）

🔴 用户的裁定逐字：「**不要打补丁了**」「给存量 `admin` 补 11 行的幂等迁移会**再增加一处需要维护的真值**」。
⇒ 迁移**不许**成为第二份手写事实：它的**值**（岗位、码、名单）一律由清单渲染 ⇒ 手改产物必红
（`test_generated_migrations_are_fresh`），清单改了没重渲染也必红。

## 用法（两条命令，与 `generate_readings.py` 同款）

```
python3 rbac/generate_migration.py            # 重新渲染五份迁移（改完清单后跑）
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


# ── 产物常量（版本号 / 文件名 / I4 的码与端点 / 各产物角色）──────────────────────────────────────────────
P5_VERSION = 136
P6_VERSION = 137
I4_VERSION = 138

#: P5 的收敛射程 = **五个原有内置岗位**（`product_manager` / `knowledge_editor` 由 V137 自己建行授权）。
P5_ROLES = ("admin", "customer_service", "finance", "operator", "sales")

# ── V158（issue #5652 的质检员 `inspector`）────────────────────────────────────────────────────────
#: 🔴 **V158 不是已发布迁移 ⇒ 它的渲染输入是活清单**（与 V136 / V137 的 `FROZEN_SNAPSHOTS` 有意不同）：
#: 活清单前进 ⇒ 重新渲染本产物；手改本产物 ⇒ 新鲜度判据判红。两份「渲染输入从哪来」都有判据钉着
#: （`test_frozen_artifacts_do_not_follow_the_live_manifest` 与 `test_live_artifacts_follow_the_live_manifest`）。
#: ⚠️ 版本号让号（#7010 的在飞迁移占 `V156`；本单的质检记录表占 `V157`）⇒ 本岗位迁移取 **V158**。
INSPECTOR_VERSION = 158
#: 新岗位的**唯一 id 真值**：清单 `roles.seed` 的键。
INSPECTOR_CODE = "inspector"

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


def _pairs_literal(pairs) -> str:
    """`_comment_rows` / `_ledger_rows` 的**同一份值**的单行形态：`('a', 'b'), ('c', 'd')`。

    🔴 为什么要有它（issue #5652）：**生成物（SQL 迁移）不是人读的文档** —— 迁移里那些
    `-- ── V136 的现取差集 ──` 之类的散文只写「哪些岗位/哪些码」，**不逐个码字面量点名**
    ⇒ 一个人改错了其中一项，PR 里看不出来。而 `docs/wiki/RBAC.md` 的岗位清单行**必须**逐值
    点名（`test_rbac_role_list_doc_consistency.py` 守着）⇒ 手抄那份清单就是**第二份会漂的真值**。
    本函数给出「同一实例的两种渲染」中的**文档形态**（值仍只有一处真值 = 清单）。
    """
    return ", ".join(f"('{role}', '{code}')" for role, code in pairs)


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


def role_codes(manifest: dict, role: str) -> list[str]:
    """某角色在清单 `roles.seed` 里声明的码（`*` 展开成目录全集）—— **值级唯一入口**。"""
    derive = load_derive()
    return sorted(derive.expand_role_codes(manifest, manifest["roles"]["seed"][role]))


def p6_codes(manifest: dict, role: str) -> list[str]:
    """P6 的码读取（与 `role_codes` **同一份实现** —— 本函数只是旧名，避免两处各写一遍展开口径）。"""
    return role_codes(manifest, role)


def render_p6(manifest: dict) -> str:
    """渲染 `V137`（**已发布 ⇒ 输入钉在发布时刻的清单快照上**，见 `FROZEN_SNAPSHOTS`；同 `render_p5`）。"""
    manifest = load_frozen_snapshot(f"V{P6_VERSION}")
    return _render_role_definition(
        manifest,
        version=P6_VERSION,
        rel_name="V137__formalize_legacy_roles.sql",
        entries=tuple((role, P6_ROLES[role][0], P6_ROLES[role][1]) for role in sorted(P6_ROLES)),
        header=_P6_HEADER.format(
            pm_codes=len(p6_codes(manifest, "product_manager")),
            ke_codes=len(p6_codes(manifest, "knowledge_editor")),
        ),
        footer=_P6_FOOTER,
        missing_roles_msg="个历史岗位码没有 roles 行 —— 回滚本迁移",
        missing_notice="RAISE NOTICE 'V{version} 终态对账通过：两个历史岗位码已正式定义（roles 行 + 授权）';",
    )


#: `V137` 的散文（**只含可读描述，值一律走占位符**）：值改了散文不用改 ⇒ 不存在「两处要同步」。
_P6_HEADER = """-- 两个历史岗位码的**正式定义**（issue #5699 的 **P6**，出口 (i)；设计真值源 §2.6 / §4 的 P6 行）
--
-- ## 一句话
--   `product_manager`（商品管理员）/ `knowledge_editor`（知识编辑）此前**不是岗位**：
--   不在种子里、迁移链一条谓词都不提（⇒ **没有 `roles` 行**）、岗位权限页**无法编辑**，
--   只靠 `RoleService.getPermissionCodesForRole` 的 `switch` 一行 `case` 拿 {pm_codes} / {ke_codes} 个码。
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
--   ② 米宝 `allowed_roles`（`backend/ai-agent-service/app/agents/agents/mibao.py`）与 bmini 角色名映射
--      （`frontend/bmini-app/src/pages/profile/index/index.tsx`）引用的是**角色名**：正式定义后仍逐字成立
--      （读数见 PR body），本迁移**不**动它们。"""

#: `V137` 的收口散文（**只余结构**）：收口 `RAISE NOTICE` 由 `missing_notice` 现取并写在
#: `_ROLE_GRANTS_BODY` 的 `{missing_head}` 位（与 V158 同款）⇒「两个历史岗位码」这句历史措辞
#: 属 V137 自己的散文，改清单不该让**已发布**产物漂移，故不给它任何占位符。
_P6_FOOTER = """END $$;

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
# 三·五、共用的「岗位正式定义」渲染器 + V158（issue #5652 的质检员）
# ══════════════════════════════════════════════════════════════════════════════

#: 逐条 `(岗位, 码)` 的**唯一**渲染（授权语句 + 注释块 + 终态对账的 `VALUES` 行都从它出）。
#: 🔴 为什么是三个消费点而不是一个：迁移是**人读的**（授权语句）、**对账执行**的（`VALUES` 行）、
#: 以及文件头的**可读清单**（注释行）—— 三处必须逐值同源，分开写必然漂移。
#: 占位符名 `pairs_*` 由渲染器提供（本函数**只**负责这一段）。
_ROLE_GRANTS_BODY = """{codes_rows}

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
      CROSS JOIN (VALUES {role_values}) AS want(role_code)
     WHERE NOT EXISTS (
            SELECT 1 FROM roles r
             WHERE r.tenant_id = t.id AND r.code = want.role_code AND r.deleted = 0
       );
    IF missing_roles > 0 THEN
        RAISE EXCEPTION 'V{version} 终态对账失败：% {missing_roles_msg}', missing_roles;
    END IF;

    SELECT COUNT(*) INTO missing_links
      FROM tenants t
      JOIN roles r ON r.tenant_id = t.id AND r.deleted = 0
      JOIN permissions p ON p.tenant_id = t.id
      JOIN (VALUES
        {pairs_rows}
      ) AS want(role_code, perm_code) ON want.role_code = r.code AND want.perm_code = p.code
     WHERE NOT EXISTS (
            SELECT 1 FROM role_permissions rp
             WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.deleted = 0
       );
    IF missing_links > 0 THEN
        RAISE EXCEPTION 'V{version} 终态对账失败：仍有 % 对 (岗位, 码) 没有 role_permissions 行 —— 回滚本迁移', missing_links;
    END IF;
    {missing_head}"""


def _render_role_definition(
    manifest: dict,
    *,
    version: int,
    rel_name: str,
    entries,
    header: str,
    footer: str,
    missing_roles_msg: str = "个岗位码没有 roles 行 —— 回滚本迁移",
    missing_notice: str | None = None,
) -> str:
    """渲染一份「按清单**正式定义**若干岗位」的迁移（建 `roles` 行 + 按清单授权 + 终态对账）。

    `entries` = `tuple[(role_code, 角色名, 描述), …]`；**码不给** —— 一律由 `role_codes()` 现取。

    幂等（`MigrationRunner` 的硬要求）：`roles` 用 `WHERE NOT EXISTS(同租户同 code 有效行)`、
    `role_permissions` 用 `ON CONFLICT (role_id, permission_id) DO NOTHING`、只 INSERT
    ⇒ 第二遍每条语句 0 行。

    停止条件（fail-closed）：终态对账缺任何 `roles` 行 / 任何 `(岗位, 码)` 授权行 ⇒ 抛错回滚。

    `rel_name` = 产物路径（仅用于报错定位）；`missing_roles_msg` / `missing_notice` = 两处**与岗位数
    相关**的散文（默认值 = 通用形态；V137 由 `render_p6` 传它的历史措辞 ⇒ 已发布产物逐字节不变）。
    """
    del rel_name
    for role, _name, _desc in entries:
        assert role in manifest["roles"]["seed"], (
            f"`{role}` 必须在清单 `roles.seed` 里（值只有一处真值 ⇒ 现取缺失就不渲染，fail-closed）"
        )
        fallback = manifest["roles"]["fallback"].get(role)
        assert fallback is not None and sorted(fallback) == sorted(role_codes(manifest, role)), (
            f"`{role}` 的种子与回退**必须逐值相等**（与 V137 的 P6 收口同款判据）："
            f"seed={sorted(role_codes(manifest, role))} fallback={sorted(fallback or [])}"
        )
    rows = "\n\n".join(
        f"""-- ── {role}（{name}）：{len(role_codes(manifest, role))} 个码 ──
INSERT INTO roles (id, tenant_id, name, code, description, status, created_at, updated_at, deleted)
SELECT gen_random_uuid()::text, t.id, '{name}', '{role}', '{desc}', 'active', NOW(), NOW(), 0
FROM tenants t
WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND r.code = '{role}' AND r.deleted = 0);

{_grant_stmt(f"r.code = '{role}'", role_codes(manifest, role))}"""
        for role, name, desc in entries
    )
    pairs = [(role, code) for role, _n, _d in entries for code in role_codes(manifest, role)]
    notice = missing_notice or (
        f"RAISE NOTICE 'V{version} 终态对账通过：{len(entries)} 个岗位已正式定义（roles 行 + 授权）';"
    )
    body = _ROLE_GRANTS_BODY.format(
        codes_rows=rows,
        role_values=", ".join(f"('{role}')" for role, _n, _d in entries),
        version=version,
        pairs_rows=",\n        ".join(f"('{role}', '{code}')" for role, code in pairs),
        missing_roles_msg=missing_roles_msg,
        missing_head=notice.format(version=version) + "\n",
    )
    return f"{header}\n\nBEGIN;\n\n{body}{footer}"


def render_inspector(manifest: dict) -> str:
    """渲染 `V158`（**输入 = 活清单**：本迁移尚未发布 ⇒ 清单前进即重渲染，见 `INSPECTOR_VERSION`）。"""
    entries = ((INSPECTOR_CODE, "质检员", _INSPECTOR_ROLE_DESC),)
    pairs_literal = _pairs_literal([(INSPECTOR_CODE, code) for code in role_codes(manifest, INSPECTOR_CODE)])
    return _render_role_definition(
        manifest,
        version=INSPECTOR_VERSION,
        rel_name=f"V{INSPECTOR_VERSION}__create_inspector_role.sql",
        entries=entries,
        header=_INSPECTOR_HEADER.format(
            role=INSPECTOR_CODE,
            version=INSPECTOR_VERSION,
            codes=" / ".join(f"`{code}`" for code in role_codes(manifest, INSPECTOR_CODE)),
            pairs_literal=pairs_literal,
            rollback_grants=",\n".join(
                f"--        ('{INSPECTOR_CODE}', '{code}')" for code in role_codes(manifest, INSPECTOR_CODE)
            ),
        ),
        footer=_INSPECTOR_FOOTER,
    )


#: V158 的角色描述（散文字面量；**值**一律走 `role_codes()` 现取 ⇒ 不存在第二份码表）。
_INSPECTOR_ROLE_DESC = "成品帘质检录入（issue #5652：独立质检员，持 production:view / production:inspect）"

#: V158 的文件头散文（占位符 = 角色码 / 码清单 / 逐对清单 / 回滚块，值全部现取）。
_INSPECTOR_HEADER = """-- 新岗位 `inspector`（质检员）的**正式定义**（issue #5652：质检记录 / 返工报废）
--
-- ## 一句话
--   成品帘质检的**录入者 = 独立质检员**（用户 2026-10 裁定「B 独立质检员」）⇒ 本迁移把
--   `{role}` 正式定义为一个**新租户岗位**：**建 `roles` 行**（幂等）＋**按清单授权**（幂等）＋终态对账。
--   本迁移**不改**任何既有岗位的授权（新岗位只持有 {codes} 两个码）。
--
-- ## 🔴 为什么是这两个码，且**必须新增一个目录码**
--   · `production:view` —— 看得到「生产看板 / 工序」等生产面（读码，复用既有码）；
--   · `production:inspect` —— 质检录入是**写**动作（`QualityCheckController` 的两个端点带
--     `@RequirePermission("production:inspect")`），**新码**：复用既有的 `production:execute`
--     会把质检录入权顺带发给持该码的四个岗位（客服 / 运营 / 销售 / 财务），
--     而用户裁定的录入者是「**独立**质检员」⇒ 复用即**放宽**（实测：权限判据当场判红）。
--     新码只授 `{role}`（+ 运行时恒 `["*"]` 的 `admin`）。
--     代价（照实登记）：目录码要同步三处声明面（`RegistrationService` / `PermissionService` /
--     `rbac/manifest.json` 的 `codes.*`）—— 三处逐值相等由 `rbac` 判据守着。
--   ⇒ 逐对真值：{pairs_literal}
--   （值逐字取自 `rbac/manifest.json` 的 `roles.seed.{role}`，与 `roles.fallback.{role}` **逐值相等**。）
--
-- ## 🔴 为什么需要一条迁移（只改 Java 不够）
--   新租户走 `RegistrationService.initializeDefaultRolesAndPermissions`（同批加第 8 个岗位种子）；
--   而**存量租户没有任何 Java 路径**会给他们建这个岗位行、也不会授权（`PermissionService`
--   的懒补种只管**权限目录**、不管 `roles` / `role_permissions`）⇒ 不补这条迁移，
--   「新租户有质检员岗位、老租户没有」——正是设计真值源 §3.1 登记的那条**路径依赖**。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · `roles`：`WHERE NOT EXISTS (同租户同 code 有效行)`（与 V29/V32/V137 的既有写法同款）；
--   · `role_permissions`：`ON CONFLICT (role_id, permission_id) DO NOTHING`
--     （唯一索引 `uq_role_permissions` 兜住）；
--   · **只 INSERT**，不改/不删任何既有行 ⇒ 第二遍每条语句 0 行，结果与第一遍相同。
--
-- ## 停止条件（fail-closed）
--   终态对账（文末 `DO` 块）：每个租户都必须有 `{role}` 的 `roles` 行，且上表每一对 `(岗位, 码)`
--   都必须有 `role_permissions` 行；缺任何一项 ⇒ `RAISE EXCEPTION` 并回滚本迁移（不硬推）。
--
-- ## 显式事务（同 V97 / V102 / V107 / V108 / V111 / V124 / V136 / V137 的实测口径）
--   `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` 默认逐条
--   autocommit ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
--
-- ## 本文件是**生成物**（不是手写真值）
--   由 `rbac/generate_migration.py` 从 `rbac/manifest.json` 渲染（`python3 rbac/generate_migration.py`）
--   ⇒ 手改本文件、或改了清单没重渲染，都会被新鲜度判据判红（`test_rbac_migration_convergence.py`）。
--   ⚠️ 与 `V136` / `V137` 的**有意差异**：那两份是**已发布**迁移 ⇒ 渲染输入钉在发布时刻的清单快照上
--   （`FROZEN_SNAPSHOTS`，改活清单**不会**动它们）；本迁移尚未发布 ⇒ 输入 = **活清单**。
--
-- ## 回滚（**新迁移，不删本文件**）
--   ```sql
--   -- V{version}__rollback.sql（本单只登记，不落码）：只删本迁移**建出来**的行
--   DELETE FROM role_permissions rp USING roles r, permissions p
--    WHERE rp.role_id = r.id AND rp.permission_id = p.id
--      AND (r.code, p.code) IN (VALUES
{rollback_grants});
--   DELETE FROM roles WHERE code = '{role}';
--   ```
--   **回滚是收窄**：会把租户在岗位权限页给该岗位的手工勾选一并删掉 ⇒ 属**有意**（宁可回到
--   「没有这个岗位」，也不要留下指向不存在岗位的悬空授权）。
--
-- ## bootstrap 终态（如实登记）
--   `backend/admin-api/src/main/resources/db/init/schema.sql`（新建库路径**不跑迁移链**）
--   不含任何 `role_permissions` / `permissions` 种子行（两份 `INSERT INTO …` 在该文件 **0 命中**）
--   ⇒ 本迁移**无需**同步它。"""


#: V158 的收口散文（占位符 = 与 `_ROLE_GRANTS_BODY` **完全相同**的 `{missing_head}`）。
_INSPECTOR_FOOTER = """END $$;

COMMIT;
"""


# ══════════════════════════════════════════════════════════════════════════════
# 五、V161 / V162：内置岗位**描述**的两次刷新（#7111 → #7146）
# ══════════════════════════════════════════════════════════════════════════════
#
# 两次刷新的**输入来源有意不同**：
#   · V161（#7111，2026-10-17 **已发布**）⇒ 输入**钉在发布时刻的文本**（`DESCRIPTIONS_V161`）：
#     活清单前进**不**动它（历史迁移跟着清单漂 = 两条真相）。
#   · V162（#7146，本单）⇒ 输入 = **活清单** `roles.descriptions`：清单变了没重渲染即判红
#     （新鲜度判据 = `tests/unit_ci_workflows/test_rbac_migration_convergence.py` 同族口径）。

DESCRIPTIONS_VERSION = 161

DESCRIPTIONS_V161: dict[str, str] = {
    "admin": "职责：企业最高管理岗位，负责员工、岗位与权限配置以及企业基础信息维护，统筹商品、客户、订单、生产、仓储与财务各模块的审核与异常处理。默认可用模块：全部模块 —— 经营看板、每日简报、商品管理、在线接待、知识库、售后工单、客户列表、订单列表、财务对账、生产看板、智能派单、计件工资、入库单、库存明细、发货单、余料台账、省料看板、员工管理、岗位权限、企业基础设置。",
    "customer_service": "职责：在线接待客户咨询与投诉，跟进订单进度，处理售后工单与退款，维护客户档案与知识库内容，并承担成品帘加工执行（建加工单、报工、打任务卡、发货）。默认可用模块：经营看板、每日简报、在线接待、知识库、售后工单、客户列表、订单列表、发货单、入库单、智能派单。",
    "finance": "职责：登记与核对收支流水，跟踪订单收款与对账差异，核对入库、发货与加工工价的成本口径，并按需执行加工单与报工操作。默认可用模块：经营看板、每日简报、客户列表、订单列表、财务对账、发货单、入库单、智能派单。",
    "inspector": "职责：负责成品帘质检判定录入（合格、返工、报废），核对计件工价与工序数据，为返工与报废的结算提供依据。默认可用模块：生产看板、计件工资、企业基础设置。",
    "knowledge_editor": "职责：维护客服知识库，新增、修订与下线知识卡片，按商品资料校对对外答复口径，保证客服答复准确一致。默认可用模块：经营看板、每日简报、知识库、商品管理、库存明细、省料看板。",
    "operator": "职责：统筹日常经营：建单、改单、退款与售后处理，维护客户档案、商品与分类，管理加工项与入库单，登记财务流水，并兼顾在线接待。默认可用模块：经营看板、每日简报、商品管理、在线接待、知识库、售后工单、客户列表、订单列表、财务对账、生产看板、智能派单、计件工资、入库单、库存明细、发货单、余料台账、省料看板、员工管理、企业基础设置。",
    "product_manager": "职责：维护商品资料、分类与上下架，管理加工项与加工费口径，为智能派单、生产看板与库存、省料分析提供准确的商品与工序数据。默认可用模块：经营看板、每日简报、商品管理、生产看板、智能派单、计件工资、库存明细、余料台账、省料看板、企业基础设置。",
    "sales": "职责：接待客户并促成下单，负责新建订单、订单跟进与详情核对，跟踪生产与发货进度，维护客户档案。默认可用模块：经营看板、每日简报、商品管理、客户列表、订单列表、智能派单、入库单、库存明细、发货单、省料看板。"
}

#: V162（#7146）：模块清单**改为派生**（`frontend/admin-web/src/lib/role-default-menu.ts`：一份权限码
#: → 后台菜单 + 手机端可见面）⇒ `roles.description` 只留「职责」散文；旧文案谓词 = V161 写下的文本。
LEGACY_ROLE_DESCRIPTIONS: dict[str, tuple[str, ...]] = {
    "admin": ("拥有全部管理权限",),
    "customer_service": ("负责客户服务与咨询",),
    "finance": ("负责财务对账",),
    "inspector": (
        "成品帘质检录入（issue #5652：独立质检员，持 production:inspect / production:view）",
        "成品帘质检录入（issue #5652：独立质检员，持 production:view / production:inspect）",
    ),
    "knowledge_editor": ("知识库编辑（POC 期历史岗位，issue #5699 的 P6 正式定义）",),
    "operator": ("负责日常运营管理",),
    "product_manager": ("商品与加工项管理（POC 期历史岗位，issue #5699 的 P6 正式定义）",),
    "sales": ("负责销售业务",),
}

_DESCRIPTIONS_HEADER = """-- 内置岗位**描述**的刷新（issue #7111）
--
-- ## 一句话
--   `roles.description` 是**商家可见面**（岗位权限页逐卡展示、员工弹窗里选岗位时会读到）。
--   它此前是半句话（「负责销售业务」）或**内部标识**（issue 号 / 权限码 / POC 口径），
--   既说不清「这个岗位承担什么职责」，也说不清「默认能用哪些模块」。
--   本迁移把它们统一改成「**职责 + 默认可用模块**」两段式 —— 文案的**唯一声明面**是
--   `rbac/manifest.json` 的 `roles.descriptions`，与 `RegistrationService` 的注册种子
--   **逐值对账**（`rbac/readings.json` 的 `roles.descriptions` 由同一份 `Role.builder()` 块现取）。
--
-- ## 幂等 + **不覆盖自定义文案**（本迁移的安全边界）
--   · 每条 UPDATE 的谓词是 `description IN (<旧默认文案>)` —— 只有**仍是**我们写的那句话的行会被改；
--   · 商家在岗位权限页改过的描述**不在**旧文案表里 ⇒ **一律不动**（迁移不是「把文案推平」的工具）；
--   · 改过的行第二次执行时已不匹配谓词 ⇒ **第二遍每条 0 行**，结果与第一遍相同。
--
-- ## 存量租户（为什么需要一条迁移）
--   新租户走 `RegistrationService` 的种子（本 PR 同批改成新文案）；存量租户的 `roles` 行
--   由 V29 / V32 / V137 / V158 建出、且**没有任何 Java 路径**会改写已有描述 ⇒ 不补这条迁移，
--   「新租户是新文案、老租户还是旧文案」的两份真相会一直并存。
--
-- ## 停止条件（fail-closed）
--   终态对账（文末 `DO` 块）：任何一行仍同时命中「内置岗位码 + 旧默认文案」⇒
--   `RAISE EXCEPTION` 并回滚本迁移（不硬推半完成态）。
--
-- ## 显式事务（同 V97 / V102 / V107 / V108 / V111 / V124 / V136 / V137 / V158 的实测口径）
--   `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` 默认逐条
--   autocommit ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
--
-- ## 本文件是**生成物**（不是手写真值）
--   由 `rbac/generate_migration.py` 从 `rbac/manifest.json` 渲染（`python3 rbac/generate_migration.py`）
--   ⇒ 手改本文件、或改了清单没重渲染，都会被新鲜度判据判红（`test_rbac_migration_convergence.py`）。
--
-- ## 回滚（**新迁移，不删本文件**）
--   ```sql
--   -- 只会回到「旧默认文案」；商家自定义文案本迁移从未改过 ⇒ 无需回滚
--   UPDATE roles SET description = '<旧默认文案>' WHERE code = '<岗位码>' AND deleted = 0
--     AND description = '<新文案>';   -- 逐岗位重复（回滚是「文案回退」，不涉及授权 / 数据）
--   ```
--
-- ## 边界（照实登记）
--   ① 不改任何 `role_permissions` 行，**零授权 delta**；② 不回填 `users.permissions` 快照；
--   ③ 空描述（NULL / 空串）**不动** —— 留白多半是有意的（本迁移只认「我们写的那句话」）。"""

_DESCRIPTIONS_V2_HEADER = """-- 内置岗位描述**去模块清单**（issue #7146）
--
-- ## 一句话
--   `roles.description` 是**商家可见面**（岗位权限页逐卡展示）。#7111 曾把「默认可用模块」也写进散文
--   —— 那是**第二份会漂的清单**：它只抄后台侧边栏菜单，且菜单一变就与现实脱节
--   （#7087 撤掉「每日简报」菜单后 7/8 条描述仍点名它，见 #7139）。
--   用户 2026-10-17 逐字：「手机端可见面要不要作为『默认岗位默认菜单』的一部分，当然需要，
--   **把 PC 和手机端当一个整体**」⇒ 模块清单改为**派生**（一份权限码 → 后台菜单 + 手机端可见面，
--   见 `frontend/admin-web/src/lib/role-default-menu.ts`），描述只留「职责：…」散文。
--
-- ## 幂等 + **不覆盖自定义文案**（本迁移的安全边界）
--   · 每条 UPDATE 的谓词是 `description IN (<V161 写下的默认文案>)` —— 只有**仍是**我们写的那句话的行会被改；
--   · 商家在岗位权限页改过的描述**不在**旧文案表里 ⇒ **一律不动**（迁移不是「把文案推平」的工具）；
--   · 改过的行第二次执行时已不匹配谓词 ⇒ **第二遍每条 0 行**，结果与第一遍相同。
--
-- ## 存量租户（为什么需要一条迁移）
--   新租户走 `RegistrationService` 的种子（本 PR 同批改成职责-only）；存量租户的行由 V161 写成两段式、
--   且**没有任何 Java 路径**会改写已有描述 ⇒ 不补这条迁移，「新租户职责-only、老租户还带模块清单」会一直并存。
--
-- ## 停止条件（fail-closed）
--   终态对账（文末 `DO` 块）：任何一行仍命中「内置岗位码 + V161 默认文案」⇒
--   `RAISE EXCEPTION` 并回滚本迁移（不硬推半完成态）。
--
-- ## 显式事务（同 V161 的实测口径）
--   `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` 默认逐条 autocommit
--   ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
--
-- ## 本文件是**生成物**（不是手写真值）
--   由 `rbac/generate_migration.py` 从 `rbac/manifest.json` 渲染（`python3 rbac/generate_migration.py`）
--   ⇒ 手改本文件、或改了清单没重渲染，都会被新鲜度判据判红。
--
-- ## 回滚（**新迁移，不删本文件**）
--   ```sql
--   -- 只会回到「V161 文案」；商家自定义文案本迁移从未改过 ⇒ 无需回滚
--   UPDATE roles SET description = '<V161 文案>' WHERE code = '<岗位码>' AND deleted = 0
--     AND description = '<新文案>';   -- 逐岗位重复（回滚是「文案回退」，不涉及授权 / 数据）
--   ```
--
-- ## 边界（照实登记）
--   ① 不改任何 `role_permissions` 行，**零授权 delta**；② 不回填 `users.permissions` 快照；
--   ③ 空描述（NULL / 空串）**不动** —— 留白多半是有意的（本迁移只认「我们写的那句话」）。"""

DESCRIPTIONS_V2_VERSION = 162

_UPDATE_TEMPLATE = (
    "-- ── {role}：只改「仍是旧默认文案」的行（自定义描述一律不动）──\n"
    "UPDATE roles\n"
    "   SET description = '{desc}', updated_at = NOW()\n"
    " WHERE code = '{role}'\n"
    "   AND deleted = 0\n"
    "   AND description IN ({legacy});"
)

_DO_BLOCK = """-- ══════════════════════════════════════════════════════════════════════════════
-- 终态对账（仍有行保留旧默认文案 ⇒ 回滚，不硬推）
-- ══════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    stale INTEGER;
BEGIN
    SELECT COUNT(*) INTO stale
      FROM roles r
     WHERE r.deleted = 0
       AND (r.code, r.description) IN (VALUES
        {old_pairs}
       );
    IF stale > 0 THEN
        RAISE EXCEPTION 'V{version} 终态对账失败：仍有 % 行保留旧默认描述 —— 回滚本迁移', stale;
    END IF;
    RAISE NOTICE 'V{version} 终态对账通过：{count} 个内置岗位的描述已刷新';
END $$;

COMMIT;
"""


def _assert_roles_match_seed(manifest: dict, descriptions: dict) -> None:
    seed = manifest["roles"]["seed"]
    assert set(descriptions) == set(seed), (
        f"`roles.descriptions` 的岗位码必须与 `roles.seed` 逐值相等（缺/多都不渲染）："
        f"缺 {sorted(set(seed) - set(descriptions))} / 多 {sorted(set(descriptions) - set(seed))}"
    )


def _render_description_refresh(
    version: int,
    header: str,
    descriptions: dict[str, str],
    old_texts: dict[str, tuple[str, ...]],
) -> str:
    """渲染一份「描述刷新」迁移（V161 / V162 共用；只有一个来源不同 = 传进来的 `descriptions`）。"""
    for role in sorted(descriptions):
        text = descriptions[role]
        assert "'" not in text, f"`{role}` 的描述含单引号 ⇒ 渲染出的 SQL 会断（fail-closed）"
        assert role in old_texts and old_texts[role], (
            f"`{role}` 没有登记旧默认描述 ⇒ 迁移不知道要改哪一行（fail-closed）"
        )
    updates = "\n\n".join(
        _UPDATE_TEMPLATE.format(role=role, desc=descriptions[role], legacy=_sql_list(old_texts[role]))
        for role in sorted(descriptions)
    )
    old_pairs = ",\n        ".join(
        f"('{role}', '{old}')" for role in sorted(descriptions) for old in old_texts[role]
    )
    return f"""{header}

BEGIN;

{updates}

{_DO_BLOCK.format(old_pairs=old_pairs, version=version, count=len(descriptions))}"""


def render_role_descriptions(manifest: dict) -> str:
    """渲染 `V161`（#7111，**已发布** ⇒ 输入钉在发布时刻文本，活清单不驱动它）。"""
    _assert_roles_match_seed(manifest, DESCRIPTIONS_V161)
    for role in sorted(DESCRIPTIONS_V161):
        assert DESCRIPTIONS_V161[role].startswith("职责：") and "默认可用模块：" in DESCRIPTIONS_V161[role], (
            f"V161 的冻结文本必须逐字保留它当时写下的两段式：{role}"
        )
    return _render_description_refresh(
        DESCRIPTIONS_VERSION, _DESCRIPTIONS_HEADER, DESCRIPTIONS_V161, LEGACY_ROLE_DESCRIPTIONS
    )


def render_role_descriptions_v2(manifest: dict) -> str:
    """渲染 `V162`（#7146，**输入 = 活清单**）：描述只留「职责」，模块清单改为派生。"""
    descriptions = manifest["roles"]["descriptions"]
    _assert_roles_match_seed(manifest, descriptions)
    for role in sorted(descriptions):
        text = descriptions[role]
        assert text.startswith("职责："), f"`{role}` 的描述必须以「职责：」开头：{text!r}"
        assert "默认可用模块：" not in text, (
            f"`{role}` 的描述仍带「默认可用模块：」⇒ 模块清单必须派生（issue #7146）：{text!r}"
        )
    old_texts = {role: (DESCRIPTIONS_V161[role],) for role in descriptions}
    return _render_description_refresh(
        DESCRIPTIONS_V2_VERSION, _DESCRIPTIONS_V2_HEADER, descriptions, old_texts
    )


# ══════════════════════════════════════════════════════════════════════════════
# 四、入口
# ══════════════════════════════════════════════════════════════════════════════

#: `{产物路径: 渲染函数}` —— 顺序即文件名顺序（`--check` 的输出顺序稳定）。
ARTIFACTS = {
    f"backend/admin-api/src/main/resources/db/migration/V{P5_VERSION}__converge_builtin_role_permissions.sql": render_p5,
    f"backend/admin-api/src/main/resources/db/migration/V{P6_VERSION}__formalize_legacy_roles.sql": render_p6,
    f"backend/admin-api/src/main/resources/db/migration/V{I4_VERSION}__add_production_execute_permission.sql": render_i4,
    f"backend/admin-api/src/main/resources/db/migration/V{INSPECTOR_VERSION}__create_inspector_role.sql": render_inspector,
    f"backend/admin-api/src/main/resources/db/migration/V{DESCRIPTIONS_VERSION}__refresh_default_role_descriptions.sql": render_role_descriptions,
    f"backend/admin-api/src/main/resources/db/migration/V{DESCRIPTIONS_V2_VERSION}__strip_default_role_module_lists.sql": render_role_descriptions_v2,
}


def render_all(manifest: dict | None = None) -> dict[str, str]:
    """渲染五份迁移（纯函数；注入式红证 = 喂改过的清单）。"""
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
