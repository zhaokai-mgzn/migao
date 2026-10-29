# case_ids: DA-006
"""工具选择的**真值单源化**：`【不要用于】` 元数据（issue #8132 / 审计 P1-2 F3）。

## 病根（现取读数，不是假说）

B 端黄金策每轮绑 34–38 个工具，**选错工具**是主要失败来源之一。「不要用 A 做 B」过去有**两份真值**：
① `app/graph/skills/references/prompts/*.md` 的手写「工具选择」规则；② 工具自己的 `description`。
本包把那句话从 ① 里删掉、搬进 ②，并在原位留一行指路 —— 本文件锁三件事：
**每个工具都声明了「不要用于」** / **声明的目标工具真实存在且不是自己** /
**被删的那条真值确实活在工具描述里、且没在 prompt 表里复活**。

## 判据与红证（改这一处即红）

| 用例 | 反例输入 |
|---|---|
| `test_every_tool_declares_what_it_is_not_for` | 删掉任一工具的 `【不要用于】` 段 ⇒ 红 |
| `test_every_named_target_is_a_registered_tool_and_not_itself` | `（用 session_manage）` 改成不存在的名字 / 改成自己 ⇒ 红 |
| `test_every_line_names_at_least_one_cross_domain_tool` | 两处都指向同域工具（如 `order_query` 只写「用 order_create」）⇒ 红 |
| `test_deleted_prompt_rule_is_gone_and_truth_lives_in_tool_description` | 把旧规则写回 `prompts/data.md` ⇒ 红 |
| `TestGuardIsNotVacuous` | 合成夹具（缺段 / 自指 / 同域）在内存里各自判红 ⇒ 守卫不是恒绿 |

## 边界（判不了什么）

- 判不了「跳转到的那把工具**业务上真的**能处理那类问题」—— 那要评审 / 评测；本文件只判
  **存在性 + 不是自己 + 跨域**，**不是**能力正确性背书。
- 域 = 工具名第一段（`order_query` → `order`）；这是**防「全都推给同一把工具」**的粗粒度判据，
  不是业务域的真值。故同域同前缀但语义不同的（如 `processing_item_query` 属商品目录域）不会被本判据区分。
"""

import re
from pathlib import Path

import pytest

from app.tools.registry import get_tool_registry

SERVICE_ROOT = Path(__file__).resolve().parents[1]
DATA_PROMPT = SERVICE_ROOT / "app" / "graph" / "skills" / "references" / "prompts" / "data.md"

MARKER = "【不要用于】"
MAX_LINE_CHARS = 120
#: 装配面去噪口径（tests/test_prompt_denoise.py）：会进 system prompt 的正文里不得有内部编号。
ISSUE_REF_RE = re.compile(r"#\d{4,}")

#: 本切片覆盖的 6 个最易混 B 端只读工具（选错工具的失败面集中在这里）。
TOOLS = (
    "order_query",
    "customer_manage",
    "processing_order_query",
    "stock_ledger_query",
    "finance_api",
    "dashboard_stats",
)

#: 被删掉的那条手写规则的**标志性短语**（它不该再出现在 prompt 表里）。
DELETED_RULE_HALLMARKS = (
    "工具分工不要串",
    "查客服会话详情用 session_manage",
)


def not_for_line(description: str) -> str:
    """取 `description` 里 `【不要用于】` 段（到下一个 `【` 段或结尾为止）。"""
    match = re.search(rf"{MARKER}(.*?)(?=【|\Z)", description, re.S)
    return match.group(1).strip() if match else ""


def named_targets(line: str) -> list:
    """`（用 <tool>）` 里点名的工具（只认 snake_case 工具名，避免把散文当工具）。"""
    return re.findall(r"（用\s*([a-z][a-z0-9_]*)）", line)


def domain_of(tool: str) -> str:
    return tool.split("_")[0]


@pytest.fixture(scope="module")
def registry():
    return get_tool_registry()


@pytest.fixture(scope="module")
def descriptions(registry):
    return {name: registry.get_tool(name).description for name in TOOLS}


def test_every_tool_declares_what_it_is_not_for(descriptions):
    """6 个工具的描述里都必须有 `【不要用于】` 段（单源的入口）。"""
    missing = [name for name, desc in descriptions.items() if not not_for_line(desc)]
    assert not missing, (
        f"以下工具的描述里没有 `{MARKER}` 段（改回 order_query 之外的手写表 = 真值又分两份）：{missing}"
    )


