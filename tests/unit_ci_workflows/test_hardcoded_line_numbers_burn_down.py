# case_ids: MC-362
"""断言**比较的右侧**不得是硬编码「第 N 行」字面量（issue #9150）。

## 病（2026-11-25 实测，真红两次）

\`check-ui-regression.sh\` 加了 8 行注释（#9147 的 depth-aware fetch）⇒ 这条断言立刻红：

\`\`\`python
assert find_unbraced_var_before_non_ascii(mutated) == ["第 73 行 $f（"]
\`\`\`

它真正要判的是「扫描器能不能**定位到那一行**」，与「那一行排第几」**无关** ⇒
写死行号把「文件行数」这个无关变量钉进了判据，4/4 片整片失败。

## 为什么**不**做全量 burn-down（口径，2026-11-25 逐一分类后的结论）

现取全仓 \`第 N 行\` 字面量共 40 处，逐条看：**几乎全是**文档串 / 报错文案 / 夹具文本
（例：\`"issue #4727 第 8 行"\`、\`"第 1 行不是 \`---\`"\`），**不是**对仓内文件行号的期望 ⇒ 无害。
真正危险的是**窄的那一类**：`assert <扫描器读数> == "第 N 行 …"`。

⇒ 本判据只拦这一类（`ast.Compare` 的**比较右侧**出现 \`第 \\d+ 行\` 字符串常量）。
左侧（被测调用）与错误消息里的字面量**不受影响**。

## 判据

1. 任何 \`ast.Compare\` 的 comparator 子树里不得出现匹配 \`第 \\d+ 行\` 的字符串常量；
2. 判据自证：注入 §「病」里的那条形态 ⇒ 必红（红证内置在 `test_guard_has_teeth` 里，用合成 AST 跑，不落盘）。
"""

from __future__ import annotations

import ast
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
UNIT_CI_DIR = REPO_ROOT / "tests" / "unit_ci_workflows"
SELF = pathlib.Path(__file__).name
PATTERN = re.compile(r"第\s*\d+\s*行")


def _comparator_literals(tree: ast.AST) -> list[tuple[int, str]]:
    """比较**右侧**（comparators）里命中「第 N 行」的字符串常量。"""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for comp in node.comparators:
            for sub in ast.walk(comp):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and PATTERN.search(sub.value):
                    out.append((sub.lineno, sub.value[:60]))
    return out


def test_no_assert_compares_against_a_hardcoded_line_number():
    offenders: list[str] = []
    for path in sorted(UNIT_CI_DIR.glob("test_*.py")):
        if path.name == SELF:
            continue
        for lineno, literal in _comparator_literals(ast.parse(path.read_text(encoding="utf-8"))):
            offenders.append(f"{path.name}:{lineno} {literal!r}")
    assert not offenders, (
        "断言的**比较右侧**写死了「第 N 行」—— 行号不是稳定标识，改无关文件的行数就会假红"
        "（实例：check-ui-regression.sh 加 8 行注释 ⇒ 4/4 片整片失败）。\n"
        "改成现算（按 needle 在源文件里的位置算）或改成符号锚点：\n  " + "\n  ".join(offenders)
    )


def test_guard_has_teeth():
    """红证（合成 AST，不落盘）：§「病」里那条形态必须被判出来；而**左侧**/消息里的字面量不受影响。"""
    bad = ast.parse('assert scan(mutated) == ["第 73 行 $f（"]\n')
    assert _comparator_literals(bad), "判据对历史真实形态没有判别力（这就是 4/4 片假红的形态）"

    good_left = ast.parse('assert "第 7 行" not in scan(text)\n')
    assert not _comparator_literals(good_left), "被测调用的入参里出现行号字面量是合法的（那是夹具）"

    good_msg = ast.parse('assert ok, f"应指到第 1 行，实得 {got}"\n')
    assert not _comparator_literals(good_msg), "错误消息里的行号是给人读的，不该判红"
