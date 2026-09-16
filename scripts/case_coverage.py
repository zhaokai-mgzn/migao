#!/usr/bin/env python3
"""
评测用例「能力覆盖体检」共享核心（issue #3555）。

**为什么单独成模块**：C 端（`xiaobu_coverage.py`）与 B 端（`mibao_coverage.py`）
体检必须**同一口径**——判据、端归属、薄覆盖定义只要复制一份就会漂移（历史教训：
两套并行实现 → 一处改了另一处不知道 → 「本地绿 CI 红」/ 假绿）。故：
  · 用例选择复用 `eval_case_filter.select_cases_for_persona`（运行器同一实现）；
  · 端工具集复用 `eval_case_filter.XIAOBU_TOOLS` / `mibao_real_toolset()`（源码解析真值）；
  · 本模块只补「覆盖矩阵 + 薄覆盖判定」这一层纯计算；
  · 两个 CLI 脚本只做参数解析与渲染，不含判据。

**判据（与 verify-all.sh 既有设计意图一致）**：
  ① 结构性缺失（**硬失败**）：工具 0 用例 / 只有对抗档或否定式用例（缺正向用例）/
     孤儿用例（用例挂到了错的端）/ 端用例集为空；
  ② 厚度不足（**只报告，不阻塞**）：某工具仅 1 条用例。条数是**随迭代收敛的活指标**
     —— verify-all.sh:66-68 明确拒绝 `--max-uncovered` 式硬编码阈值（制造返工式门禁）。
     本模块把两者分开输出，就是为了让"缺口"可见而"收敛中"不被拦。

零第三方依赖（仅标准库 + 仓库内纯函数），可在 CI 的 pytest+pyyaml 轻量 job 里跑。
"""
from __future__ import annotations       # 前置类型注解（脚本需兼容 python3.9 系统解释器）

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT / ".github"), str(REPO_ROOT / "tests" / "agent_eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_case_filter as lr  # noqa: E402

# 正向用例判据的唯一实现在 `eval_case_filter`（用例选择与覆盖判据同一处，防漂移）；
# 此处再导出，使"体检"的调用方与测试不必知道它住在哪个模块。
is_positive_case = lr.is_positive_case

PERSONAS = ("xiaobu", "mibao")

# ── 存量豁免清单（burn-down baseline，issue #3575 决策记录）──────────────────────
# 为什么需要：门禁首次接入时必然与**存量**结构性缺口冲突（工具零用例 / 只有拒绝式断言）。
# 直接放宽判据 = 门禁变摆设；直接挡住所有 PR = 用存量债锁死流水线。第三条路是
# **显式、可收缩的清单**：只豁免**已登记**的存量缺口，任何**新出现**的缺口照旧阻塞。
#
# 防「白名单变垃圾场」的四道锁（缺一即红，全部由 `load_baseline` + 单测强制）：
#   ① 每条必须带齐 tool / kind / issue / reason（issue 必须是真实存在的 issue 号格式）；
#   ② 条目必须**指向该端真实工具**且**确实对应一种已知缺口 kind**；
#   ③ 条目若指向工具**当前不存在的缺口** = 陈旧登记（销账后没删）→ 阻塞；
#   ④ 条目 kind 必须与该工具**当前实际的缺口 kind** 一致（例如工具只有 1 条用例，
#      却登记成 `missing_positive` → 判陈旧，逼登记与实际对齐）。
# 清单是**工作清单不是免死金牌**：报告里逐条打印归属 issue，补完用例即删条目。
BASELINE_PATH = REPO_ROOT / ".github" / "eval-coverage-baseline.yml"
BLOCKING_KINDS = ("uncovered", "missing_positive", "action_dangling")
REPORTING_KINDS = ("thin", "thin_positive")
GAP_KINDS = BLOCKING_KINDS + REPORTING_KINDS
ENTRY_REQUIRED_FIELDS = ("tool", "kind", "issue", "reason", "added")
_ISSUE_RE = re.compile(r"^#\d+$")
_MIN_REASON_LEN = 8

# ── action 级覆盖（工具级之下的一层，issue #3667）────────────────────────────────
# 背景：工具级矩阵问不出「这个工具**有**用例，但它的某个 action 从没被测」——
# 实证 `processing_item_manage` 9 个 action 只有 3 个被断言、
# `processing_order_update` 4 个只有 1 个（PG-016 靠 `action: complete` 撑起整域覆盖），
# 而工具级矩阵把它们显示成"✅ 已覆盖"。真值取**工具源码的 action 枚举**（不是从用例反推，
# 否则缺失的 action 根本不在集合里 = 缺口不可见）。
#
# 处置分两档（与既有 `dangling_cases` / `thin_tools` 同构，见 issue #3667 决策记录）：
#   · `action_uncovered`（该工具有用例、该 action 零覆盖）→ **只报告**：仓库实测 41 处，
#     阻塞即大面积飘红 = 用存量债锁死流水线；且它本质是**厚度**指标（§14.5 已把"仅 1 条用例"
#     定为只报告），不是"能力完全没被测"的结构性缺失；
#   · `action_dangling`（用例声明了工具**不存在**的 action）→ **阻塞**：这是配置错误
#     （断言永不满足 = 假红/假绿），与拼错工具名的 `dangling_cases` 同一家族。
#     #3701 补齐三处**假绿盲区**（旧实现实测全部放行）：① 只遍历「有 action 维度的工具」
#     （OR-026 那种 `must_fail: [{tool: order_create, action: create}]` 被整条跳过）；
#     ② 只扫 `select_cases_for_persona()` 选中的用例（skip 的用例藏住悬空声明，如 OR-006）；
#     ③ 不收 `repeat_until.action`。判据唯一实现在 `action_binding_violations`（下方），
#     L0 不变式 `tests/unit_ci_workflows/test_eval_assertion_action_binding.py` 调用同一函数。
TOOLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "tools"
_ACTION_PROP_RE = re.compile(r'"action"\s*:\s*\{')
_ENUM_RE = re.compile(r'"enum"\s*:\s*\[(.*?)\]', re.S)
_ACTION_VALUE_RE = re.compile(r'"([A-Za-z_][A-Za-z0-9_]*)"')
_ACTION_ARG_RE = re.compile(r"action\s*=\s*([A-Za-z_][A-Za-z0-9_]*)")
# 解析到的「多 action 工具」数下界（防源码解析静默失效 → action 报告假绿）。
# 不是覆盖门禁阈值：只用来发现**解析器坏了**（新增多 action 工具后请同步上调）。
ACTION_TOOL_FLOOR = 15


def tool_declared_actions(tool: str) -> set:
    """工具源码声明的 action 全集（真值 = `parameters.properties.action.enum`）。

    ⚠️ 用**花括号配对**取 `action` 属性块，而不是 `.*?"enum"` 非贪婪跨属性匹配：
    后者在"action 无 enum、但后面某个属性有 enum"的工具上会**串味**（把 status 的枚举
    当成 action 的），串味的后果是缺口判错且**看不出来**。
    """
    path = TOOLS_DIR / f"{tool}.py"
    if not path.exists():
        return set()
    try:
        src = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    m = _ACTION_PROP_RE.search(src)
    if not m:
        return set()
    start, depth, end = m.end() - 1, 0, -1
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return set()
    e = _ENUM_RE.search(src[start + 1:end])
    if not e:
        return set()
    return set(_ACTION_VALUE_RE.findall(e.group(1)))


def action_catalog(tools) -> dict:
    """该端「工具 → 声明的 action 全集」（只含**有 action 维度**的工具）。"""
    out = {}
    for t in sorted(tools):
        acts = tool_declared_actions(t)
        if acts:
            out[t] = acts
    return out


def _split_actions(raw) -> list:
    """`raw` → action 名列表；支持 `a or b`（仓库实有此形态：notification_manage）。"""
    out = []
    for part in re.split(r"\s+or\s+", str(raw or ""), flags=re.IGNORECASE):
        part = part.strip()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", part):
            out.append(part)
    return out


def case_declared_actions(case) -> dict:
    """用例**机器可判声明**里的 `tool → {action}`（不做自然语义猜测）。

    来源（2026-09-14 实测清点，覆盖仓库现有全部形态）：
      · `expectations[].args.action`（dict 形态）与 `expectations` 字符串形态
        （`customer_manage(action=list)`）；
      · `must_succeed[] / output_verify[] / required_args[] / must_fail[]` 的 `{tool, action}`；
      · `db_verify[]` 的 `{source, action}`（`source` 指写工具，同 runner 口径）。
    **不收**自然语义 `data_checks`（"customer_id 从 customer_manage 查询获得"）——
    它不是可执行判据（acceptance-protocol §1.3），拿它当覆盖证据就是"看起来有覆盖"。
    """
    def get(key):
        return (case.get(key) if isinstance(case, dict)
                else getattr(case, key, None)) or []

    out: dict = {}

    def add(tool, raw_action) -> None:
        tool = str(tool or "").strip()
        if tool:
            for a in _split_actions(raw_action):
                out.setdefault(tool, set()).add(a)

    for exp in get("expectations"):
        if isinstance(exp, dict):
            args = exp.get("args")
            add(exp.get("tool"), (args or {}).get("action") if isinstance(args, dict) else None)
            continue
        # 字符串形态（`customer_manage(action=list)`）：只认**单分支**——`A or B` 下
        # action 归属哪个分支无法从文本判定，宁可不收（本判据在"新增断言能力"上取保守侧：
        # 漏收只少一条报告，误收会造出假 `action_dangling` 阻塞）。
        branches = lr.expectation_branches(exp)
        if len(branches) == 1:
            for m in _ACTION_ARG_RE.finditer(str(exp)):
                add(branches[0], m.group(1))
    for key in ("must_succeed", "output_verify", "required_args", "must_fail"):
        for spec in get(key):
            if isinstance(spec, dict):
                add(spec.get("tool"), spec.get("action"))
    for spec in get("db_verify"):
        if isinstance(spec, dict):
            add(spec.get("tool") or spec.get("source"), spec.get("action"))
    return out


def repeat_until_bindings(case) -> list:
    """用例 `user_inputs[].repeat_until.action` 声明的 `(tool, action)`（#3667 的 action 级停条件）。

    ⚠️ 只服务于「声明的 action **是否存在**」这一配置合法性判据（`action_binding_violations`），
    **不作为覆盖证据**（停条件不等于断言，拿它当"该 action 被测过"会虚增覆盖率）。
    """
    out = []
    for ui in (case.get("user_inputs") if isinstance(case, dict)
               else getattr(case, "user_inputs", None)) or []:
        if not isinstance(ui, dict):
            continue
        spec = ui.get("repeat_until")
        for s in (spec if isinstance(spec, list) else [spec]):
            if not isinstance(s, dict):
                continue
            tool = str(s.get("tool_called") or s.get("tool") or "").strip()
            action = str(s.get("action") or "").strip()
            if tool and action:
                out.append((tool, action))
    return out


def case_action_bindings(case) -> dict:
    """用例声明的**全部** `tool → {action}`：机器可判断言 + `repeat_until.action`。

    与 `case_declared_actions` 的分工（有意分开，别合并）：后者是**覆盖证据**
    （skip 的用例不算证据、停条件也不算证据）；本函数只喂 `action_binding_violations`
    这一配置合法性判据 —— 把停条件也算成覆盖会让 `action_uncovered` 静默缩水。
    """
    out = {t: set(a) for t, a in case_declared_actions(case).items()}
    for tool, action in repeat_until_bindings(case):
        out.setdefault(tool, set()).add(action)
    return out


def action_enum(tool: str) -> set | None:
    """工具源码声明的 action 枚举；`None` = 该工具**没有源码文件**（不在本判据职责内）。

    与 `tool_declared_actions` 同一份解析实现，只多区分「工具不存在」（None）与
    「工具存在但没有 action 维度」（空集）—— 后者是**结构性配置错误**（声明任何 action
    都永不满足，必须报出），前者交给工具级 `dangling_cases` 判据，避免同一件事报两遍。
    """
    if not (TOOLS_DIR / f"{tool}.py").exists():
        return None
    return tool_declared_actions(tool)


def registered_tools() -> set:
    """两端注册表并集（B 端米宝 + C 端小布）—— 未注册工具由 `dangling_cases` 判据管。"""
    return set(lr.mibao_real_toolset()) | set(lr.XIAOBU_TOOLS)


def action_binding_violations(cases, tools=None) -> list:
    """`[(case_id, tool, action, kind)]`；kind = `no_action_param`（工具无 action 维度）
    或 `not_in_enum`（枚举不含该值）—— 两者都是"断言永不满足"，都不静默跳过。

    **「声明的 action 必须真实存在于该工具的 action 枚举」的唯一实现点**：门禁
    （`build_coverage_report`，两个 CLI 共用）与 L0 静态不变式
    （`tests/unit_ci_workflows/test_eval_assertion_action_binding.py`）都调用本函数，
    禁止任何一方另写一套 —— 两套判据必然漂移，后果就是"单测绿 ≠ 门禁绿"。

    三处**必须**的覆盖面（issue #3701：旧实现的三处假绿盲区，实测全部放行）：
      ① 工具**没有** action 维度时声明 `action` 同样是悬空（`no_action_param`）——
         旧实现只遍历「有 action 维度的工具」，`must_fail: [{tool: order_create, action: create}]`
         （OR-026 被拒的写法，runner 里整条静默跳过）**整个不被检查**；
      ② `skip_reason` 非空的用例**照扫**（调用方传入全量用例，别先过
         `select_cases_for_persona`）—— 用例解 skip 时不得带着永不满足的声明上场。
         （**历史实例，非现状**：OR-006 曾声明 `order_query(action=detail)`，而 `detail` 并非
         该工具 action 枚举取值——真值为 `list / statistics / follow_status_stats`——靠
         `skip_reason` 藏住而长期未被发现；已由 #3702（合入 PR #3715，`eab62fad`）按真实语义
         改为 `action: list`，其 `action_dangling` 登记条目亦已销账删除。此处保留为
         「skip 会藏住非法声明」的说明性实例；引用前请以 `.github/cases/order.yml` 为准。）
      ③ 收 `repeat_until.action`（停条件悬空 → 用例空转到轮数耗尽）。
    """
    tools = registered_tools() if tools is None else set(tools)
    out = []
    for case in cases:
        cid = case.get("id") if isinstance(case, dict) else getattr(case, "id", "?")
        for tool, acts in case_action_bindings(case).items():
            if tool not in tools:
                continue                    # 未注册工具：另有工具级 `dangling_cases` 判据
            enum = action_enum(tool)
            if enum is None:
                continue                    # 工具无源码文件：工具存在性另判
            for a in sorted(acts):
                if a not in enum:
                    out.append((cid, tool, a,
                                "not_in_enum" if enum else "no_action_param"))
    return out


def load_baseline(path=None, persona: str = "", tools=None):
    """读并**校验**存量豁免清单（fail-closed：文件缺失/格式坏/条目不合规 → 抛 ValueError）。

    返回 `{"path", "meta", "entries", "by_tool", "entries_by_tool", "issues"}`；
    `entries` 只含该 persona 的条目（其它端的条目在此忽略，但仍会被格式校验）。
    """
    path = Path(path) if path else BASELINE_PATH
    if not path.exists():
        raise ValueError(
            f"存量豁免清单不存在: {path}\n"
            f"    ⇒ 门禁要么全绿（无存量缺口）要么无法豁免存量缺口，二者都必须显式 ——"
            f"若确实无存量缺口，创建一个只有 meta 的空清单文件"
        )
    try:
        # 用仓库自己的零依赖解析器（`yaml_light`，与 render_cases/truths 同一份实现）：
        # `case-coverage-gate` job 只做 setup-python，**没有** `pip install`
        # （pyyaml 只装在 `ci workflow helper unit tests` job）—— 这里 import yaml 会让门禁
        # 对每个 PR 常红（"覆盖体检无法执行：需要 pyyaml"），且与用例质量无关。
        from yaml_light import load_file as _load_yaml
        data = _load_yaml(path)
    except Exception as exc:
        raise ValueError(f"{path.name} YAML 解析失败: {exc}")
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} 顶层必须是映射（含 version/entries）")
    entries = data.get("entries")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise ValueError(f"{path.name} 的 entries 必须是列表")

    end_tools = set(tools) if tools is not None else None
    by_tool: dict = {}
    entries_by_tool: dict = {}
    issues = set()
    problems = []
    for i, raw in enumerate(entries):
        where = f"entries[{i}]"
        if not isinstance(raw, dict):
            problems.append(f"{where}: 必须是映射（tool/kind/issue/reason/added）")
            continue
        missing = [f for f in ENTRY_REQUIRED_FIELDS if not str(raw.get(f) or "").strip()]
        if missing:
            problems.append(f"{where}: 缺字段 {missing}（防白名单变垃圾场：一条不许留空）")
            continue
        tool, kind = str(raw["tool"]).strip(), str(raw["kind"]).strip()
        entry_persona = str(raw.get("persona") or "").strip().lower()
        issue, reason = str(raw["issue"]).strip(), str(raw["reason"]).strip()
        where = f"entries[{i}] {tool}[{kind}]"
        if kind not in GAP_KINDS:
            problems.append(f"{where}: kind 必须是 {GAP_KINDS} 之一")
            continue
        if not _ISSUE_RE.match(issue):
            problems.append(f"{where}: issue 必须是 '#<数字>'（真实存在的追踪 issue），实际 {issue!r}")
            continue
        if len(reason) < _MIN_REASON_LEN:
            problems.append(f"{where}: reason 至少 {_MIN_REASON_LEN} 字（说清为什么暂时豁免）")
            continue
        if entry_persona and entry_persona not in PERSONAS:
            problems.append(f"{where}: persona 必须是 {PERSONAS} 之一或留空（双端共用）")
            continue
        # 归属**别的端**的条目不由本次体检负责（工具真值/缺口由那端的体检校验）
        if entry_persona and persona and entry_persona != persona:
            continue
        # 只对归属本端的条目校验工具真值
        if end_tools is not None and tool not in end_tools:
            problems.append(f"{where}: {tool} 不是{persona or '该端'}工具（拼错/工具已删除 → 登记无效）")
            continue
        by_tool.setdefault(tool, set()).add(kind)
        entries_by_tool.setdefault(tool, {})[kind] = raw
        issues.add(issue)
    if problems:
        raise ValueError(
            f"{path.name} 有 {len(problems)} 条不合规条目：\n  - " + "\n  - ".join(problems)
        )
    own = [e for e in entries if isinstance(e, dict)
           and (not e.get("persona") or not persona
                or str(e["persona"]).strip().lower() == persona)]
    return {"path": path, "meta": {k: v for k, v in data.items() if k != "entries"},
            "entries": own, "by_tool": by_tool, "entries_by_tool": entries_by_tool,
            "issues": issues}


