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
4. **增长判据按类分流**（#4233）：增长只治**债务类**（`wip` / `no-data-source` / `deprecated`
   —— 它们才是"用来绕开评测的豁免"）⇒ 基线 `debt_skip_total` + `debt_skip_ids` 是锚点快照，
   用例库里的债务类非空 skip **超出即红**（净增即红；**不设** per-PR 强制消减，留给后续裁定）。
   `[backend-contract]` 类**设计上就不进 agent-eval**（它的 `skip_reason` 是 runner 侧
   `eval_case_filter.case_skip_reason` 的**分隔符**，不是豁免；去掉它反而会让用例空跑/假绿），
   故**单列** `backend_contract_ids` **合规清单**、**不计入**增长 ⇒ 新增该类**合规**用例
   **无需**重锚定账本。`.github/skip-exemption-baseline.json` 仍记锚定 SHA + `skip_total`
   （锚点快照，与 `legacy_skip_ids` 自洽）；`skip_total` 本身**不再作增长分母**。
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
  `pending ⊆ legacy` + 按类清单 `⊆ legacy` 增加摩擦力，**但那不是密码学封印** —— 改基线是
  **显式的、会被 diff 看见的**动作，与仓里其它基线同一信任模型。
- **锚点前移（重锚定）的唯一例外**：与基线 `_when_to_update` ⑤ **同一套判据**
  （`_history_growth_allowed`，集成裁定 2026-09-18）—— **仅 `history` 末行带显式 `note`**
  的增长可放行（账本对齐 main 现实 —— #4192 对 CH-008/CH-017 的 unrunnable 登记）；
  无 `note` 的增长 / 非末行增长一律仍红。
  ⚠️ 这条例外**不是**给 `[backend-contract]` 类准备的：那类新增**无需**动基线（见判据 4），
  例外只服务"锚点前移时账本数字必须跟上 main 现实"这一情形。
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

# 债务类（**派生**自 `SKIP_CATEGORIES` 的 `debt` 标志，不新造平行分类源）：
# 增长判据只治这一类（#4233）。
_DEBT_CATEGORIES = tuple(sorted(c for c, spec in SKIP_CATEGORIES.items() if spec["debt"]))

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
BACKEND_CONTRACT_ROSTER = "SKIP-BACKEND-CONTRACT-ROSTER"
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


def category_of(case: dict) -> str | None:
    """`skip_reason` 的类别（`[<cat>]` 前缀 **且** 类别在 `SKIP_CATEGORIES` 里）；否则 `None`。

    分类真值**只有** `SKIP_CATEGORIES` 一个来源（#4233：复用既有 `debt` 标志，
    不新造平行分类源）。
    """
    m = PREFIX_RE.match(str(case.get("skip_reason") or "").strip())
    if not m or m.group(1) not in SKIP_CATEGORIES:
        return None
    return m.group(1)


def is_debt_skip(case: dict) -> bool:
    """是否**债务类**（`wip` / `no-data-source` / `deprecated`）非空 skip。"""
    cat = category_of(case)
    return bool(cat) and bool(SKIP_CATEGORIES[cat]["debt"])


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


def _history_growth_allowed(history: list, totals: list[int]) -> bool:
    """history 增长例外（集成裁定 2026-09-18，方案 A）：仅「末行增长 + 该行带显式 `note`」
    的锚点前移重锚定可放行（账本对齐 main 现实 —— #4192 给 CH-008/CH-017 的 unrunnable
    登记，两条已机器钉住）；无 note 的增长、非末行增长 ⇒ False（fail-closed，其余判据一字不松）。"""
    for i in range(1, len(totals)):
        if totals[i] > totals[i - 1]:
            row = history[i] if isinstance(history[i], dict) else {}
            if i != len(totals) - 1:
                return False
            if not str(row.get("note") or "").strip():
                return False
    return True


