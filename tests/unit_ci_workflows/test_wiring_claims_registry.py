# case_ids: MC-051
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, NoReturn

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = Path(__file__).resolve().parent / "wiring_claims_ledger.json"
SKILL_REL = ".agent-presets/migao/skills/migao-dev-flow/SKILL.md"
SELF_REL = "tests/unit_ci_workflows/test_wiring_claims_registry.py"
WIRING_DIR = Path(__file__).resolve().parent

# 🔴 声明常量必须**排在模块 docstring 之前，且是本文件里第一个「常量名 = 双引号值」的出现处**
# —— docstring / 表格里**逐字引用**这个形态时会把「首个命中」抢走 ⇒ 声明锚会被读成占位符。
# 实测：本文件初稿即被自己的说明文字抢走（正是 §28 本条要治的同族形态）。
# 本守卫**自己**就是「测接线」的那一族 ⇒ 它必须自己先过自己的判据（台账里有一条自指 `claims`）。
WIRING_UNDER_TEST = "tests/unit_ci_workflows/conftest.py::helper_leg_shape_problems"
#: 台账 `claims[].declared_in` 用它区分「本守卫自己的接线声明」与「别的接线声明」。
SELF_ANCHOR = f"{SELF_REL}::{WIRING_UNDER_TEST}"

#: 台账 ⇄ 声明文本的**唯一**形态（判据 2 与「真语料上的双向自证」都用它 ⇒ 两半同源）。
#: 声明**必须**带尾随下划线：正确的 `WIRING_UNDER_TEST` 与占位符 / 别的名字**静态可区分**。
DECL_RE = re.compile(r'WIRING_UNDER_TEST\s*=\s*"([^"]+)"')
MARKER_RE = re.compile(r"\bWIRING_UNDER_TEST\b")

"""「判据本体绿 ≠ 接线在」的**规范承载体**（issue #5814；规范 = `migao-dev-flow` §28.2）。

## 病（PR #5829 的实例，逐字）

`#5825`（CI 削峰，已合并）把 `pytest_sessionfinish` 收口钩子**整个丢掉**，而 **5 条判据文件照样全绿**
—— 因为**判据本体被测到了、消费点 / 接线没人测** ⇒ 落进 main。后果：收集面**下一档**
（某天少收集一批判据）**没有任何东西会报**，「变快」可能是「少跑」而 required 照旧绿。
**理由逐字**：**判据绿只是「判据函数被调用过」，不代表「它接在真流程上」。**

## 本守卫守什么（能机械化的那一半）

**凡测试文件显式声明自己守某个接线**（模块级常量，名字带尾随下划线、值为 `<仓库相对路径>::<符号>`）
⇒ 必须登记进台账 `tests/unit_ci_workflows/wiring_claims_ledger.json`，且：

| # | 判据 | 红证 |
|---|---|---|
| 1 | **未登记即红** | 文件里有声明标记、台账里没有对应条目 ⇒ 具名报出该文件 |
| 2 | **台账未被兑现即红** | 台账每条必须能在它声称的文件里逐字找到同一句声明 |
| 3 | **声明必须指名真对象** | `::` 左边是仓内**存在**的 `.py` 文件、右边在该文件里**逐字出现**（**摘线注入点**：删掉 / 改名 ⇒ 红） |
| 4 | **fail-closed** | 台账 `claims` 为空 ⇒ 红（清空台账不得把守卫变成空跑） |
| 5 | **声明 ⇄ 台账双向** | 台账的锚值必须等于它声称的文件里那个常量的**现取值**（改声明不改台账 / 改台账不改声明 ⇒ 红） |
| 6 | 每条必须写下 `case_ids`（用例面关联） | 新增登记却不声明用例 ⇒ 红 |
| 7 | **判别力自证** | 六种坏形态在内存里各自判红；真语料上的双向自证见 `test_mutating_the_real_wiring_anchor_turns_it_red` |
| 8 | **只改注释 ⇒ 不红**（对照） | 守卫被自己的文案喂红 ⇒ 红 |

## 边界（照实登记；另见台账 `coverage_boundary`）

- 只保证「**声明了的**接线锚真实存在」；**不保证**「那段代码真的跑在真 session / 真入口上」
  （本仓没有通用 harness 驱动每个消费点）⇒ **行为面**的直连红证仍是**作者的一次动作**
  （PR #5829 的形态：短库存 ⇒ `returncode=1` 且打印归因；xdist 控制器 ⇒ 早退不抛），读数进 PR body。
- **完全没写声明标记**的测接线文件在面外（「文件没声明」与「确实没测接线」静态不可区分）。
- 判据**刻意不跑**被引用的那条测试（跑它 = 把「未登记即红」退化成「全量套件再跑一遍」，§27 要治的机器重活）。
- 红线：**注入只改内存里的字符串**，不改仓内文件（不写盘 ⇒ 判据之间零互相污染）。
"""


