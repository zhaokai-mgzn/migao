# case_ids: MC-096
"""「已移除的页面名不得出现在**服务端面向商家的文案**里」的**类级守卫**（issue #6827；同类存量 = issue #6826）。

## 病根（一类缺陷，不是一个缺陷）

`#6580`（2026-10-09）撤掉了「参数总览」一级项与「加工项管理」/「工艺配置」两个菜单项 ——
配置面收口进 `/settings`（**企业基础设置**）页内的配置域。而**服务端下发的文案**
（未配置提示 / 422 拒绝理由 / 日志话术）仍逐字写着旧页面名 ⇒ 商家照着提示去点，**找不到那个页面**。
2026-10-13 用户在「企业基础设置 → 余料尺寸」域上**当场撞到**这一条（issue #6827 的 `notice`）。

修一处 = 没修（铁律 8）⇒ 本文件是那一类的机械面：**未登记即红 / 台账未被兑现即红 / 只许缩短**。

## 判据（逐条会红；红证 = 真语料 + 内存注入，见文末「判别力自证」）

| # | 判什么 | 取法（结构化证据） |
|---|---|---|
| 1 | **未登记即红**：`backend/admin-api/src/main/java/**/*.java` 的**字符串字面量**里出现已移除页面名，而台账里没有同键条目 | 词法取字面量（`_source_parsing.java_literals`，注释**不算**）⇄ 台账，报出 `文件 + 行 + 串` |
| 2 | **余料面永久清零**（本单的靶心）：任何命中与任何台账条目的名字都不得是「参数总览」 | 同上（这条**永不缩短**，`CLEARED_NAMES`） |
| 3 | **台账未被兑现即红 + 只许缩短**：台账每条必须在现取命中里有**同键同数**的对应；条数与命中数 ≤ 冻结上界 | 台账 ⇄ 现取；上界 = 本文件的 `FROZEN_MAX_*`（加条目必须同 PR 改大它，diff 里显式可见） |
| 4 | **只扫字面量、不扫注释**（对照读数）：注释里的旧页面名**不判**，字面量里的**判** | 词法分段（`//` / `/* */` / 字符串各自成段，`#5323` 的唯一实现） |
| 5 | **判别力自证**（注入式）：未登记命中 / 台账幽灵条目 / 命中数漂移 / 余料面复发**各自判红**；只改注释 ⇒ **不红** | 内存合成 + **真语料**变异 |
| 6 | **射程非空自证**（fail-closed）：扫描面 0 文件 ⇒ 红；正控 = 新指针「企业基础设置 → 余料尺寸」必须被同一把尺子**读到** | 现取 |

## 射程与边界（照实登记，`migao-dev-flow` §19.1）

- **射程 = `backend/admin-api/src/main/java/**/*.java` 的字符串字面量**（服务端面向商家的文案面）。
  **不含**：前端字面量（`frontend/**` 由 issue #6826 承担 —— 本单**不建第二份会漂的口径**，§31 P3）、
  `backend/ai-agent-service/**`、迁移 SQL、以及**注释 / javadoc**（沿革注释是**合法**的，见判据 4）。
- **已移除页面名的集合** = `REMOVED_PAGE_NAMES`（本期 = 参数总览 / 工艺配置 / 加工项管理 / 加工费管理）。
  扩集合必须同 PR 改这里并在 PR body 说明；`CLEARED_NAMES`（本单已清零的面）**不是**可选项。
- **未固化（照实登记）**：① 本判据判的是**文本**，判不了「该文案会不会真的上屏」（那要 §15.7 的真机截图）；
  ② 判不了「新指针指向的域 label 与 `frontend/admin-web/src/lib/config-center-domains.ts` 逐字一致」
  （域真值源自己的判据管那一半；**实例判据** = `tests/unit_ci_workflows/test_removed_page_pointer_targets.py`，MC-097）；
  ③ 台账里剩下的 3 条是**能力名**（岗位/权限显示名，不是坐标）—— 跟踪 issue #6826，本文件不为它们背书；
  ④ 判不了「假出口」（指向一个**不存在写能力**的页面坐标）—— 它只看页名，改写后的文案是否**真可行动**
  由 `docs/design/user-facing-copy-standard.md` 的评审口径 + MC-097 的实例判据承担。
- 复算：`python3 -m pytest tests/unit_ci_workflows/test_removed_page_copy_guard.py -q -s`
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_CI_DIR = REPO_ROOT / "tests" / "unit_ci_workflows"
LEDGER_PATH = UNIT_CI_DIR / "removed_page_copy_ledger.json"
SELF_REL = "tests/unit_ci_workflows/test_removed_page_copy_guard.py"

# ── 共享件（issue #5323：Java 剥注释 / 取字面量的**唯一**实现）──
sys.path.append(str(REPO_ROOT / "tests"))
from unit_ci_workflows._source_parsing import java_literals  # noqa: E402

#: 扫描面（服务端商家可见文案 = admin-api 的 Java 源码）。
SCAN_ROOT = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java"
SCAN_REL = "backend/admin-api/src/main/java"
SCAN_GLOB = "*.java"

#: 「已移除的页面名」（#6580 撤掉的一级项 / 菜单项）。**只许缩短**（要扩先改这里 + PR body 说明）。
REMOVED_PAGE_NAMES = ("参数总览", "工艺配置", "加工项管理", "加工费管理")

#: 本单（issue #6827）已清零的面 —— **永不**允许再出现在命中或台账里。
CLEARED_NAMES = ("参数总览",)

#: 台账冻结上界（**只许缩短**）：加条目必须是「同 PR 改大这里 + PR body 说明」，diff 里显式可见。
#: 🔻 2026-10-13（issue #6839 = #6826 的 B1 包）：12 条 / 13 处 ⇒ **3 条 / 3 处**（页名指针全部改指
#: 「企业基础设置 → <域 label>」，只剩**能力名**那 3 条 —— 显式判定「不改」+ 重启条件，见台账 reason）。
FROZEN_MAX_ENTRIES = 3
FROZEN_MAX_HITS = 3

#: 正控锚（判据 6）：本单落地的新指针 —— 它必须能被同一把尺子读到（否则说明字面量视图坏了）。
POSITIVE_CONTROL_LITERAL = "企业基础设置 → 余料尺寸"
POSITIVE_CONTROL_FILE = "backend/admin-api/src/main/java/com/migao/admin/service/RemnantService.java"

ISSUE_RE = re.compile(r"#\d+")


# ══════════════════════════════════════════════════════════════════════════════
# 检出器（词法；**纯函数** —— 判据与判别力自证共用同一份实现）
# ══════════════════════════════════════════════════════════════════════════════


def hits_in_source(rel: str, source: str) -> list[dict]:
    """一份 Java 源码里**字符串字面量**命中的已移除页面名（`文件 + 行 + 串`）。

    注释（`//` / `/* */`）里的同形文本**不算** —— 沿革注释是合法事实（判据 4 的对照读数）。
    """
    out: list[dict] = []
    for pos, literal in java_literals(source):
        for name in REMOVED_PAGE_NAMES:
            if name in literal:
                out.append({
                    "path": rel,
                    "line": source[:pos].count("\n") + 1,
                    "literal": literal,
                    "name": name,
                })
    return out


def corpus_key(hit: dict) -> str:
    """台账键 = `文件::字面量原文`（同文件同串的多处命中按**计数**合并 ⇒ 行号漂移不炸台账）。"""
    return f"{hit['path']}::{hit['literal']}"


def _group(hits: list[dict]) -> dict[str, dict]:
    grouped: dict[str, dict] = {}
    for hit in hits:
        key = corpus_key(hit)
        entry = grouped.setdefault(key, {
            "path": hit["path"],
            "name": hit["name"],
            "literal": hit["literal"],
            "hits": 0,
            "lines": [],
        })
        entry["hits"] += 1
        entry["lines"].append(hit["line"])
    for entry in grouped.values():
        entry["lines"] = sorted(entry["lines"])
    return grouped


def scanned_files() -> list[Path]:
    """扫描面文件（**空面 ⇒ fail-closed**：射程塌了不是「无需登记」）。"""
    files = sorted(SCAN_ROOT.rglob(SCAN_GLOB))
    if not files:
        raise AssertionError(
            f"扫描面为空：{SCAN_REL}/{SCAN_GLOB} 一个文件都没有 ⇒ 射程塌了 ⇒ 红（本判据 fail-closed）"
        )
    return files


def detected_hits() -> list[dict]:
    out: list[dict] = []
    for path in scanned_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        out.extend(hits_in_source(rel, path.read_text(encoding="utf8")))
    return out


def ledger() -> dict:
    if not LEDGER_PATH.exists():
        raise AssertionError(
            f"台账不存在：{LEDGER_PATH} —— fail-closed（缺台账 = 未修项无人管，不是「无需登记」）"
        )
    return json.loads(LEDGER_PATH.read_text(encoding="utf8"))


def ledger_entries() -> list[dict]:
    return list(ledger().get("entries", []))


def ledger_keys() -> dict[str, dict]:
    return {corpus_key(e): e for e in ledger_entries()}


# ── 三个判定本体（**纯函数**：判据与判别力自证调用同一份，不做第二份实现）────────


def unregistered_hits(hits: list[dict], entries: list[dict]) -> list[str]:
    """**未登记即红**：现取命中 ⇄ 台账，键或计数对不上就报出（含现取行号，便于复算）。"""
    detected, registered = _group(hits), {corpus_key(e): e for e in entries}
    problems: list[str] = []
    for key, hit in sorted(detected.items()):
        entry = registered.get(key)
        if entry is None:
            problems.append(
                f"未登记：{hit['path']}:{hit['lines']} 的字符串字面量含已移除页面名「{hit['name']}」"
                f" ⇒ {hit['literal']!r}（请改指向「企业基础设置 → <域 label>」，或按只许缩短登记进台账）"
            )
        elif int(entry.get("hits", 0)) != hit["hits"]:
            problems.append(
                f"命中数漂移：{hit['path']} 的 {hit['literal']!r} 现取 {hit['hits']} 处"
                f" / 台账 {entry.get('hits')} 处（改一处必须同 PR 销账）"
            )
    return problems


def unfulfilled_entries(hits: list[dict], entries: list[dict]) -> list[str]:
    """**台账未被兑现即红**：台账条目必须在现取命中里活著（幽灵条目 = 陈旧债务）。"""
    detected, registered = _group(hits), {corpus_key(e): e for e in entries}
    problems: list[str] = []
    for key, entry in sorted(registered.items()):
        if key not in detected:
            problems.append(
                f"台账未被兑现：{entry.get('path')} 的 {entry.get('literal')!r} 在扫描面上**已不存在**"
                f" ⇒ 该条陈旧（销账即删，台账只许缩短）"
            )
    return problems


def cleared_name_violations(hits: list[dict], entries: list[dict]) -> list[str]:
    """**余料面永久清零**：命中与台账里都不得再出现 `CLEARED_NAMES`。"""
    problems: list[str] = []
    for hit in _group(hits).values():
        if hit["name"] in CLEARED_NAMES:
            problems.append(
                f"「{hit['name']}」已由 #6580 撤掉：{hit['path']}:{hit['lines']} 的字面量仍是旧指针"
                f" ⇒ {hit['literal']!r}"
            )
    for entry in entries:
        if entry.get("name") in CLEARED_NAMES:
            problems.append(
                f"台账里登记了**已清零面**的名字「{entry.get('name')}」（{entry.get('path')}）—— 余料面不再允许挂账"
            )
    return problems


# ══════════════════════════════════════════════════════════════════════════════
# 判据
# ══════════════════════════════════════════════════════════════════════════════


def test_no_removed_page_name_in_server_copy_without_ledger_entry():
    """判据 1：**未登记即红**（现取命中必须逐条在台账里有同键同数的对应）。"""
    problems = unregistered_hits(detected_hits(), ledger_entries())
    assert problems == [], "服务端文案里出现未登记的已移除页面名：\n" + "\n".join(problems)


def test_remnant_face_stays_cleared():
    """判据 2（本单靶心）：**已清零面**（余料 / 参数总览）不得复发 —— 命中与台账都不许有。"""
    problems = cleared_name_violations(detected_hits(), ledger_entries())
    assert problems == [], "已清零面复发：\n" + "\n".join(problems)


def test_ledger_entries_are_live_and_only_shrink():
    """判据 3：**台账未被兑现即红** + 只许缩短（条数 / 命中数 ≤ 冻结上界）。"""
    hits, entries = detected_hits(), ledger_entries()
    problems = unfulfilled_entries(hits, entries)
    assert problems == [], "台账未被兑现：\n" + "\n".join(problems)
    total = sum(int(e.get("hits", 0)) for e in entries)
    assert len(entries) <= FROZEN_MAX_ENTRIES, (
        f"台账条数 {len(entries)} > 冻结上界 {FROZEN_MAX_ENTRIES}（只许缩短）—— "
        "新增条目必须同 PR 改大本文件的 FROZEN_MAX_ENTRIES，并在 PR body 说明为什么它是跨单债务"
    )
    assert total <= FROZEN_MAX_HITS, (
        f"台账命中数 {total} > 冻结上界 {FROZEN_MAX_HITS}（只许缩短）—— 同上"
    )


def test_ledger_is_well_formed():
    """台账形状：每条都要能复核（文件存在 / 串里含该名 / 跟踪单 / 理由），键不许重复。"""
    entries = ledger_entries()
    assert entries, "台账空转（entries 为空）—— 若真已清零，应同时把 FROZEN_MAX_* 收到 0 并说明"
    keys = [corpus_key(e) for e in entries]
    assert len(keys) == len(set(keys)), f"台账键重复：{sorted(k for k in keys if keys.count(k) > 1)}"
    for entry in entries:
        path = entry.get("path", "")
        assert path.startswith(SCAN_REL + "/") and (REPO_ROOT / path).is_file(), (
            f"台账条目的 path 不是扫描面内真实文件：{path!r}"
        )
        name = entry.get("name")
        assert name in REMOVED_PAGE_NAMES, f"台账条目名字不在 REMOVED_PAGE_NAMES 里：{name!r}"
        assert name in entry.get("literal", ""), f"台账条目的 literal 里不含它声称的名字 {name!r}"
        assert ISSUE_RE.search(entry.get("issue", "")), f"台账条目缺跟踪单号：{entry!r}"
        assert entry.get("reason", "").strip(), f"台账条目缺 reason：{entry!r}"


def test_scan_surface_is_live_and_detector_reads_literals():
    """判据 6：射程非空 + **正控**（本单落地的「企业基础设置 → 余料尺寸」必须被同一把尺子读到）。"""
    files = scanned_files()
    assert len(files) > 100, f"扫描面只有 {len(files)} 个 Java 文件 —— 射程可疑地小 ⇒ 红"
    source = (REPO_ROOT / POSITIVE_CONTROL_FILE).read_text(encoding="utf8")
    literals = [text for _pos, text in java_literals(source)]
    assert any(POSITIVE_CONTROL_LITERAL in text for text in literals), (
        f"正控失败：{POSITIVE_CONTROL_FILE} 的字面量里读不到 {POSITIVE_CONTROL_LITERAL!r} —— "
        "字面量视图坏了（此时「零命中」是假绿）"
    )
    assert all("参数总览" not in text for text in literals), "正控文件里余料面的旧指针又回来了"


# ══════════════════════════════════════════════════════════════════════════════
# 判别力自证（注入式；四种坏形态各自判红 + 一条对照读数）
# ══════════════════════════════════════════════════════════════════════════════


def _fake_entry(hit: dict, hits: int = 1) -> dict:
    return {
        "path": hit["path"], "name": hit["name"], "literal": hit["literal"], "hits": hits,
        "issue": "#6826", "reason": "判别力自证用的内存夹具",
    }


def test_injection_unregistered_hit_is_red():
    """坏形态 ①：把旧指针写回**字面量** ⇒ 判据 1 当场红并**具名**（含文件 + 行 + 串）。"""
    source = (
        "class X {\n"
        '    static final String NOTICE = "请在「参数总览 → 余料回收」里填尺寸";\n'
        "}\n"
    )
    hits = hits_in_source("backend/admin-api/src/main/java/X.java", source)
    assert len(hits) == 1
    problems = unregistered_hits(hits, [])
    assert len(problems) == 1 and "X.java:[2]" in problems[0] and "参数总览" in problems[0]
    assert cleared_name_violations(hits, []) != [], "余料面复发必须被判据 2 抓住"


def test_injection_comment_only_change_is_not_red():
    """对照读数：**只改注释**（`//` 与 `/* */` 两种形态）⇒ 一条判据都不红。"""
    source = (
        "/** 沿革：本域原在「参数总览 → 余料回收」下（issue #6580 撤销） */\n"
        "class X {\n"
        "    // 旧指针（说明用）：参数总览 / 工艺配置 / 加工项管理 / 加工费管理\n"
        "    static final String OK = \"企业基础设置 → 余料尺寸\";\n"
        "}\n"
    )
    hits = hits_in_source("backend/admin-api/src/main/java/X.java", source)
    assert hits == [], f"只改注释却被判红（沿革注释是合法的）：{hits}"
    assert unregistered_hits(hits, []) == []
    assert cleared_name_violations(hits, []) == []


def test_injection_real_corpus_comment_vs_literal():
    """真语料变异（同一份实现）：`RemnantService.java` 加注释 ⇒ 不红；把新指针改成旧指针 ⇒ 红。"""
    rel = POSITIVE_CONTROL_FILE
    source = (REPO_ROOT / rel).read_text(encoding="utf8")
    assert detected_hits_for(rel, source) == []

    commented = source + "\n// 沿革注释：这里曾指向「参数总览 → 余料回收」（issue #6827 已改）\n"
    assert detected_hits_for(rel, commented) == [], "注释注入不该被判红"

    mutated = source.replace(
        f"请在「{POSITIVE_CONTROL_LITERAL}」里为需要的小件",
        "请在「参数总览 → 余料回收」里为需要的小件",
        1,
    )
    assert mutated != source, "变异没生效（正控锚在新源码里找不到）⇒ 判据会假绿"
    mutated_hits = detected_hits_for(rel, mutated)
    assert len(mutated_hits) == 1 and mutated_hits[0]["name"] == "参数总览"
    assert cleared_name_violations(mutated_hits, []) != []


def detected_hits_for(rel: str, source: str) -> list[dict]:
    """`hits_in_source` 的具名包装（真语料变异用；与判据调用同一份实现）。"""
    return hits_in_source(rel, source)


def test_injection_ghost_ledger_entry_and_count_drift_are_red():
    """坏形态 ②/③：台账**幽灵条目**（未兑现）与**命中数漂移**各自判红。"""
    hit = hits_in_source(
        "backend/admin-api/src/main/java/X.java",
        'class X { static final String S = "请去「加工费管理」定价"; }\n',
    )[0]
    live = _fake_entry(hit, hits=1)
    assert unfulfilled_entries([hit], [live]) == []
    ghost = _fake_entry({**hit, "literal": "请去「加工费管理」定价（已不存在的串）"}, hits=1)
    assert unfulfilled_entries([hit], [ghost]) != [], "幽灵台账条目必须红"

    two = hits_in_source(
        "backend/admin-api/src/main/java/X.java",
        'class X { static final String S = "请去「加工费管理」定价"; static final String T = "请去「加工费管理」定价"; }\n',
    )
    assert len(two) == 2
    drift = unregistered_hits(two, [live])
    assert len(drift) == 1 and "命中数漂移" in drift[0], "同键命中数变化必须红（改一处必须销账）"


def test_corpus_key_is_stable_across_line_shifts():
    """键 = 文件 + 字面量原文 ⇒ **行号漂移不炸台账**（台账只许缩短，不靠行号定位）。"""
    before = hits_in_source("backend/admin-api/src/main/java/X.java",
                            'class X { static final String S = "请去「加工费管理」定价"; }\n')
    after = hits_in_source("backend/admin-api/src/main/java/X.java",
                           '\n\n\nclass X { static final String S = "请去「加工费管理」定价"; }\n')
    assert before[0]["line"] != after[0]["line"]
    assert corpus_key(before[0]) == corpus_key(after[0])
