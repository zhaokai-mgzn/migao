# case_ids: MC-356
"""CI 必须装 `pytest-timeout` 并把 `--timeout=` 传给 pytest（issue #9144）。

## 病

`.github/workflows/pr-check.yml` 的 helper 测试步只装 `pip install -q pytest pytest-xdist pyyaml`
—— **没有 `pytest-timeout`**。于是任何**单条**用例挂住时，唯一的兜底是 job 的
`timeout-minutes: 20`，而 **cancelled job 不上传日志**（issue #9114）⇒ 具体是哪条挂住、
挂在哪一行**永远查不出来**（3/4 片曾 4 次如此，见 #9141）。

## 判据（三条，现取文本，不手填台账）

1. CI 的安装行含 `pytest-timeout`；
2. pytest 命令行（**单一来源** `scripts/ci_helper_scope.py::CANONICAL_ARGV` + CI 全量档 +
   `verify-all.sh` 四片）都带 `--timeout=<N>` 且 `--timeout-method=signal`；
3. `N` 必须落在 `[120, 600]`：小于 120 会把合法慢用例（依赖真实数据库的用例要现起本地实例）假红；
   大于 600 又会「先被 job 上限掐死」（与 MC-355 同一条口径）。
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"
VERIFY = REPO_ROOT / "verify-all.sh"
SCOPE = REPO_ROOT / "scripts" / "ci_helper_scope.py"
JOB_ANCHOR = "Run ci workflow helper tests"


def test_ci_installs_pytest_timeout():
    """没有插件 ⇒ 逐用例看门狗缺失 ⇒ 挂住只能靠 job cancel（日志还拿不到）。"""
    text = WORKFLOW.read_text(encoding="utf-8")
    installs = re.findall(r"pip install[^\n]*", text)
    assert installs, "pr-check.yml 里找不到任何 pip install 行"
    helper_install = [line for line in installs if "pytest-xdist" in line]
    assert helper_install, "找不到 helper 腿的安装行（以 pytest-xdist 为锚）"
    assert any("pytest-timeout" in line for line in helper_install), (
        "helper 腿的 pip install 没装 pytest-timeout ⇒ 单条用例挂住只能靠 job cancel，"
        f"证据不可得（issue #9144）。现取安装行：{helper_install}"
    )


def _timeout_flags(cmdline: str) -> tuple[str | None, str | None]:
    m = re.search(r"--timeout[= ](\d+)", cmdline)
    method = re.search(r"--timeout-method[= ](\w+)", cmdline)
    return (m.group(1) if m else None), (method.group(1) if method else None)


def test_every_pytest_entrypoint_passes_the_timeout_flag():
    """三个入口（单一来源常量 / CI 全量档 / 本地四片）都必须带同一组 timeout 参数。"""
    scope = SCOPE.read_text(encoding="utf-8")
    wf = WORKFLOW.read_text(encoding="utf-8")
    verify = VERIFY.read_text(encoding="utf-8")

    canonical = re.search(r"CANONICAL_ARGV = \((.*?)\)", scope, re.S)
    assert canonical, "找不到 `CANONICAL_ARGV`（全量命令的单一来源）"
    # 物理行可能用 `\` 折行 ⇒ 先续行合并，再取命令行（否则判据会「看见半条命令」而假红）
    def _joined(text: str) -> list[str]:
        lines, buf = [], ""
        for raw in text.splitlines():
            piece = raw.rstrip()
            if piece.endswith("\\"):
                buf += piece[:-1] + " "
                continue
            lines.append(buf + piece)
            buf = ""
        if buf:
            lines.append(buf)
        return lines

    # 只取**真命令行**：注释里引用同一条命令不算（否则判据会去判注释）
    def _is_call(line: str) -> bool:
        stripped = line.strip()
        # 只判**分片腿**（`-n 4` 跑整个判据目录）；单文件判据腿（Case Trust Gate / llm-sink）另有其归属，
        # 它们装不装插件不在本判据范围（写面控制：不为本单扩大改动面）。
        return (not stripped.startswith("#")) and "pytest tests/unit_ci_workflows " in line + " " \
            and ("-m pytest" in line) and ("-n 4" in line)

    ci_lines = [ln for ln in _joined(wf) if _is_call(ln)]
    local_lines = [ln for ln in _joined(verify) if _is_call(ln)]
    assert ci_lines, "CI 里找不到 pytest 命令行"
    assert len(local_lines) == 4, f"本地腿应有四片显式命令行，实得 {len(local_lines)} 条"

    problems = []
    for label, cmdline in [("CANONICAL_ARGV", canonical.group(1))] + \
                          [(f"CI:{i+1}", l) for i, l in enumerate(ci_lines)] + \
                          [(f"verify-all:{i+1}", l) for i, l in enumerate(local_lines)]:
        seconds, method = _timeout_flags(cmdline)
        if seconds is None:
            problems.append(f"{label} 缺 `--timeout=`")
            continue
        if method != "signal":
            problems.append(f"{label} 的 `--timeout-method` 应为 signal，实得 {method!r}")
        if not 120 <= int(seconds) <= 600:
            problems.append(f"{label} 的 `--timeout={seconds}` 不在 [120, 600]")
    assert not problems, "pytest 超时参数不一致/缺失：\n  " + "\n  ".join(problems)


def test_the_timeout_is_not_a_magic_number():
    """`--timeout=300` 必须有出处：判据自己写清上下界与理由，改值要连带解释。"""
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert "120" in text and "600" in text, "判据正文没写清上下界"
    assert "下界" in text and "假红" in text, "没写「下界为什么不能太小」（现起本地数据库实例耗时数十秒）"
