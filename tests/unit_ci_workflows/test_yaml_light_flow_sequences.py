# case_ids: OR-014, OR-017, OR-018
"""`yaml_light` 对 flow 序列/映射的解析（issue #3367）。

## 为什么必须有

`checks: [unit_price, subtotal, total]` 是 flow 序列。`yaml_light` 原先不解析它，
把整串当**字符串**存进渲染产物 → 运行时 `[str(x) for x in "<str>"]` 把它拆成**字符列表**
→ `"unit_price" in checks` 恒假 → **金额断言三项全被跳过、恒通过**。

后果有多严重：OR-014/OR-017 一直"带金额断言"，而线上一个数都没核对过。
我为此写的单测传的是 Python 列表，所以单测全绿 —— 典型的"工具自证"盲区
（单测测的是我以为的输入，不是渲染器真给的输入）。

本测试把两层都锁住：
  1. 解析层：flow 序列/映射必须解析成 list/dict；
  2. 产物层：渲染出的 `eval_cases.py` 里 `checks` 必须是**列表字面量**（不是字符串）。
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

from yaml_light import load as yl_load  # noqa: E402

EVAL_PY = REPO_ROOT / "tests" / "agent_eval" / "eval_cases.py"


class TestFlowSequences:
    def _parse(self, text):
        return yl_load(text)

    def test_flow_sequence_of_scalars(self):
        doc = self._parse("k:\n  - checks: [unit_price, subtotal, total]\n")
        assert doc["k"][0]["checks"] == ["unit_price", "subtotal", "total"]

    def test_empty_flow_sequence(self):
        assert self._parse("k: []\n")["k"] == []

    def test_flow_sequence_of_quoted_strings(self):
        doc = self._parse('k: ["夏日清风窗帘", "遮光窗帘"]\n')
        assert doc["k"] == ["夏日清风窗帘", "遮光窗帘"]

    def test_flow_mapping(self):
        doc = self._parse("k: {夏日清风窗帘: 3, 遮光窗帘: 2}\n")
        assert doc["k"] == {"夏日清风窗帘": 3, "遮光窗帘": 2}

    def test_plain_scalar_unaffected(self):
        assert self._parse("k: hello\n")["k"] == "hello"
        assert self._parse("k: 3\n")["k"] == 3


class TestRenderedAmountChecksAreLists:
    def test_amount_verify_checks_are_python_lists(self):
        """产物层守卫：`checks` 若是字符串，金额断言就会静默失效（本轮实证）。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("ec_guard", EVAL_PY)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        bad = []
        for c in m.ALL_CASES:
            for av in (getattr(c, "amount_verify", None) or []):
                if not isinstance(av, dict):
                    continue
                checks = av.get("checks")
                if checks is not None and not isinstance(checks, list):
                    bad.append(f"{c.id}: checks={checks!r}（应为列表）")
        assert not bad, (
            "渲染产物的 amount_verify.checks 不是列表 → 金额断言会被静默跳过：\n  "
            + "\n  ".join(bad)
        )

    def test_db_verify_expect_products_are_lists(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ec_guard2", EVAL_PY)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        bad = []
        for c in m.ALL_CASES:
            for dv in (getattr(c, "db_verify", None) or []):
                if isinstance(dv, dict) and "expect_products" in dv:
                    if not isinstance(dv["expect_products"], list):
                        bad.append(f"{c.id}: expect_products={dv['expect_products']!r}")
        assert not bad, f"db_verify.expect_products 非列表：{bad}"
