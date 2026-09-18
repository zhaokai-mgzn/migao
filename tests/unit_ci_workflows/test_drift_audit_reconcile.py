# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""L0 红证（#4247）：`reconcile_baseline` 的**键形映射**必须显式 —— 否则 `refs-are-fixtures`
例外在「同文件有已入基线的引用条目」时**以 traceback 代替结论**。

## 病灶（实测崩溃，非推测）

`FIXTURE_MARKER`（`# drift-audit: refs-are-fixtures`，`tests/**` 专用）的语义 = 该文件
**整体退出** ref-freshness 扫描面 ⇒ 文件里**已入基线**的存量条目在**全库重算**里归零 ⇒
被 `reconcile_baseline` 判为 stale。崩溃点：

    stale = [{"key": k, "count": cur_entries[k], …} for k in sorted(stale_keys)]

`stale_keys` 取自**门禁侧** `recon["stale"][].removed_codes`，其码形是 `_codes_of` 展开出来的
`…|bare × 1`（**带 `× N` 后缀**）；而 `cur_entries` 的键形是 `…|bare`（**无后缀**）
⇒ `cur_entries[k]` 直接 `KeyError`。`dropped` 分支（`base_entries[k]`）是**同一族的键形问题**
（`dropped_codes` 同样是展开后的码），故本文件对两个方向对称断言。

## 为什么这条必须双向（issue 的「红证要求」）

