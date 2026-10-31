# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""停用的周期腿必须**具名登记 + 定期复查**（issue #8218 上线审计 P1-03）。

## 病（2026-10-31 审计读数，逐字）

- **C**：`.github/workflows/nightly-verification.yml::on` 的 `schedule` 已被注释
  （注释写明 2026-09-06 暂停，issue #2957「待根因排查 + 本地验证提速后恢复」）。
- **R**：`gh run list --workflow=nightly-verification.yml` ⇒ 最后三次均 `workflow_dispatch` +
  `failure`（2026-09-14/15），`schedule` 最后一次是 **2026-09-05** ⇒ **夜间回归停了 55 天**。
- 影响：白天只有 `post-merge-verify` / `post-deploy-eval` 兜底；长周期回归（smoke p1 +
  fixture e2e 全量）实际**无人跑**（`tests/unit_ci_workflows/e2e_spec_inventory_ledger.json`
  的 `_reason` 就是这条缺口的影子）。

## 为什么不是「把 schedule 恢复」而是「登记」

铁律 10 的对象是**无人值守的删除 / 破坏性动作**；nightly 两条 job 会在**生产**上跑 smoke p1
（写业务数据）⇒ 恢复它需要先修 #2957 的根因，不是本包能裁的。
审计给的替代路径是**显式登记为「已接受缺口 + 重启条件」** —— 但「登记在注释里」正是本病的形态：
**注释不会过期、不会报警、也没有人因此变红**。所以本判据把登记变成**会红的台账**。

## 判据（每条都能单独变红，见文件末尾的注入式红证）

| # | 判据 | 变红形态 |
|---|---|---|
| 1 | 语料与台账**非空**，停用判据来自**单一出处**（`scripts/drift_audit.py` 的 `PAUSED_SCHED` / `SCHED_LINE`） | 台账 `entries` 清空 ⇒ 红；取不到 drift 判据 ⇒ 红（无法判定 ⇒ 不得当通过） |
| 2 | 🔴 **未登记即红**（防「注释里停了、无人知道」再次发生） | 任一 workflow 的 `schedule` 被注释停用却不在台账 ⇒ 红，并**具名**点出该文件 |
| 3 | **陈旧登记即红**（恢复即销账） | 台账条目对应的文件已删 / 已恢复 `schedule` / 已无注释停用的 cron ⇒ 红 |
| 4 | **六要素齐全**（停用缺口不许匿名存在） | 缺 `reason_issue` / `alternative_legs` / `restart_conditions` / `owner` / `review_due` / `reviewed_at` / `doc` 等任一项 ⇒ 红 |
| 5 | **复查新鲜度**（判据的「新鲜度」那一半） | `review_due` 早于今天 ⇒ 红（**停用缺口过了复查期却没人复查**）；`review_due <= reviewed_at` ⇒ 红（顺延没写清） |
| 6 | **替代腿真存在**（`声明存在 ≠ 可达`，铁律 11） | `alternative_legs` 里点名一个 `.github/workflows/` 下不存在的腿 / 把停用腿自己当替代腿 ⇒ 红 |
| 7 | **声明 ⇄ 现取双向**（名称一致） | 台账的 `name` 与 workflow 的 `name:` 不再一致（改名后审计读不出对应关系）⇒ 红 |
| 8 | **文档接线**：`docs/testing/paused-schedules.md` 里必须有该条的 `doc_markers`（原因 / 复查日期 / 替代腿 …），且停用腿的**注释本身必须指向该文档** | 删掉文档里的锚 ⇒ 红；删掉 workflow 注释里的文档指针 ⇒ 红（那样又回到「注释里停了、无人知道」） |

## 时钟（为什么这里允许读今天）

第 5 条天生依赖「今天」。处置与 `tests/unit_ci_workflows/test_skip_exemption_gate.py` 同口径：
**日期是参数**（`judge(..., today=...)`）⇒ 判据本体是纯函数、红证可把 `today` 支到未来复现「复查过期」；
只有「真语料」那一条测试用 `date.today()`（它的用途正是「到日子就红」，不是可无限重放的快照）。

## 覆盖面（照实登记，§19.1 —— 别读成「停用这件事已被解决」）

- 本台账**不恢复**任何调度，也**不判定**「该不该恢复」—— 它只保证「停用有名有姓、有复查日期、
  过期会红」；重启条件是否达成由 #2957 的承接方裁决。
