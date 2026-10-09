# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""定时腿的**逐条点名**未知豁免（`--allow-unknown <check-id>`，issue #3951）。

## 病灶（结构性，与"有没有漂移"无关）

`scripts/drift_audit.py` 的 `check_skill_anchor` 在**活锚不存在**时**曾经**返回 `status="unknown"`，
而 `.github/workflows/drift-audit.yml` 的定时腿声明了 `--fail-on-unknown` ⇒ `tri_state()` 返回 `3`；
而 **CI runner 上活锚天然不存在、也没有任何步骤装它** ⇒ 即使 `main` 零漂移，定时腿也**必然**非零：
上线以来 **10/10 红**，`stale-report-reaper` 也因此永远收不掉它（它要求最近 3 次已完成 run 全 `success`）。

两种"看起来能修"的写法都是**降级**：① 去掉 `--fail-on-unknown` ⇒ 顺带放行**心跳/网络**类的未知
（那正是该开关要拦的假绿）；② 把 `unknown` 整体当通过 ⇒ 同一个 blanket bypass。

## 🔴 #6144 §1-C1 改判（2026-10-03）：`skill-anchor` 不再是"未知"，改判 `not_applicable`

原诊断是「活锚不存在 ⇒ `unknown` ⇒ 与"真漂移"同码」——**根因是那次的状态选错了**，
不是「豁免不够」：判定对象**在本环境里结构性地不存在**（活锚没装 / 预设语料取不到），
正确的三态是**具名的 `not_applicable`**（`not_applicable()`：`evaluated=0` + 报告末尾具名清单 +
计数声明），而**不是** `unknown`（那是"对象在、这次没读出结论"）。
⇒ 于是 `--allow-unknown skill-anchor` 这条**豁免过期**（`unknown_exemption_errors()` 当场判用法
错误 ⇒ 定时腿会 `exit 2`）⇒ 本 PR **把豁免撤掉**（豁免只许缩短，不许永久挂着）。

**豁免机制本身一个字都没放宽，本文件照旧逐条钉它**（把被测对象换成**真的会未知**的那条：

`heartbeat` —— `--offline` ⇒ `gh` 不可达 ⇒ `unknown`）。

## 本文件锁九条（每条都是**注入式**：在临时仓库里构造状态，不依赖本机）

1. **不改既有语义**：无名单时，`--fail-on-unknown` 下的 `unknown` **仍判 `3`**；
2. **新契约**：活锚不存在 ⇒ `skill-anchor` 记 **`not_applicable`**（**不是** `unknown`、**不是** `ok`），
   且报告末尾有**具名清单 + 计数声明**；`--fail-on-unknown` 下**不折非零**（行为面）；
3. **豁免不泄漏**：`--allow-unknown` 只影响**点名的那条** —— 点一个本次 `not_applicable` / `ok`
   的 id 会当场用法错误（清单必须兑现），故不可能"顺手"放行别的未知；
4. **点名的那一条真的被免**：退出 `0`，而**判据照旧打印**（状态仍 `unknown`、note 原文仍在、
   报告 `summary.unknown_exempt` 登记本轮名单、抬头 `UNKNOWN-EXEMPT` —— 不当 `ok`）；
5. **名单必须兑现（形态一）**：点名一个**不存在**的判据 id ⇒ 用法错误（非零）；
6. **名单必须兑现（形态二）**：点名的判据**本次能判**（`ok`）⇒ 用法错误（非零）
   —— 否则"我声明过"会静默腐烂成"这条永远不判"；
7. **活锚真的存在时照常判定**：活锚落后 ⇒ 该判据照旧报出漂移（读数 + 处置），豁免**吞不掉**它；
8. **接线**：豁免面穷举 —— 定时腿上**没有** `--allow-unknown`（#6144 撤掉了那条过期的），
   PR 腿也没有；
9. **整条腿的收口**：无漂移的树 + 定时腿参数 ⇒ `0`（活的未知只剩 `skill-anchor` 的
   `not_applicable`，它**不折非零**）。

## 红证（本文件自己证明得了会红）

