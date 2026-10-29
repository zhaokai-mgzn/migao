# case_ids: PP-011, UI-053
"""洗水码**纸面几何 × 垂直预算注释**一致性守卫（issue #5646）。

## 病根（实测，不是推断）

洗水码的纸面几何是**同一份真值的三处投影**：
① `@page { size: Wmm Hmm }`（分页尺寸）、② `.task-card-label { width; height }`（标签本体）、
③ 组件文件头那段**靠真机渲染量出来的垂直预算注释**（逐行行高 / 折行数 / 二维码行 / 内边距）。

#4946（30×60）→ #5646（**50×60**）→ 2026-10-25（50×70）→ 2026-10-26（#7816：固定 50×150）
→ 2026-10-27（#7960：50×119 / 11pt）→ **2026-10-28（issue #7979：50×140 + 上下各留白 15mm）**
这次改版里，①② 一改就看得见，**③ 不会** ——
旧读数（30mm 宽 / 27.6mm 版心 / 17 行上限）留在注释里**没有任何东西会变红**，
下一个人照着过期预算加一行，就会把纸面底部的二维码与人可读短码挤出纸外。
**#4949 已经实测过一次这个后果**（行①折行吃掉 2.96mm ⇒ 每张的人可读短码被裁 1.25mm），
根因正是「改了版式没重算预算」。

## 冻结口径（G1~G7）

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| G1 | `@page` 的 W×H 与 `.task-card-label` 的 width/height **字面一致** | 把介质换成 30×40 而容器不动 ⇒ 必红 |
| G2 | 文件头预算注释**声明当前几何**（`Wmm × Hmm`） | 注释写回 `30mm × 60mm` ⇒ 必红 |
| G3 | 预算注释**结构完整**：版心 / 每行 / 二维码 / 内边距 / `≤` 五要素齐备 | 删掉任一要素 / 清空预算段 ⇒ 必红 |
| G4 | **版心宽可复算**：注释「版心宽 Xmm」== `width − 横向内边距`（±0.01mm） | **只把容器宽改回 30mm** ⇒ 必红（G2 挡不住这一路，见下） |
| G5 | **可用高度可复算**：注释「可用 Hmm」== `height − 纵向内边距`（2026-10-28 起 = 上留白 15mm + 下净空 15mm） | 只改 height 不改注释 ⇒ 必红 |
| G6 | **每行行高可复算**：注释「每行 Xmm」== `font-size × line-height`（±0.01mm） | 只改字号/行高不改注释 ⇒ 必红 |
| G7 | 注入式红证 + **内容指纹**自证（禁 mtime/size，issue #4260） | 注入未生效 ⇒ 必红 |
| G8 | **专属唛的短纸高 == 矩阵**（issue #8107）：`.task-card-label--option { height: Hmm }` 的 H == 命名页介质 `pageBoxMm.heightMm` | 把专属唛高改回 140mm（常规唛那张）⇒ 必红 |
| G9 | **命名页同源**：容器 `page: <名字>` 与 `printNamedPageRule('<名字>', '<介质id>')` 逐字对上，且该介质的 `pageSize` 与容器宽/高一致 | 删命名页 / 换一个介质 id ⇒ 必红 |
| G10 | **专属唛预算段可复算**（`【专属唛预算】` 之后的段）：版心宽 / 可用 / 每行三条恒等式按**短纸**复算，且 `≤ Hmm` 用的是这张短纸的高 | 删段 / 把「可用」改成 110mm（常规唛的）⇒ 必红 |
| G11 | 注入式红证（专属唛：改回 140 / 删命名页 / 删预算段 / 改预算读数）+ 内容指纹自证 | 注入未生效 ⇒ 必红 |

🔴 **G2 与 G4 必须成对，缺一不可**（本守卫第一版只有 G2，被自己的红证实测打回）：
预算注释里**必须**写清沿革（「由 #4946 的 30mm × 60mm 改成本版的 50mm × 60mm」），
于是**旧几何也合法地出现在注释里** ⇒ 只做「注释里有没有 `Wmm × Hmm` 这个子串」的地毯式判定，
在「代码已退回 30mm、注释仍写着新旧两个值」时**照样通过 = 假绿**（实测：把 `@page` 与容器一起退回
30mm×60mm，G2 仍绿）。G4 用**可复算恒等式**堵这一路：代码宽一变，`width − 横向内边距` 立刻不等于
注释里的版心 ⇒ 必红。这是 `migao-dev-flow` §2.2「引用即实例」在本守卫里的**实例**。

⚠️ **G4/G5/G6 刻意用「可复算恒等式」而不是钉死读数**：读数是**从几何算出来的**，
几何一变恒等式自己就红 —— 这才是「让改动者停下来重算」的摩擦，
而不是在守卫里再抄一份会漂移的数字（§17.3「同一真值两处投影」）。

🔴 **G2~G6 只在「常规唛段」上跑、G8~G10 只在「专属唛段」上跑**（issue #8107 的两段预算以
`【专属唛预算】` 分段）：两段都写「版心宽 / 可用 / 每行」，全文 `re.search` 只会取到第一处 ⇒
专属唛那段的读数将**永远不会被复算**（改坏了也不红 = 空判据）。

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
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 洗水码版式组件（唯一受管文件）
LABEL_SRC = "frontend/admin-web/src/components/production/TaskCardPrint.tsx"

#: `@page { size: Wmm Hmm; … }`
_PAGE_RE = re.compile(r"@page\s*\{\s*size:\s*([0-9.]+)mm\s+([0-9.]+)mm")
#: 写法 A（issue #5914）：`printPageRule('<介质id>')` —— 纸型由介质矩阵生成，尺寸从矩阵取。
#: 🔴 #7776 的动态纸长写法（`printPageRuleForLength('<id>', <纸长变量>)`）随 issue #7816 退场
#: （用户 2026-10-26「水洗唛长度不足，设置为打印50*150」⇒ 纸型固定）—— 本正则**故意不认**它：
#: 有人把动态纸长写回来 ⇒ 解析不出介质 id ⇒ 判据红（不是静默跳过）。
_PAGE_RULE_CALL_RE = re.compile(r"printPageRule\(\s*'([a-z0-9-]+)'")
MEDIA_MATRIX = REPO_ROOT / "frontend/admin-web" / "src" / "lib" / "print-media.json"


def _matrix() -> dict[str, dict]:
    """介质矩阵（真值源 = `frontend/admin-web/src/lib/print-media.json`）。"""
    data = json.loads(MEDIA_MATRIX.read_text(encoding="utf-8"))
    return {str(spec.get("id")): spec for spec in data.get("media", [])}


def _page_mm_from_matrix(media_id: str) -> tuple[float, float]:
    """从介质矩阵取该介质的纸型 mm（`pageSize` 形如 `50mm 60mm`）；未登记 ⇒ 抛错（不静默）。"""
    data = json.loads(MEDIA_MATRIX.read_text(encoding="utf-8"))
    for spec in data.get("media", []):
        if str(spec.get("id")) != media_id:
            continue
        parts = str(spec.get("pageSize", "")).split()
        if len(parts) != 2 or not all(part.endswith("mm") for part in parts):
            raise AssertionError(f"介质 `{media_id}` 的 pageSize 不是 `Wmm Hmm`：{spec.get('pageSize')!r}")
        return float(parts[0][:-2]), float(parts[1][:-2])
    raise AssertionError(f"介质 `{media_id}` 不在 {MEDIA_MATRIX.name} 里 ⇒ 判据无从判定（不静默）")
#: `.task-card-label { width: Wmm; height: Hmm; … }`
_LABEL_RE = re.compile(r"\.task-card-label\s*\{\s*width:\s*([0-9.]+)mm;\s*height:\s*([0-9.]+)mm")
#: 专属唛的修饰类（issue #8107）：`.task-card-label--option { height: Hmm; page: <命名页>; }`
_OPTION_RE = re.compile(
    r"\.task-card-label--option\s*\{\s*height:\s*([0-9.]+)mm;\s*page:\s*([A-Za-z0-9_-]+)\s*;?\s*\}"
)
#: 命名 `@page` 的写法：`printNamedPageRule('<名字>', '<介质id>')`（issue #8107）
_NAMED_PAGE_CALL_RE = re.compile(r"printNamedPageRule\(\s*'([A-Za-z0-9_-]+)'\s*,\s*'([a-z0-9-]+)'\s*\)")
#: 文件头里把两段预算分开的**唯一标记**（缺它 ⇒ G10 判红；两段各自可复算，互不干扰）
OPTION_BUDGET_MARK = "【专属唛预算】"
#: 标签本体的 padding（单个值或 CSS 简写：`padding: 15mm 1.2mm 15mm;`）
_PADDING_RE = re.compile(r"\.task-card-label\s*\{[^}]*?padding:\s*([^;}]+)")
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
    """组件里那段活 CSS（`<style>{` 模板串内部）—— G1/G4/G5/G6 的取值来源。

    🔴 单据现在会发**多块** `<style>`（issue #5914：条件化的 `@page` 单独一块 + 主体 CSS 一块）
    ⇒ 取**含 `.task-card-label` 的那一块**（都没有就退回最长的一块），**不许**盲取第一块
    —— 盲取会把「条件纸型」那块当成版式本体 ⇒ 判据恒抛（假红）。
    """
    blocks = [hit.group("css") for hit in _STYLE_RE.finditer(src)]
    if not blocks:
        return ""
    for block in blocks:
        if ".task-card-label" in block:
            return block
    return max(blocks, key=len)


def _header(src: str) -> str:
    """文件头 JSDoc 正文（预算注释所在处）。"""
    hit = _HEADER_RE.search(src)
    return hit.group("body") if hit else ""


def _geometry(src: str, css: str) -> tuple[float, float, float, float]:
    """→ `(page_w, page_h, label_w, label_h)`；任一缺失 ⇒ 抛 `AssertionError`（不静默）。

    纸型支持两种写法（issue #5914 起单据一律用写法 A）：
    A `printPageRule('<介质id>')` —— 尺寸取自介质矩阵；
    B 自写 `@page { size: Wmm Hmm; … }` —— 与容器字面比对。
    """
    page = _PAGE_RE.search(css)
    if page:
        page_w, page_h = float(page.group(1)), float(page.group(2))
    else:
        call = _PAGE_RULE_CALL_RE.search(src)
        if call is None:
            raise AssertionError(
                "洗水码几何解析失败：既没有 `@page { size: … }` 字面量、也没有 "
                "`printPageRule('<介质id>')` 调用 —— 判据按这两种写法解析，改写法必须同步本守卫（**不得**静默跳过）"
            )
        page_w, page_h = _page_mm_from_matrix(call.group(1))
    label = _LABEL_RE.search(css)
    if not label:
        raise AssertionError(
            "洗水码几何解析失败：`.task-card-label { width…; height… }` 缺失/改形 —— "
            "判据按字面量解析，改写法必须同步本守卫（**不得**静默跳过）"
        )
    return page_w, page_h, float(label.group(1)), float(label.group(2))


def _declared(header: str, keyword: str) -> float | None:
    """注释里 `关键词 … Xmm` 声明的读数；没写 ⇒ `None`（判据据此判红）。"""
    match = re.search(re.escape(keyword) + r"[^0-9]{0,14}([0-9]+(?:\.[0-9]+)?)\s*mm", header)
    return float(match.group(1)) if match else None


def _budget_regions(header: str) -> tuple[str, str]:
    """把文件头的预算注释切成 `(常规唛段, 专属唛段)`（issue #8107）。

    🔴 **为什么要切段**：两段都写「版心宽 / 可用 / 每行」，全文 `re.search` 只会取到**第一处** ⇒
    专属唛那段的读数**永远不会被复算**（改坏了也不红 = 空判据）。切段后两段各自复算，
    缺标记 ⇒ 专属唛段为空串 ⇒ G10 判红（不是静默通过）。
    """
    if OPTION_BUDGET_MARK not in header:
        return header, ""
    regular, option = header.split(OPTION_BUDGET_MARK, 1)
    return regular, option


def _spec(media_id: str) -> dict:
    """介质矩阵里的一条（未登记 ⇒ 抛错，不静默）。"""
    spec = _matrix().get(media_id)
    if spec is None:
        raise AssertionError(f"介质 `{media_id}` 不在 {MEDIA_MATRIX.name} 里 ⇒ 判据无从判定（不静默）")
    return spec


def _box_height_mm(spec: dict) -> float:
    box = spec.get("pageBoxMm") or {}
    height = box.get("heightMm")
    if not isinstance(height, (int, float)):
        raise AssertionError(f"介质 `{spec.get('id')}` 缺 `pageBoxMm.heightMm` ⇒ 纸高无法复算（不静默）")
    return float(height)


def _padding_mm(raw: str) -> tuple[float, float]:
    """`padding` 简写 → `(横向合计, 纵向合计)`（mm）。

    支持 1~4 个值（CSS 简写口径：上 / 右 / 下 / 左；1 值 = 四边；2 值 = 上下 / 左右；
    3 值 = 上 / 左右 / 下）。🔴 2026-10-28 起 `.task-card-label` 用 `padding: 15mm 1.2mm 15mm`
    （上 = 顶部留白、下 = 二维码与底部虚线的净空）—— 旧的「2 × 单值」会把可用高度算成 110mm 以外的值，
    而真实可用是 **110mm**（少算 ⇒ 预算注释与代码会对不上却看不出来）。
    """
    values = [float(v) for v in re.findall(r"([0-9.]+)mm", raw)]
    if not values or len(values) > 4:
        raise AssertionError(f"`.task-card-label` 的 padding 解析不出 1~4 个 mm 值：{raw!r}")
    if len(values) == 1:
        top = right = bottom = left = values[0]
    elif len(values) == 2:
        top = bottom = values[0]
        right = left = values[1]
    elif len(values) == 3:
        top, right, bottom = values
        left = right
    else:
        top, right, bottom, left = values
    return left + right, top + bottom


def _budget_identities(
    region: str,
    *,
    width_mm: float,
    height_mm: float,
    pad_x: float,
    pad_y: float,
    font_pt: float | None,
    line_height: float | None,
    tag: str,
) -> list[str]:
    """三段**可复算恒等式**（版心宽 / 可用高度 / 每行行高）—— 常规唛与专属唛各跑一次（issue #8107）。

    读数一律**现取 CSS**（width / height / padding / font-size / line-height），因此几何一变，
    注释里的数就不再相等 ⇒ 判红（这才是「让改动者停下来重算」的摩擦，而不是再抄一份会漂移的数字）。
    """
    problems: list[str] = []
    expect_content = width_mm - pad_x
    got_content = _declared(region, "版心宽")
    if got_content is None:
        problems.append(f"{tag} 预算注释未声明「版心宽 …mm」")
    elif abs(got_content - expect_content) > LINES_TOLERANCE_MM:
        problems.append(
            f"{tag} 注释声明「版心宽 {got_content}mm」，但按现取几何复算 `{width_mm:g} − 横向内边距 {pad_x:g}` = "
            f"{expect_content:g}mm ⇒ 注释没跟着几何重算（**G2 的子串判定挡不住这一路**）"
        )

    expect_avail = height_mm - pad_y
    got_avail = _declared(region, "可用")
    if got_avail is None:
        problems.append(f"{tag} 预算注释未声明「可用 …mm」高度")
    elif abs(got_avail - expect_avail) > LINES_TOLERANCE_MM:
        problems.append(
            f"{tag} 注释声明「可用 {got_avail}mm」，但按现取几何复算 `{height_mm:g} − 纵向内边距 {pad_y:g}` = "
            f"{expect_avail:g}mm ⇒ 注释没跟着几何重算"
        )

    if font_pt is None or line_height is None:
        problems.append(f"{tag} 解析不出正文字号 / 行高 ⇒ 每行行高无法复算")
        return problems
    expect_line = font_pt * line_height * PT_TO_MM
    got_line = _declared(region, "每行")
    if got_line is None:
        problems.append(f"{tag} 预算注释未声明「每行 …mm」行高")
    elif abs(got_line - expect_line) > LINES_TOLERANCE_MM:
        problems.append(
            f"{tag} 注释声明「每行 {got_line}mm」，但按现取 `{font_pt:g}pt × {line_height:g}` 复算 = "
            f"{expect_line:.3f}mm ⇒ 注释没跟着字号/行高重算"
        )
    return problems


def _problems(src: str) -> list[str]:
    """G1~G10 的全部违规（纯函数 ⇒ 便于注入式红证）。空列表 = 合规。"""
    css, header = _css_block(src), _header(src)
    # 🔴 两段预算各自复算（issue #8107）：常规唛段 / 专属唛段（后者以 OPTION_BUDGET_MARK 起头）
    regular_header, option_header = _budget_regions(header)
    problems: list[str] = []
    if not css:
        return ["找不到活 CSS 块（`<style>{` … `}</style>`）—— 判据无从取值（**不得**静默通过）"]
    if not header:
        return ["找不到文件头 JSDoc（预算注释所在处）—— 判据无从取值（**不得**静默通过）"]

    page_w, page_h, label_w, label_h = _geometry(src, css)

    # G1：@page 与容器几何字面一致
    if (page_w, page_h) != (label_w, label_h):
        problems.append(
            f"G1 `@page` {page_w}mm×{page_h}mm 与 `.task-card-label` {label_w}mm×{label_h}mm **不一致** —— "
            "两处是同一份几何，必须同时改"
        )

    # G2：文件头注释声明同一对几何（**常规唛段**——专属唛段另有自己的几何，见 G8/G10）
    if f"{page_w:g}mm × {page_h:g}mm" not in regular_header:
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

    # G4/G5/G6：常规唛的三段可复算恒等式（现取 CSS 复算，注释与代码脱节 ⇒ 红）
    # ⚠️ G4 是**必需**的第二道：预算注释必须写沿革（旧几何也会合法地出现在注释里），
    # 于是「代码退回旧几何、注释里新旧两个值都在」时 G2 的子串判定照样通过（实测假绿）——
    # 恒等式才能在代码宽一变时立刻红。
    pad = _PADDING_RE.search(css)
    font = _FONT_RE.search(css)
    pad_x: float | None = None
    pad_y: float | None = None
    font_pt: float | None = None
    line_height: float | None = None
    if not pad:
        problems.append("G4/G5 解析不出 `.task-card-label` 的 `padding` ⇒ 版心宽 / 可用高度均无法复算")
    else:
        pad_x, pad_y = _padding_mm(pad.group(1))
    if not font:
        problems.append("G6 解析不出 `.task-card-label` 的 `font-size` / `line-height` ⇒ 行高无法复算")
    else:
        font_pt, line_height = float(font.group(1)), float(font.group(2))
    if pad_x is not None and pad_y is not None:
        problems.extend(
            _budget_identities(
                regular_header,
                width_mm=label_w,
                height_mm=label_h,
                pad_x=pad_x,
                pad_y=pad_y,
                font_pt=font_pt,
                line_height=line_height,
                tag="G4/G5/G6",
            )
        )

    # ── G8/G9/G10：专属唛（短纸 50×100）各自可复算（issue #8107）──────────────────
    option = _OPTION_RE.search(css)
    named = dict(_NAMED_PAGE_CALL_RE.findall(src))
    option_h: float | None = None
    if option is None:
        problems.append(
            "G8 找不到 `.task-card-label--option { height: …mm; page: … }` —— 专属唛的短纸型缺失"
            "（或改形）；判据按字面量解析，改写法必须同步本守卫（**不得**静默跳过）"
        )
    else:
        option_h = float(option.group(1))
        page_name = option.group(2)
        # G8：容器高 == 介质矩阵里那张短纸的高（只改 CSS 不改矩阵、或反过来 ⇒ 必红）
        if page_name not in named:
            problems.append(
                f"G9 容器声明 `page: {page_name}`，但源码里没有 `printNamedPageRule('{page_name}', '<介质id>')`"
                " —— 命名页缺失 ⇒ 专属唛会按文档级 @page 分页（两种纸高并存失效）"
            )
        else:
            media_id = named[page_name]
            spec = _spec(media_id)
            expect_h = _box_height_mm(spec)
            if abs(option_h - expect_h) > LINES_TOLERANCE_MM:
                problems.append(
                    f"G8 `.task-card-label--option` 高 {option_h:g}mm，但命名页介质 `{media_id}` 的"
                    f" pageBoxMm 高是 {expect_h:g}mm ⇒ 容器与纸型不是同一张纸（两种纸长 = 两种标签纸）"
                )
            # G9：命名页名与 CSS 的 `page:` 一致，且介质登记的是「Wmm Hmm」可解析值
            size_w, size_h = _page_mm_from_matrix(media_id)
            if abs(size_h - option_h) > LINES_TOLERANCE_MM or abs(size_w - label_w) > LINES_TOLERANCE_MM:
                problems.append(
                    f"G9 命名页 `@page {page_name}` 的纸型 {size_w:g}mm × {size_h:g}mm 与容器"
                    f"（{label_w:g}mm 宽 / {option_h:g}mm 高）不一致 —— 命名 @page 必须与介质矩阵逐字一致"
                )

    # G10：专属唛的**预算注释段**（缺段 / 读数与代码脱节 ⇒ 红）
    if not option_header.strip():
        problems.append(
            f"G10 文件头没有专属唛预算段（标记 `{OPTION_BUDGET_MARK}`）—— 专属唛的短纸型读数与代码脱节"
            "（改了纸高却没人重算预算 = #4946 的老病）"
        )
    elif option_h is not None and pad_x is not None and pad_y is not None:
        problems.extend(
            _budget_identities(
                option_header,
                width_mm=label_w,
                height_mm=option_h,
                pad_x=pad_x,
                pad_y=pad_y,
                font_pt=font_pt,
                line_height=line_height,
                tag="G10",
            )
        )
        # 整张预算的比较式必须拿**这张短纸**的高（写成 140mm ⇒ 必红）
        if f"≤ {option_h:g}mm" not in option_header:
            problems.append(
                f"G10 专属唛预算注释没有 `≤ {option_h:g}mm` 比较式 —— 预算必须对**这张短纸**成立"
                "（写成 140mm 那张 ⇒ 专属唛的纸长就又成了一句空话）"
            )

    return problems


# ── G1~G6：真值侧判据 ────────────────────────────────────────────────────────

def test_g1_g6_wash_label_geometry_and_budget_comment_are_consistent():
    """真值侧：组件几何自洽 + 文件头预算注释与几何可复算一致（红就说明该重算预算了）。"""
    problems = _problems(_read(LABEL_SRC))
    assert problems == [], f"`{LABEL_SRC}` 几何/预算注释违规：\n  " + "\n  ".join(problems)


def test_g0_anti_noop_geometry_is_parsed_and_nonempty():
    """反空跑锚点：几何**真解析出来了**且是有限正数 —— 否则上面那条是空判据（§「空跑」）。"""
    src = _read(LABEL_SRC)
    page_w, page_h, label_w, label_h = _geometry(src, _css_block(src))
    assert page_w > 0 and page_h > 0 and label_w > 0 and label_h > 0, (
        f"几何解析出非正数：page={page_w}×{page_h} label={label_w}×{label_h}"
    )
    # 反空跑锚点（issue #8107）：专属唛的短纸型 / 命名页 / 专属预算段**都真解析出来了** ——
    # 否则 G8~G10 是一组空判据（文件里没有这些东西时它们只会生产「缺失」类问题，看起来一样红）
    option = _OPTION_RE.search(_css_block(src))
    assert option is not None and option.group(2).strip() != "", (
        "`.task-card-label--option` 解析失败（或解析不出命名页）⇒ G8 无从判定"
    )
    assert float(option.group(1)) > 0, "专属唛容器高解析出非正数"
    named = dict(_NAMED_PAGE_CALL_RE.findall(src))
    assert option.group(2) in named, "容器声明的命名页在源码里找不到 ⇒ G9 无从判定"
    assert _box_height_mm(_spec(named[option.group(2)])) > 0, "命名页介质的纸高解析出非正数"
    assert _budget_regions(_header(src))[1].strip(), "专属唛预算段为空 ⇒ G10 无从判定"


def test_g8_g10_option_label_short_paper_and_budget_are_consistent():
    """真值侧（issue #8107）：专属唛的短纸型 = 矩阵 `label-50x100`、命名 @page 与它同源、预算可复算。"""
    problems = _problems(_read(LABEL_SRC))
    assert problems == [], (
        f"`{LABEL_SRC}` 专属唛几何/预算违规：\n  " + "\n  ".join(problems)
    )


