# case_ids: PP-011
"""水洗唛**纸面内容**的单一真值守卫（issue #6656）。

## 病根（用户 2026-10-10 逐字报的形态）

> 「直连打印机打印的样式和水洗唛预览打印的样式完全不一样，能不能做成一样的」

同一条加工单的水洗唛有**两条打印通道**，改动前**各写了一份纸面字段**：

| 通道 | 落点 | 纸面 |
|---|---|---|
| 系统打印（预览） | `frontend/admin-web/src/components/production/TaskCardPrint.tsx` | 13 行全字段 |
| 免驱动直连 | `frontend/admin-web/src/lib/label-print/wash-label.ts`（+ 页面只传 4 个键） | 只有二维码 + 短码 + 一行件名 |

两边各派生一份 ⇒ **改一处另一处不会红**，纸面就此分叉。这正是本仓已固化的
「同一真值两处投影」族（§17.3）。⇒ 内容面收敛到 `frontend/admin-web/src/lib/wash-label-content.ts`
的 `washLabelRows`（唯一真值），两个渲染器只负责**排版**。

## 为什么还要静态守卫（行为判据已经在，但覆盖不到「接线被摘掉」）

行为面判据已有两条（`frontend/admin-web/tests/unit/components/TaskCardPrint.test.tsx` 的
「纸面内容与行序 = `washLabelRows`」、`frontend/admin-web/tests/unit/lib/label-print/wash-label.test.ts`
的「纸面内容 = 行清单」）。但**「纸面前缀只许在真值模块里拼」这条**在行为上不可判：
把某一个前缀在渲染器里再拼一遍，只要文本碰巧一样就**照样绿**（而改文案时就分叉了）。
⇒ 把口径钉在**代码面**上（与 `tests/unit_ci_workflows/test_wash_label_copy_terms.py` 同族：
那一条也是「术语会爬回来、而没有任何东西会红」）。

## 判据（逐条可红）

| # | 判什么 | 红证（怎么让它红） |
|---|---|---|
| SS1 | 系统打印渲染器**真的读**唯一真值模块（从 `@/lib/wash-label-content` 导入 `washLabelRows`） | 删掉那行 import（改回内联派生）⇒ 必红 |
| SS2 | 位图渲染器的**内容类型**来自唯一真值模块（不从别处拿行清单） | 把 `@/lib/wash-label-content` 的引用改掉 ⇒ 必红 |
| SS3 | 两个渲染器的**代码面**都不得出现纸面行前缀（`单号` / `客户` / `货号` / `帘种` / `安装小区` / `安装位置` / `门幅` / `用料` / `宽高` / `特殊选项` / `备注` / `布料批次`）—— 自己派生字段 ⇒ 必红 | 在 `TaskCardPrint.tsx` 里加一句 `客户 {customerName}` ⇒ 必红 |
| SS4 | 真值模块**真的产出**全部前缀（**反空跑锚点**：防止「删掉别处的词」被当成「改完了」） | 清空真值模块里的前缀 ⇒ 必红 |
| SS5 | **注入式红证**：上面三种坏形态在内存里各自判红，且**内容指纹自证**（禁 mtime/size，issue #4260） | 注入未生效 ⇒ 必红 |
| SS6 | **反向对照**：注释里**提及**这些词不得判红（沿革要写得清，`migao-dev-flow` §2.2「引用即实例」） | 注释里加一句沿革 ⇒ **不**红 |
| SS8 | **张序 / 每套连续只许在真值模块里决定**（issue #8074）：渲染器不得自己调 `groupBySet(` 重排 / 分组出纸清单；真值模块必须真有该调用（反空跑锚点） | 在 `TaskCardPrint.tsx` 里加一句 `groupBySet([])` ⇒ 必红 |
| SS9 | **专属唛的行集合只许在真值模块里决定**（issue #8107）：`WASH_LABEL_OPTION_ROW_KEYS` 与 `input.variant === 'option'` 的过滤点必须在内容模块；渲染器只读 `sheet.variant`、**不得**自己挑行 | 在 `TaskCardPrint.tsx` 里写 `WASH_LABEL_OPTION_ROW_KEYS`（自己过滤）/ 删掉内容模块的 variant 过滤 ⇒ 必红 |

🔴 **本守卫只扫这三份源码**：测试与文档里出现这些词是**在描述口径**，不在射程。

## SS7：份数 / 张数口径也只许一处（issue #7816 → issue #8002）

用户 2026-10-26 逐字「如果订单是双开的要打印两份，单开的要打印1份，三开打印3份，4开打印4份」。
份数读的是 `order_items` 的开数（`openCount`）—— 若两个渲染器各写一份映射（一个写 `2`、一个写
`openCount ?? 1`），**两条通道的出纸张数就会不一样**，而今天没有任何行为判据能同时看见两条通道
（系统打印断言 DOM 张数、直连断言 job 数，各自的 fixture 各自给开数）。

🔴 **issue #8002 起口径再收窄**：份数 / 张数 / 张序（含「专属唛 = 每套每类别 1 张」）全部由
`washLabelSheets` 派生 ⇒ 系统打印渲染器必须调用它（不再自己按开数展开），直连通道也经它展开；
`washLabelCopies(` 与 `openCount` 这个键**只许**出现在内容真值模块里（自己读一遍开数 = 第二份映射）。

🔴 **issue #8074 再补一条 SS8**：用户 2026-10-29 逐字「当订单多套时，且选择了余料带回/布绑带，
打印的水洗唛排版顺序不对，每套连续排版，不要拆开」⇒ **张序（按套聚合、每套连续）也只许在内容模块里决定**：
渲染器若自己调 `groupBySet(` 重排 / 分组出纸清单，就是第二份套序口径（系统打印排一套、直连通道另排一套，
而两条通道的 fixture 各自成立 ⇒ 没有任何行为判据会同时看见）。行为面的「任意入参顺序 ⇒ 套序单调不降 +
每套连续段」不变量在 `frontend/admin-web/tests/unit/lib/wash-label-content.test.ts`。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:  # 复用同族的**去注释/去字符串**状态机（第二份实现自己就会漂移）
    from test_wash_label_copy_terms import code_face
except ImportError as exc:  # pragma: no cover - 路径漂移必须响，不许静默跳过
    raise AssertionError(
        "拿不到 `code_face()`（tests/unit_ci_workflows/test_wash_label_copy_terms.py）—— "
        f"本守卫的判据 3/6 无从判定，不静默跳过：{exc}"
    ) from exc

#: 系统打印渲染器（CSS）
CSS_RENDERER = "frontend/admin-web/src/components/production/TaskCardPrint.tsx"
#: 直连渲染器（canvas 位图）
BITMAP_RENDERER = "frontend/admin-web/src/lib/label-print/wash-label.ts"
#: 纸面**内容**的唯一真值模块
CONTENT_MODULE = "frontend/admin-web/src/lib/wash-label-content.ts"

#: 真值模块的**接线锚**（唯一真值模块的模块说明符；两个渲染器都必须指它）
CONTENT_SPECIFIER = "@/lib/wash-label-content"
#: 系统打印渲染器必须调用的行清单工厂
ROW_BUILDER = "washLabelRows"
#: 份数口径的**唯一实现**（issue #7816）：两个渲染器都必须调它
COPIES_READER = "washLabelCopies("
#: 出纸清单工厂（issue #8002）：张数 / 张序 / 专属唛都在这里派生 —— 系统打印渲染器必须读它
SHEET_BUILDER = "washLabelSheets("
#: 开数键：只许出现在内容真值模块（渲染器自己读 = 第二份份数映射）
OPEN_COUNT_KEY = "openCount"
#: 专属唛的**行集合**（issue #8107）：只许在内容真值模块里定义并用于过滤（渲染器自己挑行 = 第二份行集合口径）
OPTION_ROW_KEYS = "WASH_LABEL_OPTION_ROW_KEYS"
#: 内容模块里「按变体收窄行集合」的**判定点**（缺了它 SS9 的反空跑锚点就没了）
VARIANT_FILTER = "input.variant === 'option'"
#: 渲染器读变体的**唯一**途径（由内容模块在 sheet 上给出，渲染器不自己判 optionLabel）
SHEET_VARIANT_READ = "variant: sheet.variant"

#: 纸面行前缀（`washLabelRows` 是**唯一**拼它们的地方）
# ⚠️ 2026-10-25（issue #7776）：`色号` → `颜色`、新增 `门幅`（用户逐字「保留货号，颜色，门幅和其他工艺信息」；
# 件名（商品名称）与算料公式（褶倍公式）两行退场 ⇒ 它们的词条不再进这张表）。
# 🔴 2026-10-26（issue #7816）：**交期行退场**（用户逐字「移除交期字段」），新增 **`褶法`**
# （是否韩褶公式 + 折数，一个字段）；订单号提前为第一行。
# 🔴 2026-10-26（issue #7833）：`加工方式` 前缀**退场**（用户逐字「加工方式这几个字可以移除」⇒ 该行只印值）；
# 第一行改印加工单号 ⇒ 前缀 `订单` → **`单号`**（17 位订单号不上纸）；`特殊选项` 补齐进表
# （#7776 起就在纸面上，此前漏登记 —— 漏登记 = 渲染器自己拼它也不会红）。
# 🔴 2026-10-26（issue #7856）：`货号` → **`颜色`**（用户逐字「货号不要展示sku，展示颜色的内容」）；
# `部位` → **`帘种`**（同一行、值仍是 `position_kind`）；新增 **`安装小区` / `安装位置`** 两行；
# **`褶法` 前缀退场**（用户逐字「褶法：去掉，只保留后面的文字，和工艺一样」⇒ 该行只印值）。
# 🔴 2026-10-26（issue #7872）：`颜色` → **`货号`**（用户逐字「这里的颜色文案改成货号，右侧的内容不要变化了」
# —— 只改文案、值仍是 `colorName`）；**新增 `布料批次`**（值 = 快照 `batchNo`，纸面**末行**）。
# ⇒ 纸面加行/改文案必须同步这张表：漏登记 = 渲染器自己拼它也不会红（SS3/SS4 都判不到）。
ROW_PREFIX_LITERALS = (
    "单号", "客户", "安装小区", "安装位置", "货号", "帘种", "门幅", "用料", "宽高", "特殊选项", "备注",
    "布料批次",
)

_MANAGED = (CSS_RENDERER, BITMAP_RENDERER, CONTENT_MODULE)


def _read(rel: str) -> str:
    """读受管文件；**不存在 ⇒ 直接失败**（路径漂移不得退化成静默跳过 = 空跑通过）。"""
    path = REPO_ROOT / rel
    if not path.is_file():
        raise AssertionError(f"受管文件不存在：{rel} —— 路径漂移 / 文件被删 ⇒ 红（**不得**静默跳过）")
    return path.read_text(encoding="utf-8")


def _fingerprint(text: str) -> str:
    """内容指纹（**禁 mtime/size**：注入必须自证生效）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _line_of(source: str, needle: str) -> str:
    """具名归因：`文件:行`（判红必须能直接去那一行看）。"""
    for index, line in enumerate(source.splitlines(), start=1):
        if needle in line:
            return f":{index}"
    return ""