# ── 判定本体（纯函数：吃文本 + 读盘器，红证可在内存里构造坏形态）────────────────────

def declaration_anchor(anchor: str) -> str:
    """台账里的锚 → 它在测试文件里应当出现的那**一句**声明文本。"""
    return f'WIRING_UNDER_TEST = "{anchor}"'


def _raise(message: str) -> "NoReturn":
    """等强度的 fail-closed 出口：**不用** `assert x is not None` 那一族弱断言形态。

    §23.4 T1 实证：那种形态会被 CI 的弱断言扫描判红（等强度、不降门禁）。
    """
    raise AssertionError(message)


def _mentions(text: str, symbol: str) -> bool:
    """`symbol` 是否在 `text` 里**作为独立标识符**出现（不是裸子串）。

    裸子串会让「改名成 `zzz_removed_<符号>`」这种最自然的摘线注入**照样命中** ⇒ 判据变空断言。
    ⚠️ 边界必须把 `_` 也算进来（`\\b` **不行**：`_` 是非词字符 ⇒ `removed_<符号>` 里的 `\\b` 仍成立
    —— 本仓实测过这一形态）⇒ 用「前邻不是 `[A-Za-z0-9_]`」的 lookaround。
    符号里含非标识符字符（文本锚可能有）⇒ 退回裸子串包含，并如实登记在 `coverage_boundary`。
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol):
        return symbol in text
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def _problems(*, ledger: dict,
              units: dict[str, str],
              read_text: Callable[[str], str | None],
              ) -> list[str]:
    """全部违规（空列表 = 全绿）。`units` = 仓内测试文件的现取文本（用于判「未登记即红」）。"""
    bad: list[str] = []
    claims = ledger.get("claims")

    if not isinstance(claims, list):
        return ["台账 `claims` 不是列表 ⇒ 未登记即红的另一半无从判定（fail-closed）"]
    if not claims:
        bad.append("台账 `claims` 为空 ⇒ 守卫会变成空跑（清空台账不得消红，fail-closed）")

    # ── 判据 1：文件里有声明标记 ⇒ 台账必须有对应条目 ──────────────────────────────
    registered_decls = {c.get("declared_in") for c in claims if isinstance(c, dict)}
    for rel, text in sorted(units.items()):
        if not MARKER_RE.search(text):
            continue
        if rel not in registered_decls:
            bad.append(
                f"{rel}：文件里出现了接线声明标记 `WIRING_UNDER_TEST`，而台账 `claims` 里**没有**"
                f"对应条目 ⇒ 未登记即红（出口：登记进 {LEDGER_PATH.name}，写清被守的接线锚）"
            )

    # ── 判据 2~6：台账逐条兑现 ────────────────────────────────────────────────────
    seen: set[str] = set()
    for i, c in enumerate(claims):
        if not isinstance(c, dict):
            bad.append(f"claims[{i}] 不是对象 ⇒ 台账填不了这份账")
            continue
        declared_in = c.get("declared_in")
        anchor = c.get("wiring")
        where = f"claims[{i}]" + (f"（{declared_in}）" if declared_in else "")
        if not declared_in or not isinstance(declared_in, str):
            bad.append(f"{where}：缺 `declared_in`（哪份测试文件在声明）⇒ 无从兑现")
            continue
        if not anchor or not isinstance(anchor, str):
            bad.append(f"{where}：缺 `wiring`（被守的接线锚 `<仓库相对路径>::<符号>`）")
            continue

        # 判据 2：台账给不存在的声明盖章 ⇒ 红（录的是**声明**，不是闸门名）
        file_text = read_text(declared_in)
        if file_text is None:
            bad.append(f"{where}：`declared_in` 指的文件不存在：{declared_in}")
        else:
            if declaration_anchor(anchor) not in file_text:
                bad.append(
                    f"{where}：`{declared_in}` 里**找不到**这句声明 {declaration_anchor(anchor)!r}"
                    f" ⇒ 台账给不存在的声明盖章（改锚必须同批改台账）"
                )
            # 判据 5：声明 ⇄ 台账**双向**（台账值必须等于该文件里那个常量的现取值）
            found = DECL_RE.search(file_text)
            if found and found.group(1) != anchor:
                bad.append(
                    f"{where}：声明与台账**不是同一个锚** —— 文件里现取 {found.group(1)!r}、"
                    f"台账写 {anchor!r} ⇒ 改了一边没改另一边"
                )

        # 判据 3：声明必须指名真对象（左边真文件 + 右边逐字出现 + `.py` 后缀）
        if "::" not in anchor:
            bad.append(f"{where}：`wiring` 必须是 `<仓库相对路径>::<符号>`，现取 {anchor!r}")
        else:
            path_rel, symbol = anchor.split("::", 1)
            if not path_rel.endswith(".py"):
                bad.append(
                    f"{where}：`wiring` 左边必须以 `.py` 结尾（避免与「裸文件名 + 冒号 + 行号」的"
                    f"既有禁令混淆），现取 {path_rel!r}"
                )
            elif read_text(path_rel) is None:
                bad.append(f"{where}：`wiring` 左指的文件不在仓内：{path_rel} ⇒ 接线锚指向不存在的对象")
            elif not symbol.strip():
                bad.append(f"{where}：`wiring` 右边（被守的符号 / 可检索文本锚）为空")
            else:
                target = read_text(path_rel) or ""
                # ⚠️ **词边界**匹配（不是裸子串）：否则「改名成 `zzz_removed_<符号>`」这种最自然的
                # 摘线注入**照样命中**（新名字里含旧名字）⇒ 判据 3 变成空断言。本仓实测过这一形态。
                if not _mentions(target, symbol):
                    bad.append(
                        f"{where}：接线锚 {anchor!r} 在 {path_rel} 里**不存在**"
                        f" ⇒ 接线被删 / 改名（这就是「摘掉接线」的注入点）"
                    )

        # 判据 6：用例面关联
        if not c.get("case_ids"):
            bad.append(f"{where}：缺 `case_ids`（登记必须能追到用例）")

        # 判据 1 的反向：同一接线不许两条同文件同锚的重复登记（重复 = 台账腐烂的起点）
        key = f"{declared_in}::{anchor}"
        if key in seen:
            bad.append(f"{where}：重复登记（同文件同锚已有一条）：{key}")
        seen.add(key)

    return bad


def load_ledger(path: Path = LEDGER_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def corpus() -> dict[str, str]:
    """现取仓内 `tests/unit_ci_workflows/**/*.py` 的文本（判「未登记即红」的语料）。"""
    out: dict[str, str] = {}
    for p in sorted(WIRING_DIR.rglob("*.py")):
        rel = p.resolve().relative_to(REPO_ROOT).as_posix()
        out[rel] = p.read_text(encoding="utf-8")
    return out


def repo_read_text(rel: str) -> str | None:
    p = (REPO_ROOT / rel)
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _live() -> tuple[dict, dict[str, str]]:
    led = load_ledger()
    if not isinstance(led, dict):
        raise AssertionError(f"台账不是对象：{LEDGER_PATH}")
    return led, corpus()


# ── 真语料：守卫自身必须绿 ─────────────────────────────────────────────────────

def test_real_corpus_is_clean() -> None:
    """真语料（现取）⇒ 零违规。这条绿 = 台账与声明当下是一致的。"""
    led, units = _live()
    bad = _problems(ledger=led, units=units, read_text=repo_read_text)
    assert bad == [], "接线声明台账违规：\n  - " + "\n  - ".join(bad)


def test_self_anchor_is_registered_and_truthful() -> None:
    """本守卫自己必须先过自己的判据：台账里的**自指条目**恰好指向本文件的活声明。"""
    led, _ = _live()
    hits = [c for c in led["claims"] if c.get("declared_in") == SELF_REL]
    assert len(hits) == 1, f"本守卫自己的登记必须恰好一条，现取 {len(hits)} 条"
    assert hits[0].get("wiring") == WIRING_UNDER_TEST, (
        "台账自指条目的 `wiring` 必须等于本文件的 WIRING_UNDER_TEST 常量值"
    )
    assert SELF_ANCHOR == f"{SELF_REL}::{WIRING_UNDER_TEST}"
    assert declaration_anchor(WIRING_UNDER_TEST) in Path(__file__).read_text(encoding="utf-8"), (
        "本文件里必须逐字有那句声明（否则台账在给一个不存在的声明盖章）"
    )


def test_declaration_is_not_shadowed_by_the_docstring() -> None:
    """**文件内**的秩序判据：第一个声明必须是**活常量那行**，不能是 docstring 里的占位符引用。

    红证 = 本文件初稿的真实形态：docstring 里逐字写了「常量名 = 值」的说明文字，
    于是 `DECL_RE` 的首次命中落在说明文字上、声明锚被读成占位符 —— 这正是 §28 本条要治的同族形态。
    """
    rel = "tests/unit_ci_workflows/test_wiring_claims_registry.py"
    text = repo_read_text(rel)
    if text is None:
        _raise(f"本文件不在仓内：{rel}")
    found = DECL_RE.search(text)
    if found is None:
        _raise("本文件里必须有声明常量（否则整条守卫没有被测对象）")
    assert found.group(1) == WIRING_UNDER_TEST, (
        f"第一个 `WIRING_UNDER_TEST = \"…\"` 的命中不是活常量（现取 {found.group(1)!r}）"
        f" ⇒ 声明被自己的说明文字抢走"
    )
    assert text.index("WIRING_UNDER_TEST = ") < text.index('"""'), (
        "声明常量必须排在模块 docstring **之前**（否则 docstring 里的引用会抢走首次命中）"
    )


