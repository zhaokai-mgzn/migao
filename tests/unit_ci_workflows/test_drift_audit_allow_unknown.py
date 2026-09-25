# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""定时腿的**逐条点名**未知豁免（`--allow-unknown <check-id>`，issue #3951）。

## 病灶（结构性，与"有没有漂移"无关）

`scripts/drift_audit.py` 的 `check_skill_anchor` 在**活锚不存在**时返回 `status="unknown"`
（"不等于通过"，语义本身正确）。而 `.github/workflows/drift-audit.yml` 的定时腿声明了
`--fail-on-unknown` ⇒ `tri_state()` 返回 `3`；而 **CI runner 上活锚天然不存在、也没有任何步骤装它**
⇒ 即使 `main` 零漂移，定时腿也**必然**非零：上线以来 **10/10 红**，`stale-report-reaper`
也因此永远收不掉它（它要求最近 3 次已完成 run 全 `success`）。

两种"看起来能修"的写法都是**降级**：① 去掉 `--fail-on-unknown` ⇒ 顺带放行**心跳/网络**类的未知
（那正是该开关要拦的假绿）；② 把 `unknown` 整体当通过 ⇒ 同一个 blanket bypass。

## 本文件锁七条（每条都是**注入式**：在临时仓库里构造状态，不依赖本机）

1. **不改既有语义**：无名单时，`--fail-on-unknown` 下的 `unknown` **仍判 `3`**；
2. **豁免不泄漏**：名单只免**点名的那一条** —— 同一次审计里另一条 `unknown`（`heartbeat`，
   `--offline` 下 gh 不可达）照旧把它折成 `3`，且它仍出现在「判据不可判」清单里；
3. **点名的那一条真的被免**：退出 `0`，而**判据照旧打印**（状态仍 `unknown`、note 原文仍在、
   报告 `summary.unknown_exempt` 登记本轮名单、抬头 `UNKNOWN-EXEMPT` —— 不当 `ok`）；
4. **名单必须兑现（形态一）**：点名一个**不存在**的判据 id ⇒ 用法错误（非零）；
5. **名单必须兑现（形态二）**：点名的判据**本次能判**（活锚在位且一致 ⇒ `ok`）⇒ 用法错误（非零）
   —— 否则"我声明过"会静默腐烂成"这条永远不判"；
6. **活锚真的存在时照常判定**：活锚落后 ⇒ 该判据照旧报出漂移（读数 + 处置），豁免**吞不掉**它；
7. **接线**：豁免**只**声明在定时 / 手动腿，且**只**点名 `skill-anchor`（PR 腿一个字都不豁免）。

## 红证（本文件自己证明得了会红）

* 把 `tri_state()` 里的 `and c["id"] not in allowed` 去掉 ⇒ 判据 2 红（豁免泄漏到 `heartbeat`）；
* 把 `unknown_exemption_errors()` 的 `elif c["status"] != "unknown"` 分支删掉 ⇒ 判据 5 红；
* 把该函数的 `if c is None` 分支删掉 ⇒ 判据 4 红；
* 把 `check_skill_anchor` 的 `status = "unknown"` 改成 `"ok"` ⇒ 判据 1/3 红（未知不复现）；
* 把 workflow 的 `--allow-unknown skill-anchor` 删掉（或加到 PR 腿）⇒ 判据 7 红。

⚠️ 夹具里的**引用类字面量**一律拼接构造（本文件同属受管引用面，见 dev-flow §18.1）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

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
# 夹具里**两条**都会记 `unknown` 的判据：`skill-anchor`（活锚不存在）+ `heartbeat`（离线 ⇔ gh 不可达）
BOTH_UNKNOWN = ("--only", "skill-anchor,heartbeat")


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