def _attach_baseline(rep: CoverageReport, baseline: dict) -> CoverageReport:
    """把存量豁免挂到报告上，并算出「陈旧登记」（销账后未删）。

    陈旧 = 登记了某工具某 kind，但该工具**当前不再是**那种缺口（用例已补 / kind 变了）。
    这类登记必须删，否则清单会越攒越多、丧失"工作清单"的可读性。
    """
    rep.baseline = baseline
    rep.baseline_missing = [
        (tool, kind)
        for tool, kinds in baseline.get("by_tool", {}).items()
        for kind in sorted(kinds)
        if rep.baseline_is_stale(tool, kind)
    ]
    return rep


PERSONA_LABELS = {
    "xiaobu": "C 端小布",
    "mibao": "B 端米宝",
}

_KIND_LABELS = {
    "uncovered": "零用例（阻塞）",
    "missing_positive": "缺正向用例（阻塞）",
    "action_dangling": "用例声明了工具不存在的 action（阻塞）",
    "thin": "仅 1 条用例（只报告）",
    "thin_positive": "仅 1 条正向用例（只报告）",
}


def render_baseline_worklist(rep: CoverageReport, persona_label: str = "") -> str:
    """把存量豁免清单当**工作清单**打印：工具 + 缺口 + 归属 issue + 理由 + 销账方式。

    设计意图（issue #3575）：清单必须**可逐条销账**——
    「补完用例 → 删条目」；条目与当前缺口不一致会被判陈旧登记（job 红），
    所以清单只可能变短，不会变成免死金牌。
    """
    path = rep.baseline.get("path")
    out = ["=" * 68,
           f"  存量豁免工作清单（burn-down baseline）— {persona_label or rep.persona}",
           "=" * 68,
           f"清单文件: {Path(path).name if path else BASELINE_PATH.name}"
           f"（补完用例即删除对应条目；清单应单调缩短）"]
    entries = rep.baseline.get("entries") or []
    if not entries:
        out.append("  （空 —— 该端无存量缺口豁免，门禁为纯判据）")
        return "\n".join(out)
    for e in entries:
        tool, kind = str(e["tool"]), str(e["kind"])
        ids = rep.cases.get(tool) or []
        status = "已登记豁免" if rep.is_baselined(tool, kind) else "⚠️ 陈旧登记（当前不是该缺口）"
        out.append(f"  ▸ {tool}  [{_KIND_LABELS.get(kind, kind)}]  {status}")
        out.append(f"      归属: {e['issue']}   登记日期: {e['added']}")
        out.append(f"      理由: {e['reason']}")
        out.append(f"      现状: {len(ids)} 条用例" + (f" {', '.join(ids)}" if ids else "（无）"))
    if rep.baseline_stale_blocking:
        out.append("")
        out.append("  ❌ 阻断型陈旧登记（销账后**必须**删除条目，否则阻塞）:")
        for tool, kind in rep.baseline_stale_blocking:
            out.append(f"     - {tool} [{kind}]")
    if rep.baseline_stale_reporting:
        out.append("")
        out.append("  ⚠️ 只报告型陈旧登记（工具已加厚 = 好消息；建议删除条目，不阻塞）:")
        for tool, kind in rep.baseline_stale_reporting:
            out.append(f"     - {tool} [{kind}]")
    out.append("")
    out.append("  销账方式：补用例（migao-dev-flow §14.5）→ 删本文件对应条目 → CI 保持绿。")
    return "\n".join(out)

