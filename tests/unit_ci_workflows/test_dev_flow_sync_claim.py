# case_ids: MC-012
"""`docs/wiki/DEV-FLOW.md` 的「同步副本」claim 已**撤回** ⇒ 不许再悄悄长回来（issue #4315）。

## 病根（§19.1 元规则：**基于错误真相模型写出的 claim**）

该页第 3 行自称是技能 `migao-dev-flow` 的**仓库同步副本**、第 5 行写死「当前版本：v1.3」，
而**同步早已停止**（权威源当时已 **1.34.0**；页 341 行 vs 技能 971 行；8 个同名章节里 6 个归一化后仍不同）。
「这是同步副本」让读者（含 agent）**把过期内容当真值用**，而**没有任何东西会因此变红**。
同族还有写死的**易变数字**：「`migao-wt/` 下含该预设文件的 **38 个**工作区里 **31** 个版本 ≠ main」
—— 同一量本机实测已漂到 **62**（§19.2 ③「不写死易变数字」）。

## 处置 = **撤回**（issue #4315 的 A 案），不是「由权威源渲染」（B 案）

理由与代价写在 PR 报告里，一句话：本页是**人工散文节选**（技能 20 节 → 本页 8 节，且页内是摘要
而非可机械重排的结构），要"渲染"就得先把节选搬进技能或写一套摘要渲染器 ⇒ 每次技能更新都要重生成
整页，成本高于收益。撤回之后**必须有判据**，否则这条 claim 只是"这次删掉了"。

## 判据形态：取**形状**，不与技能内容等值

| # | 形态 | 判据 |
|---|---|---|
| C1 | **肯定式**同步副本声明：某行含「同步副本」却**不带**撤回标记（`不是`/`非同步`/`已停止同步`/`不再`/`已撤回`） | 不许出现 |
| C2 | 硬编码**现值**：`当前版本：vX` 形态版本戳、`副本 vX` / `权威源 vX.Y.Z` 形态的版本对 | 不许出现 |
| C3 | 硬编码 `migao-wt` **工作区计数**（`N 个工作区` / `N 个的…`） | 不许出现 |
| C4 | 页头（第一个 `## ` 之前）**必须**同时声明「已停止同步」+「以技能为准」 | 必须存在 |

C4 是**正向**断言：只删 claim 而不写清「以技能为准」，等于把过期内容变成**无归属的孤儿**。

## 边界（照实登记，别把「登记了」读成「治住了」）

* C1~C3 只治「**会腐烂的现值声明**」这一形态。页内**其余**散文现值的时效性（CI 触发档、
  经验计数等）**不在**本判据范围内 —— 已逐个列在 issue #4315 的报告里，属另开单范围。
* C3 **故意收窄**成「计数直接量词是*工作区*」的形状（`N 个工作区` / `N 个的…`）：
  泛化的「`N 条/N 个`」**没有零误红判据**（会命中"落后 42 个提交""142 个文件的大 PR"这类
  **历史叙事**），这正是 `scripts/drift_audit.py` 把 `hardcoded-count` 登记为**未实装**的理由
  —— 本文件**不**冒充当它已实装。
* 页头「权威源：`<path>`」形态由**既有**判据守着（`scripts/drift_audit.py` 的 `sync-copy`：
  `declared-source` / `declared-source-dangling`，**无基线豁免** ⇒ 掉了就红）—— 本文件**不复制**这条规则。
* 本判据**不读技能内容、不读 frontmatter 版本** ⇒ 技能更新**不会**让它红（这正是"撤回"要的性质：
  判据不该依赖"副本与技能等值"这个已被证伪的真相模型）。

## 红证（两级，都是真的）

① **常驻注入式自证**（本文件）：`ORIGINAL_DEFECT_LINES` = 撤回前的**逐字原文**，
   每个探测器在它上面**必须报错**，且把原文注回**当前页**也必须被抓到
   —— 否则主测试的绿只是空跑（`migao-acceptance`「不会红的断言 = 空断言」）。
② **真文件注入**（人工，见 PR 报告）：把 claim / 版本戳 / 计数注回真页 ⇒ 主测试必红；
   注入前后用 `python3 scripts/red_proof.py fingerprint|injected|restored` 清缓存 + 内容指纹自证
   （§19.1 元规则 ③ 红证卫生；**禁** mtime/size 判新鲜度）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DEV_FLOW = REPO / "docs" / "wiki" / "DEV-FLOW.md"

SYNC_COPY_PHRASE = "同步副本"
# 同行出现这些词 ⇒ 该行是在**说明为何不是**同步副本，不是在 claim
RETRACTION_MARKERS = ("不是", "非同步", "已停止同步", "不再", "已撤回")

# 页头必须出现的两句（C4）
DECLARED_RETRACTION = "已停止同步"
DECLARED_AUTHORITY = "以技能为准"

_CURRENT_VERSION_STAMP = re.compile(r"当前版本\s*[:：]\s*v?\d")
_SOURCE_VERSION_PAIR = re.compile(r"(?:权威源|副本)\s*v?\d+\.\d")
# 计数直接量词是**工作区**才算（见 docstring「边界」：泛化的 `N 个` 无零误红判据）
_WORKTREE_COUNT = re.compile(r"\d+\s*个\s*工作区|\d+\s*个的")

# 注入锚点（页内稳定存在的一行；注入用）
INJECT_ANCHOR = "## 1. 三把工具（开发自查用）"

# 撤回前 `docs/wiki/DEV-FLOW.md` 的**逐字原文**（@9673df68 的第 3 / 5 / 281 / 84 行）——
# 只作夹具，**不得**再出现在真页里。
ORIGINAL_DEFECT_LINES = (
    "> 本文档是 DSH 技能 `migao-dev-flow`（**权威源：`.agent-presets/migao/skills/migao-dev-flow/SKILL.md`**，"
    "随代码评审/入库）的仓库同步副本，供团队共享阅读。",
    "> 当前版本：v1.3（2026-09-04）——新增多会话并发规范（一会话一 worktree + 会话锁 + 端口隔离 + 分支卫生）、"
    "CI 队列治理、验证分级降本。",
    "> ⚠️ 本文件是 `migao-dev-flow` 技能的**同步副本**（版本戳已落后：副本 v1.3 / 权威源 1.31.0，",
    "：`migao-wt/` 下含该预设文件的 **38 个**工作区里，**31** 个的 `migao-dev-flow` 版本 ≠ main"
    "（1.18.0 ~ 1.28.0），仅 **7** 个同步。",
)
# 撤回前的**整个页头块**（逐字，@9673df68 的第 3~6 行）—— 含「以技能为准」那一行，
# 故 C4 能证明它「**只**缺『已停止同步』」而不是整块都缺。
ORIGINAL_HEADER_BLOCK = "\n".join((
    ORIGINAL_DEFECT_LINES[0],
    "> **流程口径以技能为准**：改流程规范**先改技能**，再同步本页；两份不一致时按技能执行"
    "（历史路径 `migao/.agents/skills/...` 已废弃）。",
    ORIGINAL_DEFECT_LINES[1],
    "> 内容源自历史全链路复盘（RETROSPECTIVE，未入库）的 P0/P1 改进，经实战固化。",
))


# ── 探测器（纯函数，零 IO）─────────────────────────────────────────────────

def _plain(text: str) -> str:
    """去掉 markdown 强调/代码标记（`**` / `` ` ``）——数字与量词之间常被标记隔开。"""
    return text.replace("*", "").replace("`", "")


