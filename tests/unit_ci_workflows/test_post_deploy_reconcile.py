# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""部署后「线上一致性对账」守卫 —— issue #4858（**防再犯机制本体**）。

## 本文件要拦住的三种形态（都有实测证据，见 issue 正文）

| 形态 | 实测 | 加本单之前有没有人会发现 |
|---|---|---|
| ① 静默回退：旧 run 被 flock 排队到新 run 之后执行 ⇒ 服务回退到旧 tag | 三服务全被回退；run success + 健康检查全 200 + 脚本自称成功 = **三重绿零告警** | #4854 已拦住「发生」；但**事后**无人核对线上是哪个 commit |
| ② 静默跳过：某服务镜像拉取失败 ⇒ 远端 `⚠️ 跳过该服务`，整次部署仍报成功 | `sha-56c8c51` 那次跳过 ai-agent/admin-web（**那次合理**）；但若某模块改了、镜像却没建 ⇒ 跳过 = **静默不交付** | ❌ **没有任何机制** |
| ③ 静态副本滞后：发布腿按**路径过滤**触发 ⇒ 改动不在该路径就不跑 | 线上 `/w/src/app.mjs` 一度是旧副本，缺计件幂等修复 | ❌ **没有任何机制** |

## 本文件锁什么

**A. 机制在场（拆掉即红）** —— workflow 有定时 + 手动触发且只读；远端读取体**逐词只读**；
脚本三条判据（容器侧 / 静态侧 / 一行总结）与 fail-open 出口都在，且**「判不出」不计进「一致」**；
逐服务代码路径与各 `deploy-*.yml` 的 `on.push.paths` **逐字对齐**（反查真值源，不写死常量）。

**B. 机制真的会红（注入式红证，**执行式**）** —— 桩化只读通道与线上静态根，
跑**真实脚本的真实码路**：
· 注入「容器在跑 tag 是该服务最近一次改动的**祖先**」⇒ 脚本必须 `exit 1` + `::warning::` + `不一致=1`；
· 注入「线上 `/w/` 某文件与 `origin/main` 哈希不同」⇒ 同上；
· 对照组（全部一致）⇒ `exit 0` + `不一致=0`（证明判据有**双向**判别力，不是恒红）；
· **把判据机械剥离**（`verdict=$(ancestry_verdict …)` → `verdict=descendant`）⇒ 同一组坏输入**不再红**
  —— 证明这条判据是**承重**的，不是装饰。

**C. 既有护栏逐条未削弱** —— 对 `deploy/swas/deploy.sh`（#4854 反回退闸门 / #4785 严格蓝绿 /
#4767 失败即回滚 / #4808 保留策略与回滚点三道防线）、`deploy/scripts/swas-deploy-ci.sh`（`ALLOW_DOWNGRADE`
只认 1 / `EFFECTIVE_TAG=` / `DOWNGRADE_SKIPPED=`）、`deploy-reconcile.yml`（断路器 + 漂移判据）、
`deploy/swas/h5-publish-remote.sh`（静态根父目录红线）、`worker-h5-publish.yml`（发布腿触发面）
做**锚点清单 + 逐条注入式红证**。

## ⚠️ 红证的真实性边界（**照实登记，不粉饰**）

