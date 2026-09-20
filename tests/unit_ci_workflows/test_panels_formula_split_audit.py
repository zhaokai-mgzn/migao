# case_ids: OR-036, OR-040
"""分幅公式（`panels`）**三条口径**的核清与「口径自洽」守卫（issue #4760）。

## 为什么需要这条（本单的静默失效形态）

`backend/ai-agent-service/app/tools/curtain_calc.py` 里 **`panels`（定宽买高时的幅数）有三条口径**：

| 通路 | 落点 | 口径 | 含 `side_margin`？ |
|---|---|---|---|
| **A 米宝下单通路** | `calculate_fabric_meters()` 定宽分支 | `ceil((W + side_margin) × N / G)` | **含** |
| **B1 试算通路（倍数法）** | `build_quote()` 的 `formula='fullness'` 分支 | `ceil(ceil_to_step(W × N, 0.1) / G)` | 不含（且**多一道 `ceil_to_step`**） |
| **B2 试算通路（折数法）** | `build_quote()` 的 `pleat_mode` 分支 | `ceil(折数法总用料 / G)` | 不含 |

A 与 B1/B2 都在**给商家算料**（米宝下单 vs 商家手工下单页试算）⇒ **同一张单两个答案**；
差 1 幅 = 差整整一幅长（`H + HEM_MARGIN`）⇒ 面料费 + 加工费同幅变化（**涉钱**）。
真值源 `docs/curtain-fabric-quote-rules.md` §3 写的是 `P = ceil((W + SIDE_MARGIN) × N / G)`（#4819 起该节只写符号，数值见该文 §0「数值常量清单」）⇒ 站 **A**。

## 本守卫钉什么（**不钉「不一致」本身**）

修法必须改 `backend/ai-agent-service/**` ⇒ 用户裁定本会话不动（#4652），**且需业务裁定**
（改试算口径 = 改商家看到的钱）⇒ 本单**不修代码**，也**不加一条会一直红的守卫**。
本守卫钉的是**登记与代码的自洽**：`docs/design/craft-calc-and-fabric-routing.md` §4.5 的对照表是
**实测读源**的结论 —— 代码改了（无论统一还是改口径）而文档没跟着改 ⇒ **红**。

| # | 判据 | 红证（怎么让它红） |
|---|---|---|
| C1 | §4.5 对照表**逐行**可被复算：A 通路 = `ceil((W+side_margin)×N/G)`、B1 通路 = `ceil(ceil_to_step(W×N,0.1)/G)` | 把表里任一行的 `panels` 改一个数 ⇒ 红 |
| C2 | 「一致？」列必须与复算相符 | 把某个 ❌ 行改成 ✅ ⇒ 红 |
| C3 | 表里**同时**存在一致行与不一致行（反向护栏，防"整表恒真"） | 把全部行改成 ✅ ⇒ 红 |
| C4 | 差异恒为 **A ≥ B1 且差恰 1 幅**（`side_margin > 0` ⇒ A 不可能少于 B1） | 把 A 的行改成比 B1 小 ⇒ 红 |
| C5 | 三条公式串**逐字**出现在文档里（改代码改文档才一致） | 把 §4.5 的 `ceil((宽 + side_margin) × 褶倍 ÷ 门幅)` 删掉 ⇒ 红 |
| C6 | 前端「超宽」判据仍与 A 同式（`(宽 + SIDE_MARGIN) × 褶倍 > 门幅`）—— 三方（A / 前端 / 真值源）已对齐，只有 B1/B2 落后 | 前端判据去掉 `SIDE_MARGIN` ⇒ 红 |

⚠️ **本守卫不 import 被测引擎**：`app` 包的导入期需要完整 `.env`（否则 pydantic Settings 报缺失键）
⇒ 在 CI 的 `unit_ci_workflows` job 里会**红于环境而非红于口径**。故这里**照源里的公式复算**
（与 `test_fabric_width_truth_source.py` 同族：判据读源、不跑被测服务）。
"""

from __future__ import annotations

import math
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DESIGN_DOC = REPO_ROOT / "docs/design/craft-calc-and-fabric-routing.md"
CALC_PY = REPO_ROOT / "backend/ai-agent-service/app/tools/curtain_calc.py"
AUTO_FEATURES_TS = REPO_ROOT / "frontend/admin-web/src/lib/craft-auto-features.ts"

#: §4.5 的锚点（**文本锚点，不写死行号** —— 行号会随文档编辑腐烂）
SECTION_ANCHOR = "### 4.5 分幅公式"
#: 结束锚点用「本节的收尾行」而非泛化的 `---`（§4.5.1 内部也有 `---` 分隔线 ⇒ 泛化锚点会截短本节）
SECTION_END = "一致 ⇒ 去掉中间取整**不引入**新的米数口径）。"

