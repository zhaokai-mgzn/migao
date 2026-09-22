# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""判据异常 ⇒ **不可判（三态 `3`）**，不是「发现数为 0 / 基线归零未删」（issue #5151）。

## 病灶（PR #5147 实测，差一步造成破坏）

`scripts/drift_audit.py` 的 `mutable-locator` 用严格 loader 读用例源文件 ⇒ 一个未转义的裸
双引号让**整条判据抛错**。而抛错后的形态与"判据说没有漂移"**在报告里长得一样**（`findings`
为空）⇒ 下游把它读成「这 9 条 `component|*` 基线条目已不再漂移」⇒

· 报告写「**基线归零未删 9（阻塞）**」（**报错指向错误病因**），
· 并给出**破坏性建议** `--regen-baseline`（照做＝**凭一次解析错误永久删掉 9 条合法豁免**）。

## 本文件锁四条

1. **红证 B**（注入式夹具）：判据腿的 loader 抛错 ⇒ 输出必须是**「不可判」**（三态 `3`），
   **不得**是「发现 0 / 归零未删」；且**不得**出现 `--regen-baseline` 这类建议
   （改前形态：`rc=1`、打印「基线归零未删 9」、打印 regen 建议 —— 本文件在改前必红）。
2. **正对照**（同一份夹具、同一条基线，**只**把那个坏文件去掉）⇒ 立刻变回「判红 + 归零未删 9
   + regen 建议」。⇒ 证明 `3` 与 `1` 是**真的分开了**，而不是"把陈旧判定关掉了"。
3. **三态语义本体**（纯函数）：`error` ⇒ 3；`--fail-on-unknown` 下的 `unknown` ⇒ 3；
   **无该开关时 `unknown` 仍只报告（0，既有语义不放宽）**；真漂移优先于不可判 ⇒ 1；
   clean ⇒ 0。**`3` 永不等于 `0`**。
4. **workflow 接线**：`3` 到了 CI 里必须是「失败/需要人看」，**不是静默通过** ——
   机械读 `.github/workflows/drift-audit.yml`：审计 step 把脚本的返回码**原样 `exit`**
   （非 0 一律失败），失败分支才打 `block/merge`。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIFT = REPO_ROOT / "scripts" / "drift_audit.py"
REAL_BASELINE = REPO_ROOT / "scripts" / "drift_audit_baseline.json"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "drift-audit.yml"
GH = REPO_ROOT / ".github"

#: 坏用例源文件（= #5147 的真实形态：双引号标量内一个未转义的裸双引号）
BAD = '''cases:
  - id: FX-001
    title: "坏文件 "未转义" 引号"
'''
GOOD = '''cases:
  - id: FX-001
    title: fixture
'''


# ─────────────────────────────────────────────────────────────────────────────
# 夹具：只有 `.github/` 的最小 git 仓库（用例库 = 注入面；loader 用**真的**那几份）
# ─────────────────────────────────────────────────────────────────────────────
def _fixture(tmp: Path, cases: dict[str, str]) -> Path:
    repo = tmp / "repo"
    gh = repo / ".github"
    (gh / "cases").mkdir(parents=True, exist_ok=True)
    for name in ("render_cases.py", "yaml_light.py", "cases_yaml.py"):
        (gh / name).write_bytes((GH / name).read_bytes())
    for name, body in cases.items():
        (gh / "cases" / name).write_text(body, encoding="utf-8")
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "f@e.com"),
                 ("config", "user.name", "f"), ("add", "-A"), ("commit", "-qm", "base")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return repo


def _audit(repo: Path, tmp: Path, *args: str) -> tuple[int, str, dict]:
    """跑**真的**审计（`--baseline` 指真基线，只读；`--only mutable-locator` 收窄到本单的判据）。"""
    out = tmp / "drift.json"
    p = subprocess.run(
        [sys.executable, str(DRIFT), "--repo", str(repo), "--base", "main", "--offline",
         "--baseline", str(REAL_BASELINE), "--only", "mutable-locator",
         "--json", str(out), "--check", *args],
        capture_output=True, text=True, cwd=str(REPO_ROOT))
    rep = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    return p.returncode, p.stdout + p.stderr, rep


def _mutable_baseline_count() -> int:
    """本判据在**真基线**里的条目数（**现取、不写死** —— 写死会随销账漂移）。"""
    entries = json.loads(REAL_BASELINE.read_text(encoding="utf-8"))["entries"]
    return len(entries.get("mutable-locator") or {})


def _check(rep: dict, cid: str = "mutable-locator") -> dict:
    return next(c for c in rep["checks"] if c["id"] == cid)


