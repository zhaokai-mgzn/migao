人为要求：用户 2026-10-03 逐字「有问题就立马派单修，有单子就立马派不需要问，但是不要留尾巴」。发现者是集成方，在 **#6171（PR #6177）合并后的真库重放**中当场抓到。

## 🔴 P1 回归：商家发货**每次都 422**，但订单已被改成 shipped（部分写入 + 假陈述）

**构建点**：`origin/main` @ `0595f4762`（含 #6177）；探针 = `acceptance/2026-10-03/shipments-sweep/harness/run-all.mjs`，
干净档 `out/replay-s2b/`（读数 pass=69 / fail=5 / skip=4）。

**响应体逐字**（探针 K3-1，租户 20 真库）：
```json
{"success":false,"error":{"code":"VALIDATION_ERROR","message":"当前状态（已发货）已不在可发货状态，本次未新增发货单（订单发货状态未变更）"},"requestId":"req_4161f67d541f4df9"}
```
**同时**该探针的字段级对照 = `变化: ["order_logistics.*","orders.status"]`，
且 `select * from order_shipments where order_id=…` → `[]`（**单没建**）。

### 根因（代码定序，逐字）

`ProductionController` 商家发货三步（`origin/main`）：
1. `assertShippableOrder`（零写前置）
2. `orderService.shipWithLogistics(...)` —— **记物流 + 流转 `shipped`（已提交）**
3. `orderShipmentService.recordMerchantShipment(...)` —— 但该方法**自己又判了一次**：
```java
if (!SHIPPABLE_FROM.contains(order.getStatus())) {
    throw BusinessException.validationError(String.format(
        "当前状态（%s）已不在可发货状态，本次未新增发货单（订单发货状态未变更）", …));
}
```
⇒ 第 ③ 步读到的 `order.getStatus()` 已被第 ② 步改成 `shipped`，而 `SHIPPABLE_FROM` = confirmed|producing|packed
⇒ **必然命中抛错**（"想区分'是我们刚流转的'与'本来就已发货'"这个意图，用这个谓词**区分不了**）。

### 为什么单测没抓到（要固化）

S2 的单测**直接调 `recordMerchantShipment`**（订单仍是 confirmed）⇒ 顺序问题不可见；
控制器侧测试若 mock 了 service 亦然。**只有端到端（真控制器 + 真服务 + 真库）能抓到**。

### 影响

商家发货（核心动作）**一律 422**；订单状态与物流**已写入**、发货单**未建**；错误文案与事实相反
（"订单发货状态未变更"）⇒ 商家会重试/误判，且「订单出现在发货单列表」这个用户裁定要建的**目标仍未达成**。

## 要求（修复守则）

1. **原子性**：整条商家发货路（状态流转 + 物流 + 发货单）要么全成、要么全不成。
   禁止"状态已流转 + 返回错误"的部分写入（现在就是这个形态）。
2. `recordMerchantShipment` **不许**用"当前状态"表达"我们刚流转过"（谓词区分不了）；改由调用方**显式传入**本次是否发生了流转
   （如 `shipWithLogistics` 的返回值/由事务内共享状态），或把建单并入同一事务后按"是否有本次流转"建单。
3. **文案必须与事实一致**：拒绝时**不许**声称"订单发货状态未变更"而实际改了状态。
4. **端到端判据（必须会红）**：`.github/workflows` 之外，本单至少要有 ——
   ① 走**真控制器**（不是直接调 service）的商家发货 ⇒ 2xx ∧ `order_shipments` **恰 1 行** ∧ `orders.status='shipped'`；
   ② 重复调用（同键/不同键）⇒ 仍**恰一张**、且**不得**出现"状态变了却 422"；
   ③ 注入"第 ③ 步抛错" ⇒ 判据红且**状态零变动**（原子性）。
5. 保留 #6171 已达成的：`source='admin'`、实发 = 订单未发余量、余量 0 ⇒ 4xx 且零写。
6. 不回归：`./mvnw -o test -Dtest='*Shipment*,*ProductionController*,*OrderService*'` 全绿（本机**无 `mvn`**）。

## 边界

- 🔴 `CHANGELOG.md` 不许碰（集成方独占；本单落地后由集成方把 #6171 那条改准）；`.github/cases/**` 不许碰。
- **集成方已同时 revert #6177**（抢先把 main 的商家发货恢复成可用）⇒ 本单是在**干净地基**上重做，别假设 #6177 还在。
- 不派发真实 LLM 评测（#4262）；真库重放由集成方做。
