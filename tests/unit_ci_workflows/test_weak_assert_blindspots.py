"""
弱断言门禁的双盲区守卫（issue #5080；顺带 #5083 的一条：`--check-weak` 正则误报真断言）。

**盲区①：形态不可见** —— `_WEAK_PATTERNS` 原本只含 Python 形态 ⇒ `.ts/.tsx` 测试文件
（`_is_test_file` 判定为真、本来就会被收进扫描集）命中率恒为 0，TS 侧零判据。
**盲区②：只扫新增** —— CI 与本地都只把 `git diff --diff-filter=A` 的新增文件喂给扫描器
⇒ 存量弱断言永久免疫、**没有燃尽出口**（判据源里没有可以"只许缩短"的载体）。

修法（本文件的判据对象）：
- ① TS 存在性形态入表（`_TS_WEAK_PATTERNS`，按**实测判别力**决定入表集合，见下）；
- ② 新增 fail-closed **不变** + 存量锚点账本 `.github/weak-assert-baseline.json`：
  「新增文件一律 fail-closed，存量只许非增」（同 `skip-exemption-baseline.json` 的 `history` 范式）；
- ③ 收窄存在性/缺失性模式到「**整个断言表达式就是这一个比较**」的形态：
  带 `or` / `and` 续接的复合表达式是**真断言**（实测 5 处 `is None or …` + 6 处 `is not None and …`），
  原正则把它们判成弱断言 = 假红。**不是**删表：裸形态（`is None` / `is not None`）仍逐条检出。

⚠️ 本文件自身会被 `--check-weak` 扫描（它是新增测试文件），因此正文**不得出现字面弱断言模式**
（`is not None` / `is None` 的裸形态、空 `pass`、TS 存在性形态…）：所有样本一律**拼接构造**。
"""
# case_ids: MC-012
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PY = REPO_ROOT / ".github" / "growth_gate.py"
BASELINE = REPO_ROOT / ".github" / "weak-assert-baseline.json"

# ── 样本（一律拼接构造：本文件自己也会被弱断言扫描）──
WEAK_ABSENCE = "assert result " + "is None"
WEAK_EXISTENCE = "assert rejected " + "is not None"
WEAK_ABSENCE_MSG = "assert plan " + "is None, \"no plan\""
WEAK_ABSENCE_COMMENT = "assert out " + "is None  # 哨兵"
FP_ABSENCE_COMPOUND = "assert value " + "is None or isinstance(value, str)"
FP_EXISTENCE_COMPOUND = "assert rejected " + "is not None and rejected.success is False"
TS_DEFINED_SAMPLE = "expect(" + "mod.default || mod)." + "toBeDefined()"
TS_NOTNULL_SAMPLE = "expect(" + "node).not." + "toBeNull()"
TS_TRUTHY_SAMPLE = "expect(" + "screen.getByText('x'))." + "toBeTruthy()"