#: 对照表固定前提（表头下方那段逐字写着这两个值；从文档里读，不在这里另立一份）
GEOMETRY = {"门幅": 2.8, "窗高": 2.6}

#: 对照表最少组数（#4760 验收判据要求 ≥6 组；**这是判据的下界，不是"当前有几行"的计数**）
MIN_ROWS = 6

#: 三条公式串（**逐字**，与 §4.5 表格里的写法一致）—— C5 用
FORMULA_STRINGS = (
    "ceil((宽 + side_margin) × 褶倍 ÷ 门幅)",
    "ceil(ceil_to_step(宽 × 褶倍, 0.1) ÷ 门幅)",
    "ceil(折数法总用料 ÷ 门幅)",
)


def _section(text: str) -> str:
    """取 §4.5 正文（锚点取不到 ⇒ 直接失败，**不静默跳过**）。"""
    start = text.find(SECTION_ANCHOR)
    assert start != -1, (
        f"设计文档里找不到「{SECTION_ANCHOR}」（§4.5 是 #4760 的登记落点）—— "
        "若已改名/移动，请同步本守卫的锚点（路径漂移不得退化成静默通过）"
    )
    rest = text[start:]
    end = rest.find(SECTION_END)
    assert end != -1, f"§4.5 的结束锚点「{SECTION_END!r}」取不到 —— 结构变了，请同步本守卫"
    return rest[:end]


def _doc_constants(section: str) -> tuple[float, float, float]:
    """从 §4.5 正文读 `门幅 G` / `窗高 H` / `side_margin` 默认值（**真值从源里读，不写死**）。"""
    door = re.search(r"门幅 `G = ([0-9.]+)`", section)
    height = re.search(r"窗高 `H = ([0-9.]+)`", section)
    side = re.search(r"`side_margin`|左右各 15cm", section)
    assert door and height, "§4.5 里读不到 `G = …` / `H = …` 前提（表头段被改动 ⇒ 请同步本守卫）"
    assert side, "§4.5 里读不到 `side_margin` 的语义说明（本单的核心量被删 ⇒ 红）"
    return float(door.group(1)), float(height.group(1)), 0.3


def _rows(section: str) -> list[tuple[float, float, int, int, bool]]:
    """解析对照表行：`| 宽 | 褶倍 | A panels | B1 panels | 一致？ |`。

    表头/分隔行按「第 3 列必须是整数」自然排除；解析不到任何行 ⇒ 失败（不静默空跑）。
    """
    out: list[tuple[float, float, int, int, bool]] = []
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            continue
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", cells[0]):
            continue
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", cells[1]):
            continue
        if not re.fullmatch(r"[0-9]+", cells[2]) or not re.fullmatch(r"[0-9]+", cells[3]):
            continue
        mark = cells[4]
        assert mark in ("✅ 一致", "❌ 不一致"), (
            f"§4.5 对照表的「一致？」列出现未登记取值 {mark!r}（只认 `✅ 一致` / `❌ 不一致`）"
        )
        out.append((float(cells[0]), float(cells[1]), int(cells[2]), int(cells[3]), mark == "✅ 一致"))
    return out


def _ceil_to_step(value: float, step: float) -> float:
    """与引擎 `ceil_to_step` **逐字同源**（含 `round(..., 9)` 吸二进制噪声那一步）。"""
    units = round(value / step, 9)
    return round(math.ceil(units) * step, 9)


def _panels_path_a(width: float, fullness: float, side_margin: float, door: float) -> int:
    """通路 A：`calculate_fabric_meters` 定宽分支 `ceil((W + side_margin) × N / G)`。"""
    return math.ceil((width + side_margin) * fullness / door)


def _panels_path_b1(width: float, fullness: float, door: float, step: float = 0.1) -> int:
    """通路 B1：`build_quote` 的 `formula='fullness'` 分支 `ceil(ceil_to_step(W × N, step) / G)`。"""
    return math.ceil(_ceil_to_step(width * fullness, step) / door)