def _prefix_hits(source: str) -> list[str]:
    """代码面里出现的纸面行前缀（去注释、保字符串与 JSX 文本）。"""
    face = code_face(source)
    return [f"{prefix}{_line_of(source, prefix)}" for prefix in ROW_PREFIX_LITERALS if prefix in face]


def _problems(sources: dict[str, str]) -> list[str]:
    """SS1~SS4 的全部违规（纯函数 ⇒ 便于注入式红证）。空列表 = 合规。"""
    problems: list[str] = []
    css = sources[CSS_RENDERER]
    bitmap = sources[BITMAP_RENDERER]
    content = sources[CONTENT_MODULE]

    css_face, bitmap_face = code_face(css), code_face(bitmap)

    # SS1：系统打印渲染器**真的读**唯一真值模块
    if CONTENT_SPECIFIER not in css_face or ROW_BUILDER not in css_face:
        problems.append(
            f"SS1 {CSS_RENDERER} 没有从 `{CONTENT_SPECIFIER}` 取 `{ROW_BUILDER}` —— "
            "纸面字段被改回**内联派生**（两条通道会就此分叉；issue #6656 的根因）"
        )

    # SS2：位图渲染器的内容类型也来自唯一真值模块
    if CONTENT_SPECIFIER not in bitmap_face:
        problems.append(
            f"SS2 {BITMAP_RENDERER} 没引用 `{CONTENT_SPECIFIER}` —— "
            "行清单类型/内容真值必须只有一处（否则位图版式可以自己造字段）"
        )

    # SS3：两个渲染器的代码面都不得自己拼纸面行前缀
    for rel, source in ((CSS_RENDERER, css), (BITMAP_RENDERER, bitmap)):
        hits = _prefix_hits(source)
        if hits:
            problems.append(
                f"SS3 {rel} 的**代码面**出现纸面行前缀 {hits} —— "
                f"前缀只许在 `{CONTENT_MODULE}` 里拼（自己再拼一遍 = 第二份会漂移的真值）"
            )

    # SS7：份数 / 张数口径只有一处（issue #7816 → #8002：收敛到内容模块的 `washLabelSheets`）
    #   - 系统打印：`TaskCardPrint` 不再自己按开数展开 ⇒ 必须调 `washLabelSheets(`
    #   - 直连通道：`toWashLabelInputs` 同样经它展开（位图渲染器只逐张画）
    if SHEET_BUILDER not in css_face:
        problems.append(
            f"SS7 {CSS_RENDERER} 没有调用 `{SHEET_BUILDER}` —— 张数（含专属唛）必须读共享出纸清单，"
            "自己按开数展开 ⇒ 两条通道出纸张数会不一样"
        )
    if COPIES_READER not in code_face(content):
        problems.append(
            f"SS7 `{CONTENT_MODULE}` 没有调用 `{COPIES_READER}` —— 直连通道的份数展开点就在这里，"
            "缺了它 ⇒ 蓝牙打出来永远每部位一张"
        )
    if SHEET_BUILDER not in code_face(content):
        problems.append(
            f"SS7 `{CONTENT_MODULE}` 没有 `{SHEET_BUILDER}` —— 共享出纸清单缺席 ⇒ 两条通道会各算一份"
        )
    for rel, source in ((CSS_RENDERER, css), (BITMAP_RENDERER, bitmap), (CONTENT_MODULE, content)):
        if rel != CONTENT_MODULE and OPEN_COUNT_KEY in code_face(source):
            problems.append(
                f"SS7 {rel} 的**代码面**出现开数键 `{OPEN_COUNT_KEY}` —— 份数映射只许在 `{CONTENT_MODULE}` 里"
            )

    # SS4：反空跑锚点 —— 真值模块必须真的产出全部前缀
    content_face = code_face(content)
    missing = [prefix for prefix in ROW_PREFIX_LITERALS if prefix not in content_face]
    if missing:
        problems.append(
            f"SS4 `{CONTENT_MODULE}` 里找不到这些纸面前缀 {missing} —— "
            "真值模块不再产出它们（判据 3 的「别处没有」就退化成空断言）"
        )

    # SS8（issue #8074）：**张序 / 每套连续**只许在内容模块里决定
    #   （用户 2026-10-29 逐字「当订单多套时…每套连续排版，不要拆开」）
    #   - 真值模块必须调用 `groupBySet(`：套序 / 每套连续的判定点，缺了它本判据退化成空断言；
    #   - 两个渲染器**不得**自己调 `groupBySet(` 重排 / 分组出纸清单 —— 那是第二份套序口径，
    #     正是「系统打印自己排一套、直连通道另排一套」的入口（#6656 同族的接线病）。
    if "groupBySet(" not in code_face(content):
        problems.append(
            f"SS8 `{CONTENT_MODULE}` 没有调用 `groupBySet(` —— 套序 / 每套连续的判定点缺席"
            "（出纸张序退回按部位平铺 ⇒ 多套被拆开，issue #8074）"
        )
    for rel, source in ((CSS_RENDERER, css), (BITMAP_RENDERER, bitmap)):
        if "groupBySet(" in code_face(source):
            problems.append(
                f"SS8 {rel} 自己调 `groupBySet(` 重排 / 分组出纸清单 —— "
                f"张序（每套连续）只许由 `{CONTENT_MODULE}` 的 `{SHEET_BUILDER}` 决定（issue #8074）"
            )

    # SS9（issue #8107）：**专属唛的行集合**只许在内容模块决定
    #   （用户 2026-10-29 逐字「保留货号，门幅，宽高，工艺和特殊选项 + 二维码即可」）
    #   - 内容模块必须**定义**行集合常量、并真有「按变体收窄」的过滤点（缺 ⇒ 本判据退化）；
    #   - 渲染器**不得**自己过滤（出现行集合常量 = 渲染器自己挑行 ⇒ 两条通道会分叉）；
    #   - 渲染器读变体的唯一途径 = 内容模块在 `sheet` 上给（`variant: sheet.variant`）。
    if OPTION_ROW_KEYS not in code_face(content) or VARIANT_FILTER not in code_face(content):
        problems.append(
            f"SS9 `{CONTENT_MODULE}` 缺专属唛行集合（`{OPTION_ROW_KEYS}`）或按变体收窄的过滤点"
            "（issue #8107）—— 专属唛的行集合必须只有一处真值"
        )
    for rel, source in ((CSS_RENDERER, css), (BITMAP_RENDERER, bitmap)):
        if OPTION_ROW_KEYS in code_face(source):
            problems.append(
                f"SS9 {rel} 的**代码面**出现 `{OPTION_ROW_KEYS}` —— 渲染器自己挑行 = 第二份行集合口径；"
                f"行集合只许由 `{CONTENT_MODULE}` 的 `{ROW_BUILDER}` 按 `sheet.variant` 决定"
            )
    if SHEET_VARIANT_READ not in css_face:
        problems.append(
            f"SS9 {CSS_RENDERER} 没有读内容模块给的 `{SHEET_VARIANT_READ}` —— "
            "渲染器自己判 `optionLabel` 挑行就是第二份口径"
        )

    return problems


