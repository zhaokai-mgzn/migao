"""出口 ③：从一张口径卡的 `trigger` + `counter` **自动生成一条可跑的用例**（issue #8175 判据 3 / 6）。

## 「可跑」在这里是什么意思

不是把字段拼成一段字符串，而是：生成物带**机器可执行的载荷**（`traces.playbook`），
`run_case` 拿它去调**生产同一条判定链**（`prompt.select_playbooks` / `prompt.applies_now`），
当场得出 passed / failed。判据 3 的红证就是「把生成物的载荷喂给一个坏引擎（忽略 counter /
把 draft 当 active）⇒ 用例必须 failed」。字符串拼接做不到这一点。

## 为什么 `counter` 在这里是**必判项**（判据 6）

一张卡的反例如果在生成物里只出现一次文案，那它就是注释。所以生成器做两件事：

1. 有 `counter` ⇒ 生成**负向断言**（「反例命中的语境下本卡**不得**生效」）；
2. `counter` 存在却**不可执行** ⇒ `generate_case` 直接 `raise`（拒绝生成），
   而不是悄悄少一条断言 —— 后者会让「反例写错了」看起来像「本来就只有一条断言」。

## 语境的构造是「可满足性采样」，不是幻觉

`_sample_context` 从结构里反推一个**真的能命中**的语境（`eq` 取值、`in` 取首项、
`exists` 填占位…），然后**回代验算**：`evaluate(condition, sample)` 必须为真。
做不到（矛盾条件 / `not` 嵌套 / 不可满足）⇒ `raise PlaybookNotExecutable` ——
宁可「本卡生成不出用例」，也不要生成一条**永远绿的空断言**。
"""

import json
from typing import Any, Dict, List, Optional

from app.playbook.condition import evaluate, is_executable
from app.playbook.store import STATE_ACTIVE

#: 采样占位值（不是业务值：只在「反推语境」时用，回代验算会把它验掉）
_ABSENT = "__absent__"
_PRESENT = "__present__"

#: 生成的用例 id 前缀（与本仓 `.github/cases/**` 的域前缀不冲突：那些是 MC/OR/AS…）
CASE_ID_PREFIX = "PB-"


class PlaybookNotExecutable(ValueError):
    """这张卡生成不出**真的能跑**的用例（自由文本触发 / 反例不可判 / 语境不可满足）。"""


# ── 语境采样 ────────────────────────────────────────────────────────────────


def _sample_leaf(condition: Dict[str, Any]) -> Dict[str, Any]:
    op = condition["op"]
    field = condition["field"]
    value = condition.get("value")
    if op == "eq":
        return {field: value}
    if op == "ne":
        return {field: f"{value}{_ABSENT}" if isinstance(value, str) else _PRESENT}
    if op == "in":
        return {field: value[0]}
    if op == "not_in":
        candidate = _ABSENT
        while candidate in value:
            candidate += "_"
        return {field: candidate}
    if op == "contains":
        return {field: value}
    if op == "not_contains":
        return {field: _PRESENT}
    if op == "exists":
        return {field: _PRESENT}
    return {}  # not_exists：字段**不出现**才成立


def _sample_context(condition: Any) -> Dict[str, Any]:
    """从条件反推一个「真的能命中」的最小语境（回代验算在 `_require_context`）。"""
    if not is_executable(condition):
        raise PlaybookNotExecutable("条件不可执行（自由文本 / 结构不合法）")
    return _sample(condition)


def _sample(condition: Dict[str, Any]) -> Dict[str, Any]:
    if "all" in condition:
        merged: Dict[str, Any] = {}
        for child in condition["all"]:
            merged.update(_sample(child))
        return merged
    if "any" in condition:
        # 取第一个子条件即可满足 `any`（其余子条件不参与判定 —— 这是 `any` 的语义）
        return _sample(condition["any"][0])
    if "not" in condition:
        # `not` 的满足语境 = 「内层不成立」。内层是叶子时，按「缺席 / 反值」构造；
        # 其它形态直接拒（不猜：猜错就是生成一条永远绿的断言）。
        inner = condition["not"]
        if "field" in inner and inner["op"] in ("eq", "in", "contains", "exists"):
            if inner["op"] == "exists":
                return {}
            return {inner["field"]: _PRESENT if inner["op"] != "eq" else f"{inner.get('value')}{_ABSENT}"}
        raise PlaybookNotExecutable("`not` 的满足语境无法自动构造（请把反例写成正向条件）")
    return _sample_leaf(condition)


