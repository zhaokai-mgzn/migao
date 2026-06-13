# 米宝代码质量范式

## 四层安全网

```
git commit  →  git push  →  CI PR  →  合并部署
    │             │           │          │
   L0           L2          L1        L3+
 pre-commit   pre-push    CI unit    auto-fix
  <30s         ~10min      3min      每10min
```

| 层 | 触发时机 | 跑什么 | 不过会怎样 |
|----|---------|--------|-----------|
| **L0** | `git commit` | 单元测试（920 cases，增量） | ❌ 不能 commit |
| **L1** | PR 触发 | CI 全量单测 | ❌ 不能 merge |
| **L2** | `git push` | 真实 E2E（33 cases，零 Mock） | ⚠️ 警告但允许 push |
| **L3** | 每 10 分钟 | 检查 CI + 自动修复 | 🤖 AI 自动诊断修复 |

## L0: pre-commit

```bash
# 自动安装：已在 .git/hooks/pre-commit
# 跑什么：语法检查 + 快速单测（30s 超时）
# 跳过：E2E 测试、需要服务的测试
```

## L2: pre-push — 真实 E2E

**零 Mock 铁律：E2E 测试不 Mock 任何组件。**

```bash
# 自动安装：已在 .git/hooks/pre-push
# 前置：admin-api :8080 + ai-agent :8001 必须运行
# 如果服务没启动 → 跳过（不阻塞 push）
```

### E2E 覆盖（33 cases）

| 文件 | 覆盖 |
|------|------|
| `test_query_tools.py` (18) | 全部 18 个查询工具，admin-api 数据验证 |
| `test_write_tools.py` (7) | 写操作 × admin-api 持久化验证 |
| `test_creation_flows.py` (5) | 商品/订单/售后创建 × 全字段验证 |
| `test_security.py` (3) | Prompt 注入/角色切换/代码执行拒绝 |

### 强验证标准

每个 E2E case 必须：
1. ✅ 真实 SSE 对话（零 Mock LLM）
2. ✅ 真实工具调用（零 Mock tool）
3. ✅ 真实 admin-api 查询（零 Mock API）
4. ✅ 逐字段核对数据（名称/价格/状态/颜色）
5. ✅ 写操作后 admin-api 二次确认持久化

## L3: 自动修复循环

```
测试失败 → Issue 自动创建 → AI 诊断根因 → 修复 → 提 PR → CI 绿 → 合并
```

每 10 分钟检查一次。不新增功能，只修复。

## 研发铁律

1. **单测可以 Mock，集测和 E2E 禁止 Mock** — 一个 mock 点都不允许
2. **写操作必须强验证** — admin-api 二次确认数据持久化
3. **提交前 L0 必须绿** — 不绿不 commit
4. **真实 E2E 失败 → 优先修复，不跳过**
5. **AI auto-fix 修复的代码也必须走 L0→L1→L2**