- 判不了「替代腿真的覆盖了原腿的能力」：它只证明替代腿文件**存在**（运行期覆盖度见
  `tests/unit_ci_workflows/e2e_spec_inventory_ledger.json` 的残余清单）。
- 判不了「值班真的按 `docs/testing/paused-schedules.md` 复算了」—— 复查那一步是**人的动作**，
  本判据只在过期时把「没人复查」这件事变成红。
- 停用形态只认 `# schedule:` / `# - cron:` 两种注释形态（唯一出处 = drift_audit 的两个正则）；
  「整条 workflow 被改名成 `.yml.disabled`」这类停用不在射程内（那种形态 `drift_audit` 也看不见，
  两边口径一致，不另造第二份）。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO / ".github" / "workflows"
LEDGER_PATH = Path(__file__).with_name("paused_schedule_ledger.json")
DOC_PATH = REPO / "docs" / "testing" / "paused-schedules.md"

#: 每条登记必须写清的六要素（+ 名称/日期等形态字段）
REQUIRED_ENTRY_FIELDS = (
    "file",
    "name",
    "paused_since",
    "reason_issue",
    "reason",
    "alternative_legs",
    "residual_gap",
    "restart_conditions",
    "owner",
    "review_due",
    "reviewed_at",
    "doc",
    "doc_markers",
)
DATE_FIELDS = ("paused_since", "reviewed_at", "review_due")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WF_NAME_RE = re.compile(r"(?m)^name:\s*(.+?)\s*$")


# ══════════════════════════════════════════════════════════════════════════
# 判据本体（纯函数：语料/台账/文档/今天 都是入参）
# ══════════════════════════════════════════════════════════════════════════


def drift_regexes() -> tuple[tuple[re.Pattern, re.Pattern] | None, str]:
    """停用判据的**单一出处** = `scripts/drift_audit.py`（不在这里造第二份正则）。"""
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import drift_audit  # noqa: PLC0415  # 复用既有心跳判定，不另立一套
    except Exception as exc:  # noqa: BLE001 - 任何导入失败都必须变成「无法判定」而不是通过
        return None, f"无法从 scripts/drift_audit.py 取到停用判据（PAUSED_SCHED / SCHED_LINE）：{exc.__class__.__name__}: {exc}"
    return (drift_audit.SCHED_LINE, drift_audit.PAUSED_SCHED), ""


