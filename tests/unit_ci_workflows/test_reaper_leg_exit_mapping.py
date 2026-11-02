# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""`stale-report-reaper` 腿的**退出码语义**（issue #8197 P1-04，2026-10-31 上线审计）。

## 病（逐字读数在审计 findings 里）

机制体 `scripts/stale_report_reaper.py` 的常量是四态：

```python
EXIT_OK, EXIT_USAGE, EXIT_ACTED, EXIT_UNKNOWN = 0, 1, 2, 3
```

`EXIT_ACTED = 2` 的意思是「**成功关掉了陈旧报告**」（干完了活），而 workflow 改前把它
**原样透传** ⇒ **它每成功干一轮活，腿就红一次**。实测（审计引用）：

```
run 41148096721 日志： MIGAO-REAPER-SUMMARY seen=3 acted=1 rc=2 why=可关 1 条，实关 1 条
下一行：               ##[error]Process completed with exit code 2
```

这是**假红**（与 `migao-acceptance` 的「假红」同形）：真失败与「干完了」长得一模一样
⇒ 告警疲劳 ⇒ 真坏的那天没人看。

## 判据（**执行式**：把 workflow 那一步的 run 正文抽出来，用替身 `python3` 真跑）

| # | 判据 | 变红形态 |
|---|---|---|
| 1 | `rc=0`（没有可关的）⇒ 腿绿 | 把 0 也当失败 ⇒ 红 |
| 2 | `rc=2`（EXIT_ACTED）⇒ 腿**绿**，且日志里出现 `EXIT_ACTED`（读数保留） | 原样 `exit 2` ⇒ 红（改前形态） |
| 3 | `rc=1`（EXIT_USAGE）⇒ 腿**红**（1） | 把 1 也映射成绿 ⇒ 红（真失败被吞） |
| 4 | `rc=3`（EXIT_UNKNOWN）⇒ 腿**红**（3），不得当 0 读 | 把 3 当"无法判定⇒放过" ⇒ 红 |
| 5 | 映射**只**有 `2 → 0` 这一条（不许顺手把 1/3 也归一化） | 多一条 `RC=0` 分支 ⇒ 红 |
| 6 | 注入式自证：把映射段删掉 ⇒ `rc=2` 必须重新变成退出码 2 | 删了映射仍然绿 ⇒ 判据自己在空转 |

## 边界（照实登记）

- 替身的是**机制体**（`python3 scripts/stale_report_reaper.py`），跑的是 workflow **真的 run 正文**
  （含 `source` 发射器、`${{ }}` 表达式替换后的 shell 片段）⇒ 证明的是「这一步怎么把退出码翻成人话」，
  **不是**「reaper 判据本身对不对」（那是 `test_stale_report_reaper.py` 的射程）。
- 它证明不了 GitHub 的 job 结论映射（`exit 0` ⇒ success 是平台语义，不在本机可测面）。
- 表达式替换是**测试替身**：`github.event_name=push` / `inputs.*` 为空 —— 只看 rc 映射，
  不覆盖「apply 开关」的语义（那是既有行为，本单未改）。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "stale-report-reaper.yml"
STEP_NAME = "腿转绿 ⇒ 关陈旧报告"


