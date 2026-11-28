# case_ids: AG-014
r"""C 端不再拟人化：用例库「米宝」残称守卫（issue #9280，2026-11-28 用户裁定）。

## 口径（用户逐字）

> 「C 端也不叫米宝了，C 端现在**不提供 agent 形态，只提供技术能力**，直接叫**智能客服**」

⇒ B 端经营侧 = 黄金策（agent 形态）；C 端 = **智能客服**（无 agent 形态、不拟人）。

## 为什么这是一条**类级**元守卫

原来 19 条 live 用例（`.github/cases/chat.yml` 现取 `grep -c 米宝`）把 C 端当拟人 agent 写，
其中 `AG-014` 的**前提**（「米宝」是 C 端 agent 的名字）随产品形态变化**整体失效** ——
它当时断言的「不得自称黄金策」在「C 端根本不该有拟人名」之后就只是一半的判据。
靠人记住「以后别再写米宝」必然复发（历史上品牌改名 #6525 / #8881 就复发过），
⇒ 落成判据：**未登记即红** + 台账**只许缩短**。

## 三条判据

| # | 判据 | 红的样子 |
|---|---|---|
| 1 | live 面（`title` / `precondition` / `want_text` / `data_checks` / 注释 …，**不含 `merge_log`**）不得再出现「米宝」 | 具名 `文件:行 用例ID` + 原文行 |
| 2 | 台账诚实：每条登记必须仍有命中（空豁免红）+ `frozen_max` 与条数相等（只许缩短） | 具名条目 + 复算命令 |
| 3 | `AG-014` 必须**两侧都在**：`forbidden_text` 禁「米宝」/「黄金策」/「商家后台助手」，且 `want_text`/`data_checks` 要求**表明自己是智能客服** | 具名缺哪一侧 |

`merge_log` **不在扫描面**：它是 append-only 审计记录，历史旧称一律照旧（判据 5 钉住这条排除是真的）。

三态：`0` = 绿；`1` = 红（具名）；本判据零网络、零时钟，**无 `3`**。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from unit_ci_workflows.injection import inject

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
LEDGER_PATH = Path(__file__).resolve().parent / "c_end_persona_name_residue_ledger.json"

#: C 端旧拟人名（本判据唯一扫描目标；技术标识符 `mibao` / `xiaobu` 不在此列 —— 它们是标识符，不是称呼）
OLD_NAME = "米宝"
#: C 端新称呼（不拟人）
NEW_NAME = "智能客服"
#: AG-014 禁自称面：拟人名 + B 端后台身份
AG014_FORBIDDEN = ("米宝", "黄金策", "商家后台助手")

_CASE_ID_RE = re.compile(r"^  - id:\s*(\S+)\s*$")
_FIELD_RE = re.compile(r"^    ([a-zA-Z_]+):")

#: `merge_log` 的续行判定：同缩进字段 / 缩进回到 2 空格的块级行 / 块注释 / 空行 ⇒ 区域结束
_MERGE_END_RE = re.compile(r"^(    [a-zA-Z_]+:|  \S|  #|\s*$)")


def ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def classify_lines(text: str) -> list[tuple[str, int, str, str]]:
    """逐行标注 `(case_id, 行号, 原文, zone)`；`zone ∈ {"live", "merge_log"}`。

    纯函数（红证直接喂字符串）：`merge_log` 是 append-only 审计记录，**不进扫描面**。
    """
    rows: list[tuple[str, int, str, str]] = []
    case_id = "<未归属任何用例>"
    in_merge = False
    for lineno, line in enumerate(text.split("\n"), 1):
        matched = _CASE_ID_RE.match(line)
        if matched:
            case_id = matched.group(1)
            in_merge = False
        if _FIELD_RE.match(line) and _FIELD_RE.match(line).group(1) == "merge_log":
            in_merge = True
        elif in_merge and _MERGE_END_RE.match(line):
            in_merge = False
        rows.append((case_id, lineno, line, "merge_log" if in_merge else "live"))
    return rows


def live_hits(rel_path: str, text: str) -> list[tuple[str, int, str]]:
    """live 面里含旧称的行：`[(case_id, 行号, 原文)]`。"""
    return [
        (case_id, lineno, line)
        for case_id, lineno, line, zone in classify_lines(text)
        if zone == "live" and OLD_NAME in line
    ]


def _covered(entries: list[dict], rel_path: str, case_id: str, line: str) -> bool:
    return any(
        e["path"] == rel_path and e["case_id"] == case_id and e["anchor"] in line
        for e in entries
    )


def violations(rel_path: str, text: str, entries: list[dict]) -> list[str]:
    """live 面里**未登记**的旧称出现（具名 `文件:行 用例ID` + 原文）。纯函数。"""
    return [
        f"{rel_path}:{lineno} · {case_id} · {line.strip()}"
        for case_id, lineno, line in live_hits(rel_path, text)
        if not _covered(entries, rel_path, case_id, line)
    ]


def scan_repo() -> list[str]:
    entries = ledger()["entries"]
    out: list[str] = []
    for path in sorted(CASES_DIR.glob("*.yml")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        out.extend(violations(rel, path.read_text(encoding="utf-8"), entries))
    return out


def ag014_problems(agents_text: str) -> list[str]:
    """`AG-014` 的两侧判据（`forbidden_text` 禁自称 / `want_text`+`data_checks` 表明是智能客服）。纯函数。"""
    data = yaml.safe_load(agents_text) or {}
    case = next((c for c in (data.get("cases") or []) if c.get("id") == "AG-014"), None)
    if case is None:
        return ["AG-014 不在 .github/cases/agents.yml 里（用例被删？判据无处落地）"]

    problems: list[str] = []
    forbidden = [str(x) for x in (case.get("forbidden_text") or [])]
    missing = [name for name in AG014_FORBIDDEN if name not in forbidden]
    if missing:
        problems.append(f"AG-014 的 forbidden_text 缺少禁自称面：{missing}（现取 {forbidden}）")

    checks = " ".join(str(x) for x in (case.get("data_checks") or []))
    want = " ".join(str(x) for x in (case.get("want_text") or []))
    if NEW_NAME not in want and NEW_NAME not in checks:
        problems.append(f"AG-014 没有任何「必须说自己是{NEW_NAME}」的判据（want_text={want!r}）")
    if f"含「{OLD_NAME}」" in checks or f"含『{OLD_NAME}』" in checks:
        problems.append(f"AG-014 的 data_checks 仍在要求「含「{OLD_NAME}」」—— 前提已失效（应改为表明是{NEW_NAME}）")

    if case.get("persona") != "xiaobu":
        problems.append(
            f"AG-014 的 persona 被改成 {case.get('persona')!r}：`persona` 是技术标识（另一个包在动代码侧），"
            "改名不该走这里"
        )
    return problems


# ── 判据 1：live 面零旧称 ────────────────────────────────────────────────────

def test_live_case_text_has_no_old_persona_name():
    found = scan_repo()
    assert found == [], (
        f"用例库 live 面仍有 {len(found)} 处「{OLD_NAME}」（C 端已改为不拟人的「{NEW_NAME}」）：\n  "
        + "\n  ".join(found)
        + "\n真正的代码侧字面量/负断言请登记进 tests/unit_ci_workflows/"
        "c_end_persona_name_residue_ledger.json（只许缩短）；`merge_log` 属审计记录，照旧。"
    )


# ── 判据 2：台账诚实（空豁免红 + 只许缩短）──────────────────────────────────

def test_residue_ledger_is_honest():
    data = ledger()
    entries = data["entries"]
    assert len(entries) == data["frozen_max"], (
        f"台账条数 {len(entries)} ≠ 冻结上限 {data['frozen_max']} —— 只许缩短："
        "删条目的同批必须下调 frozen_max（上调上限 = 扩大豁免，需要评审）"
    )
    stale: list[str] = []
    for entry in entries:
        text = (REPO_ROOT / entry["path"]).read_text(encoding="utf-8")
        hit = any(
            case_id == entry["case_id"] and entry["anchor"] in line
            for case_id, _lineno, line in live_hits(entry["path"], text)
        )
        if not hit:
            stale.append(f"{entry['path']} · {entry['case_id']} · {entry['anchor']}")
        assert len(entry["why"].strip()) >= 10, (
            f"台账条目缺理由（≥10 字；写不出理由 = 还没想清为什么要保留）：{entry}"
        )
    assert stale == [], (
        "台账里有登记却已无命中（空豁免只许缩短，删掉这些条目并同批下调 frozen_max）：\n  "
        + "\n  ".join(stale)
    )


# ── 判据 3：AG-014 两侧都在 ─────────────────────────────────────────────────

def test_ag_014_has_both_sides():
    agents_text = (CASES_DIR / "agents.yml").read_text(encoding="utf-8")
    problems = ag014_problems(agents_text)
    assert problems == [], "AG-014 改判不完整：\n  " + "\n  ".join(problems)


# ── 判据 4：红证（两条，都是注入式、且注入先自证生效）────────────────────────

def test_red_proof_old_name_back_in_an_expectation():
    """红证 A：把某条用例的期望改回「米宝」⇒ 判据 1 **具名红**。"""
    rel = ".github/cases/ui.yml"
    original = (REPO_ROOT / rel).read_text(encoding="utf-8")
    anchor = '空态：顶部三条居中的推荐胶囊'
    assert anchor in original, f"红证锚点已漂移（{rel} 里找不到 {anchor!r}）—— 换一条锚点，别删红证"
    broken = inject(
        original,
        '顾客打开智能客服聊天主页' + anchor,
        '顾客打开米宝聊天主页' + anchor,
        where=rel,
    )
    assert broken != original and "顾客打开米宝聊天主页" + anchor in broken, "注入没生效 ⇒ 红证是空跑"
    found = violations(rel, broken, ledger()["entries"])
    assert [v.split(" · ")[1] for v in found] == ["UI-044"], f"红证没点名 UI-044：{found}"


def test_red_proof_ag_014_loses_its_forbidden_name():
    """红证 B：把 `AG-014` 的「禁米宝」摘掉 ⇒ 判据 3 **具名红**（且点名 forbidden_text 缺哪一侧）。"""
    agents_text = (CASES_DIR / "agents.yml").read_text(encoding="utf-8")
    broken = inject(agents_text, '      - "米宝"\n', "", where=".github/cases/agents.yml")
    assert broken.count('      - "米宝"') == 0, "注入没生效（「禁米宝」还在）⇒ 红证是空跑"
    problems = ag014_problems(broken)
    assert [p for p in problems if "forbidden_text 缺少禁自称面" in p], (
        f"摘掉「禁米宝」后判据 3 没红：{problems}"
    )
    assert "米宝" in problems[0], f"红证没点名缺的是「米宝」：{problems}"


# ── 判据 5：merge_log 真的不在扫描面（历史记录 append-only）─────────────────

def test_merge_log_zone_is_excluded_from_the_scan():
    """`merge_log` 里的旧称**不得**被判红，否则等于逼人改写审计记录。"""
    synthetic = (
        "  - id: ZZ-999\n"
        '    title: "示例：智能客服答顾客"\n'
        '    merge_log: "2026-10-08 品牌改名 米宝→黄金策"\n'
        '    data_checks:\n'
        '      - "正向：表明自己是智能客服"\n'
    )
    assert live_hits(".github/cases/zz.yml", synthetic) == [], "merge_log 行被判进了扫描面"
    leaked = synthetic.replace("表明自己是智能客服", "表明自己是米宝")
    assert [case_id for case_id, _l, _t in live_hits(".github/cases/zz.yml", leaked)] == ["ZZ-999"], (
        "live 面的旧称必须命中（扫描器没有判别力）"
    )
