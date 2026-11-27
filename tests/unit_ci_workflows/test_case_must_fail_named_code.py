# case_ids: HR-009, HR-010
"""`must_fail` 必须写清**拒绝理由**（issue #9220 —— HR-009 假绿的类级根治）。

## 病灶（逐字，2026-11-27 两个独立包同日各自报告）

`HR-009` 的输入与 `HR-010` 同为「帮我开个客服账号」（**不带岗位码**）⇒ 模型自选 `role: agent`。
同一个 `employee_manage(action=create)` 因此有**两种**拒绝、码不同、语义相反：

| 拒绝层 | 触发条件 | 码 | 服务端是否被调用 |
|---|---|---|---|
| 工具层 `app/tools/base.py::permission_denied` | 缺 `employee:create` | `PERMISSION_DENIED` | 否（零 HTTP） |
| 服务层 `UserService.assertAssignableRoleAndPermissions` | `role` ∈ `FORBIDDEN_USER_ROLES` | `VALIDATION_ERROR`（422） | 是 |

`HR-009` 是 `must_fail` 形态 ⇒ 只要 create **没成功**就判绿。于是「缺权限被拒」这条语义
**可能整条没被执行**（身份回落通配 `*`、或输入让模型走到保留角色那条路）却仍然通过 ——
**用例分不清两种拒绝**。这不是「断言写弱了」，是**断言没有理由维度**。

## 判据（六条，逐条可单独变红）

* **R1 未具名即红**：每条 `must_fail` 都必须有 `error_code`，或登记在**只许缩短**的台账
  `case_must_fail_named_code_ledger.json` 里；台账行必须**仍活着**（已具名/已不存在 ⇒ 删行，否则红）。
* **R2 受限身份族不得进台账**：用例带 `debug_permissions` ⇒ 它的 `must_fail` 必须具名
  （HR-009 就是这一格：两种拒绝同形时，只有具名码能证明测的是「缺权限」）。
* **R3 早退路径必须绕开**：`must_fail[employee_manage(create)]` 的 `user_inputs` 必须**逐字点名**
  一个真实可分配岗位码（∈ `roles` 种子 ∧ ∉ `FORBIDDEN_USER_ROLES`）—— 否则模型会按「客服」
  自选 `agent`（保留角色）⇒ 走向 `VALIDATION_ERROR` 的早退路径，本用例要测的东西不执行。
* **R4 runner 的 `error_code` 语义**（`tests/agent_eval/local_runner.py::check_must_fail`）：
  码不符 ⇒ 具名违规；**没带码/对不齐 ⇒ fail-closed 违规**；成功 ⇒ 仍违规；
  **从未调用 ⇒ 仍通过**（镜像语义不变）；`args`+`error_code` ⇒ 配置错误（不静默只核一半）。
* **R5 具名码 ⇄ 源码单一来源**：HR-009 的 `PERMISSION_DENIED` 必须逐字等于
  `backend/ai-agent-service/app/tools/base.py::PERMISSION_DENIED_CODE`，且**不得**写成
  `VALIDATION_ERROR`（那正是要排除的另一种拒绝）；全库声明过的码必须是源码里真实存在的字面量。
* **R6 台账只许缩短**：`baseline` 冻结为 3、`len(entries) <= baseline`、每行必须有
  `why_baseline` + `unblock`（「为什么不具名」与「怎么才能具名」都写清，不留无出口的债）。

## 红证（本单实测，逐条见 `TestRedProof` 的 docstring）

* 删掉 HR-009 的 `error_code` ⇒ R1/R2 **具名红**（报 `HR-009: must_fail[employee_manage(create)] …`）；
* 把 HR-009 输入里的 `customer_service` 删掉 ⇒ R3 具名红；
* 把 HR-009 的码改成 `VALIDATION_ERROR` ⇒ R5 红（它等于把要排除的那条拒绝写成期望）；
* R4 的六格由构造轨迹直接注入（码不符 / 无码 / 成功 / 未调用 / args+码 / 未知键）。

## 边界（照实登记，§19.1）

* 「哪些输入会走**可预期早退路径**」**不可通用判定**（需要人工判），故只对仓内**已知的唯一实例**
  （员工岗位保留角色）落规则 R3；发现新的早退路径时必须在此登记，否则它不会被 R1/R2 之外的东西挡住。
* R2 的判据是「用例带 `debug_permissions`」—— 这是「受限身份」的**机制标记**，不是语义标记；
  将来换身份机制（`auth.py` 改造）时本判据要跟着换（否则会静默失去覆盖面）。
"""

import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
BASE_PY = REPO_ROOT / "backend/ai-agent-service/app/tools/base.py"
BUSINESS_EXCEPTION_JAVA = (
    REPO_ROOT / "backend/admin-api/src/main/java/com/migao/admin/exception/BusinessException.java")
