# case_ids: MC-269
"""`chat.py` 切片的结构守卫（类级固化，issue #8725 第三档）。

## 为什么需要它

behavior 判据（`test_chat_slice_characterization.py`）只回答"输出有没有变"；它回答不了
**"搬走的代码是不是只有一个家"**。而这类漂移恰恰是切片最常见的回归形态：

- 有人把 `_should_send_card` 又抄回 `chat.py`（两份实现 ⇒ 迟早分叉），behavior 判据**照样全绿**
  （调用点走哪份都能得到同样输出，直到某次只改了一份）；
- 有人在切片面里多放一个 `chat_xxx.py`（未登记的单元 ⇒ 没有主、没有唯一职责，也不会被任何判据约束）；
- 有人让单元反向 import `chat.py`（循环依赖；本地 import 成功、生产装配顺序变化时炸）；
- 有人把某个符号从 re-export 列表里删掉（外部 `from app.api.chat import ...` 与
  `patch("app.api.chat.<name>")` 一起静默失效 —— **patch 失效不会报错**，只会让断言变成空跑）。

## 判据（六条，全部"未登记即红"）

1. 切片面的文件集合**正好**是登记的那 4 个单元 + 入口 `chat.py`（多一个/少一个都红）；
2. 每个登记符号在**登记的单元**里恰好定义 1 次；
3. `chat.py` **一处都不许**再定义它们（只许 re-export）；
4. `chat.py` 的 re-export 列表 == 登记符号全集（少一个 ⇒ 外部 import 面破，多一个 ⇒ 登记漂移）；
5. 单元**不得**反向 import `app.api.chat`（含相对形式）—— 依赖方向单向；
6. 每个单元有非空模块 docstring 且写明「单一职责」，行数 < 800（与 LOC 棘轮的 `new_file` 线上限一致）。
"""

from __future__ import annotations

import ast
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
API_DIR = SERVICE_ROOT / "app" / "api"
ENTRY = API_DIR / "chat.py"

#: 切片面登记表（唯一真值源：本表）。键 = 单元文件，值 = 它独占的顶层符号。
SLICE_UNITS: dict[str, tuple[str, ...]] = {
    "chat_profiles.py": (
        "_get_user_nickname", "_get_tenant_name", "_generate_title_async",
        "_extract_memories_async",
    ),
    "chat_history.py": (
        "PERSIST_FAILED_MARK", "_CODE_DEFECT_EXCS", "_PERSIST_SUGGESTION",
        "_report_persist_failure", "_save_message_or_report",
        "_history_user_text", "_is_legacy_proactive_tip_row", "_format_datetime",
        "_guard_session", "_raise_session_error", "_convert_history_to_agent_format",
    ),
    "chat_outbound.py": (
        "_detect_card_type", "_should_send_card", "_normalize_order_card_data",
        "_card_payload", "_mask_for_customer", "_sanitize_outbound_text",
        "_mask_card_for_customer", "_CARD_ACTION_WORDS", "_CARD_NOUNS",
        "_CARD_WIDGET_NOUNS", "_CARD_DELIVERED_VERBS", "_CARD_ACTION_GAP",
        "_CARD_POINT_RE", "_CARD_GESTURE_RE", "_CARD_ACTION_RE", "_CARD_DELIVERED_RE",
        "_CARD_DELIVERED_CONFIRM_RE", "_CARD_GUARD_RE", "_CARD_CLAIM_RE",
        "_CARD_MISLEAD_RE", "_has_card_claim", "_rewrite_card_claims",
    ),
    "chat_interact.py": (
        "_INTERACT_XML_RE", "_extract_tag_value", "_extract_tags",
        "_parse_interact_xml", "_strip_interact_xml",
        "_parse_interact_block_or_report", "_filter_products_by_reference",
    ),
}

ALL_SYMBOLS = tuple(sorted(s for symbols in SLICE_UNITS.values() for s in symbols))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _defined_names(tree: ast.Module) -> list[str]:
    """顶层定义（函数 / 类 / 赋值目标）的符号名 —— 只看定义，不看 import。"""
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return names


def _reexported_from_units(tree: ast.Module) -> dict[str, str]:
    """`chat.py` 里 `from app.api.chat_* import ...` 的 {符号: 来源模块} 映射。"""
    mapping: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.api.chat_"):
            for alias in node.names:
                mapping[alias.asname or alias.name] = node.module
    return mapping


