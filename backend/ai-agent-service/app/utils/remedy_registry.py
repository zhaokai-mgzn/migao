# app/utils/remedy_registry.py
"""族 6（善后与补救）的「失败 → 原因 → 补救」**登记表**（issue #5441）。

**为什么单独成模块**：族 1~5 做「让 Agent 能做事」；族 6 做「**做不成时怎么办**」。
B 端用户（商家员工 / 客服）没有耐心读堆栈、也不知道该找谁 —— 失败的**用户可见话术**过去散在三处
（`execution/react_turn.py` 的 `tool_not_found`、`app/tools/base.py::_denial_suggestion` 的授权拒绝、
`graph/skills/references/base/principles.md` 的后台路径），**各自维护、没有任何东西会因为
「某个失败码没有对应话术」而变红**。本模块把它们收敛成**一张受判据约束的表**。

## 三条硬纪律（本模块的结构就是照它们长的）

① **「可重试」与「不可重试」必须分开** —— 幂等性不成立的操作（下单 / 支付 / 批量写）
   **绝不能建议重试**，否则用户按提示重来一次就是**重复写入**。
   ⚠️ 可重试**不是本表说了算**：本表只**声明** `retry=`，真值由**既有单一口径**现取推导 ——
   `app/tools/base.py::NON_RETRYABLE_ERROR_CODES`（按码）+ `BaseTool.idempotent`（按操作，
   `app/tools/order_create.py` 明写 `idempotent = False`）。推导见 `retry_allowed()`；
   **取不到证据一律判不可重试**（与 `app/graph/skills/base_skill.py::_self_correct_retry` 的 fail-safe 同向）。
   判据：`tests/unit_ci_workflows/test_remedy_registry_guard.py::test_non_retryable_remedies_never_suggest_retry`。

② **用户可见文本 ≠ 归因**（`app/utils/error_incident.py` 的既有纪律）：
   短码、类型、异常消息只落**日志/审计**；用户那一句必须是**纯中文短句**（面向低学历用户的既有约定，
   issue #3707 族）。⇒ 本表每一行的 `reason` / `remedy` **不含任何 ASCII 字母**（结构上不可能回显
   短码 / 工具名 / 异常原文），判据 `test_user_visible_text_is_pure_chinese_without_attribution`。

③ **不含「转人工」** —— 用户已裁定下线（2026-09-19：「不应该存在 human_handoff 这种东西，
   以后全是 AI 来判断」）。⇒ 本表的任何一行都**不得**把「转人工 / 找人工客服」当补救路径；
   判据把「转人工」纳入禁用形态（见 `tests/unit_ci_workflows/test_remedy_registry_guard.py` 的
   `FORBIDDEN_TEXT` 族与 `tests/unit_ci_workflows/test_human_handoff_retired.py`）。

## 表的形状

- **码级行**（`scope=""`）：对该失败码的通用话术；
- **操作级行**（`scope="<工具名>"`）：只对该操作生效，优先于码级行 ——
  这就是「同一个失败码，下单（不可重试）与只读查询（可重试）给出**不同**建议」的落点；
- **`DEFAULT_REMEDY`**（`code=""`）：**未登记码的唯一出口**。它同样受全部文本面判据约束，
  且**不得**是「未知错误」（判据 `test_default_wording_is_not_unknown_error`）。

`entry=` 声明补救路径**指向的入口**（`tool:<工具名>` / `page:<菜单项名>` / `""` = 无入口）：
它必须真实存在（工具在词汇表里且被某个 skill 绑定；页面是真实侧边栏菜单项），
且话术里点名的入口**必须**被声明 —— 否则「指点去哪里」的文本会落在判定面之外（永久免检）。
判据复用 issue #5331 的**引用面判据本体**（`tests/unit_ci_workflows/test_dead_capability_meta_guard.py`），
**不另立第二套**。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.tools.base import NON_RETRYABLE_ERROR_CODES

#: 补救路径的入口形态（与判据 `tests/unit_ci_workflows/test_remedy_registry_guard.py` 同口径）。
TOOL_ENTRY = "tool:"
PAGE_ENTRY = "page:"


@dataclass(frozen=True)
class Remedy:
    """一条「失败 → 原因 → 补救」登记。

    Args:
        code: 失败短码（与日志/审计侧同一口径，见 `app/utils/error_incident.py`）。`""` = 默认话术行。
        reason: **纯中文短句** —— 为什么没做成（用户看得懂的那一句）。
        remedy: **纯中文短句** —— 下一步能做什么（可点 / 可照做的动作）。
        entry: 补救路径指向的入口：`tool:<工具名>` / `page:<菜单项名>` / `""`（无入口）。
        scope: 该行只适用于这个工具（操作级行）；`""` = 码级行（对该码通用）。
        retry: 声明「是否建议用户重复这次操作」。⚠️ **声明，不是真值** ——
            真值由 `retry_allowed()` 从既有单一口径现取推导，判据会校验二者一致。
    """

    code: str = ""
    reason: str = ""
    remedy: str = ""
    entry: str = ""
    scope: str = ""
    retry: bool = False


#: 登记表本体。**新增失败码 ⇒ 必须同 PR 登记一行**（未登记码走 `DEFAULT_REMEDY`，
#: 并被 `tests/unit_ci_workflows/remedy_registry_ledger.json` 的燃尽账户记账）。
REMEDIES: tuple[Remedy, ...] = (
    # ── 工具面：模型调不到 / 调不成 ──────────────────────────────────────────
    Remedy(
        code="tool_not_found",
        reason="我这边暂时没有能直接办这件事的方式",
        remedy="请换个说法告诉我您想要的结果，我换个方式为您处理。",
    ),
    Remedy(
        code="tool_not_found_relocked",
        reason="订单流程刚刚切换到了订单模块",
        remedy="请回复「继续」，我马上为您提交订单。",
    ),
    Remedy(
        code="tool_execution_failed",
        reason="刚才那次操作没有成功",
        remedy="请核对一下要填的信息是否完整准确，我确认无误后再继续办理。",
    ),
    # 操作级行：**下单**（`app/tools/order_create.py` 明写 `idempotent = False`）。
    # 这是硬纪律 ① 的落点：同一失败码，下单**不得**被建议重来（会重复下单）。
    Remedy(
        code="tool_execution_failed",
        scope="order_create",
        reason="下单没有成功",
        remedy="订单还没有生成，请不要连续提交；核对收货信息后告诉我，我再为您办理。",
    ),
    # 操作级行：**只读查询**（幂等 ⇒ 可重试这一侧真的存在，判据 2 不是永远为假的空断言）。
    Remedy(
        code="tool_execution_failed",
        scope="product_search",
        reason="这次查询没有查出结果",
        remedy="可能是一时的网络波动，请稍等片刻，再试一次。",
        retry=True,
    ),
    # ── 授权面：换参数也不可能成功的终态（`NON_RETRYABLE_ERROR_CODES`）────────
    Remedy(
        code="PERMISSION_DENIED",
        reason="您的账号没有这项操作的权限",
        remedy="请联系管理员在「员工管理」里为您开通这项权限，开通后再让我办理。",
        entry="page:员工管理",
    ),
    Remedy(
        code="FORBIDDEN",
        reason="这项操作被权限设置挡住了",
        remedy="请让管理员在「员工管理」里确认一下您的权限，配置好之后再让我办理。",
        entry="page:员工管理",
    ),
    # ── 认证面：登录态 / 会话 / 服务令牌（**不是**账号缺权限，措辞必须分叉）──
    # 与 `app/tools/base.py::_denial_suggestion` 的既有口径同向（那边按 `AUTHENTICATION_ERROR_CODES`
    # 分叉；本表只是把它落成登记行）。
    Remedy(
        code="AUTH_REQUIRED",
        reason="您的登录状态可能已经失效",
        remedy="请重新登录，再发起这次操作；如果还是不行，请让管理员检查账号的登录配置。",
    ),
    Remedy(
        code="AUTH_FAILED",
        reason="这次登录没有通过校验",
        remedy="请重新登录，再发起这次操作；如果还是不行，请让管理员检查账号的登录配置。",
    ),
    Remedy(
        code="UNAUTHORIZED",
        reason="系统没有认出您的登录身份",
        remedy="请重新登录，再发起这次操作；如果还是不行，请让管理员检查账号的登录配置。",
    ),
    # ── 业务前提面：事实没落地 / 口径对不上 ────────────────────────────────
    Remedy(
        code="product_not_grounded",
        reason="我没有查到您说的那款商品",
        remedy="请把商品的名称或编号再说一次，我按您给的信息重新查询。",
        entry="tool:product_search",
    ),
    Remedy(
        code="unit_price_not_grounded",
        reason="这款商品的单价我还没有核实到",
        remedy="请告诉我商品的名称或编号，我先查到确切单价再为您报价。",
        entry="tool:product_search",
    ),
    Remedy(
        code="order_confirmation_mismatch",
        reason="确认卡上的内容和实际订单对不上",
        remedy="我不会按这个内容提交；请重新确认一次要下单的商品和数量。",
    ),
    Remedy(
        code="sms_code_not_from_customer",
        reason="这个验证码不是顾客本人提供的",
        remedy="请让顾客本人把收到的验证码发给我，我再继续。",
    ),
    # ── 配置前提面 ─────────────────────────────────────────────────────────
    Remedy(
        code="CRAFT_CALC_CONFIG_UNAVAILABLE",
        reason="算料参数还没有配置好",
        remedy="请联系管理员先完成算料参数配置，配置好之后再让我为您计算。",
    ),
)

#: **未登记码的唯一出口**（判据 1 的括号：未登记 ⇒ 有默认话术，但**不得**是「未知错误」）。
#: 它同样受全部文本面判据约束 —— 而且因为它对**未知操作**生效（下单 / 付款这类非幂等操作
#: 就可能走这里），所以**一律不得建议重试**。
DEFAULT_REMEDY = Remedy(
    code="",
    reason="这件事这次没有办成",
    remedy="请把您想要的结果再说一遍，我会先核对清楚、确认无误再往下办。",
)


def _operation_is_idempotent(scope: str) -> bool:
    """操作是否**已证明幂等**：读**既有单一标注** `BaseTool.idempotent`（不另立清单）。

    `BaseTool` 的缺省是 `True`，但**取不到工具对象时一律返回 False**
    （与 `base_skill._self_correct_retry` 的 fail-safe 同向：不证明可重试就不劝重试）。
    """
    if not scope:
        return False
    try:
        from app.tools.registry import get_tool_registry

        tool = get_tool_registry().get_tool(scope)
    except Exception:  # noqa: BLE001 —— 取不到标注 = 不可重试（fail-safe，不是吞错）
        return False
    return bool(getattr(tool, "idempotent", False))


def retry_allowed(code: str, *, scope: str = "") -> bool:
    """**推导**「是否建议重复这次操作」——两个既有单一口径，本模块不新增真相源。

    ① 码级：`code ∈ NON_RETRYABLE_ERROR_CODES`（授权/认证类，换参数也不可能成功）⇒ 否；
    ② 操作级：`scope` 指向的工具必须**已证明幂等**（`BaseTool.idempotent`）⇒ 否则否。
    ⇒ 取不到证据（无 scope / 工具不存在）**一律返回 False**。
    """
    if (code or "").strip() in NON_RETRYABLE_ERROR_CODES:
        return False
    return _operation_is_idempotent((scope or "").strip())


def remedy_for(code: str, *, scope: str = "") -> Remedy:
    """查登记表：操作级行 → 码级行 → `DEFAULT_REMEDY`（**永不返回空**）。"""
    code = (code or "").strip()
    scope = (scope or "").strip()
    if code and scope:
        for row in REMEDIES:
            if row.code == code and row.scope == scope:
                return row
    if code:
        for row in REMEDIES:
            if row.code == code and not row.scope:
                return row
    return DEFAULT_REMEDY


def user_text(code: str, *, scope: str = "") -> str:
    """用户可见的那一句（原因 + 补救）。**纯中文短句，不含短码 / 例外原文**。"""
    row = remedy_for(code, scope=scope)
    return f"{row.reason}。{row.remedy}"


def entry_of(code: str, *, scope: str = "") -> Optional[str]:
    """该失败码补救路径指向的入口（`""` = 无入口）。"""
    return remedy_for(code, scope=scope).entry or None