def baseline_violations(cases, baseline: dict, today: date) -> list[dict]:
    """**基线比对**违规：按类分流的总量判据 + pending 只许缩且未过期 + 账本自洽。

    增长判据**按类分流**（#4233）：只治**债务类**净增；`[backend-contract]` 类单列
    `backend_contract_ids` 合规清单（允许增长 ⇒ 新增该类合规用例**无需**重锚定）。
    """
    out: list[dict] = []

    def add(code: str, detail: str) -> None:
        out.append({"code": code, "case_id": "-", "detail": detail})

    # ── 账本自洽（防止把基线写成"想要的样子"）──
    legacy = baseline.get("legacy_skip_ids")
    pending = baseline.get("pending_classification")
    total = baseline.get("skip_total")
    history = baseline.get("history")
    debt_ids = baseline.get("debt_skip_ids")
    debt_total = baseline.get("debt_skip_total")
    bc_ids = baseline.get("backend_contract_ids")
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
    # 按类分解字段（#4233）：缺字段 ⇒ 增长判据无从判 ⇒ fail-closed（**不**静默退回"只判总量"）
    class_fields_ok = (
        isinstance(debt_ids, list) and isinstance(bc_ids, list)
        and isinstance(debt_total, int) and not isinstance(debt_total, bool)
    )
    if not class_fields_ok:
        add(BASELINE_INCOHERENT,
            "基线必须有按类分解字段 `debt_skip_ids`(list) / `debt_skip_total`(int) / "
            "`backend_contract_ids`(list)（#4233 起增长判据按类分流，缺字段即无法判）："
            f"实测 debt_skip_ids={debt_ids!r} / debt_skip_total={debt_total!r} / "
            f"backend_contract_ids={bc_ids!r}")
    else:
        for name, ids in (("debt_skip_ids", debt_ids), ("backend_contract_ids", bc_ids)):
            if len({str(i) for i in ids}) != len(ids) or any(not str(i or "").strip() for i in ids):
                add(BASELINE_INCOHERENT, f"`{name}` 必须是不重复的非空 ID 清单：{ids!r}")
        if len(debt_ids) != debt_total:
            add(BASELINE_INCOHERENT,
                f"`debt_skip_ids` 条目数 {len(debt_ids)} ≠ `debt_skip_total` {debt_total} "
                "⇒ 债务类快照与计数不自洽")
        outside = sorted((set(debt_ids) | set(bc_ids)) - set(legacy))
        if outside:
            add(BASELINE_INCOHERENT,
                f"按类清单里有 {len(outside)} 条不在锚点快照 `legacy_skip_ids` 里 ⇒ 不得凭空造 ID"
                f"（分类只许在锚点快照内做）：{outside[:8]}")
        overlap = sorted(set(debt_ids) & set(bc_ids))
        if overlap:
            add(BASELINE_INCOHERENT,
                f"`debt_skip_ids` 与 `backend_contract_ids` 重叠（一条 skip 只能属一类）：{overlap[:8]}")
        if debt_total + len(bc_ids) > total:
            add(BASELINE_INCOHERENT,
                f"`debt_skip_total` {debt_total} + `backend_contract_ids` {len(bc_ids)} "
                f"> `skip_total` {total} ⇒ 锚点分类计数不自洽")
    if not isinstance(history, list) or not history:
        add(BASELINE_INCOHERENT, "基线必须有非空 `history`（`skip_total` 只许非增的账本）")
    else:
        try:
            totals = [int(h["skip_total"]) for h in history]
        except (TypeError, KeyError, ValueError):
            add(BASELINE_INCOHERENT, f"`history` 形态非法（每项需含整数 `skip_total`）：{history!r}")
            totals = []
        if totals and not _history_growth_allowed(history, totals):
            add(BASELINE_INCOHERENT,
                f"`history` 里 `skip_total` 出现增长（只许非增 = 豁免只许缩；"
                f"唯一例外 = **末行**带显式 `note` 的锚点前移重锚定）：{totals}")
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

    # ── 增长按类分流（#4233）：债务类净增即红；`[backend-contract]` **不计入**增长 ──
    if class_fields_ok:
        live_debt = sorted(cid for cid, c in live.items() if is_debt_skip(c))
        if len(live_debt) > debt_total:
            extra_debt = sorted(set(live_debt) - set(debt_ids))
            add(TOTAL_GROWTH,
                f"债务类（{'/'.join(_DEBT_CATEGORIES)}）非空 skip_reason 数 {len(live_debt)} 条 > "
                f"基线 `debt_skip_total` {debt_total}（锚定 {baseline.get('anchor_sha')}）"
                f"⇒ 债务净增即红（净增 {len(live_debt) - debt_total} 条；不在锚点快照 "
                f"`debt_skip_ids` 里的：{extra_debt[:8]}）。"
                "`[backend-contract]` 类**不计入**本判据（设计上不进 agent-eval，见 "
                "`backend_contract_ids` 合规清单）；新 skip 只有两个出口：本次改到合规 / 不得新增豁免")
        # 合规清单：**允许增长**（新增该类合规用例无需重锚定），但清单内仍存活的条目
        # 不得**静默改判**成另一个已知类别（改判 ⇒ 它会真的进 agent-eval 冒烟 = 空跑/假绿）；
        # 无类别前缀的条目（含 pending 存量）不在此判据内 —— 它们由 NO_CATEGORY / pending 口径管。
        reclassed = sorted(cid for cid in bc_ids
                           if cid in live
                           and category_of(live[cid]) not in (None, "backend-contract"))
        if reclassed:
            add(BACKEND_CONTRACT_ROSTER,
                f"`backend_contract_ids` 里 {len(reclassed)} 条**仍在用例库里**、类别却已不是 "
                f"`[backend-contract]`（静默改判 ⇒ 它们会真的进 agent-eval 冒烟）：{reclassed[:8]}")

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
    """最小合法基线夹具（红证在此基础上**只改一处**，保证红因单一）。

    按类分解字段（`debt_skip_ids` / `debt_skip_total` / `backend_contract_ids`）默认**跟随**
    `legacy_skip_ids` 推导 —— 红证只改锚点快照一处时不必同步改三处（否则红因不单一）。
    """
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
    base.setdefault("debt_skip_ids", [])
    base.setdefault("debt_skip_total", len(base["debt_skip_ids"]))
    base.setdefault("backend_contract_ids",
                    [i for i in base["legacy_skip_ids"] if i not in base["debt_skip_ids"]])
    return base