① 声明 marker ⇒ **不得 traceback**，且必须产出**可行动**的 stale 报告（含机械修法入口）；
② **未声明** marker ⇒ 该文件的引用条目**仍参与扫描** —— 防止修键形时顺手把例外面放大
   （把「例外只对声明了 marker 的文件生效」改成「对所有 tests/** 生效」= 悄悄砍判据）。
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIFT = REPO_ROOT / "scripts" / "drift_audit.py"

# 夹具 key 用**真实仓库里的形态**（`文件|引用路径#行|码类`），因为要复现的正是这个键形。
FIXTURE_FILE = "tests/unit_ci_workflows/test_case_trust_gate.py"
KEY = f"{FIXTURE_FILE}|local_runner.py#2000|bare"   # 基线里计数 = 2（展开成 `… × 1` / `… × 2`）


@pytest.fixture(scope="module")
def drift():
    """按**路径**加载 `scripts/drift_audit.py`（不往 `sys.path` 塞东西，与既有契约测试同款）。

    `dataclass` 要求模块在 `sys.modules` 里可达，否则 `@dataclass` 当场 AttributeError。
    """
    spec = importlib.util.spec_from_file_location("drift_audit_reconcile_under_test", DRIFT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["drift_audit_reconcile_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


# ═══════════════════════════════════════════════════════════════════════════
# ① + ③ 纯函数：键形映射（stale / dropped 两个方向）
# ═══════════════════════════════════════════════════════════════════════════
def test_stale_report_maps_expanded_codes_back_to_plain_keys(drift):
    """**陈旧方向**：门禁侧回的是展开码（`…|bare × 1`），报告必须归位到清单里的**原键**。

    改动前：`cur_entries['…|bare × 1']` ⇒ `KeyError`（traceback 代替结论）。
    改动后：`stale == [{'key': '…|bare', 'count': 2, …}]`，且提示里带机械修法命令。
    """
    cur = {KEY: 2}   # 清单记着 2 处
    # 全库重算 0 命中（= 该文件声明了 FIXTURE_MARKER 后的真实形态）⇒ 记着的码已不再命中。
    recon = drift.reconcile_baseline("ref-freshness", {}, cur, dict(cur))
    assert [s["key"] for s in recon["stale"]] == [KEY], (
        f"陈旧项未归位到清单原键（键形仍不匹配 ⇒ 修法没落地）：{recon}")
    assert recon["stale"][0]["count"] == 2, (
        f"计数必须是**清单里的真实豁免面**（2），不是展开码的个数：{recon['stale'][0]}")
    assert recon["stale"][0]["check"] == "ref-freshness", recon["stale"][0]
    assert recon["blocking"] is True, "陈旧项必须阻塞（#4045 全量对账）"
    hint = recon["stale"][0]["hint"]
    assert drift.REGEN_COMMAND in hint, f"提示里没有机械修法入口：{hint}"
    assert KEY in hint, f"提示没点名该移除哪条：{hint}"


def test_stale_report_never_carries_expanded_codes(drift):
    """**负例（防修错方向）**：报告里**不得**出现展开码字面量（` × N` 后缀）。

    若有人图省事把展开码直接当 key 报出去（`{'key': '… × 1', 'count': cur_entries.get(…) or 0}`），
    这条会红 —— 那种"不崩了"的修法把**同一份清单条目报成 N 条**，报错指向不存在的条目。
    """
    cur = {KEY: 2}
    recon = drift.reconcile_baseline("ref-freshness", {}, cur, dict(cur))
    bad = [s["key"] for s in recon["stale"] if re.search(r" × \d+$", s["key"])]
    assert not bad, f"报告里出现展开码（会把 1 条清单条目报成 N 条）：{bad}"


def test_dropped_report_maps_expanded_codes_back_to_plain_keys(drift):
    """**被删方向（同族）**：`dropped_codes` 同样是展开码 ⇒ `base_entries[k]` 同款 KeyError。

    形态：`--base`（origin/main）的清单里记着该条、**现在仍然漂移**，却被本 PR 从清单删掉
    ⇒ 新增豁免。改动前这里同样 `KeyError`（只修 stale 半边 = 同一族只修一半）。
    """
    base = {KEY: 2}
    res = drift.CheckResult("ref-freshness")
    res.findings.append(drift.Finding(KEY, "（夹具）该条现在仍然漂移"))
    recon = drift.reconcile_baseline("ref-freshness", {KEY: 2}, {}, base)
    assert [d["key"] for d in recon["dropped"]] == [KEY], (
        f"被删项未归位到 base 清单原键（同族键形问题只修了一半）：{recon}")
    assert recon["dropped"][0]["count"] == 2, recon["dropped"][0]
    assert "origin/main" in recon["dropped"][0]["hint"], recon["dropped"][0]
    assert recon["stale"] == [], (
        f"「被删」方向不该顺带报陈旧（两个判据混在一起 = 归因错）：{recon['stale']}")


def test_missing_key_fails_closed_with_actionable_hint(drift):
    """**fail-closed 兜底（B）**：万一将来门禁侧换了码形、原键在清单里确实找不到，
    也**不得抛 `KeyError`** —— 要打印**键形差异** + 机械修法入口（可行动指引）。

    这条不是"给崩溃开后门"：它断言的是**失败形态必须是判定而不是 traceback**
    （issue：「失败形态是 traceback 而不是判定，与『判据必须可红/可绿』的纪律相悖」），
    且阻塞口径不变（`blocking` 仍为 True）。
    """
    # 正常路径：码能对上原键 ⇒ 不抛异常、仍按全量对账阻塞。
    recon = drift.reconcile_baseline("ref-freshness", {}, {KEY: 1}, {KEY: 1})
    assert recon["blocking"] is True
    # 兜底路径：把判据单一源换成**返回无法归位码**的桩（模拟门禁侧码形变化）。
    real_loader = drift._load_gate_module
    drift._load_gate_module = lambda: _OrphanGate()
    try:
        recon2 = drift.reconcile_baseline("ref-freshness", {}, {"真实键": 1}, {"真实键": 1})
    finally:
        drift._load_gate_module = real_loader
    assert recon2["stale"], f"兜底分支没报出任何陈旧项（静默吞掉 = 更糟）：{recon2}"
    assert recon2["blocking"] is True, "兜底分支不得放宽阻塞口径（fail-closed）"
    hint = recon2["stale"][0]["hint"]
    assert drift.REGEN_COMMAND in hint, f"兜底指引里没有机械修法入口：{hint}"
    assert "× 99" in hint, f"兜底指引没打印键形差异（看不出是哪种码形对不上）：{hint}"


class _OrphanGate:
    """门禁侧的桩：`removed_codes` 故意返回**无法归位**的码（模拟码形变化 / 键形漂移）。"""

    @staticmethod
    def reconcile_baseline(baseline, violations, base_baseline=None, **kw):
        return {"stale": [{"case_id": "真实键",
                           "removed_codes": ["真实键 × 99"],
                           "now_codes": []}],
                "dropped": [], "unregistered": [], "blocking": True}


# ═══════════════════════════════════════════════════════════════════════════
# ② 例外面**不得放大**：未声明 marker ⇒ 该文件仍参与扫描
# ═══════════════════════════════════════════════════════════════════════════
def test_fixture_marker_exemption_stays_scoped_to_declaring_files(drift):
    """**未声明** marker 的 `tests/**` 文件**仍参与** ref-freshness 扫描。

    防止「修键形时顺手把例外面放大」：若有人把 `check_refs` 里的 `FIXTURE_MARKER in txt`
    改成"tests/** 一律跳过"，这条会红 —— 那是**悄悄砍判据**（issue 明令「不放宽判据」）。
    """
    # 判据面（静态，纯读源码语义）：`_in_surface` 是**路径**判据，与 marker 无关；
    # marker 例外只出现在 `check_refs` 的**逐文件文本**判定里。
    assert drift._in_surface("tests/unit_ci_workflows/test_case_trust_gate.py") is True, (
        "tests/** 必须在判定面内（例外面只由文件内声明决定，不由路径决定）")
    assert drift.FIXTURE_MARKER.startswith("# drift-audit:"), (
        "marker 形态变了 ⇒ 本测试与被审文件里的声明会静默失配")

    # 行为面（真跑）：一个**未声明** marker 的 tests/** 文件里放一个悬空引用 ⇒ 必须报出。
    # 用 tmp_path 造最小 git 仓库，不依赖真实 origin/main 或网络（与既有契约测试同款）。
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        (repo / "tests" / "unit_ci_workflows").mkdir(parents=True)
        (repo / "tests" / "unit_ci_workflows" / "test_no_marker.py").write_text(
            "def test_x():\n"
            "    # 引用一个不存在的文件（悬空引用）\n"
            "    p = 'no/such/file.py:10'\n"
            "    assert p\n", encoding="utf-8")
        # 非 tests/** 面：`docs/wiki/` 在受管引用面内（`REF_SURFACE`）⇒ 必须照旧受判。
        (repo / "docs" / "wiki").mkdir(parents=True)
        (repo / "docs" / "wiki" / "doc.md").write_text(
            "引用 `no/such/file.py:10` 也是悬空。\n", encoding="utf-8")
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@example.com")
        _git(repo, "config", "user.name", "t")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "fixture")
        # `--stale-scope none` = 无 PR 上下文的纯审计（三条退出码根因全在这里发生，
        # 与「阻塞口径」无关 ⇒ 用 none 隔离出真正被测的那条路径）。
        rc, out, rep = _run_drift(repo, "--check", "--only", "ref-freshness",
                                  "--stale-scope", "none")
        assert rc == 1, f"未声明 marker 的 tests/** 文件未被扫描（判据被悄悄砍掉）：\n{out}"
        codes = {f["key"] for f in _check_of(rep, "ref-freshness")["findings"]}
        assert any("no/such/file.py" in c for c in codes), (
            f"悬空引用没被报出（该文件应仍在判定面内）：{sorted(codes)}")

        # 声明 marker 后同一文件退出判定面（这是**既有**例外语义，本条只锁"作用域不变"）。
        f = repo / "tests" / "unit_ci_workflows" / "test_no_marker.py"
        f.write_text(drift.FIXTURE_MARKER + "\n" + f.read_text(encoding="utf-8"),
                     encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "声明夹具标记")
        rc2, out2, rep2 = _run_drift(repo, "--check", "--only", "ref-freshness",
                                     "--stale-scope", "none")
        codes2 = {f2["key"] for f2 in _check_of(rep2, "ref-freshness")["findings"]}
        assert not any("test_no_marker.py" in c for c in codes2), (
            f"声明 marker 后该文件仍被判定（例外语义变了）：{sorted(codes2)}")
        assert any("doc.md" in c for c in codes2), (
            f"非 tests/** 面（文档）必须照旧受判（判据不得被整体放宽）：{sorted(codes2)}")
        # 声明 marker **不得**把整条判据判成"没跑"（`evaluated` 仍需 > 0）：
        assert _check_of(rep2, "ref-freshness")["evaluated"] > 0, out2


# ═══════════════════════════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════════════════════════
def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def _check_of(rep: dict, cid: str) -> dict:
    for c in rep.get("checks", []):
        if c["id"] == cid:
            return c
    raise AssertionError(f"报告里没有判据 {cid}（报告形态变了）：{sorted(rep)}")


def _run_drift(repo: Path, *args: str, base: str = "main") -> tuple[int, str, dict]:
    """跑审计；返回 (exit, stdout, json 报告)。报告写到仓库**外**，避免污染被测树。"""
    import tempfile

    out_json = Path(tempfile.mkdtemp()) / "drift.json"
    p = subprocess.run([sys.executable, str(DRIFT), "--repo", str(repo), "--base", base,
                        "--json", str(out_json), "--offline"] + list(args),
                       capture_output=True, text=True, timeout=300)
    rep = json.loads(out_json.read_text(encoding="utf-8")) if out_json.is_file() else {}
    return p.returncode, p.stdout + p.stderr, rep
