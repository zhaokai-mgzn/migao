# 裁高（定高）配置 · 一体机裁高计算器 · 工人端页面权限 —— 设计单

> **状态**：**设计单 v1（2026-09-29）** —— docs-only、**未落码、未裁定完毕**。母单 **#5161**。
> 与本文冲突时**以文首「本次裁定」为准**。
>
> ## 🔴 本次裁定（用户 2026-09-29，与下文冲突以本节为准）
>
> | # | 裁定（逐字口径） | 落法 |
> |---|---|---|
> | ① | 「**我们一起直接下发参数到生产机器的功能先不做**」 | Modbus 写入 / 机台档案 / 本地小桥 **整体出本期范围**（上游设计单 §3 的 P2/P4 **挂起、不删**） |
> | ② | 「裁高机的报工要支持…**扫码枪扫描我们的水洗唛直接展示订单详情，并允许操作裁高计算器**」 | 一体机 = **屏 + 有线扫码枪**（与壁达形态一致）、**自给自足**；手机扫码是**其他工序**的报工方式 ⇒ **不做跨设备联动**（工位焦点 / 轮询 / SSE 全部不需要） |
> | ③ | 「**根据壁达代码里面的计算公式和参数**进行设计，**不用考虑我的补充项**」 | 配置字段与算法**对齐壁达契约与表达式引擎**（§1）；现场便签的手写值（画线 0.145 / 绑带 0.14·0.16）**不进默认种子** |
> | ④ | 粒度 = **部位级**（帘身 / 纱 / 帘头），增量项**按工艺 / 选项命中** | §2.1 / §2.2 |
> | ⑤ | 工人端页面权限 = **租户级页面开关**起步，预留逐人覆盖 | §2.8 |
> | ⑥ | 「机器支持**三位小数**，用 **2.935**」 | 取整默认 = **保留三位小数**（`rounding.digits=3`）；机器寄存器是整型 mm ⇒ 3 位小数恰好是 mm 精度 |
> | ⑦ | 「我**没有命中规则表**，需要你去读壁达代码」 | 已读：壁达**没有**独立的命中规则表，命中由**三处触发源 + 表达式判定**构成（§1.5）；米高侧**复用既有 `production_route_rules` 触发口径**，不另造 DSL（§2.2） |
> | ⑧ | 计算器里的手改「**只读即可**」 | 手改**只改本次显示**、不落库、不留痕（§2.6） |
>
> **配套（上游，位于本仓库之外的调研工作区 `migao-device-integration/docs/`）**：
> 《裁剪机接入（扫码 → 明细 → 算高 → 串口写入）》·《壁达「定高」算法调研 —— 裁剪高度口径的参照物》·
> 《车间一体机装米高（扫码枪 + 浏览器 + 小桥）》。
> **仓库内真值源**：[../curtain-production-rules.md](../curtain-production-rules.md)（生产/计件）·
> [../curtain-fabric-quote-rules.md](../curtain-fabric-quote-rules.md)（算料）· [../wiki/RBAC.md](../wiki/RBAC.md)。

---

## 0. 一句话结论

本期只做**三件事**：

1. **「裁高配置」tab** —— 把「裁高工序参数」集中成一处（`/production/routings` 的**第三个 tab**，与「算料配置」并列）；
2. **一体机裁高计算器** —— 扫**米高自己的水洗唛** ⇒ 出**订单详情 + 裁高计算器**（命中项预勾、可手改、大字给出要往机器里输的值）；
3. **工人端页面开关** —— 手机 H5 与一体机共用一份**租户级**页面集。

**不写机器、不建机台档案、不做手机↔一体机联动** —— 那三件归上游设计单，等口径与现场取证齐了再做。

**一句话口径**：`裁剪高度(部位) = 成品高 + Σ(命中且启用的增量项)`，其中「哪些项命中」由**规则推导**（不是人工勾选），取值与取整规则**租户级可配**。

---

## 1. 壁达模型取证（本次新增，全部可复算）

**取证方式**（与上游调研同一纪律：**只读符号名与字符串常量，不反编译业务逻辑、不复制实现代码**）：