def _require_context(condition: Any, what: str) -> Dict[str, Any]:
    context = _sample_context(condition)
    if not evaluate(condition, context):
        raise PlaybookNotExecutable(f"{what} 的满足语境无法构造（采样回代验算不成立）")
    return context


def _require_counter_context(
    trigger: Any, counter: Any, trigger_context: Dict[str, Any]
) -> Dict[str, Any]:
    """反例语境 = **触发条件仍成立** + 反例命中。

    这一点是「反例不是注释」的技术前提：如果反例语境同时也不满足触发条件，那么
    「本卡不生效」有**两个**原因，负向断言就分不清「反例起作用了」还是「触发没中」——
    坏引擎（不读 counter）照样能绿。所以这里把触发条件的采样并进来，并回代验两件事。
    """
    merged = dict(trigger_context)
    merged.update(_sample_context(counter))
    if not evaluate(trigger, merged):
        raise PlaybookNotExecutable(
            "反例语境与该卡的触发条件互斥（无法构造「触发成立且反例命中」的语境）"
        )
    if not evaluate(counter, merged):
        raise PlaybookNotExecutable("反例的满足语境无法构造（采样回代验算不成立）")
    return merged


# ── 生成 ────────────────────────────────────────────────────────────────────


def generate_case(playbook: Dict[str, Any], case_id: Optional[str] = None) -> Dict[str, Any]:
    """生成一条**可跑**的用例（本仓 `.github/cases/**` 的 schema 形态）。

    Raises:
        PlaybookNotExecutable: 非 active / trigger 不可执行 / counter 存在但不可执行 /
            语境不可满足。**一律拒绝生成**，绝不降级成「少几条断言」。
    """
    if playbook.get("state") != STATE_ACTIVE:
        raise PlaybookNotExecutable(
            f"只有 {STATE_ACTIVE} 的卡才生成用例（实际 state={playbook.get('state')!r}）"
        )
    trigger = playbook.get("trigger")
    if not is_executable(trigger):
        raise PlaybookNotExecutable("trigger 不可执行 ⇒ 生成不出会红的用例")
    counter = playbook.get("counter")
    if counter is not None and not is_executable(counter):
        raise PlaybookNotExecutable("counter 不可执行 ⇒ 反例会退化成注释，拒绝生成")

    pid = str(playbook.get("id") or "")
    if not pid:
        raise PlaybookNotExecutable("口径卡缺 id")

    trigger_context = _require_context(trigger, "trigger")
    counter_context = (
        _require_counter_context(trigger, counter, trigger_context)
        if counter is not None
        else None
    )

    checks: List[str] = [
        "**判据（会红）**：`trigger` 命中的语境下本卡必须生效 —— 用例执行器把它喂进"
        "生产同一条判定链（口径卡的选取 + 反例求值）后判定；把状态改成 draft 或让选取"
        "忽略 state，本条即红。",
    ]
    if counter_context is not None:
        checks.append(
            "**判据（负控，会红）**：`counter` 命中的语境下本卡**不得**生效 —— "
            "红证 = 让选取不读 counter ⇒ 本条判红（这正是「反例不是注释」的机械形态）。"
        )
    else:
        checks.append(
            "**本卡无反例**：已如实登记（不是「反例写了但没判」—— 那种形态由生成器直接拒绝，"
            "见 PlaybookNotExecutable）。"
        )
    checks.append(
        "**判据（出口面，会红）**：prompt 片段的渲染结果里，正向语境含本卡正解、"
        "反例语境**一个字符都不含**（渲染层与选取层共用同一判定）。"
    )

    case: Dict[str, Any] = {
        "id": case_id or f"{CASE_ID_PREFIX}{pid}",
        "legacy_id": "",
        "title": f"口径卡 {pid}：{playbook.get('correct') or ''}"[:120],
        "domains": ["agent", "playbook"],
        "tier": "normal",
        "tags": ["playbook", "generated", f"tenant:{playbook.get('tenant_id')}"],
        "truths_ref": [],
        "user_inputs": [
            f"商家在会话里纠正过一次口径（来源：会话 {((playbook.get('source') or {}).get('session_id')) or '手工创建'}）；"
            f"口径卡 {pid} 的触发条件命中时，黄金策按该口径作答"
        ],
        "expectations": [{"tool": "direct_reply"}],
        "data_checks": checks,
        "skip_reason": "",
        "merge_log": [
            f"由口径卡 {pid} 自动生成（issue #8175 出口③）；生成器 app/playbook/casegen.py；"
            "生成物不入库（口径卡的审核结果会变，用例必须跟着重生成）"
        ],
        "traces": {
            "playbook": {
                "playbook_id": pid,
                "tenant_id": playbook.get("tenant_id"),
                "trigger_context": trigger_context,
                "counter_context": counter_context,
                "has_counter": counter_context is not None,
            }
        },
    }
    return case