def test_ledger_names_the_skill_section_that_carries_the_rule() -> None:
    """台账必须指到**承载体**（技能 §28）—— 规则正文与台账是两半，缺一条就是「只写了劝告」。"""
    led, _ = _live()
    skill = led.get("skill") or {}
    assert skill.get("path") == SKILL_REL, f"台账 skill.path 必须指向 {SKILL_REL}"
    heading = skill.get("section")
    assert isinstance(heading, str) and heading.strip(), "台账 skill.section 必须写下节标题（可检索）"
    text = repo_read_text(SKILL_REL)
    if text is None:
        _raise(f"技能文件不在仓内：{SKILL_REL}")
    assert heading in text, f"技能里找不到台账声称的节标题：{heading!r} ⇒ 台账给不存在的承载体盖章"


def test_coverage_boundary_is_registered_with_recompute() -> None:
    """覆盖面登记必须**在册且可复算**（每条 face + reason + recompute）—— 不许「无边界」的声称。"""
    led, _ = _live()
    entries = led.get("coverage_boundary")
    assert isinstance(entries, list) and entries, "台账必须有 `coverage_boundary`（空 = 声称覆盖一切）"
    for i, e in enumerate(entries):
        for key in ("face", "reason", "recompute", "status"):
            val = (e or {}).get(key)
            assert isinstance(val, str) and val.strip(), f"coverage_boundary[{i}] 缺 `{key}`"


