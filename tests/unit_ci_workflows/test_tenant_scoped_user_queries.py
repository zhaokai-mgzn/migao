# case_ids: AU-002, AU-008
"""租户隔离的**类级元守卫**：`@InterceptorIgnore(tenantLine = "true")` + 查 `users` ⇒ 必须自带 tenant_id。

## 病灶形态（issue #5485 要防的正是它）

`backend/admin-api/src/main/java/com/migao/admin/mapper/*.java` 上的
`@InterceptorIgnore(tenantLine = "true")` 会**关掉** MyBatis-Plus 的自动 `tenant_id` 注入。
于是「谁再写一个带该注解、又查 `users` 表、SQL 里却没有 `tenant_id` 谓词的方法」=
**跨租户串号**（issue #5485 业务真值 2 / 不变式 I1、I3），而**此前没有任何东西会因此变红**。

本仓踩过的同族形态：一次修复只修实例、同类入口照旧敞开（AGENTS.md 铁律 8 / `migao-dev-flow` §23）。
故本文件是**类级元守卫**：把「无租户谓词的跨租户用户名查询」这一类**堵在门口**。

## 判据（三条各自独立，未登记即红）

| # | 形态 | 判据 |
|---|---|---|
| 1 | 扫到的命中集（注解 + SQL 含 `users` 且**不含** `tenant_id`） | 必须 **⊆ 台账**（未登记 ⇒ 红） |
| 2 | 台账条数 | 必须 **== 现取命中条数**（只许缩短：销账后不删条目 ⇒ 红；新增豁免 ⇒ 红） |
| 3 | 台账条目 | 必须仍然**活着**（对应方法还在源码里，否则是陈旧豁免） |

台账 = `tests/unit_ci_workflows/tenant_ignore_ledger.json`，每条含
**方法名 + 豁免理由 + 补偿控制**（为什么串号不可能发生）。

## 为什么允许豁免而不是给 SQL 硬加 tenant_id

`UserMapper.selectActiveUsersByPhoneIgnoreTenant`（短信登录）**必须**跨租户查：
手机号是登录标识，同号可能存在于多个租户 —— 加了 `tenant_id` 谓词会让多租户下**查不到人**。
它的补偿控制是显式的：命中多个租户且未指定租户时**拒绝登录**（审计 07 P1-2），
绝不静默 `LIMIT 1` 落错租户。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: mapper 源码目录（本守卫的射程）
MAPPER_DIR = REPO / "backend/admin-api/src/main/java/com/migao/admin/mapper"
#: 豁免台账
LEDGER = Path(__file__).resolve().parent / "tenant_ignore_ledger.json"
#: 关掉自动租户注入的注解（**本守卫的触发条件之一**）
IGNORE_ANNOTATION = '@InterceptorIgnore(tenantLine = "true")'
#: SQL 文本里出现它 = 该查询落在 users 表上
USERS_TABLE = re.compile(r"\busers\b", re.IGNORECASE)
#: 租户谓词（缺它就跨租户）。
#  ⚠️ 必须按**谓词**判（`tenant_id` 后面跟 `=`），不能按「SQL 里有没有 tenant_id」判 ——
#  后者会把 `SELECT id, tenant_id, ... FROM users` 这种**投影列**当成谓词 ⇒ 判据空转（假绿）。
#  实测：本守卫第二版就是这么把唯一一条命中漏成 0 条的。
TENANT_PREDICATE = re.compile(r"\btenant_id\s*=", re.IGNORECASE)

STATEMENT_RE = re.compile(r"@(?:Select|Update|Delete|Insert)\(\s*(.*?)\s*\)\s*\n", re.DOTALL)
STRING_LITERAL_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')

#: 「关掉租户注入」注解**紧邻**语句注解 ⇒ 该语句属于这个方法。
#  ⚠️ 只按**文件级**出现该注解来判断会造假阳性：`UserMapper.selectDashboardUserStats` 是普通
#  `@Select`（租户条件由 TenantLineInnerInterceptor **自动注入**，它没有关掉注入）——
#  按文件级判定会把它误判成「跨租户且无 tenant_id」（实测：本守卫第一版就是这么红的）。
#  故必须把注解绑到**紧邻的**那一条语句上。
INLINE_STATEMENT_RE = re.compile(
    r'@InterceptorIgnore\(tenantLine = "true"\)\s*'
    r"@(?:Select|Update|Delete|Insert)\((.*?)\)\s*\n"
    r"[^;{]*?\s(\w+)\s*\(",
    re.DOTALL,
)


def _method_names_and_sql(java_src: str) -> list[tuple[str, str]]:
    """→ [(方法名, 语句 SQL 文本)]：**关掉租户注入注解紧邻**的那条语句 + 它后面的方法名。"""
    out: list[tuple[str, str]] = []
    for match in INLINE_STATEMENT_RE.finditer(java_src):
        sql = " ".join(STRING_LITERAL_RE.findall(match.group(1)))
        out.append((match.group(2), sql))
    return out


def scan_tenant_ignore_users_queries(mapper_dir: Path = None) -> dict[str, str]:
    """扫出「关掉租户注入 + 查 users + SQL 里没有 tenant_id」的方法（issue #5485 的病灶形态）。"""
    hits: dict[str, str] = {}
    target = Path(mapper_dir or MAPPER_DIR)
    for java in sorted(target.glob("*.java")):
        src = java.read_text(encoding="utf-8")
        for name, sql in _method_names_and_sql(src):
            if USERS_TABLE.search(sql) and not TENANT_PREDICATE.search(sql):
                hits[name] = f"{java.name}: {sql[:160]}"
    return hits


