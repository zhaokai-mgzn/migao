# 端点清单（机械抽取，只读）

- 来源 SHA：`ff655a06c` —— 🔴 **这是「部署台账声称」的构建点，不是当时的被测面**（行为实测 = `de614623d`，见 README §0.1 / #6294；
  两者相差 `de614623d..ff655a06c` 的 1106 个文件 / 11 个 controller）。本清单只作**覆盖面基线**用，
  不代表被测面上真实存在的端点集合；对账时若发现端点对不上，先按坐标差异解释，再判缺口。
- 抽取方式：`git show <SHA>:<path>` 逐文件机械抽取（只读）
- 用途：集成时对账三线覆盖面（防「声明覆盖 ≠ 端点被调用」）

覆盖文件 32 个 / 端点合计 154 个

## 写端点数（并发/幂等面候选）

- `ProductionController.java` → **22** 个写端点
- `OrderController.java` → **11** 个写端点
- `AgentProductController.java` → **5** 个写端点
- `AgentSessionController.java` → **4** 个写端点
- `WorkerAuthController.java` → **4** 个写端点
- `WorkerShipmentController.java` → **4** 个写端点
- `InboundOrderController.java` → **3** 个写端点
- `RemnantController.java` → **3** 个写端点
- `WorkerInboundController.java` → **3** 个写端点
- `AgentBatchController.java` → **3** 个写端点
- `AfterSalesController.java` → **2** 个写端点
- `ProcessingOrderController.java` → **2** 个写端点
- `ProductionPoolController.java` → **2** 个写端点
- `WorkerProductionController.java` → **2** 个写端点
- `AgentOrderController.java` → **2** 个写端点
- `AdminWorkerController.java` → **1** 个写端点
- `CustomerAgentSessionController.java` → **1** 个写端点
- `FinanceController.java` → **1** 个写端点
- `StockBatchController.java` → **1** 个写端点
- `WorkerInboundLabelController.java` → **1** 个写端点
- `WorkerInboundUploadController.java` → **1** 个写端点
- `WorkerPageConfigController.java` → **1** 个写端点
- `AgentAfterSalesController.java` → **1** 个写端点
- `AgentAuditLogController.java` → **1** 个写端点

## `/api/worker/**`（线① 主射程）

### `AdminWorkerController.java` (2 端点)

- `GET    /api/admin/workers`
- `POST   /api/admin/workers`

### `WorkerAuthController.java` (4 端点)

- `POST   /api/worker/login`
- `POST   /api/worker/session/switch`
- `POST   /api/worker/session/logout`
- `POST   /api/worker/session/current`

### `WorkerInboundController.java` (3 端点)

- `POST   /api/worker/inbound/recognize`
- `POST   /api/worker/inbound/drafts`
- `POST   /api/worker/inbound/drafts/{id}/post`

### `WorkerInboundLabelController.java` (2 端点)

- `GET    /api/worker/inbound/labels/{shortCode}`
- `POST   /api/worker/inbound/labels/{shortCode}/print`

### `WorkerInboundUploadController.java` (1 端点)

- `POST   /api/worker/inbound`

### `WorkerPageConfigController.java` (2 端点)

- `GET    /api/admin/worker-page-config`
- `PUT    /api/admin/worker-page-config`

### `WorkerProductionController.java` (6 端点)

- `GET    /api/worker/production/orders/{orderId}/operations`
- `POST   /api/worker/production/orders/{orderId}/operations/{operationId}/report`
- `GET    /api/worker/production/scan`
- `POST   /api/worker/production/scan/complete`
- `GET    /api/worker/production/cutting-height`
- `GET    /api/worker/production/current-worker`

### `WorkerProfileController.java` (1 端点)

- `GET    /api/worker/me`

### `WorkerShipmentController.java` (5 端点)

- `POST   /api/worker/shipment/recognize`
- `POST   /api/worker/shipment/orders/{orderId}/pack`
- `POST   /api/worker/shipment/orders/{orderId}/ship`
- `POST   /api/worker/shipment/orders/{orderId}/unpack`
- `GET    /api/worker/shipment/orders/{orderId}`

### `WorkerShortLinkController.java` (1 端点)

- `GET    /s/{shortCode}`


## 售后 / 退款 / 财务（线② 主射程）

### `AfterSalesController.java` (4 端点)

- `GET    /api/admin/after-sales`
- `GET    /api/admin/after-sales/{id}`
- `POST   /api/admin/after-sales`
- `PUT    /api/admin/after-sales/{id}/status`

### `FinanceController.java` (4 端点)

- `GET    /api/admin/finance/summary`
- `GET    /api/admin/finance/transactions`
- `POST   /api/admin/finance/transactions`
- `GET    /api/admin/finance/reconciliation`

### `AgentAfterSalesController.java` (2 端点)

- `POST   /api/admin/agent/after-sales`
- `GET    /api/admin/agent/after-sales/mine`

