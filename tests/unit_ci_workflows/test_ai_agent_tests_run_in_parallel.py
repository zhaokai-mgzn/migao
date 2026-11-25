# case_ids: MC-368
"""`ai-agent-service` 的单测必须真开 xdist（issue #9153 读数第一大项）。

## 病（2026-11-25 实测）

PR 腿与部署腿的命令都是：

```bash
python -m pytest tests/ -v --tb=short -q -m "not integration"
```

**没有 `-n`** ⇒ 8210 条用例在**一个进程**里跑完。CI step 实测 **459s**，而 `admin-web` 拆片、
`unit_ci_workflows` 四片早就在并行 —— 这条是全仓 PR 反馈时长里最大的一笔。

`pytest-xdist==3.8.0` **早就在** `backend/ai-agent-service/requirements.txt` 里
（注释写着「issue #2957: 本地并行提速（run -n auto）」）⇒ CI 只是**没用**它，不是装不了。

## 判据（三条）

1. **两处调用都必须带 `-n N`**（N ∈ [2, 8]）：PR 腿（`ai-agent-tests.yml`）与部署腿
   （`deploy-ai-agent-service.yml`）—— 两处不同源会让「部署前跑的那套」和「PR 上跑的那套」不是同一件事；
2. **必须 `--dist loadfile`**：同一文件的用例落同一 worker，夹具/模块级状态不被跨 worker 打散
   （`load` 会把一个文件摊到多个 worker）；
3. **`pytest-xdist` 必须在 requirements 里**：否则命令带 `-n` 也只会 fail 成「unrecognized arguments」。
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = {
    "pr": REPO_ROOT / ".github" / "workflows" / "ai-agent-tests.yml",
    "deploy": REPO_ROOT / ".github" / "workflows" / "deploy-ai-agent-service.yml",
}
REQUIREMENTS = REPO_ROOT / "backend" / "ai-agent-service" / "requirements.txt"


def _pytest_lines(path: pathlib.Path) -> list[str]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for job in (doc.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            for line in str(step.get("run") or "").splitlines():
                if "pytest" in line and "tests/" in line:
                    out.append(line.strip())
    return out


def test_both_invocations_use_xdist():
    problems: list[str] = []
    for tag, path in WORKFLOWS.items():
        lines = _pytest_lines(path)
        assert lines, f"{path.name} 里找不到运行 tests/ 的 pytest 行"
        for line in lines:
            m = re.search(r"-n\s+(\d+)", line)
            if not m:
                problems.append(f"{tag}：没有 `-n` ⇒ 单进程跑 8210 条（CI step 实测 459s）：{line}")
                continue
            n = int(m.group(1))
            if not 2 <= n <= 8:
                problems.append(f"{tag}：`-n {n}` 不在 [2,8]（runner 是 4 核；>8 只会互相排队）：{line}")
    assert not problems, "\n  ".join(["ai-agent 单测没有真并行："] + problems)


def test_dist_is_loadfile():
    problems = [
        f"{tag}：缺 `--dist loadfile`（`load` 会把同一文件摊到多个 worker，模块级状态会串）：{line}"
        for tag, path in WORKFLOWS.items()
        for line in _pytest_lines(path)
        if "--dist loadfile" not in line
    ]
    assert not problems, "\n  ".join(problems)


def test_both_legs_use_the_same_command():
    """两处命令必须**逐字相同**（PR 面与部署面跑的必须是同一件事）。"""
    pr = _pytest_lines(WORKFLOWS["pr"])
    dep = _pytest_lines(WORKFLOWS["deploy"])
    assert pr and dep, "两处都应找到 pytest 行"
    assert pr[0] == dep[0], (
        "PR 腿与部署腿的 pytest 命令不同源 ⇒ 「部署前跑的那套」≠「PR 上跑的那套」：\n"
        f"  PR  : {pr[0]}\n  DEP : {dep[0]}"
    )


def test_xdist_is_installed_by_requirements():
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert re.search(r"^pytest-xdist[=<>~]", text, re.M), (
        "requirements.txt 里没有 `pytest-xdist` ⇒ 命令带 `-n` 会 fail 成 `unrecognized arguments`"
    )
