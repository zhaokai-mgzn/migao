# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见同目录 `test_guard_parsing_is_comment_aware.py` / `_source_parsing.py` 的同款声明。
#   本 PR **不新建用例族**：现取号 MC-133 未使用 —— 新增用例族要改 `.github/cases/*.yml`
#   + 重渲染生成物，而本包是「既有红证注入」的类级固化，不是新业务用例。）
"""注入式红证的**锚点活性**类级判据（issue #7017 类级固化）。

## 病（一类缺陷，不是一个缺陷）

红证靠「把 A 逐字替换成 B」造坏形态。A 一旦**上下文漂移**（间距 / 换行 / 变量名变了），
`str.replace` **找不到目标就返回原串** ⇒ 注入静默变成空操作：

- 判据仍绿 ⇒ 被读成「**判据没牙**」（动作 = 补判据）；
- 真因是「**锚点漂了**」（动作 = 改锚点）。

两者**处置相反**，而报告**同形**。#6611 现场就是这么被误读的：`deploy-frontend.yml` 的部署调用
改成位置实参后，`test_frontend_bmini_entry_single_source.py` 那条注入的锚点不再命中，
那条守卫一直报「变异没有被判红」。

## 三条判据（施工单 ①②③）

| # | 判据 | 红成什么样 |
|---|---|---|
| **①** | **裸 `.replace(` 造变异体**（AST 判；注释 / docstring / 文案**不算**）必须改用共用原语 `injection.inject()` | **未登记即红**：给出「文件:行号 + 接收者」，出口 = 改用 `inject()` 或显式登记为存量债务。存量在 `red_proof_anchor_ledger.json` 的 `bare_replace_exemptions`，**只许缩短**（涨/跌/陈旧都红） |
| **②** | 登记在案的**每一个注入锚点**都要在**当前语料**上真跑一次 `inject()` | **锚点漂移** ⇒ 具名红：说出「哪个 id / 哪个语料 / 锚点前 60 字 / 同前缀仍在的行」，**不是**「判据没牙」 |
| **③** | **判别力自证**：把某个锚点**多打一个空格** ⇒ ② 必红，且报文含「锚点漂移」 | 判别力退化成绿 ⇒ 红（原锚点必须不抛：反向对照） |

## 台账（数据文件 `red_proof_anchor_ledger.json`，判据只读它、不读注释）

- `anchors[]` = **活锚登记册**（迁移落地的注入锚点）：每条含
  `{id, corpus, anchor, call_site, why, issue}`。**`corpus` 必须是真语料**（仓库相对路径），
  `call_site` 必须真的用 `inject(..., where=...)` 传这个锚点 —— 否则「锚点活着」也证明不了
  「红证还在用原语注入」（迁移被改回裸 replace 时这条会红）。
- `bare_replace_exemptions[]` = **存量债务**：每条含 `{path, hits, reason, issue}`，
  `hits` 是**现取条数**（不写解释性上限）。规则与 `guard_parsing_allowlist.json` 同族：
  未登记即红 / 已登记文件的条数涨或跌都红 / 文件已无命中而条目还在（陈旧）⇒ 红。
  **只许缩短**：想「加一条豁免吸收新债务」必须改这个数据文件、在 diff 里**看得见**。

## 扫描面与判定方式（为什么不会误伤文案）

- 面 = `tests/unit_ci_workflows/*.py`（排除本判据与 `injection.py` 自身）。
- 判定**只读 AST**：只有 `ast.Call` 且 `func.attr == "replace"` 才可能命中；
  注释 / docstring / 字符串字面量**不是** Call 节点 ⇒ 结构性不可能被计入（负控 = `test_comment_and_prose_mentions_are_not_counted`）。
- 「是不是注入」按**语法证据**判：接收者表达式里**或**所在函数名里出现变异/注入词
  （`mutat|inject|broken|tamper|corrupt|variant|mutant|poison|sabot`）。
  这是**形态学**判据，不做语义一刀切 —— 边界见下。

## 边界（照实登记，§19.1）

1. **判定面只到「函数名/接收者带变异词」的那一族**：写在普通函数里、变量名也普通的注入
   （例：`broken = src.replace(...)`）**不会被 ① 命中** —— 与 `test_guard_parsing_is_comment_aware.py`
   的「形态学判据」同族取舍。**假绿方向**（漏判，不误伤）；②③ 仍按登记册覆盖已迁移点。
2. **性能预筛**（不是判定）：源码里没有 `.replace(` 字样的文件跳过 `ast.parse`；
   用 `getattr(x, "replace")` 动态取方法的写法不在面内（同样假绿方向）。
3. **`count=N` 的语义是「恰好 N 次」**：这是有意的（「至多 N 次」会让「少替换一处」静默通过）。
4. 本判据**不跑**被登记锚点所属的测试（那会把本文件变成「套件再跑一遍」）；
   它只证明「锚点活着 + 迁移点接在共用原语上」，**判据该不该红仍由各红证自己证明**。
5. 按 §23 G9：本判据**不为存量债务的安全性背书**，只裁新增与漂移。

判据 = 本文件；一键复算：
`python3 -m pytest tests/unit_ci_workflows/test_red_proof_anchor_liveness.py -q -s`
"""
from __future__ import annotations

