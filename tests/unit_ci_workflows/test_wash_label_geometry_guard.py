# case_ids: PP-011, UI-053
"""洗水码**纸面几何 × 垂直预算注释**一致性守卫（issue #5646）。

## 病根（实测，不是推断）

洗水码的纸面几何是**同一份真值的三处投影**：
① `@page { size: Wmm Hmm }`（分页尺寸）、② `.task-card-label { width; height }`（标签本体）、
③ 组件文件头那段**靠真机渲染量出来的垂直预算注释**（逐行行高 / 折行数 / 二维码行 / 内边距）。

#4946（30×60）→ #5646（**50×60**）这次改版里，①② 一改就看得见，**③ 不会** ——
旧读数（30mm 宽 / 27.6mm 版心 / 17 行上限）留在注释里**没有任何东西会变红**，
下一个人照着过期预算加一行，就会把纸面底部的二维码与人可读短码挤出纸外。
**#4949 已经实测过一次这个后果**（行①折行吃掉 2.96mm ⇒ 每张的人可读短码被裁 1.25mm），
根因正是「改了版式没重算预算」。

## 冻结口径（G1~G7）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| G1 | `@page` 的 W×H 与 `.task-card-label` 的 width/height **字面一致** | 只把 `@page` 的 50mm 改回 30mm ⇒ 必红 |
| G2 | 文件头预算注释**声明当前几何**（`Wmm × Hmm`） | 注释写回 `30mm × 60mm` ⇒ 必红 |
| G3 | 预算注释**结构完整**：版心 / 每行 / 二维码 / 内边距 / `≤` 五要素齐备 | 删掉任一要素 / 清空预算段 ⇒ 必红 |
| G4 | **版心宽可复算**：注释「版心宽 Xmm」== `width − 2 × padding`（±0.01mm） | **只把容器宽改回 30mm** ⇒ 必红（G2 挡不住这一路，见下） |
| G5 | **可用高度可复算**：注释「可用 Hmm」== `height − 2 × padding` | 只改 height 不改注释 ⇒ 必红 |
| G6 | **每行行高可复算**：注释「每行 Xmm」== `font-size × line-height`（±0.01mm） | 只改字号/行高不改注释 ⇒ 必红 |
| G7 | 注入式红证 + **内容指纹**自证（禁 mtime/size，issue #4260） | 注入未生效 ⇒ 必红 |

🔴 **G2 与 G4 必须成对，缺一不可**（本守卫第一版只有 G2，被自己的红证实测打回）：
预算注释里**必须**写清沿革（「由 #4946 的 30mm × 60mm 改成本版的 50mm × 60mm」），
于是**旧几何也合法地出现在注释里** ⇒ 只做「注释里有没有 `Wmm × Hmm` 这个子串」的地毯式判定，
在「代码已退回 30mm、注释仍写着新旧两个值」时**照样通过 = 假绿**（实测：把 `@page` 与容器一起退回
30mm×60mm，G2 仍绿）。G4 用**可复算恒等式**堵这一路：代码宽一变，`width − 2 × padding` 立刻不等于
注释里的版心 ⇒ 必红。这是 `migao-dev-flow` §2.2「引用即实例」在本守卫里的**实例**。

⚠️ **G4/G5/G6 刻意用「可复算恒等式」而不是钉死读数**：读数是**从几何算出来的**，
几何一变恒等式自己就红 —— 这才是「让改动者停下来重算」的摩擦，
而不是在守卫里再抄一份会漂移的数字（§17.3「同一真值两处投影」）。

⚠️ **本守卫只扫组件源码**。用例库（`.github/cases/processing.yml`）的 `merge_log` 与
`docs/**` 沿革里**引用**旧几何是**历史记录**，不在射程 —— 判据不区分「引用」与「使用」会产出假红
（`migao-dev-flow` §2.2「引用即实例」）。

**未固化项（照实登记）**：没有判据拦住「注释里**同时**保留旧几何的**历史对照**」这种形态
（#5646 的注释里就**需要**写「由 30mm 改为 50mm」才讲得清沿革）⇒
「旧读数只许出现在沿革句里」**不可机械判定**，本守卫**不做**这条。实例判据（TS 侧
`expect(css).not.toContain('30mm 60mm')`）只钉住**活的 CSS 块**。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 洗水码版式组件（唯一受管文件）
LABEL_SRC = "frontend/admin-web/src/components/production/TaskCardPrint.tsx"

#: `@page { size: Wmm Hmm; … }`
_PAGE_RE = re.compile(r"@page\s*\{\s*size:\s*([0-9.]+)mm\s+([0-9.]+)mm")
#: `.task-card-label { width: Wmm; height: Hmm; … }`
_LABEL_RE = re.compile(r"\.task-card-label\s*\{\s*width:\s*([0-9.]+)mm;\s*height:\s*([0-9.]+)mm")
#: 标签本体的 padding（`padding: 1.2mm;`）
_PADDING_RE = re.compile(r"\.task-card-label\s*\{[^}]*?padding:\s*([0-9.]+)mm")
#: 标签本体的 font-size / line-height（`font-size: 6pt; line-height: 1.2;`）
_FONT_RE = re.compile(r"\.task-card-label\s*\{[^}]*?font-size:\s*([0-9.]+)pt;\s*line-height:\s*([0-9.]+)")
#: CSS 块（JSX 里的 `{`<style>{`…`}</style>`}`，字符串感知的去注释**不会**动模板串内部）
_STYLE_RE = re.compile(r"<style>\{(?P<css>.*?)\}</style>", re.S)
#: 文件头 JSDoc（`/** … */`）
_HEADER_RE = re.compile(r"/\*\*(?P<body>.*?)\*/", re.S)

PT_TO_MM = 25.4 / 72.0
#: 行高恒等式的容差（浏览器把 9.6px 量出来、注释里写 2.538mm 而 6pt×1.2 = 2.54mm）
LINES_TOLERANCE_MM = 0.01


def _read(rel: str) -> str:
    """读受管文件；**不存在 ⇒ 直接失败**（路径漂移不得退化成静默跳过 = 空跑通过）。"""
    path = REPO_ROOT / rel
    if not path.is_file():
        raise AssertionError(f"受管文件不存在：{rel} —— 路径漂移 / 文件被删 ⇒ 红（**不得**静默跳过）")
    return path.read_text(encoding="utf-8")


def _fingerprint(text: str) -> str:
    """内容指纹（**禁 mtime/size**，issue #4260：注入必须自证生效）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _css_block(src: str) -> str:
    """组件里那段活 CSS（`<style>{` 模板串内部）—— G1/G4/G5/G6 的取值来源。"""
    hit = _STYLE_RE.search(src)
    return hit.group("css") if hit else ""


