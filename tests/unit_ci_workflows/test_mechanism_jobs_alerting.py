# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
r"""「机制/簿记类 job 自身失败不得静默」守卫（issue #5076 的 ① 类）。

## 背景

`python3 scripts/merge_gate.py --required-diff` 把 17 条 job 列为「会判红但不拦合并」。
#5076 的裁定把其中 6 条归为**① 机制/簿记类** —— 它们判红**只说明它自己没跑成，不代表代码错**
⇒ 不该翻 required（翻了会误伤），但**自身失败时必须有告警、不得静默**。

本文件锁其中 3 条（另 3 条在别的包的白名单里）：

| job | 文件 | 改前的静默形态 |
|---|---|---|
| `Enable auto-merge` | `.github/workflows/automerge.yml` | `gh pr merge --auto` 的非零返回被 `\|\| echo` 一律吞成 `⚠️` warning，**真失败与幂等正常同形** |
| `Check Closes #xx` | `.github/workflows/pr-issue-link.yml` | API 报错时 `github-script` 抛错 → job 红，但**没有 `::error::` 也没有 step summary**，读者只看到「少一个标签」 |
| `Close linked issues (compensation + reconcile)` | `.github/workflows/close-linked-issues.yml` | 部分失败路径（单 PR 查询失败 / `gh pr list` 失败 / 关闭失败）**未写 step summary**，step 红而 summary 空 |

## 本文件锁什么

**「真失败」必须三件齐全**：`::error::` 注解 + step summary 落笔 + **非零退出**（PR 检查列表里真的红）；
**「幂等/预期内」的非零返回**必须**非阻塞**（exit 0）且**文案明确**（读者能一眼区分两者）。
每条判据都配「注入后必红」的对照，证明判据本身会红（不是恒真）。

## 另锁一条：后置回读的**三态**（issue #5113）

`Enable auto-merge` 的「arm 后回读 `autoMergeRequest`」在 `mergeable == UNKNOWN`（GitHub 尚在计算
可合并性）时会判红 —— 那是**误报**：不是"没 arm"，是"**还没算完**"。`TestAutomergeReadbackThreeStates`
用三个夹具把三态钉死（**先退避重试、再按 `mergeable` 分流**）：
夹具 A（`null` + `UNKNOWN`）⇒ unknown **非红**；夹具 B（`null` + `MERGEABLE`）⇒ **仍判红**；
夹具 C（第一次 `null`、第二次 `armed`）⇒ 判绿（退避生效）。三条各自能**单独变红**（对真脚本做单点变异）。

## 测试方式

**真跑** workflow 里的 `run:` 文本（不重写判定逻辑），PATH 前置一个 `gh` 桩（bash）提供可控世界；
判据全部来自行为（stdout/stderr 标记 / step summary 文本 / 退出码 / gh 调用记录），不来自实现细节。
`pr-issue-link.yml` 的 job 是单个 `actions/github-script` step（本机无法执行 github-script），
故那一组读**脚本正文**做结构判据 —— 但它配了**变异红证**（把 workflow 文本改坏 ⇒ 判据必红）。
"""
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

AUTOMERGE = WORKFLOWS / "automerge.yml"
PR_ISSUE_LINK = WORKFLOWS / "pr-issue-link.yml"
CLOSE_LINKED = WORKFLOWS / "close-linked-issues.yml"

# ---------------------------------------------------------------- 通用工具

# #5235 追加两个**可选**注入面（不设时既有行为逐字不变）：
#   · `STUB_EXIT_SEQ`：按调用次序给退出码（一行一次，用尽后沿用最后一个）——
#     用来表达「第一次瞬时失败、第二次成功」（arm 有界重试的判据需要它）；
#   · `STUB_ARMED_FILE`：把 GitHub 的**因果**建进桩里 —— 只有 `gh pr merge` **成功**过
#     才会写下这个文件，而 `autoMergeRequest` 回读据此给 `armed`/`none`。
#     ⇒ 「绿」不再能靠固定喂 `armed` 凑出来：重试被拿掉就必须判红（判据有判别力）。
# `gh` 桩：行为完全由环境变量决定（STUB_EXIT / STUB_STDERR / STUB_STDOUT）。
# ⚠️ 必须**真的实现 `--jq`**：真 `gh` 会把 JSON 先过 jq 再输出，桩若原样吐 JSON，
#    被测脚本的 `case "$state"` 就会走到 `*`（不可解析）分支 —— 那是**桩的缺陷**，
#    不是 workflow 的缺陷（本 PR 初版就在这里假红过一次）。
GH_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_CALL_LOG"
payload="${STUB_STDOUT:-}"
# 取 --jq 表达式（`--jq '<expr>'` 或 `--jq=<expr>`）
jqexpr=""
prev=""
for a in "$@"; do
  if [ "$prev" = "--jq" ]; then jqexpr="$a"; fi
  case "$a" in --jq=*) jqexpr="${a#--jq=}";; esac
  prev="$a"
done
# 退出码：常量（STUB_EXIT）或按调用次序（STUB_EXIT_SEQ，用尽后沿用最后一个）
code="${STUB_EXIT:-0}"
if [ -n "${STUB_EXIT_SEQ:-}" ]; then
  first="$(head -n 1 "$STUB_EXIT_SEQ")"
  rest="$(tail -n +2 "$STUB_EXIT_SEQ")"
  printf '%s\n' "${rest:-$first}" > "$STUB_EXIT_SEQ"
  code="${first:-0}"
fi
# 因果桩：`gh pr merge` 成功 ⇒ 记一笔（供 autoMergeRequest 回读使用）
if [ "$1" = "pr" ] && [ "$2" = "merge" ] && [ "$code" = "0" ] && [ -n "${STUB_ARMED_FILE:-}" ]; then
  : > "$STUB_ARMED_FILE"