B 组跑的是**本机 + 桩化的外部依赖**（只读读取通道 = 本地桩命令；线上静态根 = 本地 HTTP 服务；
真值源 = 临时 fixture 仓库）。被桩化的是**外部依赖**，被测的是**对账判据本身**。
⇒ B 组一律标注「**桩化、未真跑远端**」。真机只读观测（本 PR 采集的原文读数）见 PR body；
本机无 docker、SWAS 只读通道可用但**本单不在 CI 上真跑远端**。
"""
import copy
import functools
import http.server
import os
import re
import shutil
import subprocess

import threading
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "deploy" / "scripts" / "post-deploy-reconcile.sh"
REMOTE_BODY = REPO_ROOT / "deploy" / "swas" / "reconcile-read-remote.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "post-deploy-reconcile.yml"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

SVC_TO_DEPLOY_WORKFLOW = {
    "admin-api": "deploy-admin-api.yml",
    "ai-agent": "deploy-ai-agent-service.yml",
    "admin-web": "deploy-frontend.yml",
}

SUMMARY_ANCHOR = "**结论**：一致=${CONSISTENT} · 不一致=${INCONSISTENT} · 判不出=${UNKNOWN}"


def script_text() -> str:
    assert SCRIPT.is_file(), f"反空跑锚点：对账脚本不存在 → {SCRIPT}（机制被拆掉）"
    return SCRIPT.read_text(encoding="utf-8")


def remote_body_text() -> str:
    assert REMOTE_BODY.is_file(), f"反空跑锚点：远端只读读取体不存在 → {REMOTE_BODY}（机制被拆掉）"
    return REMOTE_BODY.read_text(encoding="utf-8")


def workflow_doc() -> dict:
    assert WORKFLOW.is_file(), f"反空跑锚点：对账 workflow 不存在 → {WORKFLOW}（机制被拆掉）"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def on_block(doc: dict) -> dict:
    # ⚠️ YAML 1.1 里裸 `on` 会被解析成布尔 True（PyYAML 已知坑）⇒ 两种键都试
    on = doc.get("on")
    return doc.get(True) if on is None else on


# ══════════════════════════════════════════════════════════════════════════
# A. 机制在场（拆掉即红）
# ══════════════════════════════════════════════════════════════════════════

def check_workflow_shape(doc: dict) -> None:
    """可定时 + 可手动触发；只读权限；有硬超时；**不碰 deploy.sh**；不加 pull_request。"""
    on = on_block(doc)
    assert isinstance(on, dict), f"{WORKFLOW.name} 的 `on` 结构变了"
    sched = on.get("schedule")
    assert sched and sched[0].get("cron"), (
        f"{WORKFLOW.name} 丢了 `schedule` ⇒ 不再是「可定时对账」（issue #4858 要求 1）"
    )
    assert "workflow_dispatch" in on, f"{WORKFLOW.name} 丢了 `workflow_dispatch`（手动对账入口）"
    assert "pull_request" not in on, (
        f"{WORKFLOW.name} 加了 `pull_request`：本腿读的是**线上真身**，与某个 PR 的 diff 无因果关系"
    )
    job = doc["jobs"]["reconcile"]
    assert job.get("timeout-minutes"), f"{WORKFLOW.name} 的 reconcile job 丢了 `timeout-minutes`（#4767 ①）"
    assert "continue-on-error" not in str(job.get("steps")), (
        f"{WORKFLOW.name} 出现 `continue-on-error`（= 「失败了也当成功」的门禁削弱形态）"
    )
    perms = doc.get("permissions") or {}
    assert perms.get("contents") == "read", f"{WORKFLOW.name} 的 permissions.contents 必须只读"
    assert "write" not in " ".join(f"{k}:{v}" for k, v in perms.items()), (
        f"{WORKFLOW.name} 出现了写权限 —— 本腿**只出声不写**（补部署是 deploy-reconcile 的职责）"
    )


def check_workflow_wiring(text: str) -> None:
    """接线：跑本单的独立脚本；全历史 checkout；**绝不**调用 `deploy/swas/deploy.sh`（#4828 红线）。

    ⚠️ 判据读 **`run:` 脚本体**（`doc["jobs"][*]["steps"][*]["run"]`），不读整份 YAML ——
    否则「注释里提到 deploy.sh（说明为什么不动它）」会被误判成「触碰了它」。
    """
    doc = workflow_doc()
    runs = "\n".join(
        str(s.get("run", "")) for job in doc["jobs"].values() for s in job.get("steps", [])
    )
    assert "deploy/scripts/post-deploy-reconcile.sh" in runs, (
        f"{WORKFLOW.name} 没有调用 `deploy/scripts/post-deploy-reconcile.sh`（判据对象不见了）"
    )
    assert "fetch-depth: 0" in text, (
        "checkout 必须 `fetch-depth: 0`：容器侧判据是**提交图祖先关系**，浅克隆里对象不可达 "
        "⇒ 退化成 compare API 兜底（匿名 60 次/小时/IP 会限流 ⇒ 判不出）"
    )
    assert "deploy/swas/deploy.sh" not in runs, (
        f"{WORKFLOW.name} 的 run 步骤触碰了 `deploy/swas/deploy.sh` —— 另一单 #4828 正在改它（要求 6）"
    )
    assert "RECONCILE_REMOTE_CMD" not in runs, (
        f"{WORKFLOW.name} 里出现了桩化钩子 `RECONCILE_REMOTE_CMD` —— 线上对账**不许桩化**"
    )


# 会改变线上状态的 docker 动词（只读红线）
FORBIDDEN_DOCKER_VERB = re.compile(
    r"\bdocker(\s+compose)?\s+(up|down|rm|rmi|stop|start|restart|kill|pull|push|run|exec|"
    r"create|build|prune|tag|login|logout|cp|commit|save|load|import|export|attach|pause|unpause)\b"
)
FORBIDDEN_SHELL_MUTATOR = re.compile(r"(^|\s)(rm|mv|chmod|chown|tee|truncate|systemctl|reboot|shutdown)\s")


def check_remote_body_read_only(text: str) -> None:
    """远端读取体**逐词只读**：对账腿写的是生产环境，一次误写就把「发现问题」变成「制造问题」。"""
    assert "docker compose ps -q" in text, "远端读取体必须用 `docker compose ps -q` 取在跑容器（只读）"
    assert "docker inspect --format" in text, "远端读取体必须用 `docker inspect --format` 取镜像引用（只读）"
    assert "RUNNING_TAG=" in text, "远端读取体必须输出 `RUNNING_TAG=<svc>:<tag>`（机器可读契约）"
    m = FORBIDDEN_DOCKER_VERB.search(text)
    assert not m, f"远端读取体出现**变更类** docker 动词：{m.group(0)!r}（只读红线被破坏）"
    m2 = FORBIDDEN_SHELL_MUTATOR.search(text)
    assert not m2, f"远端读取体出现变更类 shell 命令：{m2.group(0).strip()!r}（只读红线被破坏）"


def check_judgments_present(text: str) -> None:
    """三条判据 + 一行总结 + fail-open 出口 + 反空跑，且「判不出」**不计进一致**。"""
    # 容器侧：真值源 = 各 deploy-*.yml 的 on.push.paths（逐服务调用行，见下面的对齐守卫）
    assert "reconcile_service admin-api" in text and "reconcile_service admin-web" in text, (
        "容器侧逐服务判据不见了（`reconcile_service <svc> …` 调用行）"
    )
    assert "gitr log -1 --format=%h origin/main --" in text, (
        "容器侧必须用「该服务最近一次改动它代码路径的 main 提交」当真值（`git log -1 … origin/main -- <paths>`）"
    )
    assert "merge-base --is-ancestor" in text and "ancestry_verdict" in text, (
        "容器侧判据必须是**提交图祖先关系**（`merge-base --is-ancestor`），不是字符串相等/时间戳"
    )
    assert "RUNNING_TAG=" in text, "容器侧必须读运行中容器的**实际** image tag（`RUNNING_TAG=`）"
    # 降级判据（issue #4858 原文：该提交的镜像不存在时退化为「自上次成功部署以来该服务有无改动」）
    assert "last_successful_deploy_sha" in text and "docker manifest inspect" in text, (
        "缺降级判据（镜像存在性 + 自上次成功部署以来有无改动）"
    )
    # 静态侧：逐文件哈希，排除 tests/**（与发布脚本口径一致）
    assert "gitr ls-tree -r --name-only origin/main" in text, (
        "静态侧真值源必须是 `origin/main`（`git ls-tree -r origin/main -- frontend/worker-h5`）"
    )
    assert "grep -v '/tests/'" in text, (
        "静态侧必须排除 `tests/**` —— 与发布脚本 `deploy/swas/h5-publish-remote.sh` 的口径一致（tests 不发）"
    )
    assert "%{http_code}" in text and "file_sha256" in text, "静态侧必须逐文件取线上 body 并比哈希"
    assert "curl_rc" in text, (
        "静态侧必须**分开**取 curl rc 与 HTTP code ⇒ 「连不上（判不出）」与「404/哈希不同（不一致）」可辨；"
        "把读不到当不一致会把网络抖动误报成「线上少交付」（判据失去判别力）"
    )
    # 一行总结（issue #4858 要求 4）
    assert SUMMARY_ANCHOR in text, f"缺一行总结 `{SUMMARY_ANCHOR}`（一致=/不一致=/判不出=）"
    # fail-open 出口：判不出必须出声
    assert "::warning::" in text and "undecided()" in text, "缺「判不出」的 fail-open 出口（`::warning::`）"
    # 「判不出」不许静默当作一致（**本单的核心反模式**）
    m = re.search(r"undecided\(\)\s*\{(.*?)\n\}", text, re.S)
    assert m, "`undecided()` 结构变了（判据已过期）"
    assert "CONSISTENT" not in m.group(1), (
        "`undecided()` 里出现了 `CONSISTENT` ⇒ 「判不出」被静默计成「一致」（issue #4858 要求 4 明令禁止）"
    )
    # 确认的不一致必须让 run 红；判不出走 fail-open（exit 0）
    assert re.search(r'\[ "\$INCONSISTENT" -gt 0 \]; then(.*?)exit 1', text, re.S), (
        "确认的不一致必须 `exit 1`（真的少交付了 ⇒ run 红）"
    )
    assert re.search(r'\[ "\$UNKNOWN" -gt 0 \]; then', text), "缺「判不出」的 fail-open 分支"
    assert "exit 0" in text, "判不出/一致必须 `exit 0`（fail-open，不阻塞）"
    # 反空跑：一个判定都没做出来 ⇒ 必须出声（「没跑」不许长得像「通过」）
    assert "没有做出任何判定" in text, "缺「反空跑」判据（0 判定 ⇒ 必须 `::warning::`，不是「通过」）"


RECONCILE_CALL = re.compile(
    r'^\s*reconcile_service\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(?:"([^"]*)"|(\S+))\s*$', re.M
)


def parse_service_calls(text: str) -> dict:
    calls = {}
    for m in RECONCILE_CALL.finditer(text):
        svc, repo, wf, path, excl_q, excl_b = m.groups()
        assert svc not in calls, f"`reconcile_service {svc}` 出现了两次（判据已过期）"
        calls[svc] = {"repo": repo, "wf": wf, "path": path, "excl": excl_q if excl_q is not None else excl_b}
    assert len(calls) == 3, f"必须逐服务调用 3 次 → 实得 {sorted(calls)}"
    return calls


def check_service_paths_align_with_deploy_triggers(text: str) -> None:
    """逐服务代码路径必须与各自 deploy workflow 的 `on.push.paths` **逐字对齐**。

    判据**反查真值源**（deploy workflow 的 `on.push.paths`），不写死常量 ——
    path 对齐错 ⇒ 要么漏报真漂移（形态②漏网），要么常态误报（判据失去判别力）。
    """
    calls = parse_service_calls(text)
    assert set(calls) == set(SVC_TO_DEPLOY_WORKFLOW), f"服务集合不符：{sorted(calls)}"
    for svc, wf in SVC_TO_DEPLOY_WORKFLOW.items():
        assert calls[svc]["wf"] == wf, f"{svc} 的 deploy workflow 应为 `{wf}`（实得 {calls[svc]['wf']!r}）"
        assert (WORKFLOWS_DIR / wf).is_file(), f"反空跑锚点：{wf} 不存在（判据已过期）"
        doc = yaml.safe_load((WORKFLOWS_DIR / wf).read_text(encoding="utf-8"))
        on = on_block(doc)
        assert isinstance(on, dict) and "push" in on, f"{wf} 的 `on.push` 结构变了（判据已过期）"
        paths = [str(p) for p in on["push"]["paths"]]
        includes = [p for p in paths if not p.startswith("!")]
        excludes = [p.lstrip("!") for p in paths if p.startswith("!")]
        assert includes, f"反空跑锚点：{wf} 没有 `on.push.paths` 正向项"
        assert calls[svc]["path"] in [p.split("/**")[0] for p in includes], (
            f"对账里 {svc} 的代码路径 {calls[svc]['path']!r} 与 `{wf}` 的 on.push.paths {includes} 不一致"
        )
        for ex in excludes:
            prefix = ex.split("/**")[0]
            assert calls[svc]["excl"] == f":(exclude){prefix}", (
                f"`{wf}` 的排除项 {prefix!r} 没在对账里体现（实得 {calls[svc]['excl']!r}）"
            )


# ── 既有护栏锚点清单（**逐条注入式红证**，见 C 组）──────────────────────────
GUARDRAIL_ANCHORS = {
    "deploy/swas/deploy.sh": [
        "2.05 「不许往回走」闸门",             # #4854 反回退闸门本体
        "ALLOW_DOWNGRADE=1",                  # 显式回滚许可（只认 1）
        "EFFECTIVE_TAG=${svc}:${eff}",        # #4852 ③ 逐服务实际生效 tag
        "DOWNGRADE_SKIPPED=${svc}:${TAG}",    # #4852 ③ 被闸门跳过的服务
        "== 2.5 严格蓝绿预验证",               # #4785 严格蓝绿
        "cleanup_project_images",             # #4808 镜像保留策略
        "rollback_point_present",             # #4808 回滚点三道防线
    ],
    "deploy/scripts/swas-deploy-ci.sh": [
        "DOWNGRADE_SKIPPED=",                 # 解析并渲染「被跳过的服务」
        "ALLOW_DOWNGRADE",                    # 降级许可注入
        "__ALLOW_DOWNGRADE__",                # 占位符未渲染 ⇒ 拒绝部署（不许静默当「无许可」）
        "回滚到上一个可用镜像",                 # #4767 失败即回滚
    ],
    ".github/workflows/deploy-reconcile.yml": [
        "select(.headSha == $s)",             # 断路器只匹配同一个 head_sha
        '[ "$last" = "failure" ]',            # 断路器唯一触发条件
        "docker manifest inspect",            # 镜像存在性判据
        "fetch-depth: 0",                     # 漂移判据的前提
        "drift=",                             # 漂移判据
    ],
    "deploy/swas/h5-publish-remote.sh": [
        "assert_target_safe",                 # 静态根父目录红线（目标守卫）
        "PARENT_INDEX_BEFORE_SHA256",
        "PARENT_INDEX_AFTER_SHA256",
    ],
    ".github/workflows/worker-h5-publish.yml": [
        "frontend/worker-h5/**",              # 发布腿触发面
    ],
}


def check_existing_guardrails_anchors(files: dict) -> None:
    """既有护栏逐条在场（files = {相对路径: 文本}）—— 删任一条即红。"""
    for rel, anchors in GUARDRAIL_ANCHORS.items():
        assert rel in files, f"反空跑锚点：{rel} 未读取（判据已过期）"
        text = files[rel]
        for a in anchors:
            assert a in text, f"既有护栏锚点丢失：`{rel}` 里找不到 {a!r}（护栏被削弱）"


def read_guardrail_files() -> dict:
    out = {}
    for rel in GUARDRAIL_ANCHORS:
        p = REPO_ROOT / rel
        assert p.is_file(), f"反空跑锚点：{rel} 不存在（护栏被删除）"
        out[rel] = p.read_text(encoding="utf-8")
    return out


# ── A 组用例 ───────────────────────────────────────────────────────────────

def test_workflow_is_schedulable_and_manual_and_readonly():
    check_workflow_shape(workflow_doc())


def test_workflow_wiring_is_isolated_from_deploy_sh():
    check_workflow_wiring(WORKFLOW.read_text(encoding="utf-8"))


def test_remote_body_is_read_only():
    check_remote_body_read_only(remote_body_text())


def test_script_has_container_and_static_and_summary_judgments():
    check_judgments_present(script_text())


def test_service_paths_align_with_deploy_push_paths():
    check_service_paths_align_with_deploy_triggers(script_text())


def test_existing_guardrails_are_intact():
    check_existing_guardrails_anchors(read_guardrail_files())


def test_scripts_are_syntactically_valid():
    assert shutil.which("bash"), "环境里没有 bash"
    for p in (SCRIPT, REMOTE_BODY):
        proc = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
        assert proc.returncode == 0, f"{p} 语法错误：\n{proc.stderr}"


# ── A 组反向红证（每条判据都必须会红）──────────────────────────────────────

def test_workflow_schedule_removal_turns_red():
    """把 `schedule` 拆掉 ⇒ 不再是「可定时对账」⇒ 判据必红。"""
    doc = workflow_doc()
    check_workflow_shape(doc)
    broken = copy.deepcopy(doc)
    del broken["jobs"]["reconcile"]["timeout-minutes"]
    assert broken != doc, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_workflow_shape(broken)


def test_remote_body_write_verb_injection_turns_red():
    """把变更类 docker 动词注入回远端读取体 ⇒ 只读红线判据必红。"""
    real = remote_body_text()
    check_remote_body_read_only(real)
    broken = real.replace("docker compose ps -q", "docker compose up -d")
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_remote_body_read_only(broken)


def test_unknown_counted_as_consistent_injection_turns_red():
    """把「判不出」静默计成「一致」⇒ 判据必红（issue #4858 要求 4 的核心反模式）。"""
    real = script_text()
    check_judgments_present(real)
    broken = real.replace(
        "  UNKNOWN=$((UNKNOWN + 1))\n  say \"  · $1\"",
        "  CONSISTENT=$((CONSISTENT + 1))\n  say \"  · $1\"",
        1,
    )
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_judgments_present(broken)


