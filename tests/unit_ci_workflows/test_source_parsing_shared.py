# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 `_migration_paths.py` / `test_agent_permission_parity.py` 的同款声明。本 PR 不新建用例族。）
"""共享解析器 `tests/unit_ci_workflows/_source_parsing.py` 的**成对红证**（issue #5323 收口包）。

七个调用点（`test_assertion_specs_wellformed` / `test_eval_case_asset_truth` /
`test_eval_debug_permissions_precondition` / `test_eval_product_name_pollution` /
`test_craft_calc_config_contract` / `test_agent_permission_parity` /
`test_mixed_color_surcharge_cross_side`）各自带自己的成对红证；**本文件钉的是共享实现本身**
的三条不可让步的性质 —— 它们一旦退化，所有调用点**同时**失守，而在各自的文件里看不出来：

| 性质 | 为什么必须单独钉 |
|---|---|
| Python 侧只认 **AST 字面量** | 注释 / 文档字符串**不是** AST 节点 —— 这是「不可能被读成声明」的结构保证 |
| Java 侧**引号感知** | 字符串里的 `//`（`"http://x"`）不得被当成注释起点；注释里的字面量不得被读出 |
| Python 剥注释走 **tokenize** | 字符串里的 `#`（`"#FF0000"`）不得吃掉行尾（`#5323` 第 7 条，方向是**漏检**） |

⚠️ **本文件不得出现取值型正则调用**：它在判据面内，元守卫
`test_guard_parsing_is_comment_aware.py` 按 **pattern 形态**判（不看它被套在什么文本上）。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# append（**不是** insert）：只作脚本模式的兜底解析路径，避免遮蔽同名模块（与 conftest 同款理由）。
sys.path.append(str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import (  # noqa: E402
    assigned_mapping_keys,
    assigned_strings,
    code_without_comments,
    declared_strings,
    java_code,
    java_literals,
    nested_string_members,
)


class TestPythonSideReadsAstLiteralsOnly:
    """Python 侧：`ast` 读字面量声明 —— 注释 / 文档字符串 / 字符串都不算声明。"""

    #: **陷阱语料**：同一批「看起来像声明」的值只出现在注释与文档字符串里（**代码零改动**）。
    TRAPPED = (
        '# VALID_ACTIONS = {"ghost_a", "ghost_b"}  ← 留档注释（这不是声明）\n'
        '"""示例（说明文字，不是代码）：\n'
        'VALID_ACTIONS = {"ghost_a", "ghost_b"}\n'
        'parameters = {"properties": {"action": {"enum": ["ghost_a", "ghost_b"]}}}\n'
        '"""\n'
        'VALID_ACTIONS = {"list", "detail"}\n'
    )

    def test_comment_and_docstring_are_not_declarations(self):
        """负例：注释 / 文档字符串里的同形文本 ⇒ **不得**被读成集合成员。"""
        assert assigned_strings(self.TRAPPED, "VALID_ACTIONS", "fixture") == ("list", "detail")

    def test_declared_strings_ignores_text_mentions(self):
        """类属性式声明（工具 `name = "…"`）同样只认代码：文本里提一句不算。"""
        src = (
            '"""示例：name = "ghost_tool"\n"""\n'
            '# name = "ghost_tool"\n'
            "class T:\n"
            '    name = "demo_tool"\n'
        )
        assert declared_strings(src, "name", "fixture") == ("demo_tool",)

    def test_set_list_tuple_and_wrapper_are_all_read(self):
        """正例（防修过头）：四种**真**声明形态都读到；未声明 ⇒ 空元组（调用方自行 fail-closed）。"""
        assert assigned_strings('VALID_ACTIONS = {"a", "b"}\n', "VALID_ACTIONS", "f") == ("a", "b")
        assert assigned_strings('VALID_ACTIONS = ["a", "b"]\n', "VALID_ACTIONS", "f") == ("a", "b")
        assert assigned_strings('VALID_ACTIONS = ("a", "b")\n', "VALID_ACTIONS", "f") == ("a", "b")
        assert assigned_strings('VALID_ACTIONS = frozenset({"a", "b"})\n', "VALID_ACTIONS", "f") == (
            "a", "b")
        assert assigned_strings("x = 1\n", "VALID_ACTIONS", "f") == ()

    def test_mapping_keys_come_from_the_dict_not_from_comments(self):
        """`#5323` 第 3 条（**涉钱面**）：dict 注释里的键不是键（旧口径会读成「引擎有该键」）。"""
        src = (
            '# "ghost_key": 1,  ← 留档注释：该键已弃用\n'
            "CFG: MappingProxyType = MappingProxyType({\n"
            '    "per_fold_single": 2.0,\n'
            '    "tiers": 1,\n'
            "})\n"
        )
        assert assigned_mapping_keys(src, "CFG", "fixture") == ("per_fold_single", "tiers")

    def test_nested_enum_path_is_structural(self):
        """schema 枚举按 `parameters.properties.action.enum` **下钻**：别处的 `"enum"` 不算。"""
        src = (
            "class T:\n"
            '    other = {"enum": ["ghost_a"]}\n'
            '    parameters = {"properties": {"action": {"enum": ["list", "detail"]}}}\n'
        )
        path = ("properties", "action", "enum")
        assert nested_string_members(src, "parameters", path, "f") == ("list", "detail")
        assert nested_string_members(src, "other", ("enum",), "f") == ("ghost_a",)
        assert nested_string_members(src, "parameters", ("properties", "missing"), "f") == ()

    def test_enum_may_point_at_a_declared_name(self):
        """`"enum": list(VALID_ACTIONS)`（**真源**里的写法）⇒ 一层名字回指解析到真声明。"""
        src = (
            'VALID_ACTIONS = ("batches", "distribution")\n'
            "class T:\n"
            '    parameters = {"properties": {"action": {"enum": list(VALID_ACTIONS)}}}\n'
        )
        assert nested_string_members(src, "parameters", ("properties", "action", "enum"), "f") == (
            "batches", "distribution")