fi
jq_py() {
  STUB_JQ_IN="$payload" STUB_JQ_EXPR="$jqexpr" python3 - <<'PYJQ'
import json, os, sys
raw = os.environ["STUB_JQ_IN"]
expr = os.environ["STUB_JQ_EXPR"]
try:
    data = json.loads(raw)
except Exception:
    sys.stdout.write(raw)
    sys.exit(0)
if "autoMergeRequest" in expr:
    amr = data.get("autoMergeRequest")
    sys.stdout.write("none" if amr is None else "armed")
elif "@tsv" in expr:
    n = data.get("number", "")
    sha = (data.get("mergeCommit") or {}).get("oid") or ""
    body = (data.get("body") or "").replace("\n", "\\n").replace("\t", "\\t")
    sys.stdout.write("%s\t%s\t%s\t%s" % (n, sha, body, data.get("mergedAt") or ""))
else:
    sys.stdout.write(raw)
PYJQ
}

# 判据只读「gh 实际返回了什么」⇒ 桩必须能按**调用次序**给出不同答案（#5113 夹具 A/B/C 用）。
# 两个注入变量都未设时，走 jq_py 原路径 ⇒ 既有判据的行为逐字不变。
if [ -n "$jqexpr" ]; then
  case "$jqexpr" in
    # STUB_AMR_SEQ：`autoMergeRequest` 回读的 jq 输出按行取用（用尽后**沿用最后一个值**）
    # ⇒ 可表达「arm 的传播延迟」（第一次 none、第二次 armed）。
    *autoMergeRequest*)
      if [ -n "${STUB_AMR_SEQ:-}" ]; then
        first="$(head -n 1 "$STUB_AMR_SEQ")"
        rest="$(tail -n +2 "$STUB_AMR_SEQ")"
        printf '%s\n' "${rest:-$first}" > "$STUB_AMR_SEQ"
        payload="$first"
      elif [ -n "${STUB_ARMED_FILE:-}" ]; then
        if [ -e "$STUB_ARMED_FILE" ]; then payload="armed"; else payload="none"; fi
      else
        payload="$(jq_py)"
      fi ;;
    # STUB_MERGEABLE：`gh pr view --json mergeable` 的 jq 输出（UNKNOWN / MERGEABLE / …）。
    *.mergeable*)
      payload="${STUB_MERGEABLE:-$(jq_py)}" ;;
    *)
      payload="$(jq_py)" ;;
  esac
fi
if [ -n "$payload" ]; then printf '%s\n' "$payload"; fi
if [ -n "${STUB_STDERR:-}" ]; then printf '%s\n' "$STUB_STDERR" >&2; fi
exit "$code"
"""

# `sleep` 桩（#5113 夹具）：退避等待被**记录**而不是真的睡 ⇒ 新夹具能确定性地断言退避序列
# （`2/4/6/8`），不靠墙钟计时；既有测试本来不睡，故其行为不受影响。
SLEEP_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "${SLEEP_CALL_LOG:-/dev/null}"
exit 0
"""


