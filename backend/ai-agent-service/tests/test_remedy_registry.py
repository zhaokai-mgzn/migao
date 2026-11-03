# case_ids: HR-009
"""族 6（善后与补救）登记表的**运行期**判据（issue #5441）。

与 `tests/unit_ci_workflows/test_remedy_registry_guard.py`（静态元守卫）的分工：
那边判**表本身**（登记面 / 重试面 / 引用面 / 文本面的机械性质），这里判**运行期出口** ——
`remedy_for()` / `user_text()` / `retry_allowed()` 在被真实调用时的行为，以及
**判据 5「同一次失败在日志侧短码稳定，本族只消费」**：短码由既有 `app/utils/error_incident.py`
产出（本单**不重写**它），登记的**用户可见话术里绝不能出现它** —— 这正是归因与用户文本的边界。
"""
from __future__ import annotations

from app.utils.error_incident import llm_incident_id
from app.utils.remedy_registry import (
    DEFAULT_REMEDY,
    REMEDIES,
    remedy_for,
    retry_allowed,
    user_text,
)


def _ascii_letters(text: str) -> str:
    return "".join(sorted({ch for ch in text if ch.isascii() and ch.isalpha()}))


class TestRemedyLookup:
    """登记命中 / 默认话术出口。"""

    def test_registered_code_returns_its_own_row(self) -> None:
        row = remedy_for("tool_not_found")
        assert row.code == "tool_not_found"
        assert row is not DEFAULT_REMEDY

    def test_unregistered_code_falls_back_to_default_not_unknown_error(self) -> None:
        """判据 1：**未登记 ⇒ 有默认话术，但默认话术不得是「未知错误」**。"""
        row = remedy_for("NO_SUCH_FAILURE_CODE_XYZ")
        assert row is DEFAULT_REMEDY
        assert row.reason.strip() not in ("", "未知错误", "系统错误", "操作失败")
        assert row.remedy.strip(), "默认话术必须给出下一步（空补救 = 用户什么都看不到）"

    def test_scope_specific_row_wins_over_code_row(self) -> None:
        """操作级行优先于码级行（下单失败与查询失败的话术必须不同）。"""
        general = remedy_for("tool_execution_failed")
        scoped = remedy_for("tool_execution_failed", scope="order_create")
        assert scoped.code == "tool_execution_failed"
        assert scoped.remedy != general.remedy, (
            "下单（非幂等）与通用码级行给出同一句话术 ⇒ 操作级那一行没生效"
        )

    def test_every_registered_row_has_reason_and_remedy(self) -> None:
        assert REMEDIES, "登记表为空 ⇒ 族 6 的登记面消失"
        for row in REMEDIES:
            assert row.reason.strip(), f"{row.code} 缺原因"
            assert row.remedy.strip(), f"{row.code} 缺补救"


class TestUserVisibleText:
    """判据 4：用户可见文本不含短码 / 异常原文（沿用 `error_incident.py` 的边界）。"""

    def test_user_text_is_pure_chinese(self) -> None:
        for code in [r.code for r in REMEDIES if r.code] + ["UNREGISTERED_CODE_ZZZ"]:
            letters = _ascii_letters(user_text(code))
            assert not letters, (
                f"`{code}` 的用户话术里出现 ASCII 字母 {letters} ⇒ 不是纯中文短句"
                f"（低学历用户约定；ASCII 字母正是短码/工具名/异常原文的形态）：{user_text(code)}"
            )

    def test_user_text_never_reveals_the_failure_code(self) -> None:
        for row in REMEDIES:
            if not row.code:
                continue
            assert row.code not in user_text(row.code, scope=row.scope)

    def test_incident_short_code_stays_on_the_log_side(self) -> None:
        """判据 5：短码稳定（既有实现，本族只消费）⇒ 它**不得**出现在用户可见话术里。"""
        session_id, exc_type = "sess_remedy_registry", "TimeoutError"
        incident = llm_incident_id(session_id, exc_type)
        assert incident == llm_incident_id(session_id, exc_type), "既有短码实现不再稳定（本族只消费它）"
        assert incident not in user_text("tool_execution_failed", scope="order_create"), (
            "用户话术里出现了日志侧 incident 短码 ⇒ 归因回显给了用户（硬纪律 ② 失守）"
        )
        assert incident not in user_text("NO_SUCH_FAILURE_CODE_XYZ")


class TestRetryDiscipline:
    """判据 2：不可重试的操作**不得**建议重试 —— 口径全部来自既有单一真相源。"""

    def test_permission_codes_are_not_retryable(self) -> None:
        """`NON_RETRYABLE_ERROR_CODES`（`app/tools/base.py`）是码级唯一口径。"""
        for code in ("PERMISSION_DENIED", "FORBIDDEN", "AUTH_REQUIRED", "AUTH_FAILED", "UNAUTHORIZED"):
            assert retry_allowed(code) is False, f"{code} 属授权/认证类，换参数也不可能成功"

    def test_non_idempotent_operation_is_not_retryable(self) -> None:
        """`BaseTool.idempotent` 是操作级唯一口径：下单每次调用都创建新订单。"""
        assert retry_allowed("tool_execution_failed", scope="order_create") is False
        assert remedy_for("tool_execution_failed", scope="order_create").retry is False

    def test_idempotent_read_operation_may_be_retried(self) -> None:
        """只读查询幂等 ⇒ 「可重试」这一侧**真的存在**（否则判据 2 只是一条永远为假的空断言）。"""
        assert retry_allowed("tool_execution_failed", scope="product_search") is True

    def test_unknown_operation_fails_safe_to_not_retryable(self) -> None:
        """取不到证据一律**不可重试**（与 `base_skill._self_correct_retry` 的 fail-safe 同向）。"""
        assert retry_allowed("tool_execution_failed") is False
        assert retry_allowed("tool_execution_failed", scope="no_such_tool_xyz") is False

    def test_non_retryable_rows_carry_no_retry_wording(self) -> None:
        for row in REMEDIES:
            if row.retry:
                continue
            text = f"{row.reason}。{row.remedy}"
            for marker in ("重试", "再试", "重新提交", "重新发起", "retry", "Retry"):
                assert marker not in text, f"{row.code}@{row.scope} 不可重试却出现「{marker}」：{text}"