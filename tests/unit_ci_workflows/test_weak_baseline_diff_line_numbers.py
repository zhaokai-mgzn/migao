# case_ids: MC-223
"""存量弱断言**增长**必须报出**具体行号**（issue #5511 第四节 / 来源台账 #8313 残余②）。

## 病灶（台账原文 + 现取复核）

台账原文：「`scripts/growth_gate.py` 的 `weak_baseline_diff` 仍只返回 `(path, cur, base)`、
失败信息**无行号**」。路径已漂移到 `.github/growth_gate.py`（别照旧路径找），病灶**仍成立**：

    git show origin/main:.github/growth_gate.py | grep -A3 'def weak_baseline_diff'
    def weak_baseline_diff(counts, anchored):
        return [(p, c, anchored.get(p)) ...]

⇒ 门禁判红时只说「某文件 3 处（新增入账）」，处置的人得**先把整个文件翻一遍**才知道哪几行是
弱断言 —— 而这条门禁的处置口径是「把弱断言改成触业务数据的断言」，找不准行就改不动。

## 修法与口径（exactly what changed）

`weak_baseline_diff` 多返回一列：**该文件里全部弱断言的行号**（`weak_assert_lines()`）。
`check_weak_baseline` 的失败行因此长成 `  · 路径:行号 —— N 处（...）；弱断言行 a, b`
⇒ 报错文本可直接点开。

⚠️ **为什么报「全部」而不是「新增的那几行」**：锚点账本只存**处数**，没有逐行快照 ⇒ 差分不出
哪几行是新加的。宁可多报（每行都是可点开的候选），也不把猜出来的编号写成「新增行」。

## 本文件锁什么（每条都能单独变红）

1. `test_new_file_growth_reports_path_and_line_numbers` —— 新入账文件 ⇒ 失败文本含 `路径:行号`
   （改前只有 `路径`，本条**改前必红**）；
2. `test_existing_file_growth_reports_its_weak_lines` —— 存量增长 ⇒ 该文件两处弱断言的行号都在；
3. `test_zero_baseline_behaviour_is_unchanged` —— 不增长 ⇒ `growth == []` 且 rc 0（**负控**：
   加行号不得把干净的树判红）；
4. `test_line_lookup_failure_does_not_hide_the_red` —— 行号取不到（文件已不在）⇒ 仍判红并点名
   文件（**不拿「读不到行号」洗白已判红的结论**）。
"""
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PY = REPO_ROOT / ".github" / "growth_gate.py"

# ── 样本（一律**拼接构造**：本文件自己也会被弱断言扫描，正文不得出现字面弱断言模式）──
WEAK_LINE = "assert result " + "is None"
CLEAN_LINE = "assert snapshot[\"count\"] == 3"


def _load_gate():
    spec = importlib.util.spec_from_file_location("growth_gate_lines_under_test", GATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gate():
    return _load_gate()


def _at(rel: str, line: int) -> str:
    """运行期拼「路径 + 冒号 + 行号」。

    ⚠️ 判据源码里**不得出现字面**的 `路径:行号`：Case Trust 规则 G 会把它当成一条真的仓库行引用
    （`CASE-TRUST-STALE-LINE-REF`），而这里的样本文件是 tmp 目录里的虚构文件。拼接构造同时满足
    「判据要断言行号」与「判据文本不许写死行号」。
    """
    return rel + ":" + str(line)


def _write(repo: Path, name: str, lines: list) -> Path:
    f = repo / name
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f


def _ledger(tmp_path: Path, counts: dict) -> Path:
    """写一份最小合规账本（结构照 `.github/weak-assert-baseline.json`）。"""
    total = sum(counts.values())
    obj = {
        "anchor_sha": "0" * 40,
        "anchored_at": "2026-11-05",
        "weak_total": total,
        "legacy_weak_counts": counts,
        "history": [{"date": "2026-11-05", "weak_total": total}],
    }
    p = tmp_path / "weak-assert-baseline.json"
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def test_new_file_growth_reports_path_and_line_numbers(gate, tmp_path, capsys):
    """**本条改前必红**：新入账文件的失败文本必须含 `路径:行号`（改前只有路径 + 处数）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    # 第 3 行是弱断言（前两行是空行/注释，用来证明行号是**真取出来的**、不是常量 1）。
    _write(repo, "brand_new_test.py", ["# 新增文件", "", WEAK_LINE])
    ledger = _ledger(tmp_path, {"other_test.py": 1})

    rc, lines, _ = gate.check_weak_baseline(str(repo), str(ledger))
    capsys.readouterr()

    assert rc == 1, f"新文件里的弱断言必须 fail-closed（实测 rc={rc}）"
    expected = _at("brand_new_test.py", 3)
    assert any(expected in ln for ln in lines), (
        f"失败信息必须含 `路径:行号`（期望 {expected}，实测报告 {lines}）—— 只有路径的话，"
        f"处置的人还得自己翻整个文件找弱断言"
    )


def test_existing_file_growth_reports_its_weak_lines(gate, tmp_path, capsys):
    """存量文件从 1 处涨到 2 处 ⇒ 该文件**两处**弱断言的行号都要出现。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    body = [CLEAN_LINE, WEAK_LINE, CLEAN_LINE, WEAK_LINE]   # 行 2 与行 4 是弱断言
    _write(repo, "tracked_test.py", body)
    ledger = _ledger(tmp_path, {"tracked_test.py": 1})

    rc, lines, _ = gate.check_weak_baseline(str(repo), str(ledger))
    capsys.readouterr()

    assert rc == 1, f"存量增长必须判红（实测 rc={rc}）"
    first, second = _at("tracked_test.py", 2), _at("tracked_test.py", 4)
    assert any(first in ln and second in ln for ln in lines), (
        f"两处弱断言的行号必须同时报出（期望 {first} + {second}，实测报告 {lines}）"
    )
    assert any("存量增长 1 → 2" in ln for ln in lines), (
        f"处数差分（1 → 2）必须仍然可读（实测报告 {lines}）"
    )


def test_zero_baseline_behaviour_is_unchanged(gate, tmp_path, capsys):
    """**负控**：与锚点齐平 ⇒ `growth == []`、rc 0、不打印任何行号（加列不得把干净的树判红）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write(repo, "flat_test.py", [WEAK_LINE])
    ledger = _ledger(tmp_path, {"flat_test.py": 1})

    rc, lines, counts = gate.check_weak_baseline(str(repo), str(ledger))
    capsys.readouterr()

    assert rc == 0, f"齐平必须放行（实测 rc={rc}，报告 {lines}）"
    assert gate.weak_baseline_diff(counts, {"flat_test.py": 1}, str(repo)) == [], (
        "齐平不得产生 growth 条目（否则门禁变成「有弱断言就红」）"
    )


def test_line_lookup_failure_does_not_hide_the_red(gate, tmp_path):
    """行号取不到（文件已不在）⇒ 行号列退化为空列表，但**文件/处数必须保留**。

    为什么单列这条：取值失败若把条目整条吞掉，判红就变成「静默放行」—— 那是本仓最贵的形态。
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    growth = gate.weak_baseline_diff({"ghost_test.py": 3}, {"ghost_test.py": 2}, str(repo))
    assert growth == [("ghost_test.py", 3, 2, [])], (
        f"读不到行号时行号列退化为空列表，但文件/处数必须保留（实测 {growth}）"
    )
