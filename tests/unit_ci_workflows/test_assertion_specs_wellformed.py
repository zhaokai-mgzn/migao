# case_ids: OR-012, OR-014, OR-017, OR-018, CH-010, CH-011, DF-020, OR-023, OR-024
"""断言配置必须**形状正确**（issue #3367 断言层审计）。

## 为什么需要守卫

评测工具最危险的不是判错，而是**声称查过而其实没查**。本 session 抓到两起同族事故：

1. `amount_verify.checks` 因解析器把 flow 序列读成字符串 → 三项金额检查**全部静默跳过**、
   函数恒返回 [] → OR-014/OR-017 长期"带金额断言"却一个数都没核对；
2. `forbidden_args` / `required_args` 里「配置不完整就 `continue`」→ `fields` 写空/写错键名，
   那条**数据隔离/越权下限断言**就变 no-op，用例照样绿。

运行层已改为**失败关闭**（配错就报错）。本守卫把同一件事**左移**到 PR 阶段：
不合法配置在 CI 的零依赖 job 里就会红，不用等真实 LLM 全量跑完才发现。
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"
TOOLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "tools"

SUPPORTED_DB_FETCH = {
    "product_by_name", "order_items", "order_phone", "after_sales_ticket", "employee",
    "processing_order",
    # 负效果断言（issue #4108）：该员工**不得存在**。被权限拒绝的写用例，其效果层真值
    # 是负向的 —— 只有读落库真身能证伪"门禁静默失效后脏数据已落库"（#3778 的反面）。
    "employee_absent"}
SUPPORTED_POST_SESSION_FETCH = {"user_memories"}


def _specs(case, field):
    for s in case.get(field) or []:
        yield s if isinstance(s, dict) else {"tool": s}


def _multi_action_tools() -> dict:
    """从 tool 源码解析**多 action 工具** → {工具名: 动作集合}（单一源 = 工具源码）。

    为什么需要（issue #3544 实测 run 34809483940）：`output_verify` 按**工具名**取
    「首个成功调用的 payload」，而多 action 工具（如 `processing_item_manage` 的
    `list_categories` / `create_processing_item`）在同一次会话里会有多个 action 成功 →
    可能核对到**别的 action** 的 payload：字段名不撞 = **假红**（PP-006 实证），
    撞上 = **假绿**。故「多 action 工具必须显式声明 `action`」必须左移成 L0 不变式。

    判定信号（纯文本解析，CI helper job 无 app 依赖）：
      ① `VALID_ACTIONS = {...}` 且动作数 ≥2；或
      ② schema 里 `"action": {..., "enum": [a, b, ...]}` 且 ≥2。
    """
    out = {}
    for f in sorted(TOOLS_DIR.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        m = re.search(r'^\s*name\s*=\s*"([a-z_][a-z0-9_]*)"', src, re.M)
        if not m:
            continue
        acts = set()
        va = re.search(r"VALID_ACTIONS\s*=\s*[\{\[](.*?)[\}\]]", src, re.DOTALL)
        if va:
            acts |= set(re.findall(r'"([a-z_]+)"', va.group(1)))
        en = re.search(r'"action"\s*:\s*\{[^}]*?"enum"\s*:\s*\[([^\]]*)\]', src, re.DOTALL)
        if en:
            acts |= set(re.findall(r'"([a-z_]+)"', en.group(1)))
        if len(acts) >= 2:
            out[m.group(1)] = acts
    return out


class TestAssertionSpecsWellFormed:
    def _cases(self):
        return load_case_dicts(str(CASES_DIR))

    def test_arg_assertions_have_tool_and_fields(self):
        bad = []
        for c in self._cases():
            for field in ("forbidden_args", "required_args"):
                for i, s in enumerate(_specs(c, field)):
                    tool = str(s.get("tool") or "")
                    fields = s.get("fields") or []
                    if not tool:
                        bad.append(f"{c['id']}.{field}[{i}]: 缺 tool")
                    elif not fields:
                        bad.append(
                            f"{c['id']}.{field}[{i}]: 缺/空 fields —— 运行时会失败关闭"
                            f"（该断言退化为 no-op），请补 fields")
        assert not bad, "断言配置形状不合法：\n  " + "\n  ".join(bad)

    def test_must_succeed_has_tool(self):
        bad = [f"{c['id']}.must_succeed[{i}]: 缺 tool"
               for c in self._cases() for i, s in enumerate(_specs(c, "must_succeed"))
               if not str(s.get("tool") or "")]
        assert not bad, "must_succeed 缺 tool：\n  " + "\n  ".join(bad)

    def test_must_fail_has_tool_and_does_not_contradict(self):
        """`must_fail` 形状 + 与 `must_succeed` 互斥（同一工具既"必须成功"又"必须失败"
        = 用例永远不可能通过；issue #3544 收口批）。"""
        bad = []
        for c in self._cases():
            for i, s in enumerate(_specs(c, "must_fail")):
                tool = str(s.get("tool") or "")
                if not tool:
                    bad.append(f"{c['id']}.must_fail[{i}]: 缺 tool（运行时会失败关闭）")
            must_fail = {str(s.get("tool") or "") for s in _specs(c, "must_fail")}
            must_ok = {str(s.get("tool") or "") for s in _specs(c, "must_succeed")}
            for tool in sorted(must_fail & must_ok):
                bad.append(
                    f"{c['id']}: {tool} 同时出现在 must_fail 与 must_succeed"
                    f"—— 该用例永远不可能通过")
        assert not bad, "must_fail 配置不合法：\n  " + "\n  ".join(bad)

    def test_forbidden_tools_have_tool_and_do_not_contradict(self):
        """`forbidden_tools` 形状 + 自相矛盾检测（issue #3544 收口批）。

        ① 缺 tool 的条目运行时会失败关闭 → 左移到 PR 阶段；
        ② 同一工具既 `forbidden_tools`（全程禁用）又 `must_succeed`（必须成功）
        = 永远不可能通过的用例（配置错误）。
        """
        bad = []
        for c in self._cases():
            forbidden = set()
            for i, s in enumerate(_specs(c, "forbidden_tools")):
                tool = str(s.get("tool") or "")
                if not tool:
                    bad.append(f"{c['id']}.forbidden_tools[{i}]: 缺 tool（运行时会失败关闭）")
                    continue
                forbidden.add(tool)
            must = {str(s.get("tool") or "") for s in _specs(c, "must_succeed")}
            for tool in sorted(forbidden & must):
                bad.append(
                    f"{c['id']}: {tool} 同时出现在 forbidden_tools 与 must_succeed"
                    f"—— 该用例永远不可能通过")
        assert not bad, "forbidden_tools 配置不合法：\n  " + "\n  ".join(bad)

    def test_want_text_specs_have_text_or_any_of(self):
        """`want_text` 的 dict 形态（轮次/任一生效）必须给出 text 或 any_of（否则静默不检查）。"""
        bad = []
        for c in self._cases():
            for i, w in enumerate(c.get("want_text") or []):
                if isinstance(w, str):
                    continue
                if not isinstance(w, dict) or not (w.get("text") or w.get("any_of")):
                    bad.append(
                        f"{c['id']}.want_text[{i}]: {w!r} 既无 text 也无 any_of（会静默不检查）")
        assert not bad, "want_text 配置不合法：\n  " + "\n  ".join(bad)

    def test_forbidden_text_specs_have_text_or_any_of(self):
        """`forbidden_text` 的 dict 形态（轮次作用域 / 任一命中）必须给出 text 或 any_of。
        形态与 `want_text` 的同一格对称（issue #3833：轮次作用域是与 want_text 同构的新能力，
        空配置必须 **fail-closed**，不得静默不检查）。"""
        bad = []
        for c in self._cases():
            for i, w in enumerate(c.get("forbidden_text") or []):
                if isinstance(w, str):
                    continue
                if not isinstance(w, dict) or not (w.get("text") or w.get("any_of")):
                    bad.append(
                        f"{c['id']}.forbidden_text[{i}]: {w!r} 既无 text 也无 any_of（会静默不检查）")
        assert not bad, "forbidden_text 配置不合法：\n  " + "\n  ".join(bad)

    def test_forbidden_args_do_not_shadow_required_args(self):
        """同一工具同一字段不得既"必须"又"禁止"（自相矛盾的用例永远不可能通过）。"""
        bad = []
        for c in self._cases():
            req = {(str(s.get("tool") or ""), str(f))
                   for s in _specs(c, "required_args") for f in (s.get("fields") or [])}
            forb = {(str(s.get("tool") or ""), str(f))
                    for s in _specs(c, "forbidden_args") for f in (s.get("fields") or [])}
            for pair in sorted(req & forb):
                bad.append(f"{c['id']}: {pair[0]}.{pair[1]} 同时出现在 required_args 与 forbidden_args")
        assert not bad, "自相矛盾的断言配置：\n  " + "\n  ".join(bad)

    def test_verify_specs_supported(self):
        bad = []
        for c in self._cases():
            for i, s in enumerate(_specs(c, "db_verify")):
                fetch = s.get("fetch")
                if fetch not in SUPPORTED_DB_FETCH:
                    bad.append(f"{c['id']}.db_verify[{i}]: 不支持的 fetch={fetch!r}")
                if fetch == "product_by_name" and not s.get("name"):
                    bad.append(f"{c['id']}.db_verify[{i}]: product_by_name 缺 name")
                if fetch == "order_items" and not (s.get("expect_products") or s.get("expect_quantities")):
                    bad.append(f"{c['id']}.db_verify[{i}]: order_items 没有任何期望（空断言）")
                if fetch == "order_phone" and not s.get("expect_phone"):
                    # 空断言 = 声称核对了落库手机号、其实没核对（issue #3386 同族风险）
                    bad.append(f"{c['id']}.db_verify[{i}]: order_phone 缺 expect_phone（空断言）")
                if fetch == "after_sales_ticket" and not s.get("expect_status"):
                    # 同族：没有期望状态 → 核对器无从判定，只会退化成"查了一下"（#3544）
                    bad.append(
                        f"{c['id']}.db_verify[{i}]: after_sales_ticket 缺 expect_status"
                        f"（空断言 —— 运行时会失败关闭）")
                if fetch == "after_sales_ticket" and not (
                        s.get("expect_fields_nonempty") or s.get("expect_close_reason_contains")):
                    # 只断言状态、不核对关闭留痕 = 「关闭」用例最关键的 closedAt/closeReason 又没人查
                    bad.append(
                        f"{c['id']}.db_verify[{i}]: after_sales_ticket 既无 expect_fields_nonempty"
                        f" 也无 expect_close_reason_contains（关闭留痕无人核对）")
                if fetch == "employee":
                    if not (s.get("id") or s.get("name")):
                        bad.append(
                            f"{c['id']}.db_verify[{i}]: employee 缺 id/name（定位不到记录）")
                    if not isinstance(s.get("expect_fields"), dict) or not s.get("expect_fields"):
                        bad.append(
                            f"{c['id']}.db_verify[{i}]: employee 缺/空 expect_fields"
                            f"（空断言 —— 运行时会失败关闭）")
                if fetch == "processing_order":
                    if not (s.get("checks") or s.get("keyword")):
                        bad.append(
                            f"{c['id']}.db_verify[{i}]: processing_order 缺 checks"
                            f"（空断言 —— 运行时会失败关闭）")
                if fetch == "employee_absent":
                    # 负效果断言同样必须**能定位对象**：缺 id/name/phone ⇒ 查不到任何东西
                    # ⇒ 恒判"不存在"= 永远绿的空断言（issue #4108，与 employee 同族）。
                    if not (s.get("id") or s.get("name") or s.get("phone")):
                        bad.append(
                            f"{c['id']}.db_verify[{i}]: employee_absent 缺 id/name/phone"
                            f"（定位不到对象 ⇒ 断言永远绿）")
            for i, s in enumerate(_specs(c, "post_session")):
                if s.get("fetch") not in SUPPORTED_POST_SESSION_FETCH:
                    bad.append(f"{c['id']}.post_session[{i}]: 不支持的 fetch={s.get('fetch')!r}")
            for i, s in enumerate(_specs(c, "output_verify")):
                if not str(s.get("tool") or ""):
                    bad.append(f"{c['id']}.output_verify[{i}]: 缺 tool")
                elif not isinstance(s.get("expect"), dict) or not s.get("expect"):
                    bad.append(f"{c['id']}.output_verify[{i}]: 缺/空 expect（空断言）")
            for i, s in enumerate(_specs(c, "form_prefill")):
                if not str(s.get("field") or ""):
                    bad.append(f"{c['id']}.form_prefill[{i}]: 缺 field（空断言）")
                elif (s.get("expect") is None and not s.get("expect_present")):
                    bad.append(
                        f"{c['id']}.form_prefill[{i}]: 既无 expect 也无 expect_present"
                        f"（空断言 —— 声称核对了预填值，其实没核对）")
            for i, s in enumerate(_specs(c, "forbidden_card_text")):
                # 两种写法都支持：`{text: "用量"}` 与裸字符串 `"用量"`
                # （`_specs` 会把裸字符串包成 `{"tool": ...}`，故这里也认 tool 键）
                t = str(s.get("text") or s.get("tool") or "") if isinstance(s, dict) else str(s or "")
                if not t:
                    bad.append(f"{c['id']}.forbidden_card_text[{i}]: 空配置（会静默不检查）")
            for i, s in enumerate(_specs(c, "amount_verify")):
                checks = s.get("checks")
                if checks is None:
                    continue
                if not isinstance(checks, list):
                    bad.append(f"{c['id']}.amount_verify[{i}]: checks 必须解析成列表，实际 {type(checks).__name__}")
                elif "unit_price" in checks and not s.get("product_name"):
                    bad.append(f"{c['id']}.amount_verify[{i}]: 检查 unit_price 但没有 product_name（取不到真值）")
        assert not bad, "落库/金额断言配置不合法：\n  " + "\n  ".join(bad)