def find_affirmative_sync_claims(text: str) -> list[tuple[int, str]]:
    """C1：含「同步副本」却**不带撤回标记**的行（= 肯定式 claim）。"""
    out: list[tuple[int, str]] = []
    for no, line in enumerate(text.splitlines(), 1):
        if SYNC_COPY_PHRASE not in line:
            continue
        if any(marker in line for marker in RETRACTION_MARKERS):
            continue
        out.append((no, line.strip()))
    return out


def find_rotting_stamps(text: str) -> list[tuple[int, str]]:
    """C2 + C3：硬编码现值（版本戳 / 权威源-副本版本对 / 工作区计数）。"""
    out: list[tuple[int, str]] = []
    for no, line in enumerate(text.splitlines(), 1):
        plain = _plain(line)
        if any(pat.search(plain) for pat in
               (_CURRENT_VERSION_STAMP, _SOURCE_VERSION_PAIR, _WORKTREE_COUNT)):
            out.append((no, line.strip()))
    return out


def header_block(text: str) -> str:
    """页头 = 第一个二级标题（`## `）之前的内容。"""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith("## "):
            return "\n".join(lines[:idx])
    return text


def _page() -> str:
    return DEV_FLOW.read_text(encoding="utf-8")


# ── 主判据（跑在真页上）───────────────────────────────────────────────────

