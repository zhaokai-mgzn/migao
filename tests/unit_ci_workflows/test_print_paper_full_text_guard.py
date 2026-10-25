# case_ids: UI-062
"""纸面「打印全」守卫（issue #7715）—— 实例判据 + 类级元守卫。

## 病根（一类缺陷，不是一个缺陷）

用户 2026-10-25 逐字「这里打印预览的文字要打印全，不能缩略」：销售单打印预览里，
明细「颜色」列显示成 `2659-08 月落雾…` —— 被 `text-overflow: ellipsis` 吃了后半截。
纸面是客户**收货凭证**：被省略号吃掉的那半截恰恰是「这是哪个花色」。

那个形态**不是回归**，是 issue #5651 当年立的「长名截断可见」口径（省略号 = 证明不是静默裁字符串）。
本轮把它推翻：**折行印全文**（`break-words`），超高的内容由纸面自检如实报出，不靠裁切掩盖。

## 本文件守两件事（`migao-dev-flow` §23：实例判据 + 类级元守卫）

- **C1 实例**：销售单纸面（`SalesDoc.tsx`）去注释后不得出现任何「藏字」形态，且长值单元格声明折行；
- **C2 类级**：`components/orders/*Doc.tsx` 的**每一份**纸面单据都同尺判定 ——
  新增单据**自动**纳入射程（glob 定位，不用登记）；清单塌成 0 个 ⇒ 判红（空集不得读成通过）。
- **C3 判别力自证**：把三种裁切形态注入临时副本 ⇒ 必红；把它们写进**注释** ⇒ 不红（负控 ①：
  文件头本来就要解释这个坑，按原文判会假红）；写进 **CSS 模板字面量** ⇒ 必红（负控 ②：
  纸面样式就住在模板字面量里，看不见它这条判据就等于没看）。

## 边界（照实登记）

只判「藏字」三形态（省略号 / Tailwind `truncate` / `line-clamp-*`）。
`whitespace-nowrap` **不在此列**：它只影响折行、不藏字，而标签列（客户 / 门幅 …）印的是固定短词。
洗水唛 / 任务卡（`components/production/TaskCardPrint.tsx`）是**固定几何标签**，排版口径归位图渲染器，
不在本守卫射程；它改成纸面凭证那天必须纳入。
"""
from __future__ import annotations

import re
from pathlib import Path

from unit_ci_workflows._source_parsing import java_code  # 判据面唯一一份「引号感知」剥注释实现

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 受管纸面：客户 / 工人拿在手上的单据组件（glob ⇒ 新增单据自动进射程）
PAPER_DOC_GLOB = "frontend/admin-web/src/components/orders/*Doc.tsx"

#: 实例判据的落点（用户截图那张单据）
SALES_DOC = "frontend/admin-web/src/components/orders/SalesDoc.tsx"

#: 纸面**不许**的裁切形态（会静默 / 可见地藏掉文字）
TRUNCATION_FORMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("省略号", re.compile(r"text-overflow\s*:\s*ellipsis")),
    ("Tailwind truncate", re.compile(r"(?<![\w-])truncate(?![\w-])")),
    ("多行裁切", re.compile(r"line-clamp-\d")),
)


def truncation_hits(text: str) -> list[str]:
    """去注释后的源码里命中的裁切形态名（纯函数：判据与红证共用同一把尺子）。

    注释**不算**（`java_code` 引号感知剥注释）：文件头必须能解释「旧形态长什么样」，
    否则解释性注释会被判成违规 = 假红。
    """
    code = java_code(text)
    return [name for name, pattern in TRUNCATION_FORMS if pattern.search(code)]


