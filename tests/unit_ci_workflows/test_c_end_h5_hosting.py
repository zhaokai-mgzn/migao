# case_ids: MC-039
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式挂 MC-012；
#   本单是**新的一类**（C 端 H5 静态根落地面 + 「手动才发布」的触发面契约），按用例号顺延取 MC-039
#   （取号时现取：main 上 MC-001~MC-038 已占用、`.github/cases/` 与在飞 PR 均未占用该号）。）
r"""C 端小布 H5（`frontend/mini-app` 的 `build:h5` 产物）**静态根落地面**的常驻判据（issue #4184）。

## 病根（开工前现取复算，2026-09-27）

| 件 | 读数 |
|---|---|
| `curl -sI https://app.migaozn.com/js/app.js` 的 `Last-Modified` | `Sun, 30 Aug 2026 06:54:48 GMT`（比 `frontend/mini-app` 最近改动早 **28 天**） |
| 对照 B 端 `curl -sI https://app.migaozn.com/b/index.html` | `Sun, 27 Sep 2026 …`（今天的新构建） |
| `grep -rln '/opt/migao-deploy' .github/workflows/`（建腿前） | **0 命中** ⇒ C 端**没有任何部署通路** |
| ⇒ 结论 | 线上落后 28 天，而**没有任何东西会因此变红**（「C 端已部署」一直被当真） |

## 本守卫锁什么（每条都带注入式红证，见 `TestRedProofs`）

1. **通路存在**：`deploy/swas/c-end-h5-publish-remote.sh`（**发布逻辑单一出处**）、
   `deploy/scripts/c-end-h5-publish-ci.sh`（CI 包装）、`deploy/scripts/c-end-h5-verify-served.sh`
   （落地面断言）、`.github/workflows/c-end-h5-publish.yml` 四件齐备，且 workflow 的发布步骤调的是
   **那一份**远端执行体（不许把命令内联进 workflow 另写一份）；
2. 🔴 **合并本 PR 不会自动发布**（用户 2026-09-27 裁定 B）：`on.push.paths` **恰好**只含
   `frontend/mini-app/**`（不含 `deploy/**`，也不含 workflow 自身）**且**发布链路（发布/落地面断言两步）
   的 `if` 必须**逐字**要求 `github.event_name == 'workflow_dispatch'` **与** `inputs.publish == 'true'`
   ⇒ 对账面的兜底 dispatch（`workflow_dispatch`，不带 input）也**不会**发布；
   非手动触发时那条闸**判红并给出可复制命令**（不是静默 success —— 否则对账会把它读成「已发布」）；
3. 🔴 **红线：发布不得删除/覆盖 `w/`（工人端，线上有工人在用）与 `b/`（商家端）**：
   ① 结构层——`w` `b` 是远端脚本的**保留前缀**（`H5_RESERVED_PREFIXES`），既不许进产物顶层条目、
      也不许进托管清单；② 产物层——本腿 `index.html` 不许引用 `/<保留前缀>/…`；
   ③ 自证层——发布前后逐子树的**规范化摘要**与各自的 `index.html` 单文件哈希必须**逐字相等**
      （CI 包装侧四条读数缺一即判红）；
4. **首次发布由人签字**：远端脚本对「无人认领的根」判 `TAKEOVER_REQUIRED`（exit 2）并打印将要替换的
   条目；CI 包装**不带**任何能绕过它的开关（它带 `H5_TAKEOVER_FIRST_PUBLISH=1` 只是为了让
   「已登记过的根」不再触发该闸 —— 清单不在线上时它照样接管不了、`InvocationStatus` 非 Success ⇒ 判红）；
5. **判据本体（新鲜度）翻成 gate**（同批）：`scripts/h5_freshness_guard.py` **默认**判红
   （`::error::` + exit 2），`--no-gate` 才是报告型；`h5-freshness-guard.yml` 的 dispatch 输入
   是**反向**的 `no_gate`，且 **⛔ 无 cron**（用户 2026-09-21 裁定，未被推翻）、
   `workflow_run` 清单里新增了本腿（发布完成后立刻重判）；
6. **对账面同批接线**（FM-E3）：`deploy-reconcile.yml` 有新腿 `c-end-h5`（走漂移判据 ②），
   且它在 `test_swas_deploy_ci_hardening.py::SVC_TO_DEPLOY_WORKFLOW` 登记册里；本腿**触发面 ≠ 对账面**
   的那两条缺口（发布链路自身的两个文件）逐条登记在 `reconcile_trigger_paths_ledger.json`，
   并标 `never_in_trigger`（= 明文禁止「把它们加进触发面来消账」这条出路）；
7. **行为层（沙箱跑真脚本）**：在 `tmp_path` 造一个「静态根」沙箱（含 `w/`、`b/` 与一个清单外的
   `robots.txt`）⇒ 真跑远端执行体：首次发布必须先要 `--takeover-first-publish`（否则什么都别动）、
   发布后 `w/` `b/` `robots.txt` **逐字节不变**、幂等、陈旧托管条目被收敛、越界/缺根/坏清单一律拒绝。

**⚠️ 本文件刻意分两层**：结构层读**真 YAML / 真脚本文本**（注入式红证）；行为层**真跑**
`deploy/swas/c-end-h5-publish-remote.sh`（本地目录直达，**不联网、不碰真实静态根**，沙箱在 `tmp_path`）。
「测试测的是另一份实现」这个形态结构上不可能出现。

## 边界（照实登记，别把「登记了」读成「治住了」）

- **本文件不验证线上**：真实发布（SWAS RunCommand + `curl https://app.migaozn.com`）由
  `.github/workflows/c-end-h5-publish.yml` 在**人手动触发**时跑；首次发布**尚未发生** ⇒
  `/` 的 `last-modified` 是否变化**没有**在本机取证（属「没跑」，不是「通过」）。
- 本机**没有** nginx / docker / aliyun CLI ⇒ 证明不了 `nginx -t`、也跑不了 `RunCommand` 那一段
  （`c-end-h5-publish-ci.sh` 的云调用只是结构判据的对象）。
- **覆盖面之外**（如实登记）：SWAS 静态根里除托管清单外的其它内容（例如 `robots.txt`、证书挑战目录）、
  nginx 层（本腿不改 `nginx.conf`，`location /` 的 fallback 由既有判据承担）、CDN 缓存、
  `/w/` `/b/` 之外的其它子目录（若将来出现第四条腿，它不在本文件的 `H5_RESERVED_PREFIXES` 判据里）、
  **回滚路径**（远端脚本只在**拷贝失败**时回滚，回滚前备份在本机 `mktemp` 目录里、随进程退出删除 ⇒
  「发布成功后发现问题」没有回滚动作，只能再发一次上一版）。
"""
from __future__ import annotations

import copy
import hashlib
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "c-end-h5-publish.yml"
REMOTE_SCRIPT = REPO_ROOT / "deploy" / "swas" / "c-end-h5-publish-remote.sh"
CI_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "c-end-h5-publish-ci.sh"
VERIFY_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "c-end-h5-verify-served.sh"
FRESHNESS_SCRIPT = REPO_ROOT / "scripts" / "h5_freshness_guard.py"
FRESHNESS_WF = REPO_ROOT / ".github" / "workflows" / "h5-freshness-guard.yml"
RECONCILE_WF = REPO_ROOT / ".github" / "workflows" / "deploy-reconcile.yml"
RECONCILE_LEDGER = REPO_ROOT / "tests" / "unit_ci_workflows" / "reconcile_trigger_paths_ledger.json"

