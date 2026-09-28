# case_ids: PP-011
"""web 面**工序显示名**守卫（issue #4621，web 面工序命名统一 · 阶段 1；#4963 扩面）。

## 病根（实测）

web 面存在**两套工序名**：`production_operations.name` 是旧命名（把部位编进名字：
`布三边` / `精裁-布`），而主线 / 规则 / 矩阵用的是**逻辑名**（`三边` / `精裁`）
⇒ 商家在界面上一会儿看到 `布三边`、一会儿看到 `三边`。

冻结口径（issue #4621）：显示名 = **逻辑工序名**；该实例**有部位**时拼成 `逻辑名 · 部位`
（如 `三边 · 布帘`）；部位无关工序（`外帘装袋`）⇒ 只显示逻辑名。
后端读面在返回工序名的位置**同时**给出 `logical_name` + `position`（**读时派生、不写库**）；
既有 `operation` / `operation_name` 是**工人端快照名**（变体名）⇒ 保留，但
**界面不得渲染该键**。

⚠️ **白名单是判据的覆盖面**（issue #4630 的教训）：#4621 改了三个面，**第 4 个消费面**
（加工单「生产」页的计件表 `PieceworkTable.tsx`，同一份 `per_operation` 数据）漏了，
而当时它**不在** `FACES` 里 ⇒ 守卫照样全绿、没有任何东西会因此变红。
⇒ 判断「某面该不该在清单里」的判据 = **它是否消费了带 `logical_name`/`position` 的读面**，
而不是「#4621 当时改了哪几个文件」。

## 判据形态

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| C1 | 显示名 helper 存在、导出 `operationDisplayName`、且**拼装只有这一处** | 删/改名 helper ⇒ 必红 |
| C2 | 每个受管面**都 import 了** helper（反空跑：面文件必须是「真的那一个」） | 把 import 删掉 ⇒ 必红 |
| C3 | 受管面里不得出现变体名的**渲染位置**；非渲染读取（赋值/条件/解构）**必须放行** | 把 `{operationDisplayName(op)}` 改回 `{op.operation}` ⇒ 必红 |
| C4 | 注入式红证 + **内容指纹**自证（禁 mtime/size）；含「赋值绕过」的**边界**自证 | 注入点不存在 / 注入没生效 ⇒ 必红 |
| C5 | 已退役面不得再渲染工序（退役 ≠ 无人管） | 把工序加回纸面 ⇒ 必红 |
| C6 | 工人端（worker-h5）**引用**共享模块 `frontend/shared/operation-display.mjs`（不许自拼一份回来） | 改回 `${logical_name} · ${position}` ⇒ 必红 |
| C7 | 四份实现（admin-web / shared / bmini / mini-app）**喂同一张输入表逐值等价** | 改任一份而不同步 ⇒ 必红（含注入式红证） |
| C8 | 读面「工序名键」**逐个登记**（未登记即红 / 台账只许缩短）+ helper 的接受键集**结构化**锁定（#5003②） | 读面新增一个 `operation*` 键 ⇒ 必红；删掉 helper 的同义别名兜底 ⇒ 必红 |

## 🔴 C8 的「键名分叉」（issue #5003②）

`operation` 这一个键名在本仓有**三种语义**，`operation_name` 又是同一个语义的**另一个名字**
（同义不同名）—— 而 helper 的兜底分支原先只认 `operation`：

| 键（真值源 = `frontend/bmini-app/src/services/productionService.ts`） | 语义 | 处置 |
|---|---|---|
| `ProductionOperation.operation` | 快照 / 变体名（`精裁-布`） | **fallback**（helper 兜底键） |
| `WorkLogRow.operation_name` | 同上（报工流水读面的键名） | **fallback**（#5003② 补的显式映射） |
| `PieceworkSummary.per_operation[].operation` | **逻辑名**（`精裁`）—— 同名不同义 | `logical`：**不得**喂兜底 |
| `ScanResolveResult.operation` | 挂的是**对象**（`ScanOperationView`） | `container`：不得喂 helper |
| 各 `*.logical_name` | 读时派生的逻辑名 | `derived`：只作首选键 |

C8 把这张表变成**台账**：读面里出现的每个工序名键都必须登记（**未登记即红**），
台账条目必须**活着**（真值源里已消失 ⇒ 红 ⇒ 只许缩短），
且登记为 `fallback` 的键必须真的在 helper 的接受键集里（**两张表不许各说各话**）。

## 🔴 C3 的「渲染位置」判据（issue #4963 收口）

**旧判据**是 `\\.operation\\b`（任何成员访问）⇒ 它把 `const op = row.operation`（**非渲染**读取）
也判成违规。后果不是「太严」而是**判据不可满足**：加工单「生产」页
（`frontend/admin-web/src/app/(dashboard)/processing-orders/[id]/production/page.tsx`）
的卡点报表必须先把 `row.operation` 取出来再交给 `operationDisplayName(op)` ⇒ 想过判据只能写成
`row['operation']` 这种**绕判据**写法（§17.3 ⑤ 明令禁止）。于是该面**收不进 `FACES`**，
成了 #4630 那个「第 N 个消费面漏网」形态的**复发通道**。

**新判据只判「值会不会被渲染出去」**（剥注释后逐行扫）：

| 形态 | 例子 | 判 |
|---|---|---|
| JSX 插值 | `{op.operation}` / `{row.operation_name}` | **违规**（渲染） |
| JSX 表达式属性 | `title={op.operation}` | **违规**（渲染） |
| JSX 字符串属性 | `label="operation_name"` / `foo="op.operation"` | **违规**（渲染） |
| 赋值 / 解构 / 条件 / 比较 | `const op = row.operation` / `if (row.operation)` / `a.operation === b` | **放行**（非渲染读取） |
| 只出现 `operation` 键（无属性访问、非渲染属性值） | `operations` / `operation_id` | **放行** |

⇒ 「赋值读变体名」在**渲染位置之外**被判**允许**（合法读取）；但只要那次读取发生在 JSX 插值里
（`{(() => { const bad = op.operation; return bad })()}` 这种绕一层的写法），**照样判红** ——
判据判的是「渲染位置」而不是「有没有 helper 调用」，所以「赋值绕过」不是逃生口（C4 之二自证）。
**已知边界**（如实登记）：把读取搬到 JSX 之外、只渲染一个不带 `.operation` 的变量（`const bad = op.operation`
+ 别处 `{bad}`）**不**红 —— 那由 C2 的 import 锚点兜（面文件必须 import 并调用 `operationDisplayName`）。

## ⚠️ 注释不算违规（C3 先按字符串感知地剥注释）

判据自身不能把「注释里写的 `op.operation` 反例」判成违规 —— 那是假红，会逼人删掉解释性注释。

## ⚠️ 受管面清单是显式白名单（不是「扫全仓」）

`routings/page.tsx` 里的 `cell.operation` 本来就是**逻辑名**（矩阵读面的值域），扫全仓会把它判成假红。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 共享实现（#5323 收敛：剥注释的**唯一**实现）—— append 而非 insert，避免遮蔽同名模块。
sys.path.append(str(REPO_ROOT / "tests"))
from unit_ci_workflows._source_parsing import code_without_comments  # noqa: E402

#: 显示名的**唯一**实现（拼装只此一份；各页各拼一份必然漂移，而漂移的那一份不会变红）
HELPER = "frontend/admin-web/src/lib/operation-display.ts"

#: 受管面（显式白名单）：工序名会出现在这些界面上的位置
#: 第 4 项是 issue #4630 补的**漏改面** —— 加工单「生产」页的计件表（`per_operation` 的
#: 第 4 个消费面；#4621 只改了前三个 ⇒ 它一直渲染变体名，而**没有任何判据会因此变红**）。
#: 第 5 项是 issue #4647 / D1 补的**会话卡面** —— 米宝会话里的生产进度卡（`current_operation`）；
#: 它改前不在任何清单里 ⇒ 退回裸渲染快照名时**四条判据全绿**。
#: 第 6 项是 issue #4963 补的**加工单「生产」页本身**（`processing-orders/[id]/production/page.tsx`）：
#: 它消费卡点报表（`stuck[].operation`，带 `logical_name` / `position`）与工序进度表；
#: 收不进来的原因正是 C3 的旧判据（把 `const op = row.operation` 判违规）—— C3 改成
#: 「渲染位置」判据后，它可以**按正常写法**（先取值再交给 helper）进清单。
#: 🔴 **已退役面（issue #4964，2026-09-21）**：`frontend/admin-web/src/components/production/TaskCardPrint.tsx`
#: **不再**是本清单的成员 —— 洗水码改竖版（#4964 为 30×60；**纸宽后经 issue #5646 改判为 50×60**，
#: 退场理由与纸宽无关）后**工序摘要整体退场**（用户字段裁定未选；
#: 工人扫部位码后在 H5 看该部位工序清单，见 issue #4967）⇒ 纸面**一个工序名都不印**，
#: 该面不再消费带 `logical_name` / `position` 的读面。
#: **退役不等于无人管**：C5 反向钉住它不得再出现工序渲染 —— 将来要把工序加回纸面，
#: 必须**同时**把它加回本清单，否则就是 #4630 的漏改形态复发（改了面、判据全绿、没有东西变红）。
FACES: tuple[str, ...] = (
    "frontend/admin-web/src/components/production/ProductionProgressTable.tsx",
    "frontend/admin-web/src/app/(dashboard)/production/piecework/page.tsx",
    "frontend/admin-web/src/components/production/PieceworkTable.tsx",
    "frontend/admin-web/src/components/chat/ProductionProgressCard.tsx",
    "frontend/admin-web/src/app/(dashboard)/processing-orders/[id]/production/page.tsx",
)

#: **已退役面**（issue #4964）：曾在 `FACES` 里、现在**明确不得**再渲染工序的界面
RETIRED_FACES: tuple[str, ...] = (
    "frontend/admin-web/src/components/production/TaskCardPrint.tsx",
)

#: 面必须 import 的符号（C2 的反空跑锚点：面文件真的在用那一份实现）
REQUIRED_IMPORT = "operationDisplayName"

#: 工序显示名的四份实现（issue #4963）：**逐值等价**由 C7 钉住。
#: ① admin-web 的 .ts（web 面唯一口径）；② worker-h5 直接 import 的共享 .mjs；
#: ③ bmini（tsconfig rootDir 约束 ⇒ 逐字复制）；④ mini-app（同因）。
#: 为什么不是「一份实现 + 三个 import」：`@/*` 别名各自指向自身 `src`，且两个 Taro 包的
#: `tsconfig.include` 只含 `./src` ⇒ 跨包 import 会让 tsc 报 TS6059（见各文件头注释）。
IMPLEMENTATIONS: tuple[str, ...] = (
    HELPER,
    "frontend/shared/operation-display.mjs",
    "frontend/bmini-app/src/utils/operationDisplayName.ts",
    "frontend/mini-app/src/components/cards/operationDisplayName.ts",
)

#: worker-h5 必须 import 共享模块的那一行（C6 的反空跑锚点）
WORKER_H5_RENDER = "frontend/worker-h5/src/render.mjs"
_SHARED_IMPORT_RE = re.compile(r"""from\s+['"][^'"]*shared/operation-display\.mjs['"]""")

#: 变体名「**渲染位置**」的形态（C3，issue #4963 收口）。
#: 🔴 **不判赋值 / 解构 / 条件 / 比较**（`const op = row.operation` 是合法读取，不是渲染）——
#: 旧判据把这种非渲染读取判违规 ⇒ 判据不可满足 ⇒ 逼出 `row['operation']` 绕判据写法。
#: 只判「值会不会被渲染出去」：JSX 插值 `{…}`、JSX 表达式属性 `attr={…}`、
#: JSX 字符串属性 `attr="…operation_name…"`。
#: 成员访问用 `\b\.operation`（**不用** `(?<![\w$'"\[])`：那个 lookbehind 恒假 ⇒ 判据永不命中，
#: 会静默退化成空断言）；`\b` 天然排除字符串里的 `.operation`（前面是引号 ⇒ 无词边界）。
_VIOLATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "成员访问 .operation 出现在 JSX 插值里",
        re.compile(r"\{\s*[^}\n]*?\b\.[ \t]*operation\b(?![\w$])"),
    ),
    (
        "成员访问 .operation 出现在 JSX 表达式属性里",
        re.compile(r"\b[\w-]+\s*=\s*\{[^}\n]*?\b\.[ \t]*operation\b(?![\w$])"),
    ),
    (
        "变体名 operation_name 出现在 JSX 插值里",
        re.compile(r"\{\s*[^}\n]*?\boperation_name\b"),
    ),
    (
        "变体名 operation_name 出现在 JSX 表达式属性里",
        re.compile(r"\b[\w-]+\s*=\s*\{[^}\n]*?\boperation_name\b"),
    ),
    (
        "JSX 字符串属性含变体名",
        re.compile(
            r"""\b[\w-]+\s*=\s*["'][^"'\n]*(?:\boperation_name\b|\b\.[ \t]*operation\b)[^"'\n]*["']"""
        ),
    ),
    # 裸标识符 `{operation}`（JSX 简写渲染）。**排除解构 / 对象字面量** ——
    # 它们的 `}` 后面是 `,` / `=` / `:` / `;`（`const { operation, logical_name } = row`、
    # `const x = { operation }`、`const { operation } = row`），是读取不是渲染。
    # 判据收紧到「`}` 后**不**跟 `,`/`=`/`:`/`;`」⇒ 解构不误报、真渲染必红。
    (
        "裸标识符 {operation}",
        re.compile(r"\{\s*operation\s*\}(?!\s*[,=:;])"),
    ),
)