class TestOutputVerifyActionScope:
    """`output_verify` 指向**多 action 工具**时必须显式声明 `action`（L0 不变式，issue #3544）。

    实证（run 34809483940，PP-006）：`processing_item_manage` 是 9 个 action 的工具，
    同一会话里 R2 的 `list_categories` 先成功 → runner 按**工具名**取到它的 payload
    `{'categories': [...]}` → 去核对 `name`/`pricingMethod` **必然假红**（真建成功的 R5
    payload 从未被核对）；反之若两个 action 的 payload 字段名相撞就会**假绿**。
    这条不变式把「必须声明作用域」左移到 PR 阶段的零成本 job，第 N 次复发不可能。
    """

    def _cases(self):
        return load_case_dicts(str(CASES_DIR))

    def test_multi_action_tools_detected(self):
        """检测器自证：已知多 action 工具必须被认出来（防解析失效 → 守卫恒真）。"""
        multi = _multi_action_tools()
        assert len(multi) >= 8, f"只解析出 {len(multi)} 个多 action 工具 —— 解析疑似失效"
        for name in ("processing_item_manage", "employee_manage", "product_manage",
                     "after_sales_manage", "category_manage"):
            assert name in multi, f"{name} 未被识别为多 action 工具（检测器漏了）"
        # 单 action 工具不得误判（防过度收紧：PR-024 curtain_calc / PR-021 sku_update）
        for name in ("curtain_calc", "sku_update"):
            assert name not in multi, f"{name} 被误判为多 action 工具"

    def test_output_verify_on_multi_action_tool_declares_action(self):
        multi = _multi_action_tools()
        bad = []
        for c in self._cases():
            for i, s in enumerate(_specs(c, "output_verify")):
                tool = str(s.get("tool") or "")
                if tool not in multi:
                    continue
                action = s.get("action")
                if not action:
                    bad.append(
                        f"{c['id']}.output_verify[{i}]: {tool} 是多 action 工具"
                        f"（{len(multi[tool])} 个动作）但未声明 action —— "
                        f"会核对到别的 action 的 payload（假红/假绿双面缺陷，issue #3544）")
                elif str(action) not in multi[tool]:
                    bad.append(
                        f"{c['id']}.output_verify[{i}]: {tool}.action={action!r} 不在该工具的动作集"
                        f"{sorted(multi[tool])}（拼写错误 → 永远取不到 payload = 假红）")
        assert not bad, "output_verify 作用域不合法：\n  " + "\n  ".join(bad)