def _header(src: str) -> str:
    """文件头 JSDoc 正文（预算注释所在处）。"""
    hit = _HEADER_RE.search(src)
    return hit.group("body") if hit else ""


def _geometry(css: str) -> tuple[float, float, float, float]:
    """→ `(page_w, page_h, label_w, label_h)`；任一缺失 ⇒ 抛 `AssertionError`（不静默）。"""
    page = _PAGE_RE.search(css)
    label = _LABEL_RE.search(css)
    if not page or not label:
        raise AssertionError(
            "洗水码几何解析失败：`@page { size: … }` 或 `.task-card-label { width…; height… }` 缺失/改形 —— "
            "判据按字面量解析，改写法必须同步本守卫（**不得**静默跳过）"
        )
    return float(page.group(1)), float(page.group(2)), float(label.group(1)), float(label.group(2))


def _declared(header: str, keyword: str) -> float | None:
    """注释里 `关键词 … Xmm` 声明的读数；没写 ⇒ `None`（判据据此判红）。"""
    match = re.search(re.escape(keyword) + r"[^0-9]{0,14}([0-9]+(?:\.[0-9]+)?)\s*mm", header)
    return float(match.group(1)) if match else None


def _problems(src: str) -> list[str]:
    """G1~G6 的全部违规（纯函数 ⇒ 便于注入式红证）。空列表 = 合规。"""
    css, header = _css_block(src), _header(src)
    problems: list[str] = []
    if not css:
        return ["找不到活 CSS 块（`<style>{` … `}</style>`）—— 判据无从取值（**不得**静默通过）"]
    if not header:
        return ["找不到文件头 JSDoc（预算注释所在处）—— 判据无从取值（**不得**静默通过）"]

    page_w, page_h, label_w, label_h = _geometry(css)

    # G1：@page 与容器几何字面一致
    if (page_w, page_h) != (label_w, label_h):
        problems.append(
            f"G1 `@page` {page_w}mm×{page_h}mm 与 `.task-card-label` {label_w}mm×{label_h}mm **不一致** —— "
            "两处是同一份几何，必须同时改"
        )

    # G2：文件头注释声明同一对几何
    if f"{page_w:g}mm × {page_h:g}mm" not in header:
        problems.append(
            f"G2 文件头预算注释**未声明**当前几何 `{page_w:g}mm × {page_h:g}mm` —— "
            "注释与代码脱节（#4946→#5646 的形态：代码改了、实测读数还留着旧值）"
        )

    # G3：预算注释结构完整（版心 / 每行 / 二维码 / 内边距 / ≤ 比较）
    for keyword in ("版心", "每行", "二维码", "内边距"):
        if keyword not in header:
            problems.append(f"G3 预算注释缺要素「{keyword}」—— 没重写实测账")
    if "≤" not in header:
        problems.append("G3 预算注释缺 `≤` 比较 —— 没有「合计 ≤ 可用高度」这一步就不叫预算")

    # G4/G5：版心宽 == width − 2 × padding；可用高度 == height − 2 × padding（全部现取 CSS）
    # ⚠️ G4 是**必需**的第二道：预算注释必须写沿革（旧几何也会合法地出现在注释里），
    # 于是「代码退回旧几何、注释里新旧两个值都在」时 G2 的子串判定照样通过（实测假绿）——
    # 恒等式才能在代码宽一变时立刻红。
    pad = _PADDING_RE.search(css)
    if not pad:
        problems.append("G4/G5 解析不出 `.task-card-label` 的 `padding` ⇒ 版心宽 / 可用高度均无法复算")
    else:
        pad_mm = float(pad.group(1))

        expect_content = label_w - 2 * pad_mm
        got_content = _declared(header, "版心宽")
        if got_content is None:
            problems.append("G4 预算注释未声明「版心宽 …mm」")
        elif abs(got_content - expect_content) > LINES_TOLERANCE_MM:
            problems.append(
                f"G4 注释声明「版心宽 {got_content}mm」，但按现取几何复算 `{label_w:g} − 2×{pad_mm:g}` = "
                f"{expect_content:g}mm ⇒ 注释没跟着几何重算（**G2 的子串判定挡不住这一路**）"
            )

        expect_avail = label_h - 2 * pad_mm
        got_avail = _declared(header, "可用")
        if got_avail is None:
            problems.append("G5 预算注释未声明「可用 …mm」高度")
        elif abs(got_avail - expect_avail) > LINES_TOLERANCE_MM:
            problems.append(
                f"G5 注释声明「可用 {got_avail}mm」，但按现取几何复算 `{label_h:g} − 2×{pad_mm:g}` = "
                f"{expect_avail:g}mm ⇒ 注释没跟着几何重算"
            )

    # G6：每行行高 == font-size × line-height
    font = _FONT_RE.search(css)
    if not font:
        problems.append("G6 解析不出 `.task-card-label` 的 `font-size` / `line-height` ⇒ 行高无法复算")
    else:
        expect_line = float(font.group(1)) * float(font.group(2)) * PT_TO_MM
        got_line = _declared(header, "每行")
        if got_line is None:
            problems.append("G6 预算注释未声明「每行 …mm」行高")
        elif abs(got_line - expect_line) > LINES_TOLERANCE_MM:
            problems.append(
                f"G6 注释声明「每行 {got_line}mm」，但按现取 `{font.group(1)}pt × {font.group(2)}` 复算 = "
                f"{expect_line:.3f}mm ⇒ 注释没跟着字号/行高重算"
            )

    return problems