# ── G7：注入式红证 + 内容指纹自证 ─────────────────────────────────────────────

def test_g7_injected_geometry_drift_is_red():
    """G7：只改一处几何 / 两处都退回旧值 / 注释退回旧值 / 改行高 ⇒ 判据必红；并用**内容指纹**自证注入生效。"""
    src = _read(LABEL_SRC)
    assert _problems(src) == [], "原文件本应干净（G1~G6 已单独判）—— 这里先红说明判据或预期已变"

    # 注入 A：把介质换成**另一张纸**（三联纸 241×140）而容器不动 ⇒ G1 必红
    css = _css_block(src)
    page_w, page_h, _label_w, _label_h = _geometry(src, css)
    injected_a = _PAGE_RULE_CALL_RE.sub(lambda m: m.group(0).replace(m.group(1), "continuous-241x140"), src, count=1)
    assert "label-50x140" in src, "找不到介质 id 的注入点 ⇒ 本红证会**空跑**"
    assert injected_a != src, "找不到介质 id 的注入点 ⇒ 本红证会**空跑**"
    assert _fingerprint(injected_a) != _fingerprint(src), "注入后内容指纹未变（**禁 mtime/size**）"
    assert _problems(injected_a), "只改 `@page` 宽度后判据**没判红** ⇒ G1 是空判据"

    # 注入 B：**两处几何一起**退回 30mm×60mm（注释仍带新旧两个值）⇒ G4 必红
    #          —— 这一路 G2 的子串判定挡不住（实测假绿），是本守卫第一版被自己的红证打回的那一处
    # ⚠️ 注入点一律**从现取几何拼**（不写死 60mm/70mm）：纸型一改版，写死的注入点会静默失配 ⇒ 红证空跑
    injected_b = src.replace(
        f"width: {page_w:g}mm; height: {page_h:g}mm",
        "width: 30mm; height: 60mm",
        1,
    )
    assert injected_b != src, "找不到容器宽注入点 ⇒ 本红证会**空跑**"
    assert _problems(injected_b), "容器宽退回 30mm 后判据**没判红** ⇒ G4 是空判据（G2 会假绿）"

    # 注入 C：把文件头注释里的几何退回 30mm × 60mm ⇒ G2 必红
    # ⚠️ 注释里当前几何会出现**多次**（字段面 / 几何段落都写了）⇒ 必须**全换**，
    #    只换第一处会让第二处继续满足 G2（本红证第一版就因此空跑，实测打回）
    injected_c = src.replace(f"{page_w:g}mm × {page_h:g}mm", "30mm × 60mm")
    assert injected_c != src, "找不到注入点「Wmm × Hmm」⇒ 本红证会**空跑**"
    assert _problems(injected_c), "注释退回旧几何后判据**没判红** ⇒ G2 是空判据"

    # 注入 D：把 `line-height` 从 1.2 改成 2 ⇒ G6 必红（每行行高恒等式不再成立）
    injected_d = re.sub(r"(line-height:\s*)1\.2\b", r"\g<1>2", css, count=1)
    assert injected_d != css, "找不到 `line-height: 1.2` 注入点 ⇒ 本红证会**空跑**"
    injected_d_src = src.replace(css, injected_d, 1)
    assert _problems(injected_d_src), "改行高后判据**没判红** ⇒ G6 是空判据"