LEDGER = Path(__file__).with_name("case_must_fail_named_code_ledger.json")

sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

from render_cases import load_case_dicts  # noqa: E402

# 复用 HR-014 判据的**真值解析**（岗位种子 ⇄ 保留集），不另写第二份口径。
from unit_ci_workflows.test_case_hr010_pp002_truth import (  # noqa: E402
    _forbidden_user_roles,
    _seeded_role_codes,
)


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身，且一旦被调用即抛错）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()


# ══════════════════════════════════════════════════════════════════════════════
# 判据本体（纯函数 —— 红证驱动**同一份**本体）
# ══════════════════════════════════════════════════════════════════════════════

def _cases():
    return load_case_dicts(str(CASES_DIR))


def _specs(case):
    """`must_fail` 的条目（裸工具名归一成 `{tool: …}`，与 runner 同口径）。"""
    return [{"tool": mf} if isinstance(mf, str) else (mf or {})
            for mf in (case.get("must_fail") or [])]


def _keys(case):
    """台账键：`(case_id, tool, action)` —— 与 `case_must_fail_named_code_ledger.json` 逐字同形。"""
    return [(str(case.get("id")), str(sp.get("tool") or ""), str(sp.get("action") or ""))
            for sp in _specs(case)]


def unnamed_must_fail(cases):
    """全库**没有具名拒绝理由**的 `must_fail` 条目（排序后返回，供台账逐行比对）。"""
    return sorted(
        key for case in cases for key, spec in zip(_keys(case), _specs(case))
        if not str(spec.get("error_code") or "").strip()
    )


def ledger_keys():
    data = json.loads(LEDGER.read_text(encoding="utf-8"))
    return {(str(e["case"]), str(e["tool"]), str(e.get("action") or "")) for e in data["entries"]}


def unnamed_violations(cases, registered):
    """R1：未具名且**未登记** ⇒ 红；台账行**已不成立** ⇒ 红（只许缩短）。"""
    live = set(unnamed_must_fail(cases))
    problems = []
    for cid, tool, action in sorted(live - registered):
        problems.append(
            f"{cid}: must_fail[{tool}" + (f"({action})" if action else "") + "] 只写「失败即可」"
            " —— 拒绝理由不可区分（缺权限 PERMISSION_DENIED / 保留角色 VALIDATION_ERROR 同形）；"
            "请补 `error_code: <具名码>`（runner = check_must_fail），或按 §19.1 登记台账并写清出口")
    for cid, tool, action in sorted(registered - live):
        problems.append(
            f"台账只许缩短：{cid}: must_fail[{tool}" + (f"({action})" if action else "") + "]"
            " 已具名或已不存在 —— 请删除该行（不改行、不删条目的台账会腐烂成假豁免）")
    return problems


def restricted_identity_violations(cases, registered):
    """R2：带 `debug_permissions`（受限身份）的用例，其 `must_fail` 必须具名，且不得进台账。"""
    problems = []
    for case in cases:
        if not str(case.get("debug_permissions") or "").strip():
            continue
        cid = str(case.get("id"))
        for key, spec in zip(_keys(case), _specs(case)):
            if str(spec.get("error_code") or "").strip():
                continue
            problems.append(
                f"{cid}: 以受限身份跑（debug_permissions={case.get('debug_permissions')!r}）的 "
                f"must_fail[{spec.get('tool')}] 没有具名拒绝理由 —— 这条用例的全部意义是让"
                "「权限拒绝路径」在评测里可达，只写「失败即可」时它可能一次都没被执行（HR-009 假绿）")
        if any(k[0] == cid for k in registered):
            problems.append(
                f"{cid}: 受限身份用例**不得**进「只许缩短」台账（两类拒绝同形，具名是唯一可分证据）")
    return problems


def early_exit_input_violations(cases, assignable_codes):
    """R3：`must_fail[employee_manage(create)]` 的输入必须点名**可分配**岗位码（绕开保留角色早退）。"""
    problems = []
    for case in cases:
        cid = str(case.get("id"))
        for spec in _specs(case):
            if str(spec.get("tool") or "") != "employee_manage":
                continue
            if str(spec.get("action") or "") != "create":
                continue
            text = " ".join(str(x) for x in (case.get("user_inputs") or []))
            if not any(code in text for code in assignable_codes):
                problems.append(
                    f"{cid}: must_fail[employee_manage(create)] 的 user_inputs 没有逐字点名可分配岗位码"
                    f"（{sorted(assignable_codes)}）⇒ 模型会按「客服」自选 `agent`（系统保留角色）⇒"
                    " 早退到 VALIDATION_ERROR，本条要测的「缺权限被拒」整条不执行")
    return problems


