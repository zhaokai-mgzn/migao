"""加工项 choice 卡 multiSelect 自动补齐纯函数单测（模式 C 代码兜底，PR-014/015）。

背景：prompt 已写「加工项选择必须 multiSelect=true」，但 LLM 仍漏传（🧬不稳定），
加工项选择器退化成单选，多选流程断裂。设计标准 §3「改 3 次 prompt 修不好 → 代码管」。
"""
# case_ids: PR-014, PR-015, PR-016
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MOD_PATH = REPO_ROOT / "app" / "graph" / "skills" / "base_skill.py"

spec = importlib.util.spec_from_file_location("base_skill_mod", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestIsProcessingItemsCard:
    def test_title_contains_processing(self):
        assert mod._is_processing_items_card({"title": "请选择加工项"}) is True

    def test_option_value_proc_item(self):
        args = {"title": "请选择", "options": [{"label": "打孔", "value": "proc_item_hole"}]}
        assert mod._is_processing_items_card(args) is True

    def test_ordinary_card_not_processing(self):
        args = {"title": "请选择售卖方式", "options": [{"label": "散剪", "value": "bulk_cut"}]}
        assert mod._is_processing_items_card(args) is False

    def test_empty_args(self):
        assert mod._is_processing_items_card({}) is False


class TestEnsureProcessingItemsMultiselect:
    def test_non_interact_tool_untouched(self):
        args = {"action": "list"}
        assert mod._ensure_processing_items_multiselect("order_query", args) == args

    def test_non_choice_component_untouched(self):
        args = {"component": "confirm", "title": "确认创建"}
        assert mod._ensure_processing_items_multiselect("interact", args) == args

    def test_already_multiselect_untouched(self):
        args = {"component": "choice", "title": "选加工项", "multiSelect": True}
        out = mod._ensure_processing_items_multiselect("interact", args)
        assert out is args  # 原对象不变

    def test_processing_card_missing_multiselect_auto_filled(self):
        args = {"component": "choice", "title": "请选择加工项",
                "options": [{"label": "打孔", "value": "proc_item_hole"}]}
        out = mod._ensure_processing_items_multiselect("interact", args)
        assert out["multiSelect"] is True
        # 原 args 不被修改（返回新 dict）
        assert "multiSelect" not in args

    def test_ordinary_card_missing_multiselect_not_filled(self):
        args = {"component": "choice", "title": "选售卖方式",
                "options": [{"label": "散剪", "value": "bulk_cut"}]}
        out = mod._ensure_processing_items_multiselect("interact", args)
        assert "multiSelect" not in out
