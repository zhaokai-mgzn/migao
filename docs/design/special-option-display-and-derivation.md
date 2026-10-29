# 特殊选项的「布/纱派生族」口径（issue #8007 立机制；issue #8108 接入「绑带」族）

> **用户裁定（2026-10-28，逐字）**：「特殊选项里的这两项要改，只需要展示**余料带回**即可，
> 后面的 `-布` 和 `-纱` 应该是默认**跟随订单套行的帘种**来决定的，这样语义更清晰」
> 「把项目都审查一下，这个规则要**适用于全系统中**」。
>
> **用户裁定（2026-10-29，逐字；issue #8108）**：「把这两项也合并成一个绑带选项，布/纱是跟随帘种来确定的」
> （「这两项」= 特殊选项里的 `布绑带` / `纱绑带`）—— **完全沿用本文件的机制**，不另发明。

## 1. 问题形态

特殊选项清单里 `余料带回-布` / `余料带回-纱` 并列成两个**可点选项** ⇒ 商家必须自己回答
「这樘窗的余料是布还是纱」；而下单页的明细行**本来就有帘种**（布帘 / 纱帘 / 帘头）。
同一件事在界面上被问了两次，且两个答案可以互相矛盾（纱帘行勾 `-布`）。

本文件描述的机制共承载**两族**（`SPECIAL_OPTION_FAMILIES` 的两行）：

| 语义名（录入 / 展示） | 派生键：布帘 / 帘头 / 缺省 | 派生键：纱帘 | 业务含义 |
|---|---|---|---|
| `余料带回` | `余料带回-布` | `余料带回-纱` | 余料**归客户带走**（不计件） |
| `绑带`（issue #8108） | `布绑带` | `纱绑带` | 车间**工序**语义（触发 `绑带-布` / `绑带-纱`） |

⚠️ **两族共享机制，但业务含义不共享** —— 见 §5.1。

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

- **`布绑带` / `纱绑带` 已纳入本族**（issue #8108 推翻本文件初版在此处的结论）：它们是**同一语义选项的
  两种材料形态**（`布/纱` 跟随帘种），与 `余料带回-布` / `-纱` 同机制。两键**仍是 join key**
  （工序列名 / `trigger_value` / 计件口径一字不动），`绑带` 只做录入 / 展示。
  ⚠️ 仍**不**纳入：`加立边` / `加logo条` / `余料做绑带` —— 它们是各自独立的 ERP 选项名 + 独立工序
  （判据把这一类钉成「非族成员」：`OptionFamilyNamesTest.independentOptionNamesAreNotFamilyMembers` /
  `special-option-names.test.ts` 的同名判据）。
- **族集合是「成对」的类级判据**：`SPECIAL_OPTIONS` 里凡 `X-布`/`X-纱`（后缀）或 `布X`/`纱X`（前缀）
  **成对**出现的名字都必须登记进派生族，否则判据红 —— 防止后人新增第三对变体而忘了登记。
- **水洗唛纸面的「特殊选项」行仍按 join key 原样印**（如 `特殊选项: 余料带回-布、布绑带`）：
  这是 issue #8002 的纸面合同（判据 `frontend/admin-web/tests/unit/components/TaskCardPrint.test.tsx`
  逐字钉住），本文件 §4 第 4 行「水洗唛走 craft-display 一处收敛」的措辞对**该行**并不成立（该行走
  `frontend/admin-web/src/lib/wash-label-content.ts::washLabelSpecialOptions`，与专属唛触发链同源）。是否收敛为语义名属另一次裁定，
  **本次未改**（登记为接受的边界，不冒充已完成）。
- **`绑带` 不能写进订单**：`绑带` 不是 join key（`SPECIAL_OPTION_ROUTINGS` 里没有它）⇒ 订单若直接写它，
  绑带工序会**静默漏插**。故 Agent 写单侧的口径与 `余料带回` **相反**：`order_create` 工具描述要求
  「绑带按该明细行的帘种写 `布绑带` / `纱绑带`」（`余料带回` 则只写语义名，因为它的读侧本就兼容语义名）。
