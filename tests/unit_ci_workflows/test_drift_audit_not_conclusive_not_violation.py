# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""**「判不了」不得被报成「违规」** + `--repo` 不依赖 cwd（issue #8061）。

## 病（本机实测，2026-11-03，`main` = 49dd3af2e）

`drift-audit` 定时腿（`--check --strict-stale --fail-on-unknown`）连续红，而同一份报告里
同时打印着两句**互相矛盾**的结论：

```
❌ **判据不可判**（三态 `3`，**不得读成 0**）—— 它们**没有产出结论**
   · [heartbeat] status=unknown：整体不构成结论（见该判据的 notes）
...
本次相对基线的增减：… 面外新增 1（不阻塞，定时腿红） … ⇒ DRIFT
退出码（三态，实现 = `tri_state()`，与本节结论同源）：1 判红（有结论：确实有漂移…）
```

矛盾点：`heartbeat` **自己声明「本轮没读出结论」**（`GITHUB_WORKFLOW` 取不到 ⇒ `host-unknown`，
自身排除不生效），却仍把它名下那条 `drift-audit.yml 最近成功在 5 天前` 的 finding 留在
`new_drift_out_of_scope` 里 ⇒ `tri_state()` 先看计数 ⇒ 返回 **`1`（判红：有结论的红）**。
⇒ **`3`（判不了）被读成了 `1`（违规）**，违反三态口径（`3` 必须出声，但**不得**与 `1` 同码，
`docs/wiki/truth-source-contract.md` / `migao-dev-flow` §28）。

同一轮里还有第二个形态：那条 finding 是**自指替身** —— 本机正在**执行**这次审计的 workflow 就是
`drift-audit.yml` 自己，而 issue body 给出的清零判据（逐字 `--check --strict-stale --fail-on-unknown
--base origin/main` **退出 0**）因此在本机**结构性不可达**（实测改前 rc=`1`、改后 rc=`3`，都不是 `0`）。

## 本文件锁四条

1. **非结论判据的 findings 不计入阻塞计数**：`unknown` / `not_applicable` / `error` 三种状态下
   判据名下的 findings **一条都不丢**（进 `non_conclusive_findings`，报告与 JSON 都具名打印），
   但**不得**让 `new_drift` / `new_drift_out_of_scope` / `dropped_baseline_entry` / `env_findings`
   非空 —— 判据没结论时那些计数是**谎报**。
2. **退出码守三态**：同一份报告，`unknown` ⇒ `tri_state(...)=3`（出声、不得当 0 读），
   `not_applicable` ⇒ **不以「违规」码（`1`）退出**；两者都**不**折 `1`。
3. **`--repo` 不依赖 cwd**：`_anchor_git_root()` 把 `--repo` 锚到**它所在的那个 git 工作树根**
   ⇒ 根 / 子目录 / worktree 三种调用形态拿到**同一个** `preset_root()`（同一检出内），
   否则三条预设判据比的是**不同的对象**（子目录形态退到 `git` 物化的临时目录）。
4. **红证（注入式，两条各自可单独变红）**：
   - 把 `_reached_conclusion()` 注入成「一律 True」（= 修前形态）⇒ 同一份夹具立刻回到
     `面外新增 1` + `tri_state=1` ⇒ 判据 1/2 的断言**必红**；
   - 把 `_anchor_git_root()` 注入成 `Path.resolve`（= 修前形态）⇒ 子目录与根**不再是同一个**
     `preset_root` ⇒ 判据 3 的断言**必红**。

## 边界（照实登记）

- **不判**「`unknown` 该不该折非零」：那是 `--fail-on-unknown` 的既有语义（`3`，未放宽）；
  本文件只判「**不得折成 `1`**」。