# ── 能力标签（缺口报告的人读性）────────────────────────────────────────────────
# 只覆盖能力矩阵里需要"说人话"的工具；缺标签的工具有名字也够用。
XIAOBU_TOOL_LABELS = {
    "customer_order_query": "查本人订单",
    "customer_logistics_track": "查物流（仅本人已发货）",
    "customer_address_query": "查收货地址",
    "order_create": "下单创建",
    "product_search": "商品搜索",
    "product_detail": "商品详情",
    "curtain_calc": "窗帘算料报价",
    "aftersale_query": "售后工单查询",
    "aftersale_create": "售后工单创建",
    "knowledge_search": "知识问答（本店知识库）",
    "human_handoff": "转人工",
    "interact": "交互卡片（choice/form/confirm）",
    "validate_input": "写操作前置校验",
}

MIBAO_TOOL_LABELS = {
    "order_query": "订单查询",
    "order_manage": "订单状态/操作（改状态、发货等）",
    "order_create": "代客下单",
    "logistics_track": "物流跟踪",
    "product_search": "商品搜索",
    "product_detail": "商品详情",
    "product_manage": "商品 CRUD（建品/上下架）",
    "product_update": "商品级统一定价",
    "sku_update": "SKU 单独调价",
    "product_processing_item_manage": "商品加工项关联",
    "processing_item_manage": "加工项 CRUD",
    "processing_item_query": "加工项查询",
    "processing_order_generate": "生成加工单（批量）",
    "processing_order_query": "加工单查询",
    "processing_order_update": "加工单状态更新",
    "inventory_manage": "库存管理",
    "category_manage": "商品分类管理",
    "after_sales_manage": "售后工单处理",
    "customer_manage": "客户档案/标签/跟进",
    "employee_manage": "员工账号管理",
    "role_manage": "角色与权限管理",
    "settings_manage": "系统/AI 配置",
    "notification_manage": "站内通知/公告",
    "dashboard_stats": "经营看板",
    "finance_api": "财务（收支/流水/对账）",
    "session_manage": "客服会话/转人工",
    "knowledge_search": "知识问答（本店知识库）",
    "validate_input": "写操作前置校验",
    "interact": "交互卡片（choice/form/confirm）",
}


