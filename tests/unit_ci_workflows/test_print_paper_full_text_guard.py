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

🔴 **洗水唛已纳入射程（issue #7833）**：用户 2026-10-26 逐字「打印后的结果出现了文字缩写，
有没有办法在打印预览就发现文字会被缩略然后自动去换行打印？」—— 当初把它留在射程外的那句
「固定几何标签的排版口径归位图渲染器」**不再成立**：两条通道（CSS 预览 / 位图直连）都要印全文。
⇒ C4 同尺判定洗水唛的三份源码：CSS 渲染器不许藏字、纸面内容模块**不许带行数预算**（`maxLines`）、
位图渲染器不许按行的预算裁（`row.maxLines`）。
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
    # issue #7902：发货单整体退场 ⇒ 在册纸面单据 4 → 3（报价 / 加工 / 销售）。
    assert len(docs) >= 3, f"纸面单据只剩 {[d.name for d in docs]} ⇒ 少于既有三份（报价 / 加工 / 销售），同步本守卫"
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


# ── C4：类级 —— 洗水唛（固定几何标签）同样印全文（issue #7833）─────────────────


#: 洗水唛的三份源码：CSS 渲染器 / 纸面内容真值 / 位图渲染器
WASH_LABEL_CSS = "frontend/admin-web/src/components/production/TaskCardPrint.tsx"
WASH_LABEL_CONTENT = "frontend/admin-web/src/lib/wash-label-content.ts"
WASH_LABEL_BITMAP = "frontend/admin-web/src/lib/label-print/wash-label.ts"


def _read_managed(rel: str) -> str:
    path = REPO_ROOT / rel
    assert path.is_file(), f"受管文件不存在：{rel} —— 路径漂移不得退化成静默跳过"
    return path.read_text(encoding="utf-8")


def wash_label_full_text_problems(sources: dict[str, str]) -> list[str]:
    """C4 的**纯函数**判定（真值侧与注入式红证共用同一把尺子）。

    @param sources 三份源码（键 = 仓库相对路径）
    @return 违规说明；空列表 = 合规
    """
    problems: list[str] = []
    for rel in (WASH_LABEL_CSS, WASH_LABEL_CONTENT, WASH_LABEL_BITMAP):
        hits = truncation_hits(sources[rel])
        if hits:
            problems.append(
                f"{rel} 又把纸面文字裁掉了：{hits} —— 用户 2026-10-26 逐字「文字缩写…自动去换行打印」"
                "（洗水唛 = 车间/客户手上的标签，同样不得靠省略号掩盖）"
            )

    # 行里**没有**行数预算：`maxLines` 一旦回到内容真值模块，位图渲染器就又开始省略号收尾
    if "maxLines" in java_code(sources[WASH_LABEL_CONTENT]):
        problems.append(
            f"{WASH_LABEL_CONTENT} 又出现 `maxLines` —— 行数预算 = 省略号（issue #7833 已作废该口径）"
        )
    if "row.maxLines" in java_code(sources[WASH_LABEL_BITMAP]):
        problems.append(f"{WASH_LABEL_BITMAP} 又按行的预算裁 —— 正文必须折行印全文")

    # 正相反向锚：CSS 渲染器确实声明了折行（否则「去裁切」只是把字挤出纸外）
    css = java_code(sources[WASH_LABEL_CSS])
    if not ("break-words" in css or "break-all" in css):
        problems.append(
            f"{WASH_LABEL_CSS} 里找不到折行类（`break-words` / `break-all`）—— 长值要么被裁、要么溢出纸面"
        )
    return problems


def test_c4_wash_label_prints_full_text():
    """C4：洗水唛两条通道都**不许藏字**，且内容模块不带行数预算（有预算就有省略号）。"""
    sources = {rel: _read_managed(rel) for rel in (WASH_LABEL_CSS, WASH_LABEL_CONTENT, WASH_LABEL_BITMAP)}
    problems = wash_label_full_text_problems(sources)
    assert problems == [], "\n  ".join(problems)


def test_c4_injection_turns_red():
    """C4 的判别力自证：三种坏形态注入一份**内存副本** ⇒ 各自必红；恢复 ⇒ 不红（不是空断言）。"""
    sources = {rel: _read_managed(rel) for rel in (WASH_LABEL_CSS, WASH_LABEL_CONTENT, WASH_LABEL_BITMAP)}
    assert wash_label_full_text_problems(sources) == [], "基线必须绿（否则分不清是注入还是存量）"

    # ① 渲染器里塞 Tailwind truncate
    broken = dict(sources)
    broken[WASH_LABEL_CSS] += "\nconst leak = 'truncate'\n"
    assert any("裁掉" in p for p in wash_label_full_text_problems(broken)), "truncate 没判红 ⇒ 空断言"

    # ② 内容模块把行数预算加回来
    broken = dict(sources)
    broken[WASH_LABEL_CONTENT] += "\nconst leaked = { maxLines: 2 }\n"
    assert any("maxLines" in p for p in wash_label_full_text_problems(broken)), "maxLines 没判红 ⇒ 空断言"

    # ③ 位图渲染器按行的预算裁
    broken = dict(sources)
    broken[WASH_LABEL_BITMAP] += "\nconst leaked = row.maxLines\n"
    assert any("按行的预算裁" in p for p in wash_label_full_text_problems(broken)), "row.maxLines 没判红 ⇒ 空断言"

    # ④ 负控：写进注释不算（沿革要讲得清）
    clean = dict(sources)
    clean[WASH_LABEL_CONTENT] += "\n// 沿革：本模块曾有 maxLines 行数预算，issue #7833 起退场（truncate / line-clamp）\n"
    assert wash_label_full_text_problems(clean) == [], "只在注释里提及旧形态就判红 —— 假红"


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