def _ok_case(cid="X-001", **over) -> dict:
    """完全合规的 `[backend-contract]` 夹具（`traces.tests` 指向**真实存在**的测试文件）。"""
    c = {"id": cid, "skip_reason": "[backend-contract] 由 pytest 单测验证",
         "traces": {"tests": ["tests/unit_ci_workflows/test_skip_exemption_gate.py"]}}
    c.update(over)
    return c


def _debt_case(cid="X-003", **over) -> dict:
    """完全合规的**债务类**夹具（`[wip]` + `skip_issue` + 未过期 `skip_expires`）。"""
    c = {"id": cid, "skip_reason": "[wip] runner 发图能力未落",
         "skip_issue": 4064, "skip_expires": "2026-11-30"}
    c.update(over)
    return c


# 绝对禁令形态（"新增 skip ⇒ **不得**记进本文件"）：与门禁例外条款（`history` 末行 + 显式
# `note` 的锚点前移重锚定允许增长）在同一 PR 评审面里互相矛盾 ⇒ 口径合一后该形态必须消失。
ABSOLUTE_BAN_RE = re.compile(r"新增\s*skip\s*⇒\s*\*\*不得\*\*")


class TestRedProofs:
    """红证（报告要求逐条给原文）。A/B/C = issue #4233 判据 3/3/1 的三条。"""

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

    def test_red_proof_4_new_debt_skip_increases_the_exemption(self):
        """红证 B（#4233 判据 3）：**新增债务类 skip**（净增）⇒ **仍红** —— 防"按类分流"改过头，
        把真护栏（`wip`/`no-data-source`/`deprecated` = 用来绕开评测的豁免）一起拆了。"""
        cases = [_ok_case("X-001"), _ok_case("X-002")]
        base = _baseline()          # skip_total=2, legacy=[X-001, X-002], debt_skip_ids=[]
        assert audit(cases, base, TODAY) == []

        # 新增第三条 skip：写得**完全合规**的债务类（`[wip]` + skip_issue + 未过期 skip_expires）
        # ⇒ 债务类净增即红（合规不等于可以新增）
        cases.append(_debt_case("X-003"))
        got = audit(cases, base, TODAY)
        assert [v["code"] for v in got] == [TOTAL_GROWTH], _fmt(got)

        # 同 PR 删掉同等数量的**债务类**（净增 ≤ 0）⇒ 不报（净额口径：允许债务类内部替换）
        swap = _baseline(legacy_skip_ids=["X-001", "X-004"], skip_total=2,
                         debt_skip_ids=["X-004"], debt_skip_total=1,
                         backend_contract_ids=["X-001"])
        assert audit([_ok_case("X-001"), _debt_case("X-003")], swap, TODAY) == []

    def test_red_proof_4c_new_compliant_backend_contract_is_not_counted_as_growth(self):
        """红证 A（#4233 判据 3）：新增一条**合规** `[backend-contract]` 用例 ⇒ 门禁**绿**
        （无需重锚定账本）—— 本批 +4 条 `[backend-contract]` 撞上的正是"被计入增长"这条。

        前置条件（该类的**合规**形态）：前缀合规 + `traces.tests` 非空（文件存在性由 #4120 守卫）。
        """
        base = _baseline()      # skip_total=2 / debt_skip_ids=[] / backend_contract_ids=[X-001,X-002]
        cases = [_ok_case("X-001"), _ok_case("X-002"), _ok_case("X-003")]
        got = audit(cases, base, TODAY)
        assert got == [], _fmt(got)

    def test_red_proof_4d_roster_entry_cannot_be_silently_reclassified(self):
        """`backend_contract_ids` 里的条目若**仍存活**却已不是 `[backend-contract]`（静默改判
        ⇒ 它会真的进 agent-eval 冒烟 = 空跑/假绿）⇒ 红。"""
        base = _baseline()      # 合规清单 = [X-001, X-002]
        cases = [_ok_case("X-001"),
                 _debt_case("X-002", skip_reason="[wip] 悄悄改判成债务类")]
        codes = {v["code"] for v in audit(cases, base, TODAY)}
        assert BACKEND_CONTRACT_ROSTER in codes, _fmt(audit(cases, base, TODAY))

    def test_red_proof_4e_new_noncompliant_skip_cannot_hide_behind_net_zero(self):
        """红证 D：净增 0 也挡不住"新增一条不合规 skip"（= 偷偷挂豁免）。"""
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
        # 该条写成**合规的债务类**（`[wip]`）⇒ 同时被债务类增长口径挡一次（双重 fail-closed）
        smuggle = _baseline(pending_classification={"X-003": {"category": "wip", "missing": "x"}})
        viols = audit([_ok_case("X-001"), _ok_case("X-002"), _debt_case("X-003")], smuggle, TODAY)
        codes = {v["code"] for v in viols}
        assert BASELINE_INCOHERENT in codes, _fmt(viols)
        assert TOTAL_GROWTH in codes, _fmt(viols)

    def test_red_proof_6_history_may_not_grow(self):
        """红证⑥：账本 `history` 里的 `skip_total` 只许非增（涨回去即红）。"""
        grown = _baseline(skip_total=3, legacy_skip_ids=["X-001", "X-002", "X-003"],
                          history=[{"sha": "bd7fa9bca1b2c3d4e5f60718293a4b5c6d7e8f90",
                                    "date": "2026-09-18", "skip_total": 2},
                                   {"sha": "bd7fa9bca1b2c3d4e5f60718293a4b5c6d7e8f90",
                                    "date": "2026-10-01", "skip_total": 3}])
        assert BASELINE_INCOHERENT in {
            v["code"] for v in audit([_ok_case(f"X-00{i}") for i in (1, 2, 3)], grown, TODAY)}

    def test_red_proof_7_when_to_update_and_the_gate_exception_are_one_rule_set(self):
        """红证 C（#4233 判据 1，**口径合一**）：基线 `_when_to_update` 与门禁例外条款必须是
        **同一套** —— 不得再写"新增 skip ⇒ **不得**记进本文件"的绝对禁令（它和
        `_history_growth_allowed` 的"末行 + 显式 `note` 允许增长"在同一 PR 评审面里互相矛盾），
        且必须显式指向同一例外 + 写明按类分流。

        判据是**结构化可判**的（正则/子串），不是"读起来不矛盾"：本断言在改动前的文本下**红**。
        """
        text = str(load_baseline().get("_when_to_update") or "")
        gate_exc = _history_growth_allowed.__doc__ or ""
        # 门禁侧的例外仍在（否则"口径合一"被做成"两边都删"= 把重锚定口子彻底封死）
        assert "末行" in gate_exc and "note" in gate_exc, gate_exc
        # ① 绝对禁令形态必须消失（改动前命中 ⇒ 红）
        ban = ABSOLUTE_BAN_RE.search(text)
        assert ban is None, (
            f"`_when_to_update` 仍写着与门禁例外条款矛盾的绝对禁令：{ban.group(0)!r}（原文：{text[:120]!r}）"
        )
        # ② 必须指向门禁例外条款的**同一判据**（末行 + 显式 note）
        for kw in ("末行", "note"):
            assert kw in text, f"`_when_to_update` 未指向门禁例外条款（缺 {kw!r}）：{text[:200]!r}"
        # ③ 必须写明按类分流（`[backend-contract]` 不计入增长）
        assert "backend-contract" in text, f"`_when_to_update` 未写明按类分流：{text[:200]!r}"


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