def permission_denied_code():
    """真值：`base.py::PERMISSION_DENIED_CODE`（工具层权限拒绝的**单一来源**，现取解析）。"""
    text = BASE_PY.read_text(encoding="utf-8")
    marker = 'PERMISSION_DENIED_CODE = "'
    return text.split(marker, 1)[1].split('"', 1)[0]


def unknown_declared_codes(cases):
    """R5：全库声明过的 `error_code` 必须是源码里真实存在的字面量（拼错 = 恒红/假判）。"""
    sources = BASE_PY.read_text(encoding="utf-8") + BUSINESS_EXCEPTION_JAVA.read_text(encoding="utf-8")
    problems = []
    for case in cases:
        for spec in _specs(case):
            code = str(spec.get("error_code") or "").strip()
            if code and code not in sources:
                problems.append(
                    f"{case.get('id')}: must_fail[{spec.get('tool')}] 声明的 `error_code: {code}` "
                    "在权限拒绝的源码单一来源里不存在（拼错 ⇒ 该断言恒不满足）")
    return problems


# ══════════════════════════════════════════════════════════════════════════════
# 常驻判据（真实仓库）
# ══════════════════════════════════════════════════════════════════════════════

class TestMustFailIsNamed:
    def test_every_must_fail_is_named_or_in_the_ledger(self):
        """R1：未具名未登记即红；台账行必须仍活着。"""
        problems = unnamed_violations(_cases(), ledger_keys())
        assert problems == [], "\n".join(problems)

    def test_restricted_identity_cases_never_sit_in_the_ledger(self):
        """R2：受限身份用例的 must_fail 必须具名（HR-009 假绿的那一格）。"""
        problems = restricted_identity_violations(_cases(), ledger_keys())
        assert problems == [], "\n".join(problems)

    def test_hr009_is_named_and_its_pair_still_exists(self):
        """实例判据：HR-009 具名 `PERMISSION_DENIED`，且 HR-010（正向对照）仍在。"""
        cases = {str(c.get("id")): c for c in _cases()}
        assert "HR-009" in cases and "HR-010" in cases, "权限族的两条（拒绝半 / 允许半）缺一即红"
        specs = _specs(cases["HR-009"])
        assert [s.get("error_code") for s in specs] == ["PERMISSION_DENIED"]
        assert [s.get("action") for s in specs] == ["create"]
        assert str(cases["HR-009"].get("debug_permissions")) == "employee:list"

    def test_create_must_fail_inputs_name_an_assignable_role(self):
        """R3：`must_fail[employee_manage(create)]` 的输入必须点名可分配岗位码（绕开保留角色早退）。"""
        assignable = _seeded_role_codes() - _forbidden_user_roles()
        assert "customer_service" in assignable, (
            f"前提失效：`roles` 种子里的可分配岗位码现取 = {sorted(assignable)}"
            " —— `customer_service` 不在里面时 R3 的出口要跟着改（不许静默放行）")
        problems = early_exit_input_violations(_cases(), assignable)
        assert problems == [], "\n".join(problems)


class TestNamedCodeSingleSource:
    def test_permission_denied_code_is_the_single_source_constant(self):
        """R5：`PERMISSION_DENIED` 逐字等于工具层的单一来源常量（不是用例里另写一份）。"""
        assert permission_denied_code() == "PERMISSION_DENIED"
        hr009 = [c for c in _cases() if str(c.get("id")) == "HR-009"][0]
        declared = _specs(hr009)[0]["error_code"]
        assert declared == permission_denied_code()
        assert declared != "VALIDATION_ERROR", (
            "把要**排除**的那条拒绝（保留角色 422）写成期望 = 断言方向反了")

    def test_every_declared_code_exists_in_source(self):
        """R5：声明过的码必须是真实字面量（拼错会让断言恒不满足，是另一种假绿/恒红）。"""
        problems = unknown_declared_codes(_cases())
        assert problems == [], "\n".join(problems)


class TestLedgerIsShrinkOnly:
    def test_ledger_is_shrink_only(self):
        """R6：`baseline` 冻结、条目数只许缩短、每行都有「为什么留」与「怎么才能具名」。"""
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
        assert data["baseline"] == 3, (
            "`baseline` 冻结为 3（只许缩短）：抬数 = 让新债合法化，正是本台账要防的形态")
        assert len(data["entries"]) <= data["baseline"]
        for entry in data["entries"]:
            assert str(entry.get("why_baseline") or "").strip(), f"{entry.get('case')}: 缺 why_baseline"
            assert str(entry.get("unblock") or "").strip(), f"{entry.get('case')}: 缺 unblock（无出口的债）"


