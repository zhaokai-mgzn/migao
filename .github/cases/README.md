# cases/ — 用例契约库（并源试点）

> 单一行为用例源。标准见 `ershen/design/16-case-contract.md`（schema v1.0 草案）。

## 文件结构

```
cases/
├── README.md          # 本文件
├── order.yml          # ✅ 订单域（10 条）
├── product.yml        # ✅ 商品/库存/创建流程（12 条）
├── processing.yml     # ✅ 加工项（4 条）
├── aftersales.yml     # ✅ 售后（5 条）
├── customer.yml       # ✅ 客户（5 条）
├── hr.yml             # ✅ 人事/角色（5 条）
├── settings.yml       # ✅ 设置/通知（7 条）
├── data.yml           # ✅ 看板/数据（4 条）
├── chat.yml           # ✅ 边界/多轮（7 条）
├── cross.yml          # ✅ 跨 Skill（3 条）
├── defense.yml        # ✅ 防御（15 条）
└── category.yml       # ✅ 分类管理（3 条）
```

合计 **80 条用例 × 12 域**，全部完成并源转换（94 源用例 → 80 条，去重 14 条）。

## 关键约定

1. **引用不复制**：`truths_ref` 引用 `templates/<domain>.yml` 的真值 ID，用例内禁止内嵌真值文本。
2. **ID 稳定**：`<域前缀>-<3位数字>` 一经发布不可改；旧 ID 保留在 `legacy_id`。
3. **并源溯源**：每条用例的 `merge_log` 记录「由哪些旧用例合并而来」，防止合并时丢覆盖。
4. **缺口显式**：真值暂缺时 `truths_ref: []` + ⚠️ 注释，由映射表 5.1 节跟踪补真值，禁止留空装作无事发生。
5. **生成物禁手写**：`eval_cases.py` 与 `mibao-verification-cases.md` 迁移完成后由 `render_cases.py` 渲染。

## 迁移进度

| 步骤 | 状态 |
|---|---|
| 映射表（94 例 → 16 模板） | ✅ `ershen/docs/case-source-mapping.md` |
| schema 标准 | ✅ `ershen/design/16-case-contract.md` |
| 真值 ID 化（templates 侧） | ✅ 19 模板 151 条全部带 `[模板名.短名]` ID 前缀 |
| 真值缺口补齐 | ✅ 新建 `id-resolve.yml` / `category-manage.yml` / `defense.yml`，增补 ai-chat/order/dashboard/product 4 个模板 |
| 真值解析器 | ✅ `ershen/engine/junshi/truths.py`（index / check，fail-closed）+ `test_truths.py` 6 条单测 |
| 12 域用例转换 | ✅ 80 条全部落地（126 处 truths_ref 可解析，7 个缺口用例显式标注） |
| CI 门禁 | ✅ `pr-check.yml` 新增 `case-truth-check` job（seed + migao 两份），seed 文件已部署至 `migao/.github/` |
| `render_cases.py` 生成器 | ✅ YAML → `eval_cases.py`（80 条）+ `mibao-verification-cases.md`，两者已生成、禁止手改 |
| `local_runner.py` 直读 YAML | ✅ 新增 `--cases` 参数 + direct_reply 分支 + legacy_id 查找；`agent-eval.yml` 已改走单一源 |
| G5 追溯链（测试文件→用例） | ⏳ |

## 重新生成命令

```bash
python3 .github/render_cases.py \
  --cases .github/cases \
  --out-eval tests/agent_eval/eval_cases.py \
  --out-md docs/testing/mibao-verification-cases.md
```

## 已知缺口（在模板 ⚠️ 注释与用例 truths_ref 中显式标注）

- 多候选名称歧义处理（id-resolve.yml）
- 订单号生成规则 ORD-yyyyMMdd-XXXX（order.yml，解析侧已写真值 order.no-format）

> 2026-08-14 补挖完成的 10 处缺口：注入防护/输出长度/速率限制/Redis 降级/JWT/输入长度（defense）、来源标注（ai-chat，写真值=机制不存在）、change_password（settings）、删除分类 DESTRUCTIVE（category）、订单号解析（order）——全部回代码核实后写为真值。

## 用例预期校准记录（并源时按代码修正的旧用例）

| 旧用例预期 | 代码实际 | 校准去向 |
|---|---|---|
| escape hatch「输入长度>10」 | 域触发词（nodes.py 明确不用字符数） | CH-002 → ai-chat.escape-hatch |
| 压缩「20 条/20 轮」 | max_recent=12（base_skill.py:819） | DF-004/DF-015 → ai-chat.compression |
| 熔断「连续 5 次失败」 | failure_threshold=3（app/core） | DF-011 → defense.breaker-threshold |
| 输出「<2000 字符」 | LLM max_tokens 默认 512 | DF-001 → defense.output-limit |
| 速率限制「触发」 | 未实现（仅 key 前缀） | DF-004 → defense.rate-limit（不期待触发） |
| 来源标注「[工具返回]」 | 机制不存在 | CH-004 → ai-chat.source-annotation（断言现状） |

## 校验命令

```bash
# 用例引用校验（fail-closed；缺口用例仅告警）
python3 ershen/engine/junshi/truths.py check \
  --templates ershen/seed/migao/templates \
  --cases ershen/seed/migao/cases

# 全量真值索引
python3 ershen/engine/junshi/truths.py index --templates ershen/seed/migao/templates
```