def test_renderers_read_the_single_content_truth():
    """SS1~SS4 / SS7 / SS8：两个渲染器都读唯一真值模块，且不自己拼纸面行前缀 / 不另排张序。"""
    sources = {rel: _read(rel) for rel in _MANAGED}
    problems = _problems(sources)
    assert problems == [], "\n".join(problems)


def test_content_module_lists_every_row_prefix():
    """SS4 的正向锚：真值模块**确实**产出全部纸面前缀（不是靠删别处消红）。"""
    content = code_face(_read(CONTENT_MODULE))
    for prefix in ROW_PREFIX_LITERALS:
        assert prefix in content, f"{CONTENT_MODULE} 缺纸面前缀「{prefix}」"


def test_injection_turns_red_with_attribution():
    """SS5：三种坏形态在内存里各自判红（判据不是空断言）+ 内容指纹自证注入生效。"""
    sources = {rel: _read(rel) for rel in _MANAGED}
    assert _problems(sources) == [], "基线必须绿（否则下面的红证分不清是注入还是存量）"
    baseline = {rel: _fingerprint(text) for rel, text in sources.items()}

    # ① SS1：删掉接线（改回内联派生）
    broken = dict(sources)
    broken[CSS_RENDERER] = broken[CSS_RENDERER].replace(CONTENT_SPECIFIER, "@/lib/craft-display")
    assert _fingerprint(broken[CSS_RENDERER]) != baseline[CSS_RENDERER], "注入 ① 未生效"
    assert any("SS1" in p for p in _problems(broken)), "摘掉接线却没判红 ⇒ 判据是空断言"

    # ② SS3：在系统打印渲染器里重新内联拼一个纸面前缀
    broken = dict(sources)
    broken[CSS_RENDERER] = broken[CSS_RENDERER].replace(
        "export default function TaskCardPrint({",
        "const leaked = '客户 ' // 注入：把前缀搬回渲染器\nexport default function TaskCardPrint({",
    )
    assert _fingerprint(broken[CSS_RENDERER]) != baseline[CSS_RENDERER], "注入 ② 未生效"
    assert any("SS3" in p for p in _problems(broken)), "渲染器自己拼前缀却没判红 ⇒ 判据是空断言"

    # ③ SS7：把位图渲染器的份数读取改成自己算一份（`openCount`）⇒ 必红
    broken = dict(sources)
    broken[BITMAP_RENDERER] = broken[BITMAP_RENDERER].replace(
        "export const WASH_LABEL_MEDIA",
        "// 注入：自己算份数（第二份映射）\nconst copies = (item: any) => item.openCount ?? 1\nexport const WASH_LABEL_MEDIA",
        1,
    )
    assert _fingerprint(broken[BITMAP_RENDERER]) != baseline[BITMAP_RENDERER], "注入 ③ 未生效"
    assert any("SS7" in p for p in _problems(broken)), "自己算份数却没判红 ⇒ SS7 是空断言"

    # ④ SS4：把真值模块里的前缀清掉（「删掉别处的词」不得被读成「改完了」）
    broken = dict(sources)
    content = broken[CONTENT_MODULE]
    for prefix in ROW_PREFIX_LITERALS:
        content = content.replace(f"'{prefix}'", "''")
    broken[CONTENT_MODULE] = content
    assert _fingerprint(broken[CONTENT_MODULE]) != baseline[CONTENT_MODULE], "注入 ④ 未生效"
    assert any("SS4" in p for p in _problems(broken)), "真值模块被掏空却没判红 ⇒ 正向锚是空断言"

    # ⑤ SS7（issue #8002）：系统打印渲染器不再读共享出纸清单（改回自己按开数展开）⇒ 必红
    broken = dict(sources)
    broken[CSS_RENDERER] = broken[CSS_RENDERER].replace("washLabelSheets(", "washLabelRows(")
    assert _fingerprint(broken[CSS_RENDERER]) != baseline[CSS_RENDERER], "注入 ⑤ 未生效"
    assert any("SS7" in p for p in _problems(broken)), "不读共享出纸清单却没判红 ⇒ SS7 是空断言"

    # ⑥ SS8（issue #8074）：系统打印渲染器自己调 `groupBySet(` 重排出纸清单 ⇒ 必红（第二份套序口径）
    broken = dict(sources)
    broken[CSS_RENDERER] = broken[CSS_RENDERER].replace(
        "export default function TaskCardPrint({",
        "const legacySetOrder = groupBySet([]) // 注入：渲染器里另排一套套序\nexport default function TaskCardPrint({",
    )
    assert _fingerprint(broken[CSS_RENDERER]) != baseline[CSS_RENDERER], "注入 ⑥ 未生效"
    assert any("SS8" in p for p in _problems(broken)), "渲染器自己排套序却没判红 ⇒ SS8 是空断言"

    # ⑦ SS9（issue #8107）：系统打印渲染器自己挑专属唛行集合 ⇒ 必红（第二份行集合口径）
    broken = dict(sources)
    broken[CSS_RENDERER] = broken[CSS_RENDERER].replace(
        "export default function TaskCardPrint({",
        "const optionOnly = WASH_LABEL_OPTION_ROW_KEYS.filter(Boolean) // 注入：渲染器自己挑行\n"
        "export default function TaskCardPrint({",
    )
    assert _fingerprint(broken[CSS_RENDERER]) != baseline[CSS_RENDERER], "注入 ⑦ 未生效"
    assert any("SS9" in p for p in _problems(broken)), "渲染器自己挑行却没判红 ⇒ SS9 是空断言"


def test_comment_mention_is_not_a_violation():
    """SS6：注释里**提及**这些词不得判红（沿革必须写得清；§2.2「引用即实例」的反向对照）。"""
    sources = {rel: _read(rel) for rel in _MANAGED}
    sources[CSS_RENDERER] += "\n// 沿革：本组件原先自己拼「客户 / 用料 / 宽高」等前缀，issue #6656 起改读单一真值\n"
    assert _problems(sources) == [], "只在注释里提及纸面前缀就判红 —— 那是假红（会逼人写不清沿革）"

    # 反向对照：同样的词落进**代码面**（字符串字面量）⇒ 必须判红
    sources[CSS_RENDERER] += "\nconst legacyPrefix = '客户 赵凯'\n"
    assert any("SS3" in p for p in _problems(sources)), "代码面里的前缀没判红 ⇒ SS3 没牙"