#: helper 必须导出的核心符号（C1 的非空锚点）
_HELPER_EXPORT_RE = re.compile(r"^export\s+(?:async\s+)?function\s+(\w+)", re.M)


def _read(rel: str) -> str:
    """读一个受管文件；**不存在 ⇒ 直接失败**（路径漂移不得退化成静默跳过 = 空跑通过）。"""
    path = REPO_ROOT / rel
    if not path.is_file():
        raise AssertionError(
            f"受管文件不存在：{rel} —— 工序显示名守卫必须能读到它，"
            "路径漂移 / 文件被删 ⇒ 红（**不得**静默跳过）"
        )
    return path.read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    """剥掉 `//` 与 `/* */` 注释（**字符串字面量内的不剥**）。

    判据自身不得把注释里的反例（「不要渲染 `op.operation`」这类说明）判成违规 ——
    那是假红，会逼人删掉解释性注释。字符串感知是必须的：`'https://…'` 里的 `//` 不是注释。
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


def _violations(src: str) -> list[str]:
    """受管面源码里的**变体名渲染位置**违规（剥注释后扫描；返回可读描述）。"""
    code = _strip_comments(src)
    found: list[str] = []
    for lineno, line in enumerate(code.splitlines(), start=1):
        for label, pattern in _VIOLATION_PATTERNS:
            if pattern.search(line):
                found.append(f"{label} @ 第 {lineno} 行：{line.strip()}")
    return found


def _fingerprint(text: str) -> str:
    """内容指纹（issue #4260 红证卫生：**禁 mtime/size** —— 它们会被同秒写入骗过）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── C7 的支撑：把四份实现**真的跑起来**逐值比对（不是文本比对）────────────────

