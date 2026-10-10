# S18：PR #6725（#6720 打印纸面缺值）合并后的集成侧核验

## 源码/判据层（**在 `origin/main` 上核，不认"CI 绿"**）
| 项 | 读数 |
|---|---|
| 类级四件（`print-doc-paper.test.ts` / `order-amount.test.ts` / `print-doc-paper.ts` / `print-doc-zero-fallback-scan.mjs`） | 全部在 `origin/main` ✅ |
| 源码形态 | `SHIPMENT_DOC_MISSING = '—'` 已在；文件头写明「缺值一律印 `—`，**真 0 仍印 `0.00`**」 |
| CHANGELOG `## [Unreleased]` 段 | 含本单 4 行 ✅ |
| 判据实跑（工作树 `8dd83e8e5`） | **Test Files 5 passed / Tests 90 passed** ✅ |

## 真机层：**未取**（照实）
- 纸面只在「发货单/报价单预览」出现，而本租户 `/shipments` **无数据行** ⇒ 行内「补打」入口无从点；**发货**入口会**提交写操作**（有意不点）。
- ⇒ 包的 ⑤ 四项真机确认点**未完成**，已登记为未覆盖（与"本轮未做真机打印"同源）。

## 过程中的两次自我更正（记下来）
1. **`grep -E` 里写了 `??`**（非法重复算子）⇒ 整条 grep 失败、输出为空 ⇒ 我差点读成"源码里没有该修复"。**空输出要先怀疑命令，再怀疑代码。**
2. **`fetch` ≠ `pull`**：我在 `origin/main` 上查到判据文件在（✅），却在**落后的工作树**里跑 `vitest` ⇒ 报 "No test files found" ⇒ 差点报成"**类级元守卫是死判据**"。真因是工作树停在 `#6720` 之前。
   ⇒ **纪律**：跑判据前先证明 **工作树 == `origin/main`**（`git rev-parse --short HEAD`）；且**必须核 `Test Files` 数**——`vitest run <路径…>` 对不存在的路径**不报错**，只是少跑一个文件（"Tests N" 看起来照样全过）。
