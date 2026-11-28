# case_ids: CH-015
# （沿用 tests/unit_ci_workflows/** 的既有惯例：用例库 / 流程结构类 L0 不变式统一挂 MC-012；
#   本文件守的是 **CH-015 这条用例自身**的改判形态 ⇒ 声明的就是被它守护的那条用例 id。）
"""`CH-015`「用户显式『转人工』」**2026-11-27 改判**的结构锁（用户裁定）。

## 病：用例把**新能力**判成缺陷（比「少一条断言」更贵）

微信客服（C 端唯一主入口）落地后，「转人工」**真的会转给真人**：

* `backend/admin-api/src/main/java/com/migao/admin/service/kf/KfDecisionService.java` 的
  `HUMAN_REQUEST`（`人工` / `真人` 单独出现，或 动作词 + `人工`/`真人`/`客服`）命中即
  `ESCALATE_HUMAN` —— **规则短路**，不经 AI 语义判定（issue #9302 起 `客服` **单独**出现不再升级：那是称呼/询问）；
* `backend/admin-api/src/main/java/com/migao/admin/service/kf/KfTransferService.java` 的类注释逐字
  「这里不是 human_handoff 工具复活——是通道能力」。

而 `CH-015` 的旧断言是「AI 如实说明系统**无人工转接通道**」，且把「客服马上联系您」列进
`forbidden_text` ⇒ 转接之后**真人确实会联系顾客**，正确行为被这条用例判红（误杀）。
误杀不是「漏检」，它会把后续所有实现往回拽（实现者为了让评测变绿，只能继续否认人工通道）。

## 锁四条（每条单独可红，全部结构判据 —— 不扫「人工」这类中文措辞）

| # | 判据 | 红证（本文件内可执行） |
|---|---|---|
| 1 | `forbidden_text` **不得**再含「客服马上联系您」；而**AI 无权执行**的假承诺四条必须仍在 | 用 `inject()` 把该条加回 `CH-015` 的 `forbidden_text` ⇒ 判据 1 具名红 |
| 2 | `data_checks` **不得**再出现「无人工转接通道」这一族字面量 | 注入一条旧的「如实说明无人工转接通道」⇒ 判据 2 具名红 |
| 3 | `data_checks` 必须承载改判后的三条语义（kf 规则短路承接 / 不得否认人工 + 可执行落点 / 不得编造无权动作） | 删掉任一条 ⇒ 判据 3 具名红 |
| 4 | 用例**仍 live**（`skip_reason` 空）、`tier: normal`、`persona: xiaobu` | 把 `skip_reason` 填上 / 改 `tier` ⇒ 判据 4 具名红 |

**为什么判据 4 是硬约束**：`tests/unit_ci_workflows/test_code_criteria_cases_are_contract_marked.py`
的负控 5 把 `CH-015` 具名钉在「真 LLM 用例、`skip_reason` 必须为空」上 ——
给这条用例贴 `skip_reason` 来「让评测变绿」= 把红藏起来，该负控当场红。

## 边界（照实登记，§19.1）

- 本文件只判**用例语料的形态**（改判是否落地 / 是否被回退），不判真 LLM 行为本身
  （那是 `agent-eval.yml` 的事；按 #4262 口径不自动跑）；
- 判据 3 是**关键字**级（三条语义各自的锚点必须在场），不判措辞好坏
  —— 判措辞会逼出「改措辞消红」的纸面修复（#5196 记过同族取舍）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from unit_ci_workflows.injection import inject  # noqa: E402

CASES_FILE = REPO_ROOT / ".github" / "cases" / "chat.yml"
CASE_ID = "CH-015"

#: 改判后**必须保留**的禁令 = AI **自己无权执行**的假承诺动作。
KEPT_FORBIDDEN = (
    "已为您转接人工",
    "已帮您转接人工",
    "已提交转人工申请",
    "已通知人工客服",
)
#: 改判**必须删掉**的禁令 = kf 转接之后**确实会发生**的正确行为（误杀项）。
MISFIRING_FORBIDDEN = "客服马上联系您"
#: 「人工通道不存在」这一族字面量（改判后不得再出现在 title / data_checks）。
DENIAL_MARKERS = ("已无人工转接通道", "无人工转接通道", "没有人工转接通道")
#: 改判后的三条语义 —— 每组锚点必须全部在场（对应 data_checks 的 a/b/c）。
REQUIRED_SEMANTICS = (
    ("KfDecisionService", "ESCALATE_HUMAN"),
    ("不得否认", "微信客服"),
    ("不得编造", "无权执行"),
)


def load_cases() -> list:
    """`chat.yml` 的全部用例（`yaml.safe_load` = 与标准 YAML 同极，不吃坏样本）。"""
    doc = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8")) or {}
    return [c for c in (doc.get("cases") or []) if isinstance(c, dict)]


def pick(cases: list, case_id: str = CASE_ID) -> dict:
    """按 id 取用例；取不到 ⇒ 直接判红（「找不到 = 通过」是假绿）。"""
    for case in cases:
        if str(case.get("id")) == case_id:
            return case
    raise AssertionError(f"{CASES_FILE} 里找不到用例 {case_id} —— 被改名/删除了？")


def case_from_text(text: str, case_id: str = CASE_ID) -> dict:
    """从**变异后的原文**解析用例（红证专用：判据与线上读**同一份** loader）。"""
    doc = yaml.safe_load(text) or {}
    return pick([c for c in (doc.get("cases") or []) if isinstance(c, dict)], case_id)


# ══════════════════════════════════════════════════════════════════════════════
# 判定本体（纯函数 —— 判据与红证驱动**同一份**实现）
# ══════════════════════════════════════════════════════════════════════════════

def forbidden_problems(case: dict) -> list:
    """判据 1：误杀项必须消失、AI 无权执行的四条必须仍在。"""
    forbidden = [str(x) for x in (case.get("forbidden_text") or [])]
    out = []
    if MISFIRING_FORBIDDEN in forbidden:
        out.append(
            f"{CASE_ID}.forbidden_text 仍含「{MISFIRING_FORBIDDEN}」—— "
            "微信客服转接之后真人确实会联系顾客，禁止这句会**误杀正确行为**")
    for item in KEPT_FORBIDDEN:
        if item not in forbidden:
            out.append(
                f"{CASE_ID}.forbidden_text 缺少「{item}」—— "
                "AI 自己无权执行的假承诺必须仍然禁止")
    return out


def denial_problems(case: dict) -> list:
    """判据 2：`title` / `data_checks` 不得再断言「人工通道不存在」。"""
    texts = [str(case.get("title") or "")] + [str(x) for x in (case.get("data_checks") or [])]
    out = []
    for text in texts:
        for marker in DENIAL_MARKERS:
            if marker in text:
                out.append(
                    f"{CASE_ID} 仍出现「{marker}」：{text[:60]}… —— "
                    "微信客服已落地（规则短路 `ESCALATE_HUMAN`），该断言把新能力判成缺陷")
    return out


def semantics_problems(case: dict) -> list:
    """判据 3：改判后的三条语义必须在 `data_checks` 里有落点。"""
    blob = "\n".join(str(x) for x in (case.get("data_checks") or []))
    out = []
    for group in REQUIRED_SEMANTICS:
        missing = [anchor for anchor in group if anchor not in blob]
        if missing:
            out.append(
                f"{CASE_ID}.data_checks 缺少语义标记 {missing} —— "
                f"改判后的可判语义必须在场（这一组 = {list(group)}）")
    return out


def liveness_problems(case: dict) -> list:
    """判据 4：仍 live（`skip_reason` 空）+ `tier: normal` + `persona: xiaobu`。"""
    out = []
    reason = str(case.get("skip_reason") or "").strip()
    if reason:
        out.append(
            f"{CASE_ID}.skip_reason 非空（{reason[:80]}）—— 改判不是下线："
            "顾客仍会说『转人工』，这条必须是 live 判据")
    tier = str(case.get("tier") or "")
    if tier != "normal":
        out.append(f"{CASE_ID}.tier = {tier!r}（应为 'normal'：改判不动档位）")
    persona = str(case.get("persona") or "")
    if persona != "xiaobu":
        out.append(f"{CASE_ID}.persona = {persona!r}（应为 'xiaobu'：改判不动归属）")
    return out


def all_problems(case: dict) -> list:
    return forbidden_problems(case) + denial_problems(case) + semantics_problems(case) \
        + liveness_problems(case)


# ══════════════════════════════════════════════════════════════════════════════
# 判据（活语料逐条绿）
# ══════════════════════════════════════════════════════════════════════════════

def test_scan_surface_is_not_blind() -> None:
    """扫描面自证：读不到用例时下面的「零违规」是假绿。"""
    cases = load_cases()
    assert len(cases) >= 40, f"chat.yml 只读到 {len(cases)} 条用例 —— 扫描面失效"
    pick(cases)  # 找不到 CH-015 ⇒ 当场红


def test_forbidden_text_drops_misfiring_promise_and_keeps_unbacked_claims() -> None:
    """判据 1：`客服马上联系您` 出局；四条 AI 无权动作仍在。"""
    problems = forbidden_problems(pick(load_cases()))
    assert problems == [], "\n".join(problems)


def test_data_checks_do_not_deny_the_human_channel() -> None:
    """判据 2：`title` / `data_checks` 不再断言「无人工转接通道」。"""
    problems = denial_problems(pick(load_cases()))
    assert problems == [], "\n".join(problems)


def test_data_checks_carry_the_three_recast_semantics() -> None:
    """判据 3：kf 规则短路承接 + 不得否认人工（给落点）+ 不得编造无权动作。"""
    problems = semantics_problems(pick(load_cases()))
    assert problems == [], "\n".join(problems)


def test_case_stays_live_with_normal_tier_and_xiaobu_persona() -> None:
    """判据 4：改判 ≠ 下线（`skip_reason` 空 / `tier: normal` / `persona: xiaobu`）。"""
    problems = liveness_problems(pick(load_cases()))
    assert problems == [], "\n".join(problems)


def test_live_case_has_zero_problems() -> None:
    """四条判据的合取：活语料上问题清单必须为空（红证的反面基线）。"""
    problems = all_problems(pick(load_cases()))
    assert problems == [], "\n".join(problems)


# ══════════════════════════════════════════════════════════════════════════════
# 红证（注入式；注入先自证生效 —— 否则「判据没红」无法区分「判据没牙」与「注入没落上」）
# ══════════════════════════════════════════════════════════════════════════════

def test_red_proof_reinstating_the_misfiring_promise_is_named_red() -> None:
    """把「客服马上联系您」加回 `CH-015` 的 `forbidden_text` ⇒ 判据 1 **具名**红。"""
    src = CASES_FILE.read_text(encoding="utf-8")
    anchor = '      - "已提交转人工申请"\n      - "已通知人工客服"\n'
    mutated = inject(
        src,
        anchor,
        '      - "已提交转人工申请"\n'
        f'      - "{MISFIRING_FORBIDDEN}"\n'
        '      - "已通知人工客服"\n',
        where=".github/cases/chat.yml",
    )
    assert mutated != src, "注入未生效（原文未变）⇒ 下面的红证是空跑"
    problems = forbidden_problems(case_from_text(mutated))
    assert any(MISFIRING_FORBIDDEN in p for p in problems), (
        f"加回「{MISFIRING_FORBIDDEN}」后判据 1 没有具名红 —— 判据没牙。实际 {problems}")


def test_red_proof_restoring_the_denial_wording_is_named_red() -> None:
    """把「如实说明系统无人工转接通道」写回 `data_checks` ⇒ 判据 2 **具名**红。"""
    src = CASES_FILE.read_text(encoding="utf-8")
    anchor = '    data_checks:\n      - "「转人工」在**微信客服通道**'
    base_denial = "如实说明系统" + DENIAL_MARKERS[0]
    mutated = inject(
        src,
        anchor,
        f'    data_checks:\n      - "AI {base_denial}（不承诺转接）"\n      - "「转人工」在**微信客服通道**',
        where=".github/cases/chat.yml",
    )
    assert mutated != src, "注入未生效（原文未变）⇒ 下面的红证是空跑"
    problems = denial_problems(case_from_text(mutated))
    assert any(DENIAL_MARKERS[0] in p for p in problems), (
        f"写回「{DENIAL_MARKERS[0]}」后判据 2 没有具名红。实际 {problems}")


def test_red_proof_skipping_or_downgrading_the_case_is_named_red() -> None:
    """把 `skip_reason` 填上 / `tier` 改掉 ⇒ 判据 4 **具名**红（改判不靠「藏红」）。"""
    live = pick(load_cases())
    skipped = dict(live, skip_reason="[backend-contract] 想让评测变绿就藏起来（负例）")
    tiered = dict(live, tier="smoke")
    assert skipped["skip_reason"] != live["skip_reason"]
    assert tiered["tier"] != live["tier"]
    skip_problems = liveness_problems(skipped)
    tier_problems = liveness_problems(tiered)
    assert any("skip_reason" in p for p in skip_problems), skip_problems
    assert any("tier" in p for p in tier_problems), tier_problems