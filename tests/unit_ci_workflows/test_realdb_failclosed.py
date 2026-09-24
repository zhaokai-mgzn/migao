# case_ids: PR-103, PR-104, PR-107, PG-062
"""真库判据「缺 PG ⇒ 静默变绿」的防回退锁（issue #5192 Java 侧 / #5203 Python 侧）。

## 病灶（2026-09-23 复核后的剩余风险，非推断）

`*RealDbTest` 这批**最强证据层**在 CI 上**确实在跑** —— 但它们靠 `ubuntu-latest`（24.04）
镜像**恰好自带** PG 二进制（`/usr/lib/postgresql/16/bin`，`PgCluster.BIN_DIRS` 的 Debian 绝对
路径命中）才跑得起来：`admin-api-test` job **没有 `services:`、也不装 PG**（真库判据各自跑
一次性 `initdb` + `pg_ctl` 集群，要的是**二进制**而不是服务）。

⇒ **命中失败（镜像换代 / 换 runner / 自建 runner）时**，`Assumptions.abort` 会让「缺 PG」
与「通过」在 CI 结果列上**长得一样（都绿）**：全体真库判据**静默腐烂**，而**没有任何东西会变红**。

## 本守卫锁八条（每条都能**单独**变红，红证见 PR body）

Java 侧（issue #5192）：

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

Python 侧（issue #5203 —— 与 Java 侧**同形但不同源**，故 #5199 治不到）：

5. **冻结常量**：依赖真 PG 的测试**模块**集合 == `pg_cluster.REALDB_TEST_MODULES`
   （按 AST 判「谁真的去起集群」，**注释 / 文档串里提一句不算**）；
6. **单一收口**：13+1 个真库模块**零** `pytest.skip`、**零** `shutil.which`（只认 PATH = 病灶
   本身），且一律经收口夹具 `realdb_binaries`；全树任何「PG 关键词 + `pytest.skip`」只许在收口件里
   （剥注释与字符串后判定 ⇒ 文案喂不绿）；
7. **标记语义 + 行为级 fail-closed**：`MIGAO_REQUIRE_REALDB` 真值 = 非空且非 0/false；
   缺 PG 时**无**标记 ⇒ `pytest.skip`、**有**标记 ⇒ `pytest.fail`（改回纯 skip / 静默通过 ⇒ 红）；
8. **CI fail-closed**：`ci-workflow-tests` job 同样**同时**有「PG 二进制前置断言」+「pytest 那步
   注入 `pg_cluster.ENV_REQUIRE_REALDB`」。

## 判据只读「代码」，不读文案（防判据被自己的注释喂绿）

所有 Java 侧断言先过 `_java_code_only()`（剥掉块注释 / 字符串 / 行注释）—— 否则
「注释里提一句 `Assertions.fail`」就能把第 4 条喂绿（同 `migao-dev-flow` §17.3 的
「判据被自己的文案喂红 / 喂绿」家族）。YAML 侧按 `jobs.<id>.steps` 结构取，不扫正则；
Python 侧对应 `_py_code_only()`（同因），而「谁依赖真 PG」用 **AST** 判（排除 docstring）。
"""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest
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
    # issue #5327：批量批次（agent_batches / agent_batch_items）的跨租户隔离判据 ——
    # 起一次性真 PG 集群、用**生产拦截器 bean** 装配，逐条走收口方法 `PgCluster.startOrAbort()`。
    _SVC + "AgentBatchCrossTenantRealDbTest.java": "direct",
    _SVC + "AutoBatchDispatchRealDbTest.java": "direct",
    _SVC + "AutoBatchDueScanRealDbTest.java": "direct",
    _SVC + "BatchAssignmentRuleRealDbTest.java": "direct",
    _SVC + "BatchConsumptionCuttingPlanRealDbTest.java": "direct",
    _SVC + "BatchConsumptionLedgerRealDbTest.java": "direct",
    # issue #5243：基线语义判据（空库建终态 / 存量库不重放）**自带一次性真 PG 集群** ⇒ 登记。
    _SVC + "MigrationBaselineSemanticsTest.java": "direct",
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


