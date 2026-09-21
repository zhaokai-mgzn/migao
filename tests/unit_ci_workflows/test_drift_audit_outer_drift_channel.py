# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   「CI workflow 结构由 pytest 单测验证」是 misc.yml 里已登记的形态。）
"""#5074 的「面外漂移也有人被拦」这一半（L0，离线、零 LLM、秒级）。

背景（**本包实测**，不是照抄 issue 文本）
----------------------------------------
`Drift Audit (真相源契约)` 的两条腿对同一份漂移给出相反结论：PR 腿 `--check` 对面外漂移
**恒绿**（判定面 = 本 PR 的改动集），定时腿 `--strict-stale --fail-on-unknown` 连红 6 天。
本文件锁的是「定时腿失败之后**有人**被拦」这条通道，以及**它的语义不许被读成"已拦"**。

本包**有意不做**（红证见下）：定时腿失败时给 PR 打 `block/merge`。定时腿没有 PR（标签无处
施加），而以面外漂移给「相关 PR」打标会把**修这条漂移的那个 PR 自己**拦死 —— 修复要等合并后
才生效 ⇒ 标签永远摘不掉 = `#5075` 同款自锁。故落码的是**登记 + P1 值班口径**：
  ① 定时腿失败 ⇒ 开/更 issue 并打 `priority/P1`（新建 `--label`、存量 `--add-label`）；
  ② issue 正文登记「谁被拦」：**本通道不拦合并** + **替代拦截点**（required 的 PR 腿拦面内漂移）
     + **清零判据**；
  ③ PR 腿显式报出面外条数（免得「面外」被读成「没问题」）；
  ④ 通道语义写进 `.github/workflows/drift-audit.yml` 头部（含不做 block/merge 的理由）。

红证卫生（照 `migao-dev-flow` §19.1 元规则 ③）：判据读**文件内容**（不是 mtime/size），
注入走**内容变异** ⇒ 无缓存可污染。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WF = REPO_ROOT / ".github" / "workflows" / "drift-audit.yml"
SRC = WF.read_text(encoding="utf-8")

# ── 桩：记录调用 + 抓走 `--body-file` 的内容；其余一律 exit 1（**不假装成功**）──────
GH_STUB = r"""#!/usr/bin/env bash
echo "$*" >> "$STUB_CALLS"
case "${1:-} ${2:-}" in
  "issue list") printf '%s' "${STUB_EXIST:-}" ;;
  "issue comment" | "issue edit" | "issue create")
    prev=""
    for a in "$@"; do
      if [ "$prev" = "--body-file" ]; then cp "$a" "$STUB_BODY"; fi
      prev="$a"
    done ;;
  *) echo "stub: unexpected args: $*" >&2; exit 1 ;;