# ── G11：专属唛短纸型（issue #8107）的注入式红证 ─────────────────────────────

def test_g11_injected_option_label_regressions_are_red():
    """G11：专属唛高改回 140 / 删命名页 / 删专属预算段 / 改预算读数 ⇒ 判据必红（内容指纹自证注入生效）。"""
    src = _read(LABEL_SRC)
    assert _problems(src) == [], "原文件本应干净（G1~G10 已单独判）—— 这里先红说明判据或预期已变"

    css = _css_block(src)
    option = _OPTION_RE.search(css)
    assert option is not None and option.group(2).strip() != "", (
        "找不到 `.task-card-label--option { … }` / 其中的命名页 ⇒ 本红证会**空跑**"
    )
    page_name = option.group(2)
    option_h = float(option.group(1))
    named_media = dict(_NAMED_PAGE_CALL_RE.findall(src))[page_name]
    assert named_media != "", "找不到命名页的介质 id ⇒ 本红证会**空跑**"

    # 注入 A：把专属唛容器高改回常规唛那张（140mm）⇒ G8 必红
    injected_a = src.replace(
        f"height: {option_h:g}mm; page: {page_name}",
        "height: 140mm; page: wash-label-option",
        1,
    )
    assert injected_a != src, "找不到专属唛容器高的注入点 ⇒ 本红证会**空跑**"
    assert _fingerprint(injected_a) != _fingerprint(src), "注入 A 后内容指纹未变（**禁 mtime/size**）"
    assert any("G8" in p for p in _problems(injected_a)), "专属唛高改回 140mm 却没判红 ⇒ G8 是空断言"

    # 注入 B：删掉命名 `@page` ⇒ G9 必红（专属唛会按文档级 @page 分页 = 两种纸高并存失效）
    injected_b = _NAMED_PAGE_CALL_RE.sub("", src)
    assert injected_b != src, "找不到 `printNamedPageRule(...)` 注入点 ⇒ 本红证会**空跑**"
    assert _fingerprint(injected_b) != _fingerprint(src), "注入 B 后内容指纹未变"
    assert any("G9" in p for p in _problems(injected_b)), "删掉命名页却没判红 ⇒ G9 是空断言"

    # 注入 C：删掉专属唛预算段的标记（= 「删掉专属唛预算注释」的形态）⇒ G10 必红
    assert OPTION_BUDGET_MARK in src, "找不到专属唛预算段标记 ⇒ 本红证会**空跑**"
    injected_c = src.replace(OPTION_BUDGET_MARK, "", 1)
    assert injected_c != src, "找不到专属唛预算段标记的注入点 ⇒ 本红证会**空跑**"
    assert _fingerprint(injected_c) != _fingerprint(src), "注入 C 后内容指纹未变"
    assert any("G10" in p for p in _problems(injected_c)), "删掉专属唛预算段却没判红 ⇒ G10 是空断言"

    # 注入 D：把专属唛预算段的「可用 Xmm」改成常规唛那张的可用高 ⇒ G10 恒等式必红
    region = _budget_regions(_header(src))[1]
    got_avail = _declared(region, "可用")
    assert got_avail is not None and got_avail > 0, (
        "专属唛预算段没写「可用 …mm」（或解析出非正数）⇒ 本红证会**空跑**"
    )
    declared = f"可用 {got_avail:g}mm"
    assert declared in region, f"找不到注入点「{declared}」⇒ 本红证会**空跑**"
    injected_d = src.replace(declared, f"可用 {got_avail + 40:g}mm", 1)
    assert _fingerprint(injected_d) != _fingerprint(src), "注入 D 后内容指纹未变"
    assert any("G10" in p for p in _problems(injected_d)), "专属唛预算读数被改却没判红 ⇒ G10 恒等式是空断言"