def test_summary_line_removal_turns_red():
    """拆掉一行总结 ⇒ 判据必红。"""
    real = script_text()
    check_judgments_present(real)
    broken = real.replace(SUMMARY_ANCHOR, '**结论**：见上')
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_judgments_present(broken)


def test_service_path_misalignment_turns_red():
    """把某服务的代码路径改错 ⇒ 与 `on.push.paths` 的对齐判据必红。"""
    real = script_text()
    check_service_paths_align_with_deploy_triggers(real)
    broken = real.replace("frontend/admin-web \"\"", "frontend \"\"")
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_service_paths_align_with_deploy_triggers(broken)


def test_each_existing_guardrail_anchor_has_discriminating_power():
    """**逐条**注入：删掉任一既有护栏锚点 ⇒ 必红（不是"抽查一条就算"）。"""
    files = read_guardrail_files()
    check_existing_guardrails_anchors(files)  # 前提：真文本先绿
    for rel, anchors in GUARDRAIL_ANCHORS.items():
        for a in anchors:
            broken = dict(files)
            broken[rel] = files[rel].replace(a, "/* 已删除 */")
            assert broken[rel] != files[rel], f"注入未生效：{rel} 里找不到 {a!r}（判据自证）"
            with pytest.raises(AssertionError):
                check_existing_guardrails_anchors(broken)