#: 显示名的冻结输入表（名字 → 表达式）。**这是判据的真值**：四份实现逐条比它。
#: 每条的「为什么」都对着 #4963 登记的三处漂移之一（缺 logical_name / 不 trim / 编占位名）。
_NAMES: tuple[tuple[str, str], ...] = (
    ("未传参数（undefined）", "undefined"),
    ("空对象", "{}"),
    ("null", "null"),
    ("显式 undefined", "undefined"),
    ("逻辑名 + 部位", "{ operation: '精裁-布', logical_name: '精裁', position: '布帘' }"),
    ("部位无关工序", "{ operation: '外帘装袋', logical_name: '外帘装袋' }"),
    ("position 全空白", "{ operation: 'x', logical_name: '精裁', position: '  ' }"),
    ("缺 logical_name（老数据）", "{ operation: '定型-布' }"),
    ("logical_name 全空白", "{ operation: '定型-布', logical_name: '  ' }"),
    ("键值带空白", "{ operation: 'x', logical_name: ' 精裁 ', position: ' 布帘 ' }"),
    # #5003② 的同义不同名：报工流水读面把**同一语义**（快照 / 变体名）放在 `operation_name` 下 ——
    # 这三行是它进 helper 的**唯一**证据（改前读数 = `''`：`operation_name` 不在接受键集里 ⇒ 显示空串）。
    ("读面行：只有 operation_name", "{ operation_name: '定型-布' }"),
    ("读面行 + 逻辑名", "{ operation_name: '定型-布', logical_name: '定型' }"),
    ("读面行 + 逻辑名 + 部位", "{ operation_name: '定型-布', logical_name: '定型', position: '布帘' }"),
    # 同名不同义时**哪个赢**必须由口径定，不许留给对象字面量的书写顺序：
    # `operation` 是 `ProductionOperation` 的元素键（读面契约的主键名）⇒ 快照名优先。
    ("operation 与 operation_name 同时在", "{ operation: '精裁-布', operation_name: '三边-布' }"),
)
_EXPECTED: tuple[str, ...] = (
    "",             # ① 空态给空串，**不编占位名**「工序」（改前 bmini 编「工序」）
    "",
    "",
    "",
    "精裁 · 布帘",   # ② 逻辑名 · 部位
    "外帘装袋",      # ③ 部位无关 ⇒ 只显示逻辑名（不拼孤立的 ` · `）
    "精裁",         # ④ position 全空白 ⇒ 只显示逻辑名
    "定型-布",       # ⑤ 缺 logical_name ⇒ 退回快照名原文（改前只显示部位 / 显示空白）
    "定型-布",       # ⑥ logical_name 全空白 ⇒ 同上
    "精裁 · 布帘",   # ⑦ 键值带空白必须 trim（改前不 trim ⇒ 原样上屏）
    "定型-布",       # ⑧ #5003② 同义不同名：`operation_name` 也是快照名（改前给空串）
    "定型",         # ⑨ 逻辑名在 ⇒ 走逻辑名
    "定型 · 布帘",   # ⑩ 逻辑名 + 部位
    "精裁-布",       # ⑪ 同义两键同时在 ⇒ `operation` 优先（口径显式，不靠书写顺序）
)


