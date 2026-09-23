# case_ids: PR-103, PR-104
"""真库判据「缺 PG ⇒ 静默变绿」的防回退锁（issue #5192）。

## 病灶（2026-09-23 复核后的剩余风险，非推断）

`*RealDbTest` 这批**最强证据层**在 CI 上**确实在跑** —— 但它们靠 `ubuntu-latest`（24.04）
镜像**恰好自带** PG 二进制（`/usr/lib/postgresql/16/bin`，`PgCluster.BIN_DIRS` 的 Debian 绝对
路径命中）才跑得起来：`admin-api-test` job **没有 `services:`、也不装 PG**（真库判据各自跑
一次性 `initdb` + `pg_ctl` 集群，要的是**二进制**而不是服务）。

⇒ **命中失败（镜像换代 / 换 runner / 自建 runner）时**，`Assumptions.abort` 会让「缺 PG」
与「通过」在 CI 结果列上**长得一样（都绿）**：全体真库判据**静默腐烂**，而**没有任何东西会变红**。

## 本守卫锁四条（每条都能**单独**变红，红证见 PR body）

1. **冻结常量**：测试树里「需要真 PG」的类集合 == 本文件登记的常量（删掉 / 改名 / 新增
   一份真库判据必须同批改常量 ⇒ 判据**不许悄悄消失**）；
2. **单一收口**：每个真库测试类要么直接调 `PgCluster.startOrAbort()`、要么经共用夹具
   `RemnantTestDb`（夹具内部收口），**且一律不得自带 `Assumptions.*`** ——
   缺 PG 的处置只许在 `PgCluster` 里有一份（复制逻辑 = 下一份拷贝各自演化）；
3. **CI fail-closed**：`pr-check.yml` 的 `admin-api-test` job **同时**有「PG 二进制前置断言
   （缺失 ⇒ `exit 1`）」+「跑测试那步注入了标记环境变量」，且**标记键名与 `PgCluster` 里的
   常量字面量逐字一致**（防止两边改名后各说各话）；
4. **fail-closed 分支存在且在 abort 之前**：`PgCluster` 里 `Assertions.fail(` 必须出现在
   `Assumptions.abort(` **之前** —— 防有人把 fail-closed 改回纯 abort（挪到后面 = 永不执行，
   而「代码里有 fail」这类弱断言照样绿）。

## 判据只读「代码」，不读文案（防判据被自己的注释喂绿）

所有 Java 侧断言先过 `_java_code_only()`（剥掉块注释 / 字符串 / 行注释）—— 否则
「注释里提一句 `Assertions.fail`」就能把第 4 条喂绿（同 `migao-dev-flow` §17.3 的
「判据被自己的文案喂红 / 喂绿」家族）。YAML 侧按 `jobs.<id>.steps` 结构取，不扫正则。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = REPO_ROOT / "backend" / "admin-api" / "src" / "test"
PG_CLUSTER = TEST_ROOT / "java" / "com" / "migao" / "admin" / "service" / "PgCluster.java"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"
JOB = "admin-api-test"

_SVC = "backend/admin-api/src/test/java/com/migao/admin/service/"
_MAP = "backend/admin-api/src/test/java/com/migao/admin/mapper/"

# ── 冻结常量（判据①）：需要真 PG 的测试类 ────────────────────────────────────────
# value = 它怎么拿到集群：
#   "direct"            = 自己调收口方法 `PgCluster.startOrAbort()`
#   "via:RemnantTestDb" = 经**共用夹具** `RemnantTestDb`（余料三个测试类共用一套 schema/夹具，
#                         issue #5146）—— 夹具内部收口，故这三个类**不直接**出现 `PgCluster`，
#                         这就是本表要**显式登记**的例外（不登记 = 判据②会把它判红）。
REALDB_FILES: dict[str, str] = {
    _SVC + "AutoBatchDispatchRealDbTest.java": "direct",
    _SVC + "AutoBatchDueScanRealDbTest.java": "direct",
    _SVC + "BatchAssignmentRuleRealDbTest.java": "direct",
    _SVC + "BatchConsumptionCuttingPlanRealDbTest.java": "direct",
    _SVC + "OrderUrgencyRealDbTest.java": "direct",
    _SVC + "PooledDispatchRealDbTest.java": "direct",
    # 类名不含 `RealDb`（`*RealMappingTest`）—— 判据①**不能**只扫 `*RealDbTest` 通配，
    # 否则这一类判据的改名/删除扫不出来（本守卫正是按「谁真去连真 PG」定义集合）。
    _SVC + "ProductionPartCodeRealMappingTest.java": "direct",
    _SVC + "ProductionScanClaimRealDbTest.java": "direct",
    _SVC + "RemnantRecoveryRealDbTest.java": "direct",
    _SVC + "SavingMetricsBoardRealDbTest.java": "direct",
    _SVC + "SkuBatchGuardRealDbTest.java": "direct",
    _MAP + "FabricRemnantMapperTest.java": "via:RemnantTestDb",
    _MAP + "RemnantItemSizeMapperTest.java": "via:RemnantTestDb",
    _SVC + "RemnantServiceTest.java": "via:RemnantTestDb",
}

# 共用夹具（不是判据本身，但同样必须走收口方法 —— 它是上述三个类的 PG 入口）
FIXTURE_FILE = _SVC + "RemnantTestDb.java"

# 收口方法（单一入口，issue #5192）
FUNNEL = "PgCluster.startOrAbort("
# 本机友好分支的**唯一**合法住所：缺 PG 的处置只许在 PgCluster 里有一份
SKIP_MARKER = "Assumptions.abort("
# CI fail-closed 分支
FAIL_MARKER = "Assertions.fail("


# ────────────────────────────────────────────── 工具

def _java_code_only(text: str) -> str:
    """剥掉注释与字符串字面量，只留**代码**（防「注释里提一句」把判据喂绿）。

    顺序要紧：先块注释（javadoc），再字符串/字符字面量，最后行注释 ——
    否则 JDBC URL 里的 `//` 会被当成行注释、把后半行代码整段吃掉（实测过）。
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', text)
    text = re.sub(r"'(?:[^'\\\n]|\\.)*'", "''", text)
    return re.sub(r"//[^\n]*", " ", text)