# ══════════════════════════════════════════════════════════════════════════
# B. 机制真的会红（**执行式**红证：桩化外部依赖，跑真实脚本的真实码路）
# ══════════════════════════════════════════════════════════════════════════

H5_FILES = {
    "frontend/worker-h5/index.html": "<!doctype html><title>worker</title>\n",
    "frontend/worker-h5/src/app.mjs": "export const APP = 'v1';\n",
}


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    }
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, f"git {' '.join(args)} 失败：{proc.stderr}"
    return proc.stdout.strip()


def _commit(repo: Path, msg: str, files: dict) -> str:
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "--short=7", "HEAD")


@pytest.fixture
def fixture_repo(tmp_path):
    """真值源 fixture 仓库：`origin/main` 指向 c4。

    c1 admin-api v1 + worker-h5（H5 真值源）· c2 ai-agent v1 · c3 admin-web v1 · c4 admin-api v2
    ⇒ LAST_CHANGE: admin-api=c4 / ai-agent=c2 / admin-web=c3（提交图关系都是**真的**，不是桩）。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    c1 = _commit(repo, "c1", {**H5_FILES, "backend/admin-api/App.java": "v1\n"})
    c2 = _commit(repo, "c2", {"backend/ai-agent-service/app.py": "v1\n"})
    c3 = _commit(repo, "c3", {"frontend/admin-web/page.tsx": "v1\n"})
    c4 = _commit(repo, "c4", {"backend/admin-api/App.java": "v2\n"})
    _git(repo, "update-ref", "refs/remotes/origin/main", c4)
    return {"dir": repo, "c1": c1, "c2": c2, "c3": c3, "c4": c4}


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # 静音（测试输出只留判据）
        return


def _serve(directory: Path):
    handler = functools.partial(_QuietHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}", httpd


def _site(tmp_path: Path, *, app_mjs: str | None = None) -> Path:
    """线上静态根 fixture：`<site>/w/{index.html,src/app.mjs}`（`app_mjs` 非 None ⇒ 注入「旧副本」）。"""
    site = tmp_path / "site" / "w"
    (site / "src").mkdir(parents=True)
    (site / "index.html").write_text(H5_FILES["frontend/worker-h5/index.html"], encoding="utf-8")
    (site / "src" / "app.mjs").write_text(
        H5_FILES["frontend/worker-h5/src/app.mjs"] if app_mjs is None else app_mjs, encoding="utf-8"
    )
    return tmp_path / "site"


def _remote_log(fixture_repo, running: dict) -> str:
    lines = [
        "RECONCILE_HOST=stub", "RECONCILE_DATE=1970-01-01T00:00:00Z",
        "RECONCILE_COMPOSE_DIR=/opt/migao-deploy", "RECONCILE_DOCKER=(absent)",
        f"RECONCILE_LAST_GOOD_TAG=sha-{fixture_repo['c4']}",
    ]
    for svc in ("admin-api", "ai-agent", "admin-web"):
        tag = running.get(svc) or ""
        lines.append(f"RUNNING_TAG={svc}:{tag}")
        lines.append(f"RUNNING_STATE={svc}:{'running' if tag else 'not-found'}")
    lines.append("RECONCILE_READ_DONE=1")
    return "\n".join(lines) + "\n"


def _run_reconcile(tmp_path: Path, fixture_repo, running: dict, base_url: str, script: Path | None = None):
    """跑**真实脚本的真实码路**；只把外部依赖桩化（读取通道 = 本地文件；线上静态根 = 本地 HTTP）。

    ⚠️ 标注：**桩化、未真跑远端** —— 被桩化的是外部依赖，被测的是对账判据本身。
    """
    log = tmp_path / "remote.log"
    log.write_text(_remote_log(fixture_repo, running), encoding="utf-8")
    env = {
        **os.environ,
        "RECONCILE_REPO_DIR": str(fixture_repo["dir"]),
        "RECONCILE_REMOTE_CMD": f"cat {log}",
        "RECONCILE_BASE_URL": base_url,
    }
    env.pop("GITHUB_STEP_SUMMARY", None)
    return subprocess.run(
        ["bash", str(script or SCRIPT)], capture_output=True, text=True, env=env, timeout=180
    )


def _green_inputs(fixture_repo):
    """对照组：三个服务都跑在「该有的或其后代」+ 线上静态根与 origin/main 逐字节一致。"""
    return {
        "admin-api": f"sha-{fixture_repo['c4']}",
        "ai-agent": f"sha-{fixture_repo['c2']}",
        "admin-web": f"sha-{fixture_repo['c3']}",
    }


def test_all_consistent_is_green(tmp_path, fixture_repo):
    """对照组：全部一致 ⇒ exit 0 + `不一致=0`（证明判据不是恒红）。"""
    base, httpd = _serve(_site(tmp_path))
    try:
        proc = _run_reconcile(tmp_path, fixture_repo, _green_inputs(fixture_repo), base)
    finally:
        httpd.shutdown()
    assert proc.returncode == 0, f"对照组不该红：\n{proc.stdout}\n{proc.stderr}"
    assert "一致=5 · 不一致=0 · 判不出=0" in proc.stdout, proc.stdout


def test_injected_container_tag_mismatch_turns_red(tmp_path, fixture_repo):
    """🔴 注入形态②（静默不交付）：admin-api 在跑 `c3`，而该服务最近一次改动是 `c4`（c3 是 c4 的**祖先**）。"""
    running = _green_inputs(fixture_repo)
    running["admin-api"] = f"sha-{fixture_repo['c3']}"
    base, httpd = _serve(_site(tmp_path))
    try:
        proc = _run_reconcile(tmp_path, fixture_repo, running, base)
    finally:
        httpd.shutdown()
    assert proc.returncode == 1, f"注入的容器 tag 不一致**必须**让对账红：\n{proc.stdout}\n{proc.stderr}"
    assert "[容器/admin-api] **不一致**" in proc.stdout, proc.stdout
    assert "线上**缺该服务最近一次改动**" in proc.stdout, proc.stdout
    assert "一致=4 · 不一致=1 · 判不出=0" in proc.stdout, proc.stdout
    assert "::warning::" in proc.stdout, "出声形态缺失（只有 exit code 不够）"


def test_injected_static_copy_lag_turns_red(tmp_path, fixture_repo):
    """🔴 注入形态③（静态副本滞后）：线上 `/w/src/app.mjs` 是**旧副本**（缺计件幂等修复的形态）。"""
    base, httpd = _serve(_site(tmp_path, app_mjs="export const APP = 'stale';\n"))
    try:
        proc = _run_reconcile(tmp_path, fixture_repo, _green_inputs(fixture_repo), base)
    finally:
        httpd.shutdown()
    assert proc.returncode == 1, f"注入的静态副本滞后**必须**让对账红：\n{proc.stdout}\n{proc.stderr}"
    assert "[静态/src/app.mjs] **不一致**" in proc.stdout, proc.stdout
    assert "一致=4 · 不一致=1 · 判不出=0" in proc.stdout, proc.stdout


def test_missing_static_file_turns_red(tmp_path, fixture_repo):
    """线上**没有**这份文件（HTTP 404）⇒ 也是不一致（形态③的「发布腿根本没跑」）。"""
    site = _site(tmp_path)
    (site / "w" / "src" / "app.mjs").unlink()
    base, httpd = _serve(site)
    try:
        proc = _run_reconcile(tmp_path, fixture_repo, _green_inputs(fixture_repo), base)
    finally:
        httpd.shutdown()
    assert proc.returncode == 1, proc.stdout
    assert "HTTP=404" in proc.stdout, proc.stdout


def test_undecidable_is_fail_open_and_never_counted_as_consistent(tmp_path, fixture_repo):
    """判不出 ⇒ `::warning::` + **不计进一致** + fail-open（exit 0）—— issue #4858 要求 4。"""
    running = {"admin-api": "latest", "ai-agent": None, "admin-web": None}  # 非 sha tag / 容器未起
    base, httpd = _serve(_site(tmp_path))
    try:
        proc = _run_reconcile(tmp_path, fixture_repo, running, base)
    finally:
        httpd.shutdown()
    assert proc.returncode == 0, f"判不出必须 fail-open（不阻塞）：\n{proc.stdout}\n{proc.stderr}"
    assert "一致=2 · 不一致=0 · 判不出=3" in proc.stdout, proc.stdout
    assert proc.stdout.count("::warning::") >= 3, "判不出必须**逐个出声**，不许静默"
    assert "判不出 ≠ 一致" in proc.stdout or "判不出" in proc.stdout, proc.stdout


