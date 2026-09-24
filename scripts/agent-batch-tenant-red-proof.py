#!/usr/bin/env python3
"""#5327 红证机具：把「批量批次的跨租户隔离」每条判据的**判别力**变成可复算的。

## 为什么要有它

`AgentBatchCrossTenantRealDbTest` 的三条跨租户判据（读 / 执行 / 撤销）必须能**抓住**它要防的
三类真问题，否则「真库全绿」与「mocked mapper 全绿」没有区别（本仓 #5314 服务端包登记的边界：
那三条判据原先用的是 mocked mapper，SQL 根本没被执行）：

    ① 对生产源码逐条注入一个**语义缺陷**（不是改文案）；
    ② 跑**整类**真库判据，从 surefire XML 读**逐方法**结果；
    ③ 期望 = **目标判据方法 FAIL**（= 这条判据确实抓得住这个缺陷）；
       同时**逐条打印**还有哪些判据一起红了 —— 那是「共享覆盖面」，如实登记、不当失败；
    ④ 还原源码，并按 **sha256 内容指纹**自证与注入前逐字节相同。

## 变异各自钉的那一格（含「为什么必须是这一条」）

| 变异 | 注入的缺陷 | 期望变红的判据 | 这一格为什么只能靠它证明 |
|---|---|---|---|
| `interceptor_table_registration_removed` | 两张批次表被塞进 `IGNORE_TENANT_TABLES`（= 从拦截范围里摘掉） | `crossTenantGetIsNotFoundAndWritesNothing` | 表纳管遗漏是**静默**的：不报错，只是不再过滤 |
| `tenant_predicate_erased` | 多租户拦截器不再挂到 `MybatisPlusInterceptor` 上（谓词不再注入） | `crossTenantExecuteIsNotFoundAndWritesNothing` | 谓词缺失 = SQL 层完全不设防，而服务层第二道闸仍会挡 ⇒ 只有**分层**断言看得见 |
| `both_gates_removed`（复合） | 表豁免 **+** `requireBatch` 的显式租户比对一起摘掉 | `crossTenantRevertIsNotFoundAndWritesNothing` | 🔴 纵深防御的语义：任一层单独成立即可挡住 ⇒ **服务层那条断言**只有在两闸同时失效时才会红（否则它是一句永真话） |
| `new_table_without_tenant_id` | 终态 schema 追加一张**没有** `tenant_id`、也没登记豁免的新表 | `tenantInterceptionCoverageLedgersAreFrozen` | 类级元守卫（§23 G1/G2）：未登记即红、台账只许缩短 —— 只有这张新表能让它红 |
| `items_tenant_column_missing` | 明细表 DDL 去掉 `tenant_id` 列（**类级**红形态） | `<class>`（整类） | 「列不存在」是**响亮**失败：终态 schema 自己就建不起来（RLS 策略引用该列）⇒ 整类判据当场失败，而**不是**静默泄露 |

🔴 **两条「单层」注入为什么不是复合注入的重复**：只摘一层时，跨租户请求仍被**另一层**挡住
（服务层判据保持绿），这正是纵深防御；而分层写断言之后，单层注入各自**单独**打红对应的那一层。
没有 `both_gates_removed` 就没有任何东西能证明服务层断言有判别力 —— 它会被读成「反正都会 NOT_FOUND」。

🔴 **`items_tenant_column_missing` 为什么是「类级」而不是逐方法**（如实登记，不粉饰）：缺列时
① 终态 schema 的 RLS 策略/索引先引用该列 ⇒ 建库当场抛；② 即便建起来了，夹具的
`@BeforeEach` 清理语句也引用该列 ⇒ 每条判据都到不了自己的断言。故这里**只**声明「整类必红 +
红文本必须命中缺列错误」，**不冒充**逐方法判别力（逐方法的列存在性断言由
`agentBatchItemsAreInsideTenantInterception` 承载，其判别力由
`interceptor_table_registration_removed` 的共享覆盖面证明）。

## 用法

    python3 scripts/agent-batch-tenant-red-proof.py            # 跑全部变异（真注入 + 真跑判据，需 JDK + PG）
    python3 scripts/agent-batch-tenant-red-proof.py --only tenant_predicate_erased
    python3 scripts/agent-batch-tenant-red-proof.py --check    # 前提自检（门禁调用这个面；零 Maven/零副作用）

退出码（实跑面）：`0` = 全部变异都被对应判据抓到；`1` = 有判据**没有**判别力（或意外结果）；`3` = 无法判定。
退出码（`--check` 面）：`0` = 全部前提成立；`1` = 有腐烂（**具名**报出哪条变异烂在哪）；`3` = 无法判定。

## 报告卫生（issue #5216）

读数取自 `target/surefire-reports/**` ⇒ ① 跑 Maven **前先 `unlink`** 目标报告；
② 报告缺失 ⇒ **fail-closed 抛错**（无法判定），**绝不**回落读上一次变异的内容
（被并发抢 `target` / 编译失败打断时，旧报告会把环境事故读成「这条变异被抓到 / 没抓到」——
错误归因比没有红证更危险）。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from functools import partial
from pathlib import Path

import red_proof_harness as h  # noqa: E402  #5193 门禁调用的是 --check 面（零 Maven/零副作用）

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "backend/admin-api"
TOOL_REL = "scripts/agent-batch-tenant-red-proof.py"

CONFIG_REL = "backend/admin-api/src/main/java/com/migao/admin/config/MybatisPlusConfig.java"
SERVICE_REL = "backend/admin-api/src/main/java/com/migao/admin/service/AgentBatchService.java"
SCHEMA_REL = "backend/admin-api/src/main/resources/db/init/schema.sql"
TEST_REL = "backend/admin-api/src/test/java/com/migao/admin/service/AgentBatchCrossTenantRealDbTest.java"

TEST_CLASS = "AgentBatchCrossTenantRealDbTest"
TEST_FQN = f"com.migao.admin.service.{TEST_CLASS}"

#: 目标判据方法 → 它钉的那一格（打印用）
CRITERIA = {
    "crossTenantGetIsNotFoundAndWritesNothing": "判据 1 跨租户读：SQL 层看不见 + NOT_FOUND + 零写",
    "crossTenantExecuteIsNotFoundAndWritesNothing": "判据 2 跨租户执行：同上（+ A 仍能执行）",
    "crossTenantRevertIsNotFoundAndWritesNothing": "判据 3 跨租户撤销：同上（+ A 仍能撤销）",
    "agentBatchItemsAreInsideTenantInterception": "判据 4 明细表纳管：handler 不豁免 + 真库有列 + B 读不到",
    "tenantInterceptionCoverageLedgersAreFrozen": "判据 5 类级元守卫：豁免台账未登记即红 + 燃尽台账只许缩短",
}

#: 「整类」目标（逐方法结果不可得时用）：**只**声明「整类必红 + 红文本命中期望」，不冒充逐方法判别力。
CLASS_LEVEL = "<class>"

#: 整类红形态（缺列注入）：终态 schema 的 RLS 策略/索引 / 夹具清理语句引用该列 ⇒ PG 报缺列。
#: ⚠️ **两种 locale 都要认**（实测：本机 PG 是 zh_CN ⇒ `错误: 字段 "tenant_id" 不存在`；
#: CI runner 是英文 ⇒ `column "tenant_id" of relation ... does not exist`）—— 只钉英文措辞
#: 会把本机的**真红**读成「红形态与登记不符」（错误归因）。
CLASS_LEVEL_RED = (r'PSQLException[\s\S]{0,300}(column|字段) "tenant_id" '
                   r'(of relation "[^"]+" )?(does not exist|不存在)')


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def replace_once(text: str, anchor: str, replacement: str) -> str:
    """锚点必须在源码里命中**恰好 1 次**（0 次 = 漂移；>1 次 = 注入不确定）⇒ 否则报「锚点」。"""
    hits = text.count(anchor)
    if hits != 1:
        raise AssertionError(f"变异锚点出现 {hits} 次（要求恰好 1 次）—— 被测源码已漂移：{anchor[:70]!r}")
    return text.replace(anchor, replacement, 1)


# ── 五条变异（改语义，不是改文案）────────────────────────────────────────────
# 每条签名统一为 `(files: dict[rel → 原文]) -> dict[rel → 注入后]`（复合变异要动两个文件）。

def _exempt_batch_tables(files: dict) -> dict:
    """两张批次表被塞进豁免清单（= 从租户拦截范围里摘掉）。"""
    files[CONFIG_REL] = replace_once(
        files[CONFIG_REL],
        '            "notification_templates",\n'
        '            "notification_rules"\n'
        '    );',
        '            "notification_templates",\n'
        '            "notification_rules",\n'
        '            // [RED-PROOF] 两张批次表被塞进豁免清单 = 从拦截范围里摘掉\n'
        '            "agent_batches",\n'
        '            "agent_batch_items"\n'
        '    );')
    return files


def mutation_interceptor_table_registration_removed(files: dict) -> dict:
    """表纳管遗漏（静默：不报错，只是不再过滤）—— 判据 1 的红证形态。"""
    return _exempt_batch_tables(files)


def mutation_tenant_predicate_erased(files: dict) -> dict:
    """租户谓词不再注入（多租户拦截器没挂到 MybatisPlusInterceptor 上）—— 判据 2 的红证形态。"""
    files[CONFIG_REL] = replace_once(
        files[CONFIG_REL],
        '        // 添加多租户拦截器\n'
        '        interceptor.addInnerInterceptor(tenantLineInnerInterceptor());\n',
        '        // [RED-PROOF] 租户谓词不再注入：多租户拦截器未挂上\n')
    return files


def mutation_both_gates_removed(files: dict) -> dict:
    """两层闸（SQL 层纳管 + 服务层显式比对）同时摘掉 —— 服务层断言的红证形态（纵深防御）。"""
    files = _exempt_batch_tables(files)
    files[SERVICE_REL] = replace_once(
        files[SERVICE_REL],
        '        if (batch == null || (batch.getTenantId() != null && !batch.getTenantId().equals(tenantId))) {\n',
        '        if (batch == null) { // [RED-PROOF] 显式租户比对被摘掉（第二层闸）\n')
    return files


def mutation_new_table_without_tenant_id(files: dict) -> dict:
    """终态 schema 追加一张没有 tenant_id、也没登记豁免的新表 —— 类级元守卫的红证形态。"""
    files[SCHEMA_REL] = replace_once(
        files[SCHEMA_REL],
        '-- ================================================\n'
        '-- END OF SCHEMA\n'
        '-- ================================================\n',
        '-- [RED-PROOF] 新表没有 tenant_id 列、也没登记豁免（拦截器会给它注入 tenant_id 谓词）\n'
        'CREATE TABLE IF NOT EXISTS zz_redproof_unregistered (\n'
        '    id VARCHAR(64) PRIMARY KEY\n'
        ');\n\n'
        '-- ================================================\n'
        '-- END OF SCHEMA\n'
        '-- ================================================\n')
    return files


def mutation_items_tenant_column_missing(files: dict) -> dict:
    """明细表 DDL 去掉 `tenant_id` 列（拦截器注入的谓词会打到不存在的列）—— 类级红证形态。"""
    files[SCHEMA_REL] = replace_once(
        files[SCHEMA_REL],
        '    batch_id VARCHAR(64) NOT NULL REFERENCES agent_batches(id) ON DELETE CASCADE,\n'
        '    tenant_id BIGINT NOT NULL REFERENCES tenants(id),  -- 契约之外追加：租户插件会注入该列谓词\n',
        '    batch_id VARCHAR(64) NOT NULL REFERENCES agent_batches(id) ON DELETE CASCADE,\n'
        '    -- [RED-PROOF] 明细表的 tenant_id 列被去掉：拦截器注入的谓词将打到不存在的列\n')
    return files


MUTATIONS = [
    ("interceptor_table_registration_removed",
     "两张批次表被塞进豁免清单（表纳管遗漏）",
     mutation_interceptor_table_registration_removed, "crossTenantGetIsNotFoundAndWritesNothing"),
    ("tenant_predicate_erased",
     "租户谓词不再注入（拦截器未挂上）",
     mutation_tenant_predicate_erased, "crossTenantExecuteIsNotFoundAndWritesNothing"),
    ("both_gates_removed",
     "两层闸同时摘掉（纵深防御的语义）",
     mutation_both_gates_removed, "crossTenantRevertIsNotFoundAndWritesNothing"),
    ("new_table_without_tenant_id",
     "新表没有 tenant_id、也没登记豁免（元守卫）",
     mutation_new_table_without_tenant_id, "tenantInterceptionCoverageLedgersAreFrozen"),
    ("items_tenant_column_missing",
     "明细表 DDL 去掉 tenant_id 列（列不存在 ⇒ 整类响亮失败）",
     mutation_items_tenant_column_missing, CLASS_LEVEL),
]


def _probe(mutate, target: str, name: str) -> None:
    """一条变异的前提探针（**只读**）：被守卫文件可读 + 各注入锚点命中 1 次 + 目标判据存在。

    锚点检查走 `mutate` 本身（它内部用 `replace_once`）—— 因此「源码重构导致锚点失配」
    必然在这里被判成腐烂，而不是在实跑时静默注入失败。
    """
    guarded = sorted({CONFIG_REL, SERVICE_REL, SCHEMA_REL})
    files = {rel: h.read_source(rel, what=f"变异 [{name}] 的被守卫源码") for rel in guarded}
    test = h.read_source(TEST_REL, what=f"变异 [{name}] 的判据源码")
    if target == CLASS_LEVEL:
        # 「整类」目标：判据锚点不是某个方法，而是**这个类仍在**（类被改名/删掉 ⇒ 前提腐烂）。
        if not re.search(rf"class\s+{re.escape(TEST_CLASS)}\b", test):
            raise h.Rot(f"变异 [{name}]：判据类 {TEST_CLASS} 在判据源码里找不到 —— 该变异的红证目标不存在")
    else:
        h.require_method(test, target, what=f"变异 [{name}] 的目标判据")
    if mutate(dict(files)) == files:
        raise h.Rot("变异没有改变任何被守卫文件（锚点失配，或它与原文语义等价）")


def check() -> int:
    """前提自检（`--check`）：不注入、不跑判据、不写任何文件。"""
    decls = [h.declare(name, target, partial(_probe, mutate, target, name))
             for name, _label, mutate, target in MUTATIONS]
    return h.report_and_exit(TOOL_REL, decls)


def run_suite() -> dict:
    """跑整类，返回 {方法名: (是否通过, 失败文本)}。报告缺失 / 编译失败 ⇒ 抛错（**无法判定**）。

    ⚠️ 类级失败（建库 / `@BeforeAll` 炸）在 surefire 里是一条**名字为空**的 `testcase`
    ⇒ 这里照样收进来（键 `""`），由 `verdict()` 决定它算不算该变异的红形态。
    """
    report = MODULE / "target/surefire-reports" / f"TEST-{TEST_FQN}.xml"
    if report.exists():
        report.unlink()
    proc = subprocess.run(
        ["./mvnw", "-o", "-q", "test", f"-Dtest={TEST_CLASS}", "-DfailIfNoTests=false"],
        cwd=MODULE, capture_output=True, text=True)
    if not report.exists():
        raise AssertionError("surefire XML 未产出 ⇒ **无法判定**（不是通过）：\n"
                             + (proc.stdout or "")[-2500:] + (proc.stderr or "")[-1500:])
    results: dict = {}
    for case in ET.parse(report).getroot().iter("testcase"):
        bad = [child for child in case if child.tag in ("failure", "error")]
        text = "\n".join(f"{child.get('type') or ''} {child.get('message') or ''}\n{child.text or ''}"
                         for child in bad)
        results[case.get("name") or ""] = (not bad, text)
    return results


def verdict(results: dict, target: str) -> tuple[bool, str, str]:
    """该变异下「目标判据是否红 + 红形态」⇒ `(ok, note, observed)`（ok=False 即该条无判别力）。"""
    if target == CLASS_LEVEL:
        passed, text = results.get("", (True, ""))
        if passed:
            return False, "整类**没有**红（缺列注入下应当场失败）", ""
        if not re.search(CLASS_LEVEL_RED, text):
            return False, (f"整类红了，但红形态与登记不符（期望 /{CLASS_LEVEL_RED}/）"), text
        return True, "整类失败（缺列 ⇒ 建库/夹具当场炸，不是静默泄露），红文本命中期望", text
    if target not in results:
        return False, (f"报告里没有 {target} 这条判据（测试没跑起来）—— 实测方法集："
                       f"{sorted(k for k in results if k)[:8]}"), results.get("", (True, ""))[1]
    passed, text = results[target]
    if passed:
        return False, "该判据在报告里**没有失败**", ""
    return True, "该判据失败（判别力成立）", text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None, help="只跑指定变异（名字见 MUTATIONS）")
    parser.add_argument("--check", action="store_true",
                        help="只做前提自检（#5193 门禁调用的面）：零 Maven、零副作用、不注入")
    args = parser.parse_args()
    if args.check:
        return check()

    guarded = sorted({CONFIG_REL, SERVICE_REL, SCHEMA_REL})
    original = {rel: (REPO / rel).read_text(encoding="utf-8") for rel in guarded}
    original_hash = {rel: sha256(text) for rel, text in original.items()}
    print("被守卫源码（sha256 前 16 位）：")
    for rel in guarded:
        print(f"  · {rel}  {original_hash[rel][:16]}…")

    selected = [m for m in MUTATIONS if args.only is None or m[0] == args.only]
    if not selected:
        print(f"❌ 没有匹配的变异：{args.only}", file=sys.stderr)
        return 3

    failures: list = []
    try:
        baseline = run_suite()
        not_green = sorted(k for k, (ok, _) in baseline.items() if not ok)
        print(f"\n基线：{len(baseline)} 条判据，{'全绿 ✅' if not not_green else '有红 ❌ ' + str(not_green)}")
        if not_green:
            print("❌ 基线不绿 ⇒ 无法取红证（先修基线）", file=sys.stderr)
            return 1

        for name, label, mutate, target in selected:
            if target not in CRITERIA and target != CLASS_LEVEL:
                print(f"❌ 变异 {name} 的目标不在判据表里：{target}", file=sys.stderr)
                return 3
            mutated = mutate(dict(original))
            changed = sorted(rel for rel in guarded if mutated[rel] != original[rel])
            if not changed:
                print(f"❌ 变异 {name} 没有改变源码（锚点失配）—— **无法判定**", file=sys.stderr)
                return 3
            for rel in changed:
                (REPO / rel).write_text(mutated[rel], encoding="utf-8")
            print(f"\n── 变异 [{name}] {label}")
            print(f"   注入文件：{changed}")
            print(f"   期望变红：{target}"
                  + ("" if target != CLASS_LEVEL else "（**整类**：逐方法判别力不冒充，见 docstring）"))
            try:
                results = run_suite()
            finally:
                for rel in changed:
                    (REPO / rel).write_text(original[rel], encoding="utf-8")
                bad = [rel for rel in changed
                       if sha256((REPO / rel).read_text(encoding="utf-8")) != original_hash[rel]]
                if bad:
                    print(f"❌ 还原校验失败：{bad} 与注入前不一致 —— **停手人工核对**", file=sys.stderr)
                    return 1

            ok, note, observed = verdict(results, target)
            others_red = sorted(k for k, (v, _) in results.items() if k != target and not v)
            if ok:
                print(f"   ✅ {note}")
                if observed:
                    print(f"   逐字红形态（节选）：{' '.join(observed.split())[:220]}")
                if others_red:
                    print(f"   ℹ️ 共享覆盖面（同一次变异也命中这几条，属预期，不当失败）："
                          f"{['<类级>' if k == '' else k for k in others_red]}")
                else:
                    print("   ✅ 且只有它一条红（其余仍绿 ⇒ 该判据独立抓这一格）")
            else:
                print(f"   ❌ {target} **没有变红**：{note} ⇒ 这条判据没有判别力（空断言或未覆盖该缺陷）")
                if observed:
                    print(f"   实测红形态（节选）：{' '.join(observed.split())[:220]}")
                if others_red:
                    print(f"   ℹ️ 反而有别的判据红了（红被别处抓走）："
                          f"{['<类级>' if k == '' else k for k in others_red]}")
                failures.append(name)
    finally:
        for rel in guarded:
            if (REPO / rel).read_text(encoding="utf-8") != original[rel]:
                (REPO / rel).write_text(original[rel], encoding="utf-8")
        restored = [rel for rel in guarded
                    if sha256((REPO / rel).read_text(encoding="utf-8")) != original_hash[rel]]
        print("\n还原：" + ("✅ 全部与注入前逐字节相同" if not restored
                          else f"❌ 不一致 —— 人工核对 {restored}"))

    if failures:
        print(f"\n❌ 有 {len(failures)} 个变异没被对应判据抓到：{failures}", file=sys.stderr)
        return 1
    print(f"\n✅ 全部 {len(selected)} 个变异都被对应判据单独抓到（每条判据都有判别力）")
    return 0


if __name__ == "__main__":
    sys.exit(main())