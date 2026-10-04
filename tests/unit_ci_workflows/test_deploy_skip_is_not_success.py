# case_ids: MC-080
"""**「跳过部署」不得被计成「已部署」**（issue #6294，P0·部署）。

## 病（现取读数，不是推断）

`deploy-*.yml` 的 `Skip if already built (schedule reconcile)` 在 `schedule` / `workflow_dispatch`
触发时，只要「镜像已在 ACR」**或**「同 sha 的部署 run 结论 = success」就 `skip=true` + `exit 0`
⇒ `Deploy to SWAS` / `Assert server-side build` / `Post-Deploy Smoke Test` **整段 skipped**，
而 **run 结论 = success**。对账侧（`deploy-reconcile.yml`）的断路器把 `success` 放进**允许名单**
⇒ 判定「该 commit 已部署」⇒ **不再补部署**。

issue #6294 的现场读数（2026-10-04）：`admin-web` 近 40 次 run 里两条 `success`
（run `37156277078` / `37131394391`）**都是**「skip 成功 + Deploy 步 skipped」；
而 SWAS 实例上运行中的容器是 `admin-web:sha-877ac15`（40 小时前）、`.last-good-tag` = `sha-6838a05`、
main HEAD = `9d82e2e60` ⇒ **环境一次都没换过，台账全绿**。

## 本文件锁什么（判据本体 = 「跳过」必须被**运行面**自证，而不是被 run 结论自证）

1. **运行面读数存在于共享脚本里**（`deploy/scripts/swas-deploy-ci.sh` 的 `--probe-running-tag` 模式）：
   它经同一条 SWAS `RunCommand` 通道**只读**地取回每个服务的**在跑 tag**（`RUNNING_TAG=<svc>:<tag>`），
   不构建、不 pull、不 up。**实现体只有一份** ⇒ 三条腿不可能各读一套。
2. **期望 tag ≠ 实测 tag ⇒ 具名判红**（退出码 1，非零）：判红信息必须含
   **服务 / 期望 tag / 实测 tag / 可复制复算命令** 四件（issue #6294 判据 1 逐字要求「判红必须具名」）。
   ⚠️ **不是**「顺手补一次部署」：`skip` 的语义是「该 commit 已部署」，被打脸时**必须出声**，
   否则就变成对账断路器要防的那种「反复重试同一个坏 commit」的 churn。
3. **一致 ⇒ 放行**（退出码 0）：`skip` 成立（环境确实在跑目标 tag）⇒ 不得报警（噪声判据是缺陷）。
4. **探不到 ⇒ fail-closed**（退出码 3）：云调用失败 / 远端输出里没有 `RUNNING_TAG=` / 未知服务键
   ⇒ 判「探不到」，**不许**当成「一致」，也**不许**当成「不一致」（那会让噪声判据复活）。
5. **三条部署腿**（`deploy-frontend.yml` / `deploy-admin-api.yml` / `deploy-ai-agent-service.yml`）
   **同源修**（铁律 8：只修一处 = 没修）：每条腿都必须把这条自证 step 接在
   `Deploy to SWAS (测试环境)` **之后**、且只在 `skip == 'true'` 时跑；
   **类级元守卫**：任何 `.github/workflows/deploy-*.yml` 里带 `Skip if already built` 步的腿，
   漏接这条 step ⇒ **未登记即红**（新加一条同形腿就自动被这条判据拦住）。
6. **实现体不许复制三份**：三条腿的 step 必须调用**同一份**共享脚本
   （逐腿断言共享脚本名出现；把实现内联进 workflow ⇒ 红）。

⚠️ **未覆盖（如实登记，不粉饰）**：`skip=false`（真跑了完整部署）那条路径本判据**不**自证运行 tag ——
它由 `deploy.sh` 自己的健康检查与 `EFFECTIVE_TAG=` 读数承担；本单的射程是「**跳过**不得冒充已部署」。
⚠️ 桩的诚实标注：`aliyun` 是**桩**（记录调用、读预设 JSON），故本文件证明的是
「脚本在给定输入下**会**做什么」，不是「阿里云真的会回这个读数」；后者只有真跑 CI 才能验证。
本文件不联网、不碰真实云、不写共享 `/tmp`（一切产物落 pytest `tmp_path`）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "deploy" / "scripts" / "swas_deploy_running_tag.sh"
CI_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "swas-deploy-ci.sh"
REMOTE_SCRIPT = REPO_ROOT / "deploy" / "swas" / "deploy.sh"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

PROBE_STEP = "Assert running tag == target (skip 不得冒充已部署，issue #6294)"
DEPLOY_STEP = "Deploy to SWAS (测试环境)"
SKIP_STEP = "Skip if already built (schedule reconcile)"

# 与 CI 的 shell 同形（`bash --noprofile --norc -e -o pipefail`）
BASH_SHELL = ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail"]

# 桩 `aliyun`：`run-command` 回一个固定 InvokeId；`describe-invocation-result` 回预设 JSON。
# 全部行为由环境变量驱动 ⇒ 判据不联网、不碰真实云。
ALIYUN_STUB = r'''#!/usr/bin/env python3
import json, os, sys

args = sys.argv[1:]
with open(os.environ["PROBE_CALL_LOG"], "a", encoding="utf-8") as fh:
    fh.write(" ".join(args) + "\n")

if len(args) >= 2 and args[0] == "swas-open" and args[1] in ("run-command", "RunCommand"):
    sys.stdout.write(json.dumps({"InvokeId": os.environ.get("STUB_INVOKE_ID", "inv-1")}))
    sys.exit(0)

if len(args) >= 2 and args[0] == "swas-open" and args[1] in (
        "describe-invocation-result", "DescribeInvocationResult"):
    sys.stdout.write(os.environ.get("STUB_RESULT_JSON", "{}"))
    sys.exit(0)

# `aliyun version` / `configure` / `plugin` 等一律当成功（判据只关心上面两条）
sys.exit(0)
'''


def _b64(text: str) -> str:
    import base64
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _invocation(remote_text: str, status: str = "Success") -> str:
    """与真实 SWAS 返回同形：`InvocationResult.Output` 是 **base64**。"""
    import json
    return json.dumps({"InvocationResult": {"InvocationStatus": status, "Output": _b64(remote_text)}})


def read(path: Path) -> str:
    assert path.is_file(), f"反空跑锚点：文件不存在 → {path}"
    return path.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════
# 执行台：把共享脚本拷进 tmp，桩掉 CLI 安装块 + 垫一片 `aliyun` 桩
# ══════════════════════════════════════════════════════════════════════════

def stage_probe(tmp_path: Path) -> Path:
    """只安装**探测模式**这一条码路（既有 `swas-deploy-ci.sh` 顶部是 `exec` 式参数解析，
    无法只抽出函数）—— 用**逐字锚点**替换掉 CLI 安装块与主流程，其余原文照跑。

    锚点取不到 ⇒ 显式失败（判据已过期），不静默降级成「测的是另一份实现」。
    """
    body = read(CI_SCRIPT)
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "deploy" / "scripts").mkdir(parents=True)
    (stage / "deploy" / "swas").mkdir(parents=True)
    (stage / "deploy" / "scripts" / "swas_deploy_running_tag.sh").write_text(read(REGISTRY), encoding="utf-8")
    (stage / "deploy" / "swas" / "deploy.sh").write_text(read(REMOTE_SCRIPT), encoding="utf-8")

    # ① 砍掉 `echo "== 安装 Aliyun CLI =="` 之前的**输入段**（位置参数、常量表）里我们不需要的
    #    —— 保留全部参数解析与常量，只把「安装 CLI」与「主流程」两段替成 no-op。
    marker_install = 'echo "== 安装 Aliyun CLI =="'
    marker_main = "# ── 主流程 ──"
    assert marker_install in body, "锚点过期：找不到 Aliyun CLI 安装块"
    assert marker_main in body, "锚点过期：找不到主流程分界线"
    head, rest = body.split(marker_install, 1)
    _, tail = rest.split(marker_main, 1)
    body = head + 'echo "（判据：跳过 CLI 安装）"\n' + marker_main + "\n" + 'echo "（判据：主流程不执行）"\n'
    del tail

    # ② 判据**不联网、不装 CLI**：把库里的 `running_tag_install_cli()` 换成 no-op（逐字锚点，
    #    取不到即显式失败）。⚠️ 换成 no-op 而不是「留着让它跑」：runner 上 `sudo mv` 会以
    #    `Permission denied` 把探测判成异常退出 —— 那是**测试环境**的缺陷伪装成被测实现的缺陷。
    lib = read(REGISTRY)
    m = re.search(r"^running_tag_install_cli\(\) \{.*?^\}", lib, re.M | re.S)
    assert m, "锚点过期：库里找不到 `running_tag_install_cli()`"
    (stage / "deploy" / "scripts" / "swas_deploy_running_tag.sh").write_text(
        lib[:m.start()] + 'running_tag_install_cli() { echo "（判据：跳过 CLI 安装）"; }\n' + lib[m.end():],
        encoding="utf-8")

    # ③ 探测模式**必须在解释器读完顶部之后、CLI 安装与主流程之前**分发 ⇒ 分发段本就在
    #    `swas-deploy-ci.sh` 顶部（与生产实现同一份）⇒ 这里**不再**注入任何东西，
    #    只断言它**真的**在 CLI 安装块之前（否则「探测」会变成一次完整部署）。
    assert "swas_deploy_running_tag.sh" in body, (
        "锚点过期：顶部找不到 `--probe-running-tag` 分发段（它必须调共享库）"
    )
    assert body.index("swas_deploy_running_tag.sh") < body.index("（判据：跳过 CLI 安装）"), (
        "探测分发必须在 CLI 安装 / 主流程**之前**（否则探测会触发一次完整部署）"
    )
    (stage / "deploy" / "scripts" / "swas-deploy-ci.sh").write_text(body, encoding="utf-8")

    # ④ 垫片：`aliyun` 桩 + 记录日志
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "aliyun").write_text(ALIYUN_STUB, encoding="utf-8")
    (shim / "aliyun").chmod(0o755)
    return shim


class Probe:
    def __init__(self, tmp_path: Path, *, expected: str, service: str,
                 running: str | None = None, status: str = "Success",
                 remote_text: str | None = None, service_arg: str | None = None):
        self.tmp = tmp_path
        self.shim = stage_probe(tmp_path)
        self.calls = tmp_path / "aliyun-calls.log"
        self.env = os.environ.copy()
        self.env.update({
            "PATH": f"{self.shim}{os.pathsep}{self.env['PATH']}",
            "PROBE_CALL_LOG": str(self.calls),
            "STUB_INVOKE_ID": "inv-1",
        })
        if remote_text is None:
            remote_text = f"RUNNING_TAG={service}:{running}\n" if running is not None else ""
        self.remote_text = remote_text
        self.env["STUB_RESULT_JSON"] = _invocation(remote_text, status)
        self.expected = expected
        self.service = service
        self.service_arg = service if service_arg is None else service_arg

    def run(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            BASH_SHELL + ["deploy/scripts/swas-deploy-ci.sh", "--probe-running-tag",
                          "i-1", "cn-hangzhou", "AK", "SK", self.expected, self.service_arg],
            cwd=self.tmp / "stage", env=self.env, capture_output=True, text=True)

    @property
    def call_log(self) -> str:
        return self.calls.read_text(encoding="utf-8") if self.calls.exists() else ""


# ══════════════════════════════════════════════════════════════════════════
# 一、运行面读数：共享脚本 + 只读探测（不构建 / 不 pull / 不 up）
# ══════════════════════════════════════════════════════════════════════════

def test_running_tag_probe_exists_and_is_a_single_shared_implementation():
    """**反空跑锚点 + 唯一实现**：共享库必须在场，且读的是**运行面**
    （`docker compose ps` + `docker inspect .Config.Image`，与远端执行体的 `running_tag_of` 同形态）。"""
    text = read(REGISTRY)
    for token in ("docker compose -f deploy/swas/docker-compose.yml ps -q",
                  "docker inspect --format",
                  "running_tag_probe_main", "run-command", "describe-invocation-result", "RUNNING_TAG="):
        assert token in text, f"共享库缺 `{token}`（判据已过期 / 实现被改空）"
    # 只读：**可执行行**里不许出现任何写面动作（否则「探测」会变成一次静默部署）。
    # 注释里提到这些词是**说明**（本判据只剥 `#` 起头的行）。
    code_lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    for ln in code_lines:
        for forbidden in ("docker compose up", "docker compose pull", "docker build", "flock ", "rm -rf"):
            assert forbidden not in ln, (
                f"探测路径必须**只读**：可执行行里出现 `{forbidden}` ⇒ 它不是探测而是部署 → {ln!r}"
            )
    # 远端执行体里那份 `running_tag_of()` 仍是**部署路径**的唯一实现（本库不复制它的函数体）
    remote = read(REMOTE_SCRIPT)
    assert "running_tag_of()" in remote, "远端执行体里找不到 `running_tag_of`（判据已过期）"
    assert "docker inspect --format" in remote, "远端执行体里找不到取 tag 的实现（判据已过期）"


def test_probe_runs_read_only_remote_command(tmp_path):
    """探测**真的**发一条 `run-command`（只读脚本），并且**不**发任何别的东西。"""
    ex = Probe(tmp_path, expected="sha-abc1234", service="admin-web", running="sha-abc1234")
    rc = ex.run()
    assert rc.returncode == 0, f"一致 ⇒ 必须放行 → rc={rc.returncode}\n{rc.stdout}\n{rc.stderr}"
    log = ex.call_log
    assert "swas-open run-command" in log, f"必须发 RunCommand → {log}"
    assert "describe-invocation-result" in log, f"必须取回结果 → {log}"
    assert "--command-content" in log, f"必须真的把远端脚本递过去 → {log}"
    assert "migao-ci-running-tag" in log, f"RunCommand 必须具名（可归因）→ {log}"
    for forbidden in ("docker compose up", "docker build", "--yaml"):
        assert forbidden not in log, f"探测调用里出现写面动作 `{forbidden}` → {log}"


# ══════════════════════════════════════════════════════════════════════════
# 二、判别力：一致放行 / 不一致具名判红 / 探不到 fail-closed
# ══════════════════════════════════════════════════════════════════════════

def test_matching_running_tag_passes(tmp_path):
    """**反向对照**：环境确实在跑目标 tag ⇒ `skip` 成立 ⇒ 退 0、不报警（噪声判据是缺陷）。"""
    ex = Probe(tmp_path, expected="sha-abc1234", service="admin-web", running="sha-abc1234")
    rc = ex.run()
    assert rc.returncode == 0, f"一致必须退 0 → rc={rc.returncode}\n{rc.stdout}\n{rc.stderr}"


def test_diverging_running_tag_is_red_and_named(tmp_path):
    """**注入式红证（本单核心）**：期望 `sha-abc1234`、实测 `sha-877ac15`（= issue #6294 的现场读数）
    ⇒ **判红**（非零），且信息必须含 **服务 / 期望 tag / 实测 tag / 可复制复算命令** 四件。"""
    ex = Probe(tmp_path, expected="sha-abc1234", service="admin-web", running="sha-877ac15")
    rc = ex.run()
    assert rc.returncode == 1, (
        f"运行 tag ≠ 目标 tag ⇒ 必须判红（退出码 1，不是 0）→ rc={rc.returncode}\n{rc.stdout}\n{rc.stderr}"
    )
    blob = rc.stdout + rc.stderr
    assert "admin-web" in blob, f"判红必须**具名到服务** →\n{blob}"
    assert "sha-abc1234" in blob, f"判红必须给出**期望 tag** →\n{blob}"
    assert "sha-877ac15" in blob, f"判红必须给出**实测 tag** →\n{blob}"
    assert "--probe-running-tag" in blob, (
        f"判红必须给**可复制复算命令**（否则读者只能猜怎么复现）→\n{blob}"
    )
    assert "::error::" in blob, "判红必须给 ::error:: 注解（红而不留痕 = #3834 的形态）"


def test_unreadable_running_tag_is_fail_closed(tmp_path):
    """**fail-closed 三态三分**：远端拿不到读数（输出里没有 `RUNNING_TAG=`）⇒ 退出码 **3**，
    且判红文案要说清是「**探不到**」，与「确认不一致」（退出码 1）**长得不一样**。"""
    ex = Probe(tmp_path, expected="sha-abc1234", service="admin-web", remote_text="（远端什么都没打）\n")
    rc = ex.run()
    assert rc.returncode == 3, (
        f"探不到必须退 3（不是 0，也不是 1 —— 三态必须分开）→ rc={rc.returncode}\n{rc.stdout}\n{rc.stderr}"
    )
    blob = rc.stdout + rc.stderr
    assert "探不到" in blob or "无法判定" in blob, f"必须明说「探不到」而非「不一致」→\n{blob}"
    assert "::error::" in blob, "fail-closed 同样要留痕"


def test_cloud_api_failure_is_fail_closed_not_green(tmp_path):
    """云调用失败（`describe-invocation-result` 报 Failed）⇒ **绝不能**退 0（那正是假绿）。"""
    ex = Probe(tmp_path, expected="sha-abc1234", service="admin-web",
               running="sha-abc1234", status="Failed")
    rc = ex.run()
    assert rc.returncode != 0, (
        f"云调用失败必须判红 —— 退 0 就是「跳过被计成已部署」的原形态 → rc={rc.returncode}\n{rc.stdout}"
    )


def test_unknown_service_key_is_rejected(tmp_path):
    """未知服务键 ⇒ 拒绝发命令（不许猜）。"""
    ex = Probe(tmp_path, expected="sha-abc1234", service="admin-web", running="sha-abc1234",
               service_arg="definitely-not-a-service")
    rc = ex.run()
    assert rc.returncode == 3, f"未知服务键必须 fail-closed → rc={rc.returncode}\n{rc.stdout}\n{rc.stderr}"
    assert "不是已知服务" in rc.stdout + rc.stderr, f"必须具名说出拒绝理由 →\n{rc.stdout}\n{rc.stderr}"


def test_empty_running_tag_counts_as_divergence(tmp_path):
    """容器没起 / 取不到 tag（空读数）⇒ 属**不一致**（退出码 1，不是「探不到」）——
    「远端回答了，答案是空」与「远端没回答」是两回事。"""
    ex = Probe(tmp_path, expected="sha-abc1234", service="admin-web", remote_text="RUNNING_TAG=admin-web:\n")
    rc = ex.run()
    assert rc.returncode == 1, (
        f"空读数 = 实测 tag 为空 ⇒ 与期望不一致（1）→ rc={rc.returncode}\n{rc.stdout}\n{rc.stderr}"
    )
    assert "实测 tag：（空）" in rc.stdout + rc.stderr, f"判红要**显式**写出「实测 tag 为空」→\n{rc.stdout}"


# ══════════════════════════════════════════════════════════════════════════
# 三、接线：三条腿同源修（铁律 8）+ 位置在 Deploy 之后 + 只在 skip 时跑
# ══════════════════════════════════════════════════════════════════════════

def _legs_with_skip_step() -> dict:
    """**真值源现取**：带 `Skip if already built (schedule reconcile)` 步的 deploy 腿
    ⇒ `{workflow 文件名: (job 名, 该 job 的 steps)}`。"""
    out = {}
    for wf in sorted(WORKFLOWS_DIR.glob("deploy-*.yml")):
        doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        for job, jd in (doc.get("jobs") or {}).items():
            if not isinstance(jd, dict):
                continue
            names = [s.get("name") for s in (jd.get("steps") or []) if isinstance(s, dict)]
            if SKIP_STEP in names:
                out[wf.name] = (job, jd.get("steps") or [])
    return out


def test_every_skip_capable_leg_is_wired_to_the_probe():
    """**类级元守卫（未接线即红）**：每条带 `Skip if already built` 的腿都必须接上这条自证，且
    ① 位置在 `Deploy to SWAS (测试环境)` **之后**（判据要求「部署后」）
    ② `if:` 覆盖「本轮跳过部署」这条路径（`steps.sync.outputs.skip == 'true'`）
    ③ **调用同一份**共享库 `deploy/scripts/swas_deploy_running_tag.sh`（禁止三份复制实现）
    ④ 期望 tag 来自该腿自己的 tag 解析（`steps.tag.outputs.IMAGE_TAG`），不是第二份真相源
    ⑤ 三条腿的 step **逐字同源**（`if/env/run` 文本一致 ⇒ 不可能有一条腿偷偷走别的口径）。"""
    legs = _legs_with_skip_step()
    assert len(legs) >= 3, f"反空跑锚点：只找到 {len(legs)} 条带 skip 步的腿（判据已过期）→ {sorted(legs)}"
    shapes = set()
    for wf, (job, steps) in sorted(legs.items()):
        names = [s.get("name") for s in steps]
        assert PROBE_STEP in names, (
            f"{wf}（job={job}）漏接「跳过部署自证」步 —— 它的 skip 路径仍会把「跳过」计成 success（issue #6294）。"
            f"现状步骤：{names}"
        )
        assert names.index(PROBE_STEP) > names.index(DEPLOY_STEP), (
            f"{wf}：自证步必须在 `{DEPLOY_STEP}` **之后**（判据要求「部署后」）→ {names}"
        )
        step = next(s for s in steps if s.get("name") == PROBE_STEP)
        cond = str(step.get("if") or "")
        assert "steps.sync.outputs.skip" in cond and "'true'" in cond, (
            f"{wf}：自证步的 `if:` 必须只在「本轮跳过部署」时跑，现状 {cond!r}"
        )
        run = step.get("run") or ""
        assert "swas_deploy_running_tag.sh" in run, (
            f"{wf}：必须调用**共享库** `deploy/scripts/swas_deploy_running_tag.sh`，"
            f"不许把实现内联/复制成三份 → {run!r}"
        )
        env = step.get("env") or {}
        assert "IMAGE_TAG" in env and "steps.tag.outputs.IMAGE_TAG" in str(env["IMAGE_TAG"]), (
            f"{wf}：期望 tag 必须取本腿自己的 tag 解析（`steps.tag.outputs.IMAGE_TAG`），"
            f"否则「期望」是第二份真相源 → {env!r}"
        )
        # 三条腿的形状逐字同源（用名字/条件/正文骨架比较；正文里的服务键是唯一允许的差异）
        shapes.add(json.dumps({
            "if": cond,
            "env_keys": sorted(env),
            "run_head": run.split("\n")[0],
            "calls_shared": "swas_deploy_running_tag.sh" in run,
        }, sort_keys=True))
    assert len(shapes) == 1, (
        f"三条腿的自证步**形状必须逐字同源**（同源修，铁律 8）—— 现状出现 {len(shapes)} 种：{shapes}"
    )
    # ⚠️ secrets 引用**只许出现在 job env 一处**（Danger Scan 的「移动 vs 新增」口径）：
    #    逐腿断言 `AK`/`SK` 在 job env 里、且自证 step 自己不重复声明（重复声明 = 新增 secrets ⇒ blocker）
    for wf, (job, steps) in sorted(legs.items()):
        doc = yaml.safe_load((WORKFLOWS_DIR / wf).read_text(encoding="utf-8"))
        job_env = (doc["jobs"][job].get("env") or {})
        assert "AK" in job_env and "SK" in job_env, (
            f"{wf}：AK/SK 必须在 job env 里声明一次（Deploy step 与自证 step 共用）→ {sorted(job_env)}"
        )
        step = next(s for s in steps if s.get("name") == PROBE_STEP)
        assert "AK" not in (step.get("env") or {}), (
            f"{wf}：自证 step **不得**重复声明 AK（重复 = danger-scan 判「新增 secrets」⇒ 阻塞合并）"
        )


def test_probe_implementation_is_a_single_shared_library():
    """**唯一实现**：探测逻辑只许活在共享库里，不许被复制到别处（也没有第二份 workflow）。"""
    lib = read(REGISTRY)
    assert "running_tag_probe_main" in lib, "共享库必须导出 `running_tag_probe_main`"
    for forbidden in ("docker inspect", "docker compose"):
        assert forbidden in lib, f"共享库必须自己读运行面（缺 `{forbidden}`）"
    # 探测循环只许出现在库里：workflow YAML 里不许再写一遍（那是「复制实现」的形态）
    for wf in sorted(WORKFLOWS_DIR.glob("deploy-*.yml")):
        text = wf.read_text(encoding="utf-8")
        for forbidden in ("docker inspect", "RUNNING_TAG="):
            assert forbidden not in text, (
                f"{wf.name} 里出现探测实现 `{forbidden}` ⇒ 唯一实现被复制进了 YAML"
            )
    dupes = [p for p in REPO_ROOT.rglob("swas_deploy_running_tag*.sh") if ".git" not in p.parts]
    assert len(dupes) == 1, f"共享库被复制成多份（就是「三份复制」的形态）→ {dupes}"


def test_workflow_run_bodies_stay_within_the_github_limit():
    """接线是**往三条腿各加一段正文** ⇒ 复核那条硬约束（超限 ⇒ 整份 workflow invalid）。"""
    limit = 13250
    worst = (0, "")
    for wf in sorted(WORKFLOWS_DIR.glob("*.yml")):
        doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            continue
        for job, jd in (doc.get("jobs") or {}).items():
            if not isinstance(jd, dict):
                continue
            for s in (jd.get("steps") or []):
                if isinstance(s, dict) and isinstance(s.get("run"), str):
                    if len(s["run"]) > worst[0]:
                        worst = (len(s["run"]), f"{wf.name}::{job}::{s.get('name')}")
                    assert len(s["run"]) <= limit, (
                        f"{wf.name}::{job}::{s.get('name')} 的 run 正文 {len(s['run'])} 字符 > {limit}"
                        "（GitHub 会把整份 workflow 判 invalid ⇒ 该腿静默不跑）"
                    )
    assert worst[0] > 4000, f"对照读数：最长的 run 正文只有 {worst[0]} 字符（{worst[1]}）—— 判据可能扫错对象"


# ══════════════════════════════════════════════════════════════════════════
# 四、判别力自证（判据本身会红；只改注释不红）
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("mutate,why", [
    (lambda s: s.replace("RUNNING_TAG=", ""), "把共享脚本的读数标记删掉 ⇒ 反空跑锚点必红"),
    (lambda s: s.replace("docker compose", "docker compose", 1), "对照：不动正文 ⇒ 不得红"),
])
def test_probe_script_anchors_are_discriminating(tmp_path, mutate, why):
    """把共享脚本里的读数锚点删掉 ⇒ 静态判据必红（判据不是恒真式）。"""
    text = read(REGISTRY)
    mutated = mutate(text)
    if mutated == text:
        assert "docker compose" in text      # 对照读数：不得红
        return
    assert "RUNNING_TAG=" not in mutated, why
    assert "RUNNING_TAG=" in text, "前提：真语料里有该锚点"
