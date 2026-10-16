# case_ids: FN-001, OR-001, OR-002, PR-001, PR-024
"""评测夹具 ⇄ 用例机器断言 数据依赖契约的 **pytest 套件**（issue #7043）。

判定本体在 `tests/agent_eval/eval_fixture_case_contract.py`（**单一实现**，本文件只把它的
读数变成会红的判据 + 注入式红证）。口径、判据表、边界见那个模块的 docstring —— 此处不重复。

跑法（零网络、零 DB、零 LLM）：

```bash
python3 -m pytest tests/agent_eval/test_eval_fixture_case_contract.py -q
```

⚠️ 弱断言纪律：本文件**不得**出现 `assert x is not None` / `assert x` 这类无信息量形态
（CI 的 `Check weak asserts in new tests` 扫新增测试文件）—— 每条断言都钉在**具体文本**上。

⚠️ **case_ids 说明（不编造）**：`.github/cases/` 里没有本判据这一域的条目（它是基建静态判据，
不是行为用例）⇒ 只声明**真实存在**的五个被保护用例。现取分配提示为 `MC-111`，但本包**不写进声明行**
（`QA Growth Gate` 的 G5 会把「声明了不存在的用例 ID」判 block）；该域要立条目时，由
`.github/cases/**` 的所有权包登记后追加。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# append（**不是** insert）：只作脚本模式的兜底解析路径，避免遮蔽同名模块（与同仓既有守卫同款理由）
sys.path.append(str(REPO_ROOT / "tests"))

from agent_eval import eval_fixture_case_contract as C  # noqa: E402


# ────────────────────────────────────────────────────────────────────────────
# 1. 真实语料：本仓必须绿（对照读数 —— 判据不得被自己的文案喂红）
# ────────────────────────────────────────────────────────────────────────────
def test_real_repo_satisfies_the_contract():
    print(f"[现取] 非空断言 = {sorted(C.collect_requirements(C.Root()))}")
    problems = C.contract_problems()
    assert problems == [], "本仓未通过数据依赖契约：\n" + "\n".join(f"  · {p}" for p in problems)


def test_requirement_scan_actually_sees_the_five_assertions():
    """扫描面本身有牙齿：现取必须至少看到 FN-001 那条（否则判据 1 是空断言）。"""
    reqs = C.collect_requirements(C.Root())
    assert "FN-001:finance_api:get_transactions:items" in reqs, (
        f"`FN-001` 的非空断言没被扫到 ⇒ 判据 1（未登记即红）退化成空断言。现取 = {sorted(reqs)}"
    )
    assert len(reqs) >= 5, f"非空断言只剩 {len(reqs)} 条 ⇒ 用例库或扫描口径变了，请复核台账"


# ────────────────────────────────────────────────────────────────────────────
# 2. 判据 1：未登记即红（把台账里 FN-001 那行拿掉）
# ────────────────────────────────────────────────────────────────────────────
def _ledger():
    import json

    return json.loads((REPO_ROOT / C.LEDGER_REL).read_text(encoding="utf-8"))


def test_unregistered_nonempty_assertion_is_named_red():
    ledger = _ledger()
    ledger["entries"].pop("FN-001:finance_api:get_transactions:items")
    problems = C.contract_problems(ledger=ledger)
    hits = [p for p in problems if "未登记即红" in p and "FN-001" in p]
    assert hits, f"拿掉 FN-001 的登记却没判红（判据 1 无牙齿）。现取 = {problems}"


# ────────────────────────────────────────────────────────────────────────────
# 3. 判据 3 + 判别力自证：剪掉 `finance_transactions` 的种子 ⇒ 具名报出 FN-001
#    （issue #7043 第 3 项作业；注入只改**内存**，不动仓库文件）
# ────────────────────────────────────────────────────────────────────────────
def test_removing_finance_seed_is_red_and_names_FN_001():
    base = C.Root()
    # 先自证注入真的生效（否则「没判红」分不清是判据没牙还是注入没进去）
    mutated = C.strip_seed_block(base, "tests/agent_eval/fixtures/mibao_eval_seed.sql", "finance_transactions")
    assert "INSERT INTO finance_transactions" not in C.strip_sql_comments(
        mutated.read_text("tests/agent_eval/fixtures/mibao_eval_seed.sql")
    ), "注入未生效：剪掉之后仍能扫到 `INSERT INTO finance_transactions`"

    problems = C.contract_problems(root=mutated)
    hits = [p for p in problems if p.startswith("FN-001:finance_api:get_transactions:items")]
    assert hits, f"剪掉流水种子后**没有**具名报出 FN-001（判别力缺失）。现取 = {problems}"
    assert any("finance_transactions" in p for p in hits), f"判红没点出缺的是哪张表：{hits}"


def test_unmutated_memory_overlay_is_green():
    """反向对照：同一份内存覆盖机制、不剪任何东西 ⇒ 不许报（否则上面的红证不可归因）。"""
    base = C.Root()
    overlay = C.Root(root=base.root, overlays={"tests/agent_eval/fixtures/mibao_eval_seed.sql": base.read_text("tests/agent_eval/fixtures/mibao_eval_seed.sql")})
    assert C.contract_problems(root=overlay) == []


def test_comment_mention_does_not_count_as_seed():
    """负控：把种子**降级成注释**（本缺陷的原始形态：文件里唯一命中它的那行是注释）⇒ 仍判红。"""
    base = C.Root()
    rel = "tests/agent_eval/fixtures/mibao_eval_seed.sql"
    text = base.read_text(rel)
    stripped = C.strip_seed_block(base, rel, "finance_transactions").read_text(rel)
    _ = text  # 只用于说明「原文 vs 注入后」两份文本都来自同一文件
    assert C.insert_statement_for(stripped, "finance_transactions") is None, (
        "注释形态仍被读成「种了数据」⇒ `strip_sql_comments` 这一层失效"
    )


# ────────────────────────────────────────────────────────────────────────────
# 4. 判据 2：台账未兑现即红（豁免只许缩短）
# ────────────────────────────────────────────────────────────────────────────
def test_ledger_entry_that_no_longer_matches_is_red():
    ledger = _ledger()
    ledger["entries"]["XX-999:ghost_tool:list:items"] = {
        "case_id": "XX-999", "tool": "ghost_tool", "action": "list", "field": "items",
        "kind": "seed",
        "why": "红证用：一条对不上任何现取断言的空转台账",
        "seed_evidence": {"file": "tests/agent_eval/fixtures/mibao_eval_seed.sql", "table": "finance_transactions"},
    }
    problems = C.contract_problems(ledger=ledger)
    assert any(p.startswith("XX-999:ghost_tool:list:items") and "已不存在" in p for p in problems), (
        f"空转台账没被判红（豁免就永远不会缩短）。现取 = {problems}"
    )


# ────────────────────────────────────────────────────────────────────────────
# 5. 判据 5：fail-closed（清空台账不是「消红」的路）
# ────────────────────────────────────────────────────────────────────────────
def test_empty_ledger_is_red():
    problems = C.contract_problems(ledger={"entries": {}})
    assert any("entries` 为空" in p for p in problems), f"清空台账竟能绿。现取 = {problems}"
