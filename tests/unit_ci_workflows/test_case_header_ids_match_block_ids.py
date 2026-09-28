# case_ids: MC-040
"""**围栏注释头的用例号必须等于它下面那一块的 `- id:`**（用例语料的号一致性守卫）。

## 病灶（实测，不是设想）

本仓的用例语料里，**一部分**用例块上方有一条**围栏注释头**（形态固定）：

```yaml
  # ==========================================================================
  # MC-037（Refs #5699 的 P4；设计真值源 …）。
  # ==========================================================================

  - id: MC-037
```

它是**给人和 agent 看的号索引**：取号 / 复核 / 派单时，人（与 agent）读的往往是这一行，
而**不是**下面那个 `- id:`。⇒ 两者不一致时，**读数与它声称的对象不是同一个**：实测后果 =
另一个在飞包读到 `# MC-039` 这一行，回报里写成「`fix/5699` 分支加了 MC-039、与 main 上
#5731 的 MC-039 撞号」，并据此误判「在飞已占 MC-040/041」（issue #5699 的 P5/P6/I4 包在
rebase 让号时只改了 `- id:`，漏改注释头 —— 就是本判据要拦的形态）。

## 判据（两条，都在**围栏形态**上判，不碰散文）

1. **头 == 块**：每一条围栏头的号必须等于它下方**第一个** `- id:` 的号（不等 ⇒ 红，两个号都点名）。
2. **头号唯一**：同一个号不得出现在**两条**围栏头里（重复 ⇒ 红 —— 那正是「读号的人被引到错块」）。

## 为什么只认「围栏形态」（而是不认「任何以 `# <ID>` 开头的注释」）—— 本判据的判别力边界

实测普查：全语料 553 个用例块里，**以 `# <ID>` 开头但不是块头**的注释行有 **14 处**，
它们全是**散文里的引用**（例：`.github/cases/aftersales.yml` 的
`# OR-008 / OR-009 / OR-015 / CR-003 等**并行**用例都在同一个手机号…`、
`.github/cases/chat.yml` 的 `# OR-014 下单 / CU-003 客户标签 / AS-004 售后改状态）…`）。
⇒ 若判据写成「任何 `# <ID>` 行都必须是块头」，这 14 处会**全部假红**（判据被自己的语料喂红）。
故本判据只认**「上一行是 `# ====…` 围栏」**这一形态：实测命中 **35 处**（分布在
`processing-order.yml` 20 / `misc.yml` 11 / `processing.yml` 3 / `ui.yml` 1），
其中 **32 处相符、3 处不等**（就是本单修掉的那三处）⇒ 形态稳定、口径可判。

## 红证（全部内存构造）

| 断言 | 变异 | 期望 |
|---|---|---|
| 头 == 块 | 合成语料里把围栏头写成 `MC-999` 而块是 `MC-998` | 红（两个号都点名） |
| 头号唯一 | 同一条围栏头出现两次（指向两个不同块） | 红 |
| **散文不是头**（判别力边界） | 合成语料里放一条 `# MC-999（…）` **但上一行不是围栏** | **不红** |
| 只改散文 ⇒ 不红（对照） | 只改块内的普通注释散文 | **不红** |
| 空跑即红（fail-closed） | 合成一份**没有任何围栏头**的语料 | 红（「判据在空语料上是空断言」不许静默绿） |

## 覆盖面（照实登记）

- 只覆盖 `.github/cases/*.yml`（**不含** `registry.yml`：它不是用例块文件）；
- 只覆盖**围栏形态**的注释头（散文引用不在射程 —— 见上「判别力边界」）；
- **不判**「围栏头里的散文写对了没有」（那是内容正确性，机器判不了 —— 本判据只判**号**）。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"

#: 围栏行（`# =====…`）—— 形态的唯一入口：只有**紧跟在围栏行之后**的 `# <ID>（` 才算注释头。
FENCE = re.compile(r"^\s*#\s*=+\s*$")
#: 注释头：`# MC-037（…` / `# PG-013 (…`（号 + 全角或半角左括号 ⇒ 排除 `# MC-037 与 …` 这类散文）。
HEADER = re.compile(r"^\s*#\s*([A-Z]{2,4}-\d{3})\s*[（(]")
#: 用例块起始行。
BLOCK_ID = re.compile(r"^\s*-\s*id:\s*([A-Z]{2,4}-\d{3})\s*$")

#: 注释头与它下方块之间的**搜索窗口**（行）：窗口内没有 `- id:` ⇒ 视为「头没有自己的块」（红）。
BIND_WINDOW = 40


def case_files(root: Path | None = None) -> list[Path]:
    """语料文件（`.github/cases/*.yml`，**排除** `registry.yml`）。空集 ⇒ fail-closed。"""
    directory = root or CASES_DIR
    files = [p for p in sorted(directory.glob("*.yml")) if p.name != "registry.yml"]
    assert files, f"用例语料目录里没有 `*.yml`：{directory}（fail-closed，不得静默跳过）"
    return files


def header_bindings(text: str) -> list[tuple[int, str, int, str]]:
    """`[(头行号, 头里的号, 块行号, 块的号)]` —— 只认围栏形态（见模块 docstring 的「判别力边界」）。"""
    lines = text.split("\n")
    out: list[tuple[int, str, int, str]] = []
    for i, line in enumerate(lines):
        if not FENCE.match(line) or i + 1 >= len(lines):
            continue
        match = HEADER.match(lines[i + 1])
        if not match:
            continue
        for j in range(i + 2, min(i + 2 + BIND_WINDOW, len(lines))):
            block = BLOCK_ID.match(lines[j])
            if block:
                out.append((i + 2, match.group(1), j + 1, block.group(1)))
                break
        else:
            out.append((i + 2, match.group(1), -1, ""))
    return out


def header_problems(corpus: dict[str, str]) -> list[str]:
    """两条判据的合流（纯函数：喂 `{相对路径: 文本}`，返回问题清单 ⇒ 注入式红证就是喂改过的输入）。"""
    out: list[str] = []
    seen: dict[str, list[str]] = {}
    total = 0
    for rel, text in sorted(corpus.items()):
        for line_no, header_id, block_line, block_id in header_bindings(text):
            total += 1
            seen.setdefault(header_id, []).append(f"{rel}:{line_no}")
            if not block_id:
                out.append(
                    f"`{rel}:{line_no}` 有围栏注释头 `# {header_id}（…` 但**下方 {BIND_WINDOW} 行内没有** "
                    "`- id:` ⇒ 头没有自己的块（挂错位置 / 块被删而头留下）"
                )
                continue
            if header_id != block_id:
                out.append(
                    f"`{rel}:{line_no}` 的围栏注释头写的是 `{header_id}`，而它下面那一块的 `- id:` 是 "
                    f"`{block_id}`（第 {block_line} 行）⇒ **读号的人会被引到错的块**（本仓实测事故形态："
                    "另一个包据此误报撞号）。出口：把头改成块号（或把块号改成头号，二者必须一致）"
                )
    for header_id, where in sorted(seen.items()):
        if len(where) > 1:
            out.append(
                f"围栏注释头里的号 `{header_id}` 出现了 {len(where)} 次（{where}）⇒ 同一个号不许出现在"
                "两条注释头里（读号的人分不清它指哪一块）"
            )
    if total == 0:
        out.append(
            "语料里**一条围栏注释头都没有** ⇒ 本判据在空语料上是空断言（fail-closed：形态消失即红，"
            "而不是静默绿）"
        )
    return out


def load_corpus(root: Path | None = None) -> dict[str, str]:
    base = root or REPO_ROOT
    return {p.relative_to(base).as_posix(): p.read_text(encoding="utf-8") for p in case_files(root)}


# ══════════════════════════════════════════════════════════════════════════════
# 断言（正例 + 红证 + 对照）
# ══════════════════════════════════════════════════════════════════════════════

_FENCE = "  # ==========================================================================\n"


def _corpus(header_id: str, block_id: str, *, extra: str = "") -> dict[str, str]:
    return {
        ".github/cases/fixture.yml": (
            "schema: \"case-contract/1.0\"\n"
            "cases:\n"
            + _FENCE
            + f"  # {header_id}（夹具：合成语料）\n"
            + _FENCE
            + "\n"
            + f"  - id: {block_id}\n"
            + '    title: "夹具"\n'
            + extra
        )
    }


def test_fenced_header_ids_match_block_ids_on_the_current_corpus():
    corpus = load_corpus()
    bindings = sum(len(header_bindings(text)) for text in corpus.values())
    assert bindings >= 30, (
        f"现取只认到 {bindings} 条围栏注释头（远少于实测的 35 处）⇒ 形态变了，本判据会静默缩小射程"
    )
    problems = header_problems(corpus)
    assert problems == [], "围栏注释头与块号不一致：\n" + "\n".join(f"  - {p}" for p in problems)


def test_mismatched_fenced_header_is_red():
    """红证：围栏头写 `MC-999` 而块是 `MC-998` ⇒ 必须红，且**两个号都点名**（锚唯一）。"""
    assert header_problems(_corpus("MC-999", "MC-999")) == [], "对照：头 == 块 ⇒ 不红"
    problems = header_problems(_corpus("MC-999", "MC-998"))
    assert any("MC-999" in p and "MC-998" in p and "引到错的块" in p for p in problems), (
        f"头与块不一致没被判红：{problems}"
    )


def test_duplicate_fenced_header_id_is_red():
    """红证：同一个号出现在两条围栏头里 ⇒ 必须红。"""
    text = (
        _FENCE + "  # MC-777（第一处）\n" + _FENCE + "\n  - id: MC-777\n"
        + _FENCE + "  # MC-777（第二处）\n" + _FENCE + "\n  - id: MC-778\n"
    )
    problems = header_problems({".github/cases/fixture.yml": text})
    assert any("出现了 2 次" in p and "MC-777" in p for p in problems), f"重复头号没被判红：{problems}"


def test_prose_mention_of_a_case_id_is_not_a_header():
    """**判别力边界**：`# <ID>（…` 上一行不是围栏 ⇒ 那只是散文引用 ⇒ **不红**。

    实测依据：全语料有 14 处这样的散文引用（`aftersales.yml` / `chat.yml` / `hr.yml` / `order.yml` /
    `processing.yml` / `product.yml` / `bmini.yml` / `defense.yml` / `processing-order.yml`），
    它们**不是**块头；把它们读成块头会让判据被自己的语料喂红（同 §2.2「引用即实例」的形态）。
    """
    text = (
        "cases:\n"
        "  # MC-888（散文里提到这个号，但上一行不是围栏 ⇒ 不是块头）\n"
        "  - id: MC-889\n"
        '    title: "夹具"\n'
    )
    assert header_bindings(text) == [], "散文引用被读成了注释头（判别力边界失守）"
    problems = header_problems({".github/cases/fixture.yml": text})
    assert not any("引到错的块" in p or "出现了" in p for p in problems), (
        f"散文引用被判成了块头（判别力边界失守）：{problems}"
    )
    # ⚠️ 这份合成语料**一条围栏头都没有** ⇒ fail-closed 那条**应当**报出（它不是误报，是设计：
    # 「形态消失即红」）。把它一并断言，顺带证明 fail-closed 规则是承载字段。
    assert any("一条围栏注释头都没有" in p for p in problems), f"fail-closed 未生效：{problems}"


def test_comment_only_change_is_not_red():
    """**对照读数**：只改块内的普通注释散文 ⇒ 不红（判的是号，不是文件变没变）。"""
    base = _corpus("MC-777", "MC-777")
    mutated = {k: v.replace('    title: "夹具"', '    title: "夹具"  # 只改一句散文') for k, v in base.items()}
    assert mutated != base, "散文变异注入未生效（自证失败）"
    assert header_problems(mutated) == [], "只改散文竟判红 ⇒ 判据在读文本而不是在读号"


def test_corpus_without_any_fenced_header_is_red():
    """红证（fail-closed）：语料里一条围栏头都没有 ⇒ 必须红（不许静默退化成空断言）。"""
    problems = header_problems({".github/cases/fixture.yml": "cases:\n  - id: MC-001\n"})
    assert any("一条围栏注释头都没有" in p for p in problems), f"空语料没被判红：{problems}"