def _load_gate():
    """从 .github/growth_gate.py 加载被测模块（零依赖，importlib 文件加载）。"""
    spec = importlib.util.spec_from_file_location("growth_gate_weak_under_test", GATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(path, name, body):
    f = Path(path) / name
    f.write_text(body + "\n", encoding="utf-8")
    return f


def _hit_lines(gate, path):
    return [w["line_no"] for w in gate.find_weak_asserts(str(path))]


@pytest.fixture(scope="module")
def gate():
    return _load_gate()


@pytest.fixture(scope="module")
def repo_scan(gate):
    return gate.scan_repo_weak_asserts(str(REPO_ROOT))


def _ledger_file(tmp_path, counts, history_totals=None):
    """写一份最小合规账本（结构照 .github/weak-assert-baseline.json）。"""
    total = sum(counts.values())
    totals = history_totals if history_totals is not None else [total]
    obj = {
        "anchor_sha": "0" * 40,
        "anchored_at": "2026-09-21",
        "weak_total": total,
        "legacy_weak_counts": dict(counts),
        "history": [{"anchored_at": "2026-09-21", "anchor_sha": "0" * 40,
                     "weak_total": t, "note": "测试夹具"} for t in totals],
    }
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


# ── ① 盲区一：TS 形态必须可见（原表 0 命中）──

def test_ts_existence_forms_are_detected(gate, tmp_path):
    """TS 存在性形态（只证明"东西在"）必须被检出 —— 这是盲区①的正面判据。"""
    defined = _write(tmp_path, "a.test.tsx", TS_DEFINED_SAMPLE)
    notnull = _write(tmp_path, "b.test.ts", TS_NOTNULL_SAMPLE)
    assert _hit_lines(gate, defined) == [1], "TS 存在性形态必须命中（原表恒 0 = 盲区①）"
    assert _hit_lines(gate, notnull) == [1], "not.toBeNull 同属存在性断言"


def test_ts_forms_do_not_leak_into_python_files(gate, tmp_path):
    """TS 形态只对 .ts/.tsx 生效：Python 文件里的同名字符串不得被误判。"""
    py = _write(tmp_path, "c_test.py", TS_DEFINED_SAMPLE)
    assert _hit_lines(gate, py) == [], "TS 专属形态不得施加到 Python 文件"


def test_tobetruthy_stays_out_of_table_with_measured_rationale(gate, tmp_path):
    """`toBeTruthy` **有意不入表**（实测取舍，不是漏项）。

    全仓实测（本仓当前树）：`toBeTruthy` 500 处 / 60 个测试文件，其中 424 处作用在
    testing-library 的 `getBy*`/`findBy*` 返回值上、76 处作用在 `querySelector` /
    `includes` / 位掩码等**真断言**上 ⇒ 文本层一刀切 = 认下 76 处假红（issue #5080 的
    验收判据①明确要求按实测判别力决定入表集合）。本测试**钉住这个取舍**：谁要把
    `toBeTruthy` 收进表，必须同时修好这条测试与口径说明（不许静默放宽/收紧）。
    """
    truthy = _write(tmp_path, "d.test.tsx", TS_TRUTHY_SAMPLE)
    assert gate._TS_WEAK_PATTERNS, "TS 表不得为空（否则盲区①原地复发）"
    assert _hit_lines(gate, truthy) == [], "toBeTruthy 是有意排除项，不得入表"


def test_cli_check_weak_reddens_on_new_ts_file(gate, tmp_path, capsys):
    """issue #5080 验收判据③：新增一个 TS 存在性断言测试文件 ⇒ 门禁必须判红。"""
    f = _write(tmp_path, "new_feature.test.tsx", TS_DEFINED_SAMPLE)
    rc = gate.main(["--check-weak", "--new-tests-only", "--files", str(f)])
    out, _ = capsys.readouterr()
    assert rc == 1, "新增 TS 弱断言必须 fail-closed（原行为 exit 0 = 假绿）"
    assert "1 处弱断言" in out


# ── ② #5083 的一条：存在性/缺失性模式收窄到「单一比较」形态 ──

def test_bare_existence_and_absence_still_weak(gate, tmp_path):
    """收窄**不得**放过裸形态：这两个是判据要保住的真弱断言（不触业务数据）。"""
    absence = _write(tmp_path, "e_test.py", WEAK_ABSENCE)
    existence = _write(tmp_path, "f_test.py", WEAK_EXISTENCE)
    assert _hit_lines(gate, absence) == [1], "裸缺失性断言仍是弱断言"
    assert _hit_lines(gate, existence) == [1], "裸存在性断言仍是弱断言（#5080 明令不得放过）"


def test_compound_boolean_expressions_are_not_weak(gate, tmp_path):
    """注入式红证（#5083）：带 `or` / `and` 续接的复合表达式是**真断言**，不得判弱。

    这些形态在原正则下全部命中（本地实测 5 处 `is None or …` + 6 处 `is not None and …`），
    属"误报真断言"；本判据的单点变异 = 把样本写成复合形态 ⇒ 必须不被检出。
    """
    absence_fp = _write(tmp_path, "g_test.py", FP_ABSENCE_COMPOUND)
    existence_fp = _write(tmp_path, "h_test.py", FP_EXISTENCE_COMPOUND)
    assert _hit_lines(gate, absence_fp) == [], "is None or … 是真断言，不得判弱"
    assert _hit_lines(gate, existence_fp) == [], "is not None and … 是真断言，不得判弱"


def test_trailing_message_and_comment_forms_still_weak(gate, tmp_path):
    """收窄只针对**布尔续接**：尾随断言消息 / 行尾注释仍是同一个单一比较 ⇒ 仍判弱。"""
    msg = _write(tmp_path, "i_test.py", WEAK_ABSENCE_MSG)
    comment = _write(tmp_path, "j_test.py", WEAK_ABSENCE_COMMENT)
    assert _hit_lines(gate, msg) == [1], "尾随消息不改变断言表达式 ⇒ 仍弱"
    assert _hit_lines(gate, comment) == [1], "行尾注释不改变断言表达式 ⇒ 仍弱"


# ── ③ 盲区二：存量锚点只许非增 + 新增 fail-closed ──

def test_repo_scan_sees_both_python_and_ts_weak_asserts(repo_scan):
    """全仓扫描器必须同时看得见两侧形态（否则账本只锚住半张表）。"""
    assert repo_scan, "全仓扫描不得为空（空 = 扫描器空转）"
    assert sum(repo_scan.values()) >= 100, "本仓存量弱断言是三位数（实测口径见账本）"
    ts_files = [p for p in repo_scan if p.endswith((".ts", ".tsx"))]
    assert ts_files, "账本必须覆盖 TS 侧 —— 否则盲区①只是「看不见」而非「修好了」"


def test_ledger_total_is_not_ts_blind(gate, repo_scan):
    """账本总量必须是**含 TS 表**的扫描结果（旧快照会少一截 ⇒ 不得拿来当锚点）。"""
    _, meta, err = gate.load_weak_baseline(str(BASELINE))
    assert err == "", f"账本必须可加载：{err}"
    saved = list(gate._TS_WEAK_PATTERNS)
    try:
        gate._TS_WEAK_PATTERNS = []
        python_only = gate.scan_repo_weak_asserts(str(REPO_ROOT))
    finally:
        gate._TS_WEAK_PATTERNS = saved
    assert sum(repo_scan.values()) == meta["weak_total"], "账本 weak_total 必须等于当前含 TS 的实测总量"
    assert sum(python_only.values()) < sum(repo_scan.values()), "TS 表必须真的改变结果（否则入表是空转）"


def test_current_repo_is_within_baseline(gate, repo_scan):
    """本仓当前树必须**不增长**于锚点（这就是"只许缩短"的机械判据）。"""
    _, meta, err = gate.load_weak_baseline(str(BASELINE))
    assert err == "", f"账本必须可加载：{err}"
    growth = gate.weak_baseline_diff(repo_scan, meta["legacy_weak_counts"])
    assert growth == [], f"存量弱断言只许非增（新增文件一律 fail-closed）：{growth}"


def test_ledger_self_consistent(gate):
    """账本自身自洽（结构与 skip-exemption-baseline.json 同族）。"""
    counts, meta, err = gate.load_weak_baseline(str(BASELINE))
    assert err == "", f"账本必须自洽：{err}"
    assert re.fullmatch(r"[0-9a-f]{40}", meta["anchor_sha"]), "anchor_sha 必须是完整 sha"
    assert meta["weak_total"] == sum(counts.values()) == meta["history"][-1]["weak_total"]
    assert all(gate._is_test_file(p) for p in counts), "账本键必须都是测试文件（同 _is_test_file 单一事实源）"
    assert all(n > 0 for n in counts.values()), "0 处不入账（否则「缩短」没有可读的差分）"
    assert meta["history"], "history 必须非空（照 skip-exemption-baseline.json 的范式）"


def test_ledger_missing_or_corrupt_is_fail_closed(gate, tmp_path, capsys):
    """账本缺失/损坏 ⇒ 非零且不得打印"合规"（fail-closed，同 return 2 口径）。"""
    rcs = []
    rc, _, _ = gate.check_weak_baseline(str(REPO_ROOT), str(tmp_path / "nope.json"))
    rcs.append(rc)
    capsys.readouterr()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"anchor_sha": "x", "weak_total": 1,
                               "legacy_weak_counts": {"a": 1}, "history": []}), encoding="utf-8")
    rc2, _, _ = gate.check_weak_baseline(str(REPO_ROOT), str(bad))
    rcs.append(rc2)
    capsys.readouterr()
    assert rcs == [2, 2], f"账本缺失/损坏必须 fail-closed（rc=2），实测 {rcs}"