def _extract_function(src: str, name: str) -> str:
    """从源码里取出名为 `name` 的**函数声明整段**（含签名）。

    找不到 ⇒ AssertionError（**不得**静默跳过：抽取锚点漂了就是判据空跑）。
    取签名时做**平衡括号**扫描，不用正则截断 —— 参数里的 `{ ... }` 会让 `[^)]*` 提前收尾。
    """
    m = re.search(rf"\bfunction\s+{re.escape(name)}\s*\(", src)
    assert m, (
        f"抽不到函数 `{name}` —— C7 的抽取锚点漂了（改名 / 改写成箭头函数 / 删函数）⇒ "
        "判据会**空跑通过**，故这里必须红"
    )
    i = src.index("(", m.start())
    depth = 0
    while i < len(src):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    assert depth == 0, f"`{name}` 的签名括号不平衡 ⇒ 抽取失败（不得静默跳过）"
    body_start = src.index("{", i)
    j, depth = body_start, 0
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    assert depth == 0, f"`{name}` 的函数体大括号不平衡 ⇒ 抽取失败"
    return src[m.start(): j + 1]


def _strip_parameter_types(params: str) -> str:
    """剥掉参数表里的 TS 类型注解，**保留每个参数的 JS 形态**。

    只认「`名字?` + `:` + 类型」这一种形态（本判据的四份实现都是它）：
    `op?: { a?: string | null } | null` ⇒ `op`；`op?: OperationNameFields | null` ⇒ `op`；
    `op = { a: 1 }`（默认值对象字面量，**没有**类型注解）⇒ 原样保留。

    🔴 为什么不是「按 `:` 切掉类型、保留后面的花括号」：那样会把 `op?: { … }` 剥成 `op?{ … }`
    （花括号本是**类型**的一部分），参数表直接语法错误 ⇒ C7 会以「编译不过」红，而不是以
    「口径漂移」红 —— 判据的**归因**就错了。参数名之后的一切（类型 + 可选标记）整体丢弃。
    """
    out = re.sub(r"(\w+)\?\s*:\s*[^,]*?(?=,\s*\w|\s*$)", r"\1", params, flags=re.S)
    out = re.sub(r"(\w+)\s*:\s*[^,]*?(?=,\s*\w|\s*$)", r"\1", out, flags=re.S)
    return out