def classify_paused(
    workflows: dict[str, str], regexes: tuple[re.Pattern, re.Pattern]
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """→ (仍生效 `schedule` 的腿, `schedule` 被注释停用的腿)；口径与 drift_audit 的心跳判定一致。"""
    sched_re, paused_re = regexes
    active: dict[str, list[str]] = {}
    paused: dict[str, str] = {}
    for name, text in workflows.items():
        head = text.split("\njobs:")[0]
        crons = [c.strip() for c in sched_re.findall(head)]
        if crons:
            active[name] = crons
        elif paused_re.search(text):
            paused[name] = text
    return active, paused


def workflow_name(text: str) -> str:
    m = _WF_NAME_RE.search(text)
    return m.group(1).strip() if m else ""


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def judge(
    *,
    workflows: dict[str, str],
    ledger: dict,
    doc_text: str,
    today: date,
    regexes: tuple[re.Pattern, re.Pattern] | None,
    regex_unavailable: str = "",
) -> list[str]:
    v: list[str] = []

    # ── 判据 1：判据出处 / 语料 / 台账都不许为空（fail-closed）────────────────
    if regexes is None:
        return [f"无法判定停用形态 ⇒ 判红（不得当通过）：{regex_unavailable}"]
    active, paused = classify_paused(workflows, regexes)
    if not workflows:
        v.append("语料为空（`.github/workflows/*.yml` 一个都没读到）⇒ 判定面为 0，不是通过")
    entries = ledger.get("entries")
    if not isinstance(entries, list) or not entries:
        v.append(
            "台账 tests/unit_ci_workflows/paused_schedule_ledger.json 的 `entries` 为空或形态不对"
            "（fail-closed：没东西可判不是通过）"
        )
        entries = []

    registered = {str(e.get("file", "")) for e in entries if isinstance(e, dict)}

    # ── 判据 2：未登记即红（本判据的牙齿）─────────────────────────────────────
    for name in sorted(set(paused) - registered):
        v.append(
            f"`{name}` 的 `schedule` 已被注释停用，却没有登记在 "
            "tests/unit_ci_workflows/paused_schedule_ledger.json ⇒ 这正是「注释里停了、无人知道」的形态："
            "停用必须带原因（issue 号）/ 替代腿 / 重启条件 / 责任人 / 复查日期"
        )

    for entry in entries:
        if not isinstance(entry, dict):
            v.append("台账条目必须是 JSON object")
            continue
        fname = str(entry.get("file", ""))

        # ── 判据 4：六要素齐全 ────────────────────────────────────────────────
        for field in REQUIRED_ENTRY_FIELDS:
            if field not in entry:
                v.append(f"台账条目 `{fname or '?'}` 缺字段 `{field}`（停用缺口不许匿名存在）")
        reason_issue = entry.get("reason_issue")
        if not isinstance(reason_issue, int) or isinstance(reason_issue, bool) or reason_issue <= 0:
            v.append(f"台账条目 `{fname or '?'}` 的 `reason_issue` 必须是正整数（停用原因必须挂到具体 issue）")
        for field in ("reason", "residual_gap", "owner"):
            if not str(entry.get(field, "")).strip():
                v.append(f"台账条目 `{fname or '?'}` 的 `{field}` 为空（缺口不许匿名存在）")
        legs = entry.get("alternative_legs")
        if not isinstance(legs, list) or not legs:
            v.append(f"台账条目 `{fname or '?'}` 的 `alternative_legs` 必须是非空列表（替代腿不许靠口头承诺）")
            legs = []
        conds = entry.get("restart_conditions")
        if not isinstance(conds, list) or not conds or any(not str(c).strip() for c in conds):
            v.append(f"台账条目 `{fname or '?'}` 的 `restart_conditions` 必须是非空、逐条非空的列表")
            conds = []

        # ── 判据 3：陈旧登记即红（恢复即销账）─────────────────────────────────
        if fname not in workflows:
            v.append(
                f"台账登记的 `{fname}` 在 .github/workflows/ 里不存在（文件已删 / 改名）⇒ "
                "陈旧登记（必须销账，否则台账会给不存在的停用面盖章）"
            )
        elif fname in active:
            v.append(
                f"台账登记为「已停用」的 `{fname}` 现取**有**生效的 `schedule`（cron: {active[fname]}）⇒ "
                "陈旧登记：恢复即销账（删台账条目 + 更新 docs/testing/paused-schedules.md）"
            )
        elif fname not in paused:
            v.append(
                f"台账登记为「已停用」的 `{fname}` 现取**没有**注释停用的 `schedule` ⇒ "
                "陈旧登记（要么把停用恢复成可识别的形态，要么销账）"
            )

        # ── 判据 7：声明 ⇄ 现取（名称）───────────────────────────────────────
        if fname in workflows:
            actual = workflow_name(workflows[fname])
            declared = str(entry.get("name", "")).strip()
            if actual and declared != actual:
                v.append(
                    f"台账 `{fname}` 的 `name` 声明为 `{declared}`，而 workflow 现取 `name:` 是 `{actual}` ⇒ "
                    "改名后审计读不出对应关系（声明与现取必须一致）"
                )

        # ── 判据 5：复查新鲜度 ───────────────────────────────────────────────
        parsed: dict[str, date | None] = {}
        for field in DATE_FIELDS:
            d = _parse_date(entry.get(field))
            parsed[field] = d
            if d is None:
                v.append(f"台账条目 `{fname or '?'}` 的 `{field}` 必须是 `YYYY-MM-DD` 形态（现取 {entry.get(field)!r}）")
        reviewed, due = parsed.get("reviewed_at"), parsed.get("review_due")
        if reviewed and due and due <= reviewed:
            v.append(
                f"台账条目 `{fname or '?'}` 的 `review_due`（{due}）不晚于 `reviewed_at`（{reviewed}）⇒ "
                "复查日期没有顺延到下一次复查（等于「复查即过期」）"
            )
        if due and today > due:
            v.append(
                f"台账条目 `{fname or '?'}` 的复查日期已过（review_due={due}，今天={today}）⇒ "
                "停用缺口过了复查期却没人复查：按重启条件恢复，或复查后顺延 review_due 并把新读数写进 "
                "docs/testing/paused-schedules.md"
            )

        # ── 判据 6：替代腿真存在（声明存在 ≠ 可达）─────────────────────────────
        for leg in legs:
            leg_name = str(leg).strip()
            if leg_name == fname:
                v.append(f"台账条目 `{fname or '?'}` 把停用腿自己当成替代腿（`alternative_legs` 含自身）")
            elif leg_name not in workflows:
                v.append(
                    f"台账条目 `{fname or '?'}` 的替代腿 `{leg_name}` 在 .github/workflows/ 下不存在 ⇒ "
                    "替代腿必须点名仓内真实存在的腿（声明存在 ≠ 可达）"
                )

        # ── 判据 8：文档接线（原因/复查日期/替代腿 必须落进人读的地方）────────────
        doc_path = str(entry.get("doc", "")).strip()
        if doc_path and not (REPO / doc_path).is_file():
            v.append(f"台账条目 `{fname or '?'}` 的 `doc`（`{doc_path}`）不是仓内存在的文件")
        markers = entry.get("doc_markers")
        if not isinstance(markers, list) or not markers:
            v.append(f"台账条目 `{fname or '?'}` 的 `doc_markers` 必须是非空列表（文档锚不许空转）")
            markers = []
        for marker in markers:
            text = str(marker).strip()
            if not text:
                v.append(f"台账条目 `{fname or '?'}` 的 `doc_markers` 里有空锚")
            elif text not in doc_text:
                v.append(
                    f"docs/testing/paused-schedules.md 里找不到锚 `{text}`（台账条目 `{fname or '?'}` 要求它必须出现）⇒ "
                    "停用的原因 / 替代腿 / 复查日期必须写进人读的文档，而不是只躺在 JSON 里"
                )
        if fname in workflows and doc_path and doc_path not in workflows[fname]:
            v.append(
                f"`{fname}` 的注释里没有指向 `{doc_path}` 的指针 ⇒ 下一个人只看 workflow 还是不知道"
                "「停了、为什么停、什么时候复查」（这就是「注释里停了、无人知道」的复发形态）"
            )

    return v


# ══════════════════════════════════════════════════════════════════════════
# 真语料
# ══════════════════════════════════════════════════════════════════════════


def _read_workflows() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WORKFLOWS_DIR.glob("*.yml"))}