def _load(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _job(doc, name):
    return (doc.get("jobs") or {})[name]


def _step(doc, job_name, name_contains):
    for s in _job(doc, job_name).get("steps") or []:
        if name_contains in (s.get("name") or ""):
            return s
    return None


def _run_text(doc, job_name):
    return "\n".join(s.get("run") or "" for s in _job(doc, job_name).get("steps") or [])


class World:
    """可控世界：`gh` 桩 + 被测 `run:` 文本 + 结果（stdout/stderr/退出码/summary）。"""

    def __init__(self, tmp_path, run_text, env=None):
        self.tmp = Path(tmp_path)
        self.bin = self.tmp / "bin"
        self.bin.mkdir(parents=True, exist_ok=True)
        gh = self.bin / "gh"
        gh.write_text(GH_STUB, encoding="utf-8")
        gh.chmod(0o755)
        sleep = self.bin / "sleep"
        sleep.write_text(SLEEP_STUB, encoding="utf-8")
        sleep.chmod(0o755)
        self.call_log = self.tmp / "gh-calls.log"
        self.sleep_log = self.tmp / "sleep-calls.log"
        self.summary = self.tmp / "summary.md"
        self.run_file = self.tmp / "run.sh"
        self.run_file.write_text(run_text, encoding="utf-8")
        self.extra_env = dict(env or {})

    def run(self, **overrides):
        env = dict(os.environ)
        env.update({
            "PATH": str(self.bin) + os.pathsep + env.get("PATH", ""),
            "GH_CALL_LOG": str(self.call_log),
            "SLEEP_CALL_LOG": str(self.sleep_log),
            "GH_TOKEN": "stub",
            "GH_REPO": "zhaokai-mgzn/migao",
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "STUB_EXIT": "0",
            # 🔴 有意钉成 **非 UTF-8 locale**（本 PR 实测的真实缺陷形态）：
            #   `LANG=C` 下 bash 会把紧跟 `$rc` 的多字节字符（如 `：`）的**首字节**
            #   当成变量名的一部分 ⇒ `rc\xef: unbound variable`（`set -u` 直接崩）。
            #   CI runner 的 locale 不保证是 UTF-8 ⇒ 这是「本地绿 / CI 红」的静默失效形态。
            #   钉死它之后，脚本必须写 `${rc}`（花括号定界）才稳。
            "LANG": "C",
            "LC_ALL": "C",
        })
        env.update(self.extra_env)
        env.update({k: str(v) for k, v in overrides.items()})
        self.proc = subprocess.run(["bash", str(self.run_file)], capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   env=env, timeout=120)
        return self

    @property
    def rc(self):
        return self.proc.returncode

    @property
    def out(self):
        return self.proc.stdout + self.proc.stderr

    @property
    def calls(self):
        if not self.call_log.exists():
            return []
        return self.call_log.read_text(encoding="utf-8").splitlines()

    @property
    def sleeps(self):
        """退避等待的参数序列（`sleep` 桩记录的实参；不真的睡）。"""
        if not self.sleep_log.exists():
            return []
        return self.sleep_log.read_text(encoding="utf-8").split()

    def summary_text(self):
        return self.summary.read_text(encoding="utf-8") if self.summary.exists() else ""


def _has_error_annotation(text):
    return bool(re.search(r"^::error::", text, re.M))


def _has_warning_annotation(text):
    return bool(re.search(r"^::warning::", text, re.M))


# ================================================================ ① automerge

AUTOMERGE_ENV = {
    "GITHUB_EVENT_NAME": "pull_request_target",
    "GITHUB_EVENT_ACTION": "opened",
    "PR_NUMBER": "1234",
    "GITHUB_REPOSITORY": "zhaokai-mgzn/migao",
    "GH_REPO": "zhaokai-mgzn/migao",
}

# `gh pr view --json autoMergeRequest` 已 arm 时的真实形状（本机实测 PR #5098）：
ARMED_JSON = ('{"autoMergeRequest":{"mergeMethod":"SQUASH",'
              '"enabledBy":{"login":"app/github-actions"}}}')
NOT_ARMED_JSON = '{"autoMergeRequest":null}'


def _automerge_script():
    doc = _load(AUTOMERGE)
    step = _step(doc, "enable-auto-merge", "auto-merge") or {}
    run = step.get("run") or ""
    assert "gh pr merge" in run, (
        f"automerge.yml 的 Enable auto-merge step 必须真的执行 gh pr merge；实际 run={run[:80]!r}"
    )
    return run


class TestAutomergeRealFailureIsLoud:
    """`Enable auto-merge`：真失败必须红，幂等正常必须静默放行。"""

    def test_arm_failure_is_an_error_not_a_warning(self, tmp_path):
        """改前：`|| echo "⚠️ …非错误"` 把**任何**非零返回吞成 warning（真失败与幂等同形）。

        改后：`gh pr merge --auto` 真失败（无幂等标记）⇒ `::error::` + step summary + 非零退出。
        """
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT=1, STUB_STDERR="HTTP 403: Resource not accessible by integration",
        )
        assert w.rc != 0, (
            "gh pr merge --auto 真失败却以 0 退出 ⇒ 该 job 永远绿，静默没 arm 无人知晓"
        )
        assert _has_error_annotation(w.out), f"真失败必须打 ::error::；实际输出：\n{w.out}"
        assert "summary" in w.summary_text() or "auto-merge" in w.summary_text().lower(), (
            f"真失败必须写 step summary（读者在 PR 页面能看见）；实际：{w.summary_text()!r}"
        )

    def test_idempotent_failure_stays_non_blocking_with_explicit_text(self, tmp_path):
        """幂等/预期内的非零返回（已在 merge queue）⇒ **非阻塞** + 文案明确，不得刷红。"""
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT=1, STUB_STDERR="already in merge queue",
        )
        assert w.rc == 0, (
            "已在 merge queue 属预期内（幂等）⇒ 必须非阻塞；"
            f"实际退出码 {w.rc}，输出：\n{w.out}"
        )
        assert not _has_error_annotation(w.out), "预期内的幂等情形不得打 ::error::"
        assert "幂等" in w.out or "预期内" in w.out, (
            f"幂等分支必须有明确文案（读者能区分它和真失败）；实际输出：\n{w.out}"
        )

    def test_success_path_is_quiet(self, tmp_path):
        """正常 arm 成功（后置条件查得 armed）⇒ 零告警、退出 0。"""
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT=0, STUB_STDOUT=ARMED_JSON,
        )
        assert w.rc == 0, f"已 arm 的成功路径必须退出 0；实际 rc={w.rc}\n{w.out}"
        assert not _has_error_annotation(w.out), f"成功路径不得打 ::error::：\n{w.out}"

    def test_does_not_swallow_every_nonzero_with_bare_or_echo(self, tmp_path):
        """判据的**形态**：脚本不得再出现「`|| echo` 一律吞掉 `gh pr merge` 非零返回」。

        注入红证（见 test_bare_or_echo_pattern_is_detectable）：把 `|| echo` 放回 ⇒ 本判据必红。
        """
        script = _automerge_script()
        assert not re.search(r"gh pr merge[\s\S]{0,200}?\|\|\s*echo", script), (
            "`gh pr merge … || echo` 把真失败与幂等正常吞成同一个 warning —— #5076 ① 类的原始形态"
        )

    def test_bare_or_echo_pattern_is_detectable(self):
        """变异红证：上面那条形态判据在「坏文本」上必须判红（证明判据会红）。"""
        bad = 'gh pr merge "$N" --auto --squash || echo "⚠️ 非错误"'
        assert re.search(r"gh pr merge[\s\S]{0,200}?\|\|\s*echo", bad), (
            "变异文本未被判据命中 ⇒ 该判据恒绿（空断言）"
        )