def toolset_for(persona: str) -> set:
    """该端可跑工具集（单一真值来源，与用例边界守卫共用）。"""
    if persona == "xiaobu":
        return set(lr.XIAOBU_TOOLS)
    if persona == "mibao":
        return lr.mibao_real_toolset()
    raise ValueError(f"未知 persona: {persona!r}（应为 {PERSONAS}）")


def tool_label(persona: str, tool: str) -> str:
    table = XIAOBU_TOOL_LABELS if persona == "xiaobu" else MIBAO_TOOL_LABELS
    return table.get(tool, "")


def case_title(c) -> str:
    if isinstance(c, dict):
        return str(c.get("title") or c.get("id") or "")
    return str(getattr(c, "title", "") or getattr(c, "id", ""))


@dataclass
class CoverageReport:
    """一端的能力覆盖体检结果（纯数据，渲染见各 CLI 脚本）。"""

    persona: str
    cases_total: int = 0                      # 用例库总条数
    cases_run: int = 0                        # 该端实际会跑的条数
    tools: set = field(default_factory=set)   # 该端工具集
    cases: dict = field(default_factory=dict)         # tool → [用例 ID]（含对抗/否定）
    positive: dict = field(default_factory=dict)      # tool → [正向用例 ID]
    adversarial: dict = field(default_factory=dict)   # tool → [对抗档用例 ID]
    uncovered: list = field(default_factory=list)     # 0 用例（结构性缺失 → 阻塞）
    missing_positive: dict = field(default_factory=dict)   # 缺正向用例（结构性缺失 → 阻塞）
    thin_tools: list = field(default_factory=list)    # 仅 1 条用例（厚度不足 → 只报告）
    thin_positive: list = field(default_factory=list)  # 仅 1 条且该条是正向（阈值：1 条）
    exempt: dict = field(default_factory=dict)        # tool → 显式豁免理由（非缺口）
    orphan_cases: list = field(default_factory=list)  # [(用例ID, [工具])] 挂到了错的端 → 阻塞
    dangling_cases: list = field(default_factory=list)  # [(用例ID, [工具])] 两端注册表都没有 → 阻塞
    baseline: dict = field(default_factory=dict)      # CoverageBaseline 或 {}（存量豁免，仅 --check）
    baseline_stale: list = field(default_factory=list)  # [(tool, kind)] 已销账但登记未删 → 阻塞
    baseline_missing: list = field(default_factory=list)  # 登记了但当前不是缺口 → 阻塞
    action_tools: dict = field(default_factory=dict)    # tool → 源码声明的 action 全集（真值）
    action_cases: dict = field(default_factory=dict)    # (tool, action) → [用例 ID]（被断言的 action）
    action_uncovered: list = field(default_factory=list)  # [(tool, action)] 有工具用例但该 action 零覆盖 → 只报告
    action_dangling: list = field(default_factory=list)   # [(tool, action)] 用例声明了工具不存在的 action → 阻塞
    # (tool, action) → [用例 ID]（**含 skip_reason 非空的用例**，见 #3701 盲区②：
    # skip 只免"参与覆盖统计"，不免"声明合法性"）。dangling 报错信息从这里取。
    action_dangling_cases: dict = field(default_factory=dict)

    @property
    def covered(self) -> int:
        return len(self.tools) - len(self.uncovered)

    def uncovered_actionable(self) -> list:
        """排除显式豁免后的真缺口。"""
        return [t for t in self.uncovered if t not in self.exempt]

    # ── 存量豁免（burn-down baseline，issue #3575 决策）───────────────────────
    def blocking_gaps(self) -> list:
        """当前**结构性缺失**清单：[(tool, kind)]，kind ∈ BLOCKING_KINDS。

        kind 的区分是有意的（豁免条目要按真实形态登记，登记错判陈旧）：
          · `uncovered`        = 零用例（连证据都没有）；
          · `missing_positive` = 有用例、但**一条正向都没有**（只有对抗档/否定式断言）；
          · `action_dangling`  = 用例声明了工具**不存在**的 action（#3667；断言永不满足）。
        """
        return [(t, "uncovered" if t in self.uncovered_actionable() else "missing_positive")
                for t in sorted(self.missing_positive)] \
            + sorted({(t, "action_dangling") for t, _a in self.action_dangling})

    def reporting_gaps(self) -> list:
        """**只报告**（不阻塞）的厚度不足清单：[(tool, kind)]，kind ∈ {"thin", "thin_positive"}。

        两种 kind 物理上等价（都只有 1 条用例），分开是为了让豁免条目能声明
        「这唯一一条是不是正向」—— 声明错了视为陈旧登记（见 `baseline_is_stale`）。
        """
        out = []
        for tool in self.thin_tools:
            out.append((tool, "thin_positive" if tool in self.thin_positive else "thin"))
        return out

    def all_gap_kinds(self) -> list:
        """全量缺口清单（含只报告的薄覆盖），既有语义锚点，也用于渲染工作清单。"""
        return sorted(set(list(self.blocking_gaps()) + self.reporting_gaps()))

    def is_baselined(self, tool: str, kind: str) -> bool:
        return kind in (self.baseline.get("by_tool", {}).get(tool, set()))

    def baseline_is_stale(self, tool: str, kind: str) -> bool:
        """已销账（当前不是缺口）但登记还在 → 陈旧登记，必须删（防白名单变垃圾场）。"""
        return kind in (self.baseline.get("by_tool", {}).get(tool, set())) \
            and (tool, kind) not in self.all_gap_kinds()

    def baseline_entry(self, tool: str, kind: str) -> dict:
        return (self.baseline.get("entries_by_tool", {}).get(tool, {}) or {}).get(kind) or {}

    @property
    def baseline_stale_blocking(self) -> list:
        """陈旧登记中**会阻断**的那些（kind ∈ BLOCKING_KINDS）→ 阻塞。

        理由：这类豁免在**抑制**一个真实的结构性缺口；销账后不删条目意味着清单在"
        假装某个缺口还在"，必须逼删（否则白名单腐烂，且后续会掩盖同工具的新缺口）。
        """
        return [(t, k) for t, k in self.baseline_missing if k in BLOCKING_KINDS]

    @property
    def baseline_stale_reporting(self) -> list:
        """陈旧登记中**只报告**的那些（kind ∈ REPORTING_KINDS）→ 仅警告。

        理由（#3575 排序实证）：这类条目从不抑制任何阻断 —— 工具变厚是好消息。
        若也判阻塞，会让"补了用例的那个包"（它不知道本清单存在）把 main 变红，
        即**用工作清单给别人下绊子**。故降级为警告：报告里提示删除，不拦合并。
        """
        return [(t, k) for t, k in self.baseline_missing if k in REPORTING_KINDS]

    def check_problems(self) -> list:
        """--check 的失败条件（只含**结构性缺失**，不含厚度不足）。"""
        problems = []
        if self.cases_run == 0:
            problems.append(f"{PERSONA_LABELS[self.persona]}用例集为空（评测假绿）")
        if self.orphan_cases:
            problems.append(
                f"{len(self.orphan_cases)} 条孤儿用例（期望工具 {PERSONA_LABELS[self.persona]}没有，"
                f"用例挂到了错的端）: " + ", ".join(cid for cid, _ in self.orphan_cases)
            )
        if self.dangling_cases:
            problems.append(
                f"{len(self.dangling_cases)} 条用例断言了**两端注册表都没有**的工具"
                f"（拼错/已删除，期望永不满足）: "
                + ", ".join(f"{cid}({','.join(t)})" for cid, t in self.dangling_cases)
            )
        if self.baseline_stale_blocking:
            problems.append(
                f"{len(self.baseline_stale_blocking)} 条**阻断型**存量豁免已销账但条目未删"
                f"（清单会腐烂 → 可能掩盖同工具的新缺口）: "
                + ", ".join(f"{t}[{k}]" for t, k in self.baseline_stale_blocking)
                + "\n     ⇒ 补完用例即删除该条目（清单只能变短）"
            )
        # 悬空 action 单独报（比 `new_gaps` 的通用文案更具体），但仍**尊重存量豁免**：
        # 否则登记了也挡不住它，门禁会在 main 上常红（与 `new_gaps` 的 is_baselined 口径一致）。
        unresolved_dangling = [(t, a) for t, a in self.action_dangling
                               if not self.is_baselined(t, "action_dangling")]
        if unresolved_dangling:
            problems.append(
                f"{len(unresolved_dangling)} 处用例声明了工具**不存在**的 action"
                f"（断言永不满足 = 假红/假绿，同 `dangling_cases` 家族）: "
                + ", ".join(f"{t}(action={a})[{','.join(self.action_dangling_cases.get((t, a)) or [])}]"
                            for t, a in unresolved_dangling)
                + "\n     ⇒ 核对工具 schema 的 action 枚举后改用例声明"
            )
        new_gaps = [(t, k) for t, k in self.blocking_gaps() if not self.is_baselined(t, k)]
        if new_gaps:
            problems.append(
                f"{len(new_gaps)} 处**新出现**的结构性覆盖缺口（未登记存量豁免）: "
                + ", ".join(f"{t}[{k}]" for t, k in new_gaps)
                + f"\n     ⇒ 补用例（migao-dev-flow §14.5）；确有客观原因才登记进 "
                  f"{BASELINE_PATH.relative_to(REPO_ROOT)}（每条必须带 ≥4 字的 issue 号与理由）"
            )
        return problems