# ── 断言词汇表审计（issue #3417 复盘）────────────────────────────────────────────
# 词汇表单一源 = 生成物 `EvalCase` 的字段（渲染器/装载器/守卫三方都以它为准）
META_FIELDS = {
    "id", "title", "skill", "difficulty", "user_inputs", "expectations",
    "data_checks", "skip_reason", "legacy_id", "tags", "persona",
}

# 允许"暂时无用例使用"的断言字段 → 必须写明**为什么保留**（空理由/理由过短即红）。
# 这不是白名单豁免，而是把"实现了却没人用"变成**显式决定**。
UNUSED_ALLOWED = {
    # `must_fail` 原在此表（「零成功调用」断言，期待 OR-026 接线）。**2026-09-18 移除**：
    # 第一条消费者已落地 —— OR-030（`.github/cases/order.yml`，S2 #4073 的 B 端拒绝半）
    # 用 `must_fail: [{tool: order_create, args: {customer_phone: "05718886666"}}]` 咬住
    # 「非法号码不得落单」的参数值级不变量（值级作用域由 #3689 落地）。
    # 按本表自己的规则（`test_allowlisted_field_is_still_unused`：字段一旦被用上就必须移出）
    # 删除，不做"过期豁免"。
    "form_prefill": (
        "老客户收货信息预填的**机制级**断言（issue #3397）。目前 C 端两处覆盖都刻意走"
        "产出侧（OR-023 断言订单落库地址、CH-025 断言修改后门牌，见 #3404 复盘："
        "把用例绑死在『必须发 form 卡』上会造假红），预填的**逐字保真**另由图谱守卫"
        "`_form_prefill_fidelity_block` 结构性保证。保留该断言是为了将来需要"
        "『明确要求发 form 卡』的用例（如卡字段被改写/掩码回流）能直接用。"
    ),
}