def _job(name: str = JOB) -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or {}
    assert name in jobs, f"{WORKFLOW.name} 里找不到 job `{name}`（被改名/删除？issue #5192/#5203）"
    return jobs[name]


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


# ══════════════════════════════════════ Python 侧（issue #5203）══════════════════════════
# 病灶（与 Java 侧**同形但不同源** ⇒ #5199 治不到）：`ci-workflow-tests`（`ci workflow helper
# unit tests`）里 13 个真库模块的 PG 探测**只认 `PATH`**（`shutil.which`），而 runner 的 PG
# 二进制在 `/usr/lib/postgresql/16/bin`（**不在 PATH**）⇒ 83 条真库判据在 CI 上**一直静默 skip
# 成绿**（实测：CI 87 skip；「只藏 PG 三个二进制」精确复现 83 条）。
# 收口件 = `tests/unit_ci_workflows/pg_cluster.py`（发现 + 处置），夹具 = `conftest.realdb_binaries`。
PY_TESTS = REPO_ROOT / "tests" / "unit_ci_workflows"
PY_FUNNEL = PY_TESTS / "pg_cluster.py"
PY_JOB = "ci-workflow-tests"
#: 本守卫自身会**提到** PG 关键词与夹具名 ⇒ 扫描时必须排除（否则判据把自己判红）
SELF = "test_realdb_failclosed.py"
#: 非测试模块（收口件 / 夹具 / 包标记，都不是判据）
_NOT_TESTS = {SELF, PY_FUNNEL.name, "conftest.py", "__init__.py"}


def _py_code_only(text: str) -> str:
    """剥掉注释与字符串**内容**，只留代码（防「注释里提一句」把判据喂绿 —— #5199 的 M4 变异实证过）。"""
    text = re.sub(r'"""(?:.|\n)*?"""', '""', text)
    text = re.sub(r"'''(?:.|\n)*?'''", "''", text)
    text = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', text)
    text = re.sub(r"'(?:[^'\\\n]|\\.)*'", "''", text)
    return re.sub(r"#[^\n]*", " ", text)