# ── 红证（注入式；全部在内存里构造，不写盘）──────────────────────────────────────

def _base() -> tuple[dict, dict[str, str]]:
    return _live()


def test_injection_unregistered_declaration_turns_it_red() -> None:
    """红证 1（未登记即红）：语料里多一份带声明标记的文件、台账不认它 ⇒ 必红。"""
    led, units = _base()
    units = dict(units)
    units["tests/unit_ci_workflows/test_zzz_injected.py"] = (
        '# case_ids: MC-051\nWIRING_UNDER_TEST = "tests/unit_ci_workflows/conftest.py::x"\n'
    )
    bad = _problems(ledger=led, units=units, read_text=repo_read_text)
    assert any("test_zzz_injected.py" in b and "未登记即红" in b for b in bad), bad


def test_injection_ledger_stamps_a_nonexistent_declaration_turns_it_red() -> None:
    """红证 2（台账未被兑现即红）：台账换一个本文件里没有的锚 ⇒ 判据 2 必红。"""
    led, units = _base()
    led = json.loads(json.dumps(led))
    led["claims"][0]["wiring"] = "tests/unit_ci_workflows/conftest.py::pytest_zzz_nonexistent"
    bad = _problems(ledger=led, units=units, read_text=repo_read_text)
    assert any("找不到" in b and "声明" in b for b in bad), bad