esac
exit 0
"""


def _steps(src: str) -> list:
    wf = yaml.safe_load(src) or {}
    return list((wf.get("jobs") or {}).get("audit", {}).get("steps") or [])


def _run_of(src: str, needle: str) -> str:
    for step in _steps(src):
        if needle in str(step.get("name") or ""):
            return str(step.get("run") or "")
    raise AssertionError(f"找不到名字含 {needle!r} 的步骤 ⇒ 本守卫的定位方式已失效（先修本测试）")


def schedule_leg_run(src: str = SRC) -> str:
    """定时腿失败后的处置脚本（值班口径）。"""
    out = _run_of(src, "定时腿失败")
    for expr, val in (("${{ github.server_url }}", "https://github.com"),
                      ("${{ github.repository }}", "owner/repo"),
                      ("${{ github.run_id }}", "12345")):
        out = out.replace(expr, val)
    assert "${{" not in out, "步骤里还有未替换的表达式 ⇒ 桩跑的不是真脚本（先修本测试）"
    return out


def audit_leg_run(src: str = SRC) -> str:
    """PR 腿的审计脚本（含面外条数上报）。"""
    return _run_of(src, "漂移审计")


def out_scope_snippet(src: str = SRC) -> str:
    """从审计脚本里切出「面外条数上报」那一段（可单独执行，不跑整个审计）。"""
    run = audit_leg_run(src)
    start = run.index("OUT_SCOPE=")
    return run[start:run.index("exit $RC")]


def run_schedule_leg(tmp_path: Path, *, exist: str, src: str = SRC):
    """把定时腿失败后的处置**真的执行一遍**。"""
    work = tmp_path / "repo"
    work.mkdir(parents=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(GH_STUB, encoding="utf-8")
    gh.chmod(0o755)
    calls = tmp_path / "calls.txt"
    calls.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "PATH": f"{bindir}{os.pathsep}{env.get('PATH', '')}",
        "GH_TOKEN": "stub",
        "STUB_EXIST": exist,
        "STUB_CALLS": str(calls),
        "STUB_BODY": str(tmp_path / "body.md"),
    })
    p = subprocess.run(["bash", "-e", "-c", schedule_leg_run(src)],
                       cwd=work, env=env, capture_output=True, text=True)
    return p, calls.read_text(encoding="utf-8"), (tmp_path / "body.md")


def run_out_scope(tmp_path: Path, *, out_of_scope, src: str = SRC):
    """把「面外条数上报」那段**真的执行一遍**（喂一份假报告）。"""
    work = tmp_path / "repo"
    work.mkdir(parents=True)
    (work / "drift-audit-report.json").write_text(
        '{"summary": {"new_drift_out_of_scope": %s}}' % (out_of_scope,), encoding="utf-8")
    return subprocess.run(["bash", "-e", "-c", out_scope_snippet(src)],
                          cwd=work, capture_output=True, text=True)


# ── 判据本体 ──────────────────────────────────────────────────────────────────

def test_schedule_leg_failure_files_p1_issue(tmp_path):
    """① 定时腿失败 ⇒ 新建 issue 必须带 `priority/P1`（值班口径落码，不是只写在注释里）。"""
    p, calls, body = run_schedule_leg(tmp_path, exist="")
    assert p.returncode == 0, p.stdout + p.stderr
    create = [c for c in calls.splitlines() if c.startswith("issue create")]
    assert create, f"没有新建 issue 的调用：{calls!r}"
    assert "--label priority/P1" in create[0], create[0]
    text = body.read_text(encoding="utf-8")
    assert "本定时腿不拦合并" in text, "issue 正文必须登记「本通道不拦合并」（否则会被读成已拦）"
    assert "替代拦截点" in text and "清零判据" in text


def test_existing_issue_is_labelled_and_commented(tmp_path):
    """① 存量 issue ⇒ 补 P1 标签 + 追加评论（不许只评论不补标签）。"""
    p, calls, _ = run_schedule_leg(tmp_path, exist="3951")
    assert p.returncode == 0, p.stdout + p.stderr
    assert any(c.startswith("issue comment 3951") for c in calls.splitlines()), calls
    assert any(re.match(r"issue edit 3951 .*--add-label priority/P1", c) for c in calls.splitlines()), calls


def test_out_of_scope_count_is_reported_on_pr_leg(tmp_path):
    """③ PR 腿必须**显式**报出面外条数（面外恒绿，但「绿」不等于「没问题」）。"""
    p = run_out_scope(tmp_path, out_of_scope=5)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "::warning::面外新增漂移 5 条" in p.stdout
    assert "本 PR 不阻塞" in p.stdout


def test_out_of_scope_zero_is_quiet(tmp_path):
    """③ 反向：面外为 0 时不许告警（否则每个 PR 都刷一条噪声 = 告警疲劳）。"""
    p = run_out_scope(tmp_path, out_of_scope=0)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "::warning::" not in p.stdout


def test_channel_is_registered_in_header():
    """④ 通道语义 + 「不做 block/merge」的理由必须写进 workflow 头部（否则下次有人会"顺手补上"）。"""
    head = SRC.split("\non:")[0]
    assert "面外漂移的拦截点" in head
    assert "只告警 + 值班" in head
    assert "同款自锁" in head, "必须留下「不以面外漂移拦 PR」的理由（#5075 同款自锁）"
    assert "面内" in head and "block/merge" in head
    # ⚠️ 不许把「在 required 集合里」写死：清单会漂移（本包实测：该 job 当时**不在** required 里）。
    assert "现查" in head, "required 集合必须写明「现查」，不许凭名字/印象写死"


# ── 每条判据都能被**单独**注入变红 ──────────────────────────────────────────────

RED_PROOFS = [
    ("p1_label_on_create", 'gh issue create --title "$TITLE" --body-file "$BODY" --label priority/P1',
     'gh issue create --title "$TITLE" --body-file "$BODY"', "priority/P1"),
    ("p1_label_on_existing", 'gh issue edit "$EXIST" --add-label priority/P1 || true',
     'gh issue edit "$EXIST" || true', "priority/P1"),
    ("channel_registration", "── 面外漂移的拦截点", "──（未登记）", "缺通道登记"),
    ("pr_leg_mechanism", "未 arm** 的 PR 被拦", "（未写明）", "缺 PR 腿的真实拦截机制"),
    ("no_merge_block_reason", "同款自锁", "（无理由）", "同款自锁"),
    ("out_of_scope_warning", "::warning::面外新增漂移 ${OUT_SCOPE} 条", "echo 面外条数已跳过",
     "未显式上报面外新增条数"),
]


def audit_channel(src: str) -> list:
    """通道判据（空 = 合规）。纯函数，注入变异体后复用同一路径。

    ⚠️ 登记类判据只认**文件头**（`on:` 之前的注释区）—— 本仓第 N 次踩「提及 ≠ 声明」：
    通道名同时出现在 PR 腿的告警文案里，若拿全文找子串，删掉头部登记也照样判绿（空断言）。
    """
    bad = []
    head = src.split("\non:")[0]
    for needle, why in (("── 面外漂移的拦截点", "缺通道登记（#5074：别把面外恒绿读成没问题）"),
                        ("只告警 + 值班", "缺「定时腿只负责告警 + 值班，不拦合并」的登记"),
                        ("同款自锁", "缺「不以面外漂移拦 PR」的理由（#5075 同款自锁）"),
                        ("未 arm** 的 PR 被拦", "缺 PR 腿的真实拦截机制（`block/merge` 标签）")):
        if needle not in head:
            bad.append(why)
    try:
        run = schedule_leg_run(src)
        leg = audit_leg_run(src)
    except AssertionError as exc:
        return bad + [f"取不到定时腿 / PR 腿的脚本（空输入或定位方式失效）：{exc}"]
    if not re.search(r"gh issue create[^\n]*--label priority/P1", run):
        bad.append("新建 issue 未带 `--label priority/P1` ⇒ 定时腿失败不进值班口径")
    if not re.search(r'gh issue edit "\$EXIST" --add-label priority/P1', run):
        bad.append("存量 issue 未补 `--add-label priority/P1`")
    for needle in ("本定时腿不拦合并", "替代拦截点", "清零判据"):
        if needle not in run:
            bad.append(f"issue 正文缺「{needle}」（谁被拦 / 怎么拦必须写清）")
    if "::warning::面外新增漂移" not in leg:
        bad.append("PR 腿未显式上报面外新增条数 ⇒ 面外会被读成「没问题」")
    return bad


def test_real_workflow_passes_channel_audit():
    assert audit_channel(SRC) == [], audit_channel(SRC)


def test_empty_input_is_not_silently_green():
    assert audit_channel("") != [], "空输入判绿 ⇒ 守卫会静默空跑"


def test_every_channel_rule_can_be_injected_red():
    """每条通道判据都有一条**内容变异**红证（删/弱化任一条 ⇒ 该条必红）。"""
    for label, old, new, expected in RED_PROOFS:
        mutated = SRC.replace(old, new, 1)
        assert mutated != SRC, f"{label}：注入锚点失效（先修本测试）"
        violations = audit_channel(mutated)
        assert any(expected in v for v in violations), (
            f"{label}：注入后期望违规含 {expected!r}，实际 {violations}")