# ─────────────────────────────────────────────────────────────────────────────
# 判据 1：红证 B
# ─────────────────────────────────────────────────────────────────────────────
def test_loader_error_is_unjudgeable_not_zero(tmp_path):
    """**红证 B**：判据腿 loader 抛错 ⇒ 三态 `3`（不可判），且**不给**破坏性建议。

    改前形态（本判据的红证）：`rc=1` + 「基线条目已归零但未删」+ 「可 `--regen-baseline`」
    —— 读者会照着去删那 9 条**合法**豁免。
    """
    n = _mutable_baseline_count()
    assert n > 0, "真基线里没有 mutable-locator 条目 ⇒ 本判据的前提不成立（夹具会静默空跑）"
    repo = _fixture(tmp_path, {"product.yml": BAD})
    rc, out, rep = _audit(repo, tmp_path)
    c = _check(rep)

    assert rc == 3, f"判据不可判时退出码不是 3（三态失守）：rc={rc}\n{out}"
    assert c["status"] == "error", out
    assert "不可判" in c["error"] and "发现数为 0" in c["error"], c["error"]
    # ① 不得被读成「归零未删」：那 N 条必须落在"未能重算"，**不是**陈旧
    assert rep["summary"]["stale_baseline_entry"] == 0, out
    assert rep["summary"]["stale_baseline_blocking"] == 0, out
    assert len(c["stale_baseline_unverifiable"]) == n, (
        f"那 {n} 条基线条目没有落在「未能重算」（没跑 ≠ 已不漂移）：{c['stale_baseline_unverifiable']}")
    assert not c["stale_baseline_entry"], out
    # ② 报告的**文字**里不得把它写成"归零未删"，也不得给**破坏性建议**。
    # ⚠️ 判据读**结构**（小节/条目），不读裸字符串：报告为了禁止 regen，正文里**提到**了
    # `--regen-baseline` 这个词 —— 拿裸 grep 当判据会被自己的文案喂红/喂绿（本仓已踩过多次）。
    assert "基线归零未删 0" in out, f"抬头没有把它归零：\n{out}"
    assert "基线条目已归零但未删" not in out, f"把它读成了「归零未删」（错误病因）：\n{out}"
    assert "怎么改（按判据逐条）" not in out, (
        f"不可判时仍在给「怎么改」小节（那一段带着 regen 建议）：\n{out}")
    assert "若确认这些是**应接受的存量**" not in out, f"**破坏性建议**又在不可判时出现了：\n{out}"
    assert "先修判据" in out, f"没有给出正确的处置（先修判据）：\n{out}"
    # ③ 机器可读报告与退出码同源
    assert rep["summary"]["tri_state"] == 3, rep["summary"]
    assert rep["summary"]["verdict"] == "crash", rep["summary"]["verdict"]


def test_same_baseline_goes_back_to_red_when_the_bad_file_is_gone(tmp_path):
    """**正对照**：同一份夹具、同一条基线，只把坏文件去掉 ⇒ 立刻「判红 + 归零未删 + regen」。

    ⇒ 证明 `3` 与 `1` **真的分开了**（不是"顺手把陈旧判定关掉了"这种假修）。
    """
    n = _mutable_baseline_count()
    repo = _fixture(tmp_path, {"good.yml": GOOD})
    rc, out, rep = _audit(repo, tmp_path)
    assert rc == 1, f"没有坏文件时应当照旧判红（陈旧条目阻塞）：rc={rc}\n{out}"
    assert rep["summary"]["stale_baseline_blocking"] == n, out
    assert "基线条目已归零但未删" in out, out
    assert "--regen-baseline" in out, out
    assert rep["summary"]["tri_state"] == 1, rep["summary"]


# ─────────────────────────────────────────────────────────────────────────────
# 判据 3：三态语义本体（纯函数，单一实现）
# ─────────────────────────────────────────────────────────────────────────────
def _rep(*, statuses: dict[str, str], new_drift: int = 0, stale_blocking: int = 0,
         dropped: int = 0, stale: int = 0, out_scope: int = 0, burn: bool = False) -> dict:
    return {"checks": [{"id": k, "status": v} for k, v in statuses.items()],
            "summary": {"new_drift": new_drift, "stale_baseline_blocking": stale_blocking,
                        "dropped_baseline_entry": dropped, "stale_baseline_entry": stale,
                        "new_drift_out_of_scope": out_scope,
                        "burn_down": {"blocking": burn}}}