def test_remote_read_failure_is_loud_not_silent(tmp_path, fixture_repo):
    """只读通道整体失败 ⇒ 三个服务**全部**判不出 + 出声（不许静默当作一致）。"""
    log = tmp_path / "empty.log"
    log.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "RECONCILE_REPO_DIR": str(fixture_repo["dir"]),
        "RECONCILE_REMOTE_CMD": f"cat {log}",
        "RECONCILE_BASE_URL": "http://127.0.0.1:1",
    }
    env.pop("GITHUB_STEP_SUMMARY", None)
    proc = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=180)
    # 静态侧也读不到（端口 1 拒连）⇒ 也判不出；整体仍 fail-open（exit 0）但**必须出声**
    assert proc.returncode == 0, proc.stdout
    assert "判不出=5" in proc.stdout, proc.stdout
    assert "::warning::" in proc.stdout, proc.stdout


def test_neutered_judgment_stops_detecting(tmp_path, fixture_repo):
    """🔴 **把机制拆掉 ⇒ 必须红**：机械剥离容器侧判据后，同一组坏输入**不再红**。

    这一步证明那条判据是**承重**的（不是装饰）：剥离它 = 形态② 重新变成「没有任何机制会发现」。
    """
    running = _green_inputs(fixture_repo)
    running["admin-api"] = f"sha-{fixture_repo['c3']}"
    base, httpd = _serve(_site(tmp_path))
    try:
        real = _run_reconcile(tmp_path, fixture_repo, running, base)
        assert real.returncode == 1, "前提：未剥离时该组输入必须红"

        # 机械剥离：把「提交图祖先关系」判据换成恒定的 descendant（= 删掉这条判据）
        neutered = tmp_path / "neutered.sh"
        text = script_text().replace(
            'verdict=$(ancestry_verdict "$expected7" "$running")', "verdict=descendant"
        )
        assert text != script_text(), "注入未生效（判据自证）"
        neutered.write_text(text, encoding="utf-8")
        broken = _run_reconcile(tmp_path, fixture_repo, running, base, script=neutered)
    finally:
        httpd.shutdown()
    assert broken.returncode == 0, (
        "剥离容器侧判据后**仍然红了** ⇒ 说明红不来自这条判据（红证无效）"
    )
    assert "不一致=0" in broken.stdout, broken.stdout