WORKFLOW_NAME = "c-end-h5-publish.yml"
# 兜底面（`FM-E17` 收口口径）：cron 的**单一真值**在台账里，判据两边互钉
FALLBACK_LEDGER = REPO_ROOT / "tests" / "unit_ci_workflows" / "publish_leg_fallback_ledger.json"
WORKFLOW_DISPLAY_NAME = "Publish C-end H5 (app.migaozn.com 根)"
JOB = "publish"
PUBLISH_SCRIPT = "deploy/scripts/c-end-h5-publish-ci.sh"
VERIFY_SERVED = "deploy/scripts/c-end-h5-verify-served.sh"
MINI_APP_GLOB = "frontend/mini-app/**"
STATIC_ROOT = "/opt/migao-deploy/h5"
MANIFEST = ".migao-c-end-h5-manifest.json"
RESERVED = ("w", "b")
STRAY_GLOBS = ("deploy/**",)

# 发布链路自身的两个文件**永远不许**进 `on.push.paths`（见 ledger 的 `never_in_trigger`）
CHAIN_FORBIDDEN_IN_TRIGGER = (".github/workflows/c-end-h5-publish.yml", PUBLISH_SCRIPT)

# 模式判定步（**唯一**决定「会不会发布」的地方）：它必须逐字包含这两条判据
MODE_STEP = "Resolve mode"
GATE_EVENT = "github.event_name"
GATE_INPUT = "inputs.publish"
MODE_PUBLISH = 'echo "mode=publish" >> "$GITHUB_OUTPUT"'
MODE_NOTIFY = 'echo "mode=notify" >> "$GITHUB_OUTPUT"'
PUBLISH_IF = "steps.mode.outputs.mode == 'publish'"
NOTIFY_IF = "steps.mode.outputs.mode != 'publish'"

DESTRUCTIVE_RE = re.compile(r"(rm\s+-[A-Za-z]*[rf][A-Za-z]*\b|--delete\b|-delete\b)")


# ── 读盘 / YAML（缺失即判据失败，不静默）──────────────────────────────────────

def _read(path: Path):
    return path.read_text(encoding="utf-8") if path.exists() else None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): _file_sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def _on_key(wf: dict):
    """yaml 会把裸 `on:` 解析成布尔 True 键（同 test_bmini_h5_hosting.py 的处理）。"""
    return "on" if "on" in wf else True


def _triggers(wf: dict) -> dict:
    value = wf.get("on")
    if value is None:
        value = wf.get(True)
    return value if isinstance(value, dict) else {}


def _steps(wf: dict) -> list:
    job = (wf.get("jobs") or {}).get(JOB) or {}
    steps = job.get("steps")
    return steps if isinstance(steps, list) else []


def _run_text(step) -> str:
    return str((step or {}).get("run") or "")


def _if_text(step) -> str:
    return str((step or {}).get("if") or "")


def _unsanctioned_destructive_lines(text: str) -> list:
    """破坏性语句必须只指向受守卫的目标或自建临时目录（源码层红线）。

    ⚠️ 注释处理口径（`tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py` 同族）：
    **只跳过整行注释**，**绝不**按 `#` 截断行 —— 朴素截断会让字符串里的 `#` 吃掉行尾（假绿）。
    """
    hits = []
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if not DESTRUCTIVE_RE.search(raw):
            continue
        # 白名单（与 test_bmini_h5_hosting.py 同口径）：自建临时目录 / 变量名明确的临时文件
        # ⚠️ `$STATIC_ROOT/$name` 只出现在**受清单约束**的删除上（`$name` 来自
        #    `MANAGED ∩ 磁盘现值`，首次发布为空集）⇒ 它是本腿唯一的写盘删除动作。
        if any(tok in raw for tok in ("$TARGET", "$WORK", "$BACKUP", "$out_file", "$STATIC_ROOT/$name")):
            continue
        hits.append(raw.strip())
    return hits


# ── 结构层：发布腿（纯函数 + 注入式红证）────────────────────────────────────