class TestAutomergePostcondition:
    """#4829 的「静默没 arm」：命令成功 ≠ 真的 arm 上了 ⇒ 必须有后置条件判据。"""

    def test_armed_success_is_quiet(self, tmp_path):
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT=0, STUB_STDOUT=ARMED_JSON,
        )
        assert w.rc == 0, f"已 arm 却判红（误伤）：\n{w.out}"
        assert not _has_error_annotation(w.out)

    def test_not_armed_after_success_is_loud(self, tmp_path):
        """`gh pr merge --auto` 返回 0、但 PR 的 autoMergeRequest 仍是 null ⇒ 真·静默没 arm。

        这是 #4829 登记过的形态（disarm 后 push 重新 arm / 已 arm 却卡合并），
        「命令成功」不能当判据 —— 必须查 PR 的实际 auto-merge 状态。
        """
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT=0, STUB_STDOUT=NOT_ARMED_JSON,
        )
        assert w.rc != 0, (
            "autoMergeRequest 为 null（= 没 arm 上）却报成功 ⇒ 正是「静默没 arm」的事故形态"
        )
        assert _has_error_annotation(w.out), f"未 arm 必须打 ::error::：\n{w.out}"
        assert w.summary_text().strip(), "未 arm 必须写 step summary"

    def test_state_query_failure_is_loud_not_assumed_ok(self, tmp_path):
        """后置查询本身失败 ⇒ 不得当「已 arm」读（三态：armed / not-armed / unknown）。"""
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT=0, STUB_STDOUT="",
        )
        assert w.rc != 0, "后置状态无法判定（查询无输出）时不得静默成功"
        assert _has_error_annotation(w.out), f"无法判定必须打 ::error::：\n{w.out}"

    def test_state_query_non_json_is_loud(self, tmp_path):
        """查询返回不可解析内容（非 JSON / 半截输出）同样属 unknown ⇒ 不得静默成功。"""
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT=0, STUB_STDOUT="not-json",
        )
        assert w.rc != 0, "不可解析的后置状态不得当「已 arm」读"
        assert _has_error_annotation(w.out), f"不可解析必须打 ::error::：\n{w.out}"


# ------------------------------------------------ ① automerge · 后置回读三态（#5113）

def _amr_seq(tmp_path, *values):
    """`autoMergeRequest` 回读的**按序**输出（一行一次；用尽后沿用最后一个值）。"""
    p = Path(tmp_path) / "amr-seq.txt"
    p.write_text("\n".join(values) + "\n", encoding="utf-8")
    return str(p)


def _mutate(script, old, new):
    """对**真脚本源码文本**做单点变异（不 mock 被测函数；锚点漂移即测试自身失败）。"""
    assert old in script, f"变异锚点不存在（脚本已漂移）：{old!r}"
    return script.replace(old, new, 1)


UNKNOWN_GATE = 'if [ "$mergeable" = "UNKNOWN" ]; then'


class TestAutomergeReadbackThreeStates:
    """#5113：`mergeable == UNKNOWN`（GitHub 尚在计算可合并性）时**不得把「无从判定」渲染成红**。

    实测（PR #5106 的 run 35677848752，2026-09-22T01:59:24Z）：`gh pr merge --auto` 零输出、rc=0，
    同一时刻 `gh pr view 5106 --json mergeable` = `UNKNOWN` ⇒ 回读 `autoMergeRequest` 仍为 `null`
    ⇒ 旧实现走 `exit 1` 报「未 arm（静默失效）」。那是**误报**：不是"没 arm"，是"还没算完"。

    三态口径（`migao-dev-flow` §19.2）：绿 = 判据真跑过且通过；红 = 真跑过且失败；
    **unknown = 判据没跑成，既不得当红也不得当绿**。本仓的 unknown 只能这样落地：GitHub Actions
    的 step 只有红/绿二值（neutral 要 Checks API / GitHub App），且本 job 的 step 列表被
    `tests/unit_ci_workflows/test_automerge_bot_safe_path.py` 逐字钉死（不得拆出第二个 step）
    ⇒ unknown = `exit 0` + `::warning::` 注解 + step summary 写明「无从判定」，
    语义由**注解与 summary**承载，**不由退出码**承载。

    三个夹具各自**能单独变红**（变异锚点 = 真脚本源码文本，不是断言自己的文案）。
    """

    def test_fixture_a_unknown_mergeable_is_not_red(self, tmp_path):
        """夹具 A：`null` + `mergeable=UNKNOWN` ⇒ unknown（**不是红**），summary 说明「无从判定」。"""
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT=0, STUB_AMR_SEQ=_amr_seq(tmp_path, "none"), STUB_MERGEABLE="UNKNOWN")
        assert w.rc == 0, (
            f"mergeable=UNKNOWN 时把「无从判定」渲染成红 = #5113 的误报形态；rc={w.rc}\n{w.out}"
        )
        assert not _has_error_annotation(w.out), f"unknown 不得打 ::error::：\n{w.out}"
        assert _has_warning_annotation(w.out), f"unknown 必须可见（::warning::）：\n{w.out}"
        assert "无从判定" in w.summary_text(), f"summary 必须写明「无从判定」：{w.summary_text()!r}"
        assert "unknown" in w.summary_text(), f"summary 必须标明三态=unknown：{w.summary_text()!r}"
        # 退避真的跑满：5 次回读 ⇒ 4 次等待（2/4/6/8 秒），且不因误判提前放弃
        assert w.sleeps == ["2", "4", "6", "8"], f"退避序列不符：{w.sleeps}"
        assert sum(1 for c in w.calls if "autoMergeRequest" in c) == 5, w.calls

    def test_fixture_a_mutation_turns_it_red(self, tmp_path):
        """夹具 A 的红证：把 UNKNOWN 分流闸换成 `false` ⇒ A 立刻变红（证明 A 的「非红」有判别力）。"""
        src = _mutate(_automerge_script(), UNKNOWN_GATE, "if false; then")
        w = World(tmp_path, src, env=AUTOMERGE_ENV).run(
            STUB_EXIT=0, STUB_AMR_SEQ=_amr_seq(tmp_path, "none"), STUB_MERGEABLE="UNKNOWN")
        assert w.rc != 0, "打掉 UNKNOWN 分流闸后夹具 A 仍判「非红」⇒ 夹具 A 的红证没有判别力"

    def test_fixture_b_mergeable_but_not_armed_is_still_red(self, tmp_path):
        """夹具 B：`null` + `mergeable=MERGEABLE`（算完了却没 arm）⇒ **仍然判红**（真静默失效）。"""
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT=0, STUB_AMR_SEQ=_amr_seq(tmp_path, "none"), STUB_MERGEABLE="MERGEABLE")
        assert w.rc != 0, (
            "可合并性已算出（MERGEABLE）却仍没 arm ⇒ 必须判红（#4829 的捕获力不得丢）；"
            f"rc={w.rc}\n{w.out}"
        )
        assert _has_error_annotation(w.out), f"真静默失效必须打 ::error::：\n{w.out}"
        assert w.summary_text().strip(), "真静默失效必须写 step summary"

    def test_fixture_b_mutation_turns_it_green(self, tmp_path):
        """夹具 B 的红证（反向）：把 UNKNOWN 分流闸放宽成 `true` ⇒ B 变绿 ⇒ B 的红来自该判据。"""
        src = _mutate(_automerge_script(), UNKNOWN_GATE, "if true; then")
        w = World(tmp_path, src, env=AUTOMERGE_ENV).run(
            STUB_EXIT=0, STUB_AMR_SEQ=_amr_seq(tmp_path, "none"), STUB_MERGEABLE="MERGEABLE")
        assert w.rc == 0, "把 UNKNOWN 分流闸放宽成无条件后夹具 B 仍判红 ⇒ 夹具 B 的红证没有判别力"

    def test_fixture_c_backoff_recovers_from_propagation_delay(self, tmp_path):
        """夹具 C：第一次 `null`、第二次 `armed`（模拟 arm 的传播延迟）⇒ **判绿**（退避生效）。"""
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT=0, STUB_AMR_SEQ=_amr_seq(tmp_path, "none", "armed"))
        assert w.rc == 0, f"第二次回读已 armed 却仍判红（退避没生效）：rc={w.rc}\n{w.out}"
        assert not _has_error_annotation(w.out), f"已 arm 不得打 ::error::：\n{w.out}"
        assert sum(1 for c in w.calls if "autoMergeRequest" in c) == 2, w.calls
        assert w.sleeps == ["2"], f"应恰好退避一次（2 秒）：{w.sleeps}"

    def test_fixture_c_without_backoff_is_red(self, tmp_path):
        """夹具 C 的红证：把重试次数压成 1（打掉退避）⇒ C 变红（证明绿来自退避本身）。"""
        src = _mutate(_automerge_script(), 'while [ "$attempt" -lt 5 ]; do',
                      'while [ "$attempt" -lt 1 ]; do')
        w = World(tmp_path, src, env=AUTOMERGE_ENV).run(
            STUB_EXIT=0, STUB_AMR_SEQ=_amr_seq(tmp_path, "none", "armed"))
        assert w.rc != 0, "打掉退避重试后夹具 C 仍判绿 ⇒ 夹具 C 的红证没有判别力"

    def test_readback_query_failure_still_red(self, tmp_path):
        """**边界（有意收窄）**：读不到 `autoMergeRequest`（查询失败）仍 fail-closed 判红。

        只有**逐字 `mergeable=UNKNOWN`** 才分流到 unknown —— 读不到可合并性时宁可多报一次，
        也不静默放过（与本 job 既有的 fail-closed 口径一致）。
        """
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT=0, STUB_AMR_SEQ=_amr_seq(tmp_path, ""), STUB_MERGEABLE="UNKNOWN")
        assert w.rc != 0, "回读查询本身失败时不得静默成功（三态里的 unknown 是「可合并性未算完」）"
        assert _has_error_annotation(w.out), f"回读查询失败必须打 ::error::：\n{w.out}"