# ── G1~G6：真值侧判据 ────────────────────────────────────────────────────────

def test_g1_g6_wash_label_geometry_and_budget_comment_are_consistent():
    """真值侧：组件几何自洽 + 文件头预算注释与几何可复算一致（红就说明该重算预算了）。"""
    problems = _problems(_read(LABEL_SRC))
    assert problems == [], f"`{LABEL_SRC}` 几何/预算注释违规：\n  " + "\n  ".join(problems)


def test_g0_anti_noop_geometry_is_parsed_and_nonempty():
    """反空跑锚点：几何**真解析出来了**且是有限正数 —— 否则上面那条是空判据（§「空跑」）。"""
    page_w, page_h, label_w, label_h = _geometry(_css_block(_read(LABEL_SRC)))
    assert page_w > 0 and page_h > 0 and label_w > 0 and label_h > 0, (
        f"几何解析出非正数：page={page_w}×{page_h} label={label_w}×{label_h}"
    )


# ── G7：注入式红证 + 内容指纹自证 ─────────────────────────────────────────────

def test_g7_injected_geometry_drift_is_red():
    """G7：只改一处几何 / 两处都退回旧值 / 注释退回旧值 / 改行高 ⇒ 判据必红；并用**内容指纹**自证注入生效。"""
    src = _read(LABEL_SRC)
    assert _problems(src) == [], "原文件本应干净（G1~G6 已单独判）—— 这里先红说明判据或预期已变"

    # 注入 A：只把 `@page` 的宽度改回 30mm（容器不动）⇒ G1 必红
    css = _css_block(src)
    page_w = float(_PAGE_RE.search(css).group(1))
    injected_a = src.replace(f"size: {page_w:g}mm", "size: 30mm", 1)
    assert injected_a != src, f"找不到注入点 `size: {page_w:g}mm` ⇒ 本红证会**空跑**"
    assert _fingerprint(injected_a) != _fingerprint(src), "注入后内容指纹未变（**禁 mtime/size**）"
    assert _problems(injected_a), "只改 `@page` 宽度后判据**没判红** ⇒ G1 是空判据"

    # 注入 B：**两处几何一起**退回 30mm×60mm（注释仍带新旧两个值）⇒ G4 必红
    #          —— 这一路 G2 的子串判定挡不住（实测假绿），是本守卫第一版被自己的红证打回的那一处
    injected_b = src.replace(f"width: {page_w:g}mm; height: 60mm", "width: 30mm; height: 60mm", 1)
    assert injected_b != src, "找不到容器宽注入点 ⇒ 本红证会**空跑**"
    assert _problems(injected_b), "容器宽退回 30mm 后判据**没判红** ⇒ G4 是空判据（G2 会假绿）"

    # 注入 C：把文件头注释里的几何退回 30mm × 60mm ⇒ G2 必红
    injected_c = src.replace(f"{page_w:g}mm × 60mm", "30mm × 60mm", 1)
    assert injected_c != src, "找不到注入点「Wmm × 60mm」⇒ 本红证会**空跑**"
    assert _problems(injected_c), "注释退回旧几何后判据**没判红** ⇒ G2 是空判据"

    # 注入 D：把 `line-height` 从 1.2 改成 2 ⇒ G6 必红（每行行高恒等式不再成立）
    injected_d = re.sub(r"(line-height:\s*)1\.2\b", r"\g<1>2", css, count=1)
    assert injected_d != css, "找不到 `line-height: 1.2` 注入点 ⇒ 本红证会**空跑**"
    injected_d_src = src.replace(css, injected_d, 1)
    assert _problems(injected_d_src), "改行高后判据**没判红** ⇒ G6 是空判据"