def _load_py_funnel():
    """按**路径**加载收口件（不依赖 pytest 的 import 模式；判据⑤~⑦ 都读它的真值）。"""
    spec = importlib.util.spec_from_file_location("_pg_cluster_under_test", PY_FUNNEL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _docstring_ids(tree) -> set[int]:
    """模块 / 类 / 函数**文档串**的节点 id（文档串也是「文案」，判据⑤必须排除）。

    ⚠️ 只认这四类节点的 `body[0]`：`ast.Lambda` / `ast.IfExp` 也有 `body`，但那是**表达式**
    （不可下标）—— 实测踩过 `TypeError: 'Attribute' object is not subscriptable`。
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            out.add(id(first.value))
    return out


def _actual_py_realdb_modules() -> set[str]:
    """AST 判「这个测试模块**真的**依赖真 PG」（注释 / 文档串里提一句**不算**）。

    两条信号任一命中：① 引用收口夹具 / 收口模块（`realdb_binaries` / `pg_cluster`）；
    ② argv 里出现**恰为** `"initdb"` / `"pg_ctl"` 的字符串常量（= 自己起集群，正是要拦的拷贝形态）。
    本仓有 7 个文件只在**注释 / 文档串**里提 `docker-entrypoint-initdb.d`（`initdb` 的中止语义），
    它们**不是**真库判据 —— 所以判据必须建在 AST 上，不能扫裸子串。
    """
    found: set[str] = set()
    for p in sorted(PY_TESTS.glob("test_*.py")):
        if p.name in _NOT_TESTS:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        docs = _docstring_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in {"realdb_binaries", "pg_cluster"}:
                found.add(p.name)
                break
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in docs and node.value in {"initdb", "pg_ctl"}:
                found.add(p.name)
                break
    return found


#: PG 关键词（判据⑥的全树扫描用；`\bPG\b` 防命中 `PGN` 之类）
_PG_KEYWORD = re.compile(r"(?i)postgres|initdb|pg_ctl|真库|\bPG\b")


def _pg_skip_calls_in(p: Path) -> list[str]:
    """该文件里**代码层面**的 `pytest.skip(...)` 调用中命中 PG 关键词的那些。

    ⚠️ 用 AST 取**调用节点的源码段**（`ast.get_source_segment`）：注释**不在**节点源码里 ⇒
    「注释里写一句 `pytest.skip` 说明历史」不会把判据喂红（本判据第一版就自伤在这里：
    `conftest.py` 有一条解释病灶的注释里带了 `pytest.skip`）。
    """
    text = p.read_text(encoding="utf-8")
    out: list[str] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "skip" and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == "pytest":
            seg = ast.get_source_segment(text, node) or ""
            if _PG_KEYWORD.search(seg):
                out.append(f"{p.name}:{node.lineno}: {seg.splitlines()[0].strip()}")
    return out


# ────────────────────────────────────────────── 判据⑤ 冻结常量（Python 侧）

def test_python_realdb_module_set_is_frozen():
    """依赖真 PG 的 **Python** 测试模块集合 == 收口件的冻结登记表（issue #5203 判据⑤）。"""
    expected = set(_load_py_funnel().REALDB_TEST_MODULES)
    actual = _actual_py_realdb_modules()
    assert actual == expected, (
        "真库（Python）判据集合与冻结登记表不一致 —— 有意新增 / 删除 / 改名一份真库判据时，"
        "请同批更新 tests/unit_ci_workflows/pg_cluster.py 的 REALDB_TEST_MODULES"
        "（本仓口径：判据不许悄悄消失，也不许悄悄多一份拷贝）。\n"
        f"  只在实际集合里（未登记 / 改名 / 新增）：{sorted(actual - expected)}\n"
        f"  只在登记表里（被删 / 改名 / 不再需要真 PG）：{sorted(expected - actual)}"
    )


# ────────────────────────────────────────────── 判据⑥ 单一收口（Python 侧）

def test_only_py_funnel_may_skip_on_missing_pg():
    """「缺 PG ⇒ skip」的副本只许在收口件里（issue #5203 判据⑥；**剥注释与字符串后**判定）。"""
    funnel = _load_py_funnel()
    problems: list[str] = []
    for name in sorted(funnel.REALDB_TEST_MODULES):
        code = _py_code_only((PY_TESTS / name).read_text(encoding="utf-8"))
        if "pytest.skip(" in code:
            problems.append(
                f"{name}: 自带 `pytest.skip(` —— 缺 PG 的处置只许在 pg_cluster.require_pg()")
        if "realdb_binaries" not in code:
            problems.append(f"{name}: 未经收口夹具 `realdb_binaries`（自己解析二进制路径？）")
        if re.search(r"\bshutil\.which\b", code):
            problems.append(f"{name}: 又出现 `shutil.which`（只认 PATH = 本 issue 的病灶）")
    # 全树：任何「PG 关键词 + pytest.skip」只许出现在收口件里（AST 取调用源码段 ⇒ 注释不算）
    for p in sorted(PY_TESTS.rglob("*.py")):
        if p.name in {PY_FUNNEL.name, SELF}:
            continue
        problems.extend(_pg_skip_calls_in(p))
    assert not problems, (
        "Python 侧真库判据未收口（issue #5203；复制逻辑 = 下一份拷贝各自演化）：\n  "
        + "\n  ".join(problems)
        + "\n应当只调收口夹具 `realdb_binaries`（缺 PG 时 CI 判红 / 本机 skip 都在它内部决定）。"
    )


# ────────────────────────────────────────────── 判据⑦ 标记语义 + 行为级 fail-closed

def test_require_realdb_flag_is_fail_closed(monkeypatch):
    """标记语义（非空且非 0/false）+ **行为级** fail-closed（改回纯 skip ⇒ 红，issue #5203 判据⑦）。"""
    funnel = _load_py_funnel()
    for value, expected in (("1", True), ("true", True), ("yes", True),
                            ("0", False), ("false", False), ("", False)):
        monkeypatch.setenv(funnel.ENV_REQUIRE_REALDB, value)
        assert funnel.require_realdb() is expected, (
            f"`{funnel.ENV_REQUIRE_REALDB}={value!r}` 应判 {expected}（真值 = 非空且非 0/false）")
    monkeypatch.setattr(funnel, "missing", lambda: list(funnel.PG_BINARIES))

    monkeypatch.delenv(funnel.ENV_REQUIRE_REALDB, raising=False)
    # 无标记 ⇒ 必须 `Skipped`（本机开发友好）。若改判成 `Failed`，异常逃出上下文管理器 ⇒ 红。
    with pytest.raises(pytest.skip.Exception):
        funnel.require_pg()

    monkeypatch.setenv(funnel.ENV_REQUIRE_REALDB, "1")
    # ⚠️ 这里**不能**用 `pytest.raises(pytest.fail.Exception)`：真回归（改回纯 skip）抛的是
    # `Skipped`，它会**逃出**上下文管理器被 pytest 记成「跳过」—— 判据自己变成静默绿。
    # 故显式捕获后**断言异常类型**（「抛了别的」与「什么都没抛」都判红）。
    captured: BaseException | None = None
    try:
        funnel.require_pg()
    except BaseException as exc:  # noqa: BLE001 —— 含 pytest.skip.Exception（最危险的回归形态）
        captured = exc
    assert isinstance(captured, pytest.fail.Exception), (
        f"带 `{funnel.ENV_REQUIRE_REALDB}=1` 且缺 PG 时，`require_pg()` 的结果是 "
        f"{type(captured).__name__ + '（' + str(captured) + '）' if captured else '**什么都没抛**'} "
        "—— 必须判 **FAIL**（`pytest.fail`），不是 skip、更不是静默通过："
        "CI 上「真库判据没跑」绝不能是绿（issue #5203）。"
    )


# ────────────────────────────────────────────── 判据⑧ CI fail-closed（Python 侧）

def test_ci_workflow_tests_job_fails_closed_without_pg_binaries():
    """`ci-workflow-tests` 必须**同时**有 PG 二进制前置断言与标记注入（issue #5203 判据⑧）。"""
    steps = _steps(_job(PY_JOB))
    assert steps, f"{PY_JOB} job 没有任何 step？"
    prechecks = [
        s for s in steps
        if "initdb" in _shell_code_only(_run_text(s))
        and "pg_ctl" in _shell_code_only(_run_text(s))
        and re.search(r"(?m)^\s*exit 1\s*$", _shell_code_only(_run_text(s)))
    ]
    assert prechecks, (
        f"`{PY_JOB}` job 找不到「PG 二进制前置断言」（判据：某一步的 run 里同时出现 initdb/pg_ctl，"
        "且有**独立的** `exit 1`）。删掉它 ⇒ 镜像换代时 Python 侧真库判据退回**静默 skip（绿）**"
        f"且无人发现（issue #5203）。\n  现有 step 名：{[s.get('name') for s in steps]}"
    )
    env_key = _load_py_funnel().ENV_REQUIRE_REALDB
    test_steps = [s for s in steps if "pytest" in _run_text(s)]
    assert test_steps, f"`{PY_JOB}` job 找不到执行 pytest 的 step（改名了？）"
    injected = [
        s.get("name") for s in test_steps
        if str(((s.get("env") or {}).get(env_key)) or "").strip().lower()
        not in ("", "0", "false")
    ]
    assert injected, (
        f"`{PY_JOB}` job 的 pytest step 未注入真库标记 `{env_key}`（真值 = 非空且非 0/false）。"
        "不注入 ⇒ 缺 PG 时 `pg_cluster.require_pg()` 走本机分支（skip）⇒ CI 上「缺 PG」照样是**绿**"
        f"（issue #5203 的原始病灶）。\n  实际 env：{[(s.get('name'), s.get('env')) for s in test_steps]}"
    )