def build_coverage_report(cases, persona: str, tools=None, exempt=None) -> CoverageReport:
    """计算一端的覆盖矩阵与薄覆盖清单。

    cases  : `.github/cases` 加载出的用例 dict 列表（全库，本函数自己做端归属过滤）
    persona: "xiaobu" / "mibao"
    tools  : 该端工具集（缺省取真值；测试可注入小集合验证判据）
    exempt : 显式豁免（tool → 理由），豁免项不计入"零用例"缺口
             （**只用于客观无法跑的能力**，且理由写进报告；豁免会掩盖回归，故应尽量为空）
    """
    persona = (persona or "").strip().lower()
    if persona not in PERSONAS:
        raise ValueError(f"未知 persona: {persona!r}（应为 {PERSONAS}）")
    tools = set(tools) if tools is not None else toolset_for(persona)
    exempt = dict(exempt or {})

    selected = lr.select_cases_for_persona(cases, persona)
    known_anywhere = tools | set(lr.XIAOBU_TOOLS) | lr.mibao_real_toolset() | set(lr.PSEUDO_TOOLS)

    rep = CoverageReport(persona=persona, cases_total=len(list(cases)),
                         cases_run=len(selected), tools=tools, exempt=exempt)
    for case in selected:
        cid = case.get("id") if isinstance(case, dict) else getattr(case, "id", "?")
        tier = str(case.get("tier") if isinstance(case, dict) else getattr(case, "tier", ""))
        is_adv = tier.strip().lower() == "adversarial"
        positive = lr.is_positive_case(case)

        outside_end, dangling = set(), set()
        for exp in (case.get("expectations") if isinstance(case, dict)
                    else getattr(case, "expectations", None)) or []:
            branches = lr.expectation_branches(exp)
            if not branches:
                continue
            if not (set(branches) & tools):
                outside_end |= set(branches)
            if not (set(branches) & known_anywhere):
                dangling |= set(branches)
        if dangling:
            rep.dangling_cases.append((cid, sorted(dangling)))
        elif outside_end:
            # 该用例的**每一个**工具期望都落在此端能力之外 → 用例挂错了端（阻塞）
            rep.orphan_cases.append((cid, sorted(outside_end)))

        for tool in lr.case_expectation_tools(case):
            if tool in tools:
                rep.cases.setdefault(tool, []).append(cid)
                if is_adv:
                    rep.adversarial.setdefault(tool, []).append(cid)
        if positive:
            for tool in lr.case_expectation_tools(case):
                if tool in tools:
                    rep.positive.setdefault(tool, []).append(cid)

        for tool, acts in case_declared_actions(case).items():
            if tool not in tools:
                continue
            for a in sorted(acts):
                rep.action_cases.setdefault((tool, a), []).append(cid)

    for tool in sorted(tools):
        ids = rep.cases.get(tool) or []
        if not ids:
            rep.uncovered.append(tool)        # 0 用例 → 结构性缺失（阻塞）
        elif len(ids) == 1:
            rep.thin_tools.append(tool)       # 仅 1 条 → 厚度不足（只报告）
            if rep.positive.get(tool):
                rep.thin_positive.append(tool)   # 该唯一一条是正向（供豁免条目声明 kind）
        # 缺正向用例（结构性缺失 → 阻塞）：**被断言过**却没有一条证明"该工具能力可用"的用例
        # —— 包括两种形态：① 只有对抗档（拒绝/越权路径）② 只有否定式期望。
        # 零用例的工具也会落在这里，但 `blocking_gaps()` 用 uncovered 归类（避免同一件事报两遍）。
        if not rep.positive.get(tool) and tool not in exempt:
            rep.missing_positive[tool] = list(ids)

    # ── action 级（#3667）：真值取源码枚举；零用例工具的 action 由工具级 uncovered 报，不重复 ──
    # 单 action 工具（枚举只有 1 项，如 `customer_order_query` 的 `list`）**不报未覆盖**：
    # 调该工具 == 调那个 action，工具级已覆盖即 action 级已覆盖 —— 报出来是**假缺口**
    # （会把 100% 覆盖的工具显示成"未覆盖 1/1"）。悬空检测对它们照旧生效（声明错 action 仍是错）。
    # ── 悬空 action（#3667 引入 / #3701 补 3 处盲区）：判据**唯一实现**在
    # `action_binding_violations`（与 L0 不变式同一函数）。
    # 与上方覆盖统计**有意分开**：
    #   · 扫**全库**用例（含 `skip_reason` 非空者）—— skip 免的是"参与覆盖统计"，
    #     不免"声明合法性"。（**历史实例，非现状**：OR-006 曾声明
    #     `order_query(action=detail)`——`detail` 不在该工具 action 枚举真值
    #     `list / statistics / follow_status_stats` 内——靠 skip 藏住而长期未被发现；
    #     已由 #3702（合入 PR #3715，`eab62fad`）改为 `action: list`，条目已销账删除。）
    #   · 覆盖「工具没有 action 维度」（旧实现只遍历 `action_tools` = 放行）；
    #   · 收 `repeat_until.action`。
    rep.action_tools = action_catalog(tools)
    declared_by_tool: dict = {}
    for (tool, action) in rep.action_cases:
        declared_by_tool.setdefault(tool, set()).add(action)
    for tool, acts in rep.action_tools.items():
        declared = declared_by_tool.get(tool, set())
        if rep.cases.get(tool) and len(acts) > 1:
            rep.action_uncovered += [(tool, a) for a in sorted(acts - declared)]
    for cid, tool, action, _kind in action_binding_violations(cases, tools):
        rep.action_dangling_cases.setdefault((tool, action), []).append(cid)
    rep.action_dangling = sorted(rep.action_dangling_cases)
    return rep


