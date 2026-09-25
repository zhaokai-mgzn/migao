#!/usr/bin/env python3
"""机制存活看门人 —— issue #5326「机制静默失效」这一**类别**的固化。

## 病根（今晚两例各藏 ~40 小时）

机制**停摆 / 瞎了**，但**没有任何读数会因此改变**：

| 实例 | 静默多久 | 为什么没人发现 |
|---|---|---|
| `#5264`：台账 `approve` 因分页缺陷**一次都没发出去** | ~40h | 机制「跑了」且每次都**成功退出**，打印的 ✅ 读数**与事实相反** |
| `#5307`：台账分支 required 测试**恒红** | ~40h | 不在 required 集合 + `flaky-triage` 自指守卫跳过该分支 + reconcile 只补 approve/arm、不读失败原因 |

**已有一半的护栏（本脚本不重做）**：`scripts/drift_audit.py::check_heartbeat()` 判的是
「`schedule:` 存在且没被注释停用」= **调度存在**。它答不了「**最近一次真的干成过事**没有」。

## 本脚本判什么（三条，各带注入式红证 —— 见 tests/unit_ci_workflows/test_mechanism_liveness.py）

1. **登记完整性**（判据 3）：按**结构性规则**（不是文件名清单）发现维护类机制 ⇒ 未登记者判红。
   规则 = `on:` 含 `schedule` / `workflow_run`（**无人值守**）**且** workflow/job 级 `permissions`
   有任一**写**作用域。**实测它零特例地重现 issue #5326 正文列出的 8 条机制**。
2. **读数落点**（判据 1 / 4）：每个 `reading: instrumented` 的机制，其 workflow 必须有
   **独立的一步**（最后一步、`if: always()`）调用 `.github/scripts/mechanism_liveness.sh`
   —— 于是「零动作」也出声（`acted=0` + `why`），而「没跑」是**根本没有这一行**。
3. **存活看门人**（判据 2）：main 上**最近一次已完成**的 run，其注解里必须存在
   **绑定该 run id** 的 `MECHANISM-LIVENESS` 读数；缺失 / 绑定旧 run / **rc 与结论矛盾** ⇒ 红。
   ⚠️ **判定只用 run 归属与结论，不用挂钟时长**（时长受 runner 负载污染 —— 判据 4）。

## 三态退出码（`3` = 无法判定，**不得当 `0` 读**）

`0` = 无 finding；`1` = 有 finding；`3` = 无法判定（PyYAML 缺失 / registry 不可读 / gh 不可达）。

## 边界（照实登记，勿当成"已覆盖"）

- 本脚本证明「**机制跑到读数点了、rc 是多少**」。它**不**验证机制自身的正确性
  （`#5264` 那句与事实相反的 ✅ 是机制**自己**打的）—— 那归各机制自己的判据。
- 读数取自 **GitHub 注解**（`::notice::` 的结构化形态）；注解有 per-step/per-job 上限，
  故判据 2 只要求**读数步是一个独立 step**（保证额度不被同 step 的其它注解挤掉）；
  注解取不到时退化为 `gh run view --log` 抓取（同一语法，两条腿必须一致）。
- 未固化的机制逐条登记在 `scripts/mechanism-registry.json` 的 `unfixed`（判据 5），**不留白**。

一键复算：
    python3 scripts/mechanism_liveness.py --check              # 登记 + 读数落点（离线，确定）
    python3 scripts/mechanism_liveness.py --check --watchdog    # 追加存活看门人（需要 gh）
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

MECHANISM_MARKER = "MECHANISM-LIVENESS"
EMITTER_REL = ".github/scripts/mechanism_liveness.sh"
EMITTER_NAME = "mechanism_liveness.sh"
REGISTRY_REL = "scripts/mechanism-registry.json"

#: 无人值守触发面：没有「某个人/某个 PR」在推动它 —— 停摆了也没人盯着。
UNATTENDED_TRIGGERS = frozenset({"schedule", "workflow_run"})
#: **写**作用域：能改仓库状态的机制才需要「谁在看」。
MUTATING_SCOPES = frozenset({
    "issues", "pull-requests", "contents", "actions", "discussions", "packages", "deployments",
})
VALID_READING_STATUS = frozenset({"instrumented", "unfixed"})
#: 读数落点的形态：`emitter` = 调共享发射器；`inline` = **内联**同一语法（必须带理由 ——
#: 唯一场景是「本 job 不得 checkout」这类安全不变量，见 `check_readings`）。
VALID_READING_SITES = frozenset({"emitter", "inline"})
INLINE_REASON_MIN = 20

REQUIRED_ENTRY_FIELDS = ("id", "name", "workflow", "job", "expected_observable", "criterion", "consumer")
ISSUE_RE = re.compile(r"^#\d{3,}$")
#: 读数行解析（与 `.github/scripts/mechanism_liveness.sh` 的语法**同源**，改语法必须同改两处并有判据钉住）。
#: 读数的**两种载体**必须都能认（issue #5419 实测）：
#:   · **日志行**（`gh run view --log`）：带 workflow-command 前缀，形如 `##[notice]MECHANISM-LIVENESS …`
#:     （日志里还带 ANSI/时间戳，故前缀**可选**匹配）；
#:   · **注解 API**（`…/check-runs/<id>/annotations` 的 `message`）：GitHub **已经吃掉** `notice::` 前缀
#:     （等级在 `annotation_level` 字段里）⇒ 拿带前缀的正则去配它**永远配不上**。
#: ⚠️ 这正是 #5419 的真根因：看门人把「注解存在但没前缀」判成「机制没出声」⇒ **假红**（真机制在正常出声）。
#: 口径不变：仍然**只认结构化字段**（`mech/run/rc/seen/acted/why`），不按文案判（§17.3 ③）。
READING_RE = re.compile(
    r"(?:(?:notice|warning|error)::)?" + MECHANISM_MARKER +
    r"\s+mech=(?P<mech>\S+)\s+run=(?P<run>\S+)\s+rc=(?P<rc>\S+)"
    r"\s+seen=(?P<seen>\S+)\s+acted=(?P<acted>\S+)\s+why=(?P<why>.*)$"
)


@dataclass
class Finding:
    """一条判红。`key` 稳定（不含行号）——只许缩短的台账口径。"""

    key: str
    detail: str
    kind: str = "registration"  # registration | reading | watchdog


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    evaluated: dict[str, int] = field(default_factory=dict)
    status: str = "ok"  # ok | findings | unknown

    def add(self, key: str, detail: str, kind: str) -> None:
        self.findings.append(Finding(key, detail, kind))

    def note(self, text: str) -> None:
        self.notes.append(text)


class Undecidable(Exception):
    """无法判定（**必须**以退出码 3 表达，不得静默当成 0）。"""


# ═══════════════════════════════════════════════════════════════════════════
# 一、发现面（结构性规则，读真 YAML —— 不用正则扫 YAML，本仓已立此教训）
# ═══════════════════════════════════════════════════════════════════════════
def _yaml():
    try:
        import yaml  # noqa: PLC0415  （零依赖退路见 docstring：缺 ⇒ Undecidable，不当绿）
    except ImportError as exc:  # pragma: no cover - CI 显式安装
        raise Undecidable(
            "PyYAML 不可用 ⇒ **无法判定**（本脚本按真 YAML 结构判 `on:` / `permissions:`，"
            "不退化成正则扫文本 —— 那正是本仓 #5323 清扫过的形态）"
        ) from exc
    return yaml


def _write_scopes(perms: object) -> set[str]:
    """`permissions:` 映射里的**写**作用域（只认 `X: write` 这种真语法绑定，不吃注释/文案）。"""
    if not isinstance(perms, dict):
        return set()
    return {
        str(scope)
        for scope, value in perms.items()
        if isinstance(value, str) and value.strip() == "write" and str(scope) in MUTATING_SCOPES
    }


def _triggers(doc: dict) -> set[str]:
    on = doc.get("on", doc.get(True))  # PyYAML 会把裸 `on:` 解析成布尔 True
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(x) for x in on}
    if isinstance(on, dict):
        return {str(k) for k in on}
    return set()


def discover_maintenance_workflows(repo: Path) -> dict[str, dict]:
    """发现**维护类机制**：无人值守触发面 × 写作用域。

    返回 `{文件名: {"writes": [...], "triggers": [...]}}`。
    **实测（本仓 main）**：该规则零特例地重现 issue #5326 正文的 8 条机制。
    """
    yaml = _yaml()
    wf_dir = repo / ".github" / "workflows"
    if not wf_dir.is_dir():
        raise Undecidable(f"workflow 目录不存在：{wf_dir} ⇒ 判定面取空（护栏失效，不得当绿）")
    found: dict[str, dict] = {}
    for path in sorted(wf_dir.glob("*.yml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise Undecidable(f"{path.name} 不是合法 YAML（{exc}）⇒ 解析面残缺，不得当绿") from exc
        if not isinstance(doc, dict):
            continue
        triggers = _triggers(doc)
        if not (triggers & UNATTENDED_TRIGGERS):
            continue
        writes = _write_scopes(doc.get("permissions"))
        for job in (doc.get("jobs") or {}).values():
            if isinstance(job, dict):
                writes |= _write_scopes(job.get("permissions"))
        if writes:
            found[path.name] = {"writes": sorted(writes), "triggers": sorted(triggers)}
    if not found:
        raise Undecidable(
            "结构性发现面为空 —— 没有**任何**维护类机制被识别出来 ⇒ 规则失效（不得当绿）"
        )
    return found


# ═══════════════════════════════════════════════════════════════════════════
# 二、登记清单（判据 3）
# ═══════════════════════════════════════════════════════════════════════════
def load_registry(repo: Path) -> dict:
    path = repo / REGISTRY_REL
    if not path.is_file():
        raise Undecidable(f"机制清单不存在：{REGISTRY_REL} ⇒ 没有任何机制被登记（不得当绿）")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Undecidable(f"{REGISTRY_REL} 不是合法 JSON（{exc}）⇒ 清单读不出来，不得当绿") from exc
    if not isinstance(data, dict) or not isinstance(data.get("mechanisms"), list):
        raise Undecidable(f"{REGISTRY_REL} 缺 `mechanisms` 数组 ⇒ 清单结构不对")
    if not data["mechanisms"]:
        raise Undecidable(f"{REGISTRY_REL} 的 `mechanisms` 为空 ⇒ 登记面为空（护栏失效）")
    return data


def check_registration(repo: Path, registry: dict) -> tuple[Report, dict[str, dict]]:
    """判据 3：**新增维护类机制必须同时登记**，否则『新机制没人看』重演。"""
    rep = Report()
    discovered = discover_maintenance_workflows(repo)
    entries = {str(e.get("workflow", "")): e for e in registry["mechanisms"]}
    registered = {Path(w).name for w in entries}
    rep.evaluated["discovered_maintenance_workflows"] = len(discovered)
    rep.evaluated["registered_mechanisms"] = len(registry["mechanisms"])
    rep.evaluated["exempt"] = len(registry.get("exempt") or [])

    # ── ① 发现面 - 登记面 - 豁免面 = 空（否则有机制**没人看**）──
    exempt = {}
    for item in registry.get("exempt") or []:
        wf = str(item.get("workflow", ""))
        exempt[Path(wf).name] = item
        problems = []
        if len(str(item.get("reason") or "").strip()) < 8:
            problems.append(f"`reason` 缺失或过短（{item.get('reason')!r}）")
        if not ISSUE_RE.match(str(item.get("issue") or "").strip()):
            problems.append(f"`issue` 缺失或不是单号（{item.get('issue')!r}）")
        if problems:
            rep.add(f"exempt:{wf}", f"豁免条目不合规（豁免必须带**理由 + 单号**）：{'；'.join(problems)}", "registration")
        if Path(wf).name in registered:
            rep.add(
                f"exempt-duplicate:{wf}",
                f"{wf} **同时**出现在 `mechanisms` 与 `exempt` 里 —— 两处记账必然漂移"
                f"（一道门要么「已登记」要么「豁免」，不许两条都写）",
                "registration",
            )
        if Path(wf).name not in discovered:
            rep.add(
                f"exempt-stale:{wf}",
                f"豁免条目**已陈旧** —— {wf} 现在不是「无人值守 × 写作用域」的维护类机制 ⇒ 必须删除该条目（台账只许缩短）",
                "registration",
            )
    unregistered = sorted(set(discovered) - registered - set(exempt))
    for name in unregistered:
        info = discovered[name]
        rep.add(
            f"unregistered:{name}",
            f"**未登记的维护类机制**：{name}（无人值守触发面 {info['triggers']} × 写作用域 {info['writes']}）"
            f"\n      ⇒ 它停摆/瞎了**没有任何消费面会知道**。修法（二选一）："
            f"\n         ① 在 `{REGISTRY_REL}` 登记它（机制名 / 工作流 / 期望可观测 / 判据 / 谁看），"
            f"并给它加存活读数步（`{EMITTER_REL}`）；"
            f"\n         ② 若它**不是**维护类机制，在 `exempt` 里登记 **理由 + 单号**（不是「其余全部豁免」的口子）。",
            "registration",
        )

    # ── ①b 判据 5 的**燃尽靶子**（G2）：未固化条数**只许缩短**，现取比对预算 ──
    budget = registry.get("unfixed_budget")
    live_sites = sum(1 for e in registry["mechanisms"] if e.get("reading") != "instrumented")
    live_items = sum(len(e.get("unfixed") or []) for e in registry["mechanisms"])
    rep.evaluated["unfixed_mechanisms"] = live_sites
    rep.evaluated["unfixed_items"] = live_items
    if not isinstance(budget, dict) or not isinstance(budget.get("max_items"), int):
        rep.add(
            "unfixed-budget-missing",
            f"`{REGISTRY_REL}` 缺 `unfixed_budget`（未固化条数的**燃尽靶子**）⇒ 「未固化」可以无限增长而无处可见；"
            f"现取：未固化机制 {live_sites} 个 / 子项 {live_items} 条",
            "registration",
        )
    else:
        if live_items > int(budget["max_items"]):
            rep.add(
                "unfixed-budget-exceeded",
                f"未固化子项**涨了**：现取 {live_items} 条 > 预算 {budget['max_items']} 条 "
                f"（靶子只许缩短 —— 修好一处就下调预算；把新债务登记进 `unfixed` 不是出口）",
                "registration",
            )
        if live_sites > int(budget.get("max_mechanisms", live_sites)):
            rep.add(
                "unfixed-mechanisms-exceeded",
                f"未固化的**机制数**涨了：现取 {live_sites} > 预算 {budget.get('max_mechanisms')}",
                "registration",
            )

    # ── ② 登记条目自身合规 ──
    for entry in registry["mechanisms"]:
        eid = str(entry.get("id") or "<缺 id>")
        missing = [f for f in REQUIRED_ENTRY_FIELDS if not str(entry.get(f) or "").strip()]
        if missing:
            rep.add(f"entry-fields:{eid}", f"登记条目缺字段：{missing}", "registration")
        status = str(entry.get("reading") or "")
        if status not in VALID_READING_STATUS:
            rep.add(f"entry-reading:{eid}", f"`reading` 非法（{status!r}），只许 {sorted(VALID_READING_STATUS)}", "registration")
        site = str(entry.get("reading_site") or "emitter")
        if site not in VALID_READING_SITES:
            rep.add(f"entry-site:{eid}", f"`reading_site` 非法（{site!r}），只许 {sorted(VALID_READING_SITES)}", "registration")
        elif site == "inline" and len(str(entry.get("reading_site_reason") or "").strip()) < INLINE_REASON_MIN:
            # 内联 = 同一真值的**第二处投影** ⇒ 必须写明为什么不能共享实现（#5346 ③），
            # 否则它就是「随手 echo 一行」的规避口子。
            rep.add(
                f"reading-site-reason:{eid}",
                f"`reading_site: inline`（内联发射）必须带 `reading_site_reason`（≥{INLINE_REASON_MIN} 字）写明"
                f"**为什么不能共享发射器** —— 没有理由的内联就是绕过单一真值源的口子",
                "registration",
            )
        wf = str(entry.get("workflow") or "")
        if wf and not (repo / wf).is_file():
            rep.add(f"entry-workflow:{eid}", f"登记的工作流不存在：{wf}", "registration")
        elif wf and Path(wf).name not in discovered:
            rep.add(
                f"entry-not-maintenance:{eid}",
                f"{wf} 现在**不是**维护类机制（无「无人值守 × 写作用域」）⇒ 该条登记已陈旧，须删除或改判",
                "registration",
            )
        # ── ③ 判据 5：未固化必须**逐条**登记「未固化 + 原因 + 谁看」，**不许留白** ──
        unfixed = entry.get("unfixed") or []
        if status == "unfixed" and not unfixed:
            rep.add(
                f"unfixed-blank:{eid}",
                f"`reading: unfixed` 却**没有任何** `unfixed` 条目 —— 「未固化」必须写清**原因 + 谁看**，不许留白",
                "registration",
            )
        for item in unfixed:
            problems = []
            for key in ("what", "reason", "consumer"):
                if len(str(item.get(key) or "").strip()) < 4:
                    problems.append(f"`{key}` 缺失或过短（{item.get(key)!r}）")
            if not ISSUE_RE.match(str(item.get("issue") or "").strip()):
                problems.append(f"`issue` 缺失或不是单号（{item.get('issue')!r}）")
            if problems:
                rep.add(f"unfixed-fields:{eid}", f"未固化条目不合规：{'；'.join(problems)}", "registration")
    return rep, discovered


# ═══════════════════════════════════════════════════════════════════════════
# 三、读数落点（判据 1 / 4）
# ═══════════════════════════════════════════════════════════════════════════
def _job_steps(repo: Path, workflow_rel: str, job_id: str) -> list[dict]:
    yaml = _yaml()
    doc = yaml.safe_load((repo / workflow_rel).read_text(encoding="utf-8"))
    job = ((doc or {}).get("jobs") or {}).get(job_id)
    if not isinstance(job, dict):
        raise Undecidable(f"{workflow_rel} 里没有 job `{job_id}` ⇒ 读数面取不到（不得当绿）")
    steps = job.get("steps")
    if not isinstance(steps, list) or not steps:
        raise Undecidable(f"{workflow_rel} 的 job `{job_id}` 没有 steps ⇒ 读数面取不到")
    return [s for s in steps if isinstance(s, dict)]


def check_readings(repo: Path, registry: dict) -> Report:
    """判据 1：读数落点必须存在、**独立成 step**、且 `if: always()`（零动作与失败也出声）。

    判据 4：「零动作」= 读数在且 `acted=0` + `why` 有内容；「未运行」= **没有这一行**。
    两者形态不同，靠的是「读数步 `if: always()` 且是 job 的**最后一步**」这个结构。
    """
    rep = Report()
    instrumented = [e for e in registry["mechanisms"] if e.get("reading") == "instrumented"]
    rep.evaluated["instrumented_mechanisms"] = len(instrumented)
    rep.evaluated["unfixed_mechanisms"] = len(registry["mechanisms"]) - len(instrumented)
    for entry in instrumented:
        eid, wf, job_id = str(entry["id"]), str(entry["workflow"]), str(entry["job"])
        path = repo / wf
        if not path.is_file():
            rep.add(f"reading-nofile:{eid}", f"读数落点取不到：{wf} 不存在", "reading")
            continue
        site = str(entry.get("reading_site") or "emitter")
        steps = _job_steps(repo, wf, job_id)
        if site == "inline":
            # 内联落点（唯一合法场景：本 job **不得 checkout** ⇒ 取不到发射器文件）。
            # 仍是**同一条语法**：解析器（`READING_RE`）对两处投影是同一个 —— 且由
            # `tests/…/test_inline_emission_is_grammar_equivalent_to_the_emitter`
            # **真跑内联文本**并逐字段比对（不是文案匹配）。
            inline = [
                i for i, s in enumerate(steps)
                if isinstance(s.get("run"), str) and MECHANISM_MARKER in s["run"]
                and f"mech={eid}" in s["run"]
            ]
            if not inline:
                rep.add(
                    f"reading-inline-missing:{eid}",
                    f"{wf} 的 job `{job_id}` 登记为 `reading_site: inline`，但**没有**一个 step 的 `run:` "
                    f"里内联发射 `{MECHANISM_MARKER} mech={eid}` ⇒ 该机制不出声",
                    "reading",
                )
                continue
            idx = inline
        else:
            touches_emitter = [
                s for s in steps if isinstance(s.get("run"), str) and EMITTER_NAME in s["run"]
            ]
            if not touches_emitter:
                rep.add(
                    f"reading-missing:{eid}",
                    f"{wf} 的 job `{job_id}` **没有任何一步**调用读数发射器（`{EMITTER_NAME}`）⇒ "
                    f"**该机制的零动作与停摆长得一模一样**（上半句是 #5264/#5307 的缺陷形态）。"
                    f"修法：在 job 末尾加 `if: always()` 的独立读数步："
                    f"`bash {EMITTER_REL} emit {eid} --outcome \"${{{{ job.status }}}}\"`；"
                    f"若因安全不变量**不能 checkout** ⇒ 登记 `reading_site: inline` 并写明理由",
                    "reading",
                )
                continue
            idx = [i for i, s in enumerate(steps) if f"emit {eid}" in str(s.get("run") or "")]
        if not idx:
            # （`inline` 落点在 `idx` 为空时已 `continue`；走到这里必然是 emitter 落点。）
            rep.add(
                f"reading-noemitterstep:{eid}",
                f"{wf} 的某个 step 引用了 `{EMITTER_NAME}`，但 job `{job_id}` 里**没有**一步真的执行"
                f" `emit {eid}` ⇒ 读数不会被发射（**文案里有、argv 里没有**）",
                "reading",
            )
            continue
        i = idx[0]
        step = steps[i]
        cond = str(step.get("if") or "").replace(" ", "")
        if cond != "always()":
            rep.add(
                f"reading-notalways:{eid}",
                f"{wf} 的读数步 `if:` = {step.get('if')!r}（要求 `always()`）⇒ **失败轮与取消轮不出声**，"
                f"正是「机制停了没人知道」的形态",
                "reading",
            )
        if i != len(steps) - 1:
            later = [str(s.get("name") or s.get("uses") or "<匿名 step>") for s in steps[i + 1:]]
            rep.add(
                f"reading-notlast:{eid}",
                f"{wf} 的读数步不是 job `{job_id}` 的**最后一步**（其后还有 {later}）⇒ "
                f"读数不再是本轮的**最终结论**（后面还可能失败，而读数已经说完话了）",
                "reading",
            )
    return rep


# ═══════════════════════════════════════════════════════════════════════════
# 四、存活看门人（判据 2）—— 纯函数，网络腿与夹具腿**同一判定**
# ═══════════════════════════════════════════════════════════════════════════
def parse_readings(lines: list[str], mech: str) -> list[dict]:
    """从注解 / 日志行里取出某机制的读数行（**只认结构化字段**，不按文案判 —— §17.3 ③）。"""
    out = []
    for line in lines:
        for chunk in str(line).splitlines():
            m = READING_RE.search(chunk.strip())
            if m and m.group("mech") == mech:
                out.append(m.groupdict())
    return out


def judge_watchdog(registry: dict, observations: dict[str, dict]) -> Report:
    """判据 2 的**判定本体**（纯函数）：断言「最近一次成功处置」是新鲜的。

    `observations[mech_id]` 由 provider 产出（网络腿 = gh；夹具腿 = 测试文件），字段：
      · `completed_runs`（int）：main 上**已完成**的 run 数
      · `run_id` / `conclusion` / `head_sha`：最近一次已完成的 run
      · `emitter_at_head_sha`（bool）：该 run 的 commit 上，该 workflow **是否已含**读数发射器
      · `annotations`（list[str]）：该 run 的注解（或日志行）

    ⚠️ **不用挂钟时长**（判据 4）：新鲜 = 读数**绑定到这一次 run**，不是「多久以前」。
    """
    rep = Report()
    judged = 0
    for entry in registry["mechanisms"]:
        eid = str(entry["id"])
        obs = observations.get(eid)
        if obs is None:
            rep.note(f"{eid}: 未取到观测（provider 未覆盖）⇒ **未知**（不等同于通过）")
            continue
        if not obs.get("completed_runs"):
            # 自指 / 首发日：合并当天还没有「已完成的 run」⇒ **note，不是 finding**
            # （与 `scripts/drift_audit.py::check_heartbeat()` 的 `pending-merge` 同族：
            #   监控自己不得自造假红）。
            rep.note(f"{eid}: main 上还没有**已完成**的 run（首发日 / 尚未触发）⇒ pending-first-run")
            continue
        if not obs.get("emitter_at_head_sha"):
            rep.note(
                f"{eid}: 最近一次已完成的 run（{obs.get('run_id')} @ {str(obs.get('head_sha'))[:7]}）"
                f"**早于本机制的读数落点** ⇒ pending-instrumentation（合并后首次触发即纳入判定）"
            )
            continue
        # run 级 `skipped` ＝ **本轮机制未执行**（条件门控/上游 job 没跑）⇒ 与「跑了没出声」**不是一回事**
        # （issue #5419 实测：`flaky-triage` 的最近 run 结论 = skipped ⇒ 旧口径把它报成「没出声」。
        #  与下面 job 级 skipped 的口径**同源**；「连续多轮都跳过」属另一族，见残余登记。）
        # `cancelled` / `timed_out` / `startup_failure` 等**非终态结论**同理：run 被取消 ⇒ 读数步可能
        # 根本没机会跑 ⇒ 判「跑了没出声」是**误判**（本仓口径：取消/跳过都**不是结果**，§16.7）。
        # ⚠️ 「某机制**总是**被取消/从不成功」由**心跳判据**（`drift_audit.py` 的近 N 次零成功）承接，
        #    不在这里报 —— 两条判据分工，不互相抢答。
        if str(obs.get("conclusion") or "") in {"skipped", "cancelled", "timed_out",
                                                 "startup_failure", "stale", "action_required"}:
            rep.note(
                f"{eid}: 最近一次已完成的 run（{obs.get('run_id')}）结论 = **{obs.get('conclusion')}** "
                f"（取消/跳过都**不是结果**）⇒ 本轮**无法判定**（≠「跑了没出声」）⇒ 不计 finding；"
                f"「总是被取消」由心跳判据承接"
            )
            continue
        judged += 1
        run_id = str(obs.get("run_id"))
        lines = list(obs.get("annotations") or [])
        readings = parse_readings(lines, eid)
        if not readings:
            skipped_job = _mechanism_job_skipped(registry, eid, obs)
            if skipped_job:
                # 「job 被跳过」≠「跑了没出声」：前者是机制**本轮没执行**（多 job workflow 的合法形态），
                # 后者才是缺陷。⚠️ 若**连续多轮**都被跳过 ⇒ 属另一族（需多 run 取数，见残余登记）。
                rep.note(
                    f"{eid}: 最近一次已完成的 run（{run_id}）上，本机制的 job（`{skipped_job}`）"
                    f"结论 = **skipped** ⇒ 本轮机制**未执行**（≠「跑了没出声」）⇒ 不计 finding"
                )
                continue
            rep.add(
                f"watchdog-no-reading:{eid}",
                f"最近一次已完成的 run（{run_id}，结论 {obs.get('conclusion')}）**没有**该机制的存活读数"
                f" —— 机制「跑了」而**没有出声**（读数为空 = 与「没跑」不可区分）",
                "watchdog",
            )
            continue
        live = [r for r in readings if r["run"] == run_id]
        if not live:
            rep.add(
                f"watchdog-stale-reading:{eid}",
                f"最近一次已完成的 run 是 {run_id}，但读数绑定的是 "
                f"{sorted({r['run'] for r in readings})} ⇒ **读数已旧**（本轮读数没有更新）",
                "watchdog",
            )
            continue
        reading = live[-1]
        conclusion = str(obs.get("conclusion") or "")
        rc = reading["rc"]
        if conclusion == "success" and rc not in ("0",):
            rep.add(
                f"watchdog-contradiction:{eid}",
                f"读数**与事实相反**：run {run_id} 结论 = success，而读数 `rc={rc}`（#5264 的形态）",
                "watchdog",
            )
        elif conclusion not in ("success", "") and rc == "0":
            rep.add(
                f"watchdog-contradiction:{eid}",
                f"读数**与事实相反**：run {run_id} 结论 = {conclusion}，而读数 `rc=0` "
                f"（机制报成功、事实是失败 —— #5264 的形态）",
                "watchdog",
            )
    rep.evaluated["judged_mechanisms"] = judged
    if judged == 0 and rep.findings:
        rep.status = "findings"
    return rep


# ═══════════════════════════════════════════════════════════════════════════
# 五、观测 provider（网络腿）
# ═══════════════════════════════════════════════════════════════════════════
def _gh(args: list[str]) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise Undecidable(f"gh {' '.join(args)} 失败：{proc.stderr.strip()[:300]}")
    return proc.stdout


def _gh_json(args: list[str]):
    return json.loads(_gh(args) or "null")


def _annotations_of_run(repo_slug: str, run_id: int) -> list[str]:
    """run 的注解（`::notice::` 的结构化形态）；取不到 ⇒ 退化为日志抓取（**同一语法**）。"""
    messages: list[str] = []
    try:
        jobs = _gh_json(["api", f"/repos/{repo_slug}/actions/runs/{run_id}/jobs"])
        for job in (jobs or {}).get("jobs", []):
            url = job.get("check_run_url")
            if not url:
                continue
            ann = _gh_json(["api", f"{url}/annotations"])
            for item in ann or []:
                messages.append(str(item.get("message") or ""))
    except (Undecidable, json.JSONDecodeError):
        messages = []
    if messages:
        return messages
    try:
        return _gh(["run", "view", str(run_id), "--log"]).splitlines()
    except Undecidable:
        return []


def _job_conclusions_of_run(repo_slug: str, run_id: int) -> dict[str, str]:
    """该 run 里每个 job 的结论（**归一化键**：小写、非字母数字→`-`）。

    用途：区分「**job 被跳过** ⇒ 本轮机制根本没跑」与「机制跑了但**没出声**」—— 两者在
    「读数为空」上长得一样，但归因完全不同（§23 G3）。首发日实测：`automerge` 的 run 里
    `Enable auto-merge` 两个 job 按事件条件**合法跳过**，只有 `detect-dangling-prs` 跑了。
    ⚠️ GitHub 只给 job 的**显示名**（YAML 里的 `name:`）⇒ 用归一化键与登记册的 `job` id 比对；
    对不上就**当作非跳过**（fail-closed：宁可判红让人看，也不静默豁免）。
    """
    try:
        jobs = _gh_json(["api", f"/repos/{repo_slug}/actions/runs/{run_id}/jobs"])
    except (Undecidable, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for job in (jobs or {}).get("jobs", []):
        key = _normalize_job(str(job.get("name") or ""))
        if key:
            out[key] = str(job.get("conclusion") or "")
    return out


def _normalize_job(name: str) -> str:
    return "-".join("".join(c if c.isalnum() else " " for c in name.lower()).split())


#: 「有结论」的 run 结论集合（只有它们才可能合法地承载读数；其余属非终态）。
JUDGEABLE_CONCLUSIONS = frozenset({"success", "failure"})


def _pick_judgeable_run(completed: list[dict]) -> dict:
    """从「已完成」的 run 里挑**可判**的那一次（issue #5419）。

    为什么不能直接取 `completed[0]`：`cancelled` / `skipped` 等**非终态**里，读数步可能根本没机会跑
    （本仓口径：取消/跳过都**不是结果**，§16.7）⇒ 拿它判「跑了没出声」是**误判**。
    ⚠️ 但也不能就此"只看最新那条"：若最新恰是 cancelled、而更早的 success 真的没出声，
    那条**真信号**会被漏掉 ⇒ 规则 = **先挑可判的**；一条可判的都没有时，才回落到最新那条
    （由 `judge_watchdog` 走「无法判定」note 分支）。
    """
    judgeable = [r for r in completed if str(r.get("conclusion") or "") in JUDGEABLE_CONCLUSIONS]
    return (judgeable or completed)[0]


def _mechanism_job_skipped(registry: dict, eid: str, obs: dict) -> str:
    """该 run 上**这个机制的 job** 是否被跳过 ⇒ 返回 job id（被跳过）或空串。"""
    entry = next((m for m in registry.get("mechanisms", []) if str(m.get("id")) == eid), None)
    job = str((entry or {}).get("job") or "").strip()
    if not job:
        return ""
    conclusions = obs.get("job_conclusions") or {}
    return job if str(conclusions.get(_normalize_job(job)) or "").lower() == "skipped" else ""


def _workflow_has_emitter_at(repo_slug: str, workflow_rel: str, sha: str) -> bool:
    """该 run 的 commit 上，这个 workflow **是否已含**读数发射器（用于 pending-instrumentation）。"""
    try:
        payload = _gh_json(["api", f"/repos/{repo_slug}/contents/{workflow_rel}?ref={sha}"])
        content = base64.b64decode(payload.get("content") or "").decode("utf-8", "ignore")
    except (Undecidable, json.JSONDecodeError, ValueError):
        return True  # 取不到 ⇒ **按已含**处理（fail-closed：宁可判红让人看，也不静默豁免）
    return EMITTER_NAME in content


def observe_via_gh(repo_slug: str, registry: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for entry in registry["mechanisms"]:
        eid = str(entry["id"])
        wf = Path(str(entry["workflow"])).name
        runs = _gh_json([
            "run", "list", "--workflow", wf, "--branch", "main", "--limit", "20",
            "--json", "databaseId,conclusion,status,headSha",
        ]) or []
        completed = [r for r in runs if r.get("status") == "completed"]
        if not completed:
            out[eid] = {"completed_runs": 0}
            continue
        newest = _pick_judgeable_run(completed)
        out[eid] = {
            "completed_runs": len(completed),
            "run_id": newest.get("databaseId"),
            "conclusion": newest.get("conclusion"),
            "head_sha": newest.get("headSha"),
            "emitter_at_head_sha": _workflow_has_emitter_at(
                repo_slug, str(entry["workflow"]), str(newest.get("headSha") or "")
            ),
            "annotations": _annotations_of_run(repo_slug, int(newest["databaseId"])),
            "job_conclusions": _job_conclusions_of_run(repo_slug, int(newest["databaseId"])),
        }
    return out


def observe_via_fixture(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise Undecidable(f"读数夹具结构不对（应为 {{mech_id: {{...}}}}）：{path}")
    return data


# ═══════════════════════════════════════════════════════════════════════════
# 六、入口
# ═══════════════════════════════════════════════════════════════════════════
def run(repo: Path, watchdog: bool, readings: Path | None, repo_slug: str | None) -> tuple[Report, dict]:
    registry = load_registry(repo)
    rep, discovered = check_registration(repo, registry)
    readings_rep = check_readings(repo, registry)
    rep.findings.extend(readings_rep.findings)
    rep.evaluated.update(readings_rep.evaluated)
    if watchdog:
        observations = observe_via_fixture(readings) if readings else observe_via_gh(repo_slug or "", registry)
        wd = judge_watchdog(registry, observations)
        rep.findings.extend(wd.findings)
        rep.notes.extend(wd.notes)
        rep.evaluated.update(wd.evaluated)
    rep.status = "findings" if rep.findings else "ok"
    meta = {
        "registry": registry,
        "discovered": discovered,
        "burn_down": {
            "unfixed_budget": registry.get("unfixed_budget") or {},
            "mechanisms": len(registry["mechanisms"]),
            "instrumented": sum(1 for e in registry["mechanisms"] if e.get("reading") == "instrumented"),
            "unfixed": sum(1 for e in registry["mechanisms"] if e.get("reading") != "instrumented"),
            "unfixed_items": sum(len(e.get("unfixed") or []) for e in registry["mechanisms"]),
            "exempt": len(registry.get("exempt") or []),
        },
    }
    return rep, meta


def render(rep: Report, meta: dict) -> str:
    bd = meta["burn_down"]
    out = [
        "## 机制存活看门人（issue #5326）",
        "",
        f"- 发现面（无人值守 × 写作用域）：**{len(meta['discovered'])}** 个维护类机制",
        f"- 登记面：**{bd['mechanisms']}** 条（instrumented **{bd['instrumented']}** / unfixed **{bd['unfixed']}**，"
        f"未固化子项 **{bd['unfixed_items']}** 条（预算 "
        f"{(bd.get('unfixed_budget') or {}).get('max_items', '缺')} 条，**只许缩短**）；豁免 **{bd['exempt']}** 条）",
        f"- 判定面：{rep.evaluated}",
        "",
    ]
    if rep.findings:
        out.append(f"### ❌ 判红 {len(rep.findings)} 条")
        out.append("")
        for f in rep.findings:
            out.append(f"- **[{f.kind}] {f.key}**：{f.detail}")
        out.append("")
    else:
        out.append("### ✅ 无 finding")
        out.append("")
    if rep.notes:
        out.append("### 备注（**不是**通过，也不等于失败）")
        out.append("")
        out.extend(f"- {n}" for n in rep.notes)
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="机制存活看门人（issue #5326）")
    ap.add_argument("--repo", default=".", help="仓库根（默认当前目录）")
    ap.add_argument("--check", action="store_true",
                    help="登记完整性 + 读数落点（**离线、确定性**；不加 --watchdog 时的默认行为）")
    ap.add_argument("--watchdog", action="store_true", help="追加存活看门人（判据 2；需要 gh 或 --readings）")
    ap.add_argument("--readings", type=Path, default=None, help="读数夹具（离线，与网络腿**同一判定**）")
    ap.add_argument("--repo-slug", default=None, help="owner/repo（网络腿用；默认读 GH_REPO / git remote）")
    ap.add_argument("--json", type=Path, default=None, help="机器可读报告落点")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    slug = args.repo_slug
    if args.watchdog and not args.readings and not slug:
        import os
        slug = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY")
        if not slug:
            try:
                url = subprocess.run(
                    ["git", "-C", str(repo), "remote", "get-url", "origin"],
                    capture_output=True, text=True, timeout=30,
                ).stdout.strip()
                m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
                slug = m.group(1) if m else None
            except (OSError, subprocess.TimeoutExpired):
                slug = None
    try:
        rep, meta = run(repo, args.watchdog, args.readings, slug)
    except Undecidable as exc:
        print(f"::error::机制存活看门人**无法判定**（退出码 3，**不得当 0 读**）：{exc}", file=sys.stderr)
        print(render(Report(status="unknown"), {"discovered": {}, "burn_down": {
            "mechanisms": 0, "instrumented": 0, "unfixed": 0, "unfixed_items": 0, "exempt": 0}}))
        return 3
    print(render(rep, meta))
    if args.json:
        args.json.write_text(json.dumps({
            "status": rep.status,
            "findings": [f.__dict__ for f in rep.findings],
            "notes": rep.notes,
            "evaluated": rep.evaluated,
            "burn_down": meta["burn_down"],
            "discovered": meta["discovered"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if rep.findings else 0


if __name__ == "__main__":
    sys.exit(main())