def audit(repo: Path, *args: str) -> tuple[int, str, dict]:
    """跑**真的**审计（`--offline` 只影响网络判据；报告写到仓库外，不污染被测树）。"""
    out = Path(tempfile.mkdtemp()) / "drift.json"
    p = subprocess.run(
        [sys.executable, str(DRIFT), "--repo", str(repo), "--base", "main", "--offline",
         "--json", str(out)] + list(args),
        capture_output=True, text=True, timeout=300, cwd=str(REPO_ROOT))
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
    rc, out, rep = audit(repo, *GATE, *BOTH_UNKNOWN, "--live-anchor", missing_anchor(tmp_path))
    assert rc == 3, f"无名单时 unknown 没有折成 3（既有语义被改动了）：rc={rc}\n{out}"
    assert check_of(rep, "skill-anchor")["status"] == "unknown", out
    assert check_of(rep, "heartbeat")["status"] == "unknown", out
    assert rep["summary"]["unknown_exempt"] == [], rep["summary"]
    assert rep["summary"]["tri_state"] == 3, rep["summary"]
    assert "活锚未安装" in out, f"未知的原文必须可见：\n{out}"


# ─────────────────────────────────────────────────────────────────────────────
# 判据 2：豁免**不泄漏** —— 只免点名的那一条
# ─────────────────────────────────────────────────────────────────────────────
def test_exemption_cannot_leak_to_other_unknown_checks(tmp_path):
    """豁免的粒度 = **判据 id**：同一次审计里另一条 `unknown` 照旧把结论折成 `3`。

    **两向对照**（否则本判据对"豁免根本没生效"与"豁免成了 blanket"两种故障**都不敏感**）：
    · 名单只有 `skill-anchor` ⇒ `3`（心跳的未知仍拦）；
    · 名单点名**两条** ⇒ `0`（证明上面那个 `3` 的成因**确实是**"心跳没被豁免"）。
    把 `tri_state()` 里的 `and c["id"] not in allowed` 去掉 ⇒ 第一种立刻变 `0` ⇒ 本判据红。
    """
    repo = mk_repo(tmp_path)
    anchor = missing_anchor(tmp_path)
    rc_one, out_one, rep_one = audit(repo, *GATE, *BOTH_UNKNOWN,
                                     "--live-anchor", anchor, "--allow-unknown", "skill-anchor")
    assert rc_one == 3, f"豁免泄漏到了别的判据（心跳也未知，却没折 3）：rc={rc_one}\n{out_one}"
    assert rep_one["summary"]["unknown_exempt"] == ["skill-anchor"], rep_one["summary"]
    # 「判据不可判」那一节**必须仍点名 heartbeat**，且**不得**把已豁免的 skill-anchor 算进去
    # （否则报告会自相矛盾：既说"三态 3"、又把这条写成已放行）。
    tail = out_one.split("判据不可判")[1]
    assert "[heartbeat]" in tail, f"心跳的未知没有进「不可判」清单：\n{out_one}"
    assert "[skill-anchor]" not in tail, f"已豁免的判据又被算进「不可判」（结论自相矛盾）：\n{out_one}"
    # 正对照：两条都点名 ⇒ 0（对照组成因可归因，不是"豁免压根没接线"）
    rc_both, out_both, rep_both = audit(repo, *GATE, *BOTH_UNKNOWN, "--live-anchor", anchor,
                                        "--allow-unknown", "skill-anchor",
                                        "--allow-unknown", "heartbeat")
    assert rc_both == 0, f"两条都点名却仍判 3（豁免没生效）：rc={rc_both}\n{out_both}"
    assert rep_both["summary"]["unknown_exempt"] == ["heartbeat", "skill-anchor"], rep_both["summary"]


# ─────────────────────────────────────────────────────────────────────────────
# 判据 3：点名的那一条真的被免 —— 但仍**照旧打印**
# ─────────────────────────────────────────────────────────────────────────────
def test_named_check_exempt_yields_zero_but_is_still_reported(tmp_path):
    """退出 `0`，而判据**没有被改写成通过**：`status` 仍 `unknown`、note 原文仍在、报告登记名单。"""
    repo = mk_repo(tmp_path)
    rc, out, rep = audit(repo, *GATE, "--only", "skill-anchor",
                         "--live-anchor", missing_anchor(tmp_path),
                         "--allow-unknown", "skill-anchor")
    assert rc == 0, f"点名豁免没有生效（仍判 3）：rc={rc}\n{out}"
    chk = check_of(rep, "skill-anchor")
    assert chk["status"] == "unknown", "豁免把状态改写了（应当「未知仍在，只是不折非零」）"
    assert any("活锚未安装" in n for n in chk["notes"]), chk["notes"]
    assert "活锚未安装" in out, f"未知的原文必须仍在输出里：\n{out}"
    assert rep["summary"]["unknown_exempt"] == ["skill-anchor"], rep["summary"]
    assert rep["summary"]["tri_state"] == 0, rep["summary"]
    # 抬头**同时**说出"没有漂移"与"确有一条判据没结论"：写成 ok 是否认后者，
    # 写成 unknown 与 rc=0 相反 —— 本审计治过的正是"结论与实现相反"。
    assert rep["summary"]["verdict"] == "unknown-exempt", rep["summary"]["verdict"]