- **不判**预设语料在 CI 上**该不该存在**：S4 之后业务仓已不承载 `.agent-presets/**`，
  CI 纯检出里 `not_applicable` 是**正确三态**；`scripts/drift_audit.py` 的固定基线枚举
  （`origin/main` / `origin/main~1` / `HEAD~1` / `HEAD`）是**已登记的残余**
  （`single_reader_residuals.json::restart_condition`），本文件不为它背书、也不在这里修它。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIFT = REPO_ROOT / "scripts" / "drift_audit.py"

#: 夹具预设语料（形态与 S4 之前的业务仓一致：`<repo>/.agent-presets/migao/skills/<技能>/SKILL.md`）
PRESET_DIR_REL = ".agent-presets/migao"
SKILL_REL = f"{PRESET_DIR_REL}/skills/migao-dev-flow/SKILL.md"
SKILL_TEXT = "---\nname: migao-dev-flow\nversion: 1.114.0\n---\n\n# 技能（夹具）\n"


def _load():
    """按**路径**加载被测脚本（`scripts/` 不是包；也不往 `sys.path` 里塞东西）。"""
    spec = importlib.util.spec_from_file_location("drift_audit_issue8061", DRIFT)
    assert spec and spec.loader, f"加载失败：{DRIFT}"
    mod = importlib.util.module_from_spec(spec)
    # `@dataclass` 会按 `cls.__module__` 去 `sys.modules` 里找命名空间（`from __future__ import
    # annotations` 的 ClassVar/InitVar 解析）⇒ 先登记再 exec，否则本脚本 import 阶段就炸。
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert p.returncode == 0, f"git {' '.join(args)} 失败：{p.stdout}{p.stderr}"
    return p.stdout


def _fixture_repo(tmp: Path) -> Path:
    """最小 git 仓：**真**预设语料 + 一个子目录（子目录形态是 cwd 依赖的判别面）。"""
    repo = tmp / "repo"
    (repo / Path(SKILL_REL).parent).mkdir(parents=True)
    (repo / SKILL_REL).write_text(SKILL_TEXT, encoding="utf-8")
    (repo / PRESET_DIR_REL / "preset.yml").write_text("version: 1\n", encoding="utf-8")
    (repo / "sub").mkdir()
    (repo / "sub" / "README.md").write_text("sub\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


# ─────────────────────────────────────────────────────────────────────────────
# 判据 3：`--repo` 锚到 git 工作树根 ⇒ 同一检出内三种调用形态是**同一个** preset_root
# ─────────────────────────────────────────────────────────────────────────────
def test_preset_root_is_identical_from_root_subdir_and_cwd_forms(tmp_path, monkeypatch):
    """根 / `--repo <子目录>` / **cwd = 子目录** 三种形态 ⇒ 同一个 `preset_root()`。

    子目录形态是判别面：修前（`repo = Path(args.repo).resolve()`）子目录拿不到仓内语料
    ⇒ 退到 `_preset_root_from_git()` 物化的**临时目录** ⇒ 三条预设判据比的对象变了。
    """
    da = _load()
    repo = _fixture_repo(tmp_path)
    # 镜像兜底要关掉，否则它会掩盖"子目录形态解析到别处"这件事
    monkeypatch.setenv("MIGAO_PRESET_MIRROR", str(tmp_path / "no-such-mirror"))
    want = (repo / PRESET_DIR_REL).resolve()

    from_root = da.preset_root(da._anchor_git_root(repo))
    from_sub = da.preset_root(da._anchor_git_root(repo / "sub"))
    monkeypatch.chdir(repo / "sub")                       # 真实的「cwd = 子目录」形态
    from_cwd = da.preset_root(da._anchor_git_root(Path(".")))

    assert from_root == want
    assert from_sub == want, "子目录形态解析到了另一个目录（= cwd 依赖）"
    assert from_cwd == want, "cwd = 子目录 形态解析到了另一个目录（= cwd 依赖）"


def test_preset_root_anchors_to_its_own_worktree_root(tmp_path, monkeypatch):
    """worktree 形态：锚到**该 worktree 的根**（不是主检出、不是 cwd）⇒ 同一 worktree 内一致。"""
    da = _load()
    repo = _fixture_repo(tmp_path)
    monkeypatch.setenv("MIGAO_PRESET_MIRROR", str(tmp_path / "no-such-mirror"))
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "--detach", str(wt), "main")

    monkeypatch.chdir(wt)
    from_wt_root = da.preset_root(da._anchor_git_root(Path(".")))
    from_wt_sub = da.preset_root(da._anchor_git_root(wt / "sub"))
    want = (wt / PRESET_DIR_REL).resolve()
    assert from_wt_root == want, "worktree 形态没锚到它自己的根"
    assert from_wt_sub == want, "worktree 的子目录形态没锚到它自己的根"


