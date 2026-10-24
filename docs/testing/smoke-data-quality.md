# 冒烟数据质量规范（SDQS · Smoke Data Quality Standard）

> **状态**：生效（2026-10-24）。**触发**：用户裁定「冒烟的数据质量不合格，商品 SKU 都没有，
> 应该把冒烟的数据质量规范定下来做到研发模式中，后续按这个规范执行」。
> **一句话**：**冒烟绿 ≠ 页面渲染出来了；冒烟绿 = 页面渲染出来了 + 数据是业务上能用的 + 证据能证明这一点。**
> **本文是唯一真值源**；`scripts/smoke_data_quality.py` 是它的可执行判据，
> `tests/unit_ci_workflows/test_smoke_data_quality.py` 是判据的守卫（判据自己不许变成空判据）。

---

## 0. 为什么会有这份规范（现取读数，不是假说）

2026-10-23 在**本机真栈 + 云 dev RDS（租户 46）**跑 `./scripts/ui_smoke_merchant.sh`：

| 读数 | 来源 |
|---|---|
| 汇总 **33/33 通过、0 失败、0 skip** | `acceptance/2026-10-24/merchant-ui-smoke-t46/out/smoke-summary.md` |
| 自造商品「冒烟SKU商品…」**没有 SKU 行**（建品旅程只填标题 + 一档门幅，存草稿） | `scripts/ui-smoke-merchant/spec.mjs::productsNew` |
| 商品列表截图停在 **「加载中…」**，旅程却已记「渲染 1 行」 | `acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/08-products-list.png` |
| 客户详情「无客户可进详情」也记 ✅；商品列表「列表为空（允许）」也记 ✅ | `spec.mjs::customerDetailJourney` / `productsList` |

⇒ 这份「33/33 全绿」证明的是**页面渲染**，不是**数据可用**。把它当回归结论，
下一个「SKU 选择 / 价格本 / 采购单 / 加工单」的真实缺陷会照样漏过去 —— 这是**假绿的
数据版本**：页面是真的，数据是空的，而判据看不出来。

---

## 1. 五个维度（D1 ~ D5）

| 维度 | 定义 | 反面形态（本仓真实发生过） |
|---|---|---|
| **D1 完整性** | 被测对象的关键字段非空，且**下游链路需要的子对象存在** | 商品有名称/价格，但 `product_skus` **零行** ⇒ SKU 选择、库存、采购、下单选规格全没有数据 |
| **D2 关联性** | 外键对象存在、属于本租户、且能按业务规则串起来 | 订单明细指向**已删商品**（404）；建单前置写死外部商品 id，库一换就 422 |
| **D3 一致性与真实性** | 同一字段在**所有数据源**口径一致；数据形态像真实业务（不是 `test`/`abc`/`1`） | 门幅 `2.8米`（带单位）与 `2.8`（canonical）在不同种子文件里并存；加工项用 `proc_item_1` 这种不存在的 id |
| **D4 隔离与可清理** | 自造数据打标记、幂等、跑完清理并**自证**（计数回基线）；不可删的单据登记台账 | 冒烟商品长期留在列表第一页、按创建时间倒序压过种子商品；清理失败只记 note 不判红 |
| **D5 证据质量** | 每条结论都有**机器读数**（API/DB 读回），截图必须拍在数据加载完成之后 | 截图停在「加载中…」；断言只看 `bodyLen > 50`；「无数据可测」被写成通过 |

> **口径**：D1~D3 是「数据够不够用」，D4 是「数据脏不脏」，D5 是「你说得清吗」。
> 缺任一维，冒烟结论都不可复用。

---

## 2. 六条硬规则（每条都能变红；`DQ-*` 是机器代号）

### Q1（`DQ-1`）数据面必须有数据，空态不得冒充通过

- **规则**：相关旅程跑过的实体面，`total == 0` ⇒ **红**。允许空态的场景必须登记在
  「空态台账」（见 §5 的 `empty_ok` 表）并写明**为什么空态也是有效结论**。
- **会红**：`08-products-list` 在「列表 0 行」时记 pass；`21-customer-detail` 在「无客户」时记 pass。
- **判据**：`scripts/smoke_data_quality.py` 的 `DQ-1/DQ-4`。

### Q2（`DQ-2`）冒烟自造的对象必须「像真业务数据」

