# 研发 case review 流程

## 1. 收到 issue 后

1. 看 "业务真值" 段（人写）
2. 看 "待写 case 草稿"（军师反推）

## 2. review 草稿

### ✅ 同意
- 不用动
- 写代码 + 提交 case 即可
- 草稿会作为参考

### ❌ 不同意
在 issue 评论：

```
case review:
- ❌ L2 case 3 不同意
  - 原因：[说明]
  - 建议：[你的版本]
```

军师会读反馈，下次反推更准。

### ➕ 补 case
直接加进 "待写 case 草稿" 段的 issue body，PR 时一起提交。

## 3. 写 case 时的注意事项

### L2 单测（Java/Python）
- 方法名要清晰：`test_xxx_returns_correct_value`
- 断言要具体：`assert result == 5`，不要 `assert result is not None`
- 边界 case：空数据、极值、异常输入
- 用 mock 而不是真实 DB

### L3 E2E Web（Playwright）
- happy path + 错误路径 + 边界
- 用 `page.route()` mock API（不依赖真实后端）
- 跳转/导航要断言最终 URL
- 数据断言要明确（不只断言"存在"）

### L4 业务断言（军师/独立 AI 跑）
- 你不用写，**军师会自动反推**
- 跑的是 DB 直查或 admin-api 调用
- **与你写的 L2/L3 独立**，避免合谋

## 4. 提交 PR

PR body 必须：
- 写明 Fixes #xxx
- 列你写的 L2/L3 case
- 说明 case 与业务真值的对应

## 5. 自动验收

PR 合 main 后，**军师 + 独立 AI** 会自动跑验收。
- ✅ 双一致 + 100% 通过 → 自动 close issue
- ❌ 任何失败 → 评论 + 不 close，你修

## 6. 反馈学习

如果军师反推的 case 总错某个模式，**那是模板的锅**。
军师会从你的反馈中改模板，下次反推更准。