# ------------------------------------------------ ① automerge · arm 有界重试（#5235 族 A）

def _exit_seq(tmp_path, *codes):
    """`gh` 桩的退出码序列（一行一次；用尽后沿用最后一个）。"""
    p = Path(tmp_path) / "exit-seq.txt"
    p.write_text("\n".join(str(c) for c in codes) + "\n", encoding="utf-8")
    return str(p)


# 实测形态（run `35872446921` 的 PR #5234 / `35871475072` 的 PR #5232，逐字输出）：
# GitHub 侧**瞬时** GraphQL 错误（带 request-id），同一 run 的权限面是
# `Contents: write / PullRequests: write` ⇒ 不是权限缺口 ⇒ 修法是重试。
TRANSIENT_GRAPHQL = ("GraphQL: Something went wrong while executing your query on "
                     "2026-09-23T14:12:31Z. Please include `4829:3FD750:2EC91:9A0B5:6AB3DE4E` "
                     "when reporting this issue.")


class TestAutomergeArmRetry:
    """#5235 族 A：arm 腿失败**没有重试** ⇒ PR 停在「required 全绿但永不合并」。

    两条判据缺一不可（**双侧读数**）：
    · 第一次瞬时失败、重试后成功且回读 `armed` ⇒ **绿**（重试真的修好了它）；
    · 重试都失败 **且**回读仍 `none` ⇒ **红**（`::error::` + summary + 非零退出；
      「真失败吞成 warning」这条老路被堵死）。
    判据本体仍是**回读**的 `autoMergeRequest`（#4829 的既有口径：命令成功 ≠ 真的 arm 上了）。
    """

    def test_transient_failure_is_recovered_by_retry(self, tmp_path):
        """第一次 `gh pr merge` 瞬时失败、第二次成功 ⇒ **判绿**（这正是事故的真因形态）。"""
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT_SEQ=_exit_seq(tmp_path, 1, 0), STUB_STDERR=TRANSIENT_GRAPHQL,
            STUB_ARMED_FILE=str(Path(tmp_path) / "armed.flag"))
        assert w.rc == 0, f"重试后已 arm 却判红：rc={w.rc}\n{w.out}"
        assert not _has_error_annotation(w.out), f"重试成功的路径不得打 ::error::：\n{w.out}"
        assert len([c for c in w.calls if c.startswith("pr merge")]) == 2, w.calls
        assert w.sleeps == ["5"], f"应恰好退避一次（5 秒）：{w.sleeps}"

    def test_retry_removal_turns_the_recovery_case_red(self, tmp_path):
        """**变异红证**：把重试上界压成 1 次 ⇒ 上一条的「绿」立刻变红（判别力证明）。

        桩把因果建进来了（只有 `gh pr merge` **成功**过，回读才给 `armed`）⇒
        这里的"绿"不可能来自回读被固定喂 `armed`。
        """
        src = _mutate(_automerge_script(), 'while [ "$m_attempt" -lt "$MERGE_ATTEMPTS" ]; do',
                      'while [ "$m_attempt" -lt 1 ]; do')
        w = World(tmp_path, src, env=AUTOMERGE_ENV).run(
            STUB_EXIT_SEQ=_exit_seq(tmp_path, 1, 0), STUB_STDERR=TRANSIENT_GRAPHQL,
            STUB_ARMED_FILE=str(Path(tmp_path) / "armed.flag"))
        assert w.rc != 0, "打掉重试后「瞬时失败」仍判绿 ⇒ 上一条的绿不是重试带来的（无判别力）"

    def test_retry_exhausted_and_still_not_armed_is_red(self, tmp_path):
        """🔴 判据本体：重试全部失败 **且**回读仍 `none` ⇒ `::error::` + 非零退出。"""
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT_SEQ=_exit_seq(tmp_path, 1, 1, 1), STUB_STDERR=TRANSIENT_GRAPHQL,
            STUB_ARMED_FILE=str(Path(tmp_path) / "armed.flag"))
        assert w.rc != 0, (
            f"重试后仍未 arm 却判绿 ⇒ #5235 族 A 的静默形态原样复发：rc={w.rc}\n{w.out}"
        )
        assert _has_error_annotation(w.out), f"必须打 ::error::（真失败不得吞成 warning）：\n{w.out}"
        assert "族 A" in w.summary_text(), f"summary 必须点名病因：{w.summary_text()!r}"
        assert len([c for c in w.calls if c.startswith("pr merge")]) == 3, w.calls
        assert w.sleeps[:2] == ["5", "10"], f"重试退避必须是 5/10 秒：{w.sleeps}"

    def test_idempotent_failure_is_not_retried(self, tmp_path):
        """幂等命中（已在 merge queue）⇒ **不重试**、不刷红（#5076 ① 的既有语义一字未改）。"""
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT=1, STUB_STDERR="already in merge queue")
        assert w.rc == 0 and not _has_error_annotation(w.out), w.out
        assert len([c for c in w.calls if c.startswith("pr merge")]) == 1, w.calls
        assert w.sleeps == [], f"幂等路径不该有任何退避：{w.sleeps}"

    def test_failed_but_armed_is_warning_not_error(self, tmp_path):
        """**边界（有意收窄）**：重试都失败，但回读 `armed` ⇒ 目标状态已达成 ⇒ 非致命、**不静默**。

        判据不是"命令返回码"，而是回读的 `autoMergeRequest`（#4829 的既有口径）——
        与 `flaky-ledger-reconcile.yml` §⑤-B 的「读数与动作自洽」同源。
        （反向对照：同夹具若回读 `none` ⇒ 上一条判红。）
        """
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT_SEQ=_exit_seq(tmp_path, 1, 1, 1), STUB_STDERR=TRANSIENT_GRAPHQL,
            STUB_AMR_SEQ=_amr_seq(tmp_path, "armed"))
        assert w.rc == 0, f"回读已 armed 时判红 = 假红（PR 其实已 arm）：rc={w.rc}\n{w.out}"
        assert _has_warning_annotation(w.out), f"非致命路径必须留痕（不静默）：\n{w.out}"
        assert not _has_error_annotation(w.out), f"非致命路径不得打 ::error::：\n{w.out}"
        assert "已达成" in w.summary_text(), f"summary 必须写明读数与动作自洽：{w.summary_text()!r}"

    def test_arm_failure_outranks_the_unknown_mergeable_exception(self, tmp_path):
        """🔴 **次序判据**：`rc != 0` 的判红**优先于** #5113 的 `mergeable=UNKNOWN` 分流。

        #5113 的 unknown（`null` + `UNKNOWN` ⇒ 非红）只对「命令**成功**、只是还没算完」成立；
        arm 命令自己报了失败时，不许用「还没算完」把红洗掉（fail-closed）。
        """
        w = World(tmp_path, _automerge_script(), env=AUTOMERGE_ENV).run(
            STUB_EXIT_SEQ=_exit_seq(tmp_path, 1, 1, 1), STUB_STDERR=TRANSIENT_GRAPHQL,
            STUB_ARMED_FILE=str(Path(tmp_path) / "armed.flag"), STUB_MERGEABLE="UNKNOWN")
        assert w.rc != 0, (
            f"arm 失败 + mergeable=UNKNOWN 被分流成「非红」= 用 unknown 洗掉真失败：\n{w.out}"
        )
        assert _has_error_annotation(w.out), w.out

    def test_mutating_the_red_gate_turns_that_case_green(self, tmp_path):
        """**变异红证**：打掉「rc != 0 且仍未 arm」的判红闸 ⇒ 上一场景变绿（判别力证明）。"""
        src = _mutate(_automerge_script(),
                      'if [ "$rc" -ne 0 ]; then\n      # 🔴 #5235 族 A 的判据本体',
                      'if false; then\n      # 🔴 #5235 族 A 的判据本体')
        w = World(tmp_path, src, env=AUTOMERGE_ENV).run(
            STUB_EXIT_SEQ=_exit_seq(tmp_path, 1, 1, 1), STUB_STDERR=TRANSIENT_GRAPHQL,
            STUB_ARMED_FILE=str(Path(tmp_path) / "armed.flag"), STUB_MERGEABLE="UNKNOWN")
        assert w.rc == 0, "打掉该闸后仍判红 ⇒ 「红来自这条判据」这个结论没有判别力"


