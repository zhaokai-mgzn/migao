# case_ids: UI-046
"""admin-web 的 `next build` 门禁防回退锁（issue #4412）。

## 背景（2026-09-18 实测，非推断）

Next 的 **route 文件**（`page.tsx` / `layout.tsx` / `template.tsx` / `route.ts`）只允许导出
框架认识的字段（`default` / `metadata` / `generateMetadata` / `dynamic` / `revalidate` …）；
此外**预渲染期**的错误（模块顶层碰浏览器 API、SSG 取数崩）也只有 `next build` 会判。
**这两类 `tsc --noEmit` 结构上就看不见**，而 Next **14 没有 `next typegen`**（15+ 才有）
⇒ 在补本步之前，`next build` **只在 `deploy-frontend` 的 Docker 里跑**：

| 证据 | 实测值 |
|---|---|
| `export function describeRoutingGuard(...)` 写在 `routings/page.tsx`（#4323） | `tsc` 绿 / Docker `next build` 红：`"describeRoutingGuard" is not a valid Page export field` |
| 第二个同类实例（#4401 的 `feeGuardReasons`） | 同上 |
| `deploy-frontend` 连败 | **4 次**（15:36 / 16:08 / 17:50 / 20:04），最后一次成功是 **11:05** |
| 断链时长 | **≈11.5 小时** |
| 影响面（内容级） | `merchant.migaozn.com/production/routings` 与 `/production/processing-fees` = **404**（对照 `/production/operations` = 200）⇒ #4323/#4383/#4386/#4401 的前端「已合入 main 但测试环境不可达」 |
| 本地最小实验（本守卫之外） | 一个预渲染期抛错的探针页：`tsc --noEmit` = **exit 0**，`next build` = **exit 1**（`Error occurred prerendering page`） |

## 本守卫锁什么

`pr-check` 的 `admin-web-test` job 必须**保留**那一步 `npm run build`，且**保留路径门控**：

1. 存在一步执行 `npm run build`（Next-only 校验）—— 删掉它，上述形态会**静默**退回
   「CI 全绿、部署红」，且没有任何东西会变红；
2. 该步 `if:` 绑在 `Detect admin-web changes` 的 output 上 —— 否则每个 PR 都多花一次构建
   （实测本地 17s，CI ≈40s）；
3. Detect 步真的按 `frontend/admin-web/` 做 diff；
4. checkout 有 `fetch-depth: 0` —— 浅克隆拿不到 `origin/main...HEAD` 的 merge-base，
   门控会**恒判为「无变更」**（= 静默不跑，比不装还坏）。

**读 YAML 真值，不扫正则**（同 `test_workflow_issue_permissions.py` 的口径）：
按 `jobs.<id>.steps` 结构取，避免「注释里提一句就算数」的假绿。
"""
from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = Path(__file__).parent.parent.parent / ".github" / "workflows" / "pr-check.yml"
JOB = "admin-web-test"
BUILD_STEP = "Production build (Next-only checks)"
DETECT_STEP = "Detect admin-web changes"


def _job() -> dict:
    data = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    jobs = data.get("jobs") or {}
    assert JOB in jobs, f"{WORKFLOW_PATH.name} 里找不到 job `{JOB}`（被改名/删除？）"
    return jobs[JOB]


def _steps(job: dict) -> list:
    return job.get("steps") or []


def _by_name(job: dict, name: str) -> dict:
    for s in _steps(job):
        if s.get("name") == name:
            return s
    pytest.fail(f"`{JOB}` 里找不到名为 `{name}` 的 step（本守卫的锁点被删/改名）")


def test_admin_web_job_runs_next_build():
    """① 必须存在 `npm run build` 步 —— 这是 Next-only 契约的唯一机械判据。"""
    step = _by_name(_job(), BUILD_STEP)
    assert "npm run build" in (step.get("run") or ""), (
        f"`{BUILD_STEP}` 不再执行 `npm run build`：Next 的 route 文件导出契约与预渲染期错误"
        "只有它会判（issue #4412），删掉即退回「CI 绿、部署红」。"
    )
    assert step.get("working-directory") == "frontend/admin-web", "构建步必须在 admin-web 目录里跑"


def test_build_step_is_path_gated():
    """② 构建步必须绑在 Detect 步的 output 上（否则每个 PR 都白跑一次构建）。"""
    job = _job()
    detect = _by_name(job, DETECT_STEP)
    build = _by_name(job, BUILD_STEP)

    detect_id = detect.get("id")
    assert detect_id, f"`{DETECT_STEP}` 必须有 id，构建步才能引用它的 output"

    cond = build.get("if") or ""
    assert f"steps.{detect_id}.outputs." in cond, (
        f"`{BUILD_STEP}` 的 if 未引用 `steps.{detect_id}.outputs.*` ⇒ 路径门控失效（成本落到每个 PR）"
    )


def test_detect_step_diffs_admin_web_paths():
    """③ Detect 步必须真的按 `frontend/admin-web/` 做 diff，且非 PR 事件全量跑。"""
    run = _by_name(_job(), DETECT_STEP).get("run") or ""
    assert "frontend/admin-web/" in run, "Detect 步没按 admin-web 路径过滤 —— 门控判据不成立"
    assert "origin/main...HEAD" in run, "Detect 步没用三点 diff（merge-base 口径）"
    assert "GITHUB_OUTPUT" in run, "Detect 步没写 GITHUB_OUTPUT ⇒ 下游 if 永远拿不到值"
    assert 'GITHUB_EVENT_NAME" != "pull_request"' in run or "GITHUB_EVENT_NAME\" != \"pull_request\"" in run, (
        "Detect 步缺「非 PR 事件全量跑」分支 —— push main / workflow_dispatch 会静默不构建"
    )


def test_checkout_has_full_history():
    """④ checkout 必须 fetch-depth: 0 —— 浅克隆下三点 diff 拿不到 merge-base，门控会恒判「无变更」。"""
    job = _job()
    for s in _steps(job):
        if str(s.get("uses", "")).startswith("actions/checkout"):
            assert (s.get("with") or {}).get("fetch-depth") == 0, (
                "admin-web job 的 checkout 必须是 fetch-depth: 0 —— 否则 `origin/main...HEAD` 的 "
                "merge-base 取不到，Detect 步恒判「无 admin-web 变更」⇒ next build 静默不跑"
            )
            return
    pytest.fail("admin-web job 里找不到 actions/checkout 步")