def _imported_modules(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.add("." * node.level + (node.module or ""))
            elif node.module:
                found.add(node.module)
    return found


class TestSliceSurfaceIsExactlyRegistered:
    def test_unit_file_set_is_exactly_the_registry_plus_the_entry(self):
        on_disk = sorted(p.name for p in API_DIR.glob("chat_*.py"))
        assert on_disk == sorted(SLICE_UNITS), (
            f"切片面文件集合漂移（未登记即红）：磁盘 {on_disk} vs 登记 {sorted(SLICE_UNITS)}")
        assert ENTRY.name == "chat.py" and ENTRY.is_file(), "入口 chat.py 不在（切片面不成立）"

    def test_every_unit_is_imported_by_the_entry(self):
        reexport = _reexported_from_units(_parse(ENTRY))
        expected_modules = {f"app.api.{name[:-3]}" for name in SLICE_UNITS}
        assert set(reexport.values()) == expected_modules, (
            f"有单元没被入口使用（孤儿单元）：{sorted(expected_modules - set(reexport.values()))}")


class TestSymbolsHaveExactlyOneHome:
    def test_each_symbol_is_defined_once_in_its_registered_unit(self):
        problems: list[str] = []
        for unit, symbols in SLICE_UNITS.items():
            defined = _defined_names(_parse(API_DIR / unit))
            for symbol in symbols:
                count = defined.count(symbol)
                if count != 1:
                    problems.append(f"{unit}::{symbol} 定义 {count} 次（要求恰好 1）")
        assert problems == [], "切片单元的定义面漂移：\n" + "\n".join(problems)

    def test_entry_no_longer_defines_any_sliced_symbol(self):
        defined = set(_defined_names(_parse(ENTRY)))
        still = sorted(defined & set(ALL_SYMBOLS))
        assert still == [], (
            f"chat.py 又在定义已搬走的符号（出现第二份实现）：{still}")

    def test_symbols_are_not_defined_in_a_sibling_unit(self):
        problems: list[str] = []
        for unit, symbols in SLICE_UNITS.items():
            owners = {s: unit for s, u in SLICE_UNITS.items() for s in u}
            defined = _defined_names(_parse(API_DIR / unit))
            for symbol in defined:
                if symbol in owners and owners[symbol] != unit:
                    problems.append(f"{symbol} 应住 {owners[symbol]}，却在 {unit} 也定义")
        assert problems == [], "\n".join(problems)


class TestReexportSurfaceIsComplete:
    def test_entry_reexports_exactly_the_registered_symbols_from_the_right_units(self):
        reexport = _reexported_from_units(_parse(ENTRY))
        assert sorted(reexport) == list(ALL_SYMBOLS), (
            f"re-export 列表与登记不符：缺 {sorted(set(ALL_SYMBOLS) - set(reexport))} / "
            f"多 {sorted(set(reexport) - set(ALL_SYMBOLS))}")
        wrong = {
            symbol: module for symbol, module in reexport.items()
            if module != next(f"app.api.{u[:-3]}" for u, symbols in SLICE_UNITS.items()
                              if symbol in symbols)
        }
        assert wrong == {}, f"符号从错误的单元 re-export：{wrong}"

    def test_entry_keeps_every_symbol_reachable_as_a_module_attribute(self):
        """`from app.api.chat import X` 与 `patch("app.api.chat.X")` 都必须继续成立。"""
        import app.api.chat as entry

        missing = [s for s in ALL_SYMBOLS if not hasattr(entry, s)]
        assert missing == [], f"chat.py 命名空间里缺符号（外部 import / patch 会静默失效）：{missing}"


class TestDependencyDirectionIsOneWay:
    def test_units_never_import_the_entry(self):
        offenders: list[str] = []
        for unit in SLICE_UNITS:
            imported = _imported_modules(_parse(API_DIR / unit))
            for module in imported:
                if module in ("app.api.chat", ".chat", "..api.chat", "chat"):
                    offenders.append(f"{unit} → {module}")
        assert offenders == [], f"单元反向依赖入口（循环风险）：{offenders}"

    def test_units_only_import_known_layers(self):
        """单元只许依赖 app.* / 标准库 / 第三方 —— 不许 import 测试或脚本。"""
        offenders: list[str] = []
        for unit in SLICE_UNITS:
            for module in _imported_modules(_parse(API_DIR / unit)):
                if module.startswith(("tests", "scripts")):
                    offenders.append(f"{unit} → {module}")
        assert offenders == [], "单元依赖了测试/脚本面：" + ", ".join(offenders)


class TestUnitShape:
    def test_each_unit_declares_its_single_responsibility(self):
        problems: list[str] = []
        for unit in SLICE_UNITS:
            doc = ast.get_docstring(_parse(API_DIR / unit)) or ""
            if "单一职责" not in doc:
                problems.append(f"{unit} 模块头未声明「单一职责」")
            if len(doc) < 80:
                problems.append(f"{unit} 模块头太短（{len(doc)} 字符）—— 责任一句话不得是空串")
        assert problems == [], "\n".join(problems)

    def test_each_unit_stays_below_the_new_file_ratchet_line(self):
        oversized: list[str] = []
        for unit in SLICE_UNITS:
            lines = len((API_DIR / unit).read_text(encoding="utf-8").splitlines())
            if lines >= 800:
                oversized.append(f"{unit}={lines} 行")
        assert oversized == [], (
            "切片单元越过 800 行线（要么再切，要么按 loc_ratchet_exemptions 登记并说明）："
            + ", ".join(oversized))