def _paper_docs() -> list[Path]:
    docs = sorted(REPO_ROOT.glob(PAPER_DOC_GLOB))
    assert docs, (
        f"纸面单据清单塌成 0 个（glob = {PAPER_DOC_GLOB}）⇒ 判据在空集上跑 = 空跑通过；"
        "主目录 / 文件命名变了吗？"
    )
    assert len(docs) >= 4, f"纸面单据只剩 {[d.name for d in docs]} ⇒ 少于既有四份（发货 / 报价 / 加工 / 销售），同步本守卫"
    return docs


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _read(rel: str) -> str:
    path = REPO_ROOT / rel
    assert path.is_file(), f"{rel} 不存在 ⇒ 路径漂移不得退化成静默跳过（那会让本守卫空跑通过）"
    return path.read_text(encoding="utf-8")


# ── C1：实例 —— 销售单纸面不藏字 ────────────────────────────────────────────────


def test_c1_sales_doc_prints_full_text():
    """C1：销售单去注释后无裁切形态，且长值单元格声明折行（`break-words`）。"""
    src = _read(SALES_DOC)
    hits = truncation_hits(src)
    assert hits == [], (
        f"{SALES_DOC} 又把纸面文字裁掉了：命中 {hits} —— "
        "用户 2026-10-25 裁定「这里打印预览的文字要打印全，不能缩略」：长值（颜色 / 货号 / 客户 / 地址）"
        "一律折行印全文（`break-words`），超高由纸面自检如实报出，不靠裁切掩盖。"
    )
    assert "break-words" in java_code(src), (
        f"{SALES_DOC} 里找不到折行声明（`break-words`）⇒ 长值要么被裁、要么溢出格子；"
        "纸面原子（DocTd / DocCell）必须无条件带它。"
    )


# ── C2：类级 —— 每一份纸面单据同尺判定 ──────────────────────────────────────────


def test_c2_every_paper_doc_prints_full_text():
    """C2：`components/orders/*Doc.tsx` 每份都不得藏字（新增单据自动进射程 = 未登记即红）。"""
    offenders: dict[str, list[str]] = {}
    for path in _paper_docs():
        hits = truncation_hits(path.read_text(encoding="utf-8"))
        if hits:
            offenders[_rel(path)] = hits
    assert not offenders, (
        f"这些纸面单据把文字裁掉了：{offenders} —— 同一类缺陷换一份单据（发货 / 报价 / 加工 …）"
        "也必须红，不许只修销售单这一处。"
    )


# ── C3：判别力自证（注入必红 + 两条负控）────────────────────────────────────────


def test_c3_guard_has_teeth():
    """C3：三种形态注入 ⇒ 必红；写进注释 ⇒ 不红；写进 CSS 模板字面量 ⇒ 必红。"""
    base = _read(SALES_DOC)
    assert truncation_hits(base) == [], f"{SALES_DOC} 本应干净（C1 已单独判）——先红说明判据或预期已变"

    injections = (
        (".sales-cut { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }", "省略号"),
        ('<td className="break-words truncate">x</td>', "Tailwind truncate"),
        ('<td className="line-clamp-2">x</td>', "多行裁切"),
    )
    for snippet, expected in injections:
        assert expected in truncation_hits(base + "\n" + snippet), (
            f"注入「{snippet}」后本守卫没有命中「{expected}」⇒ 这条判据不看那件事（空断言）"
        )

    # 负控 ①：注释里解释旧形态**不算违规**（文件头本来就要写这个坑）
    commented = base + "\n// 旧形态：text-overflow: ellipsis / className=\"truncate\" / line-clamp-2\n"
    assert truncation_hits(commented) == [], "解释性注释被当成违规 = 假红 ⇒ 会逼人删掉解释"

    # 负控 ②：纸面样式住在 `<style>{`…`}</style>` 的模板字面量里 —— 剥注释不得把它一起吞掉
    template_form = "\nconst css = `\n  .sales-cut { overflow: hidden; text-overflow: ellipsis; }\n`\n"
    assert "省略号" in truncation_hits(base + template_form), (
        "模板字面量里的 CSS 没被扫到 ⇒ 本守卫看不见问题真正住的地方（等于空跑）"
    )