def test_baseline_growth_and_new_file_red_end_to_end(gate, tmp_path, capsys):
    """端到端注入：新增文件 / 存量文件增长 ⇒ 判红并点名；只许缩短才放行。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    tracked = _write(repo, "tracked_test.py", WEAK_ABSENCE)
    ledger = _ledger_file(tmp_path, {"tracked_test.py": 1})
    rc, _, _ = gate.check_weak_baseline(str(repo), str(ledger))
    capsys.readouterr()
    assert rc == 0, "与锚点齐平必须放行（不得假红）"

    _write(repo, "brand_new.test.tsx", TS_DEFINED_SAMPLE)
    rc, lines, _ = gate.check_weak_baseline(str(repo), str(ledger))
    capsys.readouterr()
    assert rc == 1, "新增文件的弱断言必须 fail-closed（盲区②的修法）"
    assert any("brand_new.test.tsx" in ln for ln in lines), "必须点名到文件"

    (repo / "brand_new.test.tsx").unlink()
    _write(repo, "tracked_test.py", WEAK_ABSENCE_COMMENT + "\n" + WEAK_ABSENCE)
    rc, lines, _ = gate.check_weak_baseline(str(repo), str(ledger))
    capsys.readouterr()
    assert rc == 1, "存量文件增长（1 → 2）必须判红"
    assert any("tracked_test.py" in ln for ln in lines)


def test_baseline_shrink_is_allowed_and_write_is_shrink_only(gate, tmp_path, capsys):
    """净缩放行；重锚定**拒绝**增长（防用改账本洗白新增债务）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write(repo, "k_test.py", WEAK_ABSENCE)
    ledger = _ledger_file(tmp_path, {"k_test.py": 3, "gone_test.py": 2})
    rc, _, _ = gate.check_weak_baseline(str(repo), str(ledger))
    capsys.readouterr()
    assert rc == 0, "只许缩短：净缩必须放行"

    before = json.loads(ledger.read_text(encoding="utf-8"))
    assert before["weak_total"] == 5
    rc, _, _ = gate.write_weak_baseline(str(repo), str(ledger))
    capsys.readouterr()
    assert rc == 0, "净缩后重锚定必须成功"
    after = json.loads(ledger.read_text(encoding="utf-8"))
    assert after["weak_total"] == 1 and after["legacy_weak_counts"] == {"k_test.py": 1}
    assert len(after["history"]) == len(before["history"]) + 1, "重锚定必须留 history 一行"

    _write(repo, "smuggled.test.tsx", TS_NOTNULL_SAMPLE)
    rc, _, _ = gate.write_weak_baseline(str(repo), str(ledger))
    capsys.readouterr()
    assert rc == 1, "有增长时重锚定必须被拒（否则账本可被用来洗白新增弱断言）"