def load_ledger(path: Path = None) -> dict:
    p = Path(path or LEDGER)
    assert p.is_file(), (
        f"租户隔离豁免台账缺失：{p}（**未登记即红**：判据因此缺少唯一事实源，"
        "「没跑」不得读成「通过」）")
    return json.loads(p.read_text(encoding="utf-8"))


# ── 判据 ①：命中集必须被台账覆盖（未登记即红）──

def test_every_tenant_ignored_users_query_is_registered():
    hits = scan_tenant_ignore_users_queries()
    ledger = load_ledger()
    exempt = {e["method"] for e in ledger["entries"]}
    unregistered = sorted(set(hits) - exempt)
    assert unregistered == [], (
        "发现**未登记**的「关掉租户注入 + 查 users + SQL 无 tenant_id」方法 —— 这正是跨租户串号形态"
        "（issue #5485 I1/I3）：\n"
        + "\n".join(f"    · {m}\n        {hits[m]}" for m in unregistered)
        + "\n  两个出口：① 给 SQL 补 `tenant_id` 谓词（多数情况的正解：租户必须由登录标识解析后传入）；"
        "\n            ② 确有跨租户必要（如手机号登录）⇒ 登记进 "
        f"{LEDGER.name} 并写清**补偿控制**；\n"
        "  ⛔ 不许为了让判据变绿而给「必须跨租户」的查询硬加 tenant_id（那会让多租户下查不到人）。")


# ── 判据 ②：台账 == 现取命中（只许缩短）──

def test_ledger_matches_live_scan_exactly():
    hits = scan_tenant_ignore_users_queries()
    ledger = load_ledger()
    exempt = {e["method"] for e in ledger["entries"]}
    stale = sorted(exempt - set(hits))
    assert len(exempt) == len(hits), (
        "台账条数与现取命中数不一致（**豁免只许缩短**：销账后必须同步删条目，"
        "新增豁免必须先证明补偿控制）：\n"
        f"    现取命中 {len(hits)} 条 / 台账 {len(exempt)} 条\n"
        f"    已销账但仍留在台账：{stale or '（无）'}")
    assert stale == [], f"台账里有已不再命中的陈旧豁免（销账后请删条目）：{stale}"


# ── 判据 ③：台账条目必须活着 + 结构完整（含补偿控制）──

def test_ledger_entries_are_alive_and_justified():
    ledger = load_ledger()
    entries = ledger["entries"]
    assert entries, "台账为空 ⇒ 判据 ① 变成空断言（本仓最忌「绿了但没跑」）"
    for entry in entries:
        assert set(entry) >= {"method", "reason", "compensating_control"}, (
            f"台账条目字段不全（方法名 + 豁免理由 + 补偿控制 三件套）：{entry}")
        assert entry["reason"].strip() and entry["compensating_control"].strip(), (
            f"豁免理由/补偿控制不得为空（空 = 没解释为什么串号不可能发生）：{entry}")
        assert f" {entry['method']}(" in " " + "".join(
            p.read_text(encoding="utf-8") for p in MAPPER_DIR.glob("*.java")
        ) or entry["method"] in "".join(
            p.read_text(encoding="utf-8") for p in MAPPER_DIR.glob("*.java")
        ), f"台账条目指向的方法在源码里不存在（陈旧豁免）：{entry['method']}"


