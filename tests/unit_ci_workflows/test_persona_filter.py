"""
Test eval-case persona attribution filter (issue #2855).

背景：米宝（mibao，B 端）full 回归误报 —— 一批 C 端专属用例（转人工 human_handoff /
customer_order_query / customer_logistics_track 等仅注册于小布 customer_* skill）
在 PERSONA=mibao 下必然失败，污染 B 端回归信号。
修复：cases/*.yml 支持 persona 字段（mibao/xiaobu/""双端），render 透传 +
local_runner 按 persona 过滤（mibao 跳过 xiaobu 专属，反之亦然）。
"""
# case_ids: CH-008, CH-012, CH-013, CH-014, CH-015, CH-017, OR-012, ST-008
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

from render_cases import filter_by_persona, load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"

# 已标记 persona: xiaobu 的 C 端专属用例（issue #2855 修复对象）
XIAOBU_ONLY = {"CH-008", "CH-012", "CH-013", "CH-014", "CH-015", "CH-017", "OR-012", "ST-008"}


def _all_cases():
    return load_case_dicts(str(CASES_DIR))


class TestPersonaFieldInCases:
    """cases/*.yml 的 persona 字段声明正确性"""

    def test_xiaobu_only_cases_marked(self):
        by_id = {c["id"]: c for c in _all_cases()}
        for cid in XIAOBU_ONLY:
            assert cid in by_id, f"用例 {cid} 不存在于 cases/"
            assert by_id[cid].get("persona") == "xiaobu", f"{cid} 应标记 persona: xiaobu"

    def test_default_persona_is_both(self):
        by_id = {c["id"]: c for c in _all_cases()}
        # 未标记 persona 的用例（如米宝核心 OR-001）缺省为双端
        assert by_id["OR-001"].get("persona", "") in ("", "mibao", "both")


class TestFilterByPersona:
    """filter_by_persona 的过滤语义"""

    def test_mibao_excludes_xiaobu_only(self):
        cases = _all_cases()
        kept = {c["id"] for c in filter_by_persona(cases, "mibao")}
        assert XIAOBU_ONLY.isdisjoint(kept), "mibao 不应包含 C 端专属用例"
        assert "OR-001" in kept, "mibao 应保留双端用例"

    def test_xiaobu_keeps_xiaobu_only(self):
        cases = _all_cases()
        kept = {c["id"] for c in filter_by_persona(cases, "xiaobu")}
        assert XIAOBU_ONLY.issubset(kept), "xiaobu 应保留 C 端专属用例"

    def test_unknown_persona_keeps_all(self):
        cases = _all_cases()
        assert len(filter_by_persona(cases, "")) == len(cases)
        assert len(filter_by_persona(cases, "supply_chain")) == len(cases)

    def test_accepts_evalcase_objects(self):
        """local_runner 传入 EvalCase 对象（有 .persona 属性）时同样生效"""
        from dataclasses import dataclass

        @dataclass
        class FakeCase:
            id: str
            persona: str = ""

        items = [FakeCase("A-001", ""), FakeCase("B-001", "xiaobu"), FakeCase("C-001", "mibao")]
        mibao_kept = {c.id for c in filter_by_persona(items, "mibao")}
        assert mibao_kept == {"A-001", "C-001"}
        xiaobu_kept = {c.id for c in filter_by_persona(items, "xiaobu")}
        assert xiaobu_kept == {"A-001", "B-001"}


class TestGeneratedArtifact:
    """eval_cases.py 生成物透传 persona（禁手写，源头一致）"""

    def test_generated_has_persona_field(self):
        eval_py = (REPO_ROOT / "tests" / "agent_eval" / "eval_cases.py").read_text(encoding="utf-8")
        assert "persona: str = \"\"" in eval_py, "EvalCase dataclass 应含 persona 字段"
        assert eval_py.count("persona='xiaobu'") == len(XIAOBU_ONLY), \
            "生成物应包含 8 条 xiaobu 专属用例的 persona 声明"
