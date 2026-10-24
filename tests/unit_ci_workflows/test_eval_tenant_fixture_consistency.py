# case_ids: DA-024
"""评测运行器的租户口径 ⇄ 夹具租户口径：不一致必须 **fail-closed 且具名**（issue #7048）。

## 病灶（2026-10-16，P6 定位 / 主会话独立核实）

历史病灶（2026-10-16）：`tests/agent_eval/local_runner.py` 的 `EVAL_TENANT_ID` 缺省 = 25
（当时的云测试租户），而夹具 `tests/agent_eval/fixtures/*_eval_seed.sql` 逐行写 tenant 1
⇒ 本地裸跑把前置探针/复位 SQL 打到 tenant 25 = 空 ⇒ `capture=0`，被折进「用例资产缺陷」。
2026-10-19（issue #7340）把缺省、容器、已部署入口统一收敛到 **seed 租户 1**，因此
**裸跑默认不再错配**；但「注入错租户（如 25 / 46）必须 fail-closed 且具名」这条护栏仍必须保留
（真库该工单 tenant1 = 1 行 / tenant25 = 0 行；显式传错时不能静默跑下去）。

## 本文件锁什么（判据 + 反向红证）

| # | 判据 | 坏形态（⇒ 必红） |
|---|---|---|
| ① | **接线**：`local_runner.py` 的自检 `detect_tenant_scope_mismatch` 必须在 `main()` 里被 await，且由 `scope_err` 守卫的 `sys.exit` 收口，**早于任何 `run_suite`** | 自检定义了却没调用（死代码）/ 出口被摘 ⇒ 红（判据名字与位置都点名） |
| ② | **判别力来源**：锚点查询**不带租户谓词**（`WHERE <key> = $1`）—— 带上 `EVAL_TENANT_ID` 就只会得到「查不到」，那正是本单要治的假归因 | 谓词回流 ⇒ 红 |
| ③ | **语义三态**：口径一致 ⇒ **不误报**；锚点行在任何租户都没有（**真夹具缺口**）⇒ **不误报**（不许被吞成"错配"，两条不许互相掩盖）；锚点只在别的租户下 ⇒ **必报**，且报错含 `EVAL_TENANT_ID` + **具体该设成几** + 夹具文件 + 判据文件 | 恒返回 None（fail-closed 失效）/ 改成"查不到就报"（会掩盖真夹具缺口）/ 报错丢掉要素（不可行动）⇒ 红 |
| ④ | **锚点覆盖台账（未登记即红 / 幽灵即红 / 只许缩短）**：`local_runner.py` 里**任何**按 `{EVAL_TENANT_ID}` 定位夹具对象的表，都必须有覆盖锚点登记 | 新增一张按租户定位的表却不登记 ⇒ 红；表不再被定位而台账仍留着 ⇒ 红 |

## 边界（照实登记，§19.1）

- 判据**不连库、不起栈、不跑真实 LLM**（零 LLM 静态 + 隔离命名空间求值）：它判「自检在不在、
  接线在不在、三态语义对不对、锚点覆盖有没有漏」；**「真库上确实报错」**这一格由
  `python tests/agent_eval/local_runner.py` 的跑前自检承担（读数写在本包 PR body）。
- 判据**不解析夹具 SQL 的取值**：锚点行对照是**证据式**的（读真库），静态面只钉
  「锚点键真的写在夹具文件里」——否则就是第二份会漂的口径。
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
FIXTURE_PATHS = (
    REPO_ROOT / "tests" / "agent_eval" / "fixtures" / "mibao_eval_seed.sql",
    REPO_ROOT / "tests" / "agent_eval" / "fixtures" / "xiaobu_eval_seed.sql",
)

# 本地 / CI 临时栈的租户（夹具逐行写的那个；同 `scripts/eval_stack_seed.sh` 的自证 SQL
# `WHERE tenant_id=1` 与 `test_eval_tenant_single_source.py` 的 LOCAL_STACK_TENANT_ID）
LOCAL_STACK_TENANT_ID = 1
# 评测租户的真值（2026-10-19 / #7340：本地栈、容器、agent-eval 三处统一 seed 租户 1）
CLOUD_TEST_TENANT_ID = 1
# 红证用的「不存在的租户」：旧的云测试租户 25（共享库已不再有它）
WRONG_TENANT_ID = 25

# 判据对象（消失即判据前提失效 ⇒ 红，不许静默变成空跑）
REQUIRED_NAMES = (
    "_env_int",
    "_SEED_AFTERSALES_TICKET_NO",
    "_SEED_PROCESSING_ORDER_NO",
    "TENANT_SCOPE_MISMATCH",
    "EVAL_TENANT_ID",
    "FIXTURE_TENANT_ANCHORS",
    "tenant_scope_mismatch_message",
    "tenant_scope_mismatch",
    "detect_tenant_scope_mismatch",
)

# 锚点覆盖台账：表 → 覆盖它的锚点（**未登记即红 / 幽灵即红**）。
# 只裁「按 `{EVAL_TENANT_ID}` 定位夹具对象」的表；新增一张这样的表而不登记 ⇒ 红
# （那条表上的租户错配没有任何自检覆盖）。表消失 ⇒ 删这一行（红过才删得掉）。
TENANT_SCOPED_FIXTURE_TABLES = {
    "after_sales_tickets": "锚点 = AS-20260914-9001（FIXTURE_TENANT_ANCHORS 直接覆盖）",
    "orders": "锚点 = EVAL-MB-ORD-0002（FIXTURE_TENANT_ANCHORS 直接覆盖）",
    "processing_orders": "经 orders 锚点覆盖（复位只按 order_id ← orders.order_no 子查询定位）",
}

# 租户谓词的占位符（带闭括号 —— `{EVAL_TENANT_ID_X}` 这类改名**不算**本判据的射程）
_TENANT_PLACEHOLDER = "{EVAL_TENANT_ID}"


# ── 取真实源码 / 隔离命名空间求值（**不 import 运行器本体**）──────────────────
# 为什么不 import：`local_runner.py` 有模块级 `import httpx` 与一堆模块级副作用，
# 而本文件跑在 ci-helper 腿（只装 pytest+pyyaml）里 —— 只取需要的节点执行。

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)  # `detect_*` 是 `async def`（AsyncFunctionDef）


def _runner_nodes(text: str) -> dict[str, ast.AST]:
    """取 `local_runner.py` 顶层里本判据需要的节点（AST，不求值整文件）。"""
    tree = ast.parse(text)
    wanted: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, _FUNC_NODES) and node.name in REQUIRED_NAMES:
            wanted[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in REQUIRED_NAMES:
                    wanted[t.id] = node
    return wanted


def runner_namespace(text: str, *, tenant: int | None = None) -> dict:
    """在**隔离命名空间**里执行运行器的租户自检实现。

    `tenant` 非 None 时**注入**「运行器生效租户」（这就是「把缺省改回 25」那一格的注入点：
    行的真实所在租户不变，只改运行器认的那个 —— 判据必须当场红）。
    """
    nodes = _runner_nodes(text)
    missing = [n for n in REQUIRED_NAMES if n not in nodes]
    assert missing == [], (
        f"local_runner.py 里缺判据对象 {missing} —— 判据前提失效（改名/删除都要连带改本文件）")
    ns: dict = {"os": os, "re": re}
    for name in REQUIRED_NAMES:
        if name.startswith("detect_"):
            continue  # 异步 + 需要 asyncpg：行为面由跑前自检的真实读数承担，这里只判接线
        exec(compile(ast.Module(body=[nodes[name]], type_ignores=[]),
                     f"<runner:{name}>", "exec"), ns)
    if tenant is not None:
        ns["EVAL_TENANT_ID"] = tenant
    return ns


# ── 判据实现（纯函数：真源码上必须 []，变异文本上必须非空且具名）───────────────

def _call_linenos(fn: ast.FunctionDef, name: str) -> list[int]:
    """函数体内某次调用的行号（`sys.exit` 按末段名 `exit` 取）。"""
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            got = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if got == name:
                out.append(node.lineno)
    return sorted(out)


def audit_wiring(text: str) -> list[str]:
    """① 接线：自检被 `main()` await、由 `scope_err` 守卫的 `sys.exit` 收口、且早于 `run_suite`。"""
    tree = ast.parse(text)
    main = next((n for n in tree.body
                 if isinstance(n, _FUNC_NODES) and n.name == "main"), None)
    if main is None:
        return ["local_runner.py 里找不到 main() —— 判据前提失效"]
    problems: list[str] = []
    detect_at = _call_linenos(main, "detect_tenant_scope_mismatch")
    if not detect_at:
        problems.append(
            "main() 没有调用 detect_tenant_scope_mismatch() —— 自检定义了却不接线（死代码），"
            "租户错配照旧静默折成「用例资产缺陷」")
    guarded = False
    for node in ast.walk(main):
        if isinstance(node, ast.If) and "scope_err" in ast.unparse(node.test):
            if _call_linenos(node, "exit"):
                guarded = True
    if not guarded:
        problems.append(
            "main() 里没有「scope_err ⇒ sys.exit」的 fail-closed 出口 —— 错配只打印不停手")
    runs = _call_linenos(main, "run_suite")
    if detect_at and runs and detect_at[0] > runs[0]:
        problems.append(
            f"自检调用（行 {detect_at[0]}）晚于 run_suite（行 {runs[0]}）—— 用例已经跑了，"
            "fail-closed 失效")
    return problems


def audit_preflight_query_is_tenant_agnostic(text: str) -> list[str]:
    """② 判别力来源：`detect_tenant_scope_mismatch` 的锚点查询**不得**带租户谓词。"""
    tree = ast.parse(text)
    fn = next((n for n in tree.body if isinstance(n, _FUNC_NODES)
               and n.name == "detect_tenant_scope_mismatch"), None)
    if fn is None:
        return ["local_runner.py 里找不到 detect_tenant_scope_mismatch —— 判据前提失效"]
    sqls: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "fetch" and node.args:
            try:
                sqls.append(ast.literal_eval(node.args[0]))
            except Exception:
                sqls.append(ast.unparse(node.args[0]))
    if not sqls:
        return ["detect_tenant_scope_mismatch 没有发起锚点查询 —— 判据空转"]
    problems: list[str] = []
    for sql in sqls:
        if "tenant_id" not in sql:
            problems.append(f"锚点查询没查 tenant_id（拿不到对照租户）：{sql!r}")
        if "EVAL_TENANT_ID" in sql:
            problems.append(
                f"锚点查询带了租户谓词 —— 判别力归零（查询自己只会得到"
                f"「查不到」= 本单要治的假归因）：{sql!r}")
    return problems


def audit_scope_semantics(ns: dict) -> list[str]:
    """③ 三态语义 + 报错要素（在注入命名空间上复算）。"""
    mismatch = ns["tenant_scope_mismatch"]
    probe = int(ns["EVAL_TENANT_ID"])
    other = WRONG_TENANT_ID if probe != WRONG_TENANT_ID else 46
    problems: list[str] = []
    if mismatch("工单", "AS-20260914-9001", {probe}) is not None:
        problems.append(f"口径一致（锚点就在 EVAL_TENANT_ID={probe} 下）却报错 —— 误报")
    if mismatch("工单", "AS-20260914-9001", {probe, other}) is not None:
        problems.append("锚点在多个租户下（含探针租户）却报错 —— 误报")
    for empty in ([], (), [None]):
        if mismatch("工单", "AS-20260914-9001", empty) is not None:
            problems.append(
                f"锚点行在任何租户都没有（{list(empty)!r} = 真夹具缺口）却报成「租户错配」"
                f" —— 两条会互相掩盖（真缺陷被吞成环境错配）")
    msg = mismatch("工单", "AS-20260914-9001", {other})
    if not msg:
        problems.append(
            f"锚点只在租户 {other} 下存在、而运行器 EVAL_TENANT_ID={probe} ⇒ "
            f"未报错（fail-closed 失效：本地裸跑会静默折成「用例资产缺陷」）")
        return problems
    for must in ("EVAL_TENANT_ID", f"EVAL_TENANT_ID={other}", str(probe),
                 "tests/agent_eval/fixtures/", "local_runner.py"):
        if must not in msg:
            problems.append(f"报错缺要素 {must!r}（不可行动 / 归因不明）：{msg!r}")
    return problems


def tenant_scoped_fixture_tables(text: str) -> set[str]:
    """现取：`{EVAL_TENANT_ID}` 内插行**所在语句**定位的表（回溯最近的 FROM/UPDATE/INTO）。

    整行注释**不计**（注释里提一句占位符不是一条按租户的查询）；本文件自己的台账说明与
    `detect_*` 里的 `{table}` 变量形态天然不在射程内。
    """
    tables: set[str] = set()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") or _TENANT_PLACEHOLDER not in line:
            continue
        for j in range(i, max(-1, i - 14), -1):
            m = re.search(r"\b(?:FROM|UPDATE|INTO)\s+([a-z_][a-z0-9_]*)", lines[j], re.I)
            if m:
                tables.add(m.group(1).lower())
                break
    return tables


def audit_anchor_ledger(text: str, anchor_tables: set[str]) -> list[str]:
    """④ 锚点覆盖：未登记即红 / 幽灵即红 / 判据不许空转。"""
    computed = tenant_scoped_fixture_tables(text)
    if not computed:
        return ["现取不到任何「按租户定位的夹具 SQL」—— 扫描器或 runner 形态变了（判据前提失效）"]
    problems: list[str] = []
    for extra in sorted(computed - set(TENANT_SCOPED_FIXTURE_TABLES)):
        problems.append(
            f"`{extra}` 是按租户定位的夹具对象却没登记覆盖锚点 —— 这张表上的租户错配"
            f"不会被跑前自检覆盖；请在 TENANT_SCOPED_FIXTURE_TABLES 登记")
    for ghost in sorted(set(TENANT_SCOPED_FIXTURE_TABLES) - computed):
        problems.append(
            f"台账幽灵条目 `{ghost}`（该表已不再按租户定位）—— 台账只许缩短："
            f"删这一行要连带改 TENANT_SCOPED_FIXTURE_TABLES")
    if not (anchor_tables & computed):
        problems.append(
            f"没有任何锚点落在按租户定位的表上（锚点表 = {sorted(anchor_tables)}，"
            f"现取表 = {sorted(computed)}）—— 判据空转")
    return problems


RUNNER_TEXT = RUNNER_PATH.read_text(encoding="utf-8")


# ── 真源码上的判据（必须全绿）────────────────────────────────────────────────

def test_wiring_is_real_and_runs_before_any_case():
    assert audit_wiring(RUNNER_TEXT) == [], (
        "跑前自检没有接进 main()（或晚于用例执行）—— 租户错配会照旧静默折成"
        "「用例资产缺陷」：\n" + "\n".join(audit_wiring(RUNNER_TEXT)))


def test_anchor_query_carries_no_tenant_predicate():
    problems = audit_preflight_query_is_tenant_agnostic(RUNNER_TEXT)
    assert problems == [], "锚点对照查询被加了租户谓词 ⇒ 判别力归零：\n" + "\n".join(problems)


def test_scope_semantics_hold_for_both_tenants():
    """③ 口径一致（缺省 / 本地栈 / 已部署入口同值 1）都**不得**误报。"""
    for tenant in (None, LOCAL_STACK_TENANT_ID):
        ns = runner_namespace(RUNNER_TEXT, tenant=tenant)
        problems = audit_scope_semantics(ns)
        assert problems == [], (
            f"EVAL_TENANT_ID={ns['EVAL_TENANT_ID']} 下三态语义判据判红：\n"
            + "\n".join(problems))


def test_anchor_ledger_covers_every_tenant_scoped_fixture_query():
    ns = runner_namespace(RUNNER_TEXT)
    anchor_tables = {a[1].lower() for a in ns["FIXTURE_TENANT_ANCHORS"]}
    problems = audit_anchor_ledger(RUNNER_TEXT, anchor_tables)
    assert problems == [], "锚点覆盖台账与现取的按租户定位面不一致：\n" + "\n".join(problems)


def test_anchors_are_really_seeded_in_the_fixtures():
    """前提自证（防锚点腐烂）：锚点键与表都真的写在夹具文件里。"""
    ns = runner_namespace(RUNNER_TEXT)
    fixture_text = "\n".join(p.read_text(encoding="utf-8") for p in FIXTURE_PATHS)
    for label, table, key_col, key_val in ns["FIXTURE_TENANT_ANCHORS"]:
        assert str(key_val) in fixture_text, (
            f"锚点键 {key_val!r}（{label}）不在任何夹具文件里 —— 锚点已腐烂，跑前自检会恒判「真夹具缺口」")
        assert table in fixture_text, f"锚点表 {table!r} 不在夹具文件里"


def test_bare_local_run_default_matches_stack(monkeypatch):
    """收口后：缺省 = 本地栈租户 ⇒ 裸跑不再错配（反向对照：不误报）。"""
    monkeypatch.delenv("EVAL_TENANT_ID", raising=False)
    default = runner_namespace(RUNNER_TEXT)["EVAL_TENANT_ID"]
    assert default == CLOUD_TEST_TENANT_ID, (
        f"运行器缺省租户实测 = {default}（期望 seed 租户 {CLOUD_TEST_TENANT_ID}）—— "
        f"配置再次漂移，请连带重算本文件")
    assert default == LOCAL_STACK_TENANT_ID
    problems = audit_scope_semantics(runner_namespace(RUNNER_TEXT, tenant=default))
    assert problems == []


def test_injected_wrong_tenant_is_still_detected():
    """护栏本体：夹具锚点在 1、运行器注入 25 ⇒ 必须报错，不许静默跑。"""
    ns = runner_namespace(RUNNER_TEXT, tenant=WRONG_TENANT_ID)
    msg = ns["tenant_scope_mismatch"]("工单", "AS-20260914-9001", {LOCAL_STACK_TENANT_ID})
    assert msg, "注入错租户却没判红 —— fail-closed 自检退化"
    assert "租户口径错配" in msg
    assert f"EVAL_TENANT_ID={LOCAL_STACK_TENANT_ID}" in msg


# ── 红证（注入式）：判据自己必须会红；对照：只改注释不红 ────────────────────

class TestRedProofs:
    """把「判据会不会红」钉在测试里（不依赖人工复算；每条先自证注入生效）。"""

    def test_injection_removes_wiring_reds(self):
        """① 把 main() 里的自检调用摘掉 ⇒ 接线判据当场红并具名。"""
        broken = RUNNER_TEXT.replace(
            "_scope_err = await detect_tenant_scope_mismatch()", "_scope_err = None", 1)
        assert broken != RUNNER_TEXT, "注入未生效（锚点失配）—— 红证前提失效"
        problems = audit_wiring(broken)
        assert problems != [], "摘掉接线却没判红 —— 判据没有判别力"
        assert "没有调用 detect_tenant_scope_mismatch" in problems[0]

    def test_injection_removes_exit_reds(self):
        """① 把 fail-closed 出口摘掉（只打印不停手）⇒ 接线判据当场红。"""
        broken = RUNNER_TEXT.replace(
            '        print(f"❌ {_scope_err}")\n        sys.exit(2)',
            '        print(f"❌ {_scope_err}")', 1)
        assert broken != RUNNER_TEXT, "注入未生效（锚点失配）—— 红证前提失效"
        problems = audit_wiring(broken)
        assert problems != [], "摘掉 sys.exit 出口却没判红"
        assert "fail-closed 出口" in problems[0]

    def test_injection_tenant_predicate_reds(self):
        """② 把租户谓词加回锚点查询 ⇒ 判别力来源判据当场红。"""
        broken = RUNNER_TEXT.replace(
            'f"SELECT DISTINCT tenant_id FROM {table} WHERE {key_col} = $1"',
            'f"SELECT DISTINCT tenant_id FROM {table} WHERE {key_col} = $1 '
            'AND tenant_id = {EVAL_TENANT_ID}"', 1)
        assert broken != RUNNER_TEXT, "注入未生效（锚点失配）—— 红证前提失效"
        problems = audit_preflight_query_is_tenant_agnostic(broken)
        assert problems != [], "谓词回流却没判红"
        assert "判别力归零" in problems[0]

    def test_injection_scope_semantics_degraded_reds(self):
        """③ 把「证据式」退化成恒不报（= 缺省 25 静默跑下去）⇒ 语义判据当场红。"""
        ns = runner_namespace(RUNNER_TEXT, tenant=CLOUD_TEST_TENANT_ID)
        ns["tenant_scope_mismatch"] = lambda label, key, tenants: None
        problems = audit_scope_semantics(ns)
        assert problems != [], "fail-closed 失效却没判红"
        assert any("fail-closed 失效" in p for p in problems)

    def test_injection_missing_branch_reds(self):
        """③ 反向：把判据改成「查不到就报错」⇒ 真夹具缺口会被吞成错配，语义判据必红。"""
        ns = runner_namespace(RUNNER_TEXT, tenant=CLOUD_TEST_TENANT_ID)
        ns["tenant_scope_mismatch"] = (
            lambda label, key, tenants: "租户口径错配（EVAL_TENANT_ID 与夹具不符）")
        problems = audit_scope_semantics(ns)
        assert problems != [], "「查不到就报」的退化形态没判红"
        assert any("互相掩盖" in p for p in problems)

    def test_injection_unregistered_tenant_scoped_table_reds(self):
        """④ 新增一张按租户定位的表而不登记 ⇒ 未登记即红。"""
        broken = RUNNER_TEXT + (
            '\n_FAKE_SQL = f"SELECT 1 FROM fake_fixture_table '
            'WHERE tenant_id = {EVAL_TENANT_ID} AND order_no = $1"\n')
        assert broken != RUNNER_TEXT
        ns = runner_namespace(RUNNER_TEXT)
        anchor_tables = {a[1].lower() for a in ns["FIXTURE_TENANT_ANCHORS"]}
        problems = audit_anchor_ledger(broken, anchor_tables)
        assert problems != [], "未登记的按租户定位表没判红"
        assert any("fake_fixture_table" in p for p in problems)

    def test_injection_ghost_ledger_entry_reds(self):
        """④ 台账幽灵（表不再被定位而台账仍留着）⇒ 只许缩短的判据当场红。"""
        broken = RUNNER_TEXT.replace(_TENANT_PLACEHOLDER, "{EVAL_TENANT_ID_X}")
        assert broken != RUNNER_TEXT, "注入未生效（锚点失配）—— 红证前提失效"
        problems = audit_anchor_ledger(broken, {"after_sales_tickets", "orders"})
        assert problems != [], "台账幽灵条目没判红"
        assert any("判据前提失效" in p for p in problems)

    def test_control_comment_only_change_stays_green(self):
        """对照：只加一行**注释**（含租户占位符）⇒ 各判据都**不得**误报。"""
        benign = RUNNER_TEXT + "\n# 说明：按租户定位的 SQL 形如 tenant_id = {EVAL_TENANT_ID}（注释不算）\n"
        assert benign != RUNNER_TEXT
        ns = runner_namespace(benign)
        anchor_tables = {a[1].lower() for a in ns["FIXTURE_TENANT_ANCHORS"]}
        problems = (audit_wiring(benign)
                    + audit_preflight_query_is_tenant_agnostic(benign)
                    + audit_scope_semantics(ns)
                    + audit_anchor_ledger(benign, anchor_tables))
        assert problems == [], "只改注释被误判：\n" + "\n".join(problems)


if __name__ == "__main__":  # 允许 `python <本文件>` 直跑（与仓内其它元守卫同口径）
    pytest.main([__file__, "-q"])