商品夹具**必须**包含 SKU 矩阵（`product_skus` 行），且每一行带四样：
`colorName` / `doorWidth` / `price > 0` / `stock >= 0`；商品级再带分类、货号、单位、售价。
订单夹具**必须**带明细行 + 收货信息 + 物流；加工项必须来自**本租户目录**（不许写死 id）。

- **会红**：`createProductFixture` 只 POST 商品、不 POST `skus`；`productsNew` 只存草稿。
- **判据**：`DQ-2` + 守卫测试 `test_product_fixture_declares_sku_matrix`。

### Q3（`DQ-3`）取值口径一致（canonical）

- 门幅落库 = **裸数值**（`2.8` / `3.2` / `3.4`）；显示层才加单位（`2.8米`）。
  依据：`frontend/admin-web/src/components/products/SkuMatrix.tsx` 的写入侧 `normalizeDoorWidth`。
- **会红**：`docs/deployment/demo-seed.sql` 的 `product_skus.door_width` 写成 `2.8米`，
  而 `tests/agent_eval/fixtures/xiaobu_eval_seed.sql` 写 `2.8` ⇒ 同一字段两套口径。
- **判据**：`DQ-3` + `test_demo_seed_door_width_is_canonical`。
- **一般化**：任何**枚举 / 单位 / 大小写 / 精度**口径，只许有一个真值源；种子文件是数据源，也要守。

### Q4（`DQ-4`）前置自造，不依赖「共享表的第一行」

- 前置数据**现造**（本趟自己建、跑完清理）；禁止把「列表首个商品 / 第一条订单 / 历史 id」当自己的前置。
- **会红**：写死 `deff0be6…` 商品 id（云库已不存在 ⇒ 422）；取列表首个商品当搜索词（那是别人的对象，
  可能是已删残留 ⇒ 404）。两者都在 2026-10-24 的冒烟修复单里出现过。
- **判据**：审查 + `KNOWN_CONSOLE_ERRORS` 的 404 归因判据；新增夹具必须在 `createProductFixture`
  同族里**现造 + 清理**（已有范式，照抄，不另发明）。

### Q5（`DQ-5`）清理是断言，不是 best-effort

- 可删对象（商品 / 草稿 / 分类 / 员工 / 加工项）跑完必须删除，并**读回基线**（`404` + 计数回原值）；
  删不掉 ⇒ **判红**（不许只记 note）。
- 不可删对象（订单 / 发货单 / 售后单）不要求删除，但必须**打标记**（名称或备注含 `冒烟` 前缀）
  并登记在当轮 `smoke-data.json` 的 `fixtures` 里 —— 「留下的东西」必须可枚举。
- **会红**：`productsNew` 建完不清理（商品列表长期被「冒烟SKU商品」占据第一行）；
  `cleanupOrder` 失败只记 note。
- **判据**：`DQ-5`（商品残留计数）。

### Q6（`DQ-U`）读不到 ≠ 通过（fail-closed）

- 数据快照缺失 / 采集接口失败 / 字段缺失 ⇒ **退出码 3（不可判定）**，不许当 `0` 读。
- **会红**：spec 没产出 `smoke-data.json`、或商品详情接口 401。
- **判据**：`DQ-U` + 壳脚本「没产出快照 ⇒ 整体判红」。

---

## 3. 三处落地（规范不是文档，是三层判据）

| 层 | 承载体 | 何时生效 | 回归时会怎么红 |
|---|---|---|---|
| **夹具层** | `scripts/ui-smoke-merchant/spec.mjs` 的 `createProductFixture` / `productsNew` | 每次跑冒烟 | 夹具没 SKU ⇒ 快照 `DQ-2` 红 |
| **运行层** | spec 末尾 `collectDataSnapshot()` → `smoke-data.json`；`scripts/smoke_data_quality.py` 判定 | 每次跑冒烟 | 数据不合格 ⇒ 壳脚本退出码非零 + `smoke-data-quality.md` 具名 |
| **守卫层** | `tests/unit_ci_workflows/test_smoke_data_quality.py` | CI / `verify-all.sh gate` | 判据退化成恒真、夹具回退、种子口径漂移 ⇒ 红 |

### 3.1 快照契约（`smoke-data.json`，schema_version = 1）