# ─────────────────────────────────────────────────────────────────────────────
# 判据 1 + 2：非结论判据的 findings 不计入阻塞；退出码守三态
# ─────────────────────────────────────────────────────────────────────────────
def _probe_check(da, status: str):
    """一条**声明自己没有结论**的判据，外加一条 finding（= 本单的病灶形态）。"""

    def fn(_audit):
        r = da.CheckResult("probe")
        r.findings.append(da.Finding("drift-audit.yml|stale",
                                     "夹具：某调度任务已 5 天没有成功（自指替身）"))
        if status == "not_applicable":
            return da.not_applicable(r, "夹具对象", "夹具原因（对象不在本环境）", "夹具处置")
        r.status = status
        return r

    return da.Check(id="probe", invariant="I4", title="夹具判据", judgment="夹具判定",
                    remedy="夹具处置", fn=fn)


def _report(da, repo: Path, status: str) -> dict:
    a = da.Audit(repo, base="main", offline=True, host_workflow="")
    return da.run_audit(a, {}, None, set())


def test_unknown_check_findings_do_not_count_as_conclusive_drift(tmp_path, monkeypatch):
    """`unknown` 判据名下的 findings：**一条都不丢**，但**不计入阻塞** ⇒ 退出码是 `3` 不是 `1`。"""
    da = _load()
    repo = _fixture_repo(tmp_path)
    monkeypatch.setattr(da, "CHECKS", [_probe_check(da, "unknown")])
    rep = _report(da, repo, "unknown")
    chk, s = rep["checks"][0], rep["summary"]

    assert chk["status"] == "unknown"
    # ① 读数没丢（"判不了"必须出声，不能静默）
    assert [q["kind"] for q in chk["non_conclusive_findings"]] == ["new-out-of-scope"]
    assert s["new_drift"] == 0
    assert s["new_drift_out_of_scope"] == 0
    assert chk["new_drift_out_of_scope"] == [] and chk["new_findings_detail"] == []
    assert s["verdict"] != "drift"
    # ② 不折 `1`：`unknown` 在 `--fail-on-unknown` 下折 `3`（出声，但**不得**与 `1` 同码）
    rc = da.tri_state(rep, check=True, strict_stale=True, fail_on_unknown=True)
    assert rc == 3 and rc != 1


def test_not_applicable_check_findings_never_exit_with_the_violation_code(tmp_path, monkeypatch):
    """`not_applicable` 判据名下的 findings：**不得**以「违规」码退出（对象不在 ≠ 确实有漂移）。"""
    da = _load()
    repo = _fixture_repo(tmp_path)
    monkeypatch.setattr(da, "CHECKS", [_probe_check(da, "not_applicable")])
    rep = _report(da, repo, "not_applicable")
    chk, s = rep["checks"][0], rep["summary"]

    assert chk["status"] == "not_applicable"
    assert [q["kind"] for q in chk["non_conclusive_findings"]] == ["new-out-of-scope"]
    assert s["new_drift"] == 0 and s["new_drift_out_of_scope"] == 0
    rc = da.tri_state(rep, check=True, strict_stale=True, fail_on_unknown=True)
    assert rc != 1, "把「判不了」报成了「违规」"
    assert rc == 0, "not_applicable 不折非零（既有口径，本文件不放宽）"