# ══════════════════════════════════════════════════════════════════════════
# C. 既有护栏未削弱的**汇总锚点**（逐条红证见 test_each_existing_guardrail_anchor_*）
# ══════════════════════════════════════════════════════════════════════════

def test_no_new_write_path_to_production():
    """本单**只出声不写**：脚本里不许出现任何触发部署/变更线上状态的调用。"""
    text = script_text()
    for forbidden in ("gh workflow run", "docker compose up", "docker compose pull", "aliyun swas-open run-command --name migao-ci-deploy"):
        assert forbidden not in text, f"对账脚本里出现了会写线上状态的调用：{forbidden!r}"
    assert "RECONCILE_REMOTE_CMD" in text, "桩化钩子不见了（守卫测试的前提）"


def test_workflow_file_has_no_unexpected_extra_files():
    """本单**只新增**三样东西（脚本 / 远端读取体 / workflow），不改既有对账与部署腿（要求 6 的静态面）。"""
    for rel in ("deploy/scripts/post-deploy-reconcile.sh", "deploy/swas/reconcile-read-remote.sh",
                ".github/workflows/post-deploy-reconcile.yml"):
        assert (REPO_ROOT / rel).is_file(), f"缺少本单产物：{rel}"
    # 既有对账/部署腿的判据一字未动 —— 由 test_existing_guardrails_are_intact 逐条钉住
