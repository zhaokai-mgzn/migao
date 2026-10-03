人为要求：用户 2026-10-03 逐字「按「发现即并行」继续推进」；本单是 F4（#6114）合并后由**其修复包自己登记**的同类形态（类级未固化项），由集成方核源后开单。

## 现象（同 F4 的失败形态，另一条触发维）

F4 修好了**选项触发**（`trigger_kind='option'`）的 10 条特殊选项规则（补 `position='布帘'`）。但种子路径里还有**第二条触发维**同样引用**只有布帘变体**的工序，且 `position` 仍是 `NULL`：

`backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java:581-585`
```java
// ③ 加工项触发（issue #4577：3 条，与 V84 逐条同值）—— 排在选项之后、系数档之前
for (String[] rule : PROCESSING_ITEM_RULES) {
    priority += 10;
    addRule(plan, existing, available, tenantId, "processing_item", rule[0],
            null, rule[1], rule[2], rule[3], priority, null);   // ← 部位实参 = null
}
```
触发键 = 订单行 `processingInfo.processingItems[].name`（**精确相等**）；这 3 条引用的工序（花边 / 扣环 / 接高 一类）**只有 `-布` 变体**。

⇒ 若某张**纱帘单**带了这些加工项 ⇒ 同一形态 **fail-closed**（首条报错可能变成「特殊选项引用的条件工序 … 在工序库中不存在」而非「工艺路线 … 引用的工序 …」）。

## 必须先核的前提（**别照字面就改**）

1. 这 3 条规则与 **V84 迁移**「逐条同值」是**既有守卫**（源码注释明写）⇒ 先查 V84 是否属**冻结面**、那条守卫怎么判、改动会不会当场红。
2. 确认它**真的会 fire**：纱帘单 + 该加工项 ⇒ 复现失败；若实测不 fire（例如加工项在纱帘单上不出现），**停下回报**并把本单降级为「登记」。
3. 🔴 若「修好 + 判据绿」必须改**冻结面** ⇒ **停下报冲突的判据名与读数**，不许硬改、不许放宽断言、不许改判既有用例凑绿。

## 验收判据（冻结，必须会红）

1. **两侧夹住**：纱帘单 + 该加工项 ⇒ 不再整单失败，且不出现布帘变体；**布帘单** + 同加工项 ⇒ 行为一字不变（插入对应变体）。
2. **类级固化（本单的重点）**：一条判据覆盖「**种子来源的每条规则，其 (operation, position) 组合必须能在其适用形态下解析出变体**」—— 这条要同时罩住 `option` 与 `processing_item` 两条触发维（F4 只罩了前者，所以才有本单）。
3. 红证：把该 `position` 改回 `null` ⇒ 判据 1/2 必须红，读数逐字进 PR body。
4. 不回归：邻域 Java 测试与 `tests/unit_ci_workflows/test_production_catalog_seed.py` 全绿。

## 写面纪律

`CHANGELOG.md` 不许碰（集成方独占，回报给建议文本）；`.github/cases/**` 若需改由本包独占并重渲染（注意与在飞包的 `case_machine_fail_channel_baseline.json` 重锚冲突 ⇒ 若需重锚，**在回报里提示集成方**）；不许碰 `frontend/**`、`schema.sql`、归档迁移、`.agent-presets/**`。
