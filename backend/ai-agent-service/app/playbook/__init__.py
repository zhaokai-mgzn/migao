"""口径卡（Playbook）—— 让「纠正一次」变成「全企业受益」（issue #8175 一期最小闭环）。

**主语是「企业」，不是员工。** 所以一条口径不是一条自由文本记忆，而是**有 schema 的工件**：

    playbook: {id, tenant_id, scope: tenant|role, trigger, correct, counter,
               source: {session_id, turn}, hits, state: draft|active|retired}

四个出口共用这一份源（本期只落两个，另两个见 `docs`/PR body 的未做清单与重启条件）：

| 出口 | 本模块的承载体 |
|---|---|
| ① prompt 片段 | `app.playbook.prompt`（只有 `active` 进 prompt；退役立即消失） |
| ③ 用例（trigger/counter 自动生成） | `app.playbook.casegen`（生成物**真跑**，不是字符串拼接） |
| ② 知识卡（knowledge_search 命中） | **本期不做** |
| ④ 工具默认参数 | **本期不做** |

## 三条不变式（每条都有会红的判据）

1. **只有 `active` 出现在任何出口** —— `draft` / `retired` 一条都不许露头
   （读面**不缓存**：缓存是「退役之后还粘着」的唯一成因）；
2. **`trigger` / `counter` 必须是机器可判的结构化条件** —— 自由文本**不可执行** ⇒ 该卡
   **不出现**在任何出口（fail-closed，不是「跳过校验照发」）；
3. **租户隔离**：A 租户的卡不得出现在 B 租户的任何出口。

条件语言（唯一实现 = `app.playbook.condition`；Java 写面校验器
`PlaybookConditionValidator` 的算子表由
`tests/unit_ci_workflows/test_playbook_condition_contract.py` 现取对账）。
"""
