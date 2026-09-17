# case_ids: PG-013, CH-005, AS-006, OR-006, CH-021, KN-006, DF-015
"""`skip_reason` 豁免口子的**结构与账本**判据（零 LLM，秒级，纯静态）。

## 病灶（本仓实证：334 行含 `skip_reason` ⇒ 156 条用例**根本不跑**）

`tests/agent_eval/eval_case_filter.select_cases_for_persona` 与
`local_runner.run_case`（按 `case.skip_reason` 检索）都把非空 `skip_reason` 的用例
**直接剔除**；`local_runner` 的选档函数（`_cases_by_tier` 一族）同样 `not c.skip_reason`。
⇒ **skip = 零证据**，而且此前：

| 缺口 | 后果（实证） |
|---|---|
| 无类别 | 看不出是「后端契约用例不该进 LLM 层」（**合法**）还是「没数据源/没写完/不想修」（**债务**） |
| 无到期、无追踪 | `CH-036/037/038`、`PP-010` 长期零证据而**没有任何东西会变红** |
| 无总量约束 | 豁免可以无限增长（`case_trust_gate` 只管断言可信度，**不读 `skip_reason`**） |

## 本文件锁的判据（全部建在**结构**上：常量表 + 字段存在性 + 日期比较 + 基线比对）

1. **类别前缀必须是判据里写死的四类之一**（`SKIP_CATEGORIES`）——未带前缀 / 未知类别 / 前缀后无说明 ⇒ 红。
   新类别必须改本文件的常量表（= 一次**有意识**的决策），不得靠"措辞里含某词"蒙混（R5）。
2. **债务三类**（`wip` / `no-data-source` / `deprecated`）必须带 `skip_issue`（正整数）
   **且** `skip_expires`（`YYYY-MM-DD`，未过期）⇒ 缺失或过期即红。
3. **`backend-contract` 允许无到期，但必须被测试钉住**：`traces.tests` 非空
   （否则它就是"永远不跑的借口"）。引用的存在性/可收集性由 **#4120 的守卫**承担
   （`tests/unit_ci_workflows/test_eval_evidence_chain.py`），本文件**不重复实现**，
   只要求"有钉住它的测试"这一结构性事实。
4. **总量只许缩**：`.github/skip-exemption-baseline.json` 记锚定 SHA + `skip_total`；
   用例库非空 skip 数 **> 基线 ⇒ 红**（净增即红；**不设** per-PR 强制消减，留给后续裁定）。
5. **存量按基线放行，新增一律 fail-closed**：只有 `pending_classification` 里的 ID
   可暂时不合规（时限 `pending_expires`，过期即红）；其余任何 ID（含**新增**用例）
   必须完全合规。基线里的 `legacy_skip_ids` 是锚点快照，`pending` 只许是其子集
   **且只许缩短** ⇒ 不许把新 skip 偷偷挂进豁免。

## 本文件**不**判（如实登记边界，防被读成「有硬门禁」）

- **`skip_reason` 的语义是否成立**（"这些单测真的覆盖了这条用例吗"）＝语义判断，静态判不了；
  静态只能判"它点名的测试**跑得起来**"（#4120）与"类别/字段/账本**形状**对"（本文件）。
- **`skip_issue` 指向的 issue 是否 open**：离线无 GitHub API，**不判** —— 判据只查
  "追踪号存在且是正整数"。本条曾让 `#3917`（已 CLOSED）成为 `PG-013/015/016` 的
  "追踪号"，故这三条**留在 pending**（缺 live 追踪号），见基线 `missing` 字段。
- **基线文件被人为改写**（把 `skip_total` 抬高 / 把新 ID 塞进 `legacy_skip_ids`）：
  纯静态、无 git 历史的 job（`pr-check.yml` 的 `ci workflow helper unit tests` 是
  `fetch-depth: 1`）做不到与 `origin/main` 基线对账（`case_trust_gate` 那套靠
  `fetch-depth: 0` 的独立 job）。本文件用 `history` 账本（`skip_total` 只许非增）+
  `pending ⊆ legacy` 增加摩擦力，**但那不是密码学封印** —— 改基线是**显式的、
  会被 diff 看见的**动作，与仓里其它基线同一信任模型。
- **`eval_case_filter` 之外的其它剔除路径**：本文件只判"写法与账本"，不判 runner 是否
  真的用 `skip_reason` 过滤（那是 runner 的行为，由 runner 侧测试承担）。
- **生成物账本里看不到 `skip_issue` / `skip_expires`**：`render_cases.py` 只渲染
  `skip_reason` 与 `traces` 之外的少量字段 ⇒ casebook md / `eval_cases.py` 里**没有**
  这两个追踪字段（`migao-dev-flow` §18.5「账本里看不出来的字段 = 缺陷的盲区」）。
  本判据直接读 `.github/cases/*.yml`，不受该盲区影响；账本侧的补齐属 `render_cases.py`
  的所有权（该文件有在飞分支），**本 PR 未做**，如实登记。
- **同一用例块里重复声明 `skip_reason`**：轻量装载器（`yaml_light`）是"后键覆盖"，
  故**最后一个**声明才是真值（实测存量仅 `OR-031` 一块有此形态，其前半段 `merge_log/traces/
  pre_clean/skip_reason` 被后半段静默覆盖）。本判据读**装载后的 dict**，与
  `eval_case_filter` / runner 的运行期真值**同源**；重复声明本身的清理不属本判据。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
BASELINE_PATH = REPO_ROOT / ".github" / "skip-exemption-baseline.json"

sys.path.insert(0, str(REPO_ROOT / ".github"))
# 用例库的**唯一**装载路径（与 eval runner / 其它 L0 守卫同源）：第二套解析口径必然漂移。
import render_cases  # noqa: E402

# ── 判据本体：类别集合**写死在这里**（新类别 = 改本常量表 = 一次有意识决策）──
# `debt=True` 的三类必须可追踪：`skip_issue` + `skip_expires`（到期即红）。
# `needs_pinned_test=True` 的类别必须给出钉住它的测试（`traces.tests`）——
# `[backend-contract]` = "该用例的正确判定层在单测/后端，不在 LLM 层"，
# 它**允许无到期**，但"没有钉住它的测试"就不成立（否则 = 永远不跑的借口）。
SKIP_CATEGORIES: dict[str, dict] = {
    "backend-contract": {"debt": False, "needs_pinned_test": True},
    "no-data-source": {"debt": True, "needs_pinned_test": False},
    "deprecated": {"debt": True, "needs_pinned_test": False},
    "wip": {"debt": True, "needs_pinned_test": False},
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
# `[<category>] <说明>`：类别前缀必须是**整条 reason 的开头**，且前缀后必须还有说明
PREFIX_RE = re.compile(r"^\[([a-z][a-z0-9-]*)\]\s*(\S.*)$", re.S)

# 违规码（供红证逐条断言；码集合本身也是"判据不是空壳"的证据）
NO_CATEGORY = "SKIP-NO-CATEGORY"
UNKNOWN_CATEGORY = "SKIP-UNKNOWN-CATEGORY"
EMPTY_DETAIL = "SKIP-EMPTY-DETAIL"
DEBT_NO_ISSUE = "SKIP-DEBT-NO-ISSUE"
DEBT_BAD_EXPIRES = "SKIP-DEBT-BAD-EXPIRES"
DEBT_EXPIRED = "SKIP-DEBT-EXPIRED"
NO_PINNED_TEST = "SKIP-BACKEND-CONTRACT-NO-PINNED-TEST"
PENDING_EXPIRED = "SKIP-BASELINE-PENDING-EXPIRED"
PENDING_UNKNOWN_ID = "SKIP-BASELINE-PENDING-UNKNOWN-ID"
BASELINE_INCOHERENT = "SKIP-BASELINE-INCOHERENT"
TOTAL_GROWTH = "SKIP-TOTAL-GROWTH"

# 判据不得恒真的下限守卫（只在"装载/判据静默失效"时才触发；现值见基线 `skip_total`）
_MIN_SKIPPED_CASES = 100
_REQUIRED_CATEGORIES = frozenset(SKIP_CATEGORIES)


# ══════════════════════════════════════════════════════════════════════════════
# 输入层
# ══════════════════════════════════════════════════════════════════════════════

def load_cases(cases_dir: Path = CASES_DIR) -> tuple[dict, ...]:
    """用例库（唯一源 `.github/cases/*.yml`，经 runner 同款装载路径）。"""
    return tuple(render_cases.load_case_dicts(str(cases_dir)))


def load_baseline(path: Path = BASELINE_PATH) -> dict:
    """基线（fail-closed：缺失/坏 JSON ⇒ 抛异常，**不**静默当成"无基线"放行）。"""
    if not path.is_file():
        raise FileNotFoundError(
            f"skip 豁免基线缺失（fail-closed）：{path} —— 没有基线就没有'存量'可言，"
            "每条非空 skip_reason 都必须当场合规"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def skipped(cases) -> list[dict]:
    """`skip_reason` 非空的用例（= **本次评测不会跑**的那些）。"""
    return [c for c in cases if str(c.get("skip_reason") or "").strip()]


def _as_date(v) -> date | None:
    """严格解析 `YYYY-MM-DD`；其它形态一律 `None`（**不**猜、不宽容）。"""
    s = str(v or "").strip()
    if not DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _pinned_tests(case: dict) -> list[str]:
    """`traces.tests` 里**非空**的引用（钉住该用例的测试）。"""
    traces = case.get("traces")
    if not isinstance(traces, dict):
        return []
    tests = traces.get("tests")
    if not isinstance(tests, list):
        return []
    return [str(t).strip() for t in tests if str(t or "").strip()]


# ══════════════════════════════════════════════════════════════════════════════
# 判据本体（纯函数；红证靠注入夹具，与被测真值解耦）
# ══════════════════════════════════════════════════════════════════════════════

def case_violations(case: dict, today: date) -> list[dict]:
    """单条用例的**类别契约**违规（不含基线比对）。空列表 = 合规。"""
    cid = str(case.get("id") or "?")
    reason = str(case.get("skip_reason") or "").strip()
    if not reason:
        return []                      # 没 skip = 不属本判据的对象
    out: list[dict] = []

    def add(code: str, detail: str) -> None:
        out.append({"code": code, "case_id": cid, "detail": detail})

    m = PREFIX_RE.match(reason)
    if not m:
        add(NO_CATEGORY,
            f"skip_reason 未以类别前缀开头（合法形态：`[<类别>] <说明>`，"
            f"类别 ∈ {sorted(SKIP_CATEGORIES)}）：{reason[:80]!r}")
        return out                     # 没类别 ⇒ 后续字段判据无对象，不再叠加噪音
    cat, detail = m.group(1), m.group(2).strip()
    if cat not in SKIP_CATEGORIES:
        add(UNKNOWN_CATEGORY,
            f"未知类别 `[{cat}]` —— 类别集合写死在判据里（{sorted(SKIP_CATEGORIES)}），"
            "新增类别必须改判据常量表（有意识决策）")
        return out
    if not detail:
        add(EMPTY_DETAIL, f"类别 `[{cat}]` 前缀后没有说明")

    spec = SKIP_CATEGORIES[cat]
    if spec["debt"]:
        issue = case.get("skip_issue")
        if not isinstance(issue, int) or isinstance(issue, bool) or issue <= 0:
            add(DEBT_NO_ISSUE,
                f"债务类 `[{cat}]` 必须带 `skip_issue: <正整数>`（追踪号），"
                f"现值 = {issue!r}")
        exp = _as_date(case.get("skip_expires"))
        if exp is None:
            add(DEBT_BAD_EXPIRES,
                f"债务类 `[{cat}]` 必须带 `skip_expires: YYYY-MM-DD`，"
                f"现值 = {case.get('skip_expires')!r}")
        elif exp < today:
            add(DEBT_EXPIRED,
                f"债务类 `[{cat}]` 的 `skip_expires` {exp} 已过期（今天 {today}）"
                "⇒ 到期未收敛即红")
    if spec["needs_pinned_test"] and not _pinned_tests(case):
        add(NO_PINNED_TEST,
            f"`[{cat}]` 声称正确判定层不在 LLM 层，但 `traces.tests` 为空 ⇒ "
            "没有钉住它的测试（= 永远不跑的借口）")
    return out


def baseline_violations(cases, baseline: dict, today: date) -> list[dict]:
    """**基线比对**违规：总量只许缩 + pending 只许缩且未过期 + 账本自洽。"""
    out: list[dict] = []

    def add(code: str, detail: str) -> None:
        out.append({"code": code, "case_id": "-", "detail": detail})

    # ── 账本自洽（防止把基线写成"想要的样子"）──
    legacy = baseline.get("legacy_skip_ids")
    pending = baseline.get("pending_classification")
    total = baseline.get("skip_total")
    history = baseline.get("history")
    if not isinstance(legacy, list) or not isinstance(pending, dict) or not isinstance(total, int):
        add(BASELINE_INCOHERENT,
            "基线必须有 `legacy_skip_ids`(list) / `pending_classification`(dict) / `skip_total`(int)")
        return out
    if not SHA_RE.match(str(baseline.get("anchor_sha") or "")):
        add(BASELINE_INCOHERENT,
            f"基线缺少锚定 SHA（`anchor_sha`）：{baseline.get('anchor_sha')!r}")
    if len(legacy) != total:
        add(BASELINE_INCOHERENT,
            f"`legacy_skip_ids` 条目数 {len(legacy)} ≠ `skip_total` {total} "
            "⇒ 锚点快照与计数不自洽")
    extra = sorted(set(pending) - set(legacy))
    if extra:
        add(BASELINE_INCOHERENT,
            f"`pending_classification` 有 {len(extra)} 条不在锚点快照 `legacy_skip_ids` 里 "
            f"⇒ 偷偷给新 skip 挂豁免（只许缩短）：{extra[:8]}")
    if not isinstance(history, list) or not history:
        add(BASELINE_INCOHERENT, "基线必须有非空 `history`（`skip_total` 只许非增的账本）")
    else:
        try:
            totals = [int(h["skip_total"]) for h in history]
        except (TypeError, KeyError, ValueError):
            add(BASELINE_INCOHERENT, f"`history` 形态非法（每项需含整数 `skip_total`）：{history!r}")
            totals = []
        if totals and totals != sorted(totals, reverse=True):
            add(BASELINE_INCOHERENT,
                f"`history` 里 `skip_total` 出现增长（只许非增 = 豁免只许缩）：{totals}")
        if totals and totals[-1] != total:
            add(BASELINE_INCOHERENT,
                f"`history` 末项 {totals[-1]} ≠ `skip_total` {total}")

    # ── pending 逐条对账（陈旧条目 ⇒ 阻塞，与 case_trust_gate 同款口径）──
    live = {str(c.get("id")): c for c in skipped(cases)}
    for cid in sorted(pending):
        if cid not in live:
            add(PENDING_UNKNOWN_ID,
                f"基线 `pending` 记了 {cid}，但它现在**没有**非空 skip_reason "
                "⇒ 陈旧豁免条目，必须从基线删除（只许缩短）")

    # ── 总量只许缩（净增即红；不设 per-PR 强制消减）──
    n = len(live)
    if n > total:
        add(TOTAL_GROWTH,
            f"用例库非空 skip_reason 数 {n} > 基线 `skip_total` {total}（锚定 "
            f"{baseline.get('anchor_sha')}）⇒ 豁免净增。"
            "新 skip 只有两个出口：本次改到合规 / 不得新增豁免")

    # ── pending 到期（到期即红：存量也不是永久豁免）──
    exp = _as_date(baseline.get("pending_expires"))
    if pending and exp is None:
        add(PENDING_EXPIRED,
            f"基线有 {len(pending)} 条 pending，却没写合法的 `pending_expires`: "
            f"{baseline.get('pending_expires')!r}")
    elif pending and exp < today:
        add(PENDING_EXPIRED,
            f"基线 `pending_expires` {exp} 已过期（今天 {today}）：pending 里仍有 "
            f"{len(pending)} 条未归类存量（{sorted(pending)[:8]}）⇒ 到期未收敛")

    return out


def audit(cases, baseline: dict, today: date) -> list[dict]:
    """全量裁决：每条非空 skip 必须合规，**除非**它是基线里未过期的 pending 条目。"""
    pending = baseline.get("pending_classification") or {}
    exp = _as_date(baseline.get("pending_expires"))
    pending_alive = (
        isinstance(pending, dict) and bool(pending) and exp is not None and exp >= today
    )
    out: list[dict] = []
    for c in skipped(cases):
        cid = str(c.get("id"))
        if pending_alive and cid in pending:
            continue                  # 存量：按基线放行（有时限）
        out.extend(case_violations(c, today))
    out.extend(baseline_violations(cases, baseline, today))
    return out


def _fmt(viols: list[dict]) -> str:
    return "\n".join(f"  · [{v['code']}] {v['case_id']}: {v['detail']}" for v in viols)


# ══════════════════════════════════════════════════════════════════════════════
# 真实用例库（CI 每次 PR 都跑这一组）
# ══════════════════════════════════════════════════════════════════════════════

class TestLiveLibrary:
    """当前用例库必须全绿（收紧后 main 不得变红）。"""

    def test_library_and_baseline_are_loadable(self):
        cases, baseline = load_cases(), load_baseline()
        assert len(cases) >= _MIN_SKIPPED_CASES, f"用例库装载异常：{len(cases)} 条"
        assert len(skipped(cases)) >= _MIN_SKIPPED_CASES, "skip 装载异常（判据会静默空跑）"
        assert set(baseline["pending_classification"]) <= set(baseline["legacy_skip_ids"])

    def test_no_skip_exemption_violation(self):
        cases, baseline = load_cases(), load_baseline()
        viols = audit(cases, baseline, date.today())
        assert not viols, (
            f"skip 豁免判据报红 {len(viols)} 条：\n{_fmt(viols)}\n\n"
            "修法：① `[backend-contract]` 等类别前缀 +（债务类）`skip_issue`/`skip_expires`；"
            "② `[backend-contract]` 必须有 `traces.tests`；③ 存量走基线 pending（只许缩短）"
        )

    def test_category_table_is_not_a_dead_constant(self):
        """类别表不得是空壳：四类都必须在判据里有明确要求，且都在真实库里有实例或显式登记。"""
        assert set(SKIP_CATEGORIES) == _REQUIRED_CATEGORIES
        for cat, spec in SKIP_CATEGORIES.items():
            assert set(spec) == {"debt", "needs_pinned_test"}, cat
        assert any(SKIP_CATEGORIES[c]["debt"] for c in SKIP_CATEGORIES), "债务类不得为空"
        assert any(SKIP_CATEGORIES[c]["needs_pinned_test"] for c in SKIP_CATEGORIES)

    def test_every_category_is_exercised_by_a_red_proof(self):
        """每个类别都必须有一条"不合规即红"的红证（防"写了但永远不会红"）。"""
        covered = set()
        for cat in SKIP_CATEGORIES:
            c = {"id": "T-1", "skip_reason": f"[{cat}] 说明"}
            codes = {v["code"] for v in case_violations(c, date(2026, 1, 1))}
            if SKIP_CATEGORIES[cat]["debt"]:
                assert {DEBT_NO_ISSUE, DEBT_BAD_EXPIRES} <= codes, cat
            if SKIP_CATEGORIES[cat]["needs_pinned_test"]:
                assert NO_PINNED_TEST in codes, cat
            covered.add(cat)
        assert covered == set(SKIP_CATEGORIES)

    def test_pending_entries_are_recorded_with_what_is_missing(self):
        """pending 不是"免死金牌"：每条都要写清**缺什么**，且类别要么判定、要么**显式**记未定。

        `undecided: true` 是**一等状态**（不是沉默）：判不准的存量必须自报"判不准 + 为什么"，
        否则 pending 就成了"不写类别也能豁免"的后门。
        """
        baseline = load_baseline()
        for cid, rec in baseline["pending_classification"].items():
            assert isinstance(rec, dict), cid
            assert str(rec.get("missing") or "").strip(), f"{cid} 未登记缺什么"
            cat = str(rec.get("category") or "").strip()
            if rec.get("undecided") is True:
                assert not cat, f"{cid} 标了 undecided 却又写了类别 {cat!r}（自相矛盾）"
                continue
            assert cat in SKIP_CATEGORIES, (
                f"{cid} 的类别 {cat!r} 既不在判据常量表里，也没标 `undecided: true`"
            )


# ══════════════════════════════════════════════════════════════════════════════
# 红证（注入式夹具：与被测真值解耦，永远有效）
# ══════════════════════════════════════════════════════════════════════════════

TODAY = date(2026, 9, 18)


def _baseline(**over) -> dict:
    """最小合法基线夹具（红证在此基础上**只改一处**，保证红因单一）。"""
    base = {
        "anchor_sha": "bd7fa9bca1b2c3d4e5f60718293a4b5c6d7e8f90",
        "anchored_at": "2026-09-18",
        "skip_total": 2,
        "legacy_skip_ids": ["X-001", "X-002"],
        "pending_classification": {},
        "pending_expires": "2026-11-30",
        "history": [{"sha": "bd7fa9bca1b2c3d4e5f60718293a4b5c6d7e8f90",
                     "date": "2026-09-18", "skip_total": 2}],
    }
    base.update(over)
    return base


def _ok_case(cid="X-001", **over) -> dict:
    """完全合规的 `[backend-contract]` 夹具。"""
    c = {"id": cid, "skip_reason": "[backend-contract] 由 pytest 单测验证",
         "traces": {"tests": ["backend/ai-agent-service/tests/test_x.py"]}}
    c.update(over)
    return c


class TestRedProofs:
    """四条主红证（报告要求逐条给原文）。"""

    def test_red_proof_1_no_category(self):
        """红证①：`skip_reason` 未带类别前缀 ⇒ 红。"""
        cases = [_ok_case("X-001", skip_reason="纯前端由 jest 单测验证，不进入 agent-eval 冒烟")]
        viols = audit(cases, _baseline(legacy_skip_ids=["X-001"], skip_total=1,
                                      history=[{"sha": "bd7fa9bca1b2c3d4e5f60718293a4b5c6d7e8f90",
                                                "date": "2026-09-18", "skip_total": 1}]), TODAY)
        assert [v["code"] for v in viols] == [NO_CATEGORY], _fmt(viols)

    def test_red_proof_1b_unknown_category_is_also_red(self):
        """自造类别（即使形态像前缀）也红 —— 类别集合是判据里的常量表，不是自由文本。"""
        cases = [_ok_case("X-001", skip_reason="[because-i-dont-want-to] 就不跑")]
        viols = audit(cases, _baseline(legacy_skip_ids=["X-001"], skip_total=1,
                                      history=[{"sha": "bd7fa9bca1b2c3d4e5f60718293a4b5c6d7e8f90",
                                                "date": "2026-09-18", "skip_total": 1}]), TODAY)
        assert [v["code"] for v in viols] == [UNKNOWN_CATEGORY], _fmt(viols)
        # 非 ASCII 的方括号（`[因为我不想跑]`）**fail-closed 归到"无类别"**，
        # 而不是被宽容成"看起来有前缀"（前缀词法 = ASCII 小写标识符）。
        assert [v["code"] for v in case_violations(
            {"id": "X-001", "skip_reason": "[因为我不想跑] 懒"}, TODAY)] == [NO_CATEGORY]

    def test_red_proof_2_debt_without_issue_or_expired(self):
        """红证②：债务类缺 `skip_issue` / `skip_expires` 或**已过期** ⇒ 红。"""
        missing = {"id": "X-001", "skip_reason": "[wip] 等 runner 支持发图"}
        assert {v["code"] for v in case_violations(missing, TODAY)} == {DEBT_NO_ISSUE, DEBT_BAD_EXPIRES}

        # 只缺 expires
        half = {"id": "X-001", "skip_reason": "[no-data-source] 评测栈没有可全流转的测试订单",
                "skip_issue": 4064}
        assert [v["code"] for v in case_violations(half, TODAY)] == [DEBT_BAD_EXPIRES]

        # 过期（`skip_expires` 早于今天）
        expired = {"id": "X-001", "skip_reason": "[wip] 等 runner 支持发图",
                   "skip_issue": 4064, "skip_expires": "2026-09-17"}
        got = case_violations(expired, TODAY)
        assert [v["code"] for v in got] == [DEBT_EXPIRED], _fmt(got)

        # 合法债务形态 ⇒ 不报（负例，R2）
        good = {"id": "X-001", "skip_reason": "[wip] 等 runner 支持发图",
                "skip_issue": 4064, "skip_expires": "2026-11-30"}
        assert case_violations(good, TODAY) == []

    def test_red_proof_3_backend_contract_without_pinned_test(self):
        """红证③：`[backend-contract]` 无 `traces.tests` ⇒ 红（否则 = 永远不跑的借口）。"""
        bare = {"id": "X-001", "skip_reason": "[backend-contract] 由单测验证，非 LLM 行为"}
        assert [v["code"] for v in case_violations(bare, TODAY)] == [NO_PINNED_TEST]
        # 空串 / 空白引用不算钉住
        blank = {"id": "X-001", "skip_reason": "[backend-contract] 由单测验证",
                 "traces": {"tests": ["", "   "]}}
        assert [v["code"] for v in case_violations(blank, TODAY)] == [NO_PINNED_TEST]
        # 有钉住它的测试 ⇒ 不报（负例，R2；存在性由 #4120 守卫承担）
        assert case_violations(_ok_case(), TODAY) == []

    def test_red_proof_4_new_skip_increases_the_exemption(self):
        """红证④：**新增 skip**（净增）⇒ 红。"""
        cases = [_ok_case("X-001"), _ok_case("X-002")]
        base = _baseline()          # skip_total=2, legacy=[X-001, X-002]
        assert audit(cases, base, TODAY) == []

        # 新增第三条 skip（即便写得完全合规）⇒ 总量净增即红
        cases.append(_ok_case("X-003"))
        got = audit(cases, base, TODAY)
        assert [v["code"] for v in got] == [TOTAL_GROWTH], _fmt(got)

        # 同 PR 删掉同等数量（净增 ≤ 0）⇒ 不报
        assert audit(cases[:1] + cases[2:], base, TODAY) == []

    def test_red_proof_4b_new_noncompliant_skip_cannot_hide_behind_net_zero(self):
        """红证④b：净增 0 也挡不住"新增一条不合规 skip"（= 偷偷挂豁免）。"""
        cases = [_ok_case("X-001"), _ok_case("X-003", skip_reason="欠着，回头再说")]
        got = audit(cases, _baseline(), TODAY)
        assert [v["code"] for v in got] == [NO_CATEGORY], _fmt(got)

    def test_red_proof_5_pending_is_not_a_permanent_exemption(self):
        """红证⑤：pending 只许缩短 + 到期即红 + 陈旧条目阻塞。"""
        cases = [_ok_case("X-001", skip_reason="老写法，没类别"),
                 _ok_case("X-002")]
        live = _baseline(pending_classification={"X-001": {"category": "backend-contract",
                                                          "missing": "未加类别前缀"}})
        assert audit(cases, live, TODAY) == []          # 存量按基线放行

        # 到期 ⇒ 红
        assert PENDING_EXPIRED in {v["code"] for v in audit(cases, live, date(2026, 12, 1))}

        # 陈旧条目（记了却已不再 skip）⇒ 阻塞
        stale = _baseline(pending_classification={"X-001": {"category": "backend-contract",
                                                           "missing": "x"}})
        assert (PENDING_UNKNOWN_ID in
                {v["code"] for v in audit([_ok_case("X-002")] * 2, stale, TODAY)})

        # 把**新 ID** 塞进 pending（不在锚点快照 `legacy_skip_ids` 里）⇒ 阻塞（偷偷挂豁免）
        smuggle = _baseline(pending_classification={"X-003": {"category": "wip", "missing": "x"}})
        viols = audit([_ok_case("X-001"), _ok_case("X-002"), _ok_case("X-003")], smuggle, TODAY)
        codes = {v["code"] for v in viols}
        assert BASELINE_INCOHERENT in codes, _fmt(viols)
        assert TOTAL_GROWTH in codes, _fmt(viols)   # 同时被总量口径挡一次（双重 fail-closed）

    def test_red_proof_6_history_may_not_grow(self):
        """红证⑥：账本 `history` 里的 `skip_total` 只许非增（涨回去即红）。"""
        grown = _baseline(skip_total=3, legacy_skip_ids=["X-001", "X-002", "X-003"],
                          history=[{"sha": "bd7fa9bca1b2c3d4e5f60718293a4b5c6d7e8f90",
                                    "date": "2026-09-18", "skip_total": 2},
                                   {"sha": "bd7fa9bca1b2c3d4e5f60718293a4b5c6d7e8f90",
                                    "date": "2026-10-01", "skip_total": 3}])
        assert BASELINE_INCOHERENT in {
            v["code"] for v in audit([_ok_case(f"X-00{i}") for i in (1, 2, 3)], grown, TODAY)}


class TestNegativeCases:
    """负例（R2）：合法形态不得判红 —— 防"为了红而红"。"""

    def test_all_four_categories_have_a_legal_form(self):
        legal = [
            {"id": "A-1", "skip_reason": "[backend-contract] 由 pytest 单测验证，非 LLM 行为",
             "traces": {"tests": ["backend/ai-agent-service/tests/test_a.py"]}},
            {"id": "A-2", "skip_reason": "[no-data-source] 评测栈无非此数据源",
             "skip_issue": 4064, "skip_expires": "2026-11-30"},
            {"id": "A-3", "skip_reason": "[deprecated] 能力已随 #3917 下线",
             "skip_issue": 3917, "skip_expires": "2026-11-30"},
            {"id": "A-4", "skip_reason": "[wip] runner 发图能力未落",
             "skip_issue": 4064, "skip_expires": "2026-11-30"},
        ]
        for c in legal:
            assert case_violations(c, TODAY) == [], c["id"]

    def test_empty_skip_reason_is_out_of_scope(self):
        """`skip_reason: ""`（大多数用例）= 正常跑，不属本判据对象。"""
        assert case_violations({"id": "A-1", "skip_reason": ""}, TODAY) == []
        assert case_violations({"id": "A-1"}, TODAY) == []

    def test_expiry_boundary_today_is_still_valid(self):
        """边界：`skip_expires` == 今天 ⇒ 未过期（到期日当天还算数）。"""
        c = {"id": "A-1", "skip_reason": "[wip] x", "skip_issue": 1, "skip_expires": "2026-09-18"}
        assert case_violations(c, date(2026, 9, 18)) == []

    def test_missing_baseline_is_fail_closed(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_baseline(tmp_path / "nope.json")