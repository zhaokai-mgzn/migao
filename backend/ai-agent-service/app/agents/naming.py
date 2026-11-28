"""Agent 内部 id ↔ 产品名映射（**单一事实源**）

## 为什么内部 id 与产品名不一一对应（这是历史，不是笔误）

| 内部 id | 产品名 | 侧 | 形态 |
|---|---|---|---|
| `mibao` | 黄金策 | B 端经营侧 | agent |
| `xiaobu` | 智能客服 | C 端 | 技术能力（**无对外 agent 形态**） |

两条来历（写在这里，是为了让后人**不要「顺手改回对齐」**）：

- `mibao` 这个 id 来自**旧的 C 端产品名**。2026-10-08 产品侧改名后，C 端换了 id，`mibao` 留给了
  **B 端经营侧**（`app/agents/agents/mibao.py` 的 `display_name` 是「黄金策」）。
  ⇒ 看到 `mibao` 就想到「米宝」是**错的**，它现在指黄金策。
- `xiaobu` 是 C 端客服的**技术标识**（「小布」）。C 端自 2026-11-28 起**不提供 agent 拟人形态**
  （用户裁定逐字：「C 端现在不提供 agent 形态，只提供技术能力，直接叫智能客服」）⇒ 它对客户
  一律称「智能客服」，不拟人、不自称名字；`xiaobu` 现在指**智能客服的对话内核**
  （主入口 = 微信客服通道：通道 + 判定 + 回复内核）。

🔴 **不要改 `name=` / `persona=` / 文件名去「对齐产品名」**：它们会连带改会话状态键、路由键、
评测用例的 `persona` 字段、历史迁移与前端映射。产品口径见 `docs/brand/identity-2026-11.md`。

## 怎么用（单一事实源 ≠ 唯一真值）

- 本文件的 `AGENT_NAMING` 是**期望值**；各 agent 声明里的 `name` / `display_name` 是**独立写的真值**。
  两者由 `tests/unit_ci_workflows/test_agent_naming_source_of_truth.py` **逐字比对** —— 两边都从
  本文件派生的话，改一侧另一侧跟着变，判据就退化成恒真断言（= 空断言）。
- C 端「未起名时的兜底默认名」从 `C_END_DISPLAY_NAME` 取，避免第三处字面量。
"""

AGENT_NAMING = {
    "mibao": {
        "display_name": "黄金策",
        "side": "B",
        "form": "agent",
        "note": (
            "此 id 来自**旧的 C 端产品名**；2026-10-08 产品改名后 id 留给 B 端经营侧使用，"
            "display_name 是「黄金策」—— 与 id 不同是历史遗留，不是笔误，也不要改 id 去对齐。"
        ),
    },
    "xiaobu": {
        "display_name": "智能客服",
        "side": "C",
        "form": "capability",
        "note": (
            "C 端不提供 agent 拟人形态、不对外自称名字（用户 2026-11-28 裁定）；此 id 现在指"
            "「智能客服的对话内核」（主入口 = 微信客服通道），产品面对客户一律称「智能客服」。"
        ),
    },
}

#: C 端兜底默认名（商家未在「机器人设置」里自定义名字时用它）
C_END_DISPLAY_NAME = AGENT_NAMING["xiaobu"]["display_name"]