# ─────────────────────────────────────────────────────────────────────────────
# 判据 4 / 5：名单**必须当场兑现**（两个形态）
# ─────────────────────────────────────────────────────────────────────────────
def test_allow_list_naming_no_check_is_nonzero(tmp_path):
    """点名一个**不存在**的判据 id ⇒ 用法错误（否则豁免静默空转、随判据改名而腐烂）。"""
    repo = mk_repo(tmp_path)
    rc, out, _ = audit(repo, *GATE, "--only", "skill-anchor",
                       "--live-anchor", missing_anchor(tmp_path),
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
# 判据 6：活锚**真的存在**时照常判定 —— 豁免吞不掉真缺陷
# ─────────────────────────────────────────────────────────────────────────────
def test_live_anchor_is_judged_normally_when_it_exists(tmp_path):
    """活锚落后 ⇒ 漂移照旧报出（读数 + 处置都在报告里），且整体是**用法错误**（名单已失效）。"""
    repo = mk_repo(tmp_path, skill_version="1.0.0")
    rc, out, rep = audit(repo, *GATE, "--only", "skill-anchor",
                         "--live-anchor", str(mk_anchor(tmp_path, version="0.9.0")),
                         "--allow-unknown", "skill-anchor")
    chk = check_of(rep, "skill-anchor")
    assert chk["status"] == "new-drift", out
    assert any("落后" in f["detail"] for f in chk["env_findings"]), chk["env_findings"]
    assert "落后" in out, f"漂移的读数必须照旧打印（豁免不能把报告也吞掉）：\n{out}"
    # `2` = 用法错误：判据**已经能判**（这里是"确实有漂移"）⇒ 豁免当场失效，**不许**被豁免吞掉。
    assert rc == 2, f"活锚存在时豁免仍生效（吞掉了真缺陷）：rc={rc}\n{out}"


# ─────────────────────────────────────────────────────────────────────────────
# 判据 7：接线 —— 豁免只在定时 / 手动腿，且只点名 skill-anchor
# ─────────────────────────────────────────────────────────────────────────────
def test_workflow_declares_a_single_named_exemption_on_the_scheduled_leg():
    """机械读 workflow：豁免面 = **恰好一条** `skill-anchor`，且 PR 腿一个字都不豁免。"""
    run = audit_step_run()
    default = 'MODE_ARGS="--check"'
    assert default in run, f"审计 step 的默认（PR 腿）参数变了：\n{run}"
    assert "--allow-unknown" not in default, (
        f"PR 腿也带上了豁免 —— 那会把同一条 blanket bypass 漏进门禁：\n{run}")
    scheduled = next((ln.strip() for ln in run.splitlines()
                      if ln.strip().startswith("MODE_ARGS=") and "--strict-stale" in ln), "")
    assert scheduled == ('MODE_ARGS="--check --strict-stale --fail-on-unknown '
                         '--allow-unknown skill-anchor"'), (
        f"定时腿的参数与预期不符（豁免必须**逐条点名**、且仍带 --fail-on-unknown）：{scheduled!r}")
    # 豁免面穷举：整个 workflow 里 `--allow-unknown` 后面只许跟 skill-anchor 这一个 id
    # （多一条 ⇒ 有人悄悄扩大了 blanket 面）。
    ids = set(re.findall(r"--allow-unknown\s+([A-Za-z0-9_\-]+)",
                         WORKFLOW.read_text(encoding="utf-8")))
    assert ids == {"skill-anchor"}, f"豁免面被扩大了（只许 skill-anchor）：{sorted(ids)}"