def test_injection_removed_wiring_anchor_turns_it_red() -> None:
    """红证 3（摘掉接线 ⇒ 必红）：锚右边在目标文件里不存在 ⇒ 判据 3 必红。"""
    led, units = _base()
    led = json.loads(json.dumps(led))
    led["claims"][0]["declared_in"] = SELF_REL
    led["claims"][0]["wiring"] = "tests/unit_ci_workflows/conftest.py::pytest_zzz_removed_hook"
    units = dict(units)
    units[SELF_REL] = units[SELF_REL].replace(
        declaration_anchor(WIRING_UNDER_TEST),
        declaration_anchor("tests/unit_ci_workflows/conftest.py::pytest_zzz_removed_hook"),
    )
    bad = _problems(ledger=led, units=units, read_text=repo_read_text)
    assert any("接线被删 / 改名" in b for b in bad), bad


def test_injection_emptied_ledger_turns_it_red() -> None:
    """红证 4（fail-closed）：把 `claims` 清空「消红」⇒ 必红。"""
    led, units = _base()
    led = json.loads(json.dumps(led))
    led["claims"] = []
    bad = _problems(ledger=led, units=units, read_text=repo_read_text)
    assert any("变成空跑" in b for b in bad), bad


def test_injection_missing_case_ids_turns_it_red() -> None:
    """红证 5：登记不写 `case_ids` ⇒ 必红（登记必须能追到用例面）。"""
    led, units = _base()
    led = json.loads(json.dumps(led))
    led["claims"][0].pop("case_ids", None)
    bad = _problems(ledger=led, units=units, read_text=repo_read_text)
    assert any("case_ids" in b for b in bad), bad


def test_injection_one_sided_anchor_change_turns_it_red() -> None:
    """红证 6（声明 ⇄ 台账双向）：只改声明不改台账（或反过来）⇒ 判据 5 必红。"""
    led, units = _base()
    led = json.loads(json.dumps(led))
    led["claims"][0]["wiring"] = "tests/unit_ci_workflows/conftest.py::pytest_sessionfinish2"
    bad = _problems(ledger=led, units=units, read_text=repo_read_text)
    assert any("不是同一个锚" in b or "找不到" in b for b in bad), bad


