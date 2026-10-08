# case_ids: MC-084
"""合并凭据选择段的**夹具真跑**：证明「PAT 在 ⇒ 真用它」「PAT 不在 ⇒ fail-open + 具名出声」（issue #6418）。

## 为什么还要这一层（已有结构判据了）

`tests/unit_ci_workflows/test_automerge_merge_credential.py` 判的是**结构**（引用了 `secrets.AUTOMERGE_PAT`、
没把内置凭据绑到 `GH_TOKEN`、回落告警字面量在）。结构绿 ≠ **那段 bash 真跑起来会按预期分流**：
`set -u` 下少写一个 `:-`、`if` 分支写反、`export` 丢一行，结构判据全都看不见。

⇒ 本文件把 `automerge.yml` 里那段**逐字抽出来真跑**（夹具 = 假 `gh` + 临时目录），四种情形各一条判据：

| 情形 | 期望（现取断言） |
|---|---|
| PAT 在（actor = 人） | 打 `🔑 合并凭据 = AUTOMERGE_PAT（actor=zhaokai-mgzn）`；**无任何 `::warning::`**；`GH_TOKEN` == PAT 值 |
| PAT 在但 actor = `github-actions[bot]` | 打「**等价物** ⇒ 抑制照旧」的具名告警（PAT 被误配成内置等价物要当场可见） |
| PAT 不在 | 打具名 `::warning::AUTOMERGE_PAT 未配置 …` + step summary 写明出口；`GH_TOKEN` == 回落值；**退出码 0**（fail-open：缺 secret 不得卡住合并 —— 这是业务连续性底线） |
| 红证（注入式） | 把 `GH_TOKEN="$AUTOMERGE_PAT"` 改回 `GH_TOKEN="${FALLBACK_TOKEN:-}"` ⇒ 「PAT 在 ⇒ 用 PAT」当场判红；把 ⓪ 段整段删掉 ⇒ 抽取函数当场判红（防空跑） |

**判定的确定性**：零网络、零真 `gh`（PATH 里放假 `gh` 记账）、零时钟、零 git —— 只读 in-repo 的
`automerge.yml` + 临时目录。
"""
import os
import re
import subprocess
from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"
AUTOMERGE = WORKFLOWS_DIR / "automerge.yml"
#: 凭据选择段的起止锚（判据靠它抽取；锚漂了必须**当场红**而不是静默判 0 件事）
SEGMENT_START_MARKER = "⓪ 选合并凭据"
SEGMENT_END_MARKER = "export GH_TOKEN"
#: 假 gh 记账脚本（`api user --jq .login` 打印被注入的 actor）
FAKE_GH = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_GH_LOG"
case "$*" in
  "api user --jq .login") echo "${FAKE_GH_ACTOR:-}" ;;
  *) echo "" ;;
