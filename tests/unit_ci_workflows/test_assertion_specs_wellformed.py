# case_ids: OR-012, OR-014, OR-017, OR-018, CH-010, CH-011, DF-020, OR-023
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
            for i, s in enumerate(_specs(c, "amount_verify")):
                checks = s.get("checks")
                if checks is None:
                    continue
                if not isinstance(checks, list):
                    bad.append(f"{c['id']}.amount_verify[{i}]: checks 必须解析成列表，实际 {type(checks).__name__}")
                elif "unit_price" in checks and not s.get("product_name"):
                    bad.append(f"{c['id']}.amount_verify[{i}]: 检查 unit_price 但没有 product_name（取不到真值）")
        assert not bad, "落库/金额断言配置不合法：\n  " + "\n  ".join(bad)