@pytest.fixture(scope="module")
def drift():
    import importlib.util
    spec = importlib.util.spec_from_file_location("drift_audit_tri_state", DRIFT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["drift_audit_tri_state"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_tri_state_semantics(drift):
    """`0/1/3` 的映射，逐条钉死（`3` = 不可判，**永不当 0 读**）。"""
    t = drift.tri_state
    kw = dict(check=True, strict_stale=False, fail_on_unknown=False)
    assert t(_rep(statuses={"a": "ok"}), **kw) == 0
    assert t(_rep(statuses={"a": "known-drift"}), **kw) == 0
    # 判据崩溃 ⇒ 3（改前是 1 —— 与"确实有漂移"同码，读者分不出"没跑出结论"）
    assert t(_rep(statuses={"a": "error"}), **kw) == 3
    # 未知：**默认只报告**（既有语义不放宽 —— CI runner 上活锚天然不存在，无条件折非零 = 每个 PR 常红）
    assert t(_rep(statuses={"a": "unknown"}), **kw) == 0
    assert t(_rep(statuses={"a": "unknown"}), check=True, strict_stale=False,
             fail_on_unknown=True) == 3
    # **有结论的红优先于不可判**（先修漂移，别让"不可判"盖住"确实有问题"）
    assert t(_rep(statuses={"a": "error"}, new_drift=1), **kw) == 1
    assert t(_rep(statuses={"a": "error"}, stale_blocking=1), **kw) == 1
    assert t(_rep(statuses={"a": "error"}, dropped=1), **kw) == 1
    assert t(_rep(statuses={"a": "error"}, burn=True), **kw) == 1
    assert t(_rep(statuses={"a": "error"}, stale=1), check=True, strict_stale=True,
             fail_on_unknown=False) == 1
    # 非门禁模式（纯审计 / `--regen-baseline`）不看结论
    assert t(_rep(statuses={"a": "error"}), check=False, strict_stale=False,
             fail_on_unknown=False) == 0
    assert 0 not in (t(_rep(statuses={"a": "error"}), **kw),), "`3` 被读成了 `0`"


# ─────────────────────────────────────────────────────────────────────────────
# 判据 4：CI 接线 —— `3` 到了 workflow 里必须表现为失败/需要人看
# ─────────────────────────────────────────────────────────────────────────────
def _audit_step() -> dict:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = wf["jobs"]["audit"]["steps"]
    return next(s for s in steps if s.get("id") == "audit")


def test_workflow_wires_exit_3_to_failure_not_pass():
    """审计 step 把脚本返回码**原样** `exit`（非 0 = 失败），失败分支才打 `block/merge`。

    读的是**真正决定行为的脚本正文**（`RC=$?` → `exit $RC`），不是注释/文档措辞。
    """
    run = _audit_step()["run"]
    assert re.search(r"RC=\$\?", run), f"没有捕获脚本返回码：\n{run}"
    assert re.search(r"^\s*exit \$RC\s*$", run, re.M), (
        f"返回码没有被原样重放（可能被 `|| true` / 固定 `exit 0` 吃掉）⇒ `3` 会静默通过：\n{run}")
    assert "|| true" not in run.split("exit $RC")[0], f"返回码可能被吞：\n{run}"
    # 失败分支（`failure()`）才打 block/merge；`success()` 分支只在真通过时摘标签
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = wf["jobs"]["audit"]["steps"]
    block = next(s for s in steps if "block/merge" in (s.get("run") or ""))
    assert "failure()" in block["if"], block["if"]
    assert "github.event_name == 'pull_request'" in block["if"], block["if"]
    # 定时腿：`--fail-on-unknown` ⇒ 未知也判 3（非零），不会被读成"没漂移"
    assert "--fail-on-unknown" in run, run


def test_report_and_process_exit_code_come_from_one_implementation(tmp_path):
    """`summary.tri_state`（报告里给人/给下游读的）与进程退出码**同源**。

    否则读者会从 `verdict` 猜退出码 —— 两者一度可以相反（"抬头写 OK 而 rc=1"是本仓已修过的
    形态，见 `run_audit` 里 `verdict` 的排序注释）。
    """
    repo = _fixture(tmp_path, {"product.yml": BAD})
    rc, _out, rep = _audit(repo, tmp_path)
    assert rep["summary"]["tri_state"] == rc == 3
    # 同一份判据的**正对照**也必须同源
    repo2 = _fixture(tmp_path / "b", {"good.yml": GOOD})
    rc2, _out2, rep2 = _audit(repo2, tmp_path / "b")
    assert rep2["summary"]["tri_state"] == rc2 == 1