def test_every_named_target_is_a_registered_tool_and_not_itself(registry, descriptions):
    """点名的目标工具必须**真实存在**且**不是自己**（否则模型被指向一把调不到的工具）。"""
    registered = set(registry.get_tool_names())
    problems = []
    for name, desc in descriptions.items():
        line = not_for_line(desc)
        assert line, f"{name} 缺 `{MARKER}` 段"
        assert len(line) <= MAX_LINE_CHARS, (
            f"{name} 的 `{MARKER}` 行 {len(line)} 字 > {MAX_LINE_CHARS}：{line}"
        )
        assert line.count("（用") == 2, f"{name} 的 `{MARKER}` 行必须是两段式 `<A>（用 X）；<B>（用 Y）`：{line}"
        targets = named_targets(line)
        assert len(targets) == 2, f"{name} 的 `{MARKER}` 行解析不出两个工具名：{line}"
        for target in targets:
            if target == name:
                problems.append(f"{name}: 把自己列为「不要用于」的跳转目标")
            if target not in registered:
                problems.append(f"{name}: 跳转目标 `{target}` 不在注册表里")
    assert not problems, "「不要用于」指向了不可达 / 自指的工具：\n" + "\n".join(problems)


def test_every_line_names_at_least_one_cross_domain_tool(descriptions):
    """每条 `【不要用于】` 至少点名 1 个**不同域**的工具（防「全都推给同一把工具」）。"""
    same_domain_only = []
    for name, desc in descriptions.items():
        targets = named_targets(not_for_line(desc))
        if not any(domain_of(t) != domain_of(name) for t in targets):
            same_domain_only.append(f"{name} → {targets}")
    assert not same_domain_only, (
        "以下 `【不要用于】` 只指向同域工具（跳转等于没跳）：\n" + "\n".join(same_domain_only)
    )


def test_deleted_prompt_rule_is_gone_and_truth_lives_in_tool_description(descriptions):
    """删了不丢真值：手写规则不再出现（标志性短语），真值在工具描述里，原位留了指路行。"""
    text = DATA_PROMPT.read_text(encoding="utf-8")

    survivors = [hall for hall in DELETED_RULE_HALLMARKS if hall in text]
    assert not survivors, (
        f"`prompts/data.md` 里被删的手写规则又回来了（真值重新分两份）：{survivors} —— "
        f"它现在只该在工具描述里（{MARKER}）"
    )

    pointer_lines = [line for line in text.splitlines() if "工具选择口径以对应工具的" in line]
    assert len(pointer_lines) == 1, (
        f"`prompts/data.md` 里应有且只有 1 行指路行（删了规则却没指向工具描述）：{pointer_lines}"
    )
    assert "`description`" in pointer_lines[0] and MARKER in pointer_lines[0], (
        f"指路行必须同时点名工具 `description` 与 `{MARKER}`：{pointer_lines[0]}"
    )
    # 该行会**原样进 system prompt** ⇒ 不得带内部编号（口径 = tests/test_prompt_denoise.py）。
    assert not ISSUE_REF_RE.search(pointer_lines[0]), (
        f"指路行不得带内部 issue 编号（会被渲染进 system prompt）：{pointer_lines[0]}"
    )

    order_query_targets = named_targets(not_for_line(descriptions["order_query"]))
    assert "session_manage" in order_query_targets, (
        "被删规则的真值（会话查询用 session_manage）没落到 `order_query` 的 "
        f"`{MARKER}` 里：{order_query_targets}"
    )


class TestGuardIsNotVacuous:
    """注入式自证：判据本体对坏形态**会红**（否则上面的绿是空断言）。"""

    def test_missing_marker_is_reported(self):
        assert not_for_line("【触发】查订单。【标注】READONLY") == ""

    def test_self_reference_and_unknown_target_are_detectable(self):
        line = not_for_line("x【不要用于】甲（用 order_query）；乙（用 no_such_tool）【标注】y")
        targets = named_targets(line)
        assert targets == ["order_query", "no_such_tool"]
        assert named_targets(not_for_line("x【不要用于】甲（用 order_manage）；乙（用 order_create）")) == [
            "order_manage",
            "order_create",
        ]
        # 同域判定确实能区分：order_query 的「同域目标集」不跨域
        assert domain_of("order_manage") == domain_of("order_query")
        assert domain_of("session_manage") != domain_of("order_query")
