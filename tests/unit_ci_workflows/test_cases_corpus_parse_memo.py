# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 tests/unit_ci_workflows/test_merge_gate.py / tests/unit_ci_workflows/test_pg_orphan_sweep.py
#   的同款声明与 `.github/cases/misc.yml` 的登记。本 PR 不新建用例族。）
"""用例库**全量解析**的内容级缓存 —— 防回退守卫（issue #5301 判据①的固化件）。

## 病灶（#5301 实测，不是估算）

`render_cases.load_case_dicts()` 每次调用都把 `.github/cases/**`（25 文件 / ~1.9MB）整体解析一遍
（本机 ~160ms/次），而 `tests/unit_ci_workflows/**` 有 75 处调用点、其中不少是**每个测试各调一次**。
插桩实测（5 个文件 / 262 个用例）：**102 次调用 / 累计 152.6s** —— 而那份语料在同一个进程里
**一个字节都没变**。这正是 `ci workflow helper unit tests`（required）余量被吃光的机制之一：
「不会有人因为多解析一次而变红」⇒ 它只会**单向增长**。

## 本文件固化什么（**不是挂钟时长**）

| # | 判据（结构性 / 相对读数，禁绝对秒数与绝对次数） | 判据红了说明什么 |
|---|---|---|
| ① | 同一内容**重复加载 ⇒ 真解析 0 次**（数的是底层 `yaml_light.load_file` 被调次数，与缓存自己的计数器无关 ⇒ 判据不许自证） | 缓存失效/被摘掉 ⇒ 每次加载又各解析一遍 |
| ② | 缓存结果与**现场重新解析**逐值相同 | 缓存开始供出与磁盘不一致的内容 |
| ③ | 内容改了 ⇒ **必须重新解析**（临时语料里改一个 `id` 标量） | 缓存键退化成路径/时间戳 ⇒ 供出过期结论 |
| ④ | 调用方的原地改写**污染不了**缓存主副本 | 「省掉深拷贝」这类改动把跨调用共享对象悄悄引进套件 |
| ⑤ | **把机制注回 ⇒ 判据①的谓词必假**（直连补丁前的原函数） | 判据①是空断言（怎么都不会红） |
| ⑥ | 第二条入口 `case_trust_gate.load_cases_from_dir()` 走**同一份**缓存 | 只装一半（另一条入口又各自解析一遍） |

判据①的口径：**相对**（"重复 3 次 ⇒ 0 次真解析"），**不写死**绝对次数/秒数 —— 语料长大、
调用点变多都不会让它腐烂；只有"重复解析又回来了"才会红。

## 红证孔（默认关闭）

`MIGAO_NO_CORPUS_MEMO=1` ⇒ `conftest.install_corpus_memo()` 有意不装（口径同
`tests/unit_ci_workflows/pg_cluster.py` 的 `MIGAO_PG_BIN_DIRS`：**生产/CI 默认一字不变**，
出货孔只为让「把机制注回 ⇒ 必红」可复算）：

```
$ MIGAO_NO_CORPUS_MEMO=1 python3 -m pytest tests/unit_ci_workflows/test_cases_corpus_parse_memo.py -q
FAILED ...::test_memo_is_installed_on_the_single_corpus_loader
FAILED ...::test_repeated_loads_of_unchanged_corpus_do_no_real_parsing
（逐字读数见 PR body）
```
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

import render_cases  # noqa: E402
import yaml_light  # noqa: E402

from unit_ci_workflows import conftest  # noqa: E402

CASES = REPO_ROOT / ".github" / "cases"
GATE = REPO_ROOT / ".github" / "case_trust_gate.py"
PROBE = "PROBE-5301-MEMO"


def _count_real_parses(monkeypatch, load, calls: int) -> int:
    """跑 `calls` 次 `load()`，返回**底层真解析次数**（`yaml_light.load_file` 被调用次数）。

    数底层而不是数缓存自己的计数器：判据不该由被测对象自己汇报（否则"缓存说自己命中了"
    就足以让它变绿）。
    """
    counted = {"n": 0}
    original = yaml_light.load_file

    def counting_load_file(path):
        counted["n"] += 1
        return original(path)

    monkeypatch.setattr(yaml_light, "load_file", counting_load_file)
    for _ in range(calls):
        load()
    return counted["n"]


def _repeated_loads_do_no_real_parsing(monkeypatch, load, calls: int = 3) -> bool:
    """**判据①的谓词本体**（两个臂共用同一份：装了缓存 / 把机制注回）。"""
    load()                                     # 预热：本次会话内该内容必然已被解析过
    return _count_real_parses(monkeypatch, load, calls) == 0


def _gate_module():
    """按路径加载门禁模块（它是脚本不是包）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("case_trust_gate_memo_probe", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ids(cases) -> set[str]:
    return {str(c.get("id")) for c in cases}


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据①②④：同一内容只解析一次 / 值与新鲜解析相同 / 调用方改不动缓存
# ══════════════════════════════════════════════════════════════════════════════════════

def test_memo_is_installed_on_the_single_corpus_loader():
    """判据（fail-closed，**不 skip**）：缓存必须真的装在用例语料装载器上。"""
    state = conftest.corpus_memo_state()
    assert state["installed"] is True, (
        f"用例语料的内容级缓存没装上（issue #5301）⇒ 同一份语料又会被重复解析：{state['reason']}")
    assert render_cases.load_case_dicts is not conftest.corpus_loader_uncached(), (
        "`render_cases.load_case_dicts` 仍是补丁前的原函数 ⇒ 缓存根本没生效（装了个空壳）")


def test_repeated_loads_of_unchanged_corpus_do_no_real_parsing(monkeypatch):
    """判据①：内容没变时**重复加载 ⇒ 真解析 0 次**（相对口径，不写死次数/秒数）。"""
    load = render_cases.load_case_dicts
    assert _repeated_loads_do_no_real_parsing(monkeypatch, lambda: load(CASES)) is True, (
        "同一份内容重复加载又在重复真解析 ⇒ 缓存失效或被摘掉（issue #5301 判据①）；"
        f"当前状态：{conftest.corpus_memo_state()}")


def test_cached_result_is_value_identical_to_a_fresh_parse():
    """判据②：缓存命中拿到的必须与**现场重新解析**逐值相同（否则缓存会改语义）。"""
    fresh = conftest.corpus_loader_uncached()(CASES)
    cached = render_cases.load_case_dicts(CASES)
    assert cached == fresh, "缓存供出的用例与现场解析不一致 ⇒ 缓存键/拷贝口径错了（#5301）"
    assert _ids(cached) == _ids(fresh), "用例 id 集合不一致 ⇒ 缓存漏了或多了用例"


def test_caller_mutation_cannot_pollute_the_cache():
    """判据④：调用方原地改写拿到的那份 ⇒ **不得**影响后续加载（对象互不共享）。"""
    first = render_cases.load_case_dicts(CASES)
    first[0].setdefault("user_inputs", []).append(PROBE)
    second = render_cases.load_case_dicts(CASES)
    assert PROBE not in second[0].get("user_inputs", []), (
        "调用方的原地改写漏进了共享缓存主副本 ⇒ 后面所有测试都会读到被污染的对象（#5301 判据④）")


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据③：内容变了必须重新解析（键=内容 ⇒ 不可能供出过期结论）
# ══════════════════════════════════════════════════════════════════════════════════════

def test_changed_content_is_never_served_from_cache(tmp_path):
    """判据③：临时语料里改一个 `id` 标量 ⇒ 下一次加载**必须**看到新内容。"""
    corpus = tmp_path / "cases"
    corpus.mkdir()
    sources = sorted(p for p in CASES.glob("*.yml"))[:2]
    assert sources, "真语料目录里一个 .yml 都没有 ⇒ 本判据会退化成空跑，请同步取样口径"
    for src in sources:
        shutil.copy(src, corpus / src.name)

    before = render_cases.load_case_dicts(corpus)
    assert PROBE not in _ids(before), "临时语料里本不该有这个探针 id（取样污染）"

    target = corpus / sources[0].name
    text = target.read_text(encoding="utf-8")
    hit = re.search(r"(?m)(\bid:\s*)(\S+)", text)
    assert hit, f"{target.name} 里找不到 `id:` 标量 ⇒ 语料格式变了，本判据要同步"
    target.write_text(text[:hit.start(2)] + PROBE + text[hit.end(2):], encoding="utf-8")

    after = render_cases.load_case_dicts(corpus)
    assert PROBE in _ids(after), (
        "改了内容却仍拿到旧结果 ⇒ 缓存键不是内容（会供出过期结论，比不做缓存更危险）")
    assert PROBE not in _ids(before), "缓存把修改**回溯**进了先前那次调用的结果（快照不成立）"


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据⑤：把机制注回 ⇒ 判据①的谓词必假（证明判据①不是空断言）
# ══════════════════════════════════════════════════════════════════════════════════════

def test_injecting_the_mechanism_back_turns_the_predicate_red(monkeypatch):
    """把缓存注回（= 直连补丁前的原函数）⇒ **同一谓词**必须判假。"""
    raw = conftest.corpus_loader_uncached()
    assert callable(raw), "拿不到补丁前的原函数 ⇒ 本红证退化成空跑（缓存安装路径变了）"
    assert _repeated_loads_do_no_real_parsing(monkeypatch, lambda: raw(CASES)) is False, (
        "把缓存注回后「重复加载 ⇒ 0 次真解析」仍然成立 ⇒ 判据①怎么都不会红（空断言，#5301 判据⑤）")


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据⑥：第二条入口（门禁脚本的装载器）走同一份缓存
# ══════════════════════════════════════════════════════════════════════════════════════

def test_the_gate_loader_shares_the_same_cache(monkeypatch):
    """`.github/case_trust_gate.py` 的 `load_cases_from_dir()` 也必须命中同一份缓存。

    它调用时才 `from render_cases import load_case_dicts` ⇒ 一处安装即覆盖两条入口；
    这条判据钉住那个前提（若哪天它改成自己解析，本判据会红）。
    """
    gate = _gate_module()
    assert _repeated_loads_do_no_real_parsing(monkeypatch, gate.load_cases_from_dir, 2) is True, (
        "门禁脚本的用例装载器在重复解析 ⇒ 「一处安装、两条入口共用」的前提失效（#5301 判据⑥）")


if __name__ == "__main__":                       # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))