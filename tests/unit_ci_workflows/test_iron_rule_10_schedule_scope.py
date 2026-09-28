# case_ids: MC-047
"""铁律 10 的**窄例外**必须有机械承载体：新增 `schedule` **未登记即红**（2026-09-27 收窄，不取消禁令）。

## 病（规则与事实不一致 ⇒ 两种坏结果，任选其一都会发生）

| 事实 | 现取读数（2026-09-27，可复算） |
|---|---|
| 仓库根 `AGENTS.md` 铁律 10 的原文 | 「⛔ 不新增 schedule/cron（2026-09-21 裁定：无人值守删除不安全）」= **无条件禁令** |
| 同一天已落地的**两条每日 cron** | `.github/workflows/worker-h5-publish.yml` `23 18 * * *` · `.github/workflows/bmini-h5-publish.yml` `43 18 * * *`（PR #5731 合并，main = `9ab25c1eb`；用户 2026-09-27 逐字裁定 = 方案 A） |
| 后果（**规则不许只活在散文里**） | 下一个人读铁律 10 ⇒ ① 照旧规则办（**挡住合法工作**）或 ② 整条铁律被无视（**规则侵蚀**）；两者都不需要任何东西变红 |

⇒ **2026-09-27 用户裁定**：把铁律 10 的适用范围**收窄到「无人值守删除 / 破坏性动作」**（「按你建议的执行即可」），
**不是取消它**。本判据把「收窄」这件事从散文变成**会变红的机械判据**。

## 判据（每条都能单独变红；红证**全部内存构造**，见 `test_discriminating_power_in_memory`）

| # | 判据 | 语义 / 变红的形态 |
|---|---|---|
| 1 | 语料与台账**非空**，读数现取打印 | 空语料 / 空 `baseline` / 空 `exceptions` ⇒ 红（fail-closed：「没东西可判」不是通过） |
| 2 | 🔴 **未登记即红**（本单的牙齿） | 全仓任何一个带 `on.schedule` 的 workflow，既不在 `baseline`、也不是 `exceptions` 的具名实例 ⇒ 红（**新造一条 cron ⇒ 立刻红**） |
| 3 | **陈旧登记即红** | 登记的 workflow 现取**没有** `on.schedule`（或文件已删）⇒ 红（台账只许缩短） |
| 4 | **存量基线只许缩短**（两处冻结） | 台账 `baseline` ⇄ 本文件 `BASELINE_FILES_FROZEN` **必须逐项相等**；条数 ≤ `BASELINE_COUNT_MAX` 且 == 台账 `baseline_frozen` ⇒ 想「把新 schedule 塞进 baseline」必须同时改三处且数字变大（diff 里看得见） |
| 5 | **例外类封闭枚举** | `kind` ∉ {`republish`, `readonly_heartbeat`} ⇒ 红（不许自创第三类） |
| 6 | 🔴 **非破坏性证据锚可解析 + 锚唯一** | 三个锚（非破坏性 / 幂等 / 自证）都必须是 `<仓库相对路径>::<符号或文本片段>`：路径存在、片段在该文件里**出现至少一次**（**删光即红**）；`non_destructive_anchor` **不得被两条实例复用**（一个锚给所有东西盖章 ⇒ 红） |
| 7 | **具名双向**（判据 ⇄ 铁律正文） | `exceptions` 的 `pr` 集合 ⇄ `AGENTS.md` 铁律 10 里「📌 已批准具名实例」那行的 `#N` 集合**双向相等** ⇒ 登记了却没具名 / 具名了却没登记 ⇒ 红 |
| 8 | **声明 ⇄ 现取（双向）** | 登记的 `cron` 必须逐字出现在该 workflow 的 `on.schedule` 里，且该 workflow 的**每一条** cron 都被登记 ⇒ 台账不许给不存在的周期面盖章，也不许漏一条 |
| 9 | 🔴 **规则本体不许被删**（收窄 ≠ 取消） | 铁律 10 正文里必须**逐字**还有禁令本体（`⛔ 不新增 schedule/cron` + `无人值守`）**和**两个日期（`2026-09-21` / `2026-09-27`）⇒ 谁把禁令删了、或把出处写成「历来如此」⇒ 红 |
| 10 | **覆盖面登记** | `coverage_boundary` 每条须带 `face` / `reason` / `recompute` ⇒ 缺口不许匿名存在 |
| 11 | 🔴 **在飞实例（`pending`）一落地就必须升格** | `pending` 只是跨包交接（**不构成登记**）：其 `pr` 也要在铁律正文具名；且 `pending[].file` 一旦现取出现 `on.schedule` ⇒ **必须**移入 `exceptions`（补齐三个证据锚）⇒ 留在 `pending` = 红（不许变成「永远的在飞」） |

## 判定方式是确定的（零网络、零时钟）

只读仓内文件（`.github/workflows/*.yml` + 本目录的台账 JSON + `AGENTS.md`）⇒ 同一份代码在任何时刻给出**同一读数**。
反例（**刻意不进判据**）：`gh run list …` / `gh pr view …` 这类运行期读数会随时刻变（且「PR body 里到底声明了没有」
判据**读不到**）⇒ 它们只作为**当时的读数 + 复算命令**写在台账 `coverage_boundary` 里。

## 覆盖面（照实登记，**不是**「已全覆盖」）

逐条写在台账 `coverage_boundary`（8 条）：远端执行体到底删不删（**运行期**事实，判据只核锚可解析）/ 幂等判不了实跑 /
「失败可见」判不了「真的有人看」（`Drift Audit` 不在 required 集合 ⇒ 非阻断 + 3 天延迟）/ 第 ④ 条 PR body 声明判据读不到 /
**存量 14 条基线是否安全不在面内**（只裁新增）/ cron 跑没跑（节流、`concurrency`）/
「周期档只报告、不写盘」判不了写盘档的 `if` 在运行期真的拦住 / 与 MC-039 的
`publish_leg_fallback_ledger.json` 不互为副本也互不重判。
`test_coverage_boundary_is_registered` 逐条核 face + reason + recompute ⇒ 删掉任一条 ⇒ 红。
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Mapping

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO / ".github" / "workflows"
AGENTS_PATH = REPO / "AGENTS.md"
LEDGER_PATH = Path(__file__).with_name("schedule_scope_ledger.json")

#: 铁律 10 的正文块：`10. ` 起、`11. ` 止。取不到 ⇒ **fail-closed 红**（不当「无需判」）。
RULE10_START_RE = re.compile(r"^10\.\s", re.M)
RULE10_END_RE = re.compile(r"^11\.\s", re.M)

#: 🔴 **禁令本体**（逐字取自 2026-09-21 裁定那一句）：收窄 ≠ 取消 ⇒ 少一段就判红。
PROHIBITION_MARKERS = (
    "⛔ 不新增 schedule/cron",
    "无人值守",
)
#: 出处与日期必须在正文里（不许写成「历来如此」）：2026-09-21 原裁定 / 2026-09-27 收窄裁定。
NARROWING_MARKERS = (
    "2026-09-21",
    "2026-09-27",
)
#: 铁律正文里「已批准具名实例」的标记行；该行的 `#N` 集合 ⇄ 台账 `exceptions` 的 `pr` 集合（双向）。
INSTANCE_MARKER = "📌 已批准具名实例"
PR_RE = re.compile(r"#(\d+)")
#: 例外类**封闭枚举**（铁律 10 的窄例外只有这两类）；自创第三类 ⇒ 红。
EXCEPTION_KINDS = frozenset({"republish", "readonly_heartbeat"})
#: 每条实例必须带的三个证据锚（对应四条判据的 ①②③）。
ANCHOR_KEYS = ("non_destructive_anchor", "idempotency_anchor", "self_proof_anchor")
#: 其中**必须逐条不同**的锚（腿自己的非破坏性判定点；其余两个锚允许跨腿共用同一实现）。
UNIQUE_ANCHOR_KEYS = ("non_destructive_anchor",)
#: 覆盖面登记每条必须带的键（缺一 ⇒ 红；「缺口不许匿名存在」）。
BOUNDARY_KEYS = ("face", "reason", "recompute")
#: `pending`（**在飞**具名实例，不构成登记）每条必须带的键：能追到 PR / 周期 / 类 / 理由 / **升格动作**。
PENDING_REQUIRED = ("file", "pr", "cron", "kind", "why", "on_merge")

#: 🔴 存量冻结快照（判据侧）：台账 `baseline` 与它**必须等于**（逐项相等、无重复、无多无少）。
#: 同源声明面 = `declaration_gate_registry.json` 的 `same_source_claims`，
#: 判据 = 本文件 `test_baseline_matches_the_frozen_snapshot_in_two_places`。
BASELINE_FILES_FROZEN = (
    "automerge.yml",
    "close-linked-issues.yml",
    "deploy-admin-api.yml",
    "deploy-ai-agent-service.yml",
    "deploy-frontend.yml",
    "deploy-reconcile.yml",
    "drift-audit.yml",
    "fixture-record.yml",
    "flaky-ledger-reconcile.yml",
    "main-freshness-guard.yml",
    "mechanism-liveness.yml",
    "post-merge-verify.yml",
    "redproof-sweep.yml",
    "stale.yml",
)
#: 存量条数上限（**只许缩短**）：与冻结快照、台账 `baseline_frozen` **三处一致**才放行。
BASELINE_COUNT_MAX = 14


# ══════════════════════════════════════════════════════════════════════════════
# 一、现取（唯一来源 = 真文件；判据吃的是**文本/对象**，红证可内存构造）
# ══════════════════════════════════════════════════════════════════════════════


def on_block(wf: object) -> dict:
    """`on:` 的**真 YAML** 形态（裸 `on:` 会被 yaml 解析成布尔键 `True`；也兼容列表 / 字符串写法）。"""
    if not isinstance(wf, dict):
        return {}
    on = wf.get("on")
    if on is None and True in wf:
        on = wf.get(True)
    if isinstance(on, str):
        return {on: {}}
    if isinstance(on, list):
        return {str(e): {} for e in on}
    return on if isinstance(on, dict) else {}


def scheduled_crons(wf: object) -> tuple[str, ...]:
    """该 workflow 的 `on.schedule[].cron`（**结构性**取法；注释里的 `# - cron:` 不算）。"""
    sched = on_block(wf).get("schedule")
    if not sched:
        return ()
    if not isinstance(sched, list):
        sched = [sched]
    return tuple(str(e.get("cron")) for e in sched if isinstance(e, dict) and e.get("cron"))


def schedule_bearing(docs: Mapping[str, object]) -> dict[str, tuple[str, ...]]:
    """`{workflow 文件名: (cron, …)}` —— 只收**真的**带 `on.schedule` 的那些。"""
    return {str(name): crons for name, crons in docs.items() if crons}


def read_workflows() -> dict[str, tuple[str, ...]]:
    """现取全仓 workflow 的周期面（只读仓内文件，零网络零时钟）。"""
    if not WORKFLOWS_DIR.is_dir():
        raise AssertionError(f"workflow 目录不存在：{WORKFLOWS_DIR} —— 判据 fail-closed")
    out: dict[str, tuple[str, ...]] = {}
    for path in sorted(list(WORKFLOWS_DIR.glob("*.yml")) + list(WORKFLOWS_DIR.glob("*.yaml"))):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        out[path.name] = scheduled_crons(doc)
    return {name: crons for name, crons in out.items() if crons}


def rule10_block(text: str) -> str | None:
    """铁律 10 的正文块（`10. ` 到 `11. ` 之间）；取不到 ⇒ `None`（调用方判红）。"""
    start = RULE10_START_RE.search(text)
    if not start:
        return None
    end = RULE10_END_RE.search(text, start.end())
    return text[start.start(): end.start() if end else len(text)]


def named_instance_prs(block: str) -> set[int]:
    """铁律正文里「📌 已批准具名实例」**那一段**（标记行起、到空行 / 正文块末为止）上的 PR 号。

    取整段而不是只取标记那一行：多个实例天然要分行写（现取 3 条），而「一行一个标记」既难看也容易漏。
    """
    lines = block.splitlines()
    start = next((i for i, line in enumerate(lines) if INSTANCE_MARKER in line), None)
    if start is None:
        return set()
    out: set[int] = set()
    for line in lines[start:]:
        if not line.strip():
            break
        out.update(int(n) for n in PR_RE.findall(line))
    return out


def anchor_problems(anchor: object, label: str) -> list[str]:
    """`<仓库相对路径>::<符号或文本片段>` 必须可解析（路径存在 + 片段出现 ≥1 次）。"""
    if not isinstance(anchor, str) or "::" not in anchor:
        return [f"锚形态非法（须写成 `<仓库相对路径>::<符号>`）：{label}={anchor!r}"]
    rel, _, fragment = anchor.partition("::")
    if not rel.strip() or not fragment.strip():
        return [f"锚的路径或片段为空：{label}={anchor!r}"]
    target = REPO / rel.strip()
    if not target.is_file():
        return [f"锚指向的文件不存在（死锚）：{label}={anchor!r}"]
    if fragment not in target.read_text(encoding="utf-8"):
        return [
            f"锚的片段在该文件里**找不到**（被删光或改写）：{label}={anchor!r}"
            " ⇒ 证据锚失效（非破坏性 / 幂等 / 自证 的机械承载体没了）"
        ]
    return []


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据本体（纯函数；红证**内存构造**直接喂它）
# ══════════════════════════════════════════════════════════════════════════════


def ledger_problems(ledger: object, docs: Mapping[str, object], agents_text: str) -> list[str]:
    """→ 逐条问题（空列表 = 通过）。**所有判据都在这里**，红证无需改盘。"""
    problems: list[str] = []

    def bad(tag: str, msg: str) -> None:
        problems.append(f"[{tag}] {msg}")

    live = schedule_bearing(docs)
    # ── 判据 1：语料 / 台账非空（fail-closed：「没东西可判」不是通过）────────────────
    if not live:
        bad("语料为空", f"`{WORKFLOWS_DIR.name}/**` 里没有任何带 `on.schedule` 的 workflow —— 判据无对象可判（**不是通过**）")
    if not isinstance(ledger, dict):
        return problems + ["[台账形态] 台账必须是 JSON 对象"]
    baseline, exceptions = ledger.get("baseline"), ledger.get("exceptions")
    if not isinstance(baseline, list) or not isinstance(exceptions, list):
        return problems + ["[台账形态] `baseline` / `exceptions` 必须都是数组"]
    if not baseline:
        bad("登记表为空", "`baseline` 为空 ⇒ 存量冻结清单被清空（fail-closed 红）")
    if not exceptions:
        bad("登记表为空", "`exceptions` 为空 ⇒ 具名窄例外一条都没有（fail-closed 红）")
    entries = [e for e in exceptions if isinstance(e, dict)]
    registered = {str(x) for x in baseline} | {str(e.get("file")) for e in entries}
    # `pending`（**在飞**具名实例）：不构成登记，只做跨包交接；判据 11 管它「一落地即须升格」。
    raw_pending = ledger.get("pending", [])
    if not isinstance(raw_pending, list):
        bad("在飞登记", "`pending` 存在时必须是数组（`[]` 表示当前无在飞实例）")
        raw_pending = []
    pending_entries = [p for p in raw_pending if isinstance(p, dict)]

    # ── 判据 2：未登记即红（本单的牙齿）─────────────────────────────────────────
    for name in sorted(set(live) - registered):
        bad(
            "未登记即红",
            f"`.github/workflows/{name}` 有 `on.schedule`（现取 {list(live[name])}）但**未登记** —— "
            "铁律 10：新增周期面必须 ①非破坏性 ②幂等 ③失败可见 ④在 PR body 显式声明，"
            f"并在 `tests/unit_ci_workflows/{LEDGER_PATH.name}` 的 `exceptions` 里具名（带三个证据锚）、"
            "同时在 `AGENTS.md` 铁律 10 的「📌 已批准具名实例」行上具名",
        )
    # ── 判据 3：陈旧登记即红（台账只许缩短）─────────────────────────────────────
    for name in sorted(registered - set(live)):
        bad("陈旧登记", f"`{name}` 被登记为有周期面，但现取它**没有** `on.schedule`（或文件已删）⇒ 销账（台账只许缩短）")

    # ── 判据 4：存量基线只许缩短（三处一致）─────────────────────────────────────
    frozen_ledger = ledger.get("baseline_frozen")
    if sorted(str(x) for x in baseline) != sorted(BASELINE_FILES_FROZEN):
        bad(
            "基线只许缩短",
            "台账 `baseline` 与本判据的 `BASELINE_FILES_FROZEN` **不逐项相等** ⇒ 两处一起改才生效"
            f"（台账 {len(baseline)} 项 / 冻结快照 {len(BASELINE_FILES_FROZEN)} 项）",
        )
    if len(baseline) > BASELINE_COUNT_MAX:
        bad("基线只许缩短", f"`baseline` 条数 {len(baseline)} > 冻结上限 {BASELINE_COUNT_MAX} ⇒ 存量只许缩短；新增面**必须**走 `exceptions`")
    if frozen_ledger != BASELINE_COUNT_MAX:
        bad("基线只许缩短", f"台账 `baseline_frozen`={frozen_ledger!r} 与判据里的 `BASELINE_COUNT_MAX`={BASELINE_COUNT_MAX} 不符 ⇒ 三处之一被单改")
    if len(set(str(x) for x in baseline)) != len(baseline):
        bad("基线只许缩短", "`baseline` 里有重复项（重复 = 用同一格充数）")

    # ── 判据 7：具名双向（台账 ⇄ 铁律正文）─────────────────────────────────────
    block = rule10_block(agents_text)
    if block is None:
        bad("规则本体", "在 `AGENTS.md` 里**取不到**铁律 10 的正文块（`10. ` 起、`11. ` 止）⇒ fail-closed 红")
        named: set[int] = set()
    else:
        named = named_instance_prs(block)
    entry_prs = {int(e["pr"]) for e in entries if isinstance(e.get("pr"), int)}
    pending_prs = {int(p["pr"]) for p in pending_entries if isinstance(p.get("pr"), int)}
    declared_prs = entry_prs | pending_prs
    if not named:
        bad("具名双向", f"铁律 10 里找不到「{INSTANCE_MARKER}」行上的任何 PR 号 ⇒ 例外没有被规则正文具名（fail-closed 红）")
    for pr in sorted(declared_prs - named):
        bad("具名双向", f"台账登记的实例 PR #{pr} **没有**出现在铁律 10 的「{INSTANCE_MARKER}」行上 ⇒ 规则与事实不一致（补具名，或撤登记）")
    for pr in sorted(named - declared_prs):
        bad("具名双向", f"铁律 10 具名了 PR #{pr}，但台账 `exceptions` / `pending` 里**都没有**它 ⇒ 具名不许「给不存在的保护盖章」")

    # ── 判据 9：规则本体不许被删（收窄 ≠ 取消）+ 出处与日期 ──────────────────────
    if block is not None:
        for marker in PROHIBITION_MARKERS:
            if marker not in block:
                bad("规则本体", f"铁律 10 正文里**找不到禁令本体**的逐字片段 {marker!r} ⇒ 收窄被写成了取消（红线）")
        for marker in NARROWING_MARKERS:
            if marker not in block:
                bad("规则本体", f"铁律 10 正文里**找不到裁定日期** {marker!r} ⇒ 收窄不许写成「历来如此」（要写明 2026-09-21 原裁定 / 2026-09-27 收窄裁定）")

    # ── 判据 5/6/8：逐条核实例（枚举 / 锚 / 声明⇄现取）──────────────────────────
    for entry in entries:
        name = str(entry.get("file"))
        if entry.get("kind") not in EXCEPTION_KINDS:
            bad(
                "例外类越界",
                f"`{name}` 的 `kind`={entry.get('kind')!r} 不在铁律 10 的封闭枚举 {sorted(EXCEPTION_KINDS)} 里 ⇒ 不许自创第三类",
            )
        for key in ANCHOR_KEYS:
            for msg in anchor_problems(entry.get(key), f"{name}.{key}"):
                bad("锚不可解析", msg)
        for key in ("pr", "date", "approved_by", "why"):
            if not entry.get(key):
                bad("锚不可解析", f"`{name}` 缺 `{key}`（具名实例必须能追到 PR / 日期 / 批准人 / 理由）")
        if name in live:
            declared = str(entry.get("cron"))
            if declared not in live[name]:
                bad(
                    "声明⇄现取",
                    f"`{name}` 声明的 `cron`={declared!r} 不在现取的 `on.schedule` {list(live[name])} 里 ⇒ 台账给不存在的周期面盖章",
                )
            covered = {str(e.get("cron")) for e in entries if str(e.get("file")) == name}
            for cron in live[name]:
                if cron not in covered:
                    bad("声明⇄现取", f"`{name}` 现取有一条 cron `{cron}` **没有被任何登记项覆盖**（漏登记）")
    for key in UNIQUE_ANCHOR_KEYS:
        seen: dict[str, str] = {}
        for entry in entries:
            anchor = str(entry.get(key))
            if anchor in seen and seen[anchor] != str(entry.get("file")):
                bad(
                    "锚不唯一",
                    f"`{key}` 被 `{seen[anchor]}` 与 `{entry.get('file')}` 复用（{anchor!r}）⇒ 一个锚不许给多条实例盖章",
                )
            seen.setdefault(anchor, str(entry.get("file")))

    # ── 判据 11：在飞实例（`pending`）—— 只是交接，**一落地就必须升格** ─────────────
    for item in pending_entries:
        name = str(item.get("file"))
        if item.get("kind") not in EXCEPTION_KINDS:
            bad("在飞登记", f"`pending` 条目 `{name}` 的 `kind`={item.get('kind')!r} 不在封闭枚举 {sorted(EXCEPTION_KINDS)} 里")
        for key in PENDING_REQUIRED:
            if not item.get(key):
                bad("在飞登记", f"`pending` 条目 `{name}` 缺 `{key}`（在飞实例必须能追到 PR / 周期 / 类 / 理由 / **升格动作**）")
        if name in live:
            bad(
                "在飞即红",
                f"`{name}` 已经在现取语料里出现 `on.schedule`（{list(live[name])}）⇒ **不许留在 `pending`**："
                "必须升格为 `exceptions` 并补齐三个证据锚（`non_destructive_anchor` / `idempotency_anchor` / "
                "`self_proof_anchor`）—— `pending` 不许变成「永远的在飞」",
            )

    # ── 判据 10：覆盖面登记（缺口不许匿名存在）─────────────────────────────────
    boundary = ledger.get("coverage_boundary")
    if not isinstance(boundary, list) or not boundary:
        bad("覆盖面登记", "`coverage_boundary` 为空 ⇒ 覆盖边界不许匿名存在（fail-closed 红）")
    else:
        for i, item in enumerate(boundary):
            if not isinstance(item, dict):
                bad("覆盖面登记", f"`coverage_boundary[{i}]` 必须是对象")
                continue
            for key in BOUNDARY_KEYS:
                if not str(item.get(key) or "").strip():
                    bad("覆盖面登记", f"`coverage_boundary[{i}]` 缺 `{key}`（每条须有 face + reason + recompute）")
    return problems


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据（每条单独变红；红证见 test_discriminating_power_in_memory）
# ══════════════════════════════════════════════════════════════════════════════


def _state() -> tuple[dict, dict[str, tuple[str, ...]], str]:
    if not LEDGER_PATH.exists():
        raise AssertionError(f"台账不存在：{LEDGER_PATH} —— 判据 fail-closed（缺台账 = 周期面无人管，不是「无需登记」）")
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return ledger, read_workflows(), AGENTS_PATH.read_text(encoding="utf-8")


def _problems(tag: str) -> list[str]:
    ledger, docs, agents = _state()
    return [p for p in ledger_problems(ledger, docs, agents) if p.startswith(f"[{tag}]")]


def test_corpus_and_registry_are_not_empty() -> None:
    """判据 1：现取读数必须打印出来（「扫不到」不许长得像「通过」）。"""
    ledger, docs, _agents = _state()
    print(f"现取带 `on.schedule` 的 workflow = {len(docs)} 条：{sorted(docs)}")
    print(f"台账 baseline={len(ledger['baseline'])} 条 · exceptions={len(ledger['exceptions'])} 条")
    assert docs, "语料为空 ⇒ 判据无对象可判（fail-closed，不是通过）"
    assert ledger["baseline"] and ledger["exceptions"], "台账 baseline / exceptions 不许为空"


def test_no_unregistered_schedule_in_live_corpus() -> None:
    """判据 2（牙齿）：全仓新出现的 `on.schedule` 未登记 ⇒ 红。"""
    assert not _problems("未登记即红") and not _problems("登记表为空"), "\n".join(_problems("未登记即红") + _problems("登记表为空"))


def test_no_stale_registration_in_ledger() -> None:
    """判据 3：登记了却现取不到 ⇒ 红。"""
    assert not _problems("陈旧登记"), "\n".join(_problems("陈旧登记"))


def test_baseline_matches_the_frozen_snapshot_in_two_places() -> None:
    """判据 4：存量基线只许缩短（台账 ⇄ 冻结快照 ⇄ 条数上限，三处一致）。"""
    assert not _problems("基线只许缩短"), "\n".join(_problems("基线只许缩短"))


def test_exception_kinds_are_a_closed_enum() -> None:
    """判据 5：例外类封闭枚举（`republish` / `readonly_heartbeat`）。"""
    assert not _problems("例外类越界"), "\n".join(_problems("例外类越界"))


def test_exception_evidence_anchors_resolve_and_are_unique() -> None:
    """判据 6：三个证据锚可解析（删光即红）+ 非破坏性锚唯一。"""
    assert not _problems("锚不可解析") and not _problems("锚不唯一"), "\n".join(
        _problems("锚不可解析") + _problems("锚不唯一")
    )


def test_iron_rule_10_keeps_the_prohibition_and_names_every_instance() -> None:
    """判据 7 + 9：规则本体（禁令 + 两个日期）在位，且实例与台账**双向**具名。"""
    assert not _problems("规则本体") and not _problems("具名双向"), "\n".join(
        _problems("规则本体") + _problems("具名双向")
    )


def test_exception_cron_matches_the_live_trigger_surface() -> None:
    """判据 8：声明 ⇄ 现取（两个方向）。"""
    assert not _problems("声明⇄现取"), "\n".join(_problems("声明⇄现取"))


def test_coverage_boundary_is_registered() -> None:
    """判据 10：覆盖面每条须有 face + reason + recompute。"""
    assert not _problems("覆盖面登记"), "\n".join(_problems("覆盖面登记"))


def test_pending_instances_are_declared_and_promoted_on_landing() -> None:
    """判据 11：在飞实例必须可追（PR / cron / 类 / **升格动作**），且**一落地就必须升格**。"""
    assert not _problems("在飞登记") and not _problems("在飞即红"), "\n".join(
        _problems("在飞登记") + _problems("在飞即红")
    )


def test_real_corpus_is_green() -> None:
    """真语料上必须**零问题**（这是本判据的「双向自证」：语料侧不是空转）。"""
    ledger, docs, agents = _state()
    problems = ledger_problems(ledger, docs, agents)
    assert not problems, "真语料上有问题：\n" + "\n".join(problems)


# ══════════════════════════════════════════════════════════════════════════════
# 四、判别力自证（红证**全部内存构造**：真文件当基线 → 改内存对象 → 直接喂纯函数）
#
# 🔴 为什么不用「改磁盘上的真文件 → 跑 pytest」：本仓实测（`docs/wiki/CI-CD.md`
#    「红证机具的可靠性」节，2026-09-27）那条路**变异可能不被读到** ⇒ 判据恒绿 = 空断言。
# ══════════════════════════════════════════════════════════════════════════════


def _mutants() -> list[tuple[str, str, dict, dict, str]]:
    """→ `[(红证名, 期望命中的分支 tag, 台账, docs, AGENTS 文本), …]`（全部当场内存构造）。"""
    ledger, docs, agents = _state()
    out: list[tuple[str, str, dict, dict, str]] = []

    def add(name: str, tag: str, led=None, dc=None, tx=None) -> None:
        out.append((name, tag, copy.deepcopy(led if led is not None else ledger), dict(dc if dc is not None else docs), tx if tx is not None else agents))

    led = copy.deepcopy(ledger)
    led["exceptions"] = []
    led["baseline"] = [b for b in ledger["baseline"]]
    add("删光 exceptions（两条实例失去登记）", "未登记即红", led=led)

    add("新造一条未登记的周期面", "未登记即红", dc={**docs, "brand-new-leg.yml": ("5 5 * * *",)})
    add("台账登记了一条现取不存在的腿", "陈旧登记", led={**copy.deepcopy(ledger), "baseline": ledger["baseline"] + ["ghost-leg.yml"]}, dc=docs, tx=agents)
    add("把新 schedule 塞进 baseline（台账侧单改）", "基线只许缩短", led={**copy.deepcopy(ledger), "baseline": ledger["baseline"] + ["brand-new-leg.yml"]}, dc=docs, tx=agents)
    add("台账 baseline_frozen 单改", "基线只许缩短", led={**copy.deepcopy(ledger), "baseline_frozen": 15}, dc=docs, tx=agents)

    led = copy.deepcopy(ledger)
    led["exceptions"][0]["kind"] = "cleanup"
    add("自创第三类例外（cleanup）", "例外类越界", led=led)

    led = copy.deepcopy(ledger)
    led["exceptions"][0]["non_destructive_anchor"] = "deploy/swas/h5-publish-remote.sh::这个符号不存在"
    add("非破坏性锚被删光", "锚不可解析", led=led)

    led = copy.deepcopy(ledger)
    led["exceptions"][1]["non_destructive_anchor"] = ledger["exceptions"][0]["non_destructive_anchor"]
    add("两条实例复用同一个非破坏性锚", "锚不唯一", led=led)

    led = copy.deepcopy(ledger)
    led["exceptions"][0]["cron"] = "59 23 * * *"
    add("声明的 cron 与现取脱钩", "声明⇄现取", led=led)

    add("铁律 10 删掉禁令本体", "规则本体", tx=agents.replace("⛔ 不新增 schedule/cron", "⛔ 可以新增 schedule/cron"))
    add("铁律 10 删掉裁定日期", "规则本体", tx=agents.replace("2026-09-21", "某日").replace("2026-09-27", "某日"))
    add("铁律 10 的具名实例行被删", "具名双向", tx=agents.replace(INSTANCE_MARKER, "（摘掉了）"))
    add("铁律 10 具名了另一个 PR", "具名双向", tx=agents.replace("#5731", "#9999"))
    add("取不到铁律 10 正文块", "规则本体", tx=agents.replace("\n10. ", "\n十、 "))
    # 判据 11 的红证必须**自造**在飞实例：本单（#4184）落地时把 `pending` 清空了 ⇒ 旧写法在**空 pending** 上
    # 恒不命中（实测「无任何问题 ⇒ 变异没生效」），那是**红证自己坏了**、不是判据变强。「空 pending 合法」的语义未动。
    led = copy.deepcopy(ledger)
    led["pending"] = [{
        "file": "c-end-h5-publish.yml", "pr": 5733, "cron": "53 18 * * *",
        "kind": "readonly_heartbeat", "why": "红证自造：这条腿**已经落地**（语料里有它的 on.schedule）却仍留在 pending",
        "on_merge": "（红证）本应已升格",
    }]
    add("在飞实例已经落地却仍留在 pending", "在飞即红", led=led)
    add("在飞实例的 PR 没在铁律正文里具名", "具名双向", tx=agents.replace("#5733", "#9999"))
    # ⚠️ 本红证**自造**一条在飞实例，不依赖台账当下是否恰好有 `pending` 条目
    #    （issue #4184 的实例落地后 `pending` 变空 ⇒ 旧写法 `pending[0]` 会 IndexError，
    #     那是**红证自己坏了**、不是判据变强；判据 11 的「空 pending 合法」语义一字未动）。
    led = copy.deepcopy(ledger)
    led.setdefault("pending", []).append({
        "file": "forged-in-flight.yml", "pr": 5731, "cron": "0 0 * * *",
        "kind": "readonly_heartbeat", "why": "红证自造的在飞实例（只为验「缺升格动作」这一条）",
        "on_merge": "占位：下面当场删掉，模拟「没有升格动作」",
    })
    del led["pending"][-1]["on_merge"]
    add("在飞实例缺升格动作", "在飞登记", led=led)
    return out


def test_discriminating_power_in_memory() -> None:
    """红证逐条 + 「只改注释 ⇒ 不红」对照 + 「坏形态读数 ≠ 基线读数」自证。"""
    base_ledger, base_docs, base_agents = _state()
    baseline_problems = ledger_problems(base_ledger, base_docs, base_agents)
    assert not baseline_problems, "基线（真语料）本该零问题：\n" + "\n".join(baseline_problems)

    readings: list[str] = []
    for name, tag, led, dc, tx in _mutants():
        mutant_problems = ledger_problems(led, dc, tx)
        hit = [p for p in mutant_problems if p.startswith(f"[{tag}]")]
        readings.append(f"  {name} ⇒ 命中 [{tag}]：{hit[0] if hit else '（没命中！）'}")
        assert hit, f"红证「{name}」没有命中分支 [{tag}]；实得：\n" + "\n".join(mutant_problems or ["（无任何问题 ⇒ 变异没生效）"])
        assert mutant_problems != baseline_problems, f"红证「{name}」的读数与基线相同 ⇒ 变异没被读到（空断言）"
    print("红证读数（逐条）：\n" + "\n".join(readings))

    # 对照：「只改注释」不得报红（否则判据会把正常编辑当坏形态）。
    commented_docs = dict(base_docs)
    commented_docs["worker-h5-publish.yml"] = base_docs["worker-h5-publish.yml"]  # 形状不变
    benign = ledger_problems(
        base_ledger,
        commented_docs,
        base_agents.replace("\n## 按场景找文档", "\n<!-- 只加一条 HTML 注释：不影响任何判据 -->\n## 按场景找文档"),
    )
    assert not benign, "只改注释不该报红；实得：\n" + "\n".join(benign)
    print("对照：「只改注释 ⇒ 不红」= 通过（0 条问题）")