```bash
cd .scratch/cut-machine/beeda-erp        # 上游 2026-09-22 从壁达官网 ClickOnce 直链取的部署包
python3 - <<'PY'
import re
sym=re.compile(r'[A-Za-z_][A-Za-z0-9_\.]{4,}')
CJK=re.compile(r'[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9_\.\-/（）()：:％%° 【】=]{1,}')
for f in ['bin/BeeDaERP.BussinesServiceProxy.dll.deploy','bin/BeeDaERP.ClientUI-New-SC.exe.deploy',
          'bin/BeedaERP.StringCalculate.dll.deploy']:
    d=open(f,'rb').read()
    S=set(sym.findall(d.decode('utf-8','ignore')))                      # 元数据（符号名）
    C=set(x.strip() for x in CJK.findall(d.decode('utf-16-le','ignore')))  # 用户字符串（UI/帮助文本）
    for k in ['CutHeight','FixHeight','ExpandItem','HeightJoin','Rounding','BangDai','PleatNumber','常量']:
        print('==',f,k,[x for x in sorted(S|C) if k in x][:25])
PY
```

### 1.1 服务端契约里「裁高」那一族（逐字符号）

| 类别 | 符号（逐字） | 含义 |
|---|---|---|
| **实体** | **`RECutHeightProcessParam`** | **「裁高工序参数」** —— 壁达里"裁高"是**有实体、有维护界面**的参数族（对应 `SaveCutHeightProcessParamView/ViewModel`） |
| **表达式** | `HeightFormulaField` · `FixHeightExpressionField` · **`BodyFixHeightExpressionField`** · **`GauzeFixHeightExpressionField`** · `FixHeightQuotationQtyExpressionField` · `BodyFixWidthExpressionField` | **「定高表达式」按部位分设**（Body = 帘身 / Gauze = 纱） |
| **加工类型** | `ProcessTypeFixHeight` | 加工类型 = 定高（对应米高订单行 `cutting_mode`） |
| **高度族** | `ItemHeightField` · `BlindsHeightField` · `FabricHeightField` · `DigitalHeightField` · `CheckHeightField` · `GauzeHeightField` · `BodyHeightField` | 高度是**分部位/分类**的量，不是一个标量 |
| **取整** | `IsRoundingField` · `RoundingAmountField` · `SumRoundingAmountField`（客户端侧 `ChinaRound` / `CalculateRoundingAmount` / `SumRoundingAmount`） | **"是否取整"是开关，取整本身是算法** |
| **机台参数** | `REPLCMachineParam`（`Address` / `AddressCode` / `AddressType` / `FuncCode` / `BaudRate` / `CustomParamList·Names·Id·Str·Controls`） | 地址与功能码**是配置项**；机型差异塞进 `CustomParam*`（上游 §1.8 已录） |
| **部位参数** | `PartFormulaField` · `PartSizeField` · `PartParamInfoField` · `PartItemsField` · `PartNameField` · `PartCategoryField` | 公式与参数**挂到部位** |

### 1.2 「扩展项」（ExpandItem）—— 现场弹窗那些 chip 的真身

