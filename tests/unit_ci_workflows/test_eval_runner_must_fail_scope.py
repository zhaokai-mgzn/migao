# case_ids: OR-026
"""`must_fail` 的**参数值级作用域** + 配置 fail-closed（issue #3689，确定性层 / 零 LLM）。

**为什么需要**：OR-026（`.github/cases/order.yml:1573`）要的不变式是
「**任何一次以非法号码 `05718886666` 为 `customer_phone` 的 `order_create` 都不得成功**」。
`must_fail` 原有粒度只有 **工具×action**（`local_runner.py:1567`），三种写法逐一验过都不成立：

| 写法 | 结果 |
|---|---|
| `must_fail: [{tool: order_create}]` | 与本例 `must_succeed: order_create` **语义矛盾**（改正号码后必须成功） |
| `must_fail: [{tool: validate_input}]` | 同样矛盾（改正后闸门必须放行） |
| `must_fail: [{tool: order_create, action: create}]` | `order_create` **没有 action 参数** → 声明值永不匹配 → `if not called: continue` **整条静默跳过** = 假绿 |

**假红面（不补会挨的另一刀）**：`args` 键在旧实现里**被完全忽略**（`spec.get("args")` 从不读取）
→ 值级作用域静默降级成**工具级**「全程一次都不得成功」→ 与 `must_succeed` 直接冲突 =
用例一旦照抄就恒红。本文件的两组红证分别锁住这两面：

| 红证 | 喂什么（行为确实错了） | 必须看到 |
|---|---|---|
| ① 匹配 args 的调用**成功了** | 非法号调用 `success=true` | 报违规 |
| ② 同轮**别的调用**成功顶替 | 匹配 args 的那次失败、同轮另一次成功 | **不许**报违规（假红面） |
| ③ 反向：匹配 args 的那次成功、同轮另一次失败 | 非法号那次成功 | 必须报违规（假绿面） |
| ④ 配置键拼错/未支持（如 `rounds:`） | 该键会被静默忽略 → 断言空转 | **报配置错误**，不许静默跳过 |

红证 ④ 是「断言'未评估'也是一种失败」的落地：**未匹配的配置一律报错，不静默跳过**。
⚠️ 反向也要锁住：**从未调用 = 通过**仍是 `must_fail` 的既定镜像语义（"拒绝"未必等于"尝试"），
  不得因为 fail-closed 就把它改成红 —— 那会把"模型压根没尝试非法写操作"这类**合格拒绝**判红。

⚠️ 本目录跑在 CI 的 `ci workflow helper unit tests` job（只装 pytest+pyyaml），
而 `local_runner` 有模块级 `import httpx` → 用下方 `_load_runner()` 的最小替身。
"""
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


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

ILLEGAL_PHONE = "05718886666"
LEGAL_PHONE = "13800138000"


def _round(rnd, calls, results):
    """构造一轮 `results` 条目（同 `test_eval_runner_assertion_scope.py` 的构造器）。

    calls   : [(tool, args_dict)]
    results : [(tool, success, data)] —— 与该轮同名工具的调用**按顺序**对应
    """
    return {
        "__round": rnd,
        "tool_calls": [{"name": t, "args": a} for t, a in calls],
        "tool_results": [
            {"tool": t, "result": {"success": ok, "data": d}} for t, ok, d in results
        ],
    }


def _illegal_call(rnd=1, ok=True):
    """「用非法号码建单」这一轮 —— OR-026 的拒绝半就是冲它来的。"""
    return _round(
        rnd,
        [("order_create", {"customer_phone": ILLEGAL_PHONE, "items": []})],
        [("order_create", ok, {"orderNo": "ORD-1"} if ok else {})],
    )