esac
exit 0
"""


def arm_run_body() -> str:
    """非 bot arm job 的 `run` 正文（真语料）。"""
    doc = yaml.safe_load(AUTOMERGE.read_text(encoding="utf-8"))
    return doc["jobs"]["enable-auto-merge"]["steps"][1]["run"]


def credential_segment(text: str | None = None) -> str:
    """抽出凭据选择段（含 `export GH_TOKEN`）。**抽不到就抛** —— 不许静默返回空串。

    为什么要抛：本文件的全部判据都建立在这段文本存在上；若某次重构把锚改了，
    返回空串会让四条判据静静地一起失去判别力（同族教训见 `.github/cases/misc.yml` 的 MC-039「空跑即红」口径）。
    """
    body = arm_run_body() if text is None else text
    lines = body.splitlines()
    starts = [i for i, l in enumerate(lines) if SEGMENT_START_MARKER in l]
    if len(starts) != 1:
        raise AssertionError(
            f"凭据选择段起点锚 `{SEGMENT_START_MARKER}` 命中 {len(starts)} 次（须恰 1 次）"
            " —— 锚漂了 ⇒ 全部判据会空跑，故当场红"
        )
    start = starts[0] - 1  # 连注释行一起抽（注释是这段的说明）
    assert start >= 0
    ends = [i for i, l in enumerate(lines) if l.startswith(SEGMENT_END_MARKER)]
    if len(ends) != 1:
        raise AssertionError(f"凭据选择段终点锚 `{SEGMENT_END_MARKER}` 命中 {len(ends)} 次（须恰 1 次）")
    segment = "\n".join(lines[start:ends[0] + 1])
    assert "gh api user" in segment, "段里没有 actor 读数 ⇒ 抽错段了"
    return segment


def run_segment(tmp_path, *, pat=None, fallback=None, actor=None, segment=None):
    """在临时目录里真跑那段 bash（假 `gh` 在 PATH 上记账）。返回 (rc, stdout, summary, token, gh_calls)。"""
    seg = credential_segment() if segment is None else segment
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)

    token_out = tmp_path / "token.txt"
    gh_log = tmp_path / "gh.log"
    gh_log.write_text("", encoding="utf-8")
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    script = tmp_path / "seg.sh"
    script.write_text(
        "set -uo pipefail\n"
        + seg
        + '\nprintf \'%s\' "${GH_TOKEN:-}" > ' + str(token_out) + "\n",
        encoding="utf-8",
    )

    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        "FAKE_GH_LOG": str(gh_log),
        "FAKE_GH_ACTOR": actor or "",
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    if pat is not None:
        env["AUTOMERGE_PAT"] = pat
    if fallback is not None:
        env["FALLBACK_TOKEN"] = fallback
    proc = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, cwd=tmp_path)
    return (
        proc.returncode,
        proc.stdout + proc.stderr,
        summary.read_text(encoding="utf-8"),
        token_out.read_text(encoding="utf-8"),
        gh_log.read_text(encoding="utf-8"),
    )


# ══════════════════════════════════════════════════════════════════════════════
class TestCredentialSelectionFixture:
    def test_pat_present_uses_pat_and_is_quiet(self, tmp_path):
        """PAT 在：用它 + 打 actor 读数 + **不**打任何 warning（有 PAT 时静默是预期）。"""
        rc, out, _, token, calls = run_segment(
            tmp_path, pat="ghp_FAKE_PAT_VALUE", fallback="builtin-fallback", actor="zhaokai-mgzn")
        assert rc == 0, out
        assert "🔑 合并凭据 = AUTOMERGE_PAT（actor=zhaokai-mgzn）" in out, out
        assert "::warning::" not in out, out
        assert token == "ghp_FAKE_PAT_VALUE", f"GH_TOKEN 没走 PAT：{token!r}"
        assert "api user --jq .login" in calls, "没做 actor 读数（就没法发现 PAT 被配成内置等价物）"

    def test_pat_that_behaves_like_builtin_is_flagged(self, tmp_path):
        """PAT 值对了但 actor 解析成 `github-actions[bot]` ⇒ 必须具名告警（抑制照旧，别让人误以为修好了）。"""
        rc, out, _, token, _ = run_segment(
            tmp_path, pat="ghp_FAKE_PAT_VALUE", fallback="builtin-fallback",
            actor="github-actions[bot]")
        assert rc == 0, out
        assert "::warning::" in out and "等价物" in out, out
        assert token == "ghp_FAKE_PAT_VALUE"

    def test_pat_absent_fails_open_with_named_warning(self, tmp_path):
        """PAT 不在：**退出码 0**（不卡合并）+ 具名告警 + step summary 写明出口 + 回落到内置。"""
        rc, out, summary, token, calls = run_segment(tmp_path, fallback="builtin-fallback")
        assert rc == 0, f"缺 secret 必须 fail-open（否则合并被卡住）：rc={rc}\n{out}"
        assert "::warning::AUTOMERGE_PAT 未配置" in out, out
        assert "push" in out and "抑制" in out, "告警必须写明后果（push 被抑制 ⇒ 部署主触发不恢复）"
        assert token == "builtin-fallback", f"GH_TOKEN 没回落到内置：{token!r}"
        assert "AUTOMERGE_PAT" in summary and "Settings" in summary, (
            f"step summary 必须写出口（建 secret 的路径）：{summary!r}")
        assert calls == "", f"缺 secret 时不该再去问 actor（省一次 API 调用）：{calls!r}"

    def test_pat_absent_and_fallback_absent_is_still_fail_open(self, tmp_path):
        """两个 env 都没有（`set -u` 场景）：仍必须 rc=0（`:-` 守住），只是 GH_TOKEN 为空。"""
        rc, out, _, token, _ = run_segment(tmp_path)
        assert rc == 0, f"`set -u` 下不得因缺变量崩掉（这正是真 CI 夹具先踩到的形态）：rc={rc}\n{out}"
        assert "AUTOMERGE_PAT 未配置" in out, out
        assert token == ""


class TestCredentialSelectionRedProofs:
    """注入式红证：证明上面四条**会红**（不是橡皮图章）。"""

    def test_baseline_extraction_is_nonempty_and_real(self):
        assert SEGMENT_START_MARKER in arm_run_body(), "锚不在真语料里 ⇒ 抽取会抛"
        seg = credential_segment()
        assert "AUTOMERGE_PAT" in seg and SEGMENT_END_MARKER in seg

    def test_removing_the_segment_is_caught(self, tmp_path):
        """把 ⓪ 段整段删掉（模拟「重构把这段弄丢了」）⇒ 抽取函数当场红（防空跑）。"""
        mutated = "\n".join(
            l for l in arm_run_body().splitlines() if SEGMENT_START_MARKER not in l
            and not l.strip().startswith("if [ -n \"${AUTOMERGE_PAT"))
        try:
            credential_segment(mutated)
        except AssertionError as exc:
            assert "命中 0 次" in str(exc), str(exc)
        else:
            raise AssertionError("段被删掉却抽到了东西 ⇒ 判据会空跑（必须红）")

    def test_reverting_to_builtin_token_turns_the_fixture_red(self, tmp_path):
        """把 `GH_TOKEN=\"$AUTOMERGE_PAT\"` 改回 `GH_TOKEN=\"${FALLBACK_TOKEN:-}\"` ⇒ 夹具判红。"""
        mutated = credential_segment().replace(
            '  GH_TOKEN="$AUTOMERGE_PAT"', '  GH_TOKEN="${FALLBACK_TOKEN:-}"')
        assert mutated != credential_segment(), "变异未生效（锚漂）"
        rc, out, _, token, _ = run_segment(
            tmp_path, pat="ghp_FAKE_PAT_VALUE", fallback="builtin-fallback",
            actor="zhaokai-mgzn", segment=mutated)
        assert rc == 0
        assert token == "builtin-fallback", "变异后应当走内置 —— 这就是「红」的那个读数"
        assert token != "ghp_FAKE_PAT_VALUE"

    def test_dropping_the_fallback_warning_turns_the_fixture_red(self, tmp_path):
        """删掉回落告警那一行 ⇒ 「缺 secret 具名出声」判据失配（证明该断言不是装饰）。"""
        seg = credential_segment()
        mutated = re.sub(r'\n\s*echo "::warning::AUTOMERGE_PAT 未配置[^\n]*', "", seg)
        assert mutated != seg, "变异未生效（锚漂）"
        rc, out, _, _, _ = run_segment(tmp_path, fallback="builtin-fallback", segment=mutated)
        assert rc == 0
        assert "::warning::AUTOMERGE_PAT 未配置" not in out, "变异后不该还有该告警"