def _code_of(rel: str) -> str:
    return _java_code_only((REPO_ROOT / rel).read_text(encoding="utf-8"))


def _references_realdb(p: Path) -> bool:
    """该测试源文件是否**在代码里**引用真 PG 装配（注释里提一句不算）。"""
    if p.name == PG_CLUSTER.name:
        return False  # 收口件自身，不是判据
    code = _java_code_only(p.read_text(encoding="utf-8"))
    return "PgCluster" in code or "RemnantTestDb" in code


def _actual_realdb_files() -> set[str]:
    return {
        str(p.relative_to(REPO_ROOT)).replace("\\", "/")
        for p in sorted(TEST_ROOT.rglob("*.java"))
        if _references_realdb(p)
    }


def _job() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or {}
    assert JOB in jobs, f"{WORKFLOW.name} 里找不到 job `{JOB}`（被改名/删除？issue #5192）"
    return jobs[JOB]


def _steps(job: dict) -> list:
    return job.get("steps") or []


def _run_text(step: dict) -> str:
    return step.get("run") or ""


def _shell_code_only(text: str) -> str:
    """剥掉 shell 行注释 —— 防「注释里写一句 `exit 1 不要删`」把判据③喂绿。

    实测教训：本判据的**第一版**用裸子串判定，变异「把真正那句 `exit 1` 换成注释
    `: # 变异：本应 exit 1`」**没有让它变红**（注释里的 `exit 1` 满足了子串检查）——
    正是 `migao-dev-flow` §17.3 的「判据被自己的文案喂绿」家族。故改成
    **剥注释 + 行级精确匹配**（`^\\s*exit 1\\s*$`）。
    """
    return re.sub(r"(?m)(?:^|\s)#[^\n]*", "", text)


# ────────────────────────────────────────────── 判据① 冻结常量

def test_realdb_class_set_is_frozen():
    """真库判据的**类集合**变化即红 —— 删掉 / 改名一份判据不许悄悄发生（issue #5192 判据①）。"""
    expected = set(REALDB_FILES) | {FIXTURE_FILE}
    actual = _actual_realdb_files()
    assert actual == expected, (
        "真库判据集合与冻结常量不一致 —— 若你**有意**新增/删除/改名了一份需要真 PG 的判据，"
        "请同批更新 tests/unit_ci_workflows/test_realdb_failclosed.py 的 REALDB_FILES/FIXTURE_FILE"
        "（本仓口径：判据不许悄悄消失）。\n"
        f"  只在实际集合里（未登记 / 改名）：{sorted(actual - expected)}\n"
        f"  只在冻结常量里（被删 / 改名 / 不再需要真 PG）：{sorted(expected - actual)}"
    )


# ────────────────────────────────────────────── 判据② 单一收口

def test_every_realdb_class_goes_through_the_single_funnel():
    """每个真库测试类都走收口方法，且**一律不带** `Assumptions.*`（issue #5192 判据②）。"""
    problems = []
    for rel, how in sorted(REALDB_FILES.items()):
        code = _code_of(rel)
        if how == "direct":
            if FUNNEL not in code:
                problems.append(
                    f"{rel}: 未调用收口方法 `{FUNNEL})`（{how}）—— 缺 PG 的处置必须收口到 PgCluster")
        else:
            fixture = how.split(":", 1)[1]
            if f"{fixture}.start(" not in code:
                problems.append(f"{rel}: 未经共用夹具 `{fixture}.start(`（{how}）")
        if re.search(r"\bAssumptions\b", code):
            problems.append(
                f"{rel}: 自带 `Assumptions.*` 副本 —— 缺 PG 的处置只许在 PgCluster 里有一份"
                "（复制逻辑 = 下一份拷贝各自演化）")
    assert not problems, "真库判据未收口：\n  " + "\n  ".join(problems)