* 把 `unknown_exemption_errors()` 的 `elif c["status"] != "unknown"` 分支删掉 ⇒ 判据 6 红；
* 把该函数的 `if c is None` 分支删掉 ⇒ 判据 5 红；
* 把 `check_skill_anchor` 的活锚缺失分支从 `not_applicable()` 改回 `status = "unknown"` ⇒ 判据 2 红；
* 把 `not_applicable()` 里的 `return` 拿去 / 让 `evaluated` 保持非零 ⇒ 判据 2 的清单/计数断言红；
* 把 `tri_state()` 的 `unknown` 折非零那条去掉 ⇒ 判据 1 红；
* 往 workflow 加 `--allow-unknown <某个 id>` ⇒ 判据 8 红。

⚠️ 夹具里的**引用类字面量**一律拼接构造（本文件同属受管引用面，见 dev-flow §18.1）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIFT = REPO_ROOT / "scripts" / "drift_audit.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "drift-audit.yml"

SKILL_REL = ".agent-presets/migao/skills/migao-dev-flow/SKILL.md"
WF_REL = ".github/workflows/fixture-daily.yml"

SKILL_TMPL = """---
name: migao-dev-flow
version: {version}
description: fixture skill
---

# fixture 技能

## 1. 三把工具

正文甲。
"""

# `heartbeat` 的**判定面**：必须有一个用 `schedule:` 的 workflow，否则它直接判 `error`
# （判定面为空 = 护栏失效），拿不到本文件需要的 `unknown`。
WF_TMPL = """name: fixture daily
on:
  schedule:
    - cron: '17 21 * * *'
jobs:
  noop:
    runs-on: ubuntu-latest
    steps:
      - run: "true"
"""