class TestJavaSideIsQuoteAware:
    """Java 侧：**引号感知**的词法走查（剥注释与取字面量共用同一份走查）。"""

    def test_slash_slash_inside_a_string_is_not_a_comment(self):
        """字符串里的 `//` 不得被当成注释起点（旧口径会把该行后半截一起吃掉）。"""
        src = 'String u = "http://x/y"; // 注释\nint a = 1; /* b */ int b = 2;\n'
        code = java_code(src)
        assert '"http://x/y"' in code, f"字符串里的 `//` 被当成注释截断了：{code!r}"
        assert "注释" not in code
        assert "/* b */" not in code
        assert "int b = 2;" in code
        assert code.count("\n") == src.count("\n"), "剥注释改变了行数（报错定位会漂）"

    def test_literals_exclude_comments_and_keep_strings(self):
        """负例 + 正例：注释里的字面量不算；代码里的字面量逐个交出（含带 `//` 的字符串）。"""
        src = (
            '    // static final List<String> KEYS = List.of("ghost_key");\n'
            '    static final List<String> KEYS = List.of("a", "b");\n'
            '    String u = "http://x";\n'
        )
        values = [value for _pos, value in java_literals(src)]
        assert values == ["a", "b", "http://x"], values

    def test_positions_let_callers_scope_a_literal(self):
        """`(起点下标, 值)` 让调用方按**前缀**归属字面量（`config.put("k", …)` 就靠它取值）。"""
        body = ' config.put("per_fold_single", a); other("not_a_key", b);\n'
        keys = [value for pos, value in java_literals(body)
                if body[:pos].rstrip().endswith("config.put(")]
        assert keys == ["per_fold_single"], keys

    def test_unterminated_string_does_not_crash(self):
        """未闭合引号 ⇒ 不抛错（词法走查取到文末为止），余下代码也不被当注释吞掉。"""
        src = 'String s = "oops;\nint a = 1;\n'
        assert "int a = 1;" in java_code(src)

    def test_char_literal_slash_is_not_a_comment(self):
        """字符字面量 `'/'` 不得被当成注释起点（Java 里 `'//'` 不是注释）。"""
        src = "char c = '/'; // 注释\nint a = 1;\n"
        assert "int a = 1;" in java_code(src)
        assert "注释" not in java_code(src)


class TestPythonCommentRemovalIsLexical:
    """`#5323` 第 7 条：`tokenize` 只丢 `COMMENT`、**保留** `STRING`。"""

    def test_hash_inside_a_string_does_not_eat_the_line(self):
        """**防假绿**：字符串里的 `#` ⇒ 同一行后面的断言必须仍在（旧口径会截到行尾）。"""
        src = 'q = {"hex": "#FF0000"}; assert q["s"] == 81.84  # 期望值\n'
        stripped = code_without_comments(src, "fixture")
        assert 'assert q["s"] == 81.84' in stripped, f"字符串里的 `#` 吃掉了行尾：{stripped!r}"
        assert "期望值" not in stripped, "行尾注释没有被剥掉"
        assert "#FF0000" in stripped, "字符串内容被清空了 ⇒ 判据失去被测对象（要读的正是字符串里的断言形态）"

    def test_comment_is_removed_and_lines_are_preserved(self):
        """整行注释与行尾注释都剥掉；行数不变（报错定位照旧可用）。"""
        src = "# 整行注释\nx = 1  # 行尾注释\n"
        stripped = code_without_comments(src, "fixture")
        assert "注释" not in stripped
        assert "x = 1" in stripped
        assert stripped.count("\n") == src.count("\n")

    def test_docstrings_are_kept_as_strings(self):
        """文档字符串是 `STRING`（**不是**注释）⇒ 保留 —— 这是本单指定的修法（残余见 PR body）。"""
        assert "81.84" in code_without_comments('"""doc\n81.84\n"""\nx = 1\n', "fixture")

    def test_untokenizable_text_fails_closed(self):
        """不可 tokenize 的文本 ⇒ 显式报错（不许静默返回原文，让判据以为「已经剥过了」）。

        ⚠️ 残余（照实登记）：`tokenize` 只在真报错时才算失败 —— 本机 Python 对「未闭合的
        **单引号**字符串」不报错（词法器宽容）⇒ 那种文本会走 `TokenError` 之外的分支。
        判据面传进来的是**合法 Python 源码**，故不影响本轮收口的 7 个调用点。
        """
        try:
            code_without_comments("y = (\n", "fixture")
        except AssertionError as exc:
            assert "无法 tokenize" in str(exc), str(exc)
            return
        raise AssertionError("不可 tokenize 的文本没有 fail-closed（静默返回了原文）")