def _workflow_problems(wf, remote_src=None, ci_src=None, verify_src=None, wf_src=None) -> list:
    """⚠️ `wf_src` 必须可注入：否则「workflow 里内联第二份发布逻辑」这类**文本层**变异会去读磁盘原文
    ⇒ 变异永远看不见（实测：该变异漏判过一次）。"""
    if wf_src is None:
        wf_src = _read(WORKFLOW_PATH)
    if remote_src is None:
        remote_src = _read(REMOTE_SCRIPT)
    if ci_src is None:
        ci_src = _read(CI_SCRIPT)
    if verify_src is None:
        verify_src = _read(VERIFY_SCRIPT)
    problems: list = []

    if not remote_src:
        problems.append("远端执行体 deploy/swas/c-end-h5-publish-remote.sh 缺失 —— 发布逻辑没有单一出处")
    if not ci_src:
        problems.append("CI 发布脚本 deploy/scripts/c-end-h5-publish-ci.sh 缺失")
    if not verify_src:
        problems.append("落地面断言脚本 deploy/scripts/c-end-h5-verify-served.sh 缺失")

    on = _triggers(wf)
    if not on:
        problems.append("workflow 没有可识别的 on 触发器")
        return problems

    if wf.get("name") != WORKFLOW_DISPLAY_NAME:
        problems.append(
            f"workflow name 变了（现取 {wf.get('name')!r}）—— 它被 h5-freshness-guard.yml 的 "
            f"`workflow_run.workflows` 按**名字**引用，改名会让新鲜度判据不再被发布结果触发"
        )

    push = on.get("push") if isinstance(on.get("push"), dict) else {}
    if "main" not in (push.get("branches") or []):
        problems.append(f"push 触发面缺 main：{push.get('branches')}")
    paths = [str(p) for p in (push.get("paths") or [])]
    if paths != [MINI_APP_GLOB]:
        problems.append(
            f"🔴 on.push.paths 必须**恰好**只有 {MINI_APP_GLOB!r}，实际 {paths} —— "
            f"多一条（`deploy/**` / workflow 自身 / 别的目录）就意味着**改它就会跑这条腿**，"
            f"而它是发布腿（用户裁定 B：合并建通路的 PR 不许触发布）"
        )
    for forbidden in CHAIN_FORBIDDEN_IN_TRIGGER:
        if forbidden in paths:
            problems.append(f"🔴 on.push.paths 含发布链路自身 {forbidden} ⇒ 改链路即触发发布腿")
    for glob in STRAY_GLOBS:
        if glob in paths:
            problems.append(f"🔴 on.push.paths 含 {glob!r}（本 PR 的变更集落在 deploy/** ⇒ 会命中）")

    # —— 兜底面：`push` 在本仓会被吞 ⇒ 必须有 `schedule`（且 cron 与台账声明逐字一致）——
    # 真值只有一份（台账 `publish_leg_fallback_ledger.json`），判据从那里取 cron 再回到 YAML 里比对；
    # 取不到台账 ⇒ 判红（不是「跳过」）。
    schedule = on.get("schedule")
    crons = [str(e.get("cron")) for e in schedule if isinstance(e, dict)] if isinstance(schedule, list) else []
    if not crons:
        problems.append(
            "🔴 缺 `schedule` 兜底面：`push` 被 `GITHUB_TOKEN` 合并吞掉时这条腿**不会跑且无红**"
            "（FM-E17 口径；兜底面只报告不发布，见 notify 步）"
        )
    else:
        try:
            ledger = json.loads(FALLBACK_LEDGER.read_text(encoding="utf-8"))
            declared = next(
                (leg.get("fallback", {}).get("cron") for leg in ledger.get("legs", [])
                 if leg.get("file") == WORKFLOW_NAME), None
            )
        except Exception as exc:                     # 台账读不出来 ⇒ 宁可红，不猜
            declared = None
            problems.append(f"兜底面台账读不出来（{FALLBACK_LEDGER.name}）：{exc}")
        if declared is None:
            problems.append(f"台账 `{FALLBACK_LEDGER.name}` 里没有 {WORKFLOW_NAME} 的 `fallback.cron` 声明")
        elif declared not in crons:
            problems.append(f"兜底面 cron 与台账脱钩：台账声明 `{declared}`，现取 {crons}")
    if "pull_request" in on or "pull_request_target" in on:
        problems.append("不得有 pull_request 触发：本 workflow 写的是**线上静态根**，PR 分流内容不该有机会落上去")

    # —— 手动面：workflow_dispatch 的 `publish` 输入（默认 false）——
    dispatch = on.get("workflow_dispatch")
    if not isinstance(dispatch, dict):
        problems.append("缺 workflow_dispatch（人手动发布的唯一入口）")
    else:
        inputs = dispatch.get("inputs") or {}
        publish_input = inputs.get("publish") if isinstance(inputs, dict) else None
        if not isinstance(publish_input, dict):
            problems.append("workflow_dispatch 缺 `publish` 输入（这是「手动才发布」的签字开关）")
        else:
            if publish_input.get("type") != "boolean":
                problems.append(f"`publish` 输入必须是 boolean，实际 {publish_input.get('type')!r}")
            if publish_input.get("default") is not False:
                problems.append(
                    f"🔴 `publish` 输入默认值必须是 **false**（= 不发布），实际 {publish_input.get('default')!r} "
                    f"—— 默认 true 会让一次误 dispatch / 对账兜底 dispatch 直接发布"
                )

    # —— 发布链路两步的 if：逐字要求 workflow_dispatch + publish==true ——
    publish_steps = [s for s in _steps(wf) if PUBLISH_SCRIPT in _run_text(s)]
    verify_steps = [s for s in _steps(wf) if VERIFY_SERVED in _run_text(s)]
    build_steps = [s for s in _steps(wf) if "build:h5" in _run_text(s) and "npm run build:h5" in _run_text(s)]
    if len(publish_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个跑 {PUBLISH_SCRIPT} 的 step，实际 {len(publish_steps)}")
    if len(verify_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个跑 {VERIFY_SERVED} 的落地面断言 step，实际 {len(verify_steps)}")
    if len(build_steps) != 1:
        problems.append(f"job `{JOB}` 里必须有且只有 1 个 `npm run build:h5` step（产物必须在 CI 构建），实际 {len(build_steps)}")
    # ⚠️ 闸的口径（**模式判定 + 逐 step 消费**，两处都要钉）：
    #    ① 判定步 `Resolve mode` 是唯一决定「会不会发布」的地方 ⇒ 它必须逐字含两条判据
    #       （`github.event_name` 是 workflow_dispatch **且** `inputs.publish` 为 true）并**双向**写 mode；
    #    ② **写盘 / 依赖构建 / 落地面断言**的三步（build:h5 / 发布 / 断言）必须逐字 `if: <mode == 'publish'>`
    #       ⇒ 就算有人把判定步改成恒 publish，仍然要靠这个 if 才能发布（纵深防线）。
    mode_steps = [s for s in _steps(wf) if MODE_STEP in str(s.get("name") or "")]
    if len(mode_steps) != 1:
        problems.append(f"必须有且只有 1 个「{MODE_STEP}」step（模式判定 = 唯一决定会不会发布的地方），实际 {len(mode_steps)}")
    else:
        mode_run = _run_text(mode_steps[0])
        for token in (GATE_EVENT, GATE_INPUT, MODE_PUBLISH, MODE_NOTIFY,
                      "gh workflow run c-end-h5-publish.yml"):
            if token not in mode_run:
                problems.append(f"模式判定步的 run 缺 `{token}`")
        if str(mode_steps[0].get("id") or "") != "mode":
            problems.append(f"模式判定步的 `id` 必须是 `mode`（下游 if 引用它），实际 {mode_steps[0].get('id')!r}")
        if mode_steps[0].get("continue-on-error"):
            problems.append("模式判定步带 continue-on-error ⇒ 红被吞")

    # 写盘的那一步：必须逐字消费 mode
    for step in publish_steps:
        if PUBLISH_IF not in _if_text(step):
            problems.append(
                f"🔴 step `{step.get('name')}` 的 `if` 缺 `{PUBLISH_IF}` ⇒ 这条发布腿可能在**非发布模式**下发布"
            )
    # 构建 / 落地面断言：同样只在 publish 模式跑（否则 notify 模式会空跑构建或在没发布时假绿/假红）
    for step in build_steps + verify_steps:
        if PUBLISH_IF not in _if_text(step):
            problems.append(f"step `{step.get('name')}` 的 `if` 缺 `{PUBLISH_IF}`（非发布模式不该跑它）")
    for step in publish_steps + verify_steps + build_steps + mode_steps:
        cond = _if_text(step)
        if step.get("continue-on-error"):
            problems.append(f"step `{step.get('name')}` 带 continue-on-error ⇒ 红被吞")
        if "|| true" in _run_text(step):
            problems.append(f"step `{step.get('name')}` 带 `|| true` ⇒ 红被吞")
        if cond.strip().lower() in ("false", "0"):
            problems.append(f"step `{step.get('name')}` 的 if 恒假 ⇒ 红被吞")

    # —— notify 面：**唯一**会因为「线上落后」判红的地方 + 必须给出可复制命令 ——
    notify_steps = [s for s in _steps(wf) if "Notify" in str(s.get("name") or "")]
    if len(notify_steps) != 1:
        problems.append(f"缺「Notify」step（兜底面必须能报出「线上落后」，否则 cron 是空转），实际 {len(notify_steps)}")
    else:
        nt = notify_steps[0]
        if NOTIFY_IF not in _if_text(nt):
            problems.append(f"Notify 步的 `if` 必须是 `{NOTIFY_IF}`（只在非发布模式跑）")
        nrun = _run_text(nt)
        for token in ("::error::", "gh workflow run c-end-h5-publish.yml",
                      "scripts/h5_freshness_guard.py", "--ref origin/main", 'exit "$rc"'):
            if token not in nrun:
                problems.append(f"Notify 步的 run 缺 `{token}`（判红 / 可复制命令 / 事实基准 / 「没跑≠通过」）")
        if nt.get("continue-on-error"):
            problems.append("Notify 步带 continue-on-error ⇒ 线上落后也不会红（兜底面变空转）")

    # —— env：目标 / 清单 / 保留前缀 ——
    env = wf.get("env") or {}
    if env.get("H5_STATIC_ROOT") != STATIC_ROOT:
        problems.append(f"env.H5_STATIC_ROOT 必须是 {STATIC_ROOT}，实际 {env.get('H5_STATIC_ROOT')!r}")
    if env.get("H5_MANIFEST") != MANIFEST:
        problems.append(f"env.H5_MANIFEST 必须是 {MANIFEST!r}，实际 {env.get('H5_MANIFEST')!r}")
    if str(env.get("H5_RESERVED_PREFIXES") or "").split() != list(RESERVED):
        problems.append(
            f"🔴 env.H5_RESERVED_PREFIXES 必须是 {' '.join(RESERVED)!r}（w 工人端 / b 商家端），"
            f"实际 {env.get('H5_RESERVED_PREFIXES')!r}"
        )

    # —— 单一实现：workflow 只调 CI 包装，不内联发布命令 ——
    wf_text = wf_src or ""
    for token in ("H5_PUBLISH_SHA=", "codeload.github.com", "assert_target_safe", "H5_RESERVED_PREFIXES="):
        if token in wf_text:
            problems.append(f"workflow 里出现 `{token}` ⇒ 发布逻辑被内联了第二份（必须只调 {PUBLISH_SCRIPT}）")

    # —— CI 包装脚本：五条承重断言（逐字形态，不是「提到过这个词」）——
    if ci_src:
        for token in (
            'grep -q "^TARGET=$EXPECTED_TARGET$"',
            '[ "$REMOTE_INDEX_SHA" = "$LOCAL_SHA" ]',
            'grep -q "^PROTECTED_UNCHANGED=1$"',
            'grep -q "^ASSET_REFS_ROOT_SCOPED=1$"',
            '[ "$STATUS" = "Success" ] || die',
        ):
            if token not in ci_src:
                problems.append(f"CI 脚本缺少验收断言（逐字形态）`{token}`")
        if "PUBLISHED_INDEX_SHA256" not in ci_src:
            problems.append("CI 脚本缺少发布自证标记 `PUBLISHED_INDEX_SHA256`")
        # 保留子树的四个读数键是**按前缀循环拼出**的（`PROTECTED_${p}_BEFORE_SHA256` 等），
        # 故这里断言**拼法**逐字在案，而不是断言某一个具体前缀的字面量。
        for key in ("PROTECTED_${p}_BEFORE_SHA256", "PROTECTED_${p}_AFTER_SHA256",
                    "PROTECTED_${p}_BEFORE_INDEX_SHA256", "PROTECTED_${p}_AFTER_INDEX_SHA256"):
            if key not in ci_src:
                problems.append(f"CI 脚本缺少保留子树读数键的拼法 `{key}`")
        if 'LOCAL_INDEX="$DIST_DIR/index.html"' not in ci_src:
            problems.append("CI 脚本必须把 `frontend/mini-app/dist/index.html` 作为身份基准（产物单一源）")
        # 保留子树的四条读数必须真的被解析（写了变量不用 = 空断言）
        if 'PROTECTED_${p}_BEFORE_SHA256' not in ci_src or 'PROTECTED_${p}_AFTER_SHA256' not in ci_src:
            problems.append("CI 脚本没有逐条解析保留子树的 BEFORE/AFTER 读数（红线不可判）")
        for line in _unsanctioned_destructive_lines(ci_src):
            problems.append(f"CI 脚本里有未限定目标的破坏性语句（红线）：{line}")

    # —— 远端执行体：三组守卫函数 + 保留前缀 + 接管闸 ——
    if remote_src:
        for token in ("assert_target_safe() {", "assert_no_reserved_refs() {", "load_managed() {",
                      "compute_new_top_level() {", "compute_replacement() {", "apply_publish() {"):
            if token not in remote_src:
                problems.append(f"远端脚本必须定义 {token}")
        # 删除范围必须是「上一次清单 ∩ 磁盘现值」——这条是红线一（绝不删静态根）的机械载体
        for token in ("MANAGED_TOP_LEVEL_DELETE", "compute_replacement() {", "DELETE=") :
            if token not in remote_src:
                problems.append(f"远端脚本缺删除范围读数/机制 `{token}`")
        for token in ("TAKEOVER_REQUIRED" if False else "需要 `--takeover-first-publish`", "PROTECTED_", "MANAGED_TOP_LEVEL_DELETE"):
            if token not in remote_src:
                problems.append(f"远端脚本缺 `{token}`（首次发布的签字闸 / 保留子树自证 / 删除范围读数）")
        if "H5_RESERVED_PREFIXES" not in remote_src:
            problems.append("远端脚本没有保留前缀机制（红线二的结构层）")
        # 红线二结构层的**fail-closed 落点**：产物顶层出现保留前缀 ⇒ 立刻 die（不是「跳过它继续发」）
        if 'is_reserved "$name" && die' not in remote_src:
            problems.append("远端脚本的「产物顶层出现保留前缀 ⇒ die」这一步不见了（红线二结构层失效）")
        if 'is_reserved "$name" && die' not in remote_src or 'die "清单里出现保留前缀' not in remote_src:
            problems.append("远端脚本的「清单被保留前缀污染 ⇒ die」这一步不见了（红线二结构层失效）")
        for line in _unsanctioned_destructive_lines(remote_src):
            problems.append(f"远端脚本里有未限定目标的破坏性语句（红线）：{line}")

    return problems


def _load_workflow() -> dict:
    text = _read(WORKFLOW_PATH)
    if text is None:
        pytest.fail(
            f"{WORKFLOW_PATH.relative_to(REPO_ROOT)} 不存在 —— C 端 H5 又回到「没有任何部署通路」"
            "（issue #4184 的形态本身）。删本 workflow 必须同时给出替代接线。"
        )
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def test_real_publish_leg_has_no_problems():
    problems = _workflow_problems(_load_workflow())
    assert problems == [], "发布接线判据不通过：\n  - " + "\n  - ".join(problems)


class TestRedProofs:
    """每条判据都要能单独变红（变异 ⇒ 必红），并附「只改注释 ⇒ 不红」对照。"""

    def _mutations(self, wf) -> dict:
        def add_deploy_glob(mut):
            _triggers(mut)["push"]["paths"].append("deploy/**")

        def add_self_path(mut):
            _triggers(mut)["push"]["paths"].append(".github/workflows/c-end-h5-publish.yml")

        def add_pull_request(mut):
            _triggers(mut)["pull_request"] = {"paths": [MINI_APP_GLOB]}

        def publish_default_true(mut):
            _triggers(mut)["workflow_dispatch"]["inputs"]["publish"]["default"] = True

        def drop_dispatch_face(mut):
            _triggers(mut).pop("workflow_dispatch")

        def drop_gate_on_publish(mut):
            for step in _steps(mut):
                if PUBLISH_SCRIPT in _run_text(step):
                    step.pop("if", None)

        def gate_only_event(mut):
            for step in _steps(mut):
                if PUBLISH_SCRIPT in _run_text(step):
                    step["if"] = GATE_EVENT

        def silence_gate(mut):
            for step in _steps(mut):
                if MODE_STEP in str(step.get("name") or ""):
                    step["continue-on-error"] = True

        def drop_gate_step(mut):
            mut["jobs"][JOB]["steps"] = [
                s for s in _steps(mut) if MODE_STEP not in str(s.get("name") or "")
            ]

        def mode_always_publish(mut):
            """把模式判定改成恒 publish（= 闸失效）。"""
            for step in _steps(mut):
                if MODE_STEP in str(step.get("name") or ""):
                    step["run"] = 'echo "mode=publish" >> "$GITHUB_OUTPUT"'

        def notify_always_green(mut):
            """notify 步不再会因为「线上落后」判红（兜底面变空转）。"""
            for step in _steps(mut):
                if "Notify" in str(step.get("name") or ""):
                    step["run"] = "echo 'nothing to see here'"

        def drop_schedule(mut):
            _triggers(mut).pop("schedule")

        def retarget_cron(mut):
            _triggers(mut)["schedule"] = [{"cron": "0 0 * * *"}]

        def retarget_root(mut):
            mut["env"]["H5_STATIC_ROOT"] = "/opt/migao-deploy"

        def drop_reserved(mut):
            mut["env"].pop("H5_RESERVED_PREFIXES", None)

        def reserved_only_w(mut):
            mut["env"]["H5_RESERVED_PREFIXES"] = "w"

        def drop_publish_step(mut):
            mut["jobs"][JOB]["steps"] = [s for s in _steps(mut) if PUBLISH_SCRIPT not in _run_text(s)]

        def drop_verify_step(mut):
            mut["jobs"][JOB]["steps"] = [s for s in _steps(mut) if VERIFY_SERVED not in _run_text(s)]

        def silence_verify(mut):
            for step in _steps(mut):
                if VERIFY_SERVED in _run_text(step):
                    step["continue-on-error"] = True

        def inline_remote_logic(mut):
            """把远端脚本的活儿内联进 workflow（= 出现第二份发布实现）。"""
            for step in _steps(mut):
                if PUBLISH_SCRIPT in _run_text(step):
                    step["run"] = step["run"] + "\n          H5_PUBLISH_SHA=abc1234\n"

        def rename_workflow(mut):
            mut["name"] = "publish c-end h5"

        return {
            "触发面加 deploy/**（合并本 PR 即发布）": add_deploy_glob,
            "触发面加 workflow 自身": add_self_path,
            "给发布腿加 pull_request 触发": add_pull_request,
            "publish 输入默认改成 true": publish_default_true,
            "删掉 workflow_dispatch（人的入口）": drop_dispatch_face,
            "发布步骤去掉 if（任何触发都会发）": drop_gate_on_publish,
            "发布步骤 if 只判 event 不判 publish": gate_only_event,
            "模式判定步 continue-on-error": silence_gate,
            "删掉模式判定步": drop_gate_step,
            "模式判定恒 publish（闸失效）": mode_always_publish,
            "notify 步不再因落后判红（兜底面空转）": notify_always_green,
            "删掉 schedule 兜底面": drop_schedule,
            "改 cron（与台账声明脱钩）": retarget_cron,
            "把静态根改成上层目录": retarget_root,
            "去掉保留前缀（w/b 不再受保护）": drop_reserved,
            "保留前缀只剩 w（b 失去保护）": reserved_only_w,
            "删掉发布步": drop_publish_step,
            "删掉落地面断言步": drop_verify_step,
            "落地面断言 continue-on-error": silence_verify,
            "workflow 里内联第二份发布逻辑": inline_remote_logic,
            "改 workflow name（新鲜度 workflow_run 失联）": rename_workflow,
        }

    def test_every_workflow_mutation_is_detected(self):
        wf = _load_workflow()
        undetected = []
        for name, mutate in self._mutations(wf).items():
            mutant = copy.deepcopy(wf)
            mutate(mutant)
            # 文本层判据（「不许内联第二份实现」）必须看到**变异后的文本** ⇒ 由对象重新序列化得到
            mutant_src = yaml.safe_dump(mutant, allow_unicode=True, sort_keys=False)
            if len(_workflow_problems(mutant, wf_src=mutant_src)) == 0:
                undetected.append(name)
        assert undetected == [], f"这些变异**没有被判红**（= 空断言）：{undetected}"

    def test_comment_only_edit_does_not_turn_red(self):
        """对照：**只改注释** ⇒ 不红（判据读结构，不吃自己的说明文字）。"""
        original = _read(WORKFLOW_PATH) or ""
        annotated = original.replace(
            "on:\n", "# 注释：本腿只在手动授权时发布（publish=true），合并不会发布\non:\n", 1
        )
        assert annotated != original, "变异注入未生效（找不到 on: 锚点）"
        loaded = yaml.safe_load(annotated)
        assert _workflow_problems(loaded) == [], "只加一行注释竟判红（判据在吃自己的文案）"

    def test_script_mutations_are_all_detected(self):
        ci_src = _read(CI_SCRIPT)
        remote_src = _read(REMOTE_SCRIPT)
        assert isinstance(ci_src, str) and isinstance(remote_src, str), "发布脚本缺失 ⇒ 无法做脚本层红证"

        no_identity = ci_src.replace('[ "$REMOTE_INDEX_SHA" = "$LOCAL_SHA" ]', "true")
        assert no_identity != ci_src, "变异注入未生效（找不到产物身份断言）"
        no_protected = ci_src.replace('grep -q "^PROTECTED_UNCHANGED=1$"', "true")
        assert no_protected != ci_src, "变异注入未生效（找不到保留子树自证断言）"
        no_reserved_parse = ci_src.replace('PROTECTED_${p}_AFTER_SHA256', "PROTECTED_dropped_AFTER_SHA256")
        assert no_reserved_parse != ci_src, "变异注入未生效（找不到保留子树的 AFTER 读数解析）"
        root_delete = ci_src + '\nrm -rf "$STATIC_ROOT/"\n'
        remote_root_delete = remote_src + '\nrm -rf "$STATIC_ROOT"\n'
        drop_reserved_check = remote_src.replace('is_reserved "$name" && die', 'true')
        assert drop_reserved_check != remote_src, "变异注入未生效（找不到保留前缀的 fail-closed 行）"

        samples = {
            "CI：去掉「线上哈希 == 本次构建」断言": (ci_src, no_identity),
            "CI：去掉保留子树自证断言": (ci_src, no_protected),
            "CI：不再解析保留子树的 AFTER 读数": (ci_src, no_reserved_parse),
            "CI：新增未限定目标的删除": (ci_src, root_delete),
            "远端：新增未限定目标的删除": (remote_src, remote_root_delete),
            "远端：去掉「产物顶层出现保留前缀 ⇒ die」": (remote_src, drop_reserved_check),
        }
        undetected = []
        for name, (src, mutant) in samples.items():
            kwargs = {"ci_src": mutant} if src is ci_src else {"remote_src": mutant}
            if len(_workflow_problems(_load_workflow(), **kwargs)) == 0:
                undetected.append(name)
        assert undetected == [], f"这些脚本变异**没有被判红**（= 空断言）：{undetected}"

    def test_script_comment_only_edit_does_not_turn_red(self):
        """对照：脚本里**只加注释** ⇒ 不红（含把破坏性语句写进注释的形态）。"""
        remote_src = _read(REMOTE_SCRIPT) or ""
        annotated = remote_src.replace(
            "set -euo pipefail\n",
            "set -euo pipefail\n# 说明：本脚本绝不 rm -rf $STATIC_ROOT（这句是注释，不是动作）\n",
            1,
        )
        assert annotated != remote_src
        assert _workflow_problems(_load_workflow(), remote_src=annotated) == []


# ── 对账面 / 登记面 ─────────────────────────────────────────────────────────

def test_reconcile_has_the_c_end_leg_and_it_is_registered():
    """FM-E3：触发面与对账面**同批**接线；腿必须同时进登记册（条数派生，不写死）。"""
    reconcile = _read(RECONCILE_WF) or ""
    assert "reconcile_one c-end-h5 c-end-h5-publish.yml frontend/mini-app" in reconcile, (
        "deploy-reconcile.yml 里没有 c-end-h5 腿 ⇒ 改 frontend/mini-app 而 push 被 auto-merge 吞掉时"
        "**静默不发布**（#5001 同族）"
    )
    registry = _read(REPO_ROOT / "tests" / "unit_ci_workflows" / "test_swas_deploy_ci_hardening.py") or ""
    assert '"c-end-h5": "c-end-h5-publish.yml"' in registry, (
        "腿没有进 SVC_TO_DEPLOY_WORKFLOW 登记册 ⇒ `T1`（逐服务调用数 == 登记册条目数）会红"
    )
    assert "--seen 6" in reconcile, (
        "存活读数的 `--seen` 必须跟着腿数走（6 条：3 镜像腿 + 3 条静态落地面腿）——"
        "读数与事实不一致就是 #5264 的形态"
    )


def test_reconcile_leg_dispatches_are_safe_manual_only():
    """对账的兜底 dispatch 也**不会**发布：workflow_dispatch 不带 input ⇒ 闸判红说明（不是发布）。"""
    wf = _load_workflow()
    inputs = _triggers(wf)["workflow_dispatch"]["inputs"]
    assert inputs["publish"]["default"] is False, "publish 默认不是 false ⇒ 对账 dispatch 会直接发布"
    publish_steps = [s for s in _steps(wf) if PUBLISH_SCRIPT in _run_text(s)]
    assert len(publish_steps) == 1
    assert PUBLISH_IF in _if_text(publish_steps[0]), "发布步骤没有消费 `mode == 'publish'`"
    mode = [s for s in _steps(wf) if MODE_STEP in str(s.get("name") or "")]
    assert len(mode) == 1 and GATE_INPUT in _run_text(mode[0]), "模式判定步没有读 `inputs.publish`"


def test_chain_files_are_registered_as_never_in_trigger():
    """发布链路自身的两个文件必须挂台账 + `never_in_trigger`（明文禁止「加进触发面消账」）。"""
    import json

    ledger = json.loads(RECONCILE_LEDGER.read_text(encoding="utf-8"))
    marks = {str(e["path"]): bool(e.get("never_in_trigger")) for e in ledger["entries"] if e.get("svc") == "c-end-h5"}
    for path in CHAIN_FORBIDDEN_IN_TRIGGER:
        assert path in marks, f"{path} 没有登记进缺口台账（未登记即红）"
        assert marks[path] is True, (
            f"{path} 的台账条目缺 `never_in_trigger: true` ⇒ 台账会把「加进触发面」当成合法消账路子，"
            f"而那正是本单禁止的（合并即发布）"
        )
    triggers = [str(p) for p in _triggers(_load_workflow())["push"]["paths"]]
    for path in CHAIN_FORBIDDEN_IN_TRIGGER:
        assert path not in triggers, f"{path} 出现在 on.push.paths 里（与 never_in_trigger 矛盾）"


# ── 新鲜度判据翻 gate（同批）───────────────────────────────────────────────

def test_freshness_guard_defaults_to_gate():
    """默认判红：陈旧 ⇒ `::error::` + exit 2（`--no-gate` 才是报告型）。"""
    text = _read(FRESHNESS_SCRIPT) or ""
    assert 'level = "warning" if not args.gate else "error"' in text, (
        "陈旧分支的输出等级不再由 gate 决定（翻红被撤掉了？）"
    )
    assert '"--no-gate", dest="gate", action="store_false"' in text, (
        "缺 `--no-gate`（默认判红的反向开关）"
    )
    assert text.count('if verdict == "stale" and args.gate:') == 1, "陈旧分支的判红出口不见了"
    assert "EXIT_STALE = 0" not in text and "EXIT_STALE, EXIT_UNKNOWN = 0, 1, 2, 3" in text, (
        "退出码常量被改动（EXIT_STALE 必须仍是 2）"
    )


def test_freshness_guard_still_has_no_cron_and_keeps_three_states():
    """⛔ 无 cron（用户 2026-09-21 裁定未被推翻）；三态分离（取不到读数 ≠ 新鲜）。"""
    wf = yaml.safe_load(_read(FRESHNESS_WF) or "")
    on = _triggers(wf if isinstance(wf, dict) else {})
    assert "schedule" not in on, "h5-freshness-guard 加了 schedule/cron（用户 2026-09-21 裁定：⛔ 无 cron）"
    assert WORKFLOW_DISPLAY_NAME in (on.get("workflow_run", {}) or {}).get("workflows", []), (
        f"workflow_run.workflows 里没有 {WORKFLOW_DISPLAY_NAME!r} ⇒ 本腿发布完成后不会立刻重判新鲜度"
    )
    inputs = (on.get("workflow_dispatch") or {}).get("inputs") or {}
    assert "no_gate" in inputs and inputs["no_gate"].get("default") is False, (
        "dispatch 面必须是反向开关 `no_gate`（默认 false = 判红）；旧的 `gate` 语义会让默认退回告警"
    )
    text = _read(FRESHNESS_SCRIPT) or ""
    assert 'return "unknown"' in text and "EXIT_UNKNOWN, EXIT_OK" not in text, "三态判定被改动"
    assert "def judge(" in text and 'if live is None:' in text and 'if source is None:' in text, (
        "三态分离（取不到线上读数 / 取不到源码改动 ⇒ unknown）被削弱"
    )


def test_freshness_workflow_passes_no_gate_only_when_asked():
    """workflow 只在显式勾 `no_gate` 时传 `--no-gate`（默认不传 ⇒ 判红）。"""
    wf = yaml.safe_load(_read(FRESHNESS_WF) or "")
    runs = "\n".join(_run_text(s) for s in ((wf.get("jobs") or {}).get("h5-freshness") or {}).get("steps") or [])
    assert 'GATE_FLAG="--no-gate"' in runs, "不再组装 `--no-gate`（反向开关没接线）"
    assert 'GATE_FLAG="--gate"' not in runs, "还在组装 `--gate`（旧语义 ⇒ 默认退回只告警）"


# ── 行为层：沙箱里真跑远端脚本（不联网、不碰真实静态根）──────────────────────

def _make_static_root(tmp_path: Path, manifest: bool = False, stale_chunk: bool = False) -> Path:
    """造「线上根」的沙箱：C 端旧产物 + **工人端 `w/`** + **商家端 `b/`** + 一个清单外的文件。"""
    root = tmp_path / "h5"
    (root / "js").mkdir(parents=True)
    (root / "css").mkdir()
    (root / "index.html").write_text("<!doctype html><title>C 端旧产物</title>", encoding="utf-8")
    (root / "js" / "app.js").write_text("// C 端旧 app.js", encoding="utf-8")
    (root / "css" / "app.css").write_text(".c-end-old{}", encoding="utf-8")
    (root / "w" / "src").mkdir(parents=True)
    (root / "w" / "index.html").write_text("<!doctype html><title>工人端</title>", encoding="utf-8")
    (root / "w" / "src" / "app.mjs").write_text("// worker app", encoding="utf-8")
    (root / "b" / "js").mkdir(parents=True)
    (root / "b" / "index.html").write_text("<!doctype html><title>商家端</title>", encoding="utf-8")
    (root / "b" / "js" / "app.js").write_text("// bmini app", encoding="utf-8")
    (root / "robots.txt").write_text("User-agent: *\n", encoding="utf-8")
    if stale_chunk:
        (root / "chunk").mkdir()
        (root / "chunk" / "850.js").write_text("// 上一版留下的", encoding="utf-8")
    if manifest:
        import json
        managed = ["css", "index.html", "js"] + (["chunk"] if stale_chunk else [])
        (root / MANIFEST).write_text(json.dumps({"managed_top_level": managed}), encoding="utf-8")
    return root


def _make_dist(tmp_path: Path, ref: str = "/js/app.js", app_js: str = "// C 端新 app.js") -> Path:
    dist = tmp_path / "dist"
    (dist / "js").mkdir(parents=True, exist_ok=True)
    (dist / "css").mkdir(exist_ok=True)
    (dist / "index.html").write_text(
        f'<!doctype html><title>米高窗帘 · 小布智能助手</title><script defer src="{ref}"></script>'
        '<link href="/css/app.css" rel="stylesheet">',
        encoding="utf-8",
    )
    (dist / "js" / "app.js").write_text(app_js, encoding="utf-8")
    (dist / "css" / "app.css").write_text(".c-end-new{}", encoding="utf-8")
    return dist


def _run_remote(root: Path, dist: Path = None, *args: str, env_extra: dict | None = None):
    env = dict(os.environ)
    env["H5_STATIC_ROOT"] = str(root)
    env.pop("H5_PUBLISH_FROM_DIR", None)
    env.pop("H5_PUBLISH_SHA", None)
    if env_extra:
        env.update(env_extra)
    cmd = ["bash", str(REMOTE_SCRIPT)]
    if dist is not None:
        cmd += ["--from-dir", str(dist)]
    cmd += list(args)
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=180, cwd=str(REPO_ROOT),
    )


def test_sandbox_first_publish_requires_explicit_takeover(tmp_path):
    """首次发布：根上有无人认领的条目 ⇒ 拒绝（exit 2）、**什么都不改**，并打印将要替换的计划。"""
    root = _make_static_root(tmp_path)
    before = _tree(root)
    proc = _run_remote(root, _make_dist(tmp_path), "--apply")
    assert proc.returncode == 2, f"无人认领的根竟被接管（rc={proc.returncode}）：\n{proc.stdout}\n{proc.stderr}"
    assert "无人认领" in proc.stderr and "--takeover-first-publish" in proc.stderr, proc.stderr
    assert "PLANNED_ACTIONS_BEGIN" in proc.stdout, "拒绝时必须打印将要替换的条目（让人看清再决定）"
    assert _tree(root) == before, "拒绝路径上静态根被改动（红线）"

    # dry-run（默认）同样不写盘
    proc = _run_remote(root, _make_dist(tmp_path))
    assert proc.returncode == 2, f"dry-run 也应在「无人认领」上拒绝：{proc.stdout}"
    assert _tree(root) == before, "dry-run 改动了静态根"


def test_sandbox_publish_preserves_w_and_b_and_manifest_only_subtree(tmp_path):
    """🔴 本单最重要的一条：发布后 `w/` `b/` 与清单外文件**逐字节不变**，托管条目被替换。"""
    root = _make_static_root(tmp_path, manifest=True, stale_chunk=True)
    dist = _make_dist(tmp_path, app_js="// C 端新 app.js v2")
    w_before, b_before = _tree(root / "w"), _tree(root / "b")
    robots_before = _file_sha(root / "robots.txt")

    proc = _run_remote(root, dist, "--apply")
    assert proc.returncode == 0, f"发布失败：\n{proc.stdout}\n{proc.stderr}"

    # ① 身份：线上 index.html == 本次产物
    assert _file_sha(root / "index.html") == _file_sha(dist / "index.html")
    assert (root / "js" / "app.js").read_text(encoding="utf-8") == "// C 端新 app.js v2"
    # ② 陈旧托管条目被收敛（幂等的另一半）
    assert not (root / "chunk").exists(), "上一次托管的陈旧条目没有被收敛"
    # ③ 🔴 红线：w/ b/ 与清单外文件逐字节不变
    assert _tree(root / "w") == w_before, "工人端 w/ 被改动（红线）"
    assert _tree(root / "b") == b_before, "商家端 b/ 被改动（红线）"
    assert _file_sha(root / "robots.txt") == robots_before, "清单外文件被改动（红线）"
    # ④ 自证读数必须在输出里，且 BEFORE == AFTER（逐字）
    for p in RESERVED:
        before = re.search(rf"^PROTECTED_{p}_BEFORE_SHA256=(.+)$", proc.stdout, re.M)
        after = re.search(rf"^PROTECTED_{p}_AFTER_SHA256=(.+)$", proc.stdout, re.M)
        ib = re.search(rf"^PROTECTED_{p}_BEFORE_INDEX_SHA256=(.+)$", proc.stdout, re.M)
        ia = re.search(rf"^PROTECTED_{p}_AFTER_INDEX_SHA256=(.+)$", proc.stdout, re.M)
        assert all(isinstance(m, re.Match) for m in (before, after, ib, ia)), f"缺 {p} 的自证读数：\n{proc.stdout}"
        assert before.group(1).strip() == after.group(1).strip(), f"{p}/ 摘要前后不一致"
        assert ib.group(1).strip() == ia.group(1).strip(), f"{p}/index.html 哈希前后不一致"
        assert ib.group(1).strip() == _file_sha(root / p / "index.html")
    assert "PROTECTED_UNCHANGED=1" in proc.stdout
    assert "ROOT_INDEX_BEFORE_SHA256=" in proc.stdout and "ROOT_INDEX_AFTER_SHA256=" in proc.stdout


def test_sandbox_publish_is_idempotent(tmp_path):
    """连跑两次：**托管内容**逐字节一致；清单里除时间戳外的字段也一致（幂等的另一半）。"""
    import json

    root = _make_static_root(tmp_path, manifest=True)
    dist = _make_dist(tmp_path)
    first = _run_remote(root, dist, "--apply")
    assert first.returncode == 0, first.stdout + first.stderr
    # ⚠️ 清单**有意**写 `written_at_utc`（每轮发布的时间戳）⇒ 逐字节比较它会把「幂等」判成不幂等；
    #    故先摘掉清单比托管内容，再单独比清单里那三个**稳定**字段。
    tree = {k: v for k, v in _tree(root).items() if k != MANIFEST}
    m1 = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    second = _run_remote(root, dist, "--apply")
    assert second.returncode == 0, second.stdout + second.stderr
    assert {k: v for k, v in _tree(root).items() if k != MANIFEST} == tree, "连跑两次托管内容不一致（不幂等）"
    m2 = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    for key in ("managed_top_level", "published_index_sha256"):
        assert m1[key] == m2[key], f"清单的 `{key}` 在两次发布之间变了（{m1[key]!r} → {m2[key]!r}）"


def test_sandbox_refuses_product_that_references_the_other_apps(tmp_path):
    """产物层：index.html 引用 `/b/`（别的应用的命名空间）或相对路径 ⇒ 拒绝，且根不动。"""
    for ref, marker in (("/b/js/app.js", "别的应用"), ("./js/app.js", "相对路径")):
        root = _make_static_root(tmp_path / f"case-{abs(hash(ref))}", manifest=True)
        before = _tree(root)
        proc = _run_remote(root, _make_dist(tmp_path / f"d-{abs(hash(ref))}", ref=ref), "--apply")
        assert proc.returncode == 3, f"坏引用 {ref!r} 竟被发布：\n{proc.stdout}"
        assert marker in proc.stderr, f"判红信息里找不到 {marker!r}：{proc.stderr}"
        assert _tree(root) == before, f"拒绝 {ref!r} 时静态根被改动（红线）"


def test_sandbox_refuses_reserved_prefix_in_product_and_in_manifest(tmp_path):
    """结构层两条：产物顶层出现 `w/` ⇒ 拒绝；清单被污染（含 `w`）⇒ 拒绝。"""
    dist = _make_dist(tmp_path)
    (dist / "w").mkdir(exist_ok=True)
    (dist / "w" / "index.html").write_text("<!doctype html><title>伪装成工人端</title>", encoding="utf-8")
    root = _make_static_root(tmp_path / "r1", manifest=True)
    w_before = _tree(root / "w")
    proc = _run_remote(root, dist, "--apply")
    assert proc.returncode == 3, f"产物顶层的保留前缀竟被接受：\n{proc.stdout}"
    assert "保留前缀" in proc.stderr, proc.stderr
    assert _tree(root / "w") == w_before, "工人端被产物覆盖（红线）"

    import json
    root2 = _make_static_root(tmp_path / "r2")
    (root2 / MANIFEST).write_text(json.dumps({"managed_top_level": ["css", "index.html", "js", "w"]}), encoding="utf-8")
    w_before2 = _tree(root2 / "w")
    proc = _run_remote(root2, _make_dist(tmp_path / "d2"), "--apply")
    assert proc.returncode == 3, f"被污染的清单竟被按它删除：\n{proc.stdout}"
    assert _tree(root2 / "w") == w_before2, "按被污染的清单删除了工人端（红线）"


def test_sandbox_refuses_unsafe_targets_and_unreadable_manifest(tmp_path):
    """目标守卫：软链 / 不存在的根 / `/` / 坏清单 ⇒ 拒绝（fail-closed，且不新建目录）。"""
    dist = _make_dist(tmp_path)

    link = tmp_path / "link"
    real = _make_static_root(tmp_path / "real")
    link.symlink_to(real)
    proc = _run_remote(link, dist, "--apply")
    assert proc.returncode != 0 and "软链" in proc.stderr, f"软链静态根竟被接受：{proc.stdout}{proc.stderr}"

    absent = tmp_path / "nope" / "h5"
    proc = _run_remote(absent, dist, "--apply")
    assert proc.returncode != 0 and "不存在" in proc.stderr, f"不存在的根竟被接受：{proc.stdout}{proc.stderr}"
    assert not absent.exists(), "拒绝路径上不许建目录"

    proc = _run_remote(Path("/"), dist, "--apply")
    assert proc.returncode != 0 and "不能是 /" in proc.stderr, f"`/` 竟被接受：{proc.stdout}{proc.stderr}"

    root = _make_static_root(tmp_path / "r4")
    (root / MANIFEST).write_text("not json", encoding="utf-8")
    before = _tree(root)
    proc = _run_remote(root, dist, "--apply")
    assert proc.returncode != 0 and "读不出来" in proc.stderr, f"坏清单竟被接受：{proc.stdout}{proc.stderr}"
    assert _tree(root) == before, "坏清单路径上静态根被改动"


def test_sandbox_dry_run_by_default_changes_nothing(tmp_path):
    """默认 dry-run：打印计划、`PROTECTED_UNCHANGED=not-evaluated`、静态根逐字节不变。"""
    root = _make_static_root(tmp_path, manifest=True)
    before = _tree(root)
    proc = _run_remote(root, _make_dist(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY_RUN=1" in proc.stdout and "PROTECTED_UNCHANGED=not-evaluated" in proc.stdout
    assert _tree(root) == before, "dry-run 改动了静态根"


def test_reserved_subtree_digest_really_moves_when_touched(tmp_path):
    """红证（变异真被读到）：动一下 `w/` 里一个字节 ⇒ 两次采样必须**不再相等**。

    这条防的是「摘要恒等」这种空断言：如果 `subtree_digest()` 写坏（例如漏掉内容、只比路径），
    上面的「BEFORE == AFTER」会永远成立。这里直接对**摘要函数**做双侧取样。
    """
    root = _make_static_root(tmp_path, manifest=True)
    digest_cmd = (
        'cd "$1" && find . -type f -print0 | sort -z | while IFS= read -r -d "" f; do '
        'printf "%s  %s\\n" "${f#./}" "$(shasum -a 256 "$f" | awk \'{print $1}\')"; done '
        '| shasum -a 256 | awk \'{print $1}\''
    )

    def digest(path: Path) -> str:
        out = subprocess.run(["bash", "-c", digest_cmd, "_", str(path)], capture_output=True, text=True)
        return out.stdout.strip()

    before = digest(root / "w")
    assert before, "摘要为空 ⇒ 空断言"
    (root / "w" / "src" / "app.mjs").write_text("// worker app 被改了一个字节", encoding="utf-8")
    after = digest(root / "w")
    assert after and after != before, f"内容变了而摘要不变（摘要函数是空断言）：{before} == {after}"


# ── 落地面断言脚本自身的红/绿两面（防空断言）─────────────────────────────────

# 「上一版线上产物」的一页（08-30 那次发布的形态：结构相同、标题与注释不同 ⇒ 哈希不同）
STALE_C_END_PAGE = (
    '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"/>'
    "<title>米高窗帘 · 小布智能助手</title>"
    "<script>window.TARO_ENV = 'h5'</script>"
    '<script defer="defer" src="/js/2.js"></script>'
    '<script defer="defer" src="/js/app.js"></script>'
    '<link href="/css/app.css" rel="stylesheet"></head>'
    '<body><div id="app"></div><!-- 08-30 那版 --></body></html>'
).encode("utf-8")


class _NginxishServer:
    """一个**只实现本单用到的 nginx 语义**的本地 server（前缀 location + try_files + index）。

    `mode` 用来造四种坏形态：
      · ``ok``            —— 线上已按本单的部署生效（根 = 本次构建；`/w/` `/b/` 都是自己的产物）
      · ``stale_root``    —— 根还是**旧产物**（本单要治的形态本身：HTTP 200 但是 08-30 那版）
      · ``w_overwritten`` —— 根发布把**工人端** `/w/` 覆盖成了 C 端产物（红线）
      · ``b_overwritten`` —— 根发布把**商家端** `/b/` 覆盖成了 C 端产物（红线）
      · ``root_stray_ref``—— 根 index.html 引用了 `/b/js/app.js`（引用面串端）
      · ``root_falls_to_b`` —— 根级深层路径被 `/b/` 的 fallback 吃掉（路由面串端）
    """

    def __init__(self, root: Path, built: bytes, mode: str = "ok"):
        self.root = root
        self.built = built
        self.mode = mode
        self._server = None
        self._thread = None

    def _read(self, rel: str, default: bytes) -> bytes:
        f = self.root / rel
        return f.read_bytes() if f.is_file() else default

    def _route(self, path: str):
        c_end_built = self.built
        # 「根上是旧产物」= 线上没发布过这次的构建 ⇒ `/` 与 `/index.html` 与根级深层路径
        # 一起落到那份旧产物（三者同源，不能只让 `/` 旧、`/index.html` 新）
        c_end_old = STALE_C_END_PAGE
        w_page = self._read("w/index.html", b"<html>worker</html>")
        b_page = self._read("b/index.html", b"<html>bmini</html>")
        if path.startswith("/w/"):
            if self.mode == "w_overwritten":
                return c_end_built
            return w_page
        if path.startswith("/b/"):
            if self.mode == "b_overwritten":
                return c_end_built
            return b_page
        if self.mode == "stale_root":
            return c_end_old
        if path in ("/", "/index.html"):
            if self.mode == "root_stray_ref":
                # 直接在根页里塞一条指向**别的应用**命名空间的引用
                # （`</head>` 不在 stub 产物的字面里 ⇒ 用 rel 属性形态插入）
                return c_end_built.replace(
                    b'<link href="/css/app.css" rel="stylesheet">',
                    b'<link href="/css/app.css" rel="stylesheet">'
                    b'<script defer src="/b/js/app.js"></script>',
                )
            return c_end_built
        # 根级深层路径 ⇒ `location /` 的 `try_files $uri $uri/ /index.html`
        if self.mode == "root_falls_to_b":
            return b_page
        return c_end_built

    class _Handler(http.server.BaseHTTPRequestHandler):
        server_version = "NginxishTest/1.0"

        def log_message(self, *args):
            return None

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            body = self.server.route(path)  # type: ignore[attr-defined]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def __enter__(self):
        outer = self

        class _Server(http.server.ThreadingHTTPServer):
            def route(self, path):
                return outer._route(path)

        self._server = _Server(("127.0.0.1", 0), self._Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        for _ in range(100):
            with socket.socket() as sock:
                sock.settimeout(0.2)
                if sock.connect_ex(("127.0.0.1", self._server.server_address[1])) == 0:
                    break
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        return False


def _served_root(tmp_path: Path, built: bytes, dist: Path) -> Path:
    """线上根的形态：**已发布**（根 = 本次构建） + 工人端 `w/` + 商家端 `b/`（各自的产物）。"""
    root = tmp_path / "served"
    (root / "w").mkdir(parents=True)
    (root / "b").mkdir(parents=True)
    (root / "index.html").write_bytes(built)
    (root / "js").mkdir()
    (root / "js" / "app.js").write_bytes((dist / "js" / "app.js").read_bytes())
    (root / "w" / "index.html").write_text("<!doctype html><title>工人端</title>", encoding="utf-8")
    (root / "b" / "index.html").write_text("<!doctype html><title>商家端</title>", encoding="utf-8")
    return root


def _run_verify(base_url: str, dist: Path):
    env = dict(os.environ)
    return subprocess.run(
        ["bash", str(VERIFY_SCRIPT), base_url, str(dist)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180, env=env, cwd=str(REPO_ROOT),
    )


def test_verify_served_is_green_on_correct_landing(tmp_path):
    dist = _make_dist(tmp_path)
    built = (dist / "index.html").read_bytes()
    root = _served_root(tmp_path, built, dist)
    with _NginxishServer(root, built, "ok") as base:
        proc = _run_verify(base, dist)
    assert proc.returncode == 0, f"落地面断言在正确落地上竟失败：\n{proc.stdout}\n{proc.stderr}"
    assert "✅ 全部通过" in proc.stdout


@pytest.mark.parametrize(
    "mode, marker",
    [
        ("stale_root", "≠ 本仓库产物"),
        ("w_overwritten", "/w/ 返回的是"),
        ("b_overwritten", "/b/ 返回的是"),
        ("root_stray_ref", "别的应用的命名空间"),
        ("root_falls_to_b", "期望回落到**根 index.html**"),
    ],
)
def test_verify_served_is_red_on_broken_landings(tmp_path, mode, marker):
    """坏形态必须判红（否则上面的绿是空断言），且**指名**是哪条判据。"""
    dist = _make_dist(tmp_path)
    built = (dist / "index.html").read_bytes()
    root = _served_root(tmp_path, built, dist)
    with _NginxishServer(root, built, mode) as base:
        proc = _run_verify(base, dist)
    assert proc.returncode == 1, f"坏形态 {mode} 竟判绿（空断言）：\n{proc.stdout}"
    assert "❌" in proc.stdout
    assert any(marker in line for line in proc.stdout.splitlines()), (
        f"判红信息里找不到 {marker!r}（红得不具体 = 排查时看不出是哪条判据）：\n{proc.stdout}"
    )
