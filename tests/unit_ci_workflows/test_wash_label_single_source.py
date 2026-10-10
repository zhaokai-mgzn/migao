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
| SS3 | 两个渲染器的**代码面**都不得出现纸面行前缀（`客户` / `部位` / `色号` / `用料` / `宽高` / `加工方式` / `订单` / `交期` / `备注`）—— 自己派生字段 ⇒ 必红 | 在 `TaskCardPrint.tsx` 里加一句 `客户 {customerName}` ⇒ 必红 |
| SS4 | 真值模块**真的产出**全部前缀（**反空跑锚点**：防止「删掉别处的词」被当成「改完了」） | 清空真值模块里的前缀 ⇒ 必红 |
| SS5 | **注入式红证**：上面三种坏形态在内存里各自判红，且**内容指纹自证**（禁 mtime/size，issue #4260） | 注入未生效 ⇒ 必红 |
| SS6 | **反向对照**：注释里**提及**这些词不得判红（沿革要写得清，`migao-dev-flow` §2.2「引用即实例」） | 注释里加一句沿革 ⇒ **不**红 |

🔴 **本守卫只扫这三份源码**：测试与文档里出现这些词是**在描述口径**，不在射程。
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

#: 纸面行前缀（`washLabelRows` 是**唯一**拼它们的地方）
ROW_PREFIX_LITERALS = ("客户", "部位", "色号", "用料", "宽高", "加工方式", "订单", "交期", "备注")

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

    # SS4：反空跑锚点 —— 真值模块必须真的产出全部前缀
    content_face = code_face(content)
    missing = [prefix for prefix in ROW_PREFIX_LITERALS if prefix not in content_face]
    if missing:
        problems.append(
            f"SS4 `{CONTENT_MODULE}` 里找不到这些纸面前缀 {missing} —— "
            "真值模块不再产出它们（判据 3 的「别处没有」就退化成空断言）"
        )

    return problems


def test_renderers_read_the_single_content_truth():
    """SS1~SS4：两个渲染器都读唯一真值模块，且不自己拼纸面行前缀。"""
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

    # ③ SS4：把真值模块里的前缀清掉（「删掉别处的词」不得被读成「改完了」）
    broken = dict(sources)
    content = broken[CONTENT_MODULE]
    for prefix in ROW_PREFIX_LITERALS:
        content = content.replace(f"'{prefix}'", "''")
    broken[CONTENT_MODULE] = content
    assert _fingerprint(broken[CONTENT_MODULE]) != baseline[CONTENT_MODULE], "注入 ③ 未生效"
    assert any("SS4" in p for p in _problems(broken)), "真值模块被掏空却没判红 ⇒ 正向锚是空断言"


def test_comment_mention_is_not_a_violation():
    """SS6：注释里**提及**这些词不得判红（沿革必须写得清；§2.2「引用即实例」的反向对照）。"""
    sources = {rel: _read(rel) for rel in _MANAGED}
    sources[CSS_RENDERER] += "\n// 沿革：本组件原先自己拼「客户 / 用料 / 宽高」等前缀，issue #6656 起改读单一真值\n"
    assert _problems(sources) == [], "只在注释里提及纸面前缀就判红 —— 那是假红（会逼人写不清沿革）"

    # 反向对照：同样的词落进**代码面**（字符串字面量）⇒ 必须判红
    sources[CSS_RENDERER] += "\nconst legacyPrefix = '客户 赵凯'\n"
    assert any("SS3" in p for p in _problems(sources)), "代码面里的前缀没判红 ⇒ SS3 没牙"