def _read_ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def _judge_real(today: date | None = None) -> list[str]:
    regexes, why = drift_regexes()
    return judge(
        workflows=_read_workflows(),
        ledger=_read_ledger(),
        doc_text=DOC_PATH.read_text(encoding="utf-8"),
        today=today or date.today(),
        regexes=regexes,
        regex_unavailable=why,
    )


def test_paused_schedules_are_registered_and_fresh():
    v = _judge_real()
    assert not v, "停用周期腿台账未通过：\n- " + "\n- ".join(v)


def test_ledger_and_doc_files_exist():
    assert LEDGER_PATH.is_file(), f"缺少台账 {LEDGER_PATH}"
    assert DOC_PATH.is_file(), f"缺少登记文档 {DOC_PATH}"
    ledger = _read_ledger()
    assert isinstance(ledger.get("entries"), list) and ledger["entries"], (
        "台账 `entries` 为空（fail-closed：停用面必须有具名登记）"
    )


def test_counterpart_heartbeat_still_sees_the_paused_leg():
    """反向锚点：drift_audit 的「paused」判定必须**仍然**看得见这条停用腿。

    它看不见 ⇒ 本台账的前提变了（那条腿可能已被删/改名/恢复），要先复核再动本判据。
    """
    regexes, why = drift_regexes()
    assert isinstance(regexes, tuple) and len(regexes) == 2, f"无法判定停用面 ⇒ 判红（不得当通过）：{why}"
    _, paused = classify_paused(_read_workflows(), regexes)
    ledger_files = {e["file"] for e in _read_ledger()["entries"]}
    assert ledger_files and ledger_files <= set(paused), (
        f"台账登记的停用腿 {sorted(ledger_files)} 与 drift_audit 现取判出的停用面 {sorted(paused)} 分叉"
    )


# ══════════════════════════════════════════════════════════════════════════
# 注入式红证（每条都能单独变红）
# ══════════════════════════════════════════════════════════════════════════


def _judge_from(
    *,
    workflows: dict[str, str] | None = None,
    ledger: dict | None = None,
    doc_text: str | None = None,
    today: date | None = None,
) -> list[str]:
    regexes, why = drift_regexes()
    return judge(
        workflows=_read_workflows() if workflows is None else workflows,
        ledger=_read_ledger() if ledger is None else ledger,
        doc_text=DOC_PATH.read_text(encoding="utf-8") if doc_text is None else doc_text,
        today=today or date.today(),
        regexes=regexes,
        regex_unavailable=why,
    )