# 定时腿那一档（与 `.github/workflows/drift-audit.yml` 的 `schedule` 分支同口径）
GATE = ("--check", "--fail-on-unknown")
# 夹具里**会记 `unknown`** 的判据 = `heartbeat`（`--offline` ⇔ `gh` 不可达）。
# （#6144 起 `skill-anchor` 在活锚不存在时记 `not_applicable`，**不再**是 unknown。）
UNKNOWN_CHECK = "heartbeat"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def mk_repo(tmp: Path, skill_version: str = "1.0.0") -> Path:
    """**注入面**：临时 git 仓库（分支 `main`）—— 仓库侧技能 + 一个用 `schedule:` 的 workflow。"""
    repo = tmp / "repo"
    skill = repo / SKILL_REL
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(SKILL_TMPL.format(version=skill_version), encoding="utf-8")
    wf = repo / WF_REL
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text(WF_TMPL, encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def mk_anchor(tmp: Path, version: str = "1.0.0") -> Path:
    """**在位**的活锚（同版本、同内容 ⇒ 判据判成 `ok`）。"""
    anchor = tmp / "fake-anchor"
    skill = anchor / "skills" / "migao-dev-flow" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(SKILL_TMPL.format(version=version), encoding="utf-8")
    return anchor


def missing_anchor(tmp: Path) -> str:
    """**不存在**的活锚路径（= CI runner 上的形态）。"""
    return str(tmp / "no-such-anchor-dir")


def audit(repo: Path, *args: str, offline: bool = True) -> tuple[int, str, dict]:
    """跑**真的**审计（报告写到仓库外，不污染被测树）。

    `offline=True`（默认）让网络判据记「未知」；**给了 `--gh-fixture` 的用例要关掉它** ——
    否则心跳判据因为"离线"整条记 `unknown`，就测不到阈值本身。
    """
    out = Path(tempfile.mkdtemp()) / "drift.json"
    cmd = [sys.executable, str(DRIFT), "--repo", str(repo), "--base", "main",
           "--json", str(out)]
    if offline:
        cmd.append("--offline")
    p = subprocess.run(cmd + list(args), capture_output=True, text=True, timeout=300,
                       cwd=str(REPO_ROOT))
    rep = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    return p.returncode, p.stdout + p.stderr, rep


def check_of(rep: dict, cid: str) -> dict:
    return next(c for c in rep["checks"] if c["id"] == cid)


def audit_step_run() -> str:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"]["audit"]["steps"] if s.get("id") == "audit")["run"]


# ─────────────────────────────────────────────────────────────────────────────
# 判据 1：不改既有语义 —— 无名单时 `unknown` 仍判 `3`
# ─────────────────────────────────────────────────────────────────────────────
def test_unknown_without_allow_list_is_still_judged_3(tmp_path):
    """**既有语义不放宽**：`--fail-on-unknown` 下的 `unknown` 照旧 `3`（豁免不是"把未知当通过"）。"""
    repo = mk_repo(tmp_path)
    rc, out, rep = audit(repo, *GATE, "--only", UNKNOWN_CHECK)
    assert rc == 3, f"无名单时 unknown 没有折成 3（既有语义被改动了）：rc={rc}\n{out}"
    assert check_of(rep, UNKNOWN_CHECK)["status"] == "unknown", out
    assert rep["summary"]["unknown_exempt"] == [], rep["summary"]
    assert rep["summary"]["tri_state"] == 3, rep["summary"]
    assert "未知" in out, f"未知的原文必须可见：\n{out}"


# ─────────────────────────────────────────────────────────────────────────────
# 判据 2（#6144 §1-C1 的新契约）：活锚不存在 ⇒ `not_applicable`，**不是** unknown / ok
# ─────────────────────────────────────────────────────────────────────────────
def test_live_anchor_absent_is_not_applicable_not_unknown(tmp_path):
    """活锚不存在 ⇒ **具名 `not_applicable`** + 报告末尾具名清单 + **不折非零**。

    三件事缺一不可（否则只是把一种「说不清」换成另一种）：
      · `status == "not_applicable"` —— **不是** `unknown`（对象在才谈"没读出结论"）、
        **不是** `ok`（"没读数 ≠ 0"）；
      · `evaluated == 0` 且报告里有 `not_applicable N 条` 的**具名清单**（谁 / 为什么 / 怎么处置）；
      · `--fail-on-unknown` 下 rc == **0**（它是"不适用"，不是"不可判"）。
    """
    repo = mk_repo(tmp_path)
    rc, out, rep = audit(repo, *GATE, "--only", "skill-anchor",
                         "--live-anchor", missing_anchor(tmp_path))
    chk = check_of(rep, "skill-anchor")
    assert chk["status"] == "not_applicable", f"活锚不存在应记 not_applicable：{chk['status']}\n{out}"
    assert chk["evaluated"] == 0, chk
    assert any("not_applicable" in n and "活锚" in n for n in chk["notes"]), chk["notes"]
    # 报告末尾的**具名清单 + 计数声明**（不是静默跳过）
    assert "not_applicable 1 条" in out, f"缺具名计数声明：\n{out}"
    assert "[skill-anchor]" in out.split("not_applicable 1 条")[1], out
    assert rep["summary"]["not_applicable"] == 1, rep["summary"]
    assert rep["summary"]["not_applicable_checks"] == ["skill-anchor"], rep["summary"]
    # 它**不**参与 `--fail-on-unknown`（= 不改任何门禁的通过条件以外的东西）
    assert rc == 0, f"not_applicable 被折成了非零（与 unknown 又混在一起了）：rc={rc}\n{out}"
    assert rep["summary"]["unknown_exempt"] == [], rep["summary"]


def test_live_anchor_absent_without_flag_still_not_applicable(tmp_path):
    """反向对照：**不带** `--fail-on-unknown` 时同样是 `not_applicable`（不因开关而变）。"""
    repo = mk_repo(tmp_path)
    rc, out, rep = audit(repo, "--check", "--only", "skill-anchor",
                         "--live-anchor", missing_anchor(tmp_path))
    assert check_of(rep, "skill-anchor")["status"] == "not_applicable", out
    assert rc == 0, out


# ─────────────────────────────────────────────────────────────────────────────
# 判据 3：豁免**不泄漏** —— 名单点错对象会当场兑现失败（不可能"顺手"放行别的未知）
# ─────────────────────────────────────────────────────────────────────────────
def test_exemption_cannot_leak_to_other_unknown_checks(tmp_path):
    """`--allow-unknown` 只对**点名的那条**生效：点一个 `not_applicable` 的 id ⇒ 用法错误。

    **两向对照**（否则本判据对"豁免根本没生效"与"豁免成了 blanket"两种故障**都不敏感**）：
    · 点 `skill-anchor`（本次 `not_applicable`，**不是 unknown**）⇒ `2` 用法错误 + 报错点名它；
    · 改点 `heartbeat`（本次真 `unknown`）⇒ `0`。
    把 `unknown_exemption_errors()` 的兑现检查删掉 ⇒ 第一种会变成 `0`（豁免空转）⇒ 本判据红。
    """
    repo = mk_repo(tmp_path)
    anchor = missing_anchor(tmp_path)
    rc_bad, out_bad, _ = audit(repo, *GATE, "--only", "skill-anchor,heartbeat",
                               "--live-anchor", anchor, "--allow-unknown", "skill-anchor")
    assert rc_bad == 2, f"点名了一条 not_applicable 的判据却不是用法错误（豁免空转）：rc={rc_bad}\n{out_bad}"
    assert "不是 `unknown`" in out_bad and "skill-anchor" in out_bad, out_bad
    # 正对照：改点真的未知的那条 ⇒ 0（对照组成因可归因，不是"豁免压根没接线"）
    rc_ok, out_ok, rep_ok = audit(repo, *GATE, "--only", "skill-anchor,heartbeat",
                                  "--live-anchor", anchor, "--allow-unknown", UNKNOWN_CHECK)
    assert rc_ok == 0, f"点名的未知没有生效：rc={rc_ok}\n{out_ok}"
    assert rep_ok["summary"]["unknown_exempt"] == [UNKNOWN_CHECK], rep_ok["summary"]


# ─────────────────────────────────────────────────────────────────────────────
# 判据 4：点名的那一条真的被免 —— 但仍**照旧打印**
# ─────────────────────────────────────────────────────────────────────────────
def test_named_check_exempt_yields_zero_but_is_still_reported(tmp_path):
    """退出 `0`，而判据**没有被改写成通过**：`status` 仍 `unknown`、note 原文仍在、报告登记名单。"""
    repo = mk_repo(tmp_path)
    rc, out, rep = audit(repo, *GATE, "--only", UNKNOWN_CHECK,
                         "--allow-unknown", UNKNOWN_CHECK)
    assert rc == 0, f"点名豁免没有生效（仍判 3）：rc={rc}\n{out}"
    chk = check_of(rep, UNKNOWN_CHECK)
    assert chk["status"] == "unknown", "豁免把状态改写了（应当「未知仍在，只是不折非零」）"
    assert chk["notes"], chk["notes"]
    assert rep["summary"]["unknown_exempt"] == [UNKNOWN_CHECK], rep["summary"]
    assert rep["summary"]["tri_state"] == 0, rep["summary"]
    # 抬头**同时**说出"没有漂移"与"确有一条判据没结论"：写成 ok 是否认后者，
    # 写成 unknown 与 rc=0 相反 —— 本审计治过的正是"结论与实现相反"。
    assert rep["summary"]["verdict"] == "unknown-exempt", rep["summary"]["verdict"]
    # 「判据不可判」那一节**不得**把已豁免的判据算进去（否则报告自相矛盾）
    tail = out.split("判据不可判")[1] if "判据不可判" in out else ""
    assert f"[{UNKNOWN_CHECK}]" not in tail, f"已豁免的判据又被算进「不可判」：\n{out}"


# ─────────────────────────────────────────────────────────────────────────────
# 判据 5 / 6：名单**必须当场兑现**（两个形态）
# ─────────────────────────────────────────────────────────────────────────────
def test_allow_list_naming_no_check_is_nonzero(tmp_path):
    """点名一个**不存在**的判据 id ⇒ 用法错误（否则豁免静默空转、随判据改名而腐烂）。"""
    repo = mk_repo(tmp_path)
    rc, out, _ = audit(repo, *GATE, "--only", UNKNOWN_CHECK,
                       "--allow-unknown", "skill-anchor-typo")
    assert rc == 2, f"名单点名了不存在的判据却不是用法错误：rc={rc}\n{out}"
    assert "skill-anchor-typo" in out, f"报错必须点名那个 id（可归因）：\n{out}"
    assert "用法错误" in out, out


def test_allow_list_for_a_judgeable_check_is_nonzero(tmp_path):
    """点名的判据**本次能判**（活锚在位且一致 ⇒ `ok`）⇒ 用法错误 —— 豁免只许缩短，不许永久挂着。"""
    repo = mk_repo(tmp_path)
    rc, out, rep = audit(repo, *GATE, "--only", "skill-anchor",
                         "--live-anchor", str(mk_anchor(tmp_path)),
                         "--allow-unknown", "skill-anchor")
    assert check_of(rep, "skill-anchor")["status"] == "ok", out
    assert rc == 2, f"判据已经能判，豁免却还生效（腐烂成永久免检）：rc={rc}\n{out}"
    assert "不是 `unknown`" in out, out


# ─────────────────────────────────────────────────────────────────────────────
# 判据 7：活锚**真的存在**时照常判定 —— 豁免吞不掉真缺陷
# ─────────────────────────────────────────────────────────────────────────────
def test_live_anchor_is_judged_normally_when_it_exists(tmp_path):
    """活锚落后 ⇒ 漂移照旧报出（读数 + 处置都在报告里）；**不**因 `--allow-unknown` 而消失。"""
    repo = mk_repo(tmp_path, skill_version="1.0.0")
    rc, out, rep = audit(repo, *GATE, "--only", "skill-anchor",
                         "--live-anchor", str(mk_anchor(tmp_path, version="0.9.0")))
    chk = check_of(rep, "skill-anchor")
    assert chk["status"] == "new-drift", out
    assert any("落后" in f["detail"] for f in chk["env_findings"]), chk["env_findings"]
    assert "落后" in out, f"漂移的读数必须照旧打印：\n{out}"
    assert rc == 1, f"活锚落后必须判红：rc={rc}\n{out}"


# ─────────────────────────────────────────────────────────────────────────────
# 判据 8：接线 —— 豁免面穷举（#6144 撤掉了过期的 skill-anchor 豁免）
# ─────────────────────────────────────────────────────────────────────────────
def test_workflow_declares_no_stale_exemption_on_the_scheduled_leg():
    """机械读 workflow：豁免面 = **空**（skill-anchor 已改判 `not_applicable`，
    它那条 `--allow-unknown` 会因「名单不兑现」让定时腿当场 `exit 2`）。

    ⚠️ 本判据钉的是**当前**形态（豁免面 0 条）。将来若真的要豁免某条**真未知**的判据，
    必须**同时**改本判据并说明理由 —— 豁免面**只许缩短**，不许悄悄长回来。
    """
    run = audit_step_run()
    assert 'MODE_ARGS="--check"' in run, f"审计 step 的默认参数变了：\n{run}"
    scheduled = next((ln.strip() for ln in run.splitlines()
                      if ln.strip().startswith("MODE_ARGS=") and "--strict-stale" in ln), "")
    assert scheduled == 'MODE_ARGS="--check --strict-stale --fail-on-unknown"', (
        f"定时腿参数与预期不符（#6144 起不再豁免任何判据）：{scheduled!r}")
    # **真正被执行的那一行**不得带豁免（穷举 `MODE_ARGS=` 赋值行 —— 判「代理」而不是判全文：
    # 全文里那句 \`--allow-unknown\` 是**说明文字**（给将来要豁免时照抄的样例），不是执行面）。
    assignments = [ln.strip() for ln in run.splitlines() if ln.strip().startswith("MODE_ARGS=")]
    assert assignments, f"审计 step 里没有任何 `MODE_ARGS=` 赋值（判据的锚点没了）：\n{run}"
    assert not any("--allow-unknown" in ln for ln in assignments), (
        f"豁免面不该再有执行条目（只许缩短）：{assignments!r}")


# ─────────────────────────────────────────────────────────────────────────────
# 判据 9：整条腿的收口 —— 无漂移的树 + 定时腿参数 ⇒ `0`
# ─────────────────────────────────────────────────────────────────────────────
def test_drift_free_tree_exits_0_under_the_scheduled_leg_flags(tmp_path):
    """#6144 之后，定时腿在**无漂移的树**上真的 `0`（且**不再靠任何豁免**）。

    · `skill-anchor`：活锚不存在 ⇒ **`not_applicable`**（不折非零，无需豁免）；
    · `heartbeat`：`--gh-fixture` 给出**近期成功** ⇒ 能判、且判成 `ok`
      （`--offline` 会让它整条记 `unknown` ⇒ 必须关掉离线，见 `audit(offline=...)`）。
    """
    repo = mk_repo(tmp_path)
    fixture = tmp_path / "gh.json"
    fixture.write_text(json.dumps({"fixture-daily.yml": [
        {"status": "completed", "conclusion": "success",
         "createdAt": "2026-09-15T05:00:00Z"}]}), encoding="utf-8")
    rc, out, rep = audit(repo, "--check", "--strict-stale", "--fail-on-unknown",
                         "--only", "skill-anchor,heartbeat",
                         "--live-anchor", missing_anchor(tmp_path),
                         # #5743：本夹具里"谁在跑"与判定无关（它只测阈值本身）⇒ 显式声明
                         # 「本次没有宿主」，免得 CI 注入的真 `GITHUB_WORKFLOW` 把读数搅进来。
                         "--host-workflow", "",
                         "--gh-fixture", str(fixture), "--now", "2026-09-15T06:00:00Z",
                         offline=False)
    assert rc == 0, f"无漂移的树 + 定时腿参数仍非零：rc={rc}\n{out}"
    assert check_of(rep, "skill-anchor")["status"] == "not_applicable", out
    assert check_of(rep, "heartbeat")["status"] == "ok", out
    assert rep["summary"]["unknown_exempt"] == [], rep["summary"]


# ─────────────────────────────────────────────────────────────────────────────
# 判据 10：登记位必须**在当前树上真的被用到**（否则它就是一条没人消费的声明）
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def drift_mod():
    """按**路径**加载判据模块（不复制第二套正则/清单：有效周期只认 `drift_audit` 的实现）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("drift_audit_throttle", DRIFT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["drift_audit_throttle"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_real_repo_minute_crons_are_judged_against_the_registered_bound(drift_mod):
    """自证坐标：登记值**在当前树上被读到**，且每个分钟级 cron 的有效周期确实 = max(声明周期, 登记值)。

    这条同时钉住三种腐烂：① 登记行被删 / 被挪到 `jobs:` 之后（判据读的是**头部**）⇒ 读不到；
    ② 登记值被改到实测最坏投递间隔之下 ⇒ 结构性误红会回来；③ 分钟级 cron 全没了却留着登记
    ⇒ 台账该撤（豁免台账只许缩短）。
    """
    wf_dir = REPO_ROOT / ".github" / "workflows"
    heads = [(p.name, p.read_text(encoding="utf-8").split("\njobs:")[0])
             for p in sorted(wf_dir.glob("*.yml"))]
    throttle, problem = drift_mod._declared_throttle_minutes(heads)
    assert throttle, (
        f"读不到登记的分钟级 cron 节流上界（{problem}）⇒ 判据不放松 ⇒ 定时腿结构性误红。"
        f"登记形态 = workflow 头部 `# drift-audit: minute-cron-throttle-minutes = <N>`")
    # 实测依据：`flaky-ledger-reconcile.yml` 的 schedule 投递间隔 5h08m / 5h44m（2026-09-25）
    # ⇒ 登记值低于 330min（= 旧口径的上界 5.5h）就覆盖不住实测最坏间隔，误红会复发。
    assert throttle >= 330, (
        f"登记值 {throttle}min 低于实测最坏投递间隔（~5h44m）⇒ 「3×声明周期」式误红会复发；"
        f"要降它必须先给出新的实测依据（命令见 `docs/wiki/truth-source-contract.md` §1 I4-b 注）")
    fine = [(name, head, c) for name, head in heads for c in drift_mod.SCHED_LINE.findall(head)
            if (drift_mod._period_minutes(c) or 0)
            and drift_mod._period_minutes(c) < drift_mod.MINUTE_CRON_PERIOD_MAX]
    assert fine, (
        "当前树里已没有任何**分钟级** cron ⇒ 这条登记成了没有消费方的声明（豁免台账只许缩短）："
        "请把 workflow 头部那行 `# drift-audit: minute-cron-throttle-minutes = …` 撤掉")
    for name, _head, cron in fine:
        period = drift_mod._period_minutes(cron)
        eff, note = drift_mod._effective_period(period, throttle, problem)
        assert eff == max(period, throttle), f"{name} 的有效周期不是 max(声明周期, 登记值)：{eff}"
        assert "节流" in note, f"{name} 的报告说明没有写清「为什么用有效周期」：{note}"