```jsonc
{
  "schema_version": 1,
  "collected_at": "2026-10-24T07:00:00Z",
  "ran_journeys": ["08-products-list", "09-products-new", "..."],   // 用于收窄规则（局部跑不误红）
  "run": {"journeys_total": 33, "journeys_pass": 33},
  "entities": {
    "products": {"collected": true, "total": 12, "sampled": 12, "with_skus": 5},
    "skus":     {"collected": true, "total": 41, "door_width_noncanonical": 0,
                 "door_width_noncanonical_samples": []},
    "orders":   {"collected": true, "total": 20, "with_items": 20},
    "customers":{"collected": true, "total": 7},
    "after_sales": {"collected": true, "total": 14}
  },
  "fixtures": {"products_created": 2, "products_with_skus": 2, "products_residue": 0,
               "residue_samples": []},
  "collection_errors": []
}
```

- **数据来自管理端 API 现读**（`GET /api/admin/products` / `{id}` / `/orders` / `/customers` /
  `/after-sales`），**不从 DOM 读**：DOM 只证明「渲染了」，证明不了「数据在」。
- 采集不上的面写 `collected: false` + `why`（fail-closed，退出码 3）。

### 3.2 退出码语义（三态，不许互相冒充）

| 码 | 含义 | 汇总里怎么呈现 |
|---|---|---|
| `0` | 数据质量通过（或该面本轮未跑，规则不适用） | `✅ 数据质量：通过` |
| `1` | **数据不合格**（具名 `DQ-*`） | `❌ 数据质量：不合格` + 违规表 |
| `3` | **不可判定** | `⚠️ 数据质量：不可判定`（**不得**当通过） |

> 冒烟整体退出码 = `max(旅程退出码, 数据质量退出码)` 的语义：旅程 `0` + 数据 `1` ⇒ **整体红**。

---

## 4. 本次审计：同一主题下**其他**数据质量问题（一并收口）

