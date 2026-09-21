# case_ids: PP-011
"""web 面工序命名统一的**防复发守卫**（issue #4626，goal「web 面工序命名统一」阶段 4）。

## 与 S1 守卫的关系（**本文件不重写它**）

S1（issue #4621 / `tests/unit_ci_workflows/test_operation_display_name_guard.py`，C1~C4）已把
「受管面必须经由唯一 helper `@/lib/operation-display` 渲染、不得直接渲染变体名」落成判据，
但它的覆盖面是一张**硬编码白名单**（`FACES`）—— S1 的 docstring 自己登记了这条教训：
「**白名单是判据的覆盖面**」。#4630 正是实证：第 4 个消费面（`PieceworkTable.tsx`，读**同一份**
`per_operation`）漏在 `FACES` 之外 ⇒ 界面照旧渲染变体名（`精裁-布`），而**没有任何判据会因此变红**。

本文件补上 S1 缺的三条（判据冻结于 issue #4626 的三条评论）+ issue #4647 补的两条：

| # | 判据 | 形态 | 红证 |
|---|---|---|---|
| ① | FE 源码（**去注释后**）不得出现变体名字面量（`-布` / `-纱`） | 扫 `frontend/admin-web/src/**`（`.ts`/`.tsx`）；豁免逐条登记 | 塞 `'精裁-布'` ⇒ 红 |
| ② | **自维护登记机制**：命中标记的文件必须出现在「受管」或「豁免」之一 | 标记见 `MARKERS`；受管面必须 import 唯一 helper 且不裸渲染 | 新增一个读 `per_operation` 的面而不登记 ⇒ 红；**把米宝会话卡退回裸渲染快照名 ⇒ 红**（#4647 / D1） |
| ③ | 后端 **web 读面成对出现**：`put("operation"` / `put("operation_name"` 必须同文件出现 `logical_name` | 静态兜底（逐键权威在 S1 的 Java 单测里） | 去掉读面的 `logical_name` ⇒ 红 |
| ③b | 后端**文案**不得用拼接拼出变体名（`name + "-布"`） | 扫生产 Java（`.equals`/`.endsWith` 判定式不算）；豁免逐条登记 | 注入 `name + "-布"` ⇒ 红（#4647 / D3） |
| ④ | FE 不得在 JSX 渲染位置取 `library_name`（库口径原名键） | 扫 FE 语料；**含属性位置**（比「只拦子节点」严一格） | 往已豁免的 `routings/page.tsx` 塞 `{op.library_name}` ⇒ 红（#4647 / D5） |

② 是**本单的核心增量**：它按**数据来源**（快照类读面键 / 元素类型）而不是按「#4621 当时改了哪几个
文件」判定覆盖面 ⇒ 下次再漏一个面，CI 直接判红，而不是等人扫（`PieceworkTable` 就是靠人扫才发现的）。

## 判据的形态选择（照实登记，供复核）

- **三条都按词法级去注释后的代码判定**（`//` + `/* */`，**保留字符串字面量**，字符串感知）。
  理由有两面：① 注释里引用旧名做历史说明是**允许**的（本仓多处如此，判据不得把解释性注释判成违规）；
  ② 反过来，**注释也不能充当代码契约** —— ③ 里 `ProductionRoutingReadService` 的 javadoc 提到过
  `logical_name`，若按原文（含注释）判定，则「删一条注释」会让守卫变红、「加一条注释」能让它变绿
  （判据被注释操纵 ⇒ 假红/假绿都不可归因于代码）。
- **① 比 issue 原文严一格**：issue 写「字符串/模板字面量里出现」，本守卫扫**去注释后的代码全域**
  （含 JSX 文本 / `data-testid` / 正则字面量）。更严不会漏判（硬编码在 JSX 文本里同样是变体名漏回
  web），且当前树两处口径同为那 2 处。
- **② 的标记集（实测校准过一次，照实登记）**：初版设想用类型名 `ProductionOperation` 照「工序实例读面」，
  但**实测判别力不够** —— `ProductionProgressTable` / `TaskCardPrint` 并不引用它，它们
  `import type { ProductionPosition } from '@/types'`（`ProductionPosition.operations[]` 才是快照名所在）
  ⇒ 用 `ProductionPosition` 才照得到这两个面。故标记集 = `operation_name` / `per_operation` /
  `ProductionPosition`（消费面容器）+ `ProductionOperation`（元素类型本身，**直接持有** `operation`
  快照名；今天只命中 `types/index.ts`，保留它是为了将来「直接拿元素类型渲染快照名」的新面也被照到）。
  四条标记都用精确词边界：`\\bProductionOperation\\b` **不**匹配 `ProductionOperations` /
  `ProductionOperationUpdateParams` 这类别的类型 —— 泛匹配会把只做类型透传的文件也拖进登记表，
  而登记表越大越容易被「顺手加白」。
  实测命中（去注释后）**5 个文件**：4 个受管面 + `types/index.ts`（豁免，纯类型声明）。
  ⚠️ **该数字随标记口径变化，别照抄**（issue #4642 补 `CatalogOperation` 后命中集变为 7 个文件：
  上述 5 个 + `lib/api.ts`（豁免，纯传输层）+ `routings/page.tsx`（豁免，商家配置页））——
  自证命令：`python3 -m pytest tests/unit_ci_workflows/test_op_name_registry_guard.py -q -k c2_every_marker_hit`。
- **③ 只看「同文件出现」**：这是**静态兜底**（粗判据），不是逐键判据 —— 逐键断言在 S1 的 Java 单测。
- **③b（issue #4647 / D3）补上「文案拼接」这条漏点**：③ 判的是读面**落键**成对，**照不到文案拼接**
  ⇒ 两条非删除路径长期把变体名拼进 422 文案（`ProductionRoutingCommandService` 主线判重
  `name + "-布"` ⇒ **界面可见**；`ProcessingOrderService` 实例化 hint `logicalName + "（库中缺变体 …-布）"`）。
  判据 = 生产 Java 里变体名字面量**不得出现在拼接表达式**里；`x.equals("-布")` / `x.endsWith("-布")`
  是**判定**不是输出 ⇒ 不算违规；部位名取值（`"布帘"`）与变体名**同形不同物** ⇒ 逐条登记豁免。
  **已知边界（如实登记，不粉饰）**：间接拼接（`String suffix = "-布"; … + suffix`）**照不到** ——
  词法级判据无法可靠区分「这个变量后来被拼进文案」。真正的红线在 ③b 的 Java 单测断言上
  （`ProductionRoutingCommandServiceTest` / `ProcessingOrderServiceTest` 直接断言 message / hint
  **不含** `-布` / `-纱`）；本静态判据只兜住「直接写出来」这一形态。

## 反空跑锚点（三条各一 + 一条全局阳性对照）

| 锚点 | 判据 |
|---|---|
| ① 扫描根缺失 | `frontend/admin-web/src` / `backend/admin-api/src/main/java` 不存在 ⇒ 红（**不得**静默跳过） |
| ② 命中集空 | 标记命中集合为空 ⇒ 红（机制已死 ≠ 没问题） |
| ③ 登记表空 | 登记表 / 豁免表为空 ⇒ 红（判据会静默变成「扫了个空表」） |
| ③b / ④ 锚点 | ③b 的豁免表为空 ⇒ 红；④ 的键名常量漂移 ⇒ 红 |
| 全局阳性对照 | helper `operation-display.ts` 必须出现在 ① 的语料里（证明真扫到了我们关心的代码） |

⚠️ **受管表的一次退役（issue #4964）**：洗水码纸面 `TaskCardPrint.tsx` 因**工序摘要退场**从
`MANAGED_FACES` 转入 `EXEMPT_FACES`（理由与过期条件见该条）；S1 的 `FACES` 同批退役 ⇒ 双向漂移断言
仍为空。**这不是放宽判据**：纸面一旦重新渲染工序名，本文件 `_direct_render_hits` 与 S1 的 C5 都会红。

⚠️ **④ 与「不重写 S1」的关系**（issue #4647）：④ 是**新增**判据，与 S1 的 `FACES` 无关；
② 的受管表新增了米宝会话卡 ⇒ 同步加进 S1 的 `FACES`（否则 `_s1_drift` 会红 —— 两处清单必须一致）。

## 边界（本单**不做**）

- **不重写 S1 守卫**：S1 的 `FACES` 一字不动；本文件只做「`FACES` ⊆ 本文件受管表」的**防漂移断言**
  （两处清单漂移 ⇒ 红），把「收口到同一份清单」落成判据而不是搬文件。
- **登记表只许缩短**：豁免条目**过期**（① 的字面量已不在树上 / ② 的文件既未命中标记又无任何直接渲染
  形态 / ③ 的文件已成对）⇒ 红，必须销账；新增条目必须写理由（评审可见）。
- **不碰 `.github/cases/**`**：行为用例 `PP-011` 已覆盖本行为，本单只**引用**它（不触发 Case Trust 缴费）。
- ③ 的豁免是**逐条判断后登记**的（不是一律加白）：两条各自的理由见 `JAVA_EXEMPT`。
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: ① / ② 的扫描面（FE 源码；`.ts` / `.tsx`）
FE_SRC = "frontend/admin-web/src"
#: 工序显示名的**唯一**拼装点（S1 建的；受管面必须 import 它）
HELPER = "frontend/admin-web/src/lib/operation-display.ts"
HELPER_SPECIFIER = "@/lib/operation-display"
REQUIRED_IMPORT = "operationDisplayName"
#: S1 守卫（防漂移断言读它的 `FACES`；本文件**不修改**它）
S1_GUARD = "tests/unit_ci_workflows/test_operation_display_name_guard.py"
#: ③ 的扫描面（Java 生产源码）
JAVA_SRC = "backend/admin-api/src/main/java"

# ── ① 变体名字面量 ────────────────────────────────────────────────────────────

#: 变体名的形态 = 工序名带部位后缀（`精裁-布` / `布三边` 里的 `-布`；`-纱` 同族）
_VARIANT_LITERAL_RE = re.compile(r"-[布纱]")

#: ① 的**显式豁免**（文件, 名称, 理由）—— **只许缩短**：条目过期 ⇒ 红，必须销账。
#: 判据 = 「去注释后的**代码**里不得硬编码变体名」；特殊**选项名**属**另一个词表**（订单工艺选项，
#: 与 `routing.py` 及迁移 V59 ∪ V65 逐字一致），**不是工序名** ⇒ 逐条登记而不是放宽正则。
LITERAL_EXEMPTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "frontend/admin-web/src/lib/order-craft-fields.ts",
        "余料带回-布",
        "**特殊选项名**（订单工艺选项词表，与 `routing.py` / 迁移 V59 ∪ V65 逐字一致）—— "
        "`-布` 在这里是选项名的一部分，不是工序名的部位后缀；web 端只做展示/回传，不得归一成逻辑名",
    ),
    (
        "frontend/admin-web/src/lib/order-craft-fields.ts",
        "余料带回-纱",
        "同上（`余料带回-纱` 是另一个特殊选项名，同一份词表；与工序名的 `-纱` 变体形态同形不同物）",
    ),
)

# ── ② 自维护登记机制 ──────────────────────────────────────────────────────────

#: 「该文件消费了**快照类工序名读面**」的标记（精确键名 / 精确类型名）——
#: 出现任一 ⇒ 该文件必须出现在 `MANAGED_FACES` 或 `EXEMPT_FACES` 里（**未登记即红**）。
MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 报工/工序实例读面的快照名。⚠️ 照实登记：今天 FE **代码**里 0 命中（只在
    # `lib/operation-display.ts` 的注释里被提及）—— 保留它是因为它是读面契约键，
    # 将来有面直接读 `op.operation_name` 时即被照到（**不做逐标记非空断言**：那会逼出一个假豁免）。
    ("operation_name", re.compile(r"\boperation_name\b")),
    ("per_operation", re.compile(r"\bper_operation\b")),          # 计件汇总的快照名
    # 加工单 positions 读面的容器类型（`positions[].operations[].operation` = 快照名）——
    # 实测：`ProductionProgressTable` / `TaskCardPrint` 走的是它（不是 `ProductionOperation`）。
    ("ProductionPosition", re.compile(r"\bProductionPosition\b")),
    # 工序实例的**元素类型**本身（直接持有 `operation` 快照名）；今天只命中 `types/index.ts`，
    # 保留它是为了「直接拿元素类型渲染快照名」的新面也被照到（#4630 的形态）。
    ("ProductionOperation", re.compile(r"\bProductionOperation\b")),
    # **工序库目录读面的元素类型**（`GET /operations-catalog` 的 `groups[].operations[]`）。
    # issue #4642 实测补入：P1 正是从这条路漏过去的 —— 该读面的 `name` 曾返回**库口径变体名**
    # （`精裁-布`），而 `routings/page.tsx` 的孤儿接入弹窗直接 `{op.name}` 渲染它；
    # 标记集里没有 `CatalogOperation` ⇒ 注入一个「读 catalog 的新面」时命中集为空、守卫**不红**
    # （改前实测）。精确词边界：`\bCatalogOperation\b` **不**匹配 `CatalogOperations` 这类别的类型名。
    ("CatalogOperation", re.compile(r"\bCatalogOperation\b")),
    # **米宝会话卡的载荷键**（`production_progress_query` 精简载荷的 `current_operation`）。
    # issue #4647 / D1 实测补入：`components/chat/ProductionProgressCard.tsx` 读的正是这个键，
    # 而它的元素类型是**文件内本地接口** `ProductionCardOperation`（不是上面任何一个标记）
    # ⇒ 标记集照不到它、它也不在任何登记表里 ⇒ **四条判据全绿**（复验方注入实验：把该面退回
    # 裸渲染快照名 `String(currentFields?.operation ?? '')` ⇒ 改前不红）。补标记后该面进受管表。
    ("current_operation", re.compile(r"\bcurrent_operation\b")),
    # 本地元素类型名（同一条漏点的另一形态：将来某个面直接拿这个接口渲染快照名时也被照到）。
    ("ProductionCardOperation", re.compile(r"\bProductionCardOperation\b")),
)

#: **受管面**：必须 import 唯一 helper，且**不得**直接渲染快照名（`.operation` / `operation_name` /
#: 裸 `{operation}`）。这份清单必须覆盖 S1 的 `FACES`（防漂移断言见 C2d）。
MANAGED_FACES: tuple[str, ...] = (
    "frontend/admin-web/src/components/production/ProductionProgressTable.tsx",
    # 🔴 `TaskCardPrint.tsx`（洗水码纸面）**已退役**（issue #4964）：用户 2026-09-21 字段裁定把
    # 「工序摘要」列为**退场项**（工人扫部位码后在 H5 看该部位工序清单，见 issue #4967）⇒ 纸面
    # 一个工序名都不渲染 ⇒ 它不再是「工序名消费面」。S1 的 `FACES` 同步退役（两处清单仍双向一致）。
    # 它**仍命中标记**（`ProductionPosition`）只是因为 props 要取部位/尺寸/码 ⇒ 落 `EXEMPT_FACES`。
    "frontend/admin-web/src/app/(dashboard)/production/piecework/page.tsx",
    "frontend/admin-web/src/components/production/PieceworkTable.tsx",
    # issue #4647 / D1：米宝会话里的**生产进度卡** —— 它渲染 `current_operation`（工人端快照名），
    # 改前**不在任何清单里**（复验方实测四项全 False）⇒ 把它退回裸渲染快照名时四条判据全绿。
    # 今天它已走 `operationDisplayName()`（issue #4643），登记是为了让「下次再退回裸渲染」直接判红。
    "frontend/admin-web/src/components/chat/ProductionProgressCard.tsx",
)

#: **豁免面**（文件, 理由）—— 逐条登记；**过期即红**（只许缩短）。
EXEMPT_FACES: tuple[tuple[str, str], ...] = (
    (
        "frontend/admin-web/src/components/production/TaskCardPrint.tsx",
        "**洗水码纸面**（issue #4964 起**不再印工序**）：用户 2026-09-21 字段裁定把「工序摘要」列为"
        "**退场项**（工人扫部位码后在 H5 看该部位工序清单，见 issue #4967）⇒ 纸面一个工序名都不渲染。"
        "它仍命中标记（`ProductionPosition`）只是因为 props 要取**部位/尺寸/码**，与工序名无关。"
        "⚠️ 因此它**从 `MANAGED_FACES` 退役**（S1 的 `FACES` 同步退役 ⇒ 两处清单仍双向一致）。"
        "**过期即红**：一旦它又开始渲染工序名（`operationDisplayName` / 裸快照名 / 「工序」字样）⇒ "
        "本文件的 `_direct_render_hits` 会命中，且 S1 守卫新增的 **C5** 也判红 —— 确要加回纸面，"
        "必须**同时**把它加回本文件的 `MANAGED_FACES` 与 S1 的 `FACES`。",
    ),
    (
        "frontend/admin-web/src/types/index.ts",
        "**类型契约声明**（`ProductionOperation` / `ProductionPosition` / `per_operation` 的 TS 类型）："
        "只声明字段、**不渲染**任何工序名 ⇒ 没有可管的渲染面；该文件对 `operation` / `operation_name` "
        "的注释已明写「**web 界面不得渲染该键**」（`logical_name` + `position` 也在这里声明）",
    ),
    (
        "frontend/admin-web/src/lib/api.ts",
        "**传输层**（`request.put<ApiResponse<CatalogOperation & OperationPositionsAttachResult>>`）："
        "`CatalogOperation` 只作**泛型参数**声明响应类型，**不渲染**任何工序名（无 JSX、无 `.name` 取值）"
        "⇒ 没有可管的渲染面。它命中标记只是因为「引用了读面的元素类型」这个形态本身",
    ),
    (
        "frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx",
        "**商家配置页**（工艺项矩阵 / 路线主线 / 规则区）。本页工序名的**取值域全是逻辑工序名**："
        "`row.operation`（矩阵行键 = `production_operation_positions.logical_name`）、"
        "`cell.operation`、`step.operation`（`GET /routings` 的主线，读时已归一）、"
        "`newRule.operation`（规则弹窗「目标工序」，取自 `logicalOps`）。"
        "**issue #4642 起 `CatalogOperation` 也落在逻辑名值域**：`GET /operations-catalog` 的 `name` "
        "已是**读时归一后的逻辑名**（库列仍是旧名、另走 `library_name` 且**web 不得渲染**）"
        "⇒ 本页孤儿接入弹窗的 `{op.name}` 渲染的是逻辑名，不再是变体名。"
        "⚠️ 本页**不**进 `MANAGED_FACES` 的理由：它渲染的是**读面已归一**的逻辑名，"
        "不需要（也不该）再经 `operationDisplayName()` 做一次「快照名 → 逻辑名」转换；"
        "真正的判据在服务端（读时归一 + 本守卫③ 的 Java 断言）。"
        "**过期即红**：本页一旦出现直接渲染快照名的形态（`.operation` / `operation_name` / 裸 `{operation}`，"
        "或重新从**快照类**读面取显示名）⇒ `_stale_exempt_faces` 判红，必须销账并转 `MANAGED_FACES`。"
        "（改前本条理由写「该文件当前未被任何标记命中」且只谈 `.operation` 来源 —— "
        "**与代码不符**：它当时渲染的正是 catalog 的 `op.name`，而那正是 P1 的漏点）",
    ),
)

#: 受管面「直接渲染快照名」的三种形态（与 S1 的 C3 同形；**只匹配表达式位置**，
#: 不匹配 `operation-row-…` 这类文案/testid —— 那正是 `data-testid={`operation-row-${op.id}`}` 的误报点）。
_DIRECT_RENDER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("成员访问 .operation", re.compile(r"\.operation\b(?![\w$])")),
    ("快照键 operation_name", re.compile(r"\boperation_name\b")),
    ("裸标识符 {operation}", re.compile(r"\{\s*operation\b(?![\w$])")),
)

# ── ③ 后端 web 读面成对出现 ───────────────────────────────────────────────────

#: web 读面返回「工序名」的落键形态
_JAVA_PUT_RE = re.compile(r'\.put\(\s*"(operation|operation_name)"')
#: 成对键（逻辑工序名）：同文件出现它才算「成对」
JAVA_PAIR_KEY = "logical_name"

#: ③ 的**显式豁免**（文件, 理由）—— 逐条判断后登记（**不是**一律加白）；过期即红。
JAVA_EXEMPT: tuple[tuple[str, str], ...] = (
    (
        "backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingCommandService.java",
        "**规则写面响应**（`POST/PUT /route-rules` 的回执）：`operation` = 规则表存的**逻辑工序名**"
        "（前端规则弹窗「目标工序」取自逻辑名域）⇒ 不是工人端快照名，无需 `logical_name`"
        "（issue #4626 评论明示豁免）",
    ),
    (
        "backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingReadService.java",
        "**规则读面** `ruleView()` 的 `operation` / `after_operation` 取**逻辑工序名**（issue #4643 起"
        "**读时归一**，写面落库前也归一 ⇒ 存量变体名行不再上屏）；`positionView()` 的 `operation`"
        "直接取 `row.getLogicalName()` ⇒ 两处都不是快照名。"
        "⚠️ 本文件**代码里没有** `logical_name` 键（只在 javadoc 里提到）—— 判据按**去注释后的代码**"
        "判定：注释不能充当代码契约（否则删注释 ⇒ 假红、加注释 ⇒ 假绿）。"
        "⚠️ 键集是**冻结判据**（10 键，见 `tests/unit_ci_workflows/test_routing_read_endpoints.py::"
        "test_rule_view_keys_are_frozen_contract`）⇒ 归一**不新增键**，本豁免因此仍然成立",
    ),
)


# ── 词法工具（去注释 + 指纹）──────────────────────────────────────────────────

def _strip_comments(src: str) -> str:
    """剥掉 `//` 与 `/* */` 注释（**字符串/模板字面量内的不剥**，字符串感知）。

    判据自身不得把注释里的反例（「不要渲染 `op.operation`」这类说明）判成违规 —— 那是假红；
    反向同理：注释也不能充当代码契约（见模块 docstring「判据的形态选择」）。
    """
    out: list[str] = []
    i, n = 0, len(src)
    quote: str | None = None
    while i < n:
        ch = src[i]
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _fingerprint(text: str) -> str:
    """内容指纹（issue #4260 红证卫生：**禁 mtime/size** —— 它们会被同秒写入骗过）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── 扫描面（**根缺失 ⇒ 直接失败**：路径漂移不得退化成「静默跳过」= 空跑通过）──────