def test_injection_unregistered_paused_leg_is_caught():
    """改前形态：这条腿停了 55 天而**没有任何台账** ⇒ 判据 2 必须点名它。"""
    ledger = _read_ledger()
    ledger["entries"] = []
    v = _judge_from(ledger=ledger)
    assert any("没有登记" in x and "nightly-verification.yml" in x for x in v), v


def test_injection_restored_schedule_makes_registration_stale():
    """恢复即销账：把停用腿改回生效 `schedule` 而台账没删 ⇒ 判据 3 必须红。"""
    workflows = _read_workflows()
    src = workflows["nightly-verification.yml"]
    mutated = src.replace("  # schedule:\n", "  schedule:\n", 1).replace(
        "  #   - cron: '0 18 * * *'", "    - cron: '0 18 * * *'", 1
    )
    assert mutated != src, "注入未生效（变异后文本与原文本相同 ⇒ 下面这条红证是空断言）"
    workflows["nightly-verification.yml"] = mutated
    v = _judge_from(workflows=workflows)
    assert any("陈旧登记" in x and "nightly-verification.yml" in x for x in v), v


def test_injection_expired_review_date_is_caught():
    """复查新鲜度：把「今天」支到 review_due 之后 ⇒ 判据 5 必须红（停用缺口不许永久静默）。"""
    ledger = _read_ledger()
    due = date.fromisoformat(ledger["entries"][0]["review_due"])
    v = _judge_from(today=date(due.year + 1, 1, 1))
    assert any("复查日期已过" in x and str(due) in x for x in v), v


def test_injection_missing_doc_marker_is_caught():
    """文档锚不许空转：删掉文档里的一条锚 ⇒ 判据 8 必须红并点名该锚。"""
    ledger = _read_ledger()
    marker = ledger["entries"][0]["doc_markers"][0]
    doc = DOC_PATH.read_text(encoding="utf-8")
    assert marker in doc, f"注入点定位失败：文档里本来就没有锚 `{marker}`"
    mutated = doc.replace(marker, "【已移除】")  # 全文替换（锚可能在文档里出现多次）
    assert marker not in mutated, "变异未生效"
    v = _judge_from(doc_text=mutated)
    assert any("找不到锚" in x and marker in x for x in v), v


def test_injection_comment_pointer_removed_is_caught():
    """接线：停用腿的注释不再指向文档 ⇒ 判据 8 必须红（否则又回到「注释里停了、无人知道」）。"""
    ledger = _read_ledger()
    doc_path = ledger["entries"][0]["doc"]
    workflows = _read_workflows()
    src = workflows["nightly-verification.yml"]
    assert doc_path in src, f"注入点定位失败：workflow 注释里本来就没有 `{doc_path}`"
    workflows["nightly-verification.yml"] = src.replace(doc_path, "", 1)
    v = _judge_from(workflows=workflows)
    assert any("没有指向" in x and doc_path in x for x in v), v


def test_injection_nonexistent_alternative_leg_is_caught():
    """替代腿必须真实存在（声明存在 ≠ 可达）。"""
    ledger = _read_ledger()
    ledger["entries"][0]["alternative_legs"] = ["post-merge-verify.yml", "no-such-leg.yml"]
    v = _judge_from(ledger=ledger)
    assert any("no-such-leg.yml" in x and "不存在" in x for x in v), v


def test_injection_renamed_workflow_is_caught():
    """声明 ⇄ 现取：workflow 改名后台账 `name` 必须同步（否则审计读不出对应关系）。"""
    workflows = _read_workflows()
    src = workflows["nightly-verification.yml"]
    first = src.splitlines()[0]
    assert first.startswith("name: "), f"注入点定位失败：首行不是 name:（现取 {first!r}）"
    workflows["nightly-verification.yml"] = src.replace(first, "name: Nightly (renamed)", 1)
    v = _judge_from(workflows=workflows)
    assert any("改名后审计读不出对应关系" in x for x in v), v


def test_negative_control_unrelated_comment_edit_stays_green():
    """负控：只加一条无关注释 ⇒ 判据**必须保持绿**（否则它会被自己的文案喂红）。"""
    workflows = _read_workflows()
    src = workflows["nightly-verification.yml"]
    workflows["nightly-verification.yml"] = src + "\n# 与本判据无关的一句话（负控）\n"
    v = _judge_from(workflows=workflows)
    assert not v, "无关注释不该判红：\n- " + "\n- ".join(v)