| # | 问题 | durable 证据 | 影响 | 处置 |
|---|---|---|---|---|
| 1 | 冒烟自造商品**没有 SKU** | `spec.mjs::createProductFixture` 只 POST 商品级字段 | 下游（SKU 选择/价格本/采购/库存）无数据可测 | **本单修**：夹具补 `skus` 矩阵 |
| 2 | 建品旅程**只存草稿**、建完不清理 | `spec.mjs::productsNew` | 列表被「冒烟SKU商品」污染、按创建时间倒序压过种子 | **本单修**：填矩阵 + 读回 + 清理 |
| 3 | 空态被记成通过 | `productsList`「列表为空（允许）」；`customerDetailJourney`「无客户可进详情」 | 数据为空时 33/33 仍绿（**本次投诉的根**） | **本单**改由 `DQ-1/DQ-4` 判红；旅程内文案同步收紧 |
| 4 | 截图拍在「加载中…」 | `08-products-list.png`（列表 spinner 仍在转） | 证据不能证明数据出现 | 规范 D5：截图前必须等 settled（见 §5 自检 ③） |
| 5 | 种子门幅口径两套 | `demo-seed.sql` 用 `2.8米`；`xiaobu_eval_seed.sql` 用 `2.8` | 按门幅检索/去重在不同数据源结论相反 | **本单修** demo-seed；`DQ-3` 守卫 |
| 6 | 建单前置写死外部商品 id | 修复单 #7580 缺陷 2（云库已无该 id） | 422 假红 | 已在 #7580 改「现取 + 排除冒烟自造件」；规范 Q4 固化 |
| 7 | 冒烟默认跑**共享云库**（租户 46） | `scripts/ui_smoke_merchant.sh`（`PHONE=13900001025`，staging 同账号） | 数据不受控、跨轮残留、别人的对象混入 | **登记**：短中期以「快照体检 + 清理自证」兜住；长期见 §6 未固化项 |
| 8 | 环境数据本身不合格 | #7580 顺带发现：租户 46 `logo` 域名 NXDOMAIN；租户 1 无工艺路线/岗位 | 每页破图、加工单/员工页结构性不可用 | 已由 #7580 置空 logo；规范 §5 增加「环境前置体检」 |
| 9 | **demo-seed 商品状态落在应用枚举外**（`active` 不在 `draft/under_review/on_sale/off_sale` 里） | `docs/deployment/demo-seed.sql` 的 products 段；`ProductService.STATUS_TRANSITIONS` | 演示租户商品在按 `on_sale` 过滤的列表/库存预警里查不到，状态变更走 recovery 分支 | **已修**（#7585 改 `on_sale`）+ **判据**（#7583）：枚举**现取** `ProductService.STATUS_TRANSITIONS`，越界即红 |
| 10 | demo-seed SKU 矩阵残缺（`p-zg-002` 三颜色 0 SKU；`p-zg-001` 三颜色仅 1 行） | `docs/deployment/demo-seed.sql` 的 `product_colors` / `product_skus` 段 | 「颜色 × 门幅」在演示环境选不全 | **已修**（#7583）：8 色 × 门幅 = 14 行逐行显式 + 判据（每色有 SKU / 字段有效） |
| 11 | demo-seed 金额链不闭合（总额 ≠ 明细合计；有单无明细；明细单价 ≠ SKU 价） | `docs/deployment/demo-seed.sql` 的 orders / order_items 段 | 对账/报表读数是错的 | **已修**（#7583）：4 单 6 明细全部闭合 + 判据（总额=Σ明细 / 单价∈SKU 价集 / 无空明细 / 已收≤总额） |
| 12 | P1 API 冒烟对**生产**写入、断言接受 5xx、无清理 | `.github/workflows/nightly-verification.yml` 的 `smoke-p1`；`tests/smoke/test_10_aftersales_notifications.py` | 生产库残留测试单；500 也能绿 | **部分修**（#7583）：**禁 5xx 已落地**（两个用例收紧 + 类级判据 G）；「finally 复探/清理」与「生产写入口径」见 §6 未固化第 6 条 |
| 13 | 种子核对只数 `products`；SKU 段可静默 0 行 | `scripts/eval_stack_seed.sh` 的「数据核对」段 | 夹具缺数据时评测假红/假绿 | **已修**（#7583）：五类计数（商品/颜色/SKU/用户/金额）0 行即非零退出 + 判据（stub `docker` 跑真脚本） |
| 14 | 失败旅程无截图（`jrun` catch 不拍） | `scripts/ui-smoke-merchant/spec.mjs::jrun` | 抛错旅程零证据 | **已修**（#7583）：`jrun` 的 catch 拍 `<旅程>-failed.png` 并进 evidence + 判据 H |

---

## 5. 执行流程（每次跑冒烟时照此做）

```bash
# ① 跑（壳脚本已内建数据质量体检）
./scripts/ui_smoke_merchant.sh --keep

# ② 看两个汇总（缺任一 = 结论不成立）
#    out/smoke-summary.md            旅程面
#    out/smoke-data-quality.md       数据面（DQ-*）
#    out/smoke-data.json             原始读数（可复算）

# ③ 复算数据面（零成本）
python3 scripts/smoke_data_quality.py --snapshot acceptance/<日期>/<目录>/out/smoke-data.json
```

**发布结论前的自检（五问，缺一条不写「冒烟通过」）**：

1. 数据面 `DQ-*` 是否 `0`？（`1` = 数据不合格，`3` = 不可判定；两者都不是通过）
2. 冒烟自造商品是否**每个都有 SKU**，且至少一条能读回 `price>0`、`stock>=0`？
3. 截图/证据是否拍在**数据加载完成之后**（列表无「加载中…」、详情有 SKU 行）？
4. 可删对象是否清回基线（`products_residue == 0`）？不可删单据是否打标记并登记？
5. 有没有「无数据也记 pass」的旅程？有 ⇒ 要么补数据，要么登记到下面的空态台账。

### 5.1 空态台账（只许缩短）

| 旅程 | 为什么空态是有效结论 | 归口 |
|---|---|---|
| （空） | 本单起，冒烟数据前置由 `DQ-1/DQ-4` 保证非空 ⇒ **默认没有合法空态** | — |

> 新增一条空态豁免必须同时给：**为什么**（业务上确实可能为空）+ **归口 issue** + **撤销条件**。
> 没有这三样 ⇒ 不许加。台账**只许缩短**（与 `migao-dev-flow` §23 的豁免台账同口径）。

---

## 6. 边界与未固化（照实登记，不粉饰）