# ================================================================ ② pr-issue-link

ISSUE_LINK_GUARD = "<!-- pr-issue-link-check -->"


def _issue_link_script():
    doc = _load(PR_ISSUE_LINK)
    step = _step(doc, "issue-link-check", "Check PR body") or {}
    script = (step.get("with") or {}).get("script") or ""
    assert "context.payload.pull_request.body" in script, (
        "Check PR body step 必须是 actions/github-script 且真的读 PR body；"
        f"实际 script={script[:80]!r}"
    )
    return script


def _balanced_block(script, opener_re):
    """从 `opener_re` 命中处取**括号配平**的块正文（JS 的 `}` 会嵌套，不能用非贪婪正则）。

    ⚠️ `opener_re` 必须**锚定行首**（如 `^[ \\t]*\\}?[ \\t]*catch\\s*\\(`）：否则会命中字符串/注释里
    出现的同一个词（本 PR 实测：脚本里的中文注释含该词 ⇒ 取块取到错误位置 ⇒ 判据空转）。
    """
    m = re.search(opener_re, script, re.M)
    if not m:
        return None
    i = script.find("{", m.start())
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(script)):
        if script[j] == "{":
            depth += 1
        elif script[j] == "}":
            depth -= 1
            if depth == 0:
                return script[i + 1:j]
    return None


