#!/usr/bin/env python3
# case_ids: FN-001, OR-001, OR-002, PR-001, PR-024
"""评测夹具 ⇄ 用例机器断言 的**数据依赖契约**（类级元守卫，铁律 8；issue #7043）。

## 治的形态（不是假说，有现取读数）

「**用例的机器断言依赖某张表 / 某份数据，而夹具没有提供**」——
于是断言**永远无解**，评测里出现**假红**，而假红在报告里长得像「黄金策查不到数据」⇒
被读成**产品缺陷**（本仓反复踩的归因盲区）。

现取实例（issue #7043 正文，逐字）：
`FN-001`（`.github/cases/finance.yml`）的机器断言 = `output_verify` 里
`tool: finance_api` / `action: get_transactions` / `expect: {items: __nonempty__}`；
而那个 action 读的是 `finance_transactions`（`backend/ai-agent-service/app/tools/finance_api.py`
的 `_get_transactions` → `GET /api/admin/finance/transactions`），
`tests/agent_eval/fixtures/mibao_eval_seed.sql` 此前**一行流水都没种** ⇒
上轮评测逐字：`❌ output_verify[finance_api]: items 期望非空，实际 []`。

## 判据（每一条都能单独变红；本文件同时是 pytest 套件与可执行自检）

| # | 判什么 | 回归时会怎么红 |
|---|---|---|
| 1 | **未登记即红**：`persona != xiaobu`（= mibao 腿 ∪ 双端）的用例里，任何「要求非空」的 `output_verify` 断言必须在台账 `eval_fixture_data_contract.json` 里登记 | 新增一条「非空」断言而没登记 ⇒ **具名报出** `<用例>:<工具>[:<action>]:<字段>` |
| 2 | **台账未兑现即红**（豁免只许缩短）：台账每条必须仍能对上一条**现取**的断言 | 断言被删 / 被改判 / 用例退役 ⇒ 台账这条成为空转 ⇒ 红（不许留着凑数） |
| 3 | **数据依赖必须真被提供**：`kind=seed` 的条目，其 `seed_evidence` 声明的表必须**真**出现在声明的种子文件里（**剥注释后**的 `INSERT INTO`，且与它在**同一条语句**内带幂等护栏）、该文件必须**注册在** `scripts/eval_stack_seed.sh`（那份种子真会被装进栈）、且该表在**唯一建库脚本** `backend/admin-api/src/main/resources/db/init/schema.sql` 里有 `CREATE TABLE` | 把那段种子删掉 / 把它降级成注释 / 把种子文件从 `eval_stack_seed.sh` 摘掉 / 表被删 ⇒ 红，且**具名回报它属于哪条用例** |
| 4 | **用例可归因**：台账的 `case_id` 必须在仓内真实存在 | 台账指着删掉的用例 ⇒ 红 |
| 5 | **fail-closed**：台账为空 ⇒ 红（清空台账「消红」这条路不存在） | 有人把 `entries` 清空 ⇒ 红 |
| 6 | **判别力自证**（注入式）：把 `finance_transactions` 那段种子从夹具里剪掉 ⇒ 判据 3 当场判红并**具名 FN-001**；未注入 ⇒ 不报（反向对照） | 判据退化成恒真/恒假 ⇒ 红 |
| 7 | **对照读数**：真实语料（本仓）上不得报任何一条 | 判据被自己的文案喂红（「举例即实例」）⇒ 红 |

## case_ids 说明（不编造）

本文件是**基建静态判据**，不是行为用例本身 —— `.github/cases/` 里**没有**「评测夹具 ⇄ 用例断言
数据依赖」这一域的条目。故只声明**真实存在**的五个被保护用例（`FN-001` / `OR-001` / `OR-002` /
`PR-001` / `PR-024` = 现取的 5 条「非空」断言所属用例）。本仓同期另有包在扩用例库；若该域要立条目，
应由 `.github/cases/**` 的所有权包登记后，把真实 ID 追加到上面的声明行（现取分配提示 = `MC-111`，
本包不写进去：声明一个不存在的 ID 会被 `QA Growth Gate` 的 G5 判「声明了不存在的用例 ID」）。

## 怎么跑（两条入口，同一份判定实现）

```bash
# ① 只用标准库（种子文件 / 用例库 / schema / 种子脚本 四个输入，零网络零 DB）
python3 tests/agent_eval/eval_fixture_case_contract.py --check

# ② pytest（需要 pyyaml，解析 `.github/cases/*.yml`）
python3 -m pytest tests/agent_eval/test_eval_fixture_case_contract.py -q
```

`scripts/eval_stack_seed.sh` 在 `--dry-run`（离线自检档）里调 ① —— 「种子在装什么」
与「用例断言要什么」两个口径因此**始终被同一份判定比对**，不需要起栈、不需要真 DB。

## 未固化 / 边界（照实登记，不粉饰；`migao-dev-flow` §19.1）

1. **射程 = `output_verify` 的「非空」形态**（`__nonempty__`），比对面 = **两端全部用例**
   （现取 5 条：4 条双端 / `FN-001`·`OR-001`·`OR-002`·`PR-001`，1 条 C 端 / `PR-024`）。
   为什么不能只按 mibao 腿收口：`xiaobu` 腿的栈只装 C 端种子，只比 B 端会**系统性漏掉 C 端**那一半。
   `db_verify` / `data_checks` 里点名的表**不在射程内**：`db_verify.fetch` 是**逻辑资源名**
   （`order_phone` / `order_by_client_request_id` …）而非表名，`data_checks` 是散文（现取：
   mibao 腿 **240** 条用例在 `data_checks` 里点到**真实表名**，其中绝大多数是**拒绝写入**语义）
   ⇒ 把它们纳入射程会把「不该有数据」读成「缺数据」= 假红。
   扩大射程前必须先能把「读依赖」与「拒绝写」分开。
2. **`kind=derived` 是本台账里唯一的「不算种子依赖」出口**，逐条带 `why` + `code_anchor`，
   且被判据 2（未兑现即红）约束 ⇒ 只许缩短。⚠️ 它**只**承重「对夹具数据面零依赖」这一件事：
   「这条断言本身满不满足」是另一件事，不在本判据职责内（`PR-024` 的 `why` 里写明了这一层没有实跑）。
3. **「建表」这一半靠 `schema.sql` 的既有机翻承担，本判据只做存在性核对**：评测栈（全新库）
   的建库 = `db/init/schema.sql`（基线）+ `db/migration/**` 的增量；而 `MigrationRunner` 的语义是
   「台账已有该键 ⇒ 跳过 / 库非空 ⇒ 只记账不执行 / 库为空 ⇒ 执行后记账」，且迁移建的表**必须**同时
   写进基线（`tests/unit_ci_workflows/test_schema_integrity.py` 的「建库脚本 ⊇ 迁移链」判据）⇒
   「基线里有 `CREATE TABLE`」= 「评测栈建得出这张表」。**本判据不另跑迁移**（那要起真库）。
   ⚠️ 因此它**判不了**一个陈旧的本机夹具库（真库上已记账但表没建出来）—— 那属环境刷新，不属本判据。
4. **CI 执行面：已接线**（issue #7048 · P2；本条原为「未固化项 #4：CI 执行面未接线」，2026-10-16 改判）。
   本判据落在 `tests/agent_eval/**`（issue #7043 明确指定，避开 `tests/unit_ci_workflows/**` 的并发包），
   而 CI 的 `ci workflow helper unit tests` 腿只跑 `tests/unit_ci_workflows`（`.github/workflows/pr-check.yml`
   的既有 argv，**一字不改**）⇒ 接线落在**收集面**那一层：同名再导出
   `tests/unit_ci_workflows/test_eval_fixture_case_contract_leg.py` 让本套件进那条腿的收集面
   （判定本体与断言仍只有本文件 + 同目录的 `test_eval_fixture_case_contract.py` 这一份）。
   常驻执行点因此有两个：① 上面那条 CI 腿 ② `scripts/eval_stack_seed.sh --dry-run`
   （本地与评测 workflow 的注种子步都会走到）。**残留边界（如实登记）**：那条腿的 argv 与两个台账
   （`helper_leg_shape_ledger.json` / `ci_execution_scope_ledger.json`）**未改**（收集面成员集合没变，
   多进来的是一个判据文件）；再导出漏一条断言时由
   `test_eval_fixture_case_contract_leg.py::test_this_reexport_covers_every_guard_test_in_the_source_suite` 判红。
5. **绿 ≠ 夹具完备**：本判据只保证「**已登记**的依赖真被提供」，不保证夹具在真实栈上的
   数据能过 admin-api 的读侧过滤（时间窗 / 权限 / 租户隔离）—— 那一层要真栈复跑。
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

LEDGER_REL = "tests/agent_eval/eval_fixture_data_contract.json"
CASES_DIR_REL = ".github/cases"
EVAL_CASES_REL = "tests/agent_eval/eval_cases"   # 目录型生成物（issue #8188）
SEED_SCRIPT_REL = "scripts/eval_stack_seed.sh"
SCHEMA_REL = "backend/admin-api/src/main/resources/db/init/schema.sql"
TOOLS_DIR_REL = "backend/ai-agent-service/app/tools"

#: 「非空」断言的取值标记（与 `tests/agent_eval/local_runner.py` 的 `OUTPUT_NONEMPTY` 同源语义；
#: 这里**不 import** 它 —— 那个模块模块级 `import httpx`，而本判据要在只装 pytest/pyyaml 的
#: `ci workflow helper unit tests` 环境里跑得起来）。
NONEMPTY_MARKER = "__nonempty__"

#: 台账 / 射程的用例面 = **两端全部用例**。
#: 为什么不是「只 mibao 腿」：本缺陷形态（断言要数据而夹具没给）与端无关 ——
#: 现取 5 条「非空」断言里 **4 条是双端、1 条是 C 端（PR-024）**；
#: 而 xiaobu 腿的栈 = C 端种子（`scripts/eval_stack_seed.sh` 的 xiaobu 分支只装那一份），
#: mibao 腿的栈 = C 端 + B 端 ⇒ 两端都要比，只按 mibao 收口会**系统性漏掉 C 端**。
EXCLUDED_PERSONA = None  # 保留常量名以便将来按 persona 收窄；当前不收窄

_SQL_BLOCK_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/")
_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


def strip_sql_comments(sql: str) -> str:
    """剥掉 SQL 注释。

    🔴 **必须剥**：夹具里「为什么要有这段」的说明**必然**提到表名与 `INSERT INTO`
    （本仓明令「删了要留说明」）⇒ 不剥注释就会把**说明文字**读成**已提供的种子**
    （#7043 的根因之一正是「文件里唯一命中 finance/流水 的一行是注释」）。
    """
    return _SQL_LINE_COMMENT_RE.sub(" ", _SQL_BLOCK_COMMENT_RE.sub(" ", sql))


# ────────────────────────────────────────────────────────────────────────────
# 输入读取（可注入：测试用 `Root` 指向临时树 / 用 `overlays` 在内存里剪掉一段种子）
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class Root:
    """判据的**全部输入**都经这里读 —— 注入式红证只改这里，不动仓库文件。"""

    root: Path = REPO_ROOT
    overlays: dict = None  # type: ignore[assignment]  # {仓库相对路径: 覆盖后的全文}

    def path(self, rel: str) -> Path:
        return self.root / rel

    def read_text(self, rel: str) -> str:
        if self.overlays and rel in self.overlays:
            return self.overlays[rel]
        return self.path(rel).read_text(encoding="utf-8")

    def exists(self, rel: str) -> bool:
        if self.overlays and rel in self.overlays:
            return True
        return self.path(rel).exists()

    def glob(self, pattern: str):
        return sorted(self.path("").glob(pattern))


def case_library(root: Root):
    """读 `.github/cases/*.yml`（唯一源；`eval_cases/` 是它的生成物）。

    ⚠️ 判据读**源**不读生成物：生成物由 `render_cases.py` 渲染，读它会把「忘了重渲染」
    误判成「夹具缺数据」（两件事必须可分辨）。
    """
    import yaml

    out = []
    for p in root.glob(f"{CASES_DIR_REL}/*.yml"):
        if p.name == "registry.yml":
            continue
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        for c in data.get("cases") or []:
            c = dict(c)
            c["_source_file"] = f"{CASES_DIR_REL}/{p.name}"
            out.append(c)
    return out


def cases_in_scope(cases):
    """台账/dep 比对面的用例（当前 = 全部；见 `EXCLUDED_PERSONA` 的注释）。"""
    if EXCLUDED_PERSONA is None:
        return list(cases)
    return [c for c in cases if str(c.get("persona") or "").strip().lower() != EXCLUDED_PERSONA]


def nonempty_requirements(c) -> dict:
    """该用例里「要求非空」的 `output_verify` 断言 ⇒ `{key: 说明}`。

    key 形态 = `<用例 ID>:<工具>[:<action>]:<字段>`（与台账同源）。
    """
    found = {}
    for spec in c.get("output_verify") or []:
        if not isinstance(spec, dict):
            continue
        tool = str(spec.get("tool") or "").strip()
        action = str(spec.get("action") or "").strip()
        for field_name, expected in (spec.get("expect") or {}).items():
            if isinstance(expected, str) and NONEMPTY_MARKER in expected:
                key = ":".join([str(c.get("id")), tool] + ([action] if action else []) + [str(field_name)])
                found[key] = {"tool": tool, "action": action, "field": str(field_name)}
    return found


def collect_requirements(root: Root) -> dict:
    """全仓「非空」断言台账（现取，不写死数字）。"""
    out = {}
    for c in cases_in_scope(case_library(root)):
        for key, meta in nonempty_requirements(c).items():
            out[key] = {**meta, "case_id": c.get("id"), "source_file": c.get("_source_file")}
    return out


# ────────────────────────────────────────────────────────────────────────────
# 静态解析件（零 DB、零网络）
# ────────────────────────────────────────────────────────────────────────────
def schema_tables(root: Root) -> set:
    sql = strip_sql_comments(root.read_text(SCHEMA_REL))
    return {m.group(1).lower() for m in re.finditer(rf"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+({_IDENT})", sql, re.I)}


def seed_tables(root: Root) -> set:
    """夹具里**真被种了数据**的表（剥注释后取 `INSERT INTO <表>`）。"""
    out = set()
    for p in root.glob("tests/agent_eval/fixtures/*.sql"):
        rel = p.relative_to(root.root).as_posix()
        sql = strip_sql_comments(root.read_text(rel))
        out |= {m.group(1).lower() for m in re.finditer(rf"INSERT\s+INTO\s+({_IDENT})", sql, re.I)}
    return out


def registered_seed_files(root: Root) -> set:
    """`scripts/eval_stack_seed.sh` 里**实际会装**的种子文件（单一实现的现取读数）。

    取法 = 该脚本里所有 `$FIXTURES/<名字>.sql` 形态的字面量（`SEED_FILES=(...)` 的初值
    与 mibao 分支的追加各一处）⇒ 两份种子都在册，与 persona 无关；
    真正的 persona 分支语义由 `tests/unit_ci_workflows/test_eval_stack_seed_parity.py` 锁。
    """
    text = root.read_text(SEED_SCRIPT_REL)
    return set(re.findall(r"\$FIXTURES/([A-Za-z0-9_.-]+\.sql)", text))


def tool_source_exists(root: Root, tool: str) -> bool:
    """工具源码在不在（**只读**校验，不改后端；`backend/**` 是别的包的所有权面）。"""
    return bool(tool) and root.exists(f"{TOOLS_DIR_REL}/{tool}.py")


def sql_statements(sql: str):
    """按 `;` 切语句（剥注释后）。**不做**完整 SQL 解析 —— 本判据只问「哪条 INSERT 种了哪张表」。"""
    return [s for s in strip_sql_comments(sql).split(";") if s.strip()]


def insert_statement_for(sql: str, table: str):
    """返回**种了** `table` 的那条 INSERT 语句原文（找不到 ⇒ None）。"""
    pat = re.compile(rf"INSERT\s+INTO\s+{re.escape(table)}\b", re.I)
    for stmt in sql_statements(sql):
        if pat.search(stmt):
            return stmt
    return None


def check_seed_entry(root: Root, entry: dict) -> list:
    """判据 3 的判定体：一条 `kind=seed` 条目必须真有可复现的种子支撑。"""
    problems = []
    key = entry.get("key")
    ev = entry.get("seed_evidence") or {}
    rel = str(ev.get("file") or "")
    table = str(ev.get("table") or "").lower()
    if not rel or not table:
        return [f"{key}: kind=seed 但 seed_evidence 缺 file / table（台账条目不完整）"]
    if not root.exists(rel):
        return [f"{key}: 种子文件不存在：{rel}"]
    stmt = insert_statement_for(root.read_text(rel), table)
    if stmt is None:
        return [f"{key}: 声明的表 `{table}` 在 {rel} 里**没有任何 INSERT**（夹具没提供这份数据）"]
    # 幂等形态：种子每次起栈都会重放 ⇒ 该条 INSERT 必须自带幂等护栏
    # （本仓口径 = `ON CONFLICT DO NOTHING` 或 `WHERE NOT EXISTS` 二选一，现取两种都在用）。
    if not re.search(r"ON\s+CONFLICT|WHERE\s+NOT\s+EXISTS", stmt, re.I):
        problems.append(f"{key}: `{table}` 的 INSERT 没有幂等护栏（`ON CONFLICT` / `WHERE NOT EXISTS`）"
                        f"⇒ 重放会与首跑冲突（seed 每次起栈都重放）")
    if table not in schema_tables(root):
        problems.append(f"{key}: 表 `{table}` 在唯一建库脚本 {SCHEMA_REL} 里没有 CREATE TABLE")
    basename = rel.rsplit("/", 1)[-1]
    if basename not in registered_seed_files(root):
        problems.append(f"{key}: 种子文件 `{rel}` **未注册**在 {SEED_SCRIPT_REL}（那份种子根本不会被装进任何栈）")
    return problems


def check_entry(root: Root, reqs: dict, entry: dict) -> list:
    problems = []
    key = str(entry.get("key") or "")
    if not key:
        return ["台账有条目缺 `key` 字段"]
    if key not in reqs:
        problems.append(f"{key}: 台账登记的断言在用例库里**已不存在**（未兑现的豁免只许缩短，不许留着凑数）")
    kind = str(entry.get("kind") or "")
    if kind not in ("seed", "derived"):
        problems.append(f"{key}: kind 必须是 seed / derived（收到 {kind!r}）")
        return problems
    if not str(entry.get("why") or "").strip():
        problems.append(f"{key}: 缺 `why`（为什么它需要种子 / 为什么它不需要）")
    if kind == "seed":
        problems += check_seed_entry(root, entry)
    else:
        anchor = str(entry.get("code_anchor") or "")
        if "::" not in anchor:
            problems.append(f"{key}: kind=derived 必须给 `code_anchor`（`<仓库相对路径>::<符号>`）")
        else:
            rel, sym = anchor.split("::", 1)
            if not root.exists(rel):
                problems.append(f"{key}: code_anchor 指向的文件不存在：{rel}")
            elif sym and sym not in root.read_text(rel):
                problems.append(f"{key}: code_anchor 的符号 `{sym}` 在 {rel} 里找不到")
    tool = reqs.get(key, {}).get("tool") or str(entry.get("tool") or "")
    if tool and not tool_source_exists(root, tool):
        problems.append(f"{key}: 工具 `{tool}` 在 {TOOLS_DIR_REL}/ 下找不到源码（用例断言着不存在的工具）")
    # 台账自洽：登记的 tool / action 必须与现取断言**逐字相同**（否则台账在描述另一个断言）
    if key in reqs:
        want = reqs[key]
        if str(entry.get("tool") or "") and str(entry.get("tool")) != want["tool"]:
            problems.append(f"{key}: 台账 tool={entry.get('tool')!r} 与现取断言 tool={want['tool']!r} 不一致")
        if str(entry.get("action") or "") != want["action"]:
            problems.append(f"{key}: 台账 action={entry.get('action')!r} 与现取断言 action={want['action']!r} 不一致")
    return problems


def contract_problems(root: Root = None, ledger: dict = None) -> list:
    """全部判据的**单一判定实现**（pytest 与 `--check` 共用）。返回具名问题清单（空 = 绿）。"""
    root = root or Root()
    problems = []

    ledger = ledger if ledger is not None else json.loads(root.read_text(LEDGER_REL))
    entries = ledger.get("entries") or {}
    if not entries:
        return ["台账 `entries` 为空 ⇒ fail-closed 判红（清空台账不是「消红」的路）"]

    reqs = collect_requirements(root)
    # 判据 1：未登记即红
    for key in sorted(set(reqs) - set(entries)):
        meta = reqs[key]
        problems.append(
            f"未登记即红：`{key}`（{meta['source_file']}）是一条**要求非空**的机器断言，"
            f"但 {LEDGER_REL} 里没有它 ⇒ 无从判定夹具是否提供了这份数据"
        )
    # 判据 2~5：逐条（`key` 的单一来源 = 台账的**对象键**，条目内不重复写 ⇒ 不会两份漂）
    for key in sorted(entries):
        problems += check_entry(root, reqs, {**entries[key], "key": key})

    # 判据 4：case_id 必须真实存在于仓内（用 `eval_cases.py` 的现取 ID 集 —— 它是
    # `.github/cases/*.yml` 的生成物，且 `render_cases.py` 只渲染**带 `id` 字段**的条目）
    if root.exists(EVAL_CASES_REL):
        pkg = root.path(EVAL_CASES_REL)
        src = ("".join(p.read_text(encoding="utf-8") for p in sorted(pkg.glob("*.py")))
               if pkg.is_dir() else root.read_text(EVAL_CASES_REL))
        known = set(re.findall(r"\bid\s*=\s*'([^']+)'", src))
        if not known:
            problems.append(f"{EVAL_CASES_REL}: 一条 `id=` 都没解析到（生成物形态变了 ⇒ 判据失效，不许静默绿）")
        for key, entry in sorted(entries.items()):
            cid = str(entry.get("case_id") or "")
            if cid and cid not in known:
                problems.append(f"{key}: 台账声明的 `case_id={cid}` 在 {EVAL_CASES_REL} 里不存在")
    return problems


# ────────────────────────────────────────────────────────────────────────────
# 判别力自证（注入式：把一段种子剪掉 ⇒ 必须具名报出对应用例）
# ────────────────────────────────────────────────────────────────────────────
_SEED_BLOCK_RE = re.compile(r"INSERT\s+INTO\s+{table}\b", re.I)
#: 「从 INSERT 起到下一个 `;`」的整段（够用且不跨语句 —— 种子里没有以分号结尾的字符串字面量）
_SQL_STMT_RE = re.compile(r"INSERT\s+[\s\S]*?;", re.I)


def strip_seed_block(root: Root, rel: str, table: str) -> Root:
    """返回一个「把 `rel` 里 `table` 的那条 INSERT 语句剪掉」的 `Root`（**只改内存**，不动仓库文件）。"""
    text = root.read_text(rel)
    pat = re.compile(rf"INSERT\s+INTO\s+{re.escape(table)}\b", re.I)
    hits = [m for m in _SQL_STMT_RE.finditer(text) if pat.search(m.group(0))]
    if len(hits) != 1:
        raise AssertionError(f"注入未生效：{rel} 里 `INSERT INTO {table}` 命中 {len(hits)} 处（期望恰好 1 处）")
    m = hits[0]
    stripped = text[: m.start()] + f"-- [injected] 这段种子被剪掉（判别力自证）：INSERT INTO {table}" + text[m.end():]
    return Root(root=root.root, overlays={**(root.overlays or {}), rel: stripped})


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in ("--check",):
        print(f"用法: {Path(__file__).name} [--check]", file=sys.stderr)
        return 2
    problems = contract_problems()
    if problems:
        print("❌ 评测夹具 ⇄ 用例机器断言 数据依赖契约判红（issue #7043）：")
        for p in problems:
            print(f"  · {p}")
        print(f"\n台账 = {LEDGER_REL}（未登记即红；豁免只许缩短）")
        return 1
    reqs = collect_requirements(Root())
    seeded = len(seed_tables(Root()))
    print(f"✅ 数据依赖契约成立：{len(reqs)} 条「非空」机器断言全部登记且其依赖真被提供"
          f"（夹具现取种了 {seeded} 张表）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
