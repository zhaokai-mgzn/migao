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
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"

SUPPORTED_DB_FETCH = {"product_by_name", "order_items", "order_phone"}
SUPPORTED_POST_SESSION_FETCH = {"user_memories"}


def _specs(case, field):
    for s in case.get(field) or []:
        yield s if isinstance(s, dict) else {"tool": s}


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


# ── 断言词汇表审计（issue #3417 复盘）────────────────────────────────────────────
# 词汇表单一源 = 生成物 `EvalCase` 的字段（渲染器/装载器/守卫三方都以它为准）
META_FIELDS = {
    "id", "title", "skill", "difficulty", "user_inputs", "expectations",
    "data_checks", "skip_reason", "legacy_id", "tags", "persona",
}

# 允许"暂时无用例使用"的断言字段 → 必须写明**为什么保留**（空理由/理由过短即红）。
# 这不是白名单豁免，而是把"实现了却没人用"变成**显式决定**。
UNUSED_ALLOWED = {
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