class TestIssueLinkFailureIsLoud:
    """`Check Closes #xx`：自身执行失败（API 报错）必须显式可见，而不是「少一个标签」。"""

    def test_script_has_failure_alerting(self):
        """结构判据：脚本必须有 try/catch，catch 里 `::error::` + step summary + 非零退出。"""
        script = _issue_link_script()
        assert re.search(r"\btry\s*\{", script), (
            "github-script 必须包 try —— 否则 API 报错时只有默认堆栈，"
            "没有 ::error:: 也没有 step summary（#5076 ① 类）"
        )
        body = _balanced_block(script, r"^[ \t]*\}?[ \t]*catch\s*\(") or ""
        assert "::error::" in body, (
            f"缺 catch 块或括号不配平（取块返回空）；script 尾部={script[-120:]!r}"
        )
        assert "::error::" in body, f"catch 里必须打 ::error::；实际：\n{body}"
        # 判据形态：必须是**真的调用**落笔 API（`core.summary…write()`），
        # 而不是「文本里出现过 core.summary 这个词」—— 后者会被注释/死代码喂绿
        # （本 PR 实测：把调用换成 `Promise.resolve(); /*core.summary` 后判据仍绿 ⇒ 已收窄）。
        assert re.search(r"core\.summary[\s\S]{0,200}?\.write\s*\(\s*\)", body), (
            f"catch 里必须真的调用 core.summary…write() 落笔（不是只提到它）；实际：\n{body}"
        )
        assert re.search(r"core\.setFailed|process\.exitCode\s*=\s*1", body), (
            f"catch 里必须让 job 真的红（core.setFailed / process.exitCode = 1）；实际：\n{body}"
        )

    def test_catch_block_extraction_is_not_vacuous(self):
        """自证：括号配平取块在**嵌套** catch 上也取到最外层（防「取到内层 ⇒ 判据空转」），
        且**行首锚定**不会被字符串里出现的 `catch` 骗走。"""
        sample = 'try {\n  x();\n} catch (e) {\n  if (a) { b(); }\n  core.setFailed("z");\n}'
        body = _balanced_block(sample, r"^[ \t]*\}?[ \t]*catch\s*\(")
        assert body is not None and "core.setFailed" in body, (
            f"配平取块漏掉了嵌套之后的内容：{body!r}"
        )
        decoy = 'try {\n  console.log("catch (x) {");\n} catch (e) {\n  core.setFailed("real");\n}'
        body2 = _balanced_block(decoy, r"^[ \t]*\}?[ \t]*catch\s*\(")
        assert body2 is not None and "core.setFailed" in body2, (
            f"取块被字符串里的 `catch` 骗走（行首锚定失效）：{body2!r}"
        )

    def test_missing_link_path_still_non_blocking(self):
        """「缺 Closes 关键词」是**预期内**的业务分支 ⇒ 仍不得刷红（只打标签 + 评论）。"""
        script = _issue_link_script()
        assert "addLabels" in script and ISSUE_LINK_GUARD in script, (
            "缺关键词分支必须保留「打 needs-issue-link 标签 + 评论提醒」"
        )
        # 该分支不得 setFailed（它是预期内分支，不是自身失败）
        tail = script.split("const marker")[0]
        assert "setFailed" not in tail, (
            "「缺 Closes 关键词」是预期内分支，不得 setFailed（#5076 ① 类不得翻成阻塞）"
        )

    def test_guard_goes_red_when_failure_alerting_removed(self):
        """变异红证：把 try/catch 剥掉 ⇒ 结构判据必须判红（证明它不恒真）。"""
        script = _issue_link_script()
        opener = re.search(r"^[ \t]*try \{[ \t]*$", script, re.M)
        assert opener, "被测脚本里找不到独占一行的 `try {`（判据无从施加）"
        # 用「空白替换」剥离，绝不删行 —— 保持行/列结构，避免 YAML 或缩进被破坏
        blanked = list(script)
        for k in range(opener.start(), opener.end()):
            if blanked[k] != "\n":
                blanked[k] = " "
        blanked = "".join(blanked)
        assert not re.search(r"\btry\s*\{", blanked), "变异未生效：try 仍在"

        # catch 块（配平）整体抹白
        cb = _balanced_block(blanked, r"^[ \t]*\}?[ \t]*catch\s*\(") or ""
        assert "core.setFailed" in cb, (
            f"变异前应能取到 catch 块且块内含失败信号；实际取块={cb[:120]!r}"
        )
        start = blanked.index("{" + cb)
        end = start + len(cb) + 2
        blanked = blanked[:start] + " " * (end - start) + blanked[end:]

        assert _balanced_block(blanked, r"^[ \t]*\}?[ \t]*catch\s*\(") is None, "变异未生效：catch 仍在"

        # 把变异文本塞回结构相同的文档，再走与 test_script_has_failure_alerting 相同的判据
        doc = _load(PR_ISSUE_LINK)
        doc["jobs"]["issue-link-check"]["steps"][0]["with"]["script"] = blanked
        got = (_step(doc, "issue-link-check", "Check PR body").get("with") or {}).get("script")
        assert not re.search(r"\btry\s*\{", got), (
            "删掉 try/catch 后判据仍绿 ⇒ 结构判据恒真（空断言）"
        )
        assert _balanced_block(got, r"^[ \t]*\}?[ \t]*catch\s*\(") is None, (
            "删掉 try/catch 后仍能取到 catch 块 ⇒ 取块逻辑有误"
        )