| 符号（逐字） | 读出来的语义 |
|---|---|
| `RECurtainOrderExpandItem` · `ExpandItemId` · `ExpandItemIds` · `ExpandItemName` · `ExpandItemNames` · `ExpandItems` · `ExpandItemsName` · `ExpandDetail` | 扩展项**是订单上的实体**（有 id、有名称、可批量），不是硬编码枚举 |
| `ExpandItemNameDisplay` · `SetExpandItemNamesAlias` · `NormalizeExpandItemNames` · `SanitizeExpandItemNames` | 名称有**显示名与别名**，且要**归一化**（⇒ 名称是数据） |
| **`IsHeightJoinExpandItem`** · `AddHeightJoinExpandItem` · `RemoveHeightJoinExpandItem` · **`AddAutoHeightJoinExpandItem`** · **`EnsureAutoHeightJoinForLine`** · `ComponentNameHeightJoin` · `ResolveDefaultHeightJoinProduct` · `HasHeightJoin` | **「加高拼接」是一类扩展项**：可手工加、**可自动补齐**（`Auto`/`Ensure`），并有默认产品解析 |
| `ExpandDirection` · `ValidateExpandItemDirection` · `ExpandGroup` · `ExpandModeProperty` | 扩展项有**方向**（加/减）、**分组**与**模式** |
| **`IsExpandItemsManuallyEdited`** | **人工改过勾选**有显式标记 ⇒ 壁达的主路径里**人工可改**，系统须知道"这是人改的" |
| `ExpandPanelView/Controller/ViewModel` · `CurtainOrderExpandItemView/ViewModel` · `SaveCurtainExpandItemView` · `OpenExpandItemPicker` · `ConfirmExpandDialog` · `QueryQuickCurtainOrderExpandItems` | 有**维护页 + 拣选器 + 维护弹窗**（= 一份**档案**，不是裸常量） |
| **`ExpandItemNameBangDai`** · `ExtractBangDaiFromExpandItemsForLine` · `BangDaiName` · `BangDaiPN` · `BangDaiQty` · `BangDaiCustomerPN` · `BangDaiEqualPN` · UI 文案「工艺绑带 / 普通绑带 / 明细绑带 / 布帘默认补绑带 / 绑带从附加工艺拆出」 | **绑带在壁达里是"扩展项 + 组件"双重身份**（有货号/数量/客户货号）—— 它**不是**定高弹窗里的一个增量 chip |

### 1.3 表达式引擎（`BeedaERP.StringCalculate.dll`）

**能取到什么（函数，逐字）**：`GetComponentPleatNumber`（帮助文本逐字：「**可获得当前部位下所有主布组件的褶数之和**」）·
`GetExpandNameExist`（某扩展项**是否存在**）· `GetPartCustomParamInputValue`（**部位自定义参数输入值**）·
`GetComponentCategory` / `GetComponentCategoryQty` / `GetComponentQty` / `GetComponentQuotationQty` / `GetComponentProductSpec` · `组件类别用料(componentCategory)`。

**语言特性（字符串常量，逐字）**：`保留一位小数_第二位大于0才进一(x)` · `偶数取整(x)` · `取小(...numbers)` · `包含()` ·
`不受前面的use strict 控制 所以得放到code中` · `除/ 小括号() 条件`。

**公式族（客户端字符串，逐字，按加工类型 × 用途 × 部位分设）**：
`定高买宽外帘公式` · `定高买宽纱帘公式` · `定高买宽用料公式` · `定高买宽报价米数公式` · `定宽买高…（同四支）` ·
`帘头公式` · `通用用料公式` · `用料公式` · `单价公式` · `基础数量公式` · `面料宽公式` · `面料高公式` · `面积公式` ·
容错：`用料公式没填默认1` · `行公式错误` · `跳过特殊选项公式回写`。

**公式变量字典（客户端「常量：」串，逐字）**：

```
常量：安装工艺 特殊选项 部位 做法 是否定型
常量：左转角 右转角 粘贴方向 窗宽 窗高 成品宽 成品高 裙摆高度 部位褶距 褶距 褶倍 部位总褶数 部位扣减褶数 主布用料 主布褶数 配布褶数 褶数
部位主布褶数 部位主布幅数 部位主布用料 部位用料 部位配布褶数 部位配布个数 部位配布用料 货号价格 定型费价格 加工类型 部位名称
外帘宽 外帘高 纱帘宽 纱帘高 … 外帘开数 纱帘开数 开数 外帘用料 纱帘用料 …
```

### 1.4 现场弹窗的 chip（照片 1，逐字）与「画线无值」这个事实

`包布折 0.08` · `包布孔 0.1` · `包纱折 0.08` · `包纱孔 0.1` · **`画线`（无值）** · `布贴 0.015` · `纱贴 0.01`；
`升高高度 2.935 米 = 2.92 + 0.015`（本单命中 `布贴`）。

⇒ **「画线」在壁达里是一个"有项无值"的扩展项** —— 这解释了现场为什么要在机器上贴便签（上游照片 2）。
**我们的设计必须能表达"未配置取值"这种状态**（而不是替它编一个数，也不是静默按 0 算）。

