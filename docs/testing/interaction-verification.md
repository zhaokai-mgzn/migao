# 复杂交互验证机制（三层）— 防交互缺陷靠用户实测

> **背景**：2026-09-05 复盘。sess_fba38395ed094a9d 的加工项选择交互连修 3 轮
> （issue #2892/#2894/#2896）才到位：pageMeta TypeError → 多选/翻页控件不可用 →
> 交互模型缺陷（点一项即触发 agent 汇总）。根因不是「手滑」，而是**测试体系缺少
> 「前端交互协议 + 真实 LLM + 后端工具契约」三端联动的验证层**——单元测试和 Gate
> 只能保证「不崩」「控件在」，抓不到「交互流程行为错误」。

本文档定义**三层验证机制**，并给出订单/售后等其它复杂多轮引导域的应用模板。

## 三层机制

| 层 | 捕获的缺陷类型 | 确定性 | 成本 | 落点 |
|----|--------------|--------|------|------|
| **① 契约层** | schema 声明 ↔ execute 签名断裂（pageMeta/multiSelect 类）；跨端字段丢失 | 确定性（无需 LLM） | 零（纯静态/单测） | `test_tool_schema_signature_contract.py`、`test_interact_payload_contract.py`、前端 `interactive-contract.test.ts` |
| **② 协议流层** | 前端操作序列 ↔ SSE 事件流契约断裂（展示 choice → 翻页 → 提交的事件合法性） | 半确定（mock LLM + 真实工具层） | 低（单测级） | `test_interaction_flow_runner.py` |
| **③ 行为层** | LLM 行为错误（点一项即汇总、只取第一个名称、二次询问） | 真实 LLM（非确定） | 高（真实 token） | `cases/*.yml` → agent-eval |

**原则**：能由 ① 捕获的缺陷**不允许**流到 ②③（确定性优先）；能由 ② 捕获的
**不允许**流到 ③（省真实 token）；③ 只承载 ①② 无法静态/半确定覆盖的
「LLM 行为」本身。

## ① 契约层

### 1a. 工具 parameters schema ↔ execute 签名

`backend/ai-agent-service/tests/test_tool_schema_signature_contract.py`：

- 遍历 `app/tools/*` 全部工具类（继承 BaseTool 且有 name）；
- 对每个工具：`parameters.properties` 的 key 必须能落到 `execute()` 显式签名
  （规范化后匹配：`pageMeta` ≡ `page_meta`）；
- execute 有 `**kwargs` 兜底的工具豁免（action 分发设计，如 finance_api）。
- **新增/修改工具时**：schema 声明了参数就必须在 execute 签名里接收，否则
  LLM 按 schema 传参（这是 OpenAI function calling 契约）→ TypeError 崩溃。

### 1b. interact payload 字段白名单（后端 ↔ 前端）

- 后端 `test_interact_payload_contract.py`：interact 工具 choice/confirm/form
  产出的 data 字段 ⊆ 白名单，且白名单字段都能发出（双向覆盖）；
- 前端 `frontend/admin-web/tests/unit/store/interactive-contract.test.ts`：
  等价于后端输出的 SSE payload 经 store 解析后 full 字段保留（防 store 漏透传；
  回归：pageMeta 曾不被 store 持久化 → 翻页控件永不渲染）。
- **白名单字段增删必须两端同步**：前端 `types/index.ts` InteractiveComponent ↔
  后端 `FRONTEND_INTERACTIVE_FIELDS`。

## ② 协议流层

`backend/ai-agent-service/tests/test_interaction_flow_runner.py`：

- mock LLM（固定 tool_calls/文本序列）+ **真实 InteractTool** + 真实
  `execute_skill` 链路；
- 模拟前端操作序列，断言每个步骤 SSE 事件（交互 payload）合法：
  - 展示 choice 必须带 `pageMeta`（前端翻页契约）+ `multiSelect`（前端多选契约）；
  - `__PAGE__` 翻页白名单覆盖加工项查询；
  - 「已选加工项：A、B」一次性提交必须收敛到汇总（不只取第一个、不再二次询问）。
- **新增复杂交互 flow 时**：为「用户在前端点选的完整序列」补一段 runner 测试，
  断言各步交互 payload 字段契约。

## ③ 行为层（真实 LLM）

- 用例单一源：`.github/cases/<域>.yml` → `render_cases.py` 渲染 →
  `tests/agent_eval/eval_cases.py`（CI agent-eval 消费）。
- **B 端复杂交互用例模板**（以加工项 PR-014/PR-015 为样板）：
  1. 触发引导（如「录入这个商品」）→ 断言 interact(key 控件)；
  2. 用户按前端**真实发送的文本**回复（如「已选加工项：打孔加工、韩式折边」——
     **必须是前端按钮实际产出的文本格式**，不是人脑想象的文本）；
  3. 断言关键行为：解析全部名称 / 不二次询问 / 进下一步（validate_input / 汇总）。
- **订单域扩展**（参照 OR-010 模式）：下单引导的用户文本 = 前端 confirm 卡片
  `confirmValue` 实际发送值；分类/规格 = choice option 实际发送的 label。
- **售后域扩展**：工单创建引导同理，user_inputs = 前端交互组件实际发送文本。

## 订单/售后复杂交互应用清单（后续按域补）

| 域 | 复杂交互点 | 已有用例 | 需补的交互验证 |
|----|-----------|---------|---------------|
| 订单 | 下单引导：SKU 选择 → 加工项 → 数量 → 确认 | OR-001~OR-016 | ① 契约层：order_create 参数 schema ↔ 签名；② 协议流层：SKU choice → 计算 → confirm 事件序列；③ 行为层：前端 confirmValue 文本 → 下单不二次询问 |
| 售后 | 工单创建：原因 → 说明 → 关联订单 → 确认 | AS-001~ | ①②③ 同订单模式 |
| 客户 | 客户档案创建引导 | CU 域 | 同上 |
| 商品 | 加工项多选（**已完成**，PR-014/PR-015 + 三层测试） | PR-011/012/014/015 | ✅ |

## 改动检查清单（新交互或交互修复）

1. 工具改了 schema → 跑 `test_tool_schema_signature_contract.py`（① 必过）；
2. 交互字段变了 → 同步后端白名单 + 前端 types（① 两文件同改）；
3. 交互流程变了 → 补协议流 runner 测试（②）；
4. 用户可见行为变了 → 补/改 `cases/*.yml`（③，渲染生成物后提交）；
5. 提交前：`./verify-all.sh gate` + `./check-ui-regression.sh`；
   cases 改动后 `python3 .github/render_cases.py` 重渲染并提交生成物。