- **裁高配置面的存量规则**：按派生键存储的条件值（如 `布绑带`）在配置面展示为 `绑带`，**保存时写语义名**
  ⇒ 此后该规则对 `布绑带` / `纱绑带` 两种订单值都命中（族匹配口径，与 `余料带回` 一致）。若将来业务要求
  按材料分档（布/纱用不同裁高参数），需另单引入材料维度 —— 当前无该证据，登记为**接受的边界**。
- **存量数据不回填**：历史订单里的 `余料带回-布/-纱` 原样保留（展示收敛、读侧兼容）；新数据由录入边界派生。
- **未覆盖**：配置面「新增特殊选项」自由文本入口仍可手输派生键（见上表 #10）；
  若后续要禁止，建议在研究清楚「配置面 vs 订单面词表分离」后单独开单。
- **展示收敛写在三份同源文件里**（`craft-display.ts` × 3）：这是既有架构约束（三端逐字同源），
  不是新复制；一致性由 `special-option-names.test.ts` + `test_craft_display_same_source.py` 双向钉住。

## 5.1 🔴 「族」是通用容器，「客户带走余料」不是（issue #8108 踩过的坑）

`OptionFamilyNames.isCustomerTakeAway` 决定余料落 `customer_taken`（不进可用池、不可回收 / 不可报废）。
本文件初版实现用「**任一族成员**」判定 —— 在只有 `余料带回` 一族时它恰好正确；`绑带` 族登记进来之后，
**勾绑带的单会被误判成「客户带走余料」= 静默的账错**（而且没有任何东西会因此变红）。

收窄：只认 `余料带回` 族（`CUSTOMER_TAKE_AWAY_FAMILY`）；新增第三族时**默认不是**客户带走，
要它算客户带走必须显式改这一处。

- 实例判据 = `backend/admin-api/src/test/java/com/migao/admin/service/OptionFamilyNamesTest.java`
  的 `customerTakeAwayIsScopedToTheLeftoverFamilyOnly`（含正向对照，防「恒 false」空断言）；
- 服务级判据 = `backend/admin-api/src/test/java/com/migao/admin/service/RemnantServiceTest.java`
  的 `bandingOptionDoesNotMarkRemnantsAsCustomerTaken`（真库：勾 `布绑带` / `纱绑带` 的单余料落 `available`）；
- 红证（注入式，实测）：把 `isCustomerTakeAway` 退回任何「任一族成员」形态 ⇒ 上述两条同时红
  （`Tests run: 15, Failures: 2`）。

## 6. 判据（改坏了会红在哪）

- `frontend/admin-web/tests/unit/lib/special-option-names.test.ts`：两族派生 / 展示收敛 /
  **类级未登记即红（前缀 `布X`/`纱X` 与后缀 `X-布`/`X-纱` 两种形态）**；
- `frontend/admin-web/tests/unit/components/OrderExtraOptions.test.tsx`：**17** 个语义选项
  （19 项 join key 折叠）、无布/纱派生键、按帘种派生；
- `frontend/admin-web/tests/unit/lib/craft-display.test.ts`：展示面收回语义名；
- `frontend/admin-web/tests/unit/components/CuttingHeightConfigPanel.test.tsx`：配置面词表；
- `backend/admin-api/src/test/java/com/migao/admin/service/OptionFamilyNamesTest.java`：读侧族匹配 +
  **「客户带走只认余料带回族」**；
- `backend/admin-api/src/test/java/com/migao/admin/service/RemnantServiceTest.java`：勾绑带的单
  **不**落 `customer_taken`（服务级、真库）；
- `backend/admin-api/src/test/java/com/migao/admin/service/CuttingHeightCalculatorTest.java`：条件按族命中；
- `backend/ai-agent-service/tests/test_production/test_special_options.py`：真值源三分类 + 派生族登记；
- `tests/unit_ci_workflows/test_production_catalog_seed.py`：ERP 三形态显式登记。