def test_report_names_the_withheld_findings_and_says_they_do_not_block(tmp_path, monkeypatch):
    """报告里必须**具名**列出这些读数并写明「不计入阻塞」（不许静默丢弃、也不许标成「新增漂移」）。"""
    da = _load()
    repo = _fixture_repo(tmp_path)
    monkeypatch.setattr(da, "CHECKS", [_probe_check(da, "unknown")])
    text = da.render_summary(_report(da, repo, "unknown"), {})

    assert "没有结论的判据名下的 findings" in text
    assert "夹具：某调度任务已 5 天没有成功" in text      # 那条读数被**念出来**了（未丢）
    assert "不计入阻塞" in text
    # 不能一边说"没读出结论"、一边把它标成「新增漂移」
    assert "新增漂移（**面外**" not in text
    assert "⇒ UNKNOWN" in text
    assert "3 **不可判**" not in text   # 退出码行由 main() 写入（`tri_state` 之后），render 不臆造


# ─────────────────────────────────────────────────────────────────────────────
# 判据 4：红证（注入式，两条各自可单独变红）
# ─────────────────────────────────────────────────────────────────────────────
def test_redproof_treating_a_non_conclusive_check_as_conclusive_yields_code_1(tmp_path, monkeypatch):
    """注入「把判不了当有结论」⇒ 同一份夹具立刻回到 `面外新增 1` + `tri_state=1`。

    ⇒ 上面判据 1/2 的断言（`== 0` / `== 3` / `!= 1`）在该注入下**必红**；
    修前形态就是这一支（`non_conclusive` 恒 False）。
    """
    da = _load()
    repo = _fixture_repo(tmp_path)
    monkeypatch.setattr(da, "CHECKS", [_probe_check(da, "unknown")])
    monkeypatch.setattr(da, "_reached_conclusion", lambda _res: True)     # ← 注入（= 修前行为）
    rep = _report(da, repo, "unknown")

    assert rep["summary"]["new_drift_out_of_scope"] == 1
    assert rep["summary"]["verdict"] == "drift"
    assert da.tri_state(rep, check=True, strict_stale=True, fail_on_unknown=True) == 1


def test_redproof_without_the_git_root_anchor_the_forms_disagree(tmp_path, monkeypatch):
    """注入「`--repo` 退回 cwd 原样」⇒ 子目录形态与根形态**不再是同一个** `preset_root`。

    ⇒ 判据 3 的 `from_sub == want` / `from_cwd == want` 在该注入下**必红**。
    """
    da = _load()
    repo = _fixture_repo(tmp_path)
    monkeypatch.setenv("MIGAO_PRESET_MIRROR", str(tmp_path / "no-such-mirror"))
    reverted = lambda p: Path(p).resolve()                # ← 注入（= 修前行为）

    root_form = da.preset_root(reverted(repo))
    sub_form = da.preset_root(reverted(repo / "sub"))
    assert root_form == (repo / PRESET_DIR_REL).resolve()
    assert sub_form != root_form, "注入未生效：修前形态本应把两种形态解析成不同目录"


@pytest.mark.parametrize("status", ["ok", "known-drift"])
def test_control_conclusive_checks_still_block(tmp_path, monkeypatch, status):
    """负控：**有结论**的判据照旧阻塞 —— 本包没有把守卫改瞎（只放行"没结论"这一态）。"""
    da = _load()
    repo = _fixture_repo(tmp_path)

    def fn(_audit):
        r = da.CheckResult("probe", status="ok")
        r.evaluated = 1
        r.findings.append(da.Finding("drift-audit.yml|stale", "夹具：确实有漂移"))
        return r

    monkeypatch.setattr(da, "CHECKS", [da.Check(
        id="probe", invariant="I4", title="夹具判据", judgment="夹具",
        remedy="夹具", fn=fn)])
    rep = _report(da, repo, status)
    assert rep["summary"]["new_drift_out_of_scope"] == 1
    assert da.tri_state(rep, check=True, strict_stale=True, fail_on_unknown=True) == 1
