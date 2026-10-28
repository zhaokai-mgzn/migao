# 特殊选项的「布/纱派生族」口径（issue #8007）

> **用户裁定（2026-10-28，逐字）**：「特殊选项里的这两项要改，只需要展示**余料带回**即可，
> 后面的 `-布` 和 `-纱` 应该是默认**跟随订单套行的帘种**来决定的，这样语义更清晰」
> 「把项目都审查一下，这个规则要**适用于全系统中**」。

## 1. 问题形态

特殊选项清单里 `余料带回-布` / `余料带回-纱` 并列成两个**可点选项** ⇒ 商家必须自己回答
「这樘窗的余料是布还是纱」；而下单页的明细行**本来就有帘种**（布帘 / 纱帘 / 帘头）。
同一件事在界面上被问了两次，且两个答案可以互相矛盾（纱帘行勾 `-布`）。

## 2. 口径（全系统三条）

| # | 口径 | 判据形态 |
|---|---|---|
| **1** | **录入 / 展示只出现 base 名**（`余料带回`） | UI 词表里不含 `-布` / `-纱`（`OrderExtraOptions` / 裁高面板 / 下拉项） |
| **2** | **落库键由明细行帘种派生**：纱帘 ⇒ `-纱`；布帘 / 帘头 / 缺省 ⇒ `-布` | 勾选后 `processingInfo.specialOptions` 逐值断言；切帘体后旧键跟着换 |
| **3** | **join key 与工资口径一字不动**；读侧认语义名与两种派生键 | 注册表（`NON_PIECEWORK_OPTIONS`）仍是两个派生键；余料客户带走与裁高条件匹配都命中两种写法 |

**为什么不做「存储层只存 base 名」**：`specialOptions` 是「订单选配 → 车间工序 / 计件」的 join key，
`余料带回-布/-纱` 是**已发布迁移与历史订单**在用的值。改存储口径 = 迁移 + 工资面重算，
收益只是省一次派生 —— 不值（用户要的是**语义清晰**，不是换 key）。派生只在**边界**发生。

## 3. 承载体（单一真值，别抄第二份）

| 面 | 位置 |
|---|---|
| 前端**录入派生** + 展示词表 | `frontend/admin-web/src/lib/order-craft-fields.ts::SPECIAL_OPTION_FAMILIES` / `specialOptionDisplayOptions()` / `resolveSpecialOptionName()` / `derivedSpecialOptionValues()` |
| 前端**展示收敛**（订单详情 / 加工单屏幕 / 打印 / 水洗唛 / 三端小程序） | `craft-display.ts::optionList`（三端**逐字同源**，由 `tests/unit_ci_workflows/test_craft_display_same_source.py` 钉住） |
| 后端**读侧兼容**（余料客户带走、裁高条件匹配） | `backend/admin-api/src/main/java/com/migao/admin/service/OptionFamilyNames.java` |
| Agent 真值源镜像 | `backend/ai-agent-service/app/production/routing.py::SPECIAL_OPTION_FAMILIES`（+ 订单工具描述里的「不要写 -布/-纱」） |
| 行业真值源说明 | `docs/curtain-production-rules.md` §1【默】特殊选项清单 |

## 4. 全系统审查（哪些面查过、结论是什么）

| # | 面 | 结论 / 处置 |
|---|---|---|
| 1 | 下单页「特殊选项」toggle（`OrderExtraOptions`） | ✅ 改为 18 个语义选项；按行帘种派生 |
| 2 | 改单弹窗（`EditOrderContentModal`，复用同一组件） | ✅ 传 `curtainType`；存量派生键显示为 base 名 |
| 3 | 裁高配置面板的条件取值 / 预演取值 | ✅ 词表用语义名；后端按族匹配（规则写 base 名命中两种订单值） |
| 4 | 订单详情 / 加工单屏幕 / 打印（含任务卡）/ 水洗唛 | ✅ 走 `craft-display` 一处收敛（无需改各自渲染） |
| 5 | C 端小程序 / B 端小程序（各自 `craft-display` 副本） | ✅ 三端同源文件同批改（逐字一致判据覆盖） |
| 6 | Worker H5 扫码详情 / 机台屏 | ✅ 读同一份快照值，展示经服务端 `special_options`；语义名来源同上（无独立词表） |
| 7 | AI Agent 写单（`order_create` 工具） | ✅ 工具描述显式要求只写 `余料带回`；模型若写派生键或 base 名，读侧都正确 |
| 8 | 余料台账「客户带走」判定 | ✅ 改为族感知（此前 base 名会被漏判 ⇒ 余料误入可用池） |
| 9 | 特殊选项定价（`production_route_rules.customer_unit_price`） | ⚪ 不受影响：`余料带回` 族是**不计件**项，本来就没有定价行（V59/V77 口径） |
| 10 | 工艺路线规则「新增特殊选项」自由文本 | ⚪ 未改：该入口建的是「选项 → 工序」规则，`余料带回` 无工序可挂；本轮不引入新的名字校验（登记为边界） |

## 5. 边界（如实登记）

- **`布绑带` / `纱绑带` 不纳入本族**：它们是**两个独立选项名**（各自对应独立工序与 join key），
  且 `布/纱` 是**特征名的一部分**，不是同一语义的材料后缀。判据把它们钉成「非族成员」
  （`OptionFamilyNamesTest` / `special-option-names.test.ts`），防止后人「顺手也折叠一下」改坏工资 key。
- **存量数据不回填**：历史订单里的 `余料带回-布/-纱` 原样保留（展示收敛、读侧兼容）；新数据由录入边界派生。
- **未覆盖**：配置面「新增特殊选项」自由文本入口仍可手输派生键（见上表 #10）；
  若后续要禁止，建议在研究清楚「配置面 vs 订单面词表分离」后单独开单。
- **展示收敛写在三份同源文件里**（`craft-display.ts` × 3）：这是既有架构约束（三端逐字同源），
  不是新复制；一致性由 `special-option-names.test.ts` + `test_craft_display_same_source.py` 双向钉住。

## 6. 判据（改坏了会红在哪）

- `frontend/admin-web/tests/unit/lib/special-option-names.test.ts`：派生 / 展示收敛 / **类级未登记即红**；
- `frontend/admin-web/tests/unit/components/OrderExtraOptions.test.tsx`：18 项、无 `-布/-纱`、按帘种派生；
- `frontend/admin-web/tests/unit/lib/craft-display.test.ts`：展示面收回语义名；
- `frontend/admin-web/tests/unit/components/CuttingHeightConfigPanel.test.tsx`：配置面词表；
- `backend/admin-api/src/test/java/com/migao/admin/service/OptionFamilyNamesTest.java`：读侧族匹配；
- `backend/admin-api/src/test/java/com/migao/admin/service/CuttingHeightCalculatorTest.java`：条件按族命中；
- `backend/ai-agent-service/tests/test_production/test_special_options.py`：真值源三分类 + 派生族登记；
- `tests/unit_ci_workflows/test_production_catalog_seed.py`：ERP 三形态显式登记。