import ast
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_CI_DIR = REPO_ROOT / "tests" / "unit_ci_workflows"
LEDGER_PATH = Path(__file__).with_name("red_proof_anchor_ledger.json")

SELF_REL = "tests/unit_ci_workflows/test_red_proof_anchor_liveness.py"
PRIMITIVE_REL = "tests/unit_ci_workflows/injection.py"

#: 注入面必须**排除**自己：本判据的文档与夹具里到处是 `.replace(` 字样，
#: 而 `injection.py` 的实现本体就是一处 `str.replace`（它是唯一被允许的那一份）。
EXCLUDED_REL = frozenset({SELF_REL, PRIMITIVE_REL})

#: 「这是注入」的**语法**证据词：接收者表达式 或 所在函数名 里出现即算。
MUTATION_NAME = re.compile(r"(mutat|inject|broken|tamper|corrupt|variant|mutant|poison|sabot)", re.I)

#: 性能预筛（**不是判定**）：`str.replace` 调用必然在源码里留下 `.replace(` 字样。
#: 残余（假绿方向）见模块 docstring 边界 ②。
PREFILTER = ".replace("

sys.path.append(str(REPO_ROOT / "tests"))
from unit_ci_workflows.injection import (  # noqa: E402  （#7017：注入的唯一实现）
    AmbiguousAnchor,
    AnchorDrift,
    InjectionError,
    inject,
)


# ══════════════════════════════════════════════════════════════════════════════
# 台账读取
# ══════════════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=1)
def _ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def _anchors() -> list[dict]:
    return _ledger()["anchors"]


def _exemptions() -> list[dict]:
    return _ledger()["bare_replace_exemptions"]