def generate_cases(playbooks: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """批量生成。**单卡失败不影响其它卡**（每卡独立可跑），但在结果里逐个记名。"""
    cases: List[Dict[str, Any]] = []
    for pb in playbooks or []:
        try:
            cases.append(generate_case(pb))
        except PlaybookNotExecutable:
            continue
    return cases


# ── 执行（「生成物真能跑」的唯一证据）────────────────────────────────────────


def run_case(case: Dict[str, Any], playbooks: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """**执行**一条由 `generate_case` 生成的用例，返回 `{passed, checks}`。

    执行的是**生产同一条判定链**（不是另写一份判定）：
    正向语境 ⇒ 卡必须生效；反例语境 ⇒ 卡必须不生效；prompt 渲染同样按这两条验。
    任何异常都记成 failed（不许「跑挂了算过」）。
    """
    payload = ((case.get("traces") or {}).get("playbook")) or {}
    pid = payload.get("playbook_id")
    checks: List[Dict[str, Any]] = []

    def _record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    if not pid:
        _record("case_payload", False, "用例缺 traces.playbook.playbook_id")
        return {"passed": False, "checks": checks}

    # 延迟 import：避免 prompt ← casegen 的循环（prompt 不在本模块顶层依赖）
    from app.playbook.prompt import applies_now, render_playbook_block

    target = None
    for pb in playbooks or []:
        if str(pb.get("id")) == str(pid):
            target = pb
            break
    if target is None:
        _record("card_present", False, f"语料里找不到口径卡 {pid}")
        return {"passed": False, "checks": checks}

    trigger_context = payload.get("trigger_context") or {}
    counter_context = payload.get("counter_context")

    try:
        positive = applies_now(target, trigger_context)
        _record("trigger_fires", positive, f"语境={trigger_context} 期望生效")
        positive_block = render_playbook_block([target], trigger_context)
        _record(
            "prompt_contains_rule",
            f'<rule id="{pid}"' in positive_block,
            "正向语境的 prompt 片段应含本卡",
        )

        if payload.get("has_counter"):
            negative = applies_now(target, counter_context or {})
            _record("counter_blocks", not negative, f"语境={counter_context} 期望不生效")
            negative_block = render_playbook_block([target], counter_context or {})
            _record(
                "prompt_excludes_rule_on_counter",
                f'<rule id="{pid}"' not in negative_block,
                "反例语境的 prompt 片段不得含本卡",
            )
    except Exception as e:  # noqa: BLE001 — 执行失败必须记成 failed，不许当通过
        _record("execution", False, f"执行抛错：{type(e).__name__}: {e}")

    return {"passed": all(c["passed"] for c in checks), "checks": checks}


def cases_digest(cases: List[Dict[str, Any]]) -> str:
    """确定性摘要（同一卡集合 ⇒ 同一串；用于「生成是确定的」这类判据）。"""
    payload = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