### 1.5 🔴 「命中」是怎么来的（回答"没有命中规则表"这一条）

**结论：壁达里没有一张独立的「命中规则表」。** 增量项**命中与否**由三处构成，且**判定入口在表达式引擎**里：

| # | 触发源 | 证据（逐字） | 含义 |
|---|---|---|---|
| **A** | **特殊选项 / 附加工艺** | 符号 `ExtractBangDaiFromExpandItemsForLine` · `ExtractBangDaiFromComponentsForLine` · `ResolveBangDaiUsage`；字符串「绑带从附加工艺拆出 Seq=」「布帘默认补绑带 Seq=」「未匹配到系统附加工艺，跳过」 | 扩展项由**订单上的选项/附加工艺**派生（绑带就是这一路的典型） |
| **B** | **部位限定** | 符号 `ExpandPartFilterItems` · `FillPartItemsByExpandItem` · `ExpandPart` · `ValidateExpandItemDirection` | 同一个扩展项**只对某些部位**生效（布帘/纱帘/帘头） |
| **C** | **接高（加高拼接）** | 符号 `AddAutoHeightJoinExpandItem` · `EnsureAutoHeightJoinForLine` · `ResolveDefaultHeightJoinProduct` · `HasHeightJoin` · `IsHeightJoinExpandItem`；字符串「**货号超高需要接高，但系统特殊选项未配置**」「接高布使用主布2.8门幅货号」「未找到对应2.8门幅，无法生成接高布明细」 | 接高是**自动触发**的：**货号超高** ⇒ 需要接高 ⇒ 且**依赖特殊选项配置**（没配就显式报错，不静默） |
| **判定入口** | 表达式函数 | `ExpandNameExistsComputeMethod`（`GetExpandNameExist`）· `ComponentExistsComputeMethod` · `Contains`（「包含(特殊选项」）· 变量「常量：**安装工艺 特殊选项 部位 做法 是否定型**」 | **命中与否是在公式里判的**：`包含(特殊选项,"X")` / `存在扩展项("X")` ⇒ 这正是"没有独立规则表"的原因 |

**引擎可调用的完整函数族**（`BeedaERP.StringCalculate.dll` 的 `*ComputeMethod`，逐字符号）：
`ComponentExists` / `ExpandNameExists` / **`ComponentPleatNumber`**（褶数之和）· `ComponentCategory` / `ComponentCategoryQty` / `ComponentQty` / `ComponentQuotationQty` ·
`ComponentProductSpec` / `ComponentProductNumber` / `ComponentProductMaterialQuality` / `ComponentProductDesignType` ·
`ComponentPrice` / `ComponentProductPrice` / `ComponentWholeClothPurchasePrice` · `CustomParam`（部位自定义参数）·
`EvenCeil` / `EvenFloor` / `Abs` · `Contains` · `GetDecimalDigit` · 日期族（`DateAdd` / `DateDiff` / `DateFormat` / `DateNow` / `DatePart`）。
中文函数（逐字）：`保留一位小数_第二位大于0才进一(x)` · `偶数取整(x)` · `取小(...numbers)` · `取正(x)` · `向下取整(x)` · `保留小数点后1位(x)` · `包含()` · 「条件语句，条件成立取第一个值，不成立取第二个」。

> **客户端里查不到任何默认取值表**（对 `0.08` / `包布折` 一类串做了全量检索 ⇒ 零命中）⇒ **取值与"选项→项"的对应行都在它服务端**（`SaveCurtainExpandItemView` 那张扩展项档案 + 订单上的选项）。
> ⇒ 我们**拿不到它的行**，但**拿到了它的形态**；「选项/工艺 ↔ 增量项」的对应行必须**现场取证**（§5 第 3 条）。

### 1.6 米高侧**已经有一张同构的"命中"真值源**（可直接复用，不必新造）

`backend/admin-api/src/main/java/com/migao/admin/entity/ProductionRouteRule.java`（表 `production_route_rules`，V71/V72/V77）**就是**「订单选配 → 车间行为」的那张表：

| 列 | 取值 | 与裁高增量项的关系 |
|---|---|---|
| `trigger_kind` | **闭词表** `craft`（工艺）/ `option`（特殊选项）/ `shaped`（定型）/ `processing_item`（加工项）/ 部位维（`trigger_value` = 部位名，写面镜像进 `position`） | 增量项的命中触发源**逐档对得上**壁达的 A 类 |
| `trigger_value` | 工艺名 / 特殊选项名（**逐字 = ERP 写法**，join key） | 命中判据的键 |
| `position` | 布帘 / 纱帘 / 帘头；`NULL` = 不限部位 | 对位壁达的 B 类（部位限定） |
| `priority` | **升序**生效（顺序敏感） | 多触发叠加时的序 |
| `status` | 停用 | 停用语义 |

订单侧选项的取数口也已存在：`ProcessingOrderService.specialOptions(entry)`（`processingInfo.specialOptions: string[]`，归一化 = 只认字符串数组、去重保序）。

⇒ **设计取舍（最少代码阶梯：复用优先）**：裁高增量项**不新造一套命中 DSL**，而是**复用同一份触发口径**（`trigger_kind` + `trigger_value` + `position`），
并给条目留一个**条件表达式兜底**（对位壁达的 `包含(特殊选项,…)`）。判据：**出现第二份触发匹配实现 ⇒ 红**（§3-3）。

---

## 2. 对齐设计（米高侧）

### 2.1 壁达 → 米高 对位表（**照抄形态，数据源用米高**）

| 壁达（§1 取证） | 米高「裁高配置」 | 备注 |
|---|---|---|
| `RECutHeightProcessParam`（裁高工序参数） | 配置的**根对象**（租户级单行） | 术语对齐：对外叫「裁剪高度」，文档注明 = 壁达「定高」 |
| `BodyFixHeightExpression` / `GauzeFixHeightExpression` / `FixHeightExpression` | `formulas[]`：**加工类型 × 部位** 各一条表达式 | 裁定④：部位级 |
| 扩展项 `ExpandItem*` | `items[]`：**增量项档案**（名称 + 取值 + 部位 + 命中条件 + 方向） | 弹窗 chip 的落点 |
| `IsHeightJoinExpandItem` / `AddAutoHeightJoinExpandItem` / `EnsureAutoHeightJoinForLine` | `items[].height_join` + `items[].auto_ensure` | 「加高拼接」是**一类**增量项，且可**自动补齐** |
| `IsExpandItemsManuallyEdited` | `items[].hit`（**复用既有触发口径，默认自动推导**）+ 计算器里手改**只读展示** | 人工勾选降级为**例外路径**（上游裁定②）；手改按裁定⑧**不落库** |
| `ExpandDirection` | `items[].direction = add \| subtract` | 支持减项 |
| `IsRounding` + `保留一位小数…` / `偶数取整` | `rounding { mode, digits }`（显式可配） | 机器寄存器是**整型 mm**，取整必须显式 |
| 「常量：」变量字典 / `GetComponentPleatNumber` / `GetExpandNameExist` | `vars` 字典 + `has_item(key)` / `pleat_count` | **第一版只启用米高能逐字供数的子集** |
| `GetPartCustomParamInputValue`（部位自定义参数） | `vars.part_custom[]`（**留位，第一版不启用**） | 壁达"逐台/逐部位可配"的入口 |
| `REPLCMachineParam`（地址/功能码/波特率/CustomParam） | —— **本期不做**（裁定①） | 上游设计单已完整登记 |

### 2.2 配置对象（一份 JSON，租户级单行）

```jsonc
{
  "formulas": [
    { "cutting_mode": "定高买宽", "position": "布帘", "expr": "成品高 + 命中增量合计" },
    { "cutting_mode": "定高买宽", "position": "纱帘", "expr": "成品高 + 命中增量合计" },
    { "cutting_mode": "定高买宽", "position": "帘头", "expr": "成品高 + 命中增量合计" }
  ],
  "items": [
    { "key": "baobuzhe", "name": "包布折", "value": 0.08, "direction": "add",
      "applies_to": ["布帘"], "height_join": false,
      "hit": { "trigger_kind": "option", "trigger_value": "包布折", "position": "布帘" },
      "hit_expr": null,
      "enabled": true, "order": 10 }
  ],
  "rounding": { "mode": "half_up", "digits": 3 }
}
```

- `hit` = **复用 `production_route_rules` 的触发口径**（§1.6）：`trigger_kind ∈ {craft, option, shaped, processing_item}` × `trigger_value`（逐字）× `position`（部位限定）。
- `hit_expr` = **兜底**（默认 `null`）：只有当触发口径表达不了时才写条件表达式（对位壁达 `包含(特殊选项,…)` / `存在扩展项(…)`）。
  **两个都填 ⇒ 422**（避免两套判据漂移）。
- `rounding` = **保留三位小数**（裁定⑥：机器三位小数、用 2.935；`digits=3` 恰为 mm 精度）。

**默认种子 = 壁达现场弹窗那 7 项**（值取现场弹窗，§1.4）：

| key | 名称 | 值 | 部位 | 说明 |
|---|---|---|---|---|
| `baobuzhe` | 包布折 | 0.08 | 布帘 | |
| `baobukong` | 包布孔 | 0.1 | 布帘 | |
| `baoshazhe` | 包纱折 | 0.08 | 纱帘 | |
| `baoshakong` | 包纱孔 | 0.1 | 纱帘 | |
| `huaxian` | 画线 | **未配置** | 布帘/纱帘 | ⚠️ **有项无值**，与壁达现场一致；不替它编数 |
| `butie` | 布贴 | 0.015 | 布帘 | |
| `shatie` | 纱贴 | 0.01 | 纱帘 | |

⚠️ **现场便签的三个手写值不进默认种子**（裁定③）。需要时由商家在**同一份档案**里**自建条目**（schema 已支持 `direction` / `height_join` / `applies_to`），**不改代码**。
⚠️ **默认种子只落一处** + 一条对账判据（见 §3-7）—— 第二份会漂的默认值 = 上游设计单最忌讳的形态。

### 2.3 计算口径（单一真值：服务端算，前端只渲染）

```
裁剪高度(部位) = eval(formulas[加工类型][部位], vars)
兜底（无配置）：裁剪高度(部位) = 成品高 + Σ(命中且启用的 items × direction)
```

- `vars` **逐字取库/取快照**（成品宽高、褶倍、褶数、开数、安装工艺、特殊选项、部位备注、部位定型…），
  **禁止在 Java 侧重算**（沿用「算料/规格单一真值」纪律）。
- **命中推导**（裁定④ + §1.6）：按 `hit` 触发口径求值（部位 × 工艺 × 特殊选项 × 加工项 × 是否定型），**复用 `production_route_rules` 那一份匹配实现**；表达不了的场景才走 `hit_expr`。
- **取整**：`rounding` 决定输出，**默认保留三位小数**（裁定⑥：机器三位小数、用 `2.935`）；**未配置取整 ⇒ 显式告警**，不隐式取整。
- **缺项必须显式**：成品高缺失 / 项未配置取值 / 越界 —— 一律**指名报缺**，绝不静默按 0 算（这正是现场便签存在的原因）。

### 2.4 与算料的关系（**两套公式，禁止互相替代**）

算料引擎的「每幅长 = 窗高 + 上下卷边」（`backend/ai-agent-service/app/tools/curtain_calc.py` 的 `HEM_MARGIN = 0.3`）是**买布幅长**，
**不是**机器要的**裁剪高度**。判据见 §3-2。

### 2.5 端点与存储（**复用算料配置那一整套，不新建第二套机制**）

| 件 | 形态 | 先例（同仓库） |
|---|---|---|
| 存储 | 单行租户配置表（`uk_..._tenant` 唯一）+ 变更进既有租户参数审计（`V131__create_tenant_param_audit.sql`） | `craft_calc_configs` |
| 读 | `GET /api/admin/production/cutting-height-config`（**`production:view`**） | `CraftCalcConfigController#get` |
| 写 | `PUT`（**`processing:manage`**，**全量替换** + 缺键/未知键/非法值 **422 逐条理由**） | `CraftCalcConfigService` |
| 默认值 | 读面回 `source = stored \| default`；未配置 ⇒ 明确显示「当前使用系统默认」 | 同上 |
| 预览 | `POST /api/admin/production/cutting-height/preview`（body = 一单 / 一部位）⇒ **逐项命中明细** | 配置页 §22 P3「改动可预演」 |
| 工人面 | `GET /api/worker/production/cutting-height?token=…`（**复用扫码 token 定位部位**） | `/api/worker/production/scan` |

### 2.6 一体机裁高计算器（前端，本期唯一交付形态）

```
扫水洗唛（扫码枪 = 键盘楔；码 = 我们已印的短链 /s/<短码> 或 token）
  → GET /api/worker/production/scan?token=…            （**已有端点**，补字段见 §2.7）
  → 屏一 · 订单详情：品牌/收货人/款式/套数/宽高/加工类型/安装工艺/褶倍/用料/部位备注
  → 屏二 · 裁高计算器：部位切换 + 成品高 + 命中项预勾 + 手改 + 实时合计 + 取整结果
  → 大字：「请在机器屏输入 2.935 米」；失败/缺项**显式报缺**
```

- **不写机器**（裁定①）：本期终点 = 「给人一个**可核对**的数」。
- 扫码枪三条工程要点（上游已取证）：**不依赖 `focus()`**（HID 输入直接进 keydown 缓冲）· 兼容后缀 `CR+LF`/双 Enter · 中文输入法不吃字符。
- 手改（对位 `IsExpandItemsManuallyEdited`）：按裁定⑧ **只读即可** —— 手改**只改本次显示**，**不落库、不留痕**；界面上标出「本次手改」，刷新即回到规则推导值。

### 2.7 扫码响应补字段（既有登记缺口）

`ProductionScanService.resolve` 的 `positions[]` 现只有 3 个键（`order_item_id` / `position_kind` / `position_name`）
⇒ 一体机详情面需补：`width` `height` `craft` `curtain_type` `open_count` `cutting_mode` `fullness` `position_remark` + 用料（算料快照）。
**只加键、不改既有键**；改读面须**同批进契约账本**。

### 2.8 工人端页面权限（裁定⑤）

- **载体**：租户级页面集 `worker_pages`（例如 `["report","order","cut_calc","shipment"]`），与「裁高配置」同族的租户配置；
  `GET /api/worker/me` 下发（与 `/api/auth/me` 的商家菜单**同构**）。
- **一体机**按 `deviceLabel`（worker session 已有）决定露出哪几页；**手机端用同一份开关**。
- 🔴 **红线**：工人页面码**不进** `users.permissions`（那是商家权限）；`worker` 的 `permissions` **恒为 `[]`** 的红证一字不动；
  `/api/admin/**` 对 `worker` 仍 403。工人可达面仍然只有 `/api/worker/**`。
- **同构判据**：工人端页面源必须进机械判据（照 `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py` 的范式：**未登记即红**）。

---

## 3. 判据（每条必须能红 —— 不会红的断言 = 空断言）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| 1 | **术语不混用**：界面/文档里「裁剪高度」与「用料米数」不得互相替代 | 任一处以用料米数当裁剪高度 ⇒ 红 |
| 2 | **两套公式分离**：算料输出不得直接当裁高下发 | 把 `hem_margin` 结果当裁高 ⇒ 红 |
| 3 | **命中可复算**：给定订单工艺/选项，命中项集合由**同一份触发口径**（`production_route_rules` 的 `trigger_kind`+`trigger_value`+`position`）复算 | ① 靠人工勾选才得到同一集合 ⇒ 红；② **出现第二份触发匹配实现**（把 `trigger_value` 与选项名再比一遍）⇒ 红 |
| 4 | **未配置显式**：`画线` 这种"有项无值"必须在界面与出参里标出来 | 静默按 0 计 ⇒ 红 |
| 5 | **取整显式**：取整规则进配置且可测 | 隐式取整（含"没配就默认四舍五入"）⇒ 红 |
| 6 | **配置写面 fail-closed**：缺键 / 未知键 / 非法值 ⇒ 422 逐条理由，不静默回退默认 | 缺键被按默认值存 ⇒ 红 |
| 7 | **默认种子单一真值**：7 项种子全仓只在一处；改一处即全绿 | 第二份默认值出现（且漂移未被发现）⇒ 红 |
| 8 | **计算器不写机器**：本期任何路径都不得写寄存器 / 开串口 | 出现串口/Modbus 调用 ⇒ 红 |
| 9 | **工人零商家权限**：工人 token 调 `/api/admin/**`（含无注解端点）⇒ 403；工人页面码不出现在商家权限目录 | 200 或码出现在目录 ⇒ 红 |
| 10 | **页面不可直达**：未授权页面直接访问 ⇒ 拒绝（藏菜单不算） | 能直达 ⇒ 红 |
| 11 | **详情字段逐字取库**：一体机详情面不在 Java 侧重算算料 | 出现第二份算料实现 ⇒ 红 |

---

## 4. 明确不做（本期）

- ❌ **不写机器**：Modbus RTU / 串口 / 机台档案 / 本地小桥 / 一次性下发 token —— 全部归上游设计单（裁定①）。
- ❌ **不做手机 ↔ 一体机联动**：工位焦点、轮询 cursor、SSE / WebSocket 一律不做（裁定②）。
- ❌ **不照抄壁达的「人工勾选」为主路径**：主路径是规则推导；手改是例外路径。
- ❌ **不复制壁达实现代码**：只对齐**字段语义与形态**（纪律与上游取证一致）。
- ❌ **不把便签手写值写进默认种子**（裁定③）；需要就在档案里自建条目。
- ❌ **不新增商家权限码**、不动 `/api/admin/**` 的 worker 拒绝集合。

## 5. 待裁定 / 待现场

| # | 事项 | 现状 | 谁/何时 |
|---|---|---|---|
| 1 | ~~取整规则默认值~~ | ✅ **已裁定（⑥）**：保留三位小数（`2.935`） | — |
| 2 | 每项**增量值的来源**（0.08 / 0.1 / 0.015 是租户级还是机型级） | 现场照片给出**本租户当前值**；层级未证；**客户端里查不到任何默认表**（§1.5）⇒ 只在它服务端 | 现场 / 壁达实施方 |
| 3 | 「**选项/工艺 ↔ 增量项**」的对应行 | ✅ 机制已定位（§1.5/§1.6：壁达无独立表，靠特殊选项/附加工艺 + 部位 + 接高；米高复用 `production_route_rules`）；**对应行本身**仍只有弹窗那一单的实证 | 现场对照几单反推（客户口径） |
| 4 | ~~手改是否落库留痕~~ | ✅ **已裁定（⑧）**：只读，不落库 | — |
| 5 | 一体机是否需要**工号 PIN 登录**（读面是否匿名） | 照抄上游「工号+PIN 一次性登录」 | 现场试用后定 |
| 6 | **接高**（`height_join`）第一版是否启用 | 已进 schema（对位 `IsHeightJoinExpandItem`），触发条件是「货号超高 + 特殊选项配置」 | 有接高单再做 |

## 6. 分期与并行边界（按文件所有权切包）

| 期 | 内容 | 写路径 |
|---|---|---|
| **P0-A** | 裁高配置：表 + service + controller + 默认种子 + 预览端点 | 后端新增文件（与 `CraftCalcConfig*` **同族不同文件**） |
| **P0-B** | `routings/page.tsx` 新增第三 tab「裁高配置」（复用同一 tab/表单/预览范式） | 前端**单包独占**该文件 |
| **P0-C** | 扫码响应补明细字段（**只加键**）+ 契约账本 | `ProductionScanService` + 契约账本 |
| **P0-D** | 一体机页面（kiosk + 常驻扫码 + 裁高计算器） | `frontend/worker-h5` 新增文件 |
| **P0-E** | 工人端页面开关 + `/api/worker/me` + 前端守卫 + 同构判据 | worker 域 |
| **P1（挂起）** | 下发链路（Modbus / 机台档案 / 小桥） | 见上游设计单 §3 P2/P4 |
