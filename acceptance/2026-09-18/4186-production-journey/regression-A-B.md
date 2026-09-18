# 全量冒烟 A/B（证明本 PR 未回归既有旅程）

同一栈、同一 SHA `d5bca241` 的**同一份**被测代码，只换 spec.mjs：
- 基线 = `git show HEAD:scripts/ui-smoke-merchant/spec.mjs`（HEAD = d5bca241，即本 PR 改动前）
- 本分支 = `scripts/ui-smoke-merchant/spec.mjs`（含新增 `32-production-qr-and-piecework`）

| 旅程 | 基线(HEAD) | 本分支 | 判定 |
|---|---|---|---|
| 01-login | ✅ | ✅ | 一致 |
| 02-dashboard | ✅ | ✅ | 一致 |
| 03-briefing | ✅ | ✅ | 一致 |
| 04-agent-workspace-redirect | ✅ | ✅ | 一致 |
| 05-human-sessions | ✅ | ✅ | 一致 |
| 06-agent-sessions | ❌ | ❌ | 一致 |
| 07-chat | ❌ | ❌ | 一致 |
| 08-products-list | ✅ | ✅ | 一致 |
| 09-products-new | ✅ | ✅ | 一致 |
| 10-product-detail | ✅ | ✅ | 一致 |
| 11-product-edit-doorwidth | ❌ | ✅ | **变化（基线侧 flake：该旅程不读本 PR 任何改动）** |
| 12-processing | ✅ | ✅ | 一致 |
| 13-categories | ✅ | ✅ | 一致 |
| 14-orders-list | ✅ | ✅ | 一致 |
| 15-orders-new | ✅ | ✅ | 一致 |
| 16-order-detail-processing-order | ✅ | ✅ | 一致 |
| 32-production-qr-and-piecework | —（无此旅程） | ✅ | 新增 |
| 17-order-ship | ❌ | ❌ | 一致 |
| 18-after-sales-list | ✅ | ✅ | 一致 |
| 19-after-sales-detail | ✅ | ✅ | 一致 |
| 20-customers-list | ✅ | ✅ | 一致 |
| 21-customer-detail | ✅ | ✅ | 一致 |
| 22-finance | ✅ | ✅ | 一致 |
| 23-employees | ✅ | ✅ | 一致 |
| 24-roles | ✅ | ✅ | 一致 |
| 25-settings | ✅ | ✅ | 一致 |
| 26-notifications | ✅ | ✅ | 一致 |
| 27-corporate-home | ✅ | ✅ | 一致 |
| 28-corporate-about | ✅ | ✅ | 一致 |
| 29-corporate-contact | ✅ | ✅ | 一致 |
| 30-corporate-services | ✅ | ✅ | 一致 |
| 31-register | ✅ | ✅ | 一致 |

- 基线汇总：27/31 通过
- 本分支汇总：29/32 通过
- **回归（✅→❌）条数：0**；两轮一致 30/31 条

> 两轮都红且与本 PR 无关：`06-agent-sessions` / `07-chat`（ai-agent 未起，UI-only）、
> `17-order-ship`（前置依赖 `16-` 把加工单流转到 completed；`16-` 本身也受定长 sleep 竞态影响）。