# ══════════════════════════════════════════════════════════════════════════════
# R4：runner 的 `error_code` 语义（构造轨迹注入 —— 每格都是「行为确实错」的形态）
# ══════════════════════════════════════════════════════════════════════════════

def _round(rnd, calls, results):
    """一轮 `results` 条目：`calls=[(tool, args)]`、`results=[(tool, result_dict)]`（顺序一一对应）。"""
    return {
        "__round": rnd,
        "tool_calls": [{"name": t, "args": a} for t, a in calls],
        "tool_results": [{"tool": t, "result": r} for t, r in results],
    }


CREATE_CALL = ("employee_manage", {"action": "create", "role": "agent"})


def _created(ok, code=""):
    res = {"success": ok}
    if code:
        res["error_code"] = code
    return [("employee_manage", res)]


SPEC = [{"tool": "employee_manage", "action": "create", "error_code": "PERMISSION_DENIED"}]


class TestRunnerNamedCodeSemantics:
    def test_other_rejection_code_is_a_named_violation(self):
        """**红证主体**：失败码是 VALIDATION_ERROR（保留角色）而声明 PERMISSION_DENIED ⇒ 具名违规。"""
        issues = lr.check_must_fail([_round(1, [CREATE_CALL], _created(False, "VALIDATION_ERROR"))], SPEC)
        assert len(issues) == 1
        assert "VALIDATION_ERROR" in issues[0] and "PERMISSION_DENIED" in issues[0]
        assert "拒绝理由不可替换" in issues[0]

    def test_matching_rejection_code_passes(self):
        issues = lr.check_must_fail([_round(1, [CREATE_CALL], _created(False, "PERMISSION_DENIED"))], SPEC)
        assert issues == []

    def test_success_still_violates(self):
        """成功判据不因 `error_code` 改变（越权落库仍是最坏形态）。"""
        issues = lr.check_must_fail([_round(1, [CREATE_CALL], _created(True))], SPEC)
        assert len(issues) == 1
        assert "**成功**" in issues[0]

    def test_failure_without_code_is_fail_closed(self):
        """失败结果**没带**码 ⇒ 无法核对拒绝理由 ⇒ 违规（不静默跳过）。"""
        issues = lr.check_must_fail([_round(1, [CREATE_CALL], _created(False))], SPEC)
        assert len(issues) == 1
        assert "（空）" in issues[0] and "PERMISSION_DENIED" in issues[0]

    def test_never_called_still_passes(self):
        """镜像语义不变：从未调用 ⇒ 通过（「拒绝」未必等于「尝试」；由 expectations 管尝试）。"""
        assert lr.check_must_fail([_round(1, [], [])], SPEC) == []

    def test_args_plus_error_code_is_a_config_error(self):
        """`args`（值级）与 `error_code`（具名）同时声明 ⇒ 配置错误，不许静默只核一半。"""
        issues = lr.check_must_fail([], [{"tool": "order_create", "args": {"customer_phone": "05718886666"},
                                         "error_code": "PERMISSION_DENIED"}])
        assert len(issues) == 1
        assert "配置" in issues[0] and "不能同时声明" in issues[0]

    def test_unknown_key_is_still_a_config_error(self):
        """fail-closed 不回退：拼错的键仍报配置错误，不静默忽略。"""
        issues = lr.check_must_fail([], [{"tool": "employee_manage", "err_code": "PERMISSION_DENIED"}])
        assert len(issues) == 1
        assert "未支持的键" in issues[0]


class TestRedProof:
    """红证（每个注入都先自证生效：断言的是被注入对象真的变了）。

    实测（本单，2026-11-27）：
      * 删掉 HR-009 的 `error_code:` 行 ⇒ `test_every_must_fail_is_named_or_in_the_ledger`
        与 `test_restricted_identity_cases_never_sit_in_the_ledger` **同时**报 `HR-009`
        （前者「未登记」，后者「受限身份必须具名」）；
      * 把输入里的 `customer_service` 删掉 ⇒ `test_create_must_fail_inputs_name_an_assignable_role`
        报 `HR-009` 并列出可分配码集合；
      * 把 HR-009 的码改成 `VALIDATION_ERROR` ⇒ `TestNamedCodeSingleSource` 两条同时红；
      * `TestRunnerNamedCodeSemantics` 的七格 = 直接喂错误轨迹，全部红/绿可分辨。
    """

    def test_injection_actually_changes_the_body(self):
        """自证：注入对象（HR-009 的 must_fail 条目）里确实有可删的 `error_code` 与可删的岗位码。"""
        hr009 = [c for c in _cases() if str(c.get("id")) == "HR-009"][0]
        assert _specs(hr009)[0]["error_code"] == "PERMISSION_DENIED"
        assert "customer_service" in " ".join(str(x) for x in hr009.get("user_inputs") or [])