class TestMustFailArgsScope:
    """`{tool: X, args: {k: v}}` = 「**凡匹配该 args 的那次调用**都不得成功」。"""

    def test_matching_args_call_succeeded_is_red(self):
        """**红证 ①**：非法号那一次 `order_create` 真的成功了 → 必须报违规。

        这是本能力存在的理由：脏单落库（用校验不通过的值建了单）必须机器可见。
        """
        issues = lr.check_must_fail(
            [_illegal_call(ok=True)],
            [{"tool": "order_create", "args": {"customer_phone": ILLEGAL_PHONE}}])
        assert len(issues) == 1, issues
        assert "must_fail" in issues[0] and "order_create" in issues[0]
        assert "R1" in issues[0]

    def test_matching_args_call_failed_is_green(self):
        """合格拒绝：非法号被写前校验挡下（`success=false`）→ 绿。"""
        issues = lr.check_must_fail(
            [_illegal_call(ok=False)],
            [{"tool": "order_create", "args": {"customer_phone": ILLEGAL_PHONE}}])
        assert issues == []

    def test_args_declared_but_never_attempted_is_green(self):
        """镜像语义不变：**从未调用**（含"从未用该 args 调用"）= 通过。

        "拒绝"未必等于"尝试"——模型压根没拿非法号去建单，也是合格拒绝。
        """
        assert lr.check_must_fail(
            [], [{"tool": "order_create", "args": {"customer_phone": ILLEGAL_PHONE}}]) == []
        # 只调了合法号码 → 同样不构成违规（这正是旧实现会**误报**的形态，见下一条）
        legal = _round(1, [("order_create", {"customer_phone": LEGAL_PHONE})],
                       [("order_create", True, {"orderNo": "ORD-2"})])
        assert lr.check_must_fail(
            [legal],
            [{"tool": "order_create", "args": {"customer_phone": ILLEGAL_PHONE}}]) == []

    def test_legal_call_success_does_not_satisfy_illegal_scope(self):
        """**修假红面**：只用合法号码成功建单 ≠ 违反「非法号码不得建单」。

        旧实现忽略 `args` → 降级成工具级「order_create 全程一次都不得成功」→
        与 OR-026 自己的 `must_succeed[order_create]` **直接冲突**（用例照抄即恒红）。
        """
        results = [
            _round(1, [("order_create", {"customer_phone": ILLEGAL_PHONE})],
                   [("order_create", False, {})]),
            _round(2, [("order_create", {"customer_phone": LEGAL_PHONE})],
                   [("order_create", True, {"orderNo": "ORD-3"})]),
        ]
        assert lr.check_must_fail(
            results, [{"tool": "order_create", "args": {"customer_phone": ILLEGAL_PHONE}}]) == []

    def test_same_round_other_call_success_does_not_borrow(self):
        """**红证 ②（假红面）**：同轮匹配 args 的那次**失败**、另一次成功 → 不许报违规。

        对齐规则与 `_round_action_result`（#3667/#3681）同源：`tool_result` 不带 args，
        只能按**同轮同名调用出现顺序**对齐；"该轮有成功就算"会张冠李戴。
        """
        r = _round(
            1,
            [("order_create", {"customer_phone": ILLEGAL_PHONE}),
             ("order_create", {"customer_phone": LEGAL_PHONE})],
            [("order_create", False, {"error": "手机号格式不正确"}),
             ("order_create", True, {"orderNo": "ORD-4"})],
        )
        assert lr.check_must_fail(
            [r], [{"tool": "order_create", "args": {"customer_phone": ILLEGAL_PHONE}}]) == []

    def test_same_round_matched_call_success_is_red_even_if_other_failed(self):
        """**红证 ③（假绿面）**：同轮匹配 args 的那次**成功**、另一次失败 → 必须报违规。

        只按工具名数成败（旧口径）会在这里漏判 —— 脏单已经落库了，报告却全绿。
        """
        r = _round(
            1,
            [("order_create", {"customer_phone": ILLEGAL_PHONE}),
             ("order_create", {"customer_phone": LEGAL_PHONE})],
            [("order_create", True, {"orderNo": "ORD-5"}),
             ("order_create", False, {"error": "库存不足"})],
        )
        issues = lr.check_must_fail(
            [r], [{"tool": "order_create", "args": {"customer_phone": ILLEGAL_PHONE}}])
        assert len(issues) == 1, issues
        assert "R1" in issues[0]

    def test_multiple_args_keys_are_all_required(self):
        """多键 args = **全部**匹配才算（AND 语义）。"""
        results = [_round(
            1,
            [("order_manage", {"action": "cancel", "order_id": "ORD-9"})],
            [("order_manage", True, {"status": "cancelled"})])]
        spec = [{"tool": "order_manage", "args": {"action": "cancel", "order_id": "ORD-9"}}]
        assert len(lr.check_must_fail(results, spec)) == 1
        # 只对上一半（order_id 不匹配）→ 不算匹配那次调用 → 绿
        assert lr.check_must_fail(
            results, [{"tool": "order_manage",
                       "args": {"action": "cancel", "order_id": "ORD-OTHER"}}]) == []

    def test_action_and_args_can_be_combined(self):
        """`action` + `args` 同时声明 → 两者都命中才算作用域（AND）。"""
        results = [_round(
            1,
            [("order_manage", {"action": "cancel", "order_id": "ORD-8"})],
            [("order_manage", True, {"status": "cancelled"})])]
        assert len(lr.check_must_fail(
            results, [{"tool": "order_manage", "action": "cancel",
                       "args": {"order_id": "ORD-8"}}])) == 1
        assert lr.check_must_fail(
            results, [{"tool": "order_manage", "action": "update_status",
                       "args": {"order_id": "ORD-8"}}]) == []

    def test_value_comparison_normalizes_scalars(self):
        """值比较容错：数字/字符串同值、空白差异视为相等（YAML 与 payload 形态天然不同）。"""
        results = [_round(
            1, [("product_manage", {"action": "create", "price": 23.8})],
            [("product_manage", True, {"product_id": "p1"})])]
        assert len(lr.check_must_fail(
            results, [{"tool": "product_manage", "args": {"price": "23.8"}}])) == 1
        assert len(lr.check_must_fail(
            results, [{"tool": "product_manage", "args": {"price": 23.80}}])) == 1

    def test_tool_level_spec_keeps_legacy_semantics(self):
        """向后兼容锚点：裸工具名（无 action/args）= 原有「全程一次都不得成功」。"""
        results = [_round(1, [("order_create", {"customer_phone": LEGAL_PHONE})],
                          [("order_create", True, {"orderNo": "ORD-6"})])]
        assert len(lr.check_must_fail(results, ["order_create"])) == 1

    def test_unalignable_round_falls_back_to_round_level_success(self):
        """对不齐（结果数 ≠ 调用数，如合成轨迹）→ 按该轮该工具口径回退，不静默放过。

        与 `_round_action_result` 的 `legacy_ok` 回退同源（#3681）：对齐得上时用"那一次自己"，
        对不上时不猜也不静默 —— 该轮该工具确有成功即按违规报（fail-closed 侧）。
        """
        r = {"__round": 1,
             "tool_calls": [{"name": "order_create",
                             "args": {"customer_phone": ILLEGAL_PHONE}}],
             "tool_results": [{"tool": "order_create",
                               "result": {"success": True, "data": {}}}]}
        r["tool_calls"].append({"name": "order_create",
                                "args": {"customer_phone": LEGAL_PHONE}})
        assert len(lr.check_must_fail(
            [r], [{"tool": "order_create",
                   "args": {"customer_phone": ILLEGAL_PHONE}}])) == 1