def test_page_has_no_affirmative_sync_copy_claim():
    found = find_affirmative_sync_claims(_page())
    assert found == [], (
        "docs/wiki/DEV-FLOW.md 仍自称『同步副本』（issue #4315：同步早已停止，claim 已撤回）：\n"
        + "\n".join(f"  第 {no} 行：{text}" for no, text in found)
        + "\n改法：写明『**不是**…同步副本 / 同步已停止』并指『以技能为准』。")


def test_page_has_no_rotting_version_or_count_stamps():
    found = find_rotting_stamps(_page())
    assert found == [], (
        "docs/wiki/DEV-FLOW.md 出现硬编码的**现值**（版本戳 / 工作区计数）——§19.2 ③ 不写死易变数字"
        "（数字会腐烂、且没人会因此变红）：\n"
        + "\n".join(f"  第 {no} 行：{text}" for no, text in found)
        + "\n改法：换成**可复算的命令**（命令自证）而不是现值。")


def test_header_declares_retraction_and_authority():
    head = header_block(_page())
    missing = [m for m in (DECLARED_RETRACTION, DECLARED_AUTHORITY) if m not in head]
    assert missing == [], (
        f"docs/wiki/DEV-FLOW.md 页头缺关系声明 {missing}（issue #4315：撤回 claim 必须同时说清"
        "『已停止同步』+『以技能为准』，否则过期内容变成无归属的孤儿）。\n"
        f"页头现状：\n{head}")


# ── 常驻注入式自证：探测器在「撤回前原文」上必须报错 ────────────────────────

def test_C1_detector_flags_original_sync_copy_claim():
    """撤回前页头有肯定式「同步副本」（第 1 行）⇒ C1 必须报；页内第 281 行那处同理。"""
    assert [no for no, _ in find_affirmative_sync_claims(ORIGINAL_HEADER_BLOCK)] == [1]
    assert [no for no, _ in find_affirmative_sync_claims(ORIGINAL_DEFECT_LINES[2])] == [1]


def test_C2_detector_flags_original_version_stamps():
    """撤回前有「当前版本：v1.3」（页头第 3 行）与「副本 v1.3 / 权威源 1.31.0」（第 281 行）⇒ C2 必须都报。"""
    assert [no for no, _ in find_rotting_stamps(ORIGINAL_HEADER_BLOCK)] == [3]
    assert [no for no, _ in find_rotting_stamps(ORIGINAL_DEFECT_LINES[2])] == [1]


def test_C3_detector_flags_original_worktree_counts():
    """撤回前那行写死「38 个工作区 / 31 个的」⇒ C3 必须报（且必须容忍 `**` 标记）。"""
    hits = find_rotting_stamps(ORIGINAL_DEFECT_LINES[3])
    assert [no for no, _ in hits] == [1], f"C3 探测器失灵（没抓到工作区计数）：{hits}"


def test_C3_detector_does_not_fire_on_historical_narrative():
    """**不许误伤**：同一页里的历史叙事（"落后 42 个提交""142 个文件的大 PR"）不得被判据命中。"""
    narrative = (
        "> 实测活锚曾指向落后 `origin/main` **42 个提交**的主工作区，**内容当时恰好一致**",
        "- **禁止长期不提交**：避免 142 个文件的大 PR。",
    )
    for line in narrative:
        assert find_rotting_stamps(line) == [], f"C3 误伤历史叙事：{line}"


def test_C4_detector_discriminates_original_header():
    """撤回前页头**只**有「以技能为准」、没有「已停止同步」⇒ C4 必须恰缺一个（判据要能区分）。"""
    head = header_block(ORIGINAL_HEADER_BLOCK)
    assert DECLARED_AUTHORITY in head
    assert DECLARED_RETRACTION not in head


@pytest.mark.parametrize("payload", ORIGINAL_DEFECT_LINES)
def test_injecting_original_defect_into_current_page_is_caught(payload):
    """把撤回前的每一行**注回当前页** ⇒ C1/C2/C3 至少一个必须抓到（永久红证，不动真文件）。"""
    page = _page()
    assert INJECT_ANCHOR in page, "注入锚点没命中 ⇒ 注入未生效，红证不成立"
    mutated = page.replace(INJECT_ANCHOR, payload + "\n\n" + INJECT_ANCHOR, 1)
    assert mutated != page, "注入后文本没变 ⇒ 注入未生效"
    caught = find_affirmative_sync_claims(mutated) + find_rotting_stamps(mutated)
    assert caught, f"注入未被判据捕获 = 空断言：{payload[:60]}"