def _assertion_vocabulary():
    """从生成物 dataclass 解析断言字段（单一源）"""
    import ast
    src = (REPO_ROOT / "tests" / "agent_eval" / "eval_cases.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.ClassDef) and node.name == "EvalCase":
            return [s.target.id for s in node.body
                    if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
    raise AssertionError("eval_cases.py 里找不到 EvalCase dataclass —— 解析失效")


class TestAssertionVocabularyIsExercised:
    """断言类型不能是**死的**：实现了却没有任何用例使用 = 「声称查过而其实没查」。

    实证（issue #3417 复盘）：`form_prefill`（#3397 实现、有单测、装载器也映射）
    在 273 条用例里**零使用** —— 覆盖缺口不会报错、不会红灯，就那么静默存在。
    本守卫把这类"死断言"变成红灯（或 ALLOWLIST 里的显式决定）。
    """

    def _cases(self):
        return load_case_dicts(str(CASES_DIR))

    def test_vocabulary_is_non_trivial(self):
        vocab = [f for f in _assertion_vocabulary() if f not in META_FIELDS]
        assert len(vocab) >= 10, (
            f"只解析出 {len(vocab)} 个断言字段 —— 词汇表解析疑似失效（守卫会变成恒真断言）"
        )

    def test_every_assertion_field_is_used_or_allowlisted(self):
        cases = self._cases()
        dead = []
        for field in _assertion_vocabulary():
            if field in META_FIELDS:
                continue
            used = [c["id"] for c in cases if c.get(field) not in (None, "", [], {})]
            if used:
                continue
            if field in UNUSED_ALLOWED:
                continue
            dead.append(field)
        assert not dead, (
            "以下断言字段**没有任何用例使用**（实现了却没查过任何东西）：\n  "
            + "\n  ".join(dead)
            + "\n要么补用例真正使用它，要么加进 UNUSED_ALLOWED 并写明保留理由。"
        )

    def test_allowlist_entries_are_justified_and_alive(self):
        """ALLOWLIST 不是垃圾桶：理由必须充分，且字段必须仍然存在。"""
        vocab = set(_assertion_vocabulary())
        for field, reason in UNUSED_ALLOWED.items():
            assert field in vocab, f"UNUSED_ALLOWED 里的 {field} 已不存在于词汇表（清理掉）"
            assert field not in META_FIELDS, f"{field} 已变成元数据字段（清理 ALLOWLIST）"
            assert len(reason.strip()) >= 30, (
                f"{field} 的保留理由过短（{reason!r}）—— 允许「没用例用」必须有充分理由"
            )

    def test_allowlisted_field_is_still_unused(self):
        """反向守卫：ALLOWLIST 里的字段一旦被用例用上，就该从 ALLOWLIST 移除（防止过期豁免）。"""
        cases = self._cases()
        stale = [f for f in UNUSED_ALLOWED
                 if any(c.get(f) not in (None, "", [], {}) for c in cases)]
        assert not stale, (
            f"这些字段已有用例使用，却还挂在 UNUSED_ALLOWED 里：{stale} —— 请移除以保持豁免表真实"
        )
