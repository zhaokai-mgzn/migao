# case_ids: MC-361
"""CI 里的 `npm ci` 必须带 `--prefer-offline --no-audit --no-fund`（issue #9153 ①）。

## 病

`admin-web-test` 的 `Install dependencies`（`npm ci`）实测 **54s**，而它的 `setup-node` **已经**配了
`cache: npm` + 正确的 `cache-dependency-path`（`frontend/admin-web/package-lock.json`）。
⇒ 省不下来的不是下载，而是「网络探测 + audit 解析 + 解包前校验」这些**每次都要跑**的固定动作：

- `--no-audit` / `--no-fund`：跳过审计与赞助位解析（本仓另有独立的 secret / dependency 面，不靠 npm audit）；
- `--prefer-offline`：缓存里有就直接用，不再回头问 registry（本仓 `scripts/batch_gate.py` 的
  `--install-deps` 早就这么写，判据 `test_batch_gate.py` 的「23」条也钉着 `--prefer-offline`）。

## 判据

现取 `.github/workflows/pr-check.yml` 里**每一条** `run: npm ci` ⇒ 参数必须同时含
`--prefer-offline`、`--no-audit`、`--no-fund`。缺任一即红，并**具名**打出是哪一步（按所在 job 归类）。

为什么不是「一律禁止裸 `npm ci`」：这三个参数只影响**取包策略**，不影响装了什么 ⇒ 不降门禁。
"""

from __future__ import annotations

import pathlib
import re

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-check.yml"
REQUIRED_FLAGS = ("--prefer-offline", "--no-audit", "--no-fund")


def _npm_ci_steps() -> list[tuple[str, dict]]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    out = []
    for job_id, job in (doc.get("jobs") or {}).items():
        for step in (job or {}).get("steps") or []:
            run = str(step.get("run") or "")
            if re.search(r"^\s*npm ci\b", run, re.M):
                out.append((job_id, step))
    return out


def test_every_npm_ci_pins_the_offline_flags():
    steps = _npm_ci_steps()
    assert steps, "pr-check.yml 里找不到 `npm ci`（约束类判据必须与被约束对象对齐）"
    offenders = []
    for job_id, step in steps:
        run = str(step.get("run") or "")
        line = next(ln for ln in run.splitlines() if ln.strip().startswith("npm ci"))
        missing = [f for f in REQUIRED_FLAGS if f not in line]
        if missing:
            offenders.append(f"{job_id}::{step.get('name')} 缺 {missing}（实得：{line.strip()}）")
    assert not offenders, (
        "这些 `npm ci` 没带离线/免审计参数 ⇒ 每次都要做网络探测与 audit 解析"
        "（实测 admin-web 的 `npm ci` 54s，而 npm 缓存已命中）：\n  " + "\n  ".join(offenders)
    )


def test_the_reason_is_recorded_next_to_the_flags():
    """判据自己要有出处：这三个参数的理由（不是「随手加的」）必须写在判据或 workflow 注释里。"""
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert "54s" in text and "--prefer-offline" in text, "没写清「为什么加」（54s 的实测与参数含义）"
    wf = WORKFLOW.read_text(encoding="utf-8")
    assert "prefer-offline" in wf, "workflow 里没有这些参数 ⇒ 本判据会在一处都没有时假绿"