# ================================================================ ③ close-linked-issues

CLOSE_JOB = "close-linked-issues"
CLOSE_ENV = {
    "EVENT_NAME": "schedule",
    "EVENT_ACTION": "",
    "DISPATCH_PR": "",
    "EVENT_PR": "",
    "RECONCILE_HOURS": "48",
    "PAGE_LIMIT": "100",
    "MAX_LIMIT": "1000",
    "LATE_MINUTES": "15",
}


def _close_script():
    return _run_text(_load(CLOSE_LINKED), CLOSE_JOB)


class TestCloseLinkedIssuesFailureVisibility:
    """`Close linked issues`：静默失败 = issue 不关 ⇒ 真失败必须 `::error::` + summary + 非零退出。

    取证结论（2026-09-21，本 PR）：`gh run list --workflow=close-linked-issues.yml --limit 200`
    ⇒ `196 success / 4 skipped / 0 failure`，**未发现它真失败**（见本 PR body 的取证段）。
    故本组只补「自身失败时的可见性」面，**不**改它的触发/窗口/判定语义。
    """

    def test_close_failure_is_loud_and_summarised(self, tmp_path):
        """关闭 issue 失败（该关却没关成）⇒ 非零退出 + `::error::` + summary 落笔。"""
        w = World(tmp_path, _close_script(), env=CLOSE_ENV).run(
            STUB_EXIT=1, STUB_STDERR="HTTP 403: Resource not accessible by integration",
        )
        assert w.rc != 0, f"关闭失败必须非零退出；实际 rc={w.rc}\n{w.out}"
        assert _has_error_annotation(w.out), f"关闭失败必须打 ::error::：\n{w.out}"
        assert w.summary_text().strip(), (
            "关闭失败必须写 step summary（改前该路径只打 warning/error 注解，summary 为空）"
        )

    def test_unexpected_shell_error_is_summarised(self, tmp_path):
        """**非预期**的 shell 失败（`set -e` 中断）也必须留下 summary —— 否则 step 红了而 summary 空。"""
        # 注入点：`n_cand == 0` 的**早退分支**（本 fixture 世界必然走到）换成裸 `false`
        # ⇒ `set -e` 直接中断 ⇒ 走 trap。**不能追加在末尾**：脚本末尾是 `exit 0`，
        # 追加在它之后永不执行；也不能只换末尾那句，因为早退分支先返回。
        src = _close_script()
        broken = re.sub(r'\n\s*echo "ℹ️ 无待处理 PR，退出"\n[\s\S]*?\n\s*exit 0\n',
                        "\nfalse\n", src, count=1)
        assert broken != src, "注入点未命中（测试自身失效）"
        w = World(tmp_path, broken, env=CLOSE_ENV).run()
        assert w.rc != 0, f"注入的失败必须让脚本非零退出；实际 rc={w.rc}\n{w.out}"
        summary = w.summary_text()
        assert "本轮失败" in summary and "rc=" in summary, (
            "非预期失败必须经 trap 写**带病因**的 step summary（含「本轮失败」与 rc=）；"
            f"实际 summary={summary!r}"
        )
        assert _has_error_annotation(w.out), f"非预期失败必须打 ::error::：\n{w.out}"

    def test_expected_skip_paths_stay_quiet(self, tmp_path):
        """预期内路径（`workflow_dispatch` 点名一个未合并 PR）⇒ 非阻塞 + 明确文案，不得刷红。"""
        w = World(tmp_path, _close_script(), env=CLOSE_ENV).run(
            EVENT_NAME="workflow_dispatch", DISPATCH_PR="999",
            STUB_EXIT=0, STUB_STDOUT="999\t\tabc\t",
        )
        assert w.rc == 0, f"未合并 PR 属预期内跳过 ⇒ 必须非阻塞；实际 rc={w.rc}\n{w.out}"
        assert not _has_error_annotation(w.out), f"预期内跳过不得打 ::error::：\n{w.out}"

    def test_healthy_reconcile_writes_summary_and_exits_zero(self, tmp_path):
        """健康路径（无候选 PR）⇒ 退出 0 且 summary 有落笔（证明 trap 不误伤正常路径）。"""
        w = World(tmp_path, _close_script(), env=CLOSE_ENV).run(STUB_EXIT=0, STUB_STDOUT="")
        assert w.rc == 0, f"健康路径必须退出 0；实际 rc={w.rc}\n{w.out}"
        assert w.summary_text().strip(), "健康路径本来就会写 summary（判据是它仍在）"

    def test_guard_goes_red_without_failure_trap(self):
        """变异红证：删掉失败捕获（trap）⇒ 「非预期失败留 summary」判据必红。"""
        script = _close_script()
        mutated = re.sub(r"^.*\btrap\b.*$", "", script, flags=re.M)
        assert mutated != script, "变异未生效（测试自身失效）"
        assert "trap" not in mutated, "删掉 trap 后仍能找到 trap ⇒ 变异无效"
        # 判据本体：脚本必须含失败捕获
        assert re.search(r"\btrap\b", script), (
            "close-linked-issues 的 run: 必须含失败捕获（trap），否则非预期失败无 summary"
        )