def _implementation_source(src: str) -> str:
    """从一份实现源码里抽出可执行的 `operationDisplayName`（ESM 源码串）。"""
    fn = _extract_function(src, "operationDisplayName")
    open_paren = fn.index("(")
    depth, i = 0, open_paren
    while i < len(fn):
        if fn[i] == "(":
            depth += 1
        elif fn[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    params = _strip_parameter_types(fn[open_paren + 1:i])
    body = fn[fn.index("{", i):]
    return f"function operationDisplayName({params}) {body}\nexport {{ operationDisplayName }}\n"


def _parity_from_source(src: str) -> list[str]:
    """把一份实现**真的跑起来**（Node）喂 `_NAMES` 全表，返回逐条输出。

    🔴 为什么用 Node 而不是 Python `eval`：被测源码是 **JS/TS**，函数体里的模板串
    （`` `${logical} · ${position}` ``）Python 编译不了 ⇒ 只能在 JS 运行时里执行
    （否则判据会以「编译不过」红，而**归因错误**：真正的缺陷是口径漂移）。
    判据仍是 Python 侧的 `_EXPECTED` 表，Node 只当执行器。
    """
    program = (
        "import { operationDisplayName as f } from './impl.mjs'\n"
        f"const values = [{', '.join(v for _, v in _NAMES)}]\n"
        "console.log(JSON.stringify(values.map((v) => f(v))))\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        impl = Path(tmp) / "impl.mjs"
        impl.write_text(_implementation_source(src), encoding="utf-8")
        runner = Path(tmp) / "runner.mjs"
        runner.write_text(program, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(runner)],
            capture_output=True,
            text=True,
            cwd=tmp,
            timeout=60,
            check=False,
        )
    assert proc.returncode == 0, (
        "把实现跑起来失败（抽取 / 剥类型 / Node 执行）—— C7 会因此**空跑**，故这里必须红：\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    return list(json.loads(proc.stdout.strip()))


def _parity(rel: str) -> list[str]:
    """一份实现喂 `_NAMES` 全表的实际输出（用于与 `_EXPECTED` 逐值比对）。"""
    return _parity_from_source(_read(rel))


# ── C1：唯一实现存在且导出核心符号 ────────────────────────────────────────────

def test_c1_helper_is_the_single_composition_point():
    """C1：显示名 helper 存在、导出 `operationDisplayName`、且**同时**读三个契约键。"""
    src = _read(HELPER)
    exported = set(_HELPER_EXPORT_RE.findall(src))
    assert REQUIRED_IMPORT in exported, (
        f"`{HELPER}` 未导出 `{REQUIRED_IMPORT}`（导出：{sorted(exported)}）—— "
        "各面按这个名字 import，改名/漏导出 ⇒ 消费方直接红"
    )
    for key in ("logical_name", "operation", "position"):
        assert key in src, (
            f"`{HELPER}` 里看不到契约键 `{key}` —— 拼装口径必须在这里写全"
            "（`logical_name` 缺失退回 `operation` 原文；`position` 为空只显示逻辑名）"
        )


# ── C2：受管面都用这一份实现（反空跑锚点）────────────────────────────────────

def test_c2_every_face_imports_the_shared_helper():
    """C2：每个受管面都 import 了 helper —— 面文件必须是「真的那一个」（反空跑）。"""
    assert len(FACES) >= 5, "受管面清单被清空 ⇒ 本守卫会空跑通过（判据必须能判红）"
    for rel in FACES:
        src = _read(rel)
        assert REQUIRED_IMPORT in src, (
            f"`{rel}` 没有用 `{REQUIRED_IMPORT}` —— 工序显示名必须走**同一份**拼装实现"
            f"（`{HELPER}`）；各页各拼一份必然漂移"
        )
        assert "@/lib/operation-display" in src, (
            f"`{rel}` 没有从 `@/lib/operation-display` 取 `{REQUIRED_IMPORT}`（换了一份实现？）"
        )


# ── C3：受管面不得在**渲染位置**直接渲染变体名 ────────────────────────────────

def test_c3_faces_never_render_the_variant_name():
    """C3：受管面里不得出现变体名的**渲染位置**（JSX 插值 / JSX 属性）。

    🔴 判据是「渲染位置」而不是「任何成员访问」（issue #4963）：`const op = row.operation`
    是**非渲染**读取，必须放行 —— 否则判据不可满足，只能写成 `row['operation']` 绕判据
    （§17.3 ⑤ 禁止），加工单「生产」页因此收不进 `FACES`（#4630 的漏改形态复发通道）。
    """
    offenders: list[str] = []
    for rel in FACES:
        for hit in _violations(_read(rel)):
            offenders.append(f"{rel}: {hit}")
    assert offenders == [], (
        "受管面在**渲染位置**直接渲染了**工人端快照名**（变体名，如 `精裁-布`）—— issue #4621 "
        "要求界面只显示「逻辑名 · 部位」（如 `精裁 · 布帘`）：\n  " + "\n  ".join(offenders)
        + "\n改用 `operationDisplayName(op)`（唯一实现："
        + HELPER + "）"
    )


def test_c3_assignment_read_is_not_a_violation():
    """C3 的**反向**判据（issue #4963）：非渲染读取（赋值 / 条件 / 解构）**不得**被判违规。

    没有这条，C3 会退回「任何 `.operation` 都违规」的旧形态 —— 那正是把
    `const op = row.operation` 判红、逼人写 `row['operation']` 的原因。
    同一条测试里钉**判别力下界**：渲染位置**必须**判红（否则「放行」会退化成空判据）。
    """
    allowed = (
        "const op = row.operation\n",
        "let x = a.operation ?? null\n",
        "const { operation, logical_name } = row\n",
        "if (row.operation) return null\n",
        "const same = a.operation === b.operation\n",
        "const id = op.operation_id\n",
        "const list = row.operations ?? []\n",
    )
    for snippet in allowed:
        assert _violations(snippet) == [], (
            f"非渲染读取被判违规（判据过严 ⇒ 只能绕判据）：{snippet.strip()}"
        )
    for snippet in ("{op.operation}\n", "{row.operation_name}\n", "title={op.operation}\n", 'label="op.operation"\n'):
        assert _violations(snippet), (
            f"渲染位置**没**被判红 ⇒ C3 是空判据（不会红的断言 = 空断言）：{snippet.strip()}"
        )


# ── C4：注入式红证 + 内容指纹自证 ─────────────────────────────────────────────

def test_c4_injected_variant_render_is_red(tmp_path: Path):
    """C4：往临时副本塞「渲染位置直接渲染变体名」⇒ 判据必红；并用**内容指纹**自证注入真生效。"""
    rel = FACES[0]
    original = _read(rel)
    assert _violations(original) == [], (
        f"`{rel}` 原文件本应干净（C3 已单独判）—— 这里先红说明 C3 的判据或本文件的预期已变：\n  "
        + "\n  ".join(_violations(original))
    )

    injected = re.sub(
        r"\{\s*" + REQUIRED_IMPORT + r"\([^)]*\)[^}]*\}", "{op.operation}", original, count=1
    )
    assert injected != original, (
        f"`{rel}` 里找不到 `{REQUIRED_IMPORT}(…)` 的渲染注入点 ⇒ 本红证会**空跑**"
        "（判据必须能判红）：面文件的渲染形态变了就同步改本守卫"
    )

    copy = tmp_path / Path(rel).name
    copy.write_text(injected, encoding="utf-8")
    after = copy.read_text(encoding="utf-8")

    assert _fingerprint(after) != _fingerprint(original), (
        "注入后内容指纹未变 ⇒ 注入没生效（**禁 mtime/size**：它们会被同秒写入骗过）"
    )
    assert _violations(after), (
        "注入 `{op.operation}` 后判据**没判红** ⇒ 守卫是空判据（不会红的断言 = 空断言）"
    )


def test_c4_assignment_bypass_is_not_an_escape_hatch(tmp_path: Path):
    """C4 之二（issue #4963）：「**赋值绕过**」不是逃生口 —— 在 JSX 插值里读变体名**照样判红**。

    注入形态 = 把 `{operationDisplayName(op)}` 换成
    `{(() => { const bad = op.operation; return bad })()}`：值取自同一个键、只是绕了一层 IIFE。
    判据按「**渲染位置**」判 ⇒ 它落在 JSX 插值 `{…}` 里 ⇒ **必红**（与直接写 `{op.operation}` 同判）。
    ⇒ 想「绕过」只有两条路：① 真的走 `operationDisplayName`；② 把读取搬到 JSX 之外
    （那时它不渲染，判据不管，但 C2 的 import 锚点仍要求面文件用 helper）。
    """
    rel = FACES[0]
    original = _read(rel)
    injected = original.replace(
        f"{{{REQUIRED_IMPORT}(op)}}",
        "{(() => { const bad = op.operation; return bad })()}",
    )
    assert injected != original, (
        f"`{rel}` 里找不到 `{REQUIRED_IMPORT}(op)` 的渲染注入点 ⇒ 本红证会空跑（必须能判红）"
    )

    copy = tmp_path / Path(rel).name
    copy.write_text(injected, encoding="utf-8")
    after = copy.read_text(encoding="utf-8")
    assert _fingerprint(after) != _fingerprint(original), "注入后内容指纹未变 ⇒ 注入没生效"

    assert _violations(after), (
        "在 JSX 插值里读变体名**没**被判红 ⇒ 「赋值绕过」成了逃生口"
        "（判据必须按渲染位置判，而不是按「有没有 helper 调用」判）"
    )
    assert REQUIRED_IMPORT in after, (
        "本注入**只**替换渲染表达式、保留 import ⇒ 若连 import 都没了，说明注入形态变了，"
        "请同步本红证（它要证明的是「渲染位置判红」而不是「文件不再被扫」）"
    )


# ── C5：已退役面不得再渲染工序（退役 ≠ 无人管）──────────────────────────────

def test_c5_retired_face_no_longer_renders_operations():
    """C5：洗水码纸面**不再印工序**（issue #4964 的退场两项之一）—— 退役面不得被偷偷加回。

    判据形态 = 退役面源码（**剥注释后**）里不得出现 `operationDisplayName`、不得出现「工序」字样、
    也不得在渲染位置直接渲染变体名。**为什么必须有这条**：面一旦移出 `FACES`，C2/C3 就不再管它 ⇒
    「把工序加回纸面、且直接渲染变体名」会**全绿** —— 那正是 #4630 登记过的漏改形态。
    """
    for rel in RETIRED_FACES:
        src = _read(rel)
        code = _strip_comments(src)
        assert REQUIRED_IMPORT not in code, (
            f"`{rel}` 又用回了 `{REQUIRED_IMPORT}` ⇒ 工序被加回纸面了？确要加回：**同时**把它加回 "
            "`FACES`（本守卫的覆盖面靠白名单，不加回 = #4630 的漏改形态复发）"
        )
        assert "工序" not in code, (
            f"`{rel}` 的纸面源码里出现了「工序」字样 ⇒ issue #4964 的退场项（工序摘要）被加回；"
            "确要加回请**同时**把它加回 `FACES` 并走 `operationDisplayName`"
        )
        assert _violations(src) == [], (
            f"`{rel}` 在渲染位置直接渲染了变体名（工人端快照名）：\n  " + "\n  ".join(_violations(src))
        )


# ── C6：工人端（worker-h5）引用共享模块（不许自拼一份回来）──────────────────

def test_c6_worker_h5_imports_the_shared_module():
    """C6：`worker-h5/src/render.mjs` 必须 import 共享模块，且**不得**自拼「逻辑名 · 部位」。

    issue #4963：worker-h5 此前自拼 `${op.logical_name} · ${op.position ?? 部位名}` ——
    与 admin-web 的口径在「缺 logical_name」「键值带空白」「全缺」三种输入下渲染不同。
    判据 = ① 有 import；② 源码里不再出现 `${…logical_name} · ${…}` 的自拼形态（红证：改回去必红）。
    """
    src = _read(WORKER_H5_RENDER)
    assert _SHARED_IMPORT_RE.search(src), (
        f"`{WORKER_H5_RENDER}` 没有 import `frontend/shared/operation-display.mjs` —— "
        "工序显示名各拼一份必然漂移，而漂移的那一份不会变红"
    )
    # 自拼形态：`${…logical_name…} · ${…}`（`[^{}]|\{[^{}]*\}` 允许表达式里带一层花括号 ——
    # 例如 `${esc(op.position ?? v.position?.position_name ?? '')}` ⇒ 简单 `[^}]*` 会漏掉它）
    assert not re.search(r"\$\{[^{}]*(?:\{[^{}]*\})?[^{}]*\.logical_name[^{}]*\}[ \t]*·[ \t]*\$\{", src), (
        f"`{WORKER_H5_RENDER}` 又自拼「逻辑名 · 部位」了 ⇒ 与 admin-web 口径漂移（issue #4963）"
    )


# ── C7：四份实现喂同一张输入表逐值等价 ──────────────────────────────────────

def test_c7_all_implementations_agree_value_by_value():
    """C7：四份实现（admin-web / shared / bmini / mini-app）**逐值等价**（issue #4963）。

    为什么必须「真跑 + 逐值」而不是文本比对：跨包 import 不可行（tsconfig rootDir）⇒ 复制是
    **有意**的；但「靠纪律保证两份不漂移」= 没有任何东西会因此变红（同 `_LOGICAL_NAME_PAIRS`
    三副本的病）。本判据把四份实现**编译出来喂同一张表**，改任一份而不同步 ⇒ 必红。
    """
    assert len(IMPLEMENTATIONS) >= 4, "实现清单被清空 ⇒ 本判据会空跑通过"
    for rel in IMPLEMENTATIONS:
        actual = _parity(rel)
        assert actual == list(_EXPECTED), (
            f"`{rel}` 的工序显示名口径与冻结表不一致（issue #4963）：\n"
            + "\n".join(
                f"  {name}：期望 {exp!r}，实际 {act!r}"
                for (name, _), exp, act in zip(_NAMES, _EXPECTED, actual)
                if exp != act
            )
            + "\n四份实现（admin-web / shared / bmini / mini-app）必须逐值一致："
            "跨包 import 不可行 ⇒ 复制是有意的，但**漂移必须变红**"
        )


def test_c7_injected_divergence_is_red(tmp_path: Path):
    """C7 的注入式红证：把某一份实现改成旧口径（不回退快照名 / 不 trim）⇒ 判据必红。

    红证卫生（issue #4260）：注入前后用**内容指纹**自证（禁 mtime/size），且注入点不存在即红。
    """
    rel = IMPLEMENTATIONS[2]  # bmini 的那一份（改前正是 `|| '工序'` + 不 trim 的旧口径）
    original = _read(rel)
    injected = original.replace(
        "  const logical = (op?.logical_name ?? '').trim() || (op?.operation ?? '').trim()",
        "  const logical = op?.logical_name",
    )
    assert injected != original, (
        f"`{rel}` 里找不到注入点 ⇒ 本红证会**空跑**（判据必须能判红）：实现改了就同步改本守卫"
    )
    assert _fingerprint(injected) != _fingerprint(original), "注入后内容指纹未变 ⇒ 注入没生效"

    copy = tmp_path / "operationDisplayName.ts"
    copy.write_text(injected, encoding="utf-8")
    diverged = _parity_from_source(injected)

    assert diverged != list(_EXPECTED), (
        "把实现改成旧口径（不回退快照名 / 不 trim）后判据**没判红** ⇒ C7 是空判据"
    )
    # 反向：真实文件仍与冻结表一致（证明上面那次不一致来自注入，而不是本来就不一致）
    assert _parity(rel) == list(_EXPECTED)


# ── C8：读面「工序名键」逐个登记 + helper 接受键集（issue #5003②）──────────────
#
# 病根（#5003② 登记的**守卫/契约脆点**）：`operation` 一个键名有三种语义、`operation_name`
# 又是同一个语义的另一个键名 —— 而 helper 的兜底分支只认 `operation`
# ⇒ 传进去的对象只有 `operation_name` 时（报工流水读面 `WorkLogRow`），
# 兜底分支**取不到值**：`operationDisplayName({ operation_name: '定型-布' })` 返回 `''`
# （**改前实测读数**）⇒ 界面显示空工序名（零报错、零判据）。
#
# C8 的形态 = 「**未登记即红**」的台账 + 「两张表不许各说各话」的交叉断言。

#: 读面真值源：bmini 的读面类型**只**在这份文件里声明 ⇒ 它是「键名分叉」的对账源。
READ_FACE_SOURCE = "frontend/bmini-app/src/services/productionService.ts"

#: helper **接受**的键（C8 从四份实现里**结构化**取 `op?.<键>`，不按文本子串取）：
#: `logical_name` = 逻辑名（首选）· `position` = 部位 ·
#: `operation` / `operation_name` = **同一语义**（工人端快照 / 变体名）的两个键名，
#: 后者是 #5003② 补的**显式映射**（同义不同名）。
ACCEPTED_KEYS: frozenset[str] = frozenset(
    {"logical_name", "operation", "operation_name", "position"}
)

#: 台账（`(interface, 键, 处置)`）：读面里出现的每个工序名键都要登记，条目必须**活着**。
#:   `fallback`  = 快照 / 变体名 ⇒ helper 的兜底分支**接受**它（必须 ∈ `ACCEPTED_KEYS`）；
#:   `logical`   = **逻辑名** —— ⚠️ **同名不同义**：`per_operation[].operation` 与
#:                 `ProductionOperation.operation` 同名却是逻辑名（计件查找键）。把它喂兜底分支
#:                 就是把逻辑名当快照名显示、拿去比 `per_operation` 又查不到（#4963 的静默消失形态）；
#:   `derived`   = 读时派生的逻辑名 ⇒ 只作首选键，**不是**兜底键；
#:   `container` = 该键挂的是**对象**（不是名字字符串）⇒ 不得喂 helper。
#: 残余（如实登记，本判据判不了）：`ScanOperationView` / `ScanAlternativeView` /
#: `ScanOverviewOperationView` 三个扫码读面**只下发派生逻辑名、不下发快照名** ⇒ 老数据
#: （`logical_name` 空）时兜底分支无值可取（显示空串）。补这个键属**读面契约**
#: （Java 侧 `backend/admin-api/src/main/java/com/migao/admin/service/ProductionScanService.java`
#: → 前端类型），跨模块改动不在本包射程 —— 见 PR body 未固化项。
_NAME_KEY_LEDGER: tuple[tuple[str, str, str], ...] = (
    ("ProductionOperation", "operation", "fallback"),
    ("ProductionOperation", "logical_name", "derived"),
    ("WorkLogRow", "operation_name", "fallback"),
    ("PieceworkSummary", "operation", "logical"),
    ("ScanOperationView", "logical_name", "derived"),
    ("ScanAlternativeView", "logical_name", "derived"),
    ("ScanOverviewOperationView", "logical_name", "derived"),
    ("ScanResolveResult", "operation", "container"),
)


def _is_name_key_candidate(key: str) -> bool:
    """一个成员键是否落在「工序名键」的**发现面**里（决定它要不要登记）。

    四个已知键 + `operation*` 家族里既不是标识符（`*_id`）也不是复数容器（`*s`）的新键
    （如 `operation_label`）⇒ 一律要求登记（**未登记即红**就是靠这条发现面）。
    """
    if key in ("operation", "operation_name", "current_operation", "logical_name"):
        return True
    return key.startswith("operation") and not key.endswith(("_id", "s"))


def _interface_body(code: str, open_index: int) -> str:
    """`{…}` 平衡扫描（注释已剥；只要块边界，不做语法解析）。不平衡 ⇒ 红（fail-closed）。"""
    depth, i = 0, open_index
    while i < len(code):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return code[open_index:i + 1]
        i += 1
    raise AssertionError(f"`{READ_FACE_SOURCE}` 的 interface 大括号不平衡 ⇒ 抽取失败 ⇒ 红")


def _read_face_name_keys(src: str) -> set[tuple[str, str]]:
    """真值源里 `(interface, 键)` 的工序名键**全集**（先剥注释：复用全仓唯一实现）。

    **内联**成员也要认：`per_operation: { operation: string; amount: number }[]`
    正是「同名不同义」那一处（计件的 `operation` 是逻辑名）⇒ 只扫顶层成员会漏掉它。
    """
    code = code_without_comments(src, READ_FACE_SOURCE)
    found: set[tuple[str, str]] = set()
    for match in re.finditer(r"^export interface (\w+)", code, re.M):
        body = _interface_body(code, code.index("{", match.end()))
        for key in re.findall(r"\b([A-Za-z_]\w*)\s*\??\s*:", body):
            if _is_name_key_candidate(key):
                found.add((match.group(1), key))
    return found


def _name_key_mismatches(src: str) -> list[str]:
    """真值源 ↔ 台账的**双向**差集（未登记 / 死条目）。纯函数 ⇒ 可喂注入语料做红证。"""
    found = _read_face_name_keys(src)
    ledger = {(iface, key) for iface, key, _ in _NAME_KEY_LEDGER}
    return ([f"未登记：{iface}.{key}" for iface, key in sorted(found - ledger)]
            + [f"台账死条目（真值源里已不存在）：{iface}.{key}" for iface, key in sorted(ledger - found)])


def _accepted_keys(src: str) -> set[str]:
    """一份实现**实际读的键**（结构化：`op?.<键>`）—— 不是对实现文本做子串匹配。"""
    return set(re.findall(r"op\?\s*\.\s*(\w+)", _extract_function(src, "operationDisplayName")))


def test_c8_read_face_name_keys_are_all_registered():
    """C8 之一：bmini 读面里出现的每个工序名键都**登记在册**（未登记 / 死条目 ⇒ 红）。"""
    mismatches = _name_key_mismatches(_read(READ_FACE_SOURCE))
    assert mismatches == [], (
        f"`{READ_FACE_SOURCE}` 的工序名键与台账对不上（issue #5003②）——\n  "
        + "\n  ".join(mismatches)
        + "\n新增键要在 `_NAME_KEY_LEDGER` 里写明它的**语义**与能否当 helper 的兜底"
        "（同名不同义正是本条的病灶）；已消失的条目要删（台账只许缩短）"
    )


def test_c8_helper_accepts_exactly_the_registered_fallback_keys():
    """C8 之二：四份实现的接受键集 == `ACCEPTED_KEYS`，且台账的 `fallback` 键都在其中。

    两条合起来钉住「**两张表不许各说各话**」：把某个兜底键从 helper 里删掉
    （或只删一份实现）⇒ 必红；台账里登记成 `fallback` 而 helper 不认 ⇒ 必红。
    """
    for rel in IMPLEMENTATIONS:
        actual = _accepted_keys(_read(rel))
        assert actual == set(ACCEPTED_KEYS), (
            f"`{rel}` 的接受键集与冻结口径不一致：实际 {sorted(actual)} ≠ "
            f"{sorted(ACCEPTED_KEYS)}（#5003②：同义不同名的两个键名都要认）"
        )
    fallback_keys = {key for _iface, key, disposition in _NAME_KEY_LEDGER if disposition == "fallback"}
    assert fallback_keys <= set(ACCEPTED_KEYS), (
        f"台账把 {sorted(fallback_keys - set(ACCEPTED_KEYS))} 登记成兜底键，但 helper 不认它 ⇒ "
        "两张表各说各话（正是 #5003② 的形态）"
    )
    assert fallback_keys == {"operation", "operation_name"}, (
        f"台账里的兜底键集被改动（{sorted(fallback_keys)}）—— 兜底语义 = 快照 / 变体名，"
        "两个键名（`operation` / 同义的 `operation_name`）之外不得再加"
    )


def test_c8_unregistered_name_key_is_red(tmp_path: Path):
    """C8 之三（**未登记即红**的红证）：往读面类型里塞一个新键 ⇒ 台账立刻对不上。

    红证卫生：注入前后用**内容指纹**自证（禁 mtime/size），注入点不存在即红。
    """
    original = _read(READ_FACE_SOURCE)
    injected = original.replace(
        "  operation: string\n", "  operation: string\n  operation_label?: string\n", 1
    )
    assert injected != original, (
        f"`{READ_FACE_SOURCE}` 的 `ProductionOperation` 里找不到注入点 ⇒ 本红证会空跑"
    )
    assert _fingerprint(injected) != _fingerprint(original), "注入后内容指纹未变 ⇒ 注入没生效"
    assert ("ProductionOperation", "operation_label") in _read_face_name_keys(injected), (
        "注入的新键没被抽取到 ⇒ C8 的发现面是空跑（未登记形态会静默通过）"
    )
    assert _name_key_mismatches(injected) != [], (
        "读面新增一个未登记的工序名键却**没**判红 ⇒ C8 是空判据"
    )
    # 反向：真语料仍对得上（证明上面那次不一致来自注入，而不是本来就不一致）
    assert _name_key_mismatches(original) == []


def test_c8_dropping_the_alias_fallback_is_red():
    """C8 之四（**反向**红证）：把 `operation_name` 这个同义别名从兜底分支里删掉 ⇒ 必红。

    这条防的是「把判据改松到永远绿」的反方向 —— 有人嫌两个键名麻烦、删掉别名兜底时，
    C7 的 ⑧ 行（逐值）与 C8 之二（键集）会**同时**红。
    """
    rel = IMPLEMENTATIONS[2]  # bmini 的那一份
    original = _read(rel)
    injected = original.replace(" || (op?.operation_name ?? '').trim()", "")
    assert injected != original, f"`{rel}` 里找不到别名兜底的注入点 ⇒ 本红证会空跑"
    assert _fingerprint(injected) != _fingerprint(original), "注入后内容指纹未变 ⇒ 注入没生效"
    assert _accepted_keys(injected) != set(ACCEPTED_KEYS), (
        "删掉 `operation_name` 兜底后接受键集**没**变 ⇒ C8 是空判据"
    )
    assert _accepted_keys(original) == set(ACCEPTED_KEYS)  # 反向：真文件仍达标