def test_counterexample_comment_only_declaration_does_not_turn_red() -> None:
    """**对照读数**（判据 8）：只把该名字写成注释里的一句说明（不是声明）⇒ **不红**。

    红证与对照必须成对：只有「会红」的守卫会把任何提及该名字的文本都判红（那是被自己的文案喂红，§17.3）。
    """
    led, units = _base()
    units = dict(units)
    found = units["tests/unit_ci_workflows/test_zzz_comment_only.py"] = (
        "# case_ids: MC-051\n# 这里只**说明**那个声明常量的形态（说明文字，不是声明本身）\n"
        "# 常量名带尾随下划线与模块级赋值形态，如实登记后被守卫认账\n"
    )
    assert MARKER_RE.search(found) is None, (
        "对照不合格：这一段里不得出现那个声明标记的名字（守卫按名字判「有没有测接线」）"
    )
    bad = _problems(ledger=led, units=dict(units), read_text=repo_read_text)
    assert not any("test_zzz_comment_only.py" in b for b in bad), bad


def test_mutating_the_real_wiring_anchor_turns_it_red() -> None:
    """**真语料上的双向自证**（不写盘）：对**真** `conftest.py` 的文本摘掉被守的接线行 ⇒ 判据 3 报出该锚。

    这是「摘掉接线 ⇒ 必须红」的实测形态：只改**内存**副本（红线：注入不落盘 ⇒ 判据之间零互相污染）。
    """
    led, units = _base()
    # ⚠️ 这里的锚**拆成两行拼接**：本文件里不得逐字出现完整的 `<路径>::<被守符号>`，
    # 否则下面那句 `replace` 会把它自己那块字符串也改名 ⇒ 报错文本里拼不回原锚（假红）。
    default_anchor = ("tests/unit_ci_workflows/conftest.py::"
                      "helper_leg_shape_problems")
    real = repo_read_text("tests/unit_ci_workflows/conftest.py")
    if real is None:
        _raise("真语料取不到 ⇒ 本自证无从判定（fail-closed）")
    symbol = default_anchor.split("::", 1)[1]
    assert f"def {symbol}" in real, (
        "被守的接线本体不在 conftest.py 里 ⇒ 台账声称的对象与实际不符（先修台账或先接线）"
    )
    # ⚠️ `replace` **不带 count**：本文件里那个符号其实出现在**两处**（`def <符号>` 与
    # 台账消费点常量 `CONSUMPTION_MARKER = "<符号>"`）⇒ 只替换 def 会让守卫**照样命中**那个字符串
    # ⇒ 注入无效、判据变空断言。这是「摘线注入先自证生效」的现场形态（§23 G 族）。
    mutated = real.replace(symbol, f"zzz_removed_{symbol}")
    assert mutated != real, "变异没生效 ⇒ 下面那条断言会变成空断言（§28.1 的同族形态）"
    assert not _mentions(mutated, symbol), "变异没清干净（符号仍逐字在）⇒ 判据 3 无从判红"

    def read_with_mutation(rel: str) -> str | None:
        if rel == "tests/unit_ci_workflows/conftest.py":
            return mutated
        return repo_read_text(rel)

    bad = _problems(ledger=led, units=units, read_text=read_with_mutation)
    assert any(symbol in b and "接线被删" in b for b in bad), (
        "摘掉真接线后守卫没有报出该锚 ⇒ 判据 3 是无判别力的空断言：\n  - " + "\n  - ".join(bad)
    )
    # 反向：不注入 ⇒ 不报（否则上一条可能是「恒定红」而不是「因注入而红」）
    clean = _problems(ledger=led, units=units, read_text=repo_read_text)
    assert not any("接线被删 / 改名" in b for b in clean), clean
