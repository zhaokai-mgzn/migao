# case_ids: HR-009, HR-010
"""评测可控权限（`X-Debug-Permissions`）的**前置自断言**与**负效果断言**（issue #4108）。

## 病灶（CI run `35259795549` 的 Case Trust Gate，4 条阻塞）

按名新建的 HR-009 / HR-010 被判三条规则：

| 规则 | HR-009 | HR-010 | 形态 |
|---|---|---|---|
| `CASE-TRUST-NO-PRECONDITION-ASSERTION` | ✗ | ✗ | 前置（"本会话真的以受限权限跑"）没有任何可判定断言 |
| `CASE-TRUST-NO-EFFECT-ASSERTION` | ✗ | — | 写类用例只有"调用了"级断言 |
| `CASE-TRUST-NO-SELF-CLEAN` | ✗ | — | 写类用例未声明自清理 |

两条都是**真缺口**，不是门禁误判：

· **前置**：`X-Debug-Permissions` 的生效条件是"DEBUG=true ∧ `X-Debug-Role` 非 customer
  ∧ 值过白名单"。任一条不成立（头名拼错、值含空格、角色写成 customer、栈里 DEBUG=false）
  ⇒ 服务端**静默回落通配 `["*"]`** ⇒ HR-009 的"越权被拒"变成"有权限所以成功"，
  而报告上只表现为「agent 没按预期调用」——**归因全错**（`PG-013`/`CU-003` 同族）。
· **效果**：被**拒绝**的写操作，其效果层真值是**负向**的（"什么都没落库"）。
  `must_fail` 只覆盖"没有一次成功调用"；若权限门禁**静默失效**，`create` 会成功 ⇒
  这时必须有一层读**落库真身**的断言把它判红。

## 本文件锁的不变式（每条都有红证）

1. `debug_permissions_effective` 前置类型**有实现**、被 `check_precondition_declared` 认账；
2. 判据**可红**：声明与实际生效范围不一致 ⇒ 红；且三种"静默回落"形态
   （空值 / 含 `*` / 非法码）都红 —— 它们都会让服务端给通配权限；
3. 判据**不恒红**：- 合法且一致 ⇒ 绿（正例）；
4. `db_verify[employee_absent]` 的**形状守卫**必须 fail-closed（缺 name/phone ⇒ 报错，
   不得静默"查不到就算过"）；
5. HR-009 / HR-010 两条用例**都**声明了这个前置，且 Case Trust Gate 认账
   （`declares_precondition` 返回 True）—— 防"改了 fixture 但用例没声明"。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

from render_cases import load_case_dicts  # noqa: E402

import assertion_taxonomy as tax  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"
TARGET_CASES = ("HR-009", "HR-010")


def _runner():
    """按 `test_eval_product_name_pollution` 同款方式加载 runner（顶层无副作用 import）。"""
    import importlib.util
    import os
    os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    spec = importlib.util.spec_from_file_location(
        "migao_eval_runner_dbp", REPO_ROOT / "tests" / "agent_eval" / "local_runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cases():
    return {c["id"]: c for c in load_case_dicts(str(CASES_DIR))}


# ══════════════════════════════════════════════════════════════════════════════
# 一、前置类型有实现（fail-closed，不静默跳过）
# ══════════════════════════════════════════════════════════════════════════════

class TestPreconditionTypeIsImplemented:

    def test_type_is_registered(self):
        lr = _runner()
        assert "debug_permissions_effective" in lr._PRECONDITION_TYPES, (
            "声明了没人实现的 type ⇒ check_precondition_declared 报 config_error"
            "（用例带一个不生效的守卫跑）")

    def test_declared_type_passes_static_check(self):
        lr = _runner()
        spec = [{"type": "debug_permissions_effective", "source": "employee:list"}]
        assert lr.check_precondition_declared(spec) == []

    def test_unknown_type_still_fail_closed(self):
        """兜底分支不得被放宽：未知 type 必须继续报错（防"新类型顺手开个大口子"）。"""
        lr = _runner()
        bad = lr.check_precondition_declared([{"type": "no_such_type", "source": "x"}])
        assert bad and "没有实现" in bad[0]


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据可红 / 不恒红（红证是这一组的全部意义）
# ══════════════════════════════════════════════════════════════════════════════

class TestEffectiveScopeCheckIsRedProvable:

    SPEC = [{"type": "debug_permissions_effective", "source": "employee:list"}]

    def _check(self, effective):
        return _runner().check_debug_permissions_effective(self.SPEC, effective)

    def test_match_is_green(self):
        assert self._check("employee:list") == []

    def test_mismatch_is_red(self):
        """声明 employee:list 而实际拿到别的码 ⇒ 红（用例考的不是它声称的行为）。"""
        issues = self._check("order:list")
        assert issues, "声明与实际不一致却判绿 ⇒ 前置断言没有判别力（空跑）"

    def test_multi_code_exact_match_is_green(self):
        """声明多个码时**逐一相等**即绿（判据是相等，不是包含）。"""
        lr = _runner()
        spec = [{"type": "debug_permissions_effective", "source": "employee:list,order:list"}]
        assert lr.check_debug_permissions_effective(spec, "employee:list,order:list") == []

    def test_extra_code_is_red(self):
        """实际范围**宽于**声明 ⇒ 红：用例考的不是它声称的范围（#4108：「有能力时不得误拒」
        这条正向对照的全部意义就在于范围**恰好**是声明的那一个）。"""
        assert self._check("employee:list,order:list")

    def test_subset_is_red(self):
        """实际范围**窄于**声明 ⇒ 红（少一个码会变成误拒，看起来像 agent 不干活）。"""
        assert self._check("")

    @pytest.mark.parametrize("effective", ["", None, "*", "employee:list,*",
                                           "employee:list,,foo:bar", " employee:list",
                                           "EMPLOYEE:LIST"])
    def test_wildcard_and_invalid_fallbacks_are_red(self, effective):
        """服务端对非法/空值**整串回落通配** ⇒ 这些形态必须判红，不得放过。

        这是本前置断言存在的**首要理由**：头的值一旦被回落成 `["*"]`，
        HR-009 就从"越权被拒"变成"有权限所以成功"，而报告上看不出差别。
        """
        assert self._check(effective), f"回落形态 {effective!r} 被判绿 ⇒ 前置断言无效"


# ══════════════════════════════════════════════════════════════════════════════
# 三、负效果断言（`employee_absent`）：形状 fail-closed
# ══════════════════════════════════════════════════════════════════════════════

class TestEmployeeAbsentShapeIsFailClosed:

    def test_missing_locator_is_config_error(self):
        """既无 name 也无 phone ⇒ 定位不到对象 ⇒ 必须报配置错误，不得"查不到就算过"。"""
        import asyncio
        lr = _runner()
        issues = asyncio.run(lr.check_db_verify("tok", [{"fetch": "employee_absent"}]))
        assert issues, "缺定位键却判过 ⇒ 这条断言永远绿（空断言）"
        assert "employee_absent" in issues[0]

    def test_supported_fetch_vocabulary_includes_absent(self):
        """L0 形状守卫的白名单必须同步（否则 CI 零依赖 job 会判"不支持的 fetch"）。"""
        src = (REPO_ROOT / "tests" / "unit_ci_workflows"
               / "test_assertion_specs_wellformed.py").read_text(encoding="utf-8")
        assert "employee_absent" in src, (
            "test_assertion_specs_wellformed.SUPPORTED_DB_FETCH 未收录 employee_absent"
            " ⇒ 用例里写了它会被 L0 判「不支持的 fetch」")


# ══════════════════════════════════════════════════════════════════════════════
# 四、真实用例：两条都声明了，且门禁认账
# ══════════════════════════════════════════════════════════════════════════════

class TestRealCasesDeclareThePrecondition:

    def test_both_cases_declare_effective_scope(self):
        by = _cases()
        for cid in TARGET_CASES:
            specs = by[cid].get("precondition") or []
            hits = [s for s in specs if isinstance(s, dict)
                    and s.get("type") == "debug_permissions_effective"]
            assert hits, f"{cid} 未声明权限范围前置：{specs}"
            assert hits[0].get("source") == by[cid].get("debug_permissions"), (
                f"{cid} 的前置 source 必须与用例声明的 debug_permissions **同源**"
                f"（否则守卫守的是另一个值）：{hits[0]} vs {by[cid].get('debug_permissions')!r}")

    def test_gate_rule_f_accepts_the_declaration(self):
        """门禁 F 条必须认这个形态（否则 CI 仍红）。"""
        by = _cases()
        for cid in TARGET_CASES:
            ok, how = tax.declares_precondition(by[cid])
            assert ok, f"{cid} 的 precondition 声明未被门禁认账（{how}）"

    def test_hr009_has_negative_effect_assertion(self):
        """HR-009（被拒绝的写）必须有**负效果**断言：确认员工没有落库。"""
        c = _cases()["HR-009"]
        absent = [s for s in (c.get("db_verify") or [])
                  if isinstance(s, dict) and s.get("fetch") == "employee_absent"]
        assert absent, f"HR-009 缺效果层断言（写类用例不得只有「调用了」级断言）：{c.get('db_verify')}"
        assert tax.has_effect_assertion(c), "门禁的效果层判据仍不认它 ⇒ CI 仍红"

    def test_hr009_declares_self_clean(self):
        c = _cases()["HR-009"]
        assert c.get("pre_clean"), "HR-009 未声明自清理（门禁 b 条）"
        assert tax.self_clean_evidence(c) == "pre_clean", (
            "自清理证据必须是**强**形态 pre_clean（namespaces 是弱证据，不解决重试前置）")