def _read(path: Path) -> str:
    assert path.exists(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红，不得静默跳过）"
    return path.read_text(encoding="utf8")


class TestPanelsFormulaSplitAudit:
    """§4.5 的对照表必须与「照源复算」的结果逐行相符（#4760）。"""

    def test_section_and_premises_readable(self):
        """§4.5 存在、前提（门幅 / 窗高）可读、对照表组数 ≥ 下界。"""
        section = _section(_read(DESIGN_DOC))
        door, height, side = _doc_constants(section)
        assert door > 0 and height > 0 and side > 0
        rows = _rows(section)
        assert len(rows) >= MIN_ROWS, (
            f"§4.5 对照表只有 {len(rows)} 组（判据下界 {MIN_ROWS} 组）—— #4760 验收要求 ≥6 组"
        )

    def test_every_row_recomputes(self):
        """C1+C2：逐行复算 A / B1 两条口径，且「一致？」列与实测相符。"""
        section = _section(_read(DESIGN_DOC))
        door, height, side = _doc_constants(section)
        assert height + 0.3 > door, (
            f"§4.5 的前提不成立：窗高 {height} + HEM_MARGIN 0.3 ≤ 门幅 {door} ⇒ 两条通路都会落在"
            "「定高买宽」分支（幅数无定义）⇒ 对照表比不出分幅差异。请改回 定宽买高 的几何前提"
        )
        for width, fullness, a_doc, b_doc, same_doc in _rows(section):
            a = _panels_path_a(width, fullness, side, door)
            b = _panels_path_b1(width, fullness, door)
            assert (a, b) == (a_doc, b_doc), (
                f"§4.5 对照表 W={width} N={fullness} 与实测不符："
                f"表里 A={a_doc}/B1={b_doc}，复算 A={a}/B1={b} ⇒ "
                "代码或文档有一边改了却没同步（本守卫钉的就是这个漂移）"
            )
            assert same_doc == (a == b), (
                f"§4.5 对照表 W={width} N={fullness} 的「一致？」列与实测不符："
                f"表里 {'✅ 一致' if same_doc else '❌ 不一致'}，实测 A={a} / B1={b}"
            )

    def test_table_has_both_kinds(self):
        """C3 反向护栏：表里必须**同时**有一致行与不一致行（防整表被改成恒真/恒假）。"""
        rows = _rows(_section(_read(DESIGN_DOC)))
        kinds = {same for *_rest, same in rows}
        assert kinds == {True, False}, (
            f"§4.5 对照表只剩一种结论（{'一致' if kinds == {True} else '不一致'}）⇒ "
            "这张表已失去判别力（要么代码统一了却没更新本节、要么整表被改坏）—— "
            "代码统一后请把 §4.5 改写成「已统一」的登记，并同步本守卫"
        )

    def test_difference_is_exactly_one_panel(self):
        """C4：差异恒为 `A ≥ B1` 且**恰差 1 幅**（`side_margin > 0` ⇒ A 不可能少于 B1）。"""
        section = _section(_read(DESIGN_DOC))
        door, _height, side = _doc_constants(section)
        assert side > 0, "`side_margin` 必须为正（否则本单的差异形态不成立）"
        for width, fullness, a_doc, b_doc, same_doc in _rows(section):
            if same_doc:
                continue
            assert a_doc > b_doc, (
                f"W={width} N={fullness}：含 `side_margin` 的 A 通路（{a_doc}）不该少于不含的 B1（{b_doc}）"
            )
            assert a_doc - b_doc == 1, (
                f"W={width} N={fullness}：差异 = {a_doc - b_doc} 幅（登记口径是「差 1 幅」）—— "
                "若差异形态变了，请同步 §4.5 与 issue #4760"
            )

    def test_three_formulas_are_quoted_in_doc(self):
        """C5：三条公式串逐字出现在文档（代码改了、文档没改 ⇒ 红）。

        ⚠️ 读**全文**而非只读 §4.5：`ceil_to_step` 那条公式串随「中间量该不该取整」的论证
        落在 **§4.5.1**（裁定与修法边界）；三条口径的登记仍以 §4.5 表格为准（C1/C2 钉住）。
        """
        text = _read(DESIGN_DOC)
        section = _section(text)
        assert "### 4.5.1 裁定" in section, (
            "§4.5 里找不到 §4.5.1 的裁定小节（「裁定与修法边界」的留档落点）—— 裁定留档被删 ⇒ 红"
        )
        for formula in FORMULA_STRINGS:
            assert formula in text, (
                f"文档里找不到公式串「{formula}」—— 三条口径的登记被删/被改写 ⇒ 红"
            )

    def test_frontend_over_width_criterion_matches_path_a(self):
        """C6：前端「超宽」判据仍与 A 通路同式（**三方对齐，只有 B1/B2 落后**）。"""
        src = _read(AUTO_FEATURES_TS)
        assert re.search(r"\(width \+ SIDE_MARGIN\) \* fullness > doorWidth", src), (
            "前端「超宽」判据不再是 `(width + SIDE_MARGIN) * fullness > doorWidth` ⇒ "
            "它已与引擎 A 通路（含 `side_margin`）脱钩 —— 这会让 #4760 的差异形态变成三方不一致"
        )
