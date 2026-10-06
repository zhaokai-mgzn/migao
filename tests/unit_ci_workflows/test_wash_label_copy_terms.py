# case_ids: PP-011
"""用户可见文案的**术语口径**守卫（issue #6451）。

用户 2026-10-06 逐字：「我们页面展示的洗水码文案是不对的吧，要改成水洗唛？」
⇒ **代码面**统一为「水洗唛」（`唛` = 那张缝在布上的标签，行业口径）。

## 为什么要有这条守卫（而不是改完 8 处就算完）

术语是**会爬回来**的东西：新写一个弹窗、新加一句工人端提示，顺手就敲成旧词，
而**没有任何东西会红**（页面照样跑、测试照样绿）。⇒ 把口径钉在**代码面**上。

## 判据（逐条可红）

1. **代码面**（字符串字面量 / 模板串 / JSX 文本）出现禁用词 ⇒ 判红（归因到 `文件:行` + 原句）；
2. **注释面允许保留** —— 这是**正面对照**，同时也是把用户的**范围裁定**钉住
   （用户 2026-10-06 确认：只改用户可见面 ⇒ 历史裁定原话「洗水码宽是50」与内部命名
   `wash-code` / 报工短链**一律不动**）。没有这一条，下一个人「顺手全改」抹掉历史记录时**不会有人拦**；
3. **注入式红证**：合成的源里把词放进字符串/JSX ⇒ 必须判红（判据不是空断言）；
4. **正向锚**：用户可见面**都**已改口（防止「删掉旧词」被当成「改完了」）。

## 为什么去注释要写成**栈式**状态机（而不是一行正则、也不是单变量状态机）

- 一行正则会栽在 `'https://app.migaozn.com/s/'` 的 `//` 上 ⇒ 把 URL 之后的内容当注释删掉
  ⇒ **真违规被删没**（假绿，最危险的一种）。
- **单变量**状态机会栽在**嵌套模板串**上：`` `<style>${a ? `x` : `y`}</style>` `` ——
  内层反引号把外层提前闭合，此后整段状态错位（实测：`worker-h5/src/render.mjs` 里一个嵌套模板
  把后面的 JSDoc 整段吞成"字符串" ⇒ 注释里的旧词被当成违规 = **假红**；错位方向反过来就是漏判 = 假绿）。
- 模板串里的 **CSS 注释**（`<style>{`…/* … */…`}`）按注释算（它是注释，不是文案）。

实例判据见 `test_url_with_double_slash_is_not_eaten_as_a_comment` /
`test_nested_template_does_not_desync` / `test_css_comment_inside_template_counts_as_comment`。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 用户可见面统一后的术语（`唛` = 标签本体；指「码」时写「水洗唛上的码 / 报工码」）
BANNED_IN_CODE_FACE = ("洗水码",)
REQUIRED_TERM = "水洗唛"

# 扫面：前端三个包的**生产源码**（不含测试：测试里的旧词多是注释或在描述历史）
SCAN_ROOTS = (
    "frontend/admin-web/src",
    "frontend/bmini-app/src",
    "frontend/worker-h5/src",
)
SCAN_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs")

# 用户可见面所在的文件（正向锚：每个文件都必须已改口）
USER_FACING_FILES = (
    "frontend/admin-web/src/lib/print-doc.ts",                                    # 打印预览层标题
    "frontend/admin-web/src/app/(dashboard)/processing-orders/[id]/production/page.tsx",  # 两处弹窗
    "frontend/bmini-app/src/utils/inbound/codeSpace.ts",                          # 工人端三处
)


def _regex_starts_here(out: list[str]) -> bool:
    """`/` 是**正则字面量**的开头还是除号？（标准启发式：看前一个有意义字符/关键字）

    实测踩坑：`String(v).replace(/[&<>"']/g, …)` —— 正则**字符类里就有引号**，
    不认它就会把后面的整段当成字符串 ⇒ 状态错位（注释被吞成代码面 = 假红，方向反过来 = 假绿）。
    """
    tail = "".join(out[-200:]).rstrip()
    if not tail:
        return True
    if tail[-1] in "(,=:[!&|?{};+-*%~^<>":
        return True
    word = re.search(r"[A-Za-z_$][\w$]*$", tail)
    return bool(word) and word.group(0) in (
        "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
        "do", "else", "case", "yield", "await",
    )


def code_face(source: str) -> str:
    """**只保留代码面**：剥掉注释，字符串 / 模板串 / 正则字面量 / JSX 文本原样留下；**行数与原文逐行对齐**。

    状态**用栈**，并且要认出**正则字面量**：模板串可以嵌 `${ … }`（里面又能嵌字符串与再一层模板串），
    正则字符类里可以出现引号 —— 这两处都会让"单变量状态机"错位（理由与实测见文件头）。
    注释字符一律换成空格 ⇒ 下标即原行号 − 1。
    """
    out: list[str] = []
    stack = ["code"]  # code | tpl | expr | sq | dq | regex | line | block
    regex_in_class = False
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        state = stack[-1]

        if state in ("code", "expr"):
            if ch == "/" and nxt == "/":
                stack.append("line")
                out.append("  ")
                i += 2
            elif ch == "/" and nxt == "*":
                stack.append("block")
                out.append("  ")
                i += 2
            elif ch == "/" and _regex_starts_here(out):
                stack.append("regex")
                regex_in_class = False
                out.append(ch)
                i += 1
            elif ch in ("'", '"'):
                stack.append("sq" if ch == "'" else "dq")
                out.append(ch)
                i += 1
            elif ch == "`":
                stack.append("tpl")
                out.append(ch)
                i += 1
            elif state == "expr" and ch == "}":
                stack.pop()
                out.append(ch)
                i += 1
            else:
                out.append(ch)
                i += 1
            continue

        if state == "regex":
            if ch == "\\":
                out.append(source[i : i + 2])
                i += 2
                continue
            if ch == "[":
                regex_in_class = True
            elif ch == "]":
                regex_in_class = False
            elif (ch == "/" and not regex_in_class) or ch == "\n":
                # 未闭合的正则（语法上不该出现）⇒ 兜底退出，免得把整份文件拖进错位
                stack.pop()
            out.append(ch)
            i += 1
            continue

        if state == "tpl":
            if ch == "\\":
                out.append(source[i : i + 2])
                i += 2
            elif ch == "`":
                stack.pop()
                out.append(ch)
                i += 1
            elif ch == "$" and nxt == "{":
                stack.append("expr")
                out.append("${")
                i += 2
            elif ch == "/" and nxt == "*":  # 模板串里的 CSS 注释（`<style>{`…`}`）也是注释
                stack.append("block")
                out.append("  ")
                i += 2
            else:
                out.append(ch)
                i += 1
            continue

        if state in ("sq", "dq"):
            if ch == "\\":
                out.append(source[i : i + 2])
                i += 2
                continue
            if (state == "sq" and ch == "'") or (state == "dq" and ch == '"'):
                stack.pop()
            out.append(ch)
            i += 1
            continue

        if state == "line":
            out.append(ch if ch == "\n" else " ")
            if ch == "\n":
                stack.pop()
            i += 1
            continue

        # block
        if ch == "*" and nxt == "/":
            stack.pop()
            out.append("  ")
            i += 2
            continue
        out.append(ch if ch == "\n" else " ")
        i += 1
    return "".join(out)


def violations_in(name: str, source: str) -> list[str]:
    """代码面里的禁用词 ⇒ `名字:行: 原句`（原句取**原文**那一行，便于直接照抄去改）。"""
    face_lines = code_face(source).splitlines()
    raw_lines = source.splitlines()
    found: list[str] = []
    for index, line in enumerate(face_lines, start=1):
        for term in BANNED_IN_CODE_FACE:
            if term in line:
                raw = raw_lines[index - 1].strip() if index - 1 < len(raw_lines) else ""
                found.append(f"{name}:{index}: {raw[:100]}")
    return found


def scan_repo() -> tuple[list[str], list[Path]]:
    """扫生产源码；返回（违规清单, 扫到的文件）。"""
    violations: list[str] = []
    scanned: list[Path] = []
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in SCAN_EXTS:
                continue
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            scanned.append(path)
            violations.extend(
                violations_in(path.relative_to(REPO_ROOT).as_posix(), path.read_text(encoding="utf-8"))
            )
    return violations, scanned


# ── 判据 ①：代码面零禁用词 ────────────────────────────────────────────────────


def test_no_banned_term_in_code_face():
    violations, scanned = scan_repo()
    assert scanned, "扫面为空 —— 守卫的射程断了（SCAN_ROOTS 路径写错？）"
    assert violations == [], (
        "代码面出现了旧术语「洗水码」（用户 2026-10-06 裁定改用「水洗唛」）：\n  "
        + "\n  ".join(violations)
    )


# ── 判据 ②：注释面**允许**保留（正面对照 + 把范围裁定钉住）──────────────────────


def test_historical_ruling_quote_survives_in_comments():
    """用户 2026-09-26 的裁定原话必须**逐字**还在注释里（范围裁定 = 只改用户可见面）。"""
    source = (REPO_ROOT / "frontend/admin-web/src/components/production/TaskCardPrint.tsx").read_text(
        encoding="utf-8"
    )
    assert "洗水码宽是50" in source, "历史裁定原话被抹掉了 —— 用户确认的改动范围是「只改用户可见面」"
    # 且它**在注释里**（代码面看不到它）：这正是「注释允许保留」的实例
    assert "洗水码宽是50" not in code_face(source), "这句话跑到了代码面（会被判据 ① 判红）"


def test_comment_mention_is_not_a_violation():
    """注释里写旧词**不算违规** —— 否则判据 ① 会误伤历史记录，逼人把守卫放宽。"""
    sample = "// 与纸面洗水码同源\nconst a = 1\n/* 洗水码宽是50 */\n/**\n * 一天扫几十次洗水码报工\n */\n"
    assert violations_in("sample.ts", sample) == []


# ── 判据 ③：注入式红证（判据不是空断言）──────────────────────────────────────


def test_injection_turns_red_with_attribution():
    """把旧词放进**字符串/JSX 文本** ⇒ 必须判红，且**指到行**（可归因）。"""
    sample = "const x = 1\nconst hint = '与纸面洗水码逐张一致'\n"
    found = violations_in("sample.ts", sample)
    assert len(found) == 1, f"注入没被判红 ⇒ 判据是空断言：{found}"
    assert found[0].startswith("sample.ts:2:"), f"归因行号不对：{found[0]}"

    jsx = "export const C = () => (\n  <p>包括每张洗水码上的部位码。</p>\n)\n"
    assert [v.split(":")[1] for v in violations_in("sample.tsx", jsx)] == ["2"], "JSX 文本没被扫到"


def test_url_with_double_slash_is_not_eaten_as_a_comment():
    """状态机存在的理由之一（否则 URL 之后的真违规会被当注释删掉 = 假绿）。"""
    sample = "const url = 'https://app.migaozn.com/s/7Q2M4K8P'\nconst bad = '洗水码'\n"
    found = violations_in("sample.ts", sample)
    assert [v.split(":")[1] for v in found] == ["2"], f"URL 把后续内容吃掉了：{found}"
    # 反证：URL 本身毫发无损地留在代码面里
    assert "https://app.migaozn.com/s/7Q2M4K8P" in code_face(sample)


def test_nested_template_does_not_desync():
    """状态机存在的理由之二：嵌套模板串（单变量状态机在这里错位 ⇒ 假红/假绿双向）。"""
    sample = "const html = `<style>${ok ? `a` : `b`}</style>`\n/* 洗水码宽是50 */\nconst bad = '洗水码'\n"
    found = violations_in("sample.mjs", sample)
    assert [v.split(":")[1] for v in found] == ["3"], f"嵌套模板串导致状态错位：{found}"


def test_css_comment_inside_template_counts_as_comment():
    """`<style>{`…`}` 里的 CSS 注释是**注释**（`TaskCardPrint.tsx` 实测踩过这一处）。"""
    sample = "const css = `<style>\n/* 洗水码本体：固定 50mm */\n.a{width:50mm}\n</style>`\n"
    assert violations_in("sample.tsx", sample) == []


def test_regex_literal_with_quote_is_not_a_string():
    """状态机存在的理由之三：正则字符类里的引号（`worker-h5/src/render.mjs:206` 实测形态）。"""
    sample = (
        "const esc = (v) =>\n"
        "  String(v ?? '').replace(/[&<>\"']/g, (c) => ({ '&': '&amp;' }))\n"
        "/**\n * 洗水码宽是50\n */\n"
        "const bad = '洗水码'\n"
    )
    found = violations_in("sample.mjs", sample)
    assert [v.split(":")[1] for v in found] == ["6"], f"正则里的引号导致状态错位：{found}"


# ── 判据 ④：正向锚（用户可见面都已改口）────────────────────────────────────


def test_user_facing_surfaces_now_use_the_new_term():
    for rel in USER_FACING_FILES:
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert REQUIRED_TERM in code_face(source), f"{rel} 的用户可见文案还没改成「{REQUIRED_TERM}」"
    # 工人端的「码」语境：写的是「水洗唛上的码 / 报工码」，不是光秃秃的「水洗唛」
    code_space = (REPO_ROOT / "frontend/bmini-app/src/utils/inbound/codeSpace.ts").read_text(encoding="utf-8")
    assert re.search(r"水洗唛(上的码|上的报工码|报工码)", code_space), (
        "工人端文案的「码」语境丢了限定词 —— 用户裁定的改法是把标签与码分开说"
    )