def test_only_pgcluster_may_abort_on_missing_pg():
    """`Assumptions.abort(` 在整个 admin-api 测试树里**只许有一处**（= PgCluster 的本机分支）。"""
    offenders = []
    for p in sorted(TEST_ROOT.rglob("*.java")):
        code = _java_code_only(p.read_text(encoding="utf-8"))
        if SKIP_MARKER in code and p != PG_CLUSTER:
            offenders.append(str(p.relative_to(REPO_ROOT)).replace("\\", "/"))
    assert not offenders, (
        "「缺 PG ⇒ 跳过」的话术副本又出现了（issue #5192；复制逻辑 = 下一份拷贝各自演化）：\n  "
        + "\n  ".join(offenders)
        + f"\n应当只调 `{FUNNEL})`（本机自动 skip / CI 自动判红都在它内部决定）。"
    )


# ────────────────────────────────────────────── 判据③ CI fail-closed

def test_admin_api_job_fails_closed_without_pg_binaries():
    """`admin-api-test` 必须**同时**有 PG 二进制前置断言与标记注入（issue #5192 判据③）。"""
    steps = _steps(_job())
    assert steps, f"{JOB} job 没有任何 step？"

    # ① 前置断言：某一步的 run 里真的**判缺**（同时提到 initdb 与 pg_ctl、且缺失时**独立一行** exit 1）
    #    —— 剥注释后按 `^\s*exit 1\s*$` 匹配：注释 / `echo "…exit 1…"` 都不算数。
    prechecks = []
    for s in steps:
        code = _shell_code_only(_run_text(s))
        if "initdb" in code and "pg_ctl" in code and re.search(r"(?m)^\s*exit 1\s*$", code):
            prechecks.append(s)
    assert prechecks, (
        f"`{JOB}` job 找不到「PG 二进制前置断言」（判据：某一步的 run 里同时出现 initdb/pg_ctl，"
        "且有**独立的** `exit 1`）。删掉它 ⇒ 镜像换代时真库判据退回**静默 skip（绿）**且无人发现"
        "（issue #5192）。\n"
        f"  现有 step 名：{[s.get('name') for s in steps]}"
    )

    # ② 标记注入：跑 mvnw test 的那一步必须注入 `PgCluster.REQUIRE_REALDB_ENV` 那个键
    src = PG_CLUSTER.read_text(encoding="utf-8")
    m = re.search(r'REQUIRE_REALDB_ENV\s*=\s*"([^"]+)"', src)
    assert m, ("`PgCluster` 里找不到 `REQUIRE_REALDB_ENV = \"…\"` 常量 —— "
               "判据③要拿它跟 workflow 的注入键名比对（两边必须逐字一致）")
    env_key = m.group(1)

    test_steps = [s for s in steps if "mvnw test" in _run_text(s)]
    assert test_steps, f"`{JOB}` job 找不到执行 `mvnw test` 的 step（改名了？）"
    injected = [
        s.get("name") for s in test_steps
        if str(((s.get("env") or {}).get(env_key)) or "").strip().lower()
        not in ("", "0", "false")
    ]
    assert injected, (
        f"`{JOB}` job 的 `mvnw test` step 未注入真库标记 `{env_key}`（真值 = 非空且非 0/false）。"
        "不注入 ⇒ 缺 PG 时 `PgCluster.startOrAbort()` 走本机分支（`Assumptions.abort`）⇒ "
        "CI 上「缺 PG」照样是**绿**（issue #5192 的原始病灶）。\n"
        f"  实际 env：{[(s.get('name'), s.get('env')) for s in test_steps]}"
    )


# ────────────────────────────────────────────── 判据④ fail-closed 分支存在且在 abort 之前

def test_pgcluster_keeps_fail_closed_branch_before_abort():
    """`PgCluster` 里 `Assertions.fail(` 必须存在、且**排在** `Assumptions.abort(` 之前（判据④）。"""
    code = _code_of(str(PG_CLUSTER.relative_to(REPO_ROOT)).replace("\\", "/"))
    assert FAIL_MARKER in code, (
        f"`PgCluster` 里没有 `{FAIL_MARKER}` 分支 —— 有人把 fail-closed 改回了纯 abort："
        "CI 上缺 PG 会退回**静默 skip（绿）**（issue #5192）。"
    )
    assert SKIP_MARKER in code, (
        f"`PgCluster` 里没有 `{SKIP_MARKER}` —— 本机开发友好分支被删了？"
        "（本机没装 PG 时 `mvnw test` 会直接红）"
    )
    assert code.index(FAIL_MARKER) < code.index(SKIP_MARKER), (
        f"`{FAIL_MARKER}` 出现在 `{SKIP_MARKER}` **之后** ⇒ fail-closed 分支永不执行"
        "（abort 先抛出），而「代码里有 fail」这种弱断言照样绿 —— 顺序即语义（issue #5192）。"
    )