# ── ④ 接线锁：燃尽出口与新增 fail-closed 两条通路都不得被静默拆掉 ──

def test_verify_all_gate_runs_the_baseline_check():
    """`./verify-all.sh gate` 必须调起存量锚点检查（否则"只许缩短"没有执行点）。"""
    text = (REPO_ROOT / "verify-all.sh").read_text(encoding="utf-8")
    assert "--check-weak-baseline" in text, "gate 必须跑存量锚点检查（燃尽出口）"


def test_pr_check_keeps_new_tests_only_fail_closed():
    """CI 侧"新增测试文件"的弱断言检查不得被拆，且选取集必须走**共享实现**（#4077 / #5477）。"""
    text = (REPO_ROOT / ".github" / "workflows" / "pr-check.yml").read_text(encoding="utf-8")
    assert "--check-weak" in text and "--new-tests-only" in text, "CI 必须保留新增文件弱断言检查"
    assert "--select-weak-files" in text, (
        "CI 的选取集必须由 growth_gate 的唯一实现产出（issue #5477：此前是本文件里的内联 grep）")
    gate_src = GATE_PY.read_text(encoding="utf-8")
    assert "--diff-filter=A" in gate_src, (
        "「新增」口径仍是 diff-filter=A（本单不改变它）—— 真值现在在 growth_gate.get_added_files")