1. **它判形态，不判业务正确性**：SKU 存在、价格非空 ≠ 价格算对；金额/库存的正确性仍由单测/契约判据负责。
2. **共享云库的隔离没有根治**：当前靠「快照体检 + 清理自证」兜底；根治 = 冒烟专用租户/独立库，
   需要环境侧裁定（属 §30.1 的「需外部输入」类），**本规范不假装已解决**。
3. **订单/发货单不可删是业务事实**：规范只要求「打标记 + 可枚举」，不要求删除；残留 Orders 不进 `DQ-5`。
4. **`DQ-1` 的阈值是「至少 1 件商品有 SKU」**：这是用户投诉形态的对症阈值，不是「数据很好」的证明；
   商品 SKU 覆盖率仍应在 `smoke-data.json` 里如实透出（`with_skus / total`），供人看趋势。
5. **UI 旅程的「空态收紧」尚未全部改完**：本单先落「数据面判红」（`DQ-1/DQ-4`）+ 两个夹具修复；
   其余旅程的 `用词`（如「允许为空」）在下一轮真栈回归时逐个收紧 —— 不假装一次改完。
6. **#7583 仍未收口的两条**（有承载体，不是"已解决"）：
   ① **写用例 `finally` 复探/清理**（P1 冒烟）：本轮只落了「断言禁 5xx」（`test_10` / `test_11` + 判据 G）；
      订单类写用例**创建后不删**的形态仍在（`tests/smoke/test_09_order_lifecycle.py` 多条用例各建一单），
      修它要一次**真实 P1 跑**来验「清理后 `GET 404` + 计数回基线」⇒ 重启条件 = 下一次
      `nightly-verification` 的 `smoke-p1` 手动触发（schedule 当前停用），届时把 cleanup 断言补进同一个判据 G；
   ② **UI 旅程的「空态=pass」与「清理自证」**（`spec.mjs` 的 `categoriesJourney` 未见按钮仍 `done(true)`、
      `financeJourney`/`notificationsJourney`/`corporatePage` 只判 `bodyLen`、`cleanupOrder` 只返回 `res.ok`
      且 16/17/17b/19 四条旅程不清）：这些断言只能在**真栈**（云 dev 库 + 商家账号）上验，
      本轮不做无真栈的"改了就算修"⇒ 重启条件 = 下一次真栈冒烟（`./scripts/ui_smoke_merchant.sh --keep`），
      届时按 SDQS D5/Q1/Q5 逐个收紧并把 `cleanupOrder` 的自证（`GET 404`）补齐。
   ③ **观察项（登记不算缺陷已修）**：建库脚本 `backend/admin-api/src/main/resources/db/init/schema.sql`
      的 `products.status` **默认值**仍是 `active`（应用枚举外）—— 本单只把 seed 的**行**改成 `on_sale`，
      默认值还会给下一条 raw SQL 造出同类「来历不明的行」。改默认值要对**存量库**同批一条
      `ALTER TABLE … SET DEFAULT` 迁移（跨模块、需迁移指纹账本跟随）⇒ 不塞进本单；
      重启条件 = 下一次 schema 迁移批次。

---

## 7. 复算命令（判据 / 红证 / 守卫）

```bash
# 判据守卫（离线，零网络零 DB；红证含注入式判别力自证）
python3 -m pytest tests/unit_ci_workflows/test_smoke_data_quality.py -q
# 活 seed 的数据面判据（状态枚举 / SKU 矩阵 / 金额链 / 评测栈五类计数；同为离线）
python3 -m pytest tests/unit_ci_workflows/test_seed_data_quality.py -q

# 体检器单独跑（任意快照）
python3 scripts/smoke_data_quality.py --snapshot <path>/smoke-data.json --json

# 冒烟 shell 的语法 / 依赖判据（既有）
python3 -m pytest tests/unit_ci_workflows/test_ui_smoke_worktree_deps.py -q
```

**守卫红证（写进 PR body 的那种）**：把 §3.1 好快照里的
`entities.products.with_skus` 改成 `0` ⇒ `DQ-1` 必须判红并报「N 件商品里没有任何一件有 SKU」；
恢复 ⇒ 不红（反向对照）。把 `createProductFixture` 的 `skus:` 字段删掉 ⇒
`test_product_fixture_declares_sku_matrix` 必须红。