def _fe_corpus(root: Path) -> list[tuple[str, str]]:
    """FE 语料：`(仓库相对路径, 原文)`；扫描根不存在 ⇒ AssertionError（反空跑锚点 ①）。"""
    base = root / FE_SRC
    if not base.is_dir():
        raise AssertionError(
            f"① / ② 的扫描根不存在：{base} —— 判据必须能扫到 FE 源码，"
            "路径漂移 / 目录被移走 ⇒ 红（**不得**静默跳过 = 空跑通过）"
        )
    out: list[tuple[str, str]] = []
    for path in sorted(base.rglob("*")):
        if path.suffix in (".ts", ".tsx") and path.is_file():
            out.append((path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")))
    return out


def _java_corpus(root: Path) -> list[tuple[str, str]]:
    """Java 语料：`(仓库相对路径, 原文)`；扫描根不存在 ⇒ AssertionError（反空跑锚点 ③）。"""
    base = root / JAVA_SRC
    if not base.is_dir():
        raise AssertionError(
            f"③ 的扫描根不存在：{base} —— 路径漂移 / 目录被移走 ⇒ 红（**不得**静默跳过）"
        )
    return [
        (path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(base.rglob("*.java"))
        if path.is_file()
    ]


# ── ① 判据本体 ───────────────────────────────────────────────────────────────

def _variant_hits(root: Path) -> list[tuple[str, int, str]]:
    """去注释后的 FE 代码里出现 `-布` / `-纱` 的位置（**未扣豁免**）。"""
    hits: list[tuple[str, int, str]] = []
    for rel, text in _fe_corpus(root):
        for lineno, line in enumerate(_strip_comments(text).splitlines(), start=1):
            if _VARIANT_LITERAL_RE.search(line):
                hits.append((rel, lineno, line.strip()))
    return hits


def _unexempted_variant_hits(root: Path) -> list[str]:
    """① 违规：**扣掉逐条登记的豁免名称后**，代码里仍出现 `-布` / `-纱` 的位置。

    逐处扣减（`str.replace` 去掉豁免名称再看剩下的行）而不是「整行命中豁免就跳过」——
    后者会让「同一行里既有豁免名、又有真变体名」这种形态静默漏判。
    """
    allowed: dict[str, list[str]] = {}
    for rel, literal, _reason in LITERAL_EXEMPTIONS:
        allowed.setdefault(rel, []).append(literal)
    offenders: list[str] = []
    for rel, lineno, line in _variant_hits(root):
        rest = line
        for literal in allowed.get(rel, []):
            rest = rest.replace(literal, "")
        if _VARIANT_LITERAL_RE.search(rest):
            offenders.append(f"{rel}:{lineno} 硬编码了变体名：{line}")
    return offenders


def _stale_literal_exemptions(root: Path) -> list[str]:
    """① 过期豁免（**只许缩短**）：文件不存在 / 名称已不在代码里 / 名称压根不是变体名形态 ⇒ 销账。"""
    problems: list[str] = []
    for rel, literal, reason in LITERAL_EXEMPTIONS:
        if not (root / rel).is_file():
            problems.append(f"{rel} 不存在（豁免条目指向漂移路径 ⇒ 该条已失效，销账）")
            continue
        if not _VARIANT_LITERAL_RE.search(literal):
            problems.append(f"{rel} 的豁免名称 `{literal}` 不含 `-布`/`-纱` 形态 ⇒ 不是本判据的豁免对象")
        code = _strip_comments((root / rel).read_text(encoding="utf-8"))
        if literal not in code:
            problems.append(
                f"{rel} 的 `{literal}` 已不在代码里 ⇒ 该豁免**过期**（登记表只许缩短：删掉这一条）"
            )
        if len(reason.strip()) < 10:
            problems.append(f"{rel} 的 `{literal}` 没写理由（新增/保留豁免必须逐条写理由）")
    return problems


# ── ② 判据本体 ───────────────────────────────────────────────────────────────

def _markers_in(code: str) -> list[str]:
    return [name for name, pattern in MARKERS if pattern.search(code)]


def _marker_hits(root: Path) -> dict[str, list[str]]:
    """命中标记的文件 → 标记名（**去注释后**的代码；注释里提及不算消费了读面）。"""
    out: dict[str, list[str]] = {}
    for rel, text in _fe_corpus(root):
        hits = _markers_in(_strip_comments(text))
        if hits:
            out[rel] = hits
    return out


def _unregistered_faces(root: Path) -> list[str]:
    """② 违规：命中标记却既不在受管表、也不在豁免表（**未登记即红** = 自己发现新面）。"""
    registered = set(MANAGED_FACES) | {rel for rel, _reason in EXEMPT_FACES}
    return [
        f"{rel} 命中标记 {hits}，但既不在 MANAGED_FACES 也不在 EXEMPT_FACES"
        for rel, hits in sorted(_marker_hits(root).items())
        if rel not in registered
    ]


def _direct_render_hits(code: str) -> list[str]:
    """受管面里「直接渲染快照名」的命中（返回可读描述）。"""
    found: list[str] = []
    for lineno, line in enumerate(code.splitlines(), start=1):
        for label, pattern in _DIRECT_RENDER_PATTERNS:
            if pattern.search(line):
                found.append(f"{label} @ 第 {lineno} 行：{line.strip()}")
    return found


def _managed_face_violations(root: Path) -> list[str]:
    """② 违规：受管面必须 import 唯一 helper，且不得直接渲染快照名。"""
    offenders: list[str] = []
    for rel in MANAGED_FACES:
        path = root / rel
        if not path.is_file():
            offenders.append(f"{rel} 不存在（受管面路径漂移 ⇒ 红，不得静默跳过）")
            continue
        code = _strip_comments(path.read_text(encoding="utf-8"))
        if HELPER_SPECIFIER not in code or REQUIRED_IMPORT not in code:
            offenders.append(
                f"{rel} 没有从 `{HELPER_SPECIFIER}` 取 `{REQUIRED_IMPORT}` —— "
                "工序显示名必须走**同一份**拼装实现（各页各拼一份必然漂移）"
            )
        for hit in _direct_render_hits(code):
            offenders.append(f"{rel}: 直接渲染了工人端快照名（变体名）—— {hit}")
    return offenders


def _stale_exempt_faces(root: Path) -> list[str]:
    """② 过期豁免（**只许缩短**）：文件不存在 / 理由缺失 / 既未命中标记又无任何直接渲染形态 ⇒ 销账。

    「既未命中标记又无直接渲染形态」= 该文件已不是任何判据的假阳性来源 ⇒ 豁免不再需要。
    """
    problems: list[str] = []
    for rel, reason in EXEMPT_FACES:
        path = root / rel
        if not path.is_file():
            problems.append(f"{rel} 不存在（豁免条目指向漂移路径 ⇒ 该条已失效，销账）")
            continue
        if len(reason.strip()) < 10:
            problems.append(f"{rel} 没写豁免理由（每条豁免都必须写理由）")
        code = _strip_comments(path.read_text(encoding="utf-8"))
        if not _markers_in(code) and not _direct_render_hits(code):
            problems.append(
                f"{rel} 既未命中任何标记、也没有任何直接渲染形态 ⇒ 该豁免**过期**"
                "（登记表只许缩短：删掉这一条）"
            )
    return problems


def _s1_faces(source: str) -> tuple[str, ...]:
    """从 S1 守卫的**源码**里取出 `FACES` 白名单（`ast.literal_eval`，不 import 测试模块）。

    取不到 ⇒ AssertionError（防漂移判据无法判定，**不得**静默跳过）。
    """
    for node in ast.walk(ast.parse(source)):
        targets: list[ast.expr] = []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "FACES":
                return tuple(ast.literal_eval(node.value))
    raise AssertionError(
        f"在 `{S1_GUARD}` 里找不到 `FACES` 赋值 ⇒ 防漂移判据无法判定（S1 守卫被改名/重构了就同步改这里）"
    )


def _s1_drift(s1_source: str) -> list[str]:
    """S1 的 `FACES` 里**没被**本文件受管表覆盖的面（两处清单漂移 ⇒ 非空）。"""
    return sorted(set(_s1_faces(s1_source)) - set(MANAGED_FACES))


def _s1_reverse_drift(s1_source: str) -> list[str]:
    """本文件受管表里**没被** S1 的 `FACES` 覆盖的面（**反方向**的漂移 ⇒ 非空）。

    <p>issue #4647 收口时实测的形态：本文件把会话卡登记进 `MANAGED_FACES` 却**忘了**同步 S1 的
    `FACES` ⇒ 单向的 `_s1_drift` **不红**（它只查 S1 ⊆ 本文件），于是 S1 的 C2/C3 对这个面
    **静默不生效** —— 而 PR 正文里还写着「已同步 S1 的 FACES」（**文档与代码不符**）。
    ⇒ 判据必须是**双向**的：两处清单要么一致，要么显式登记理由（本文件没有该理由 ⇒ 必须一致）。</p>
    """
    return sorted(set(MANAGED_FACES) - set(_s1_faces(s1_source)))


# ── ③ 判据本体 ───────────────────────────────────────────────────────────────

def _java_put_faces(root: Path) -> dict[str, list[str]]:
    """③ 命中：`(仓库相对路径) → 该文件里 web 读面的 `operation` / `operation_name` 落键列表`。"""
    out: dict[str, list[str]] = {}
    for rel, text in _java_corpus(root):
        keys = _JAVA_PUT_RE.findall(_strip_comments(text))
        if keys:
            out[rel] = keys
    return out


def _java_unpaired(root: Path) -> list[str]:
    """③ 违规：出现 `put("operation"` / `put("operation_name"` 却同文件没有 `logical_name`（且未登记豁免）。"""
    exempt = {rel for rel, _reason in JAVA_EXEMPT}
    offenders: list[str] = []
    for rel, keys in sorted(_java_put_faces(root).items()):
        code = _strip_comments((root / rel).read_text(encoding="utf-8"))
        if JAVA_PAIR_KEY in code or rel in exempt:
            continue
        keys_text = '" / "'.join(sorted(set(keys)))
        offenders.append(
            f'{rel}: 有 put("{keys_text}") 但同文件没有 `{JAVA_PAIR_KEY}` —— '
            "web 读面必须成对给出逻辑工序名（否则 web 只能拼出工人端快照名 = 变体名）"
        )
    return offenders


def _stale_java_exemptions(root: Path) -> list[str]:
    """③ 过期豁免（**只许缩短**）：文件不存在 / 理由缺失 / 已不再命中 / 已成对 ⇒ 销账。"""
    problems: list[str] = []
    hits = _java_put_faces(root)
    for rel, reason in JAVA_EXEMPT:
        path = root / rel
        if not path.is_file():
            problems.append(f"{rel} 不存在（豁免条目指向漂移路径 ⇒ 该条已失效，销账）")
            continue
        if len(reason.strip()) < 10:
            problems.append(f"{rel} 没写豁免理由（每条豁免都必须写理由）")
        if rel not in hits:
            problems.append(f"{rel} 已不再有 put(\"operation\") 读面命中 ⇒ 该豁免**过期**（销账）")
        elif JAVA_PAIR_KEY in _strip_comments(path.read_text(encoding="utf-8")):
            problems.append(
                f"{rel} 代码里已经出现 `{JAVA_PAIR_KEY}`（已成对）⇒ 该豁免**过期**（销账）"
            )
    return problems


# ── ③b 后端**文案**不得拼变体名（issue #4647 / D3）─────────────────────────────
#
# 病根（复验实测）：③ 只判「读面**落键**是否成对」⇒ 它**照不到文案拼接**。于是两条**非删除**路径
# 长期把工人端快照名（变体名）拼进 422 文案：
#   ① `ProductionRoutingCommandService` 主线判重：`name + "-布"` ⇒ 界面渲染出「精裁-布」；
#   ② `ProcessingOrderService` 实例化 fail-closed 的 `hint`：`logicalName + "（库中缺变体 …-布）"`。
# 判据 = 生产 Java 源码里**不得用字符串拼接**把变体名拼出来（比较谓词 `.equals()` / `.endsWith()`
# 不算 —— 那是**判定**，不是**输出**）。

#: 变体名形态的字符串字面量：`-布` / `-纱` / `-帘` 开头的后缀，或整串含 `-布`/`-纱`/`-帘`
_JAVA_VARIANT_LITERAL_RE = re.compile(r'"-?[布纱帘]|-[布纱帘]"')
#: 字符串拼接（`+ "…"` 或 `…" +`）；`!=` 里的 `=` 不在其前，故不误判
_JAVA_CONCAT_RE = re.compile(r"\+\s*\"|\"\s*\+")
#: **判定式**（不是输出）：`x.equals("-布")` / `x.endsWith("-布")` / `startsWith` / `contains`
_JAVA_PREDICATE_RE = re.compile(r"\.(equals|endsWith|startsWith|contains)\s*\(")

#: ③b 的**显式豁免**（文件, 字面量, 理由）—— 逐条判断后登记（**不是**一律加白）；过期即红。
JAVA_TEXT_EXEMPT: tuple[tuple[str, str, str], ...] = (
    (
        "backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java",
        '"布帘"',
        "**部位名取值**（`CURTAIN_TYPE_CLOTH = \"布帘\"`，`curtainType` 闭词表的值，同文件另处"
        "做 `Map.of(\"纱\", …, \"主布\", …)` 的**取值**）：它是「部位」，不是「工序名 + 部位后缀」"
        "⇒ 与变体名同形不同物；逐条登记而不是放宽正则（放宽会让 `\"-布\"` 一并漏过）",
    ),
)


def _java_text_concat_hits(root: Path) -> list[tuple[str, int, str]]:
    """生产 Java 里「变体名字面量出现在拼接表达式里」的位置（**未扣豁免**）。"""
    hits: list[tuple[str, int, str]] = []
    for rel, text in _java_corpus(root):
        for lineno, line in enumerate(_strip_comments(text).splitlines(), start=1):
            if not _JAVA_CONCAT_RE.search(line):
                continue
            if _JAVA_PREDICATE_RE.search(line):
                continue
            if _JAVA_VARIANT_LITERAL_RE.search(line):
                hits.append((rel, lineno, line.strip()))
    return hits


def _java_text_concat_offenders(root: Path) -> list[str]:
    """③b 违规：**扣掉逐条登记的豁免字面量后**，拼接表达式里仍出现变体名字面量。

    逐处扣减（`str.replace`）而不是「整行命中豁免就跳过」—— 后者会让「同一行既有豁免字面量、
    又有真变体名」这种形态静默漏判（与 ① 同款）。
    """
    allowed: dict[str, list[str]] = {}
    for rel, literal, _reason in JAVA_TEXT_EXEMPT:
        allowed.setdefault(rel, []).append(literal)
    offenders: list[str] = []
    for rel, lineno, line in _java_text_concat_hits(root):
        rest = line
        for literal in allowed.get(rel, []):
            rest = rest.replace(literal, "")
        if _JAVA_VARIANT_LITERAL_RE.search(rest):
            offenders.append(f"{rel}:{lineno} 把变体名拼进了文案：{line}")
    return offenders


def _stale_java_text_exemptions(root: Path) -> list[str]:
    """③b 过期豁免（**只许缩短**）：文件不存在 / 理由缺失 / 字面量已不在代码里 ⇒ 销账。"""
    problems: list[str] = []
    for rel, literal, reason in JAVA_TEXT_EXEMPT:
        path = root / rel
        if not path.is_file():
            problems.append(f"{rel} 不存在（豁免条目指向漂移路径 ⇒ 该条已失效，销账）")
            continue
        if len(reason.strip()) < 10:
            problems.append(f"{rel} 的 `{literal}` 没写理由（新增/保留豁免必须逐条写理由）")
        if literal not in _strip_comments(path.read_text(encoding="utf-8")):
            problems.append(
                f"{rel} 的 `{literal}` 已不在代码里 ⇒ 该豁免**过期**（登记表只许缩短：删掉这一条）"
            )
    return problems


#: 库口径原名键：**web 界面不得渲染**（issue #4621 / #4642；今天只在 `types/index.ts` 的类型注释里
#: 被提及）。issue #4647 / D5 实测：往**已豁免**的 `routings/page.tsx` 注入 `{op.library_name}` ⇒
#: 判据全绿 ⇒ 该约束改前是**注释级**的。这里补一条机械判据。
LIBRARY_NAME_KEY = "library_name"
#: 取值形态：`{x.library_name}` / `{library_name}` / `{cond && op.library_name}` / `title={x.library_name}`。
#: **比「只拦 JSX 子节点」严一格**（照实登记）：属性位置（tooltip / `data-*`）同属「渲染出去」，
#: 一并拦；代价是它可能误伤纯内部 `data-*` 用法 —— 今天真树 **0 命中**，一旦出现就逐条判断后登记。
#: 形态选择：`{` 与键之间**必须**要么直接是键（`{library_name}`），要么中间有 `.` / `&&` / `||` /
#: `?` 这类**取值算子** —— 这一条把 TS **类型声明**（`{ library_name: string }`，冒号紧跟键名、
#: 中间无算子）排除在外（否则判据会对着 `types/index.ts` 的类型声明恒红）。
_LIBRARY_NAME_JSX_RE = re.compile(r"\{\s*(?:[^}]*?[.&|?]\s*)?library_name\b\s*(?=[,}\s]|$)")


def _library_name_render_hits(root: Path) -> list[str]:
    """FE 源码里「在 JSX 渲染位置取 `library_name`」的位置（**未扣豁免**）。"""
    hits: list[str] = []
    for rel, text in _fe_corpus(root):
        for lineno, line in enumerate(_strip_comments(text).splitlines(), start=1):
            if _LIBRARY_NAME_JSX_RE.search(line):
                hits.append(f"{rel}:{lineno} {line.strip()}")
    return hits


# ── ④ `library_name` 不得渲染（issue #4647 / D5）──────────────────────────────

def test_c4_library_name_is_never_rendered_by_web():
    """④：FE 源码**不得**在 JSX 渲染位置取 `library_name`（库口径原名键）。

    <p>issue #4647 / D5 实测：该约束改前是**注释级**的 —— 往**已豁免**的 `routings/page.tsx`
    注入 `{op.library_name}` ⇒ 判据全绿。本判据把它落成机械判据。</p>
    """
    hits = _library_name_render_hits(REPO_ROOT)
    assert hits == [], (
        "FE 在 JSX 渲染位置取了 `library_name`（库口径原名，如 `精裁-布`）—— 该键**web 不得渲染**"
        "（issue #4621 / #4642）：\n  " + "\n  ".join(hits)
        + "\n处置：渲染读面已归一的 `name`（逻辑名）；库口径原名只作内部寻址/元数据解析"
    )


def test_c4_injected_library_name_render_is_red(tmp_path: Path):
    """④ 注入式红证：往**已豁免**的 `routings/page.tsx` 塞 `{op.library_name}` ⇒ 判红。

    <p>注入面刻意选**已豁免面** —— D5 的漏点正是「豁免表让这个文件整份不受 ② 管，
    而 ① 只管字面量 ⇒ 渲染 `library_name` 无任何判据」。</p>
    """
    rel = "frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx"
    original = (REPO_ROOT / rel).read_text(encoding="utf-8")
    injected = original + "\nconst __leak = <span>{op.library_name}</span>\n"
    assert _fingerprint(injected) != _fingerprint(original), "注入没生效"

    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(injected, encoding="utf-8")

    hits = _library_name_render_hits(tmp_path)
    assert any(rel in h for h in hits), (
        f"注入 `{{op.library_name}}` 后判据**没判红** ⇒ ④ 是空判据（D5 的漏点未被堵住）：{hits}"
    )

    # 阳性对照：还原 ⇒ 变绿（红的归因是那段渲染，不是别的噪声）
    target.write_text(original, encoding="utf-8")
    assert _library_name_render_hits(tmp_path) == [], "还原后仍判红 ⇒ 判据与目标无关（误红）"

    # 还原自证 + 真树仍绿（今天 web 一处都不渲染该键 —— 泄漏是**未来**的风险）
    assert _fingerprint((REPO_ROOT / rel).read_text(encoding="utf-8")) == _fingerprint(original), (
        "真树文件内容变了 ⇒ 红证污染了被测对象（红证只许动**临时副本**）"
    )
    assert _library_name_render_hits(REPO_ROOT) == [], "真树上 ④ 应为绿"


def test_c4_attribute_position_is_also_covered():
    """④ 覆盖面自证（**如实登记**）：属性位置（`title={x.library_name}`）**也**被判据拦下。

    <p>本判据比「只拦 JSX 子节点」严一格 —— 属性位置（tooltip / `data-*`）同属「渲染出去」。
    这条断言把该口径写成可执行真值，避免复核者把它读成「只拦子节点」。</p>
    """
    for sample in (
        "<th title={op.library_name}>工序</th>\n",          # 属性位置
        "const x = <span>{op.library_name}</span>\n",        # 子节点位置
        "const y = <span>{show && op.library_name}</span>\n",  # 表达式位置
        "const z = <span>{library_name}</span>\n",           # 裸键（同一作用域解构出来的）
        "const w = <span>{a ? library_name : ''}</span>\n",  # 三元取值
    ):
        assert _LIBRARY_NAME_JSX_RE.search(sample) is not None, (
            f"样本 `{sample.strip()}` 未被判据命中 ⇒ 覆盖面与 docstring 不符（判据形态漂移了）"
        )
    # 反空跑：**非**取值位置不得命中（否则判据会退化成「见到标识符就红」/ 对着类型声明恒红）
    for negative in (
        "const x = library_name\n",
        "// library_name 是库口径键\n",
        "interface T { library_name: string }\n",
        "type T = { library_name: string }\n",
    ):
        assert _LIBRARY_NAME_JSX_RE.search(negative) is None, (
            f"样本 `{negative.strip()}` 被判据命中 ⇒ 判据过宽（类型声明 / 裸标识符不是渲染位置）"
        )


# ── ① 测试 ───────────────────────────────────────────────────────────────────

def test_c1_fe_code_has_no_variant_name_literals():
    """①：去注释后的 FE 代码里不得硬编码变体名（`-布` / `-纱`），豁免逐条登记。"""
    offenders = _unexempted_variant_hits(REPO_ROOT)
    assert offenders == [], (
        "FE 代码里硬编码了**变体名**（工人端快照名，如 `精裁-布`）—— web 面只显示「逻辑名 · 部位」"
        "（`精裁 · 布帘`）：\n  " + "\n  ".join(offenders)
        + "\n处置：改成从读面取 `logical_name` + `position`（拼装只此一份："
        + HELPER + "）；若确属**另一个词表**（如特殊选项名），逐条登记进 LITERAL_EXEMPTIONS 并写理由"
    )


def test_c1_literal_exemptions_are_registered_and_not_stale():
    """① 豁免登记：逐条有理由、文件真实存在、名称仍在代码里（过期 ⇒ 红 = 只许缩短）。"""
    assert LITERAL_EXEMPTIONS, (
        "① 的豁免表为空 ⇒ 本判据的覆盖面归零（若确已清理干净，请把本断言改成别的非空锚点，"
        "而不是留一张空表）"
    )
    problems = _stale_literal_exemptions(REPO_ROOT)
    assert problems == [], "① 豁免清单有问题：\n  " + "\n  ".join(problems)


def test_c1_injected_variant_literal_is_red(tmp_path: Path):
    """① 注入式红证：往**临时副本**塞 `'精裁-布'` ⇒ 判红；内容指纹自证注入/还原真生效。"""
    rel = "frontend/admin-web/src/components/production/TaskCardPrint.tsx"
    original = (REPO_ROOT / rel).read_text(encoding="utf-8")
    injected = original + "\nconst HARDCODED_VARIANT = '精裁-布'\n"
    assert _fingerprint(injected) != _fingerprint(original), (
        "注入后内容指纹未变 ⇒ 注入没生效（**禁 mtime/size**：它们会被同秒写入骗过）"
    )

    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(injected, encoding="utf-8")

    offenders = _unexempted_variant_hits(tmp_path)
    assert offenders, "注入 `'精裁-布'` 后判据**没判红** ⇒ 守卫是空判据（不会红的断言 = 空断言）"
    assert "精裁-布" in offenders[0], f"注入形态没被认出来：{offenders}"

    # 还原自证：真树文件一字未动（注入只发生在 tmp 副本里）+ 真树判据仍绿
    assert _fingerprint((REPO_ROOT / rel).read_text(encoding="utf-8")) == _fingerprint(original), (
        "真树文件内容变了 ⇒ 红证污染了被测对象（红证只许动**临时副本**）"
    )
    assert _unexempted_variant_hits(REPO_ROOT) == [], "真树上 ① 应为绿（注入没生效或豁免口径漂移）"


# ── ② 测试 ───────────────────────────────────────────────────────────────────

def test_c2_every_marker_hit_is_registered():
    """②：命中标记的文件必须出现在受管表或豁免表里（**未登记即红** = 自己发现新面）。"""
    offenders = _unregistered_faces(REPO_ROOT)
    assert offenders == [], (
        "有文件消费了**快照类工序名读面**（命中标记），却既不在受管表、也不在豁免表里 —— "
        "这正是 #4630 的形态（第 4 个消费面漏在硬编码白名单外，界面照旧渲染变体名而**没人会因此变红**）：\n  "
        + "\n  ".join(offenders)
        + "\n处置：受管（改走 `operationDisplayName()` 后加进 MANAGED_FACES）或豁免（写清理由加进 EXEMPT_FACES）"
    )


def test_c2_managed_faces_use_the_single_helper():
    """② 受管面：必须 import 唯一 helper，且不得直接渲染快照名（复用 S1 C2/C3 的形态）。"""
    offenders = _managed_face_violations(REPO_ROOT)
    assert offenders == [], (
        "受管面的渲染口径违规：\n  " + "\n  ".join(offenders)
        + "\n唯一实现：" + HELPER
    )


def test_c2_exempt_faces_have_reasons_and_are_not_stale():
    """② 豁免登记：逐条有理由、文件存在、仍属「会被判据误伤」的形态（过期 ⇒ 红 = 只许缩短）。"""
    assert EXEMPT_FACES, "② 的豁免表为空 ⇒ 登记机制失去一半（若真无豁免，请把本断言改成别的非空锚点）"
    problems = _stale_exempt_faces(REPO_ROOT)
    assert problems == [], "② 豁免清单有问题：\n  " + "\n  ".join(problems)


def test_c2_registry_covers_s1_faces():
    """② 防漂移（**双向**）：S1 的 `FACES` 与本文件受管表必须**互相覆盖**（两处清单不得漂移）。"""
    source = (REPO_ROOT / S1_GUARD).read_text(encoding="utf-8")
    drift = _s1_drift(source)
    assert drift == [], (
        f"`{S1_GUARD}` 的 FACES 里有面没被本文件的 MANAGED_FACES 覆盖：{drift} —— "
        "两份清单漂移时，S1 会管住一个面而本文件不管（或反之）⇒ 覆盖面出现静默缺口"
    )
    reverse = _s1_reverse_drift(source)
    assert reverse == [], (
        f"本文件的 MANAGED_FACES 里有面没被 `{S1_GUARD}` 的 FACES 覆盖：{reverse} —— "
        "**反方向**的漂移同样致命：本文件（② 的受管面判据）管住它、而 S1 的 C2/C3 对它"
        "**静默不生效**。issue #4647 收口时实测过这一形态（会话卡只进了本文件、忘了同步 S1，"
        "而单向判据不红）⇒ 两处清单必须一致，或显式登记理由"
    )


def test_c2_reverse_drift_injection_is_red():
    """② 双向防漂移的**注入式红证**：把 S1 的 `FACES` 里那个面摘掉 ⇒ 反方向判据必红。

    <p>红证形态 = issue #4647 收口时**实际发生过**的形态（只登记本文件、S1 漏同步）——
    改前单向判据对此**不红**，所以这条红证是「下次再漏同步会不会被发现」的唯一机械答案。</p>
    """
    source = (REPO_ROOT / S1_GUARD).read_text(encoding="utf-8")
    assert _s1_reverse_drift(source) == [], "真树上两处清单应一致（双向判据本应为绿）"

    face = "frontend/admin-web/src/components/chat/ProductionProgressCard.tsx"
    injected = source.replace(f'    "{face}",\n', "", 1)
    assert _fingerprint(injected) != _fingerprint(source), (
        f"在 `{S1_GUARD}` 的 FACES 里找不到 `{face}` ⇒ 本红证会**空跑**；"
        "该面的登记形态变了就同步改本守卫"
    )
    assert _s1_reverse_drift(injected) == [face], (
        "把 S1 的 FACES 摘掉一项后，**反方向**漂移判据没判红 ⇒ 双向判据是空判据"
        "（这正是 issue #4647 收口时漏同步却没被发现的原因）"
    )
    assert _fingerprint((REPO_ROOT / S1_GUARD).read_text(encoding="utf-8")) == _fingerprint(source), (
        "真树里的 S1 守卫内容变了 ⇒ 红证污染了被测对象"
    )


def test_c2_injected_unregistered_face_is_red(tmp_path: Path):
    """② 注入式红证：临时副本里新增一个读 `per_operation` 的面而不登记 ⇒ 判红；指纹自证。"""
    rel = "frontend/admin-web/src/components/production/PieceworkTable.tsx"
    original = (REPO_ROOT / rel).read_text(encoding="utf-8")
    # 注入形态 = 把 helper 导入摘掉（退回裸渲染快照名），并放到一个**未登记**的新面路径
    injected = original.replace(f"import {{ {REQUIRED_IMPORT} }} from '{HELPER_SPECIFIER}'\n", "")
    assert _fingerprint(injected) != _fingerprint(original), (
        f"在 `{rel}` 里找不到注入点（helper 的 import 形态变了）⇒ 本红证会**空跑**；"
        "判据必须能判红 ⇒ 面文件的导入形态变了就同步改本守卫"
    )

    new_rel = "frontend/admin-web/src/components/production/NewSnapshotFace.tsx"
    # 受管面**全部**放进临时副本（`rel` 用摘掉 helper 导入的那一份）—— 否则「文件不存在」的兜底
    # 路径会冒充红证，让「摘掉 helper 导入是否判红」这条**变成空断言**。
    for face in MANAGED_FACES:
        content = injected if face == rel else (REPO_ROOT / face).read_text(encoding="utf-8")
        target = tmp_path / face
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    ghost_target = tmp_path / new_rel
    ghost_target.write_text(injected, encoding="utf-8")

    offenders = _unregistered_faces(tmp_path)
    assert any(new_rel in o for o in offenders), (
        f"新增一个读 `per_operation` 且**未登记**的面后判据没判红 ⇒ 「自己发现新面」是空判据：{offenders}"
    )
    face_offenders = _managed_face_violations(tmp_path)
    assert any(rel in o and HELPER_SPECIFIER in o for o in face_offenders), (
        f"受管面 `{rel}` 被摘掉 helper 导入后判据没判红（或红的理由不是「没走唯一 helper」）⇒ "
        f"受管面判据是空判据：{face_offenders}"
    )

    # 「不得直接渲染快照名」的红证（与 S1 的 C3 同形）—— 防止本文件抄来的 patterns 变成死判据
    render_rel = MANAGED_FACES[0]
    render_original = (REPO_ROOT / render_rel).read_text(encoding="utf-8")
    render_injected = render_original + "\nconst rawSnapshotName = item.operation\n"
    assert _fingerprint(render_injected) != _fingerprint(render_original), "直接渲染形态的注入没生效"
    (tmp_path / render_rel).write_text(render_injected, encoding="utf-8")
    assert any("成员访问 .operation" in o for o in _managed_face_violations(tmp_path)), (
        "受管面里出现 `.operation` 直接渲染后判据没判红 ⇒ 直接渲染判据是空判据"
    )

    # 还原自证 + 真树仍绿
    assert _fingerprint((REPO_ROOT / rel).read_text(encoding="utf-8")) == _fingerprint(original), (
        "真树文件内容变了 ⇒ 红证污染了被测对象（红证只许动**临时副本**）"
    )
    assert _unregistered_faces(REPO_ROOT) == [], "真树上 ② 的登记判据应为绿"
    assert _managed_face_violations(REPO_ROOT) == [], "真树上 ② 的受管面判据应为绿"


def test_c2_injected_unregistered_catalog_face_is_red(tmp_path: Path):
    """② 注入式红证（issue #4642）：新增一个**读 `operations-catalog` 的新面**而不登记 ⇒ 判红。

    <p>红证形态 = `import type { CatalogOperation }` + `{o.name}` —— 正是 P1 漏过去的那条路
    （`routings/page.tsx` 的孤儿接入弹窗读 `catalog.groups[].operations[].name`）。
    **改前实测**：标记集里没有 `CatalogOperation` ⇒ 命中集为空、本判据**不红**（所以 P1 才漏了）。</p>
    """
    new_rel = "frontend/admin-web/src/components/production/NewCatalogFace.tsx"
    ghost = (
        "import type { CatalogOperation } from '@/types'\n"
        "\n"
        "export function NewCatalogFace({ operations }: { operations: CatalogOperation[] }) {\n"
        "  return <ul>{operations.map((o) => <li key={String(o.id)}>{o.name}</li>)}</ul>\n"
        "}\n"
    )
    target = tmp_path / new_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(ghost, encoding="utf-8")
    assert _fingerprint(target.read_text(encoding="utf-8")) == _fingerprint(ghost), "注入没生效"

    # 标记口径自证：`CatalogOperation` 必须**真在** MARKERS 里（否则本红证恒红/恒绿都不可归因）
    assert any(name == "CatalogOperation" for name, _p in MARKERS), (
        "MARKERS 里没有 `CatalogOperation` ⇒ 读 catalog 的新面照不到（issue #4642 的 P1 漏点）"
    )
    assert _markers_in(_strip_comments(ghost)) == ["CatalogOperation"], (
        f"注入面的标记命中不是 `['CatalogOperation']` ⇒ 本红证会空跑：{_markers_in(_strip_comments(ghost))}"
    )

    offenders = _unregistered_faces(tmp_path)
    assert any(new_rel in o for o in offenders), (
        f"新增一个读 `operations-catalog`（`CatalogOperation`）且**未登记**的面后判据没判红 ⇒ "
        f"「自己发现新面」在 catalog 读面上仍是空判据（P1 的漏点未被堵住）：{offenders}"
    )

    # 阳性对照：把它登记进豁免表 ⇒ 同一判据变绿（证明红的归因是这个面未登记，不是别的噪声）。
    # 直接改函数 globals 再还原（不 import 模块：pytest 的模块名取决于 rootdir，import 形态会空跑）。
    globals_ = _unregistered_faces.__globals__
    original_exempt = globals_["EXEMPT_FACES"]
    try:
        globals_["EXEMPT_FACES"] = original_exempt + ((new_rel, "阳性对照（临时登记）"),)
        assert _unregistered_faces(tmp_path) == [], "登记后仍判红 ⇒ 判据与「未登记」无关（误红）"
    finally:
        globals_["EXEMPT_FACES"] = original_exempt
    assert globals_["EXEMPT_FACES"] is original_exempt, "阳性对照污染了真树常量（必须还原）"

    # 真树仍绿（注入只发生在 tmp 副本里）
    assert _unregistered_faces(REPO_ROOT) == [], "真树上 ② 的登记判据应为绿"


def test_c2_s1_registry_drift_is_red():
    """② 防漂移红证：往 S1 源码的 `FACES` 里塞一个面 ⇒ 漂移判据必红（指纹自证注入生效）。"""
    source = (REPO_ROOT / S1_GUARD).read_text(encoding="utf-8")
    anchor = "FACES: tuple[str, ...] = (\n"
    ghost = "frontend/admin-web/src/components/production/GhostFace.tsx"
    injected = source.replace(anchor, anchor + f'    "{ghost}",\n')
    assert _fingerprint(injected) != _fingerprint(source), (
        f"在 `{S1_GUARD}` 里找不到注入点 `{anchor.strip()}` ⇒ 本红证会**空跑**（S1 的 FACES 形态变了就同步改）"
    )
    assert _s1_drift(source) == [], "真树上两份清单应一致（防漂移断言本应为绿）"
    assert _s1_drift(injected) == [ghost], (
        "S1 的 FACES 多出一个面后，漂移判据**没判红** ⇒ 防漂移是空判据（两处清单可以静默漂移）"
    )
    assert _fingerprint((REPO_ROOT / S1_GUARD).read_text(encoding="utf-8")) == _fingerprint(source), (
        "真树里的 S1 守卫内容变了 ⇒ 红证污染了被测对象"
    )


# ── ② 测试（issue #4647 / D1：会话卡的漏点）───────────────────────────────────

def test_c2_injected_bare_snapshot_render_in_progress_card_is_red(tmp_path: Path):
    """② 注入式红证（issue #4647 / D1）：把**米宝会话卡**退回裸渲染快照名 ⇒ 判红。

    <p>改前实测（复验方）：该面 `_markers_in()` = `[]`、不在 `MANAGED_FACES` / `EXEMPT_FACES` /
    S1 `FACES`（四项全 False）⇒ 注入**四条判据全绿**（缺陷 6 可静默复发）。
    根因 = 它读 `current_operation`、元素类型是文件内本地接口 `ProductionCardOperation`，
    而 `MARKERS` 只认 `operation_name` / `per_operation` / `ProductionPosition` /
    `ProductionOperation` / `CatalogOperation` ⇒ 照不到。</p>
    """
    rel = "frontend/admin-web/src/components/chat/ProductionProgressCard.tsx"
    original = (REPO_ROOT / rel).read_text(encoding="utf-8")

    # 注入形态 = 复验方给的「退回裸渲染快照名」：删 helper 导入 + 直接取 `current_operation`
    injected = original.replace(
        "import { operationDisplayName } from '@/lib/operation-display'\n", ""
    )
    assert _fingerprint(injected) != _fingerprint(original), (
        f"在 `{rel}` 里找不到注入点（helper 的 import 形态变了）⇒ 本红证会**空跑**；"
        "该面的导入形态变了就同步改本守卫"
    )

    # 标记口径自证：`current_operation` / `ProductionCardOperation` 必须**真在** MARKERS 里
    # （否则本红证恒红/恒绿都不可归因）
    for name in ("current_operation", "ProductionCardOperation"):
        assert any(n == name for n, _p in MARKERS), (
            f"MARKERS 里没有 `{name}` ⇒ 会话卡的读面键照不到（D1 的漏点未被堵住）"
        )
    assert _markers_in(_strip_comments(original)) != [], (
        f"`{rel}` 在真树上**一个标记都不命中** ⇒ 登记机制照不到这个面（D1 的根因）"
    )

    # 受管面**全部**放进临时副本 —— 否则「文件不存在」的兜底路径会冒充红证
    for face in MANAGED_FACES:
        content = injected if face == rel else (REPO_ROOT / face).read_text(encoding="utf-8")
        target = tmp_path / face
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    face_offenders = _managed_face_violations(tmp_path)
    assert any(rel in o and HELPER_SPECIFIER in o for o in face_offenders), (
        f"会话卡 `{rel}` 被摘掉 helper 导入后判据没判红（或红的理由不是「没走唯一 helper」）⇒ "
        f"受管面判据照不到这个面：{face_offenders}"
    )
    assert _unregistered_faces(tmp_path) == [], (
        "会话卡已登记（在 MANAGED_FACES 里）⇒ 「未登记即红」不应因它而红"
    )

    # 还原自证 + 真树仍绿
    assert _fingerprint((REPO_ROOT / rel).read_text(encoding="utf-8")) == _fingerprint(original), (
        "真树文件内容变了 ⇒ 红证污染了被测对象（红证只许动**临时副本**）"
    )
    assert _managed_face_violations(REPO_ROOT) == [], "真树上会话卡应为绿（它已走 operationDisplayName）"


# ── ③b 测试（issue #4647 / D3：文案拼接）──────────────────────────────────────

def test_c3b_java_text_never_concatenates_variant_names():
    """③b：生产 Java 文案**不得**用拼接把变体名（`-布`/`-纱`/`-帘`）拼出来。

    <p>判据来自 issue #4647 / D3：③ 只判读面**落键**成对 ⇒ **照不到文案拼接**，于是
    `ProductionRoutingCommandService`（主线判重）与 `ProcessingOrderService`（实例化 hint）
    两条非删除路径把 `精裁-布` 拼进了 422 文案（前者**界面可见**）。</p>
    """
    offenders = _java_text_concat_offenders(REPO_ROOT)
    assert offenders == [], (
        "生产 Java 把**变体名**（工人端快照名，如 `精裁-布`）拼进了文案 —— 它会经 422 响应"
        "上屏（工艺路线页的护栏理由区直接渲染 `details[].message`）：\n  "
        + "\n  ".join(offenders)
        + "\n处置：文案只写**逻辑名** + 说明（如「该工序在该部位缺库行」），"
        "不得回显 `-布`/`-纱`/`-帘` 形态；确属另一个词表（如部位名 `布帘`）⇒ 逐条登记进 JAVA_TEXT_EXEMPT"
    )


def test_c3b_java_text_exemptions_are_registered_and_not_stale():
    """③b 豁免登记：逐条有理由、文件存在、字面量仍在代码里（过期 ⇒ 红 = 只许缩短）。"""
    assert JAVA_TEXT_EXEMPT, (
        "③b 的豁免表为空 ⇒ 判据的覆盖面归零（若确已清理干净，请把本断言改成别的非空锚点，"
        "而不是留一张空表）"
    )
    problems = _stale_java_text_exemptions(REPO_ROOT)
    assert problems == [], "③b 豁免清单有问题：\n  " + "\n  ".join(problems)


def test_c3b_injected_variant_name_concat_is_red(tmp_path: Path):
    """③b 注入式红证：临时副本里把变体名拼进文案 ⇒ 判红；内容指纹自证注入/还原真生效。

    <p>注入形态 = D3(a) 的**原始形态**（`name + "-布"`）—— 改前它在真树上、判据不存在；
    改后判据必须能认出来。</p>
    """
    rel = "backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingCommandService.java"
    original = (REPO_ROOT / rel).read_text(encoding="utf-8")
    injected = original.replace(
        'String logicalName = productionOperationQueryService.normalizeOperationName(name);',
        'String logicalName = productionOperationQueryService.normalizeOperationName(name);\n'
        '            String leak = name + "-布";',
    )
    assert _fingerprint(injected) != _fingerprint(original), (
        f"在 `{rel}` 里找不到注入点（归一调用的形态变了）⇒ 本红证会**空跑**；"
        "该处实现变了就同步改本守卫"
    )

    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(injected, encoding="utf-8")

    offenders = _java_text_concat_offenders(tmp_path)
    assert any(rel in o and '"-布"' in o for o in offenders), (
        f"把 `name + \"-布\"` 注入文案后判据**没判红** ⇒ ③b 是空判据（不会红的断言 = 空断言）：{offenders}"
    )

    # 阳性对照：还原 ⇒ 同一判据变绿（证明红的归因是那段拼接，不是别的噪声）
    target.write_text(original, encoding="utf-8")
    assert _java_text_concat_offenders(tmp_path) == [], "还原后仍判红 ⇒ 判据与目标无关（误红）"

    # 还原自证 + 真树仍绿
    assert _fingerprint((REPO_ROOT / rel).read_text(encoding="utf-8")) == _fingerprint(original), (
        "真树文件内容变了 ⇒ 红证污染了被测对象（红证只许动**临时副本**）"
    )
    assert _java_text_concat_offenders(REPO_ROOT) == [], "真树上 ③b 应为绿"


def test_c3b_variant_suffix_literals_alone_are_not_red():
    """③b **判别力下界**：`"布帘"`（部位名）与 `.endsWith("-布")`（判定式）**不得**判红。

    <p>没有这条，一个「见到 `-布` 就判红」的实现会静默通过 —— 它会误伤部位名取值与判定谓词，
    逼出两个假豁免（豁免越多，判据越容易被顺手加白）。</p>
    """
    ghost = (
        'private static final String POS = "布帘";\n'
        'boolean isVariant(String name) { return name.endsWith("-布"); }\n'
        'boolean same(String a) { return a.equals("-纱"); }\n'
    )
    assert _JAVA_CONCAT_RE.search(ghost) is None, "本下界样本本身不该含拼接（样本形态漂移了）"
    assert _JAVA_VARIANT_LITERAL_RE.search(ghost) is not None, "本下界样本本身应含变体名字面量"
    # 拼接 + 判定式同行 ⇒ 不判红（判定不是输出）
    mixed = 'boolean f(String name) { return name.endsWith("-布") && true; } // x + "y"\n'
    assert _JAVA_PREDICATE_RE.search(mixed) is not None, "判定式样本形态漂移了"


# ── ③ 测试 ───────────────────────────────────────────────────────────────────

def test_c3_java_read_faces_pair_operation_with_logical_name():
    """③：凡 `put("operation"` / `put("operation_name"` 的 web 读面文件必须同文件出现 `logical_name`。"""
    offenders = _java_unpaired(REPO_ROOT)
    assert offenders == [], (
        "后端 web 读面只给了**工人端快照名**（变体名）而没给逻辑工序名 —— web 拼不出统一显示名：\n  "
        + "\n  ".join(offenders)
        + "\n处置：读时派生 `logical_name`（+ 有部位时 `position`），既有 `operation` 键保留给其它消费者"
    )


def test_c3_java_exemptions_are_registered_and_not_stale():
    """③ 豁免登记：逐条有理由、文件存在、仍命中读面且仍未成对（过期 ⇒ 红 = 只许缩短）。"""
    assert JAVA_EXEMPT, "③ 的豁免表为空 ⇒ 登记机制失效（若确无豁免，请把本断言改成别的非空锚点）"
    problems = _stale_java_exemptions(REPO_ROOT)
    assert problems == [], "③ 豁免清单有问题：\n  " + "\n  ".join(problems)


def test_c3_injected_unpaired_java_read_face_is_red(tmp_path: Path):
    """③ 注入式红证：临时副本里去掉读面的 `logical_name` ⇒ 判红；指纹自证注入/还原真生效。"""
    rel = "backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java"
    original = (REPO_ROOT / rel).read_text(encoding="utf-8")
    injected = original.replace('put("logical_name"', 'put("logicalNameRenamed"')
    assert _fingerprint(injected) != _fingerprint(original), (
        f"在 `{rel}` 里找不到注入点 `put(\"logical_name\"` ⇒ 本红证会**空跑**；"
        "读面的成对形态变了就同步改本守卫"
    )

    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(injected, encoding="utf-8")

    offenders = _java_unpaired(tmp_path)
    assert any(rel in o for o in offenders), (
        f"去掉 `{rel}` 的 `logical_name` 后判据**没判红** ⇒ ③ 是空判据：{offenders}"
    )

    # 阳性对照：把成对键加回去 ⇒ 同一判据变绿（证明红的归因是那个键，不是别的噪声）
    target.write_text(original, encoding="utf-8")
    assert _java_unpaired(tmp_path) == [], "把 `logical_name` 加回去后仍判红 ⇒ 判据与目标无关（误红）"

    # 还原自证 + 真树仍绿
    assert _fingerprint((REPO_ROOT / rel).read_text(encoding="utf-8")) == _fingerprint(original), (
        "真树文件内容变了 ⇒ 红证污染了被测对象（红证只许动**临时副本**）"
    )
    assert _java_unpaired(REPO_ROOT) == [], "真树上 ③ 应为绿"


# ── 反空跑锚点 ───────────────────────────────────────────────────────────────

def test_anchors_scan_roots_missing_is_red(tmp_path: Path):
    """反空跑锚点 ①/③：扫描根不存在 ⇒ 显式失败（**不是**「通过」）。"""
    with pytest.raises(AssertionError, match="扫描根不存在"):
        _fe_corpus(tmp_path / "nope")
    with pytest.raises(AssertionError, match="扫描根不存在"):
        _java_corpus(tmp_path / "nope")


def test_anchors_hit_sets_and_registry_are_not_empty():
    """反空跑锚点 ②/③ + 全局阳性对照：命中集空 / 登记表空 / 扫不到 helper ⇒ 显式失败。"""
    fe_files = [rel for rel, _text in _fe_corpus(REPO_ROOT)]
    assert fe_files, "① / ② 的语料为空 ⇒ 判据在空集上通过 = 空跑"
    assert HELPER in fe_files, (
        f"阳性对照失败：`{HELPER}` 不在 ① 的语料里 ⇒ 扫描口径/路径漂移（扫的不是我们关心的代码）"
    )
    assert _marker_hits(REPO_ROOT), (
        "② 命中集为空 ⇒ 自维护登记机制已死（标记键 / 元素类型在 FE 里一个都扫不到）—— "
        "这不是「没问题」，是判据失效"
    )
    assert MANAGED_FACES, "② 受管表为空 ⇒ 受管面判据在空集上通过 = 空跑"
    assert set(MANAGED_FACES) | {rel for rel, _reason in EXEMPT_FACES}, "② 登记表为空 ⇒ 未登记即红失去基准"
    assert _java_put_faces(REPO_ROOT), (
        "③ 命中集为空 ⇒ 一个 web 读面都没扫到（路径漂移 / 键名改了）—— 判据失效，不是通过"
    )
    assert JAVA_EXEMPT or _java_unpaired(REPO_ROOT) == [], (
        "③ 豁免表为空时判据必须仍能判红（此断言是 fail-closed 的兜底说明）"
    )
    assert LIBRARY_NAME_KEY == "library_name", (
        "④ 的键名常量被改 ⇒ 判据扫的不是 `library_name`（键名是本判据的**被测对象**，不得漂移）"
    )