# ── 说明 vs 实现（2026-09-25 同一形态一天撞 4 次 ⇒ 就地修在扫描器上）────────────────
#
# 现场：把「不要写某个存在性弱断言」这类**解释性注释**写进测试文件 ⇒ 账本当场多算一处弱断言
# （当天本会话的 PR 就是这么被 CI 判红的：**改法注释里出现了那个模式的字面文本**）。
# 同族更早的形态：#5272（判据按原文扫代码 ⇒ 注释里的 `"settings"` 被读成「仍绑定」）。
# ⇒ 口径：**命中落在注释/文档字符串里就不算**；其余判定一字不变（账本只许缩短）。
#
# ⚠️ 下面的**夹具文本一律用拼接构造**：本文件会被同一个扫描器扫到，若把模式字面写进语料，
# 语料自己就变成 4 处「弱断言」（本判据第一版当场踩到）—— 这是「判据语料不含自身说明」的翻版。

_WEAK = "assert got is " + "not None"      # 存在性弱断言（拼接，避免字面落进语料）
_WEAK_NONE = "assert got is " + "None"


def _scan(path, name: str, body: str) -> int:
    mod = _load_gate()
    return len(mod.find_weak_asserts(str(_write(path, name, body))))


def test_comment_mention_is_not_counted(tmp_path):
    """注释里**提到**弱断言模式 ⇒ 不算（这正是当天踩的那个坑）。"""
    body = "def test_x():\n    # 不要写 " + _WEAK + " 这种存在性断言\n    assert got == 3"
    assert _scan(tmp_path, "test_a.py", body) == 0


def test_docstring_mention_is_not_counted(tmp_path):
    """模块 docstring 里提到该模式 ⇒ 不算。"""
    body = '"""说明：历史上的 ' + _WEAK_NONE + ' 形态已修。"""\n\n\ndef test_x():\n    assert got == 3'
    assert _scan(tmp_path, "test_b.py", body) == 0


def test_real_weak_assert_is_still_counted(tmp_path):
    """真实存在性弱断言**照样计数**（口径没被放宽）。"""
    assert _scan(tmp_path, "test_c.py", "def test_x():\n    " + _WEAK) == 1


def test_weak_assert_before_a_trailing_comment_is_still_counted(tmp_path):
    """同一行「真断言 + 行尾注释」⇒ 仍计数（命中在说明**之前**）。"""
    assert _scan(tmp_path, "test_d.py", "def test_x():\n    " + _WEAK_NONE + "  # 行尾说明") == 1


def test_hash_inside_a_string_does_not_hide_later_lines(tmp_path):
    """字符串里的 `#` 不得被当成注释起点（否则后续行会被误判成说明）。"""
    body = 'def test_x():\n    tag = "a#b"\n    ' + _WEAK_NONE
    assert _scan(tmp_path, "test_e.py", body) == 1


def test_ts_line_comment_mention_is_not_counted(tmp_path):
    """TS 的 `//` 注释里提到模式 ⇒ 不算。"""
    body = "it('x', () => {\n  // expect(foo).toBe" + "Defined() 是弱断言\n  expect(foo).toEqual(3)\n})"
    assert _scan(tmp_path, "x.test.ts", body) == 0