def step_run_body() -> str:
    """取「腿转绿 ⇒ 关陈旧报告」这一步的 `run:` 正文（找不到 ⇒ fail-closed，不静默跳过）。"""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job in (doc.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if STEP_NAME in (step.get("name") or ""):
                body = step.get("run")
                assert body, f"{STEP_NAME} 这一步没有 run 正文"
                return body
    raise AssertionError(f"{WORKFLOW} 里找不到 `{STEP_NAME}` 这一步（判据的坐标没了）")


def _render_expressions(body: str) -> str:
    """把 GitHub 表达式换成固定值（只用于本测试：只看退出码映射，不看 apply 分支）。"""
    replacements = {
        "${{ github.event_name }}": "push",
        "${{ github.event.inputs.apply }}": "",
        "${{ github.event.inputs.only }}": "",
        "${{ secrets.GITHUB_TOKEN }}": "",
    }
    out = body
    for expr, value in replacements.items():
        out = out.replace(expr, value)
    leftovers = re.findall(r"\$\{\{[^}]*\}\}", out)
    assert not leftovers, f"run 正文里还有未替换的 GitHub 表达式（补上替身值再跑）：{leftovers}"
    return out


def _run_step(body: str, tmp_path: Path, rc: int) -> subprocess.CompletedProcess:
    """用替身 `python3`（只回一行 SUMMARY + 指定的退出码）真跑那一步的 run 正文。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "python3"
    stub.write_text(
        "#!/bin/sh\n"
        "printf 'MIGAO-REAPER-SUMMARY seen=3 acted=1 rc=%s why=可关 1 条，实关 1 条\\n' \"$STUB_RC\"\n"
        'exit "$STUB_RC"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin",
            "STUB_RC": str(rc),
            # 读数发射器写盘的位置：落到 tmp 里（不污染 /tmp 的共享面）
            "MECHANISM_LIVENESS_DISPOSITION": str(tmp_path / "mechanism-liveness.disposition"),
        }
    )
    return subprocess.run(
        ["bash", "-c", _render_expressions(body)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


# ══════════════════════════════════════════════════════════════════════════
# 一、执行式判据（判据 1~4）
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "rc,expected",
    [
        (0, 0),  # 没有可关的 ⇒ 绿
        (2, 0),  # EXIT_ACTED：**干完了活** ⇒ 绿（本单的修法）
        (1, 1),  # EXIT_USAGE：真失败 ⇒ 红
        (3, 3),  # EXIT_UNKNOWN：无法判定 ⇒ 红，且原样透传 3
    ],
)
def test_step_exit_code_mapping(tmp_path, rc, expected):
    out = _run_step(step_run_body(), tmp_path, rc)
    assert out.returncode == expected, (
        f"rc={rc} 时这一步的退出码应为 {expected}，实测 {out.returncode}\n"
        f"stdout:\n{out.stdout}\nstderr:\n{out.stderr}"
    )


def test_exit_acted_is_announced_but_other_failures_are_not(tmp_path):
    """判据 2 的「读数保留」：rc=2 必须**说出来**它干完了什么；rc=1/3 不得打“成功”字样。"""
    acted = _run_step(step_run_body(), tmp_path, 2)
    assert "EXIT_ACTED" in acted.stdout, f"rc=2 判绿了但没解释为什么（读数丢了）：\n{acted.stdout}"
    assert "acted=1" in acted.stdout, "rc=2 的读数里没有 acted 计数（发射器拿不到数）"

    for rc in (1, 3):
        failed = _run_step(step_run_body(), tmp_path, rc)
        assert "EXIT_ACTED" not in failed.stdout, f"rc={rc} 是**失败**，不许打成 EXIT_ACTED"


# ══════════════════════════════════════════════════════════════════════════
# 二、静态判据（判据 5：映射只许有 2→0 一条）
# ══════════════════════════════════════════════════════════════════════════


def test_only_exit_acted_is_mapped_to_success():
    body = step_run_body()
    mapping = re.findall(r'if \[ "\$\{?RC\}?" = "(\d)" \]', body)
    assert mapping == ["2"], f"退出码映射只许有 2（EXIT_ACTED）一条，实测 {mapping}"
    zeroing = re.findall(r"^\s*RC=0\s*$", body, re.M)
    assert len(zeroing) == 1, f"`RC=0` 只许出现一次（映射一次），实测 {len(zeroing)} 次"


# ══════════════════════════════════════════════════════════════════════════
# 三、注入式红证（判据 6：把映射删掉 ⇒ rc=2 必须重新变成 2，即改前形态）
# ══════════════════════════════════════════════════════════════════════════


def _strip_mapping(body: str) -> str:
    start = body.index('if [ "${RC}" = "2" ]; then')
    end = body.index("fi", body.index("RC=0", start)) + len("fi")
    mutated = body[:start] + body[end:]
    assert mutated != body, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    assert 'if [ "${RC}" = "2" ]' not in mutated, "映射段没被删干净（红证会失真）"
    return mutated


def test_injection_without_mapping_reproduces_the_original_red(tmp_path):
    """改前形态（rc=2 原样透传）⇒ 退出码 2（= 那次假红的机器形态）。"""
    mutated = _strip_mapping(step_run_body())
    out = _run_step(mutated, tmp_path, 2)
    assert out.returncode == 2, (
        "把 2→0 的映射删掉之后，rc=2 应当原样变成退出码 2（改前的假红形态）——"
        f"实测 {out.returncode}；说明本文件的执行式判据没有判别力\nstdout:\n{out.stdout}"
    )


if __name__ == "__main__":  # pragma: no cover - 手工复算入口
    raise SystemExit(pytest.main([__file__, "-q"]))