# ── 判据 ④：员工用户名的唯一性必须是**租户内**（I3 的数据面）──

def test_username_unique_index_is_tenant_scoped():
    migration = (REPO / "backend/admin-api/src/main/resources/db/migration"
                 / "V128__add_users_username_and_must_change_password.sql").read_text(encoding="utf-8")
    schema = (REPO / "backend/admin-api/src/main/resources/db/init/schema.sql").read_text(encoding="utf-8")

    for label, text in (("迁移 V128", migration), ("建库脚本 schema.sql", schema)):
        normalized = " ".join(text.split())
        assert "uk_users_tenant_username" in normalized, f"{label} 缺少员工用户名唯一索引（两份真相会漂移）"
        assert ("ON users (tenant_id, username)" in normalized), (
            f"{label} 的用户名唯一索引**不是租户内**的 —— 改成 `ON users (username)` 会让"
            "「不同企业可同名」（AU-008）当场失效：\n    " + normalized[:200])
        assert ("WHERE username IS NOT NULL AND deleted = 0" in normalized), (
            f"{label} 的用户名唯一索引丢了部分索引谓词 ⇒ 存量 NULL 行会互相冲突（且软删行会占位）")


# ── 自证：注入一个未登记的同形方法 ⇒ 判据 ① 必须红（否则上面的绿是空断言）──

def test_guard_detects_injected_violation(tmp_path):
    sample = tmp_path / "InjectedMapper.java"
    sample.write_text(
        "package com.migao.admin.mapper;\n"
        "public interface InjectedMapper {\n"
        "    @InterceptorIgnore(tenantLine = \"true\")\n"
        "    @Select(\"SELECT id FROM users WHERE username = #{username} AND deleted = 0\")\n"
        "    Object selectByUsername(String username);\n"
        "}\n",
        encoding="utf-8")
    hits = scan_tenant_ignore_users_queries(tmp_path)
    assert "selectByUsername" in hits, (
        "注入的违规方法没被扫出来 ⇒ 判据 ① 是空断言（本守卫对**将来**失效）")

    # 反向：补上 tenant_id 谓词 ⇒ 不再命中（证明判据不是「见 users 就红」）
    sample.write_text(
        "package com.migao.admin.mapper;\n"
        "public interface InjectedMapper {\n"
        "    @InterceptorIgnore(tenantLine = \"true\")\n"
        "    @Select(\"SELECT id FROM users WHERE tenant_id = #{tenantId} AND username = #{username}\")\n"
        "    Object selectByUsername(Long tenantId, String username);\n"
        "}\n",
        encoding="utf-8")
    assert scan_tenant_ignore_users_queries(tmp_path) == {}, (
        "带 tenant_id 谓词的查询不该被判违规（否则判据退化成「命中即红」的噪音）")


def test_baseline_scan_is_not_vacuous():
    """守卫的射程自证：mapper 目录必须真的被扫到（否则「绿」可能只是没扫）。"""
    assert MAPPER_DIR.is_dir(), f"mapper 目录不存在 ⇒ 本守卫没跑：{MAPPER_DIR}"
    assert list(MAPPER_DIR.glob("*.java")), f"mapper 目录下没有 Java 文件 ⇒ 本守卫没跑：{MAPPER_DIR}"
    assert IGNORE_ANNOTATION in (MAPPER_DIR / "UserMapper.java").read_text(encoding="utf-8"), (
        "UserMapper 里已无 @InterceptorIgnore(tenantLine=\"true\") ⇒ 判据 ① 可能已空转，请复核本守卫射程")


if __name__ == "__main__":
    hits = scan_tenant_ignore_users_queries()
    print(f"命中 {len(hits)} 条：")
    for name, detail in hits.items():
        print(f"  · {name}: {detail}")
    sys.exit(pytest.main([__file__, "-q"]))