class TestMustFailConfigIsFailClosed:
    """**未匹配/未评估的配置一律报错，不许静默跳过**（"断言'未评估'也是一种失败"）。"""

    def test_unknown_key_is_a_config_error_not_silently_ignored(self):
        """**红证 ④**：`rounds:`（未支持）或拼错的 `arg:` 会被旧实现**静默忽略** → 断言空转。

        静默忽略的两种后果都在仓库里发生过：
          · `arg` 拼错 → 降级成工具级语义（假红，OR-026 的 `must_succeed` 直接冲突）；
          · `rounds` 未实现 → 作者以为限定了轮次，实际全程判定（假绿/假红都可能）。
        """
        results = [_illegal_call(ok=True)]
        for bad in ({"tool": "order_create", "rounds": [1]},
                    {"tool": "order_create", "arg": {"customer_phone": ILLEGAL_PHONE}}):
            issues = lr.check_must_fail(results, [bad])
            assert len(issues) == 1, (bad, issues)
            assert "未支持" in issues[0] or "配置" in issues[0]

    def test_non_dict_args_is_a_config_error(self):
        """`args` 不是映射（如 yaml_light 把 flow 序列读成字符串）→ 报错，不许空转通过。"""
        issues = lr.check_must_fail(
            [_illegal_call(ok=True)],
            [{"tool": "order_create", "args": "customer_phone=05718886666"}])
        assert len(issues) == 1 and "args" in issues[0]

    def test_empty_args_is_a_config_error(self):
        """空 `args` = 什么也不匹配（断言永不成立）→ 配置错误，不许静默通过。"""
        issues = lr.check_must_fail(
            [_illegal_call(ok=True)], [{"tool": "order_create", "args": {}}])
        assert len(issues) == 1 and "args" in issues[0]

    def test_missing_tool_is_still_a_config_error(self):
        """既有锚点（不改语义）：缺 tool 仍是配置错误，不许静默跳过。"""
        issues = lr.check_must_fail([_illegal_call()], [{"action": "create"}])
        assert len(issues) == 1 and "tool" in issues[0]

    def test_list_items_without_any_scope_report_nothing(self):
        """空列表 → 无断言（`must_fail: []` 与缺省同义，不是配置错误）。"""
        assert lr.check_must_fail([_illegal_call()], []) == []
        assert lr.check_must_fail([_illegal_call()], None) == []
