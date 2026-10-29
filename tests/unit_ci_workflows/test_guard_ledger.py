# case_ids: DF-008
"""守卫台账（`tests/guard_ledger.json`）的机器判据 —— P1-4 前半（issue #8139）。

## 这条判据守什么

审计 F4：B 端 agent 的守卫散在多份文件里，**没有一张台账**能回答「这条守卫守什么 /
它怎么才会红 / 出问题找哪个单」。本判据让「台账 ⇄ 现存守卫文件」成为**双向相等**：
**缺一条即红、多一条即红**，且逐条具名报出路径。

## 枚举口径（现取，不抄清单）

台账的 `path` 集合必须等于下面三条的并集，**每次跑判据现算一次**：

| # | 口径 | 现取命令 |
|---|---|---|
| A | 文件名匹配 `*guard*.py` 的后端测试 | `ls backend/ai-agent-service/tests/*guard*.py` |
| B | 文件名匹配 `*guard*.py` 的仓级判据 | `ls tests/unit_ci_workflows/*guard*.py` |
| C | **类级守卫提名**（文件名不含 guard，但事实上一族缺陷的门） | `CLASS_LEVEL_GUARDS` |

C 的语义是**提名必须有实体**：文件被删 ⇒ 红（不许静默从射程里消失）；
被 A/B 通配命中 ⇒ 红（不许双计）⇒ 台账**只能是这条枚举的产物**，不是手写想象。

## 为什么普通样例测试不进台账（有意，不是遗漏）

台账只收「守某类真值、会因同类缺陷变红」的守卫。把普通样例测试塞进来凑数，会让台账
退化成文件清单——那正是本单要治的病。

## 判别力自证

同一文件内用**内存里的合成台账**证明五种坏形态各自红（少一条 / 多一条 / 空话 /
owner 不合法 / entries 为空），不靠临时改文件。

## 边界（照实登记，§19.1）

- 判**形态**不判**语义**：本判据保证集合相等、文本非空且 `red_proof` 点名了具体对象、owner 可追溯；
  **判不了**某条 `guards` 写得对不对、覆盖得全不全（那要人读源码）；
- 台账只登记**测试文件**，不登记 `.github/*.py` / `scripts/*.py` 里的实现体
  （`tests/unit_ci_workflows/time_flaky_guard.py` 是被通配命中、需要显式说明的例外）；
- 本判据**不改**任何门禁的通过条件、不新增豁免。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = REPO_ROOT / "tests" / "guard_ledger.json"
LEDGER_SCHEMA = "guard-ledger/1.0"

GUARD_GLOBS = (
    "backend/ai-agent-service/tests/*guard*.py",
    "tests/unit_ci_workflows/*guard*.py",
)
CLASS_LEVEL_GUARDS = (
    "backend/ai-agent-service/tests/test_capability_boundary.py",
    "tests/unit_ci_workflows/test_craft_calc_config_contract.py",
    # 2026-10-29（集成侧纠偏）：任务点名的这条**确实存在**于 origin/main
    # （`git cat-file -e origin/main:tests/agent_eval/test_craft_calc_config_restore.py` ⇒ 存在），
    # 原报告"不存在"是误判 ⇒ 补进类级提名（否则"登记 = 枚举产物"会漏掉一整类：复位契约）。
    "tests/agent_eval/test_craft_calc_config_restore.py",
)
REQUIRED_FIELDS = ("path", "guards", "red_proof", "owner")
MIN_TEXT = 10
OWNER_PATTERN = re.compile(r"^(?:#\d+|N/A（.+）)$")
# red_proof 只写「会判红」不算登记：必须**点名具体对象**（文件路径 / 测试名 / 符号名），
# 否则「同类缺陷出现时它会红」这种空话也能过（红证的价值在于可复算，不在措辞）。
TARGET_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_.*/-]{3,}")


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def enumerate_guard_files() -> set[str]:
    """现取口径 A ∪ B（通配一次，不读任何清单）。"""
    found: set[str] = set()
    for pattern in GUARD_GLOBS:
        directory, name = pattern.rsplit("/", 1)
        for path in (REPO_ROOT / directory).glob(name):
            if path.is_file():
                found.add(_rel(path))
    return found


def expected_paths() -> set[str]:
    return enumerate_guard_files() | set(CLASS_LEVEL_GUARDS)


def read_ledger_entries() -> list:
    """读台账；缺失 / 损坏 / schema 不对都算红（删台账不能变绿）。"""
    assert LEDGER_PATH.is_file(), f"台账不存在：{_rel(LEDGER_PATH)}（删台账不能变绿）"
    data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "台账顶层必须是对象"
    assert data.get("schema") == LEDGER_SCHEMA, (
        f"schema 必须是 {LEDGER_SCHEMA}，实际 {data.get('schema')!r}")
    return data.get("entries")


def ledger_problems(entries, expected: set[str]) -> list[str]:
    """纯函数：给定任意条目与期望路径集，返回**全部**问题（逐条具名）。

    独立于磁盘上的台账 ⇒ 同一份判定逻辑既能判真台账，也能判合成台账（判别力自证）。
    """
    if not isinstance(entries, list) or not entries:
        return ["台账 entries 为空（fail-closed：清空台账不能消红）"]

    problems: list[str] = []
    paths: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"entries[{index}] 不是对象：{entry!r}")
            continue
        missing = [field for field in REQUIRED_FIELDS if field not in entry]
        if missing:
            problems.append(f"entries[{index}] 缺字段 {missing}")
            continue
        path = entry["path"]
        paths.append(path if isinstance(path, str) else repr(path))
        for field in ("guards", "red_proof"):
            text = entry[field]
            if not isinstance(text, str) or len(text.strip()) < MIN_TEXT:
                problems.append(
                    f"{path} 的 {field} 太短（<{MIN_TEXT} 字：空话不算登记）")
        red_proof = entry["red_proof"]
        if isinstance(red_proof, str):
            if "红" not in red_proof:
                problems.append(f"{path} 的 red_proof 没说要怎么变红")
            if not TARGET_PATTERN.search(red_proof):
                problems.append(
                    f"{path} 的 red_proof 没点名具体对象（文件 / 测试名 / 符号："
                    "只说「会判红」不算登记）")
        owner = entry["owner"]
        if not isinstance(owner, str) or not OWNER_PATTERN.match(owner.strip()):
            problems.append(
                f"{path} 的 owner 不可追溯：{owner!r}（应为 #NNNN 或 N/A（理由））")

    for path, count in sorted(Counter(paths).items()):
        if count > 1:
            problems.append(f"台账有重复 path（{count} 次）：{path}")
    for path in sorted(expected - set(paths)):
        problems.append(f"漏登记：{path}（枚举到了，台账里没有）")
    for path in sorted(set(paths) - expected):
        problems.append(
            f"多登记：{path}（台账里有，枚举不到——改名 / 删除后必须同步台账）")
    return problems


def test_ledger_matches_the_live_enumeration():
    problems = ledger_problems(read_ledger_entries(), expected_paths())
    assert not problems, "守卫台账与枚举不一致：\n" + "\n".join(
        f"  - {problem}" for problem in problems)


def test_enumeration_is_not_vacuous_and_follows_the_glob():
    found = enumerate_guard_files()
    assert found, "枚举面为空：口径坏了（不是「没有守卫」）"
    for path in sorted(found):
        assert path.endswith(".py"), f"{path} 不是 Python 文件，通配口径已漂移"
        assert "guard" in Path(path).name, f"{path} 不是 *guard*.py，通配口径已漂移"


def test_class_level_nominations_are_alive_and_not_double_counted():
    globbed = enumerate_guard_files()
    for path in CLASS_LEVEL_GUARDS:
        assert (REPO_ROOT / path).is_file(), (
            f"类级守卫提名所指的文件不存在：{path}（删文件必须同时改台账与提名，不许静默出射程）")
        assert path not in globbed, f"类级守卫提名被通配口径命中，会双计：{path}"


def test_every_ledger_path_is_repo_relative_and_on_disk():
    for entry in read_ledger_entries():
        path = entry["path"]
        assert not path.startswith("/"), f"台账 path 必须是仓库相对路径：{path}"
        assert ".." not in Path(path).parts, f"台账 path 不许跳出仓库：{path}"
        assert (REPO_ROOT / path).is_file(), f"台账登记的守卫文件不存在：{path}"


def test_judge_has_discriminating_power():
    """同一份判定逻辑 + 五种内存坏台账 ⇒ 各自必须红（不靠临时改文件）。"""
    good = read_ledger_entries()
    expected = expected_paths()
    assert ledger_problems(good, expected) == [], "正控：真台账本身不该被判有问题"

    dropped_path = good[0]["path"]
    missing = ledger_problems(good[1:], expected)
    assert any("漏登记" in p and dropped_path in p for p in missing), (
        f"删掉一条（{dropped_path}）后没有具名报「漏登记」：{missing}")

    ghost = "tests/unit_ci_workflows/test_ghost_guard.py"
    extra = ledger_problems(
        good + [{"path": ghost, "guards": "凭空造的一条守卫，磁盘上并不存在",
                 "red_proof": "把它删掉就会红", "owner": "#8139"}], expected)
    assert any("多登记" in p and ghost in p for p in extra), (
        f"多一条后没有具名报「多登记」：{extra}")

    empty = ledger_problems([], expected)
    assert any("entries 为空" in p for p in empty), f"空台账没有被判红：{empty}"

    hollow = ledger_problems(
        [{"path": good[0]["path"], "guards": "会判红", "red_proof": "会判红",
          "owner": "#8139"}], {good[0]["path"]})
    assert any("太短" in p for p in hollow), f"空话条目没有被判红：{hollow}"

    vague = ledger_problems(
        [{"path": good[0]["path"], "guards": "守某个值（够长但不具体）",
          "red_proof": "同类缺陷出现的时候它就会判红，红得很确定", "owner": "#8139"}],
        {good[0]["path"]})
    assert any("没点名具体对象" in p for p in vague), (
        f"只写「会判红」的 red_proof 没有被判红：{vague}")

    bad_owner = ledger_problems(
        [{"path": good[0]["path"], "guards": "守某个值（够长但不具体）",
          "red_proof": "把它删掉就会红", "owner": "小明"}], {good[0]["path"]})
    assert any("owner 不可追溯" in p for p in bad_owner), (
        f"owner 不合法没有被判红：{bad_owner}")