# ══════════════════════════════════════════════════════════════════════════════
# ① 裸 replace 造变异体的 AST 扫描（注释 / 文案不算）
# ══════════════════════════════════════════════════════════════════════════════
class _BareReplaceScanner(ast.NodeVisitor):
    """只认 `ast.Call(func=Attribute(attr='replace'))`，并按语法证据判「是不是注入」。"""

    def __init__(self) -> None:
        self._functions: list[str] = []
        self.hits: list[tuple[int, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802（ast 协议）
        self._functions.append(node.name)
        self.generic_visit(node)
        self._functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "replace":
            receiver = ast.unparse(func.value)
            owner = self._functions[-1] if self._functions else ""
            if MUTATION_NAME.search(receiver) or MUTATION_NAME.search(owner):
                self.hits.append((node.lineno, receiver))
        self.generic_visit(node)


def scan_file(path: Path) -> list[tuple[int, str]]:
    """返回该文件里「裸 `.replace()` 造变异体」的 `[(行号, 接收者表达式)]`（已按行号排序）。"""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    scanner = _BareReplaceScanner()
    scanner.visit(tree)
    return sorted(scanner.hits)


@lru_cache(maxsize=1)
def current_sites() -> dict[str, list[tuple[int, str]]]:
    """现取扫描面：`{仓库相对路径: [(行号, 接收者)]}`（面的口径 = `UNIT_CI_DIR/*.py`）。"""
    sites: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(UNIT_CI_DIR.glob("*.py")):
        rel = f"tests/unit_ci_workflows/{path.name}"
        if rel in EXCLUDED_REL:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if PREFILTER not in text:  # 性能预筛，不是判定
            continue
        hits = scan_file(path)
        if hits:
            sites[rel] = hits
    return sites


def _inject_calls(path: Path) -> dict[str, bool]:
    """`call_site` 文件里每个 `inject(...)` 调用：`{锚点字面量: 是否传了 where=}`。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wiring: dict[str, bool] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else "")
        if name != "inject":
            continue
        has_where = any(kw.arg == "where" for kw in node.keywords)
        for arg in node.args[1:2]:  # 第 2 个位置实参 = 锚点（old）
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                wiring[arg.value] = has_where
    return wiring


# ══════════════════════════════════════════════════════════════════════════════
# ① 判据：未改用共用原语即红 + 豁免台账只许缩短
# ══════════════════════════════════════════════════════════════════════════════
def test_bare_replace_injection_sites_are_all_ledgered() -> None:
    """未登记即红：新出现的「裸 replace 造变异体」必须在 diff 里显式处置。"""
    ledgered = {entry["path"] for entry in _exemptions()}
    unledgered = [
        f"  · {path}: {len(hits)} 处 —— " + "；".join(f"L{line} `{recv[:50]}`" for line, recv in hits[:3])
        for path, hits in sorted(current_sites().items())
        if path not in ledgered
    ]
    assert unledgered == [], (
        "这些位置用**裸 `.replace()`** 造变异体（注入）⇒ 锚点漂移时 `str.replace` 会**静默返回原串**，"
        "把「注入没生效」报成「判据没牙」。出口：改用 "
        "`from unit_ci_workflows.injection import inject`（0 命中抛 AnchorDrift、不唯一抛 AmbiguousAnchor），"
        "**或**在 red_proof_anchor_ledger.json 的 bare_replace_exemptions 里显式登记为存量债务：\n"
        + "\n".join(unledgered)
    )


def test_bare_replace_ledger_is_exact_and_never_grows() -> None:
    """已有条目**只许缩短**：条数涨/跌、文件陈旧都红（与 guard_parsing_allowlist.json 同族）。"""
    entries = {entry["path"]: entry for entry in _exemptions()}
    live = current_sites()
    problems: list[str] = []

    for path, hits in sorted(live.items()):
        entry = entries.get(path)
        if entry is None:
            continue  # 由 test_bare_replace_injection_sites_are_all_ledgered 具名报出
        if entry["hits"] != len(hits):
            direction = "涨" if len(hits) > entry["hits"] else "跌"
            problems.append(
                f"  · {path}: 现取 {len(hits)} 处，台账 {entry['hits']} 处（{direction}）"
                f" ⇒ {'新增债务不许靠改台账吸收：改用 injection.inject()' if direction == '涨' else '已迁移/删掉的站点须同步销账（把 hits 改成现值）'}"
            )
    for path, entry in sorted(entries.items()):
        if path not in live:
            problems.append(
                f"  · {path}: 台账仍登记 {entry['hits']} 处，现取 **0 处**（或文件已不在面内）⇒ 陈旧条目，须销账"
            )
    assert problems == [], "豁免台账与现取站点不一致（只许缩短）：\n" + "\n".join(problems)


def test_bare_replace_ledger_entries_carry_reason_and_issue() -> None:
    """豁免必须写**理由 + 单号**；缺任一项 ⇒ 该豁免不可评审。"""
    problems = [
        f"  · {entry.get('path', '<缺 path>')}: 缺 {field}"
        for entry in _exemptions()
        for field in ("path", "reason", "issue")
        if not str(entry.get(field, "")).strip()
    ]
    problems += [f"  · hits 非正整数：{entry}" for entry in _exemptions() if not isinstance(entry.get("hits"), int) or entry["hits"] < 1]
    assert problems == [], "豁免台账条目必须含 path / hits / reason / issue：\n" + "\n".join(problems)


def test_scan_face_is_not_empty() -> None:
    """空扫描面 = 假绿（fail-closed）：面没了不该报绿。"""
    files = sorted(UNIT_CI_DIR.glob("*.py"))
    sites = current_sites()
    assert len(files) > 100, f"扫描面只剩 {len(files)} 个文件 ⇒ 路径/目录名变了（判据会静默空跑）"
    assert sites, (
        "扫描面现取 0 处裸 replace 造变异体 ⇒ 要么判据的形态词全失效、要么面取错了；"
        "**没东西可判不是通过**（先把预筛与 MUTATION_NAME 自证一遍）"
    )


def test_comment_and_prose_mentions_are_not_counted(tmp_path: Path) -> None:
    """负控：注释 / docstring / 普通（非变异）变量名里的 `.replace(` **不算**注入。"""
    sample = tmp_path / "test_sample.py"
    sample.write_text(
        '"""说明：这里曾经用 mutated.replace("A", "B") 造变异体（文档文案不算）。"""\n'
        "# 注释里的 src.replace('A', 'B') 也不算\n"
        "def test_plain():\n"
        "    text = payload.replace('A', 'B')\n"
        "    return text\n",
        encoding="utf-8",
    )
    assert scan_file(sample) == []


def test_real_mutation_shape_is_counted(tmp_path: Path) -> None:
    """正控：变异函数名 / 变异接收者里的 `.replace()` **要**被计入（判别力自证）。"""
    sample = tmp_path / "test_sample.py"
    sample.write_text(
        "def test_mutation_isd_detected():\n"
        "    mutated = src.replace('A', 'B')\n"
        "    other = injected.replace('C', 'D')\n"
        "    return mutated, other\n",
        encoding="utf-8",
    )
    assert [line for line, _ in scan_file(sample)] == [2, 3]


# ══════════════════════════════════════════════════════════════════════════════
# ② 判据：登记在案的注入锚点在**当前语料**上必须活着
# ══════════════════════════════════════════════════════════════════════════════
def test_anchor_entries_are_well_formed() -> None:
    """登记册自身可评审：必填字段 + 语料真实存在 + id 唯一 + 不是空册。"""
    anchors = _anchors()
    assert anchors, "活锚登记册为空 ⇒ ② 空跑（fail-closed）；先迁移至少一处真语料注入"

    problems: list[str] = []
    seen: set[str] = set()
    for entry in anchors:
        for field in ("id", "corpus", "anchor", "call_site", "why", "issue"):
            if not str(entry.get(field, "")).strip():
                problems.append(f"  · {entry.get('id', '<缺 id>')}: 缺 {field}")
        if entry.get("id") in seen:
            problems.append(f"  · id 重复：{entry.get('id')}")
        seen.add(entry.get("id"))
        corpus = REPO_ROOT / str(entry.get("corpus", ""))
        if not corpus.is_file():
            problems.append(f"  · {entry.get('id')}: 语料不存在 {entry.get('corpus')}")
        call_site = REPO_ROOT / str(entry.get("call_site", ""))
        if not call_site.is_file():
            problems.append(f"  · {entry.get('id')}: call_site 不存在 {entry.get('call_site')}")
    assert problems == [], "活锚登记册条目不可评审：\n" + "\n".join(problems)


def test_registered_anchors_are_alive_on_the_current_corpus() -> None:
    """② 逐条真跑：锚点必须在**当前语料**上命中一次；任一漂移 ⇒ 具名红（说清是锚点漂了）。"""
    drifted: list[str] = []
    live: list[str] = []
    for entry in _anchors():
        corpus_path = REPO_ROOT / entry["corpus"]
        if not corpus_path.is_file():
            drifted.append(f"  · {entry['id']} @ {entry['corpus']}：**语料文件不存在** ⇒ 锚点无从命中")
            continue
        try:
            inject(corpus_path.read_text(encoding="utf-8"), entry["anchor"], "", where=entry["corpus"])
        except AnchorDrift as exc:
            drifted.append(f"  · {entry['id']} @ {entry['corpus']}\n    {exc}")
        else:
            live.append(entry["id"])

    assert drifted == [], (
        f"登记在案的注入锚点里 **{len(drifted)} 个已经漂了** ⇒ 对应红证成了**空操作**："
        "这是「**锚点漂移**」，**不是**「判据没牙」（两者处置相反：改锚点 vs 补判据）。\n"
        "出口：按报错里的「同前缀仍在」行把锚点改成当前语料的样子，再复跑本判据。\n" + "\n".join(drifted)
    )
    assert len(live) == len(_anchors())


def test_registered_anchors_are_wired_through_the_shared_primitive() -> None:
    """迁移点必须真的用 `inject(..., where=...)`：否则「锚点活着」证明不了「红证还在注入」。"""
    problems: list[str] = []
    for entry in _anchors():
        call_site = REPO_ROOT / entry["call_site"]
        if not call_site.is_file():
            problems.append(f"  · {entry['id']}: call_site 不存在 {entry['call_site']}")
            continue
        wiring = _inject_calls(call_site)
        if entry["anchor"] not in wiring:
            problems.append(
                f"  · {entry['id']}: {entry['call_site']} 里没有以该锚点作第二实参的 `inject(...)` 调用"
                " ⇒ 迁移点被改回裸 replace（注入又会静默失配）"
            )
        elif not wiring[entry["anchor"]]:
            problems.append(
                f"  · {entry['id']}: 该 `inject(...)` 没传 `where=` ⇒ 漂移时会报成**匿名红**（说不出是哪个语料）"
            )
    assert problems == [], "迁移点没有接在共用注入原语上：\n" + "\n".join(problems)


# ══════════════════════════════════════════════════════════════════════════════
# ③ 判据：判别力自证（换一个空格就红，且必须报成「锚点漂移」）
# ══════════════════════════════════════════════════════════════════════════════
def test_one_space_drift_is_reported_as_anchor_drift() -> None:
    """把**真锚点**多打一个空格 ⇒ ② 那条判定的机制必红，且文案含「锚点漂移」。"""
    entry = _anchors()[0]
    corpus = (REPO_ROOT / entry["corpus"]).read_text(encoding="utf-8")

    # 反向对照：原锚点**不**抛（否则下面这份红证证明不了判别力）
    inject(corpus, entry["anchor"], "", where=entry["corpus"])

    drifted_anchor = (
        entry["anchor"].replace(" ", "  ", 1) if " " in entry["anchor"] else entry["anchor"] + " "
    )
    assert drifted_anchor != entry["anchor"], "夹具没造出漂移（锚点没变）"

    with pytest.raises(AnchorDrift) as excinfo:
        inject(corpus, drifted_anchor, "", where=entry["corpus"])
    message = str(excinfo.value)
    assert "锚点漂移" in message, f"漂移没有报成「锚点漂移」⇒ 又会被读成「判据没牙」：{message}"
    assert entry["corpus"] in message, f"漂移报文里没有语料文件名：{message}"
    # 前 60 字必须进报文（按空白折叠比对：漂移本体就是多了一个空格）
    assert entry["anchor"][:20] in re.sub(r"\s+", " ", message), f"漂移报文里没有锚点前 60 字：{message}"


# ══════════════════════════════════════════════════════════════════════════════
# 原语本体的契约（injection.py）
# ══════════════════════════════════════════════════════════════════════════════
def test_inject_never_falls_back_to_the_original_text() -> None:
    """禁止回落：0 命中**不许**返回原串（那正是缺陷形态）。"""
    with pytest.raises(AnchorDrift):
        inject("alpha\nbeta\n", "not-there", "x", where="假语料.txt")


def test_inject_default_where_still_names_the_gap() -> None:
    """不传 `where=` 时占位符要**长得像缺东西**，不能像某个真实文件名。"""
    with pytest.raises(AnchorDrift) as excinfo:
        inject("alpha", "zzz", "x")
    assert "未指明语料" in str(excinfo.value)


def test_inject_rejects_ambiguous_anchor() -> None:
    """命中 >1 次（未显式 count）⇒ `AmbiguousAnchor`；显式 count=2 ⇒ 通过；count=1 ⇒ 红。"""
    corpus = "run: a\ntarget line\nrun: a\ntarget line\n"
    with pytest.raises(AmbiguousAnchor):
        inject(corpus, "target line", "mutated line", where="假语料.yml")
    assert inject(corpus, "target line", "mutated line", count=2, where="假语料.yml").count("mutated line") == 2
    with pytest.raises(AmbiguousAnchor):
        inject(corpus, "target line", "mutated line", count=1, where="假语料.yml")


def test_inject_count_mismatch_is_an_error_not_a_partial_edit() -> None:
    """`count=N` 是「**恰好** N 次」：少一处也抛错（否则「少替换一处」会静默通过）。"""
    with pytest.raises(AmbiguousAnchor):
        inject("target line\n", "target line", "mutated line", count=2, where="假语料.yml")


def test_inject_rejects_empty_anchor_and_noop() -> None:
    """空锚点（会在每个字符间插值）与 `old == new`（空操作）都不是注入。"""
    with pytest.raises(ValueError):
        inject("abc", "", "x", where="假语料")
    with pytest.raises(InjectionError):
        inject("abc", "a", "a", where="假语料")


def test_inject_preserves_the_rest_of_the_corpus_byte_for_byte() -> None:
    """唯一的成功路径：只换锚点那一处，其余逐字节不变。"""
    corpus = "head\ntarget line\ntail\n"
    out = inject(corpus, "target line", "mutated line", where="假语料")
    assert out == "head\nmutated line\ntail\n"