# ── action 级报告渲染（两个 CLI 共用同一实现，防口径漂移）───────────────────────

def render_action_gaps(rep: CoverageReport, persona_label: str = "", md: bool = False) -> str:
    """action 级覆盖报告（§⑥）：未覆盖 action（只报告）+ 悬空 action（--check 拦截）。

    为什么单列：工具级矩阵把它们显示成"✅ 已覆盖"（`processing_item_manage` 9 个 action
    只有 3 个被断言），本段就是它下面那一层的**补用例任务书**（issue #3667）。
    未覆盖 action 多到不适合逐条阻塞（仓库实测 41 处），故只报告；悬空 action 是配置错误（阻塞）。
    """
    if not rep.action_tools and not rep.action_dangling:
        return ""
    total_actions = sum(len(a) for a in rep.action_tools.values())
    multi = len([t for t, a in rep.action_tools.items() if len(a) > 1])
    out = []

    def _actual(tool: str) -> str:
        """该工具真实声明的 action；空 = **没有 action 维度**（声明任何 action 都悬空）。"""
        acts = sorted(rep.action_tools.get(tool) or [])
        return ", ".join(acts) if acts else "（该工具无 action 参数）"

    def _ids(pair) -> str:
        return ", ".join(rep.action_dangling_cases.get(pair) or [])

    def _exempt_mark(tool: str) -> str:
        return "（已登记存量豁免）" if rep.is_baselined(tool, "action_dangling") else ""

    if md:
        out += ["", "## ⑦ action 级覆盖（工具级之下的一层，issue #3667）", "",
                f"- 有 action 维度的工具：**{len(rep.action_tools)} 个**（多 action {multi} 个），"
                f"action 合计 **{total_actions} 个**",
                f"- 未被任何用例断言的 action（**只报告不阻塞**）：**{len(rep.action_uncovered)} 个**",
                f"- 用例声明了工具**不存在**的 action（`--check` 拦截）：**{len(rep.action_dangling)} 个**"]
        if rep.action_dangling:
            out += ["", "| 用例声明 | 工具 | 不存在的 action | 工具实际 action |", "|---|---|---|---|"]
            for tool, action in rep.action_dangling:
                out.append(f"| {_ids((tool, action))}{_exempt_mark(tool)} | `{tool}` | "
                           f"`{action}` | {_actual(tool)} |")
        if rep.action_uncovered:
            out += ["", "| 工具 | 能力 | 未覆盖 action | 已覆盖 action |", "|---|---|---|---|"]
            for tool in sorted({t for t, _a in rep.action_uncovered}):
                miss = [a for t, a in rep.action_uncovered if t == tool]
                done = sorted({a for (t, a) in rep.action_cases if t == tool})
                out.append(f"| `{tool}` | {tool_label(rep.persona, tool)} | "
                           f"{', '.join(miss)} | {', '.join(done) or '（无）'} |")
        return "\n".join(out)

    multi = len([t for t, a in rep.action_tools.items() if len(a) > 1])
    out += ["", f"── ⑥ action 级覆盖（工具级之下的一层，issue #3667；{persona_label or rep.persona}）──",
            f"  有 action 维度的工具 {len(rep.action_tools)} 个（其中**多** action {multi} 个"
            f"，未覆盖只对它们有意义）/ action 合计 {total_actions} 个"
            f"；未覆盖 {len(rep.action_uncovered)} 个（只报告不阻塞）"]
    if rep.action_dangling:
        out.append("")
        out.append("  ❌ 用例声明了工具**不存在**的 action（`--check` 拦截；断言永不满足 = 假红/假绿）:")
        for tool, action in rep.action_dangling:
            out.append(f"     {tool}(action={action})  ← {_ids((tool, action))}{_exempt_mark(tool)}"
                       f"；该工具实际 action: {_actual(tool)}")
    if rep.action_uncovered:
        out.append("")
        out.append("  ⚠️ 未被任何用例断言的 action（只报告不阻塞 —— 它本质是**厚度**指标，")
        out.append("     与「仅 1 条用例」同级；硬阈值会制造返工式门禁，故只进工作清单）:")
        for tool in sorted({t for t, _a in rep.action_uncovered}):
            miss = [a for t, a in rep.action_uncovered if t == tool]
            done = sorted({a for (t, a) in rep.action_cases if t == tool})
            out.append(f"     {tool:32} {tool_label(rep.persona, tool):22} "
                       f"未覆盖 {len(miss)}/{len(miss) + len(done)}: {', '.join(miss)}")
    return "\n".join(out)

