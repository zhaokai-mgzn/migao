# case_ids: OR-017
"""yaml_light 行内注释剥离（issue #3365）。

## 为什么单独立测

`yaml_light` 是用例库的**唯一解析器**（`.github/cases/*.yml` → runner / 渲染器 / 契约测试），
但它原先不处理行内注释：`fallback: "确认"  # 点确认卡…` 会被解析成
**带引号带注释的整串** `'"确认"  # 点确认卡…'`，而评测 harness 会把它当**用户消息**发给 agent
→ 协议轮变乱码、流程判断全错。实证（CI run 34714334600，OR-017）：

    R4 you="确认"          # 点确认卡（confirmValue）／无卡则文本确认
    R5/R6/R7/R8 you=proc_item_pi_eval_punch      ← 模型反复重发加工项卡
    ❌ order_create 从未发生（用例判红，长相却像"能力不行"）

修后 OR-017 的协议轮恢复为「确认」「123456」等真实值。

## 判定规则（与标准 YAML 一致）

`#` **前有空白**且**不在引号内** → 起注释；引号内的 `#`（如「issue #3270」）必须保留。
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

from yaml_light import _parse_scalar, load  # noqa: E402


class TestInlineCommentStripping:
    def test_quoted_scalar_with_trailing_comment(self):
        assert _parse_scalar('"确认"          # 点确认卡（confirmValue）') == "确认"

    def test_quoted_number_with_comment_stays_string(self):
        """`"123456"` 带引号 → 是字符串（验证码按字符串传，不能被当 int）。"""
        assert _parse_scalar('"123456"        # 手机验证码') == "123456"

    def test_bool_with_comment(self):
        assert _parse_scalar("true          # 说明") is True

    def test_hash_inside_quotes_preserved(self):
        """引号内的 `#`（issue 号、井号文本）不得被当注释截断。"""
        assert _parse_scalar('"issue #3270：加工项铁律"') == "issue #3270：加工项铁律"
        assert _parse_scalar('"#开头"') == "#开头"

    def test_unquoted_scalar_with_comment(self):
        assert _parse_scalar("确认   # 注释") == "确认"

    def test_no_comment_unchanged(self):
        assert _parse_scalar("没有注释") == "没有注释"
        assert _parse_scalar("xiaobu") == "xiaobu"

    def test_hash_without_leading_space_is_not_comment(self):
        """`#` 前**没有空白**不算注释（标准 YAML 规则）：`abc#def` 必须原样保留。"""
        assert _parse_scalar("abc#def") == "abc#def"
        assert _parse_scalar("C#语言") == "C#语言"

    def test_load_full_case_shape(self):
        """整段（接近用例真实形态）：嵌套映射 + 行内注释 + 引号内 # 都要正确。"""
        text = (
            "cases:\n"
            "  - id: XX-001\n"
            "    user_inputs:\n"
            '      - auto_respond:\n'
            '          fallback: "确认"          # 点确认卡\n'
            '      - auto_select: true          # 答多选卡\n'
            '    data_checks:\n'
            '      - "issue #3270：金额必须接地"\n'
        )
        data = load(text)
        case = data["cases"][0]
        assert case["user_inputs"][0]["auto_respond"]["fallback"] == "确认"
        assert case["user_inputs"][1]["auto_select"] is True
        assert case["data_checks"][0] == "issue #3270：金额必须接地"
