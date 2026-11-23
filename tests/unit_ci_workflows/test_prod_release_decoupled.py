# case_ids: MC-350
r"""生产发布与 GitHub 解耦：`prod-inspect.sh` / `prod-release.sh` 的判据（issue #9119）。

## 病（2026-11-23 用户裁定逐字）

> 「为什么部署生产环境还要依赖 github 的 ci？不可以直接走部署机吗？**生产环境需要和 github 的能力解耦**」

现场证据（同一天实测）：2026-11-23 11:32–11:39 有一次**只更新 admin-api 的手工发布** ——
`admin-api=sha-26ff9f7`（11-23 11:39）、`admin-web=sha-caf01e4`（11-21 22:52）、`ai-agent=sha-0dced39`（11-22 18:25）
⇒ **三服务身份不自洽**（「发成半截」），而当时**没有任何东西会报**。
根因不是「CI 慢」，是**通道错**：生产 22 端口只对办公出口开放、GitHub runner 不在那个出口；
部署机到生产 22 不通、443 通；凭证只在部署机 `~/.aliyun/config.json` 的 `prod` profile。

## 本文件锁什么（判据本体 = 两个脚本 + 一份文档；每条都能单独变红）

| # | 判据 | 执行点 |
|---|---|---|
| ① | **只读白名单**：`prod-inspect.sh` 的远端载荷逐条拆开，**首词必须**在只读白名单内（`hostname/date/uptime/df/free/docker/cat/ls/du/nginx/crontab/systemctl` + 只读过滤器），`docker` 子命令只许 `ps` / `system`，且**不许**出现写动词 | `::test_inspect_payload_is_readonly_whitelisted` |
| ② | **发布脚本不得自带写面**：`prod-release.sh` 里不许出现 `docker restart/rm/stop/kill/prune`、`systemctl restart/stop/start`、`rm -rf`、`nginx -s reload`、`docker compose up/down`、`docker build` —— 发布只能通过盘上 `deploy.sh`；出现 ⇒ 判红并**点名行号** | `::test_release_script_has_no_write_verbs` |
| ③ | **`--apply` 闸门（静态）**：dry-run 分支必须**在**任何 `run-command` 之前 `exit 0`（照代码行号判），且脚本里出现 `[ "$APPLY" -ne 1 ]` 守卫 | `::test_apply_gate_is_static` |
| ④ | **`--apply` 闸门（行为）**：把 `aliyun` 换成**打日志的桩**，实跑 `--dry-run` ⇒ 桩 **0 次调用**（一次 `run-command` 都没发），且打印 `DRY-RUN=OK`；`--dry-run` 也不许出现 `SWITCH-BLINDSPOT`（探针只在 `--apply` 启用） | `::test_dry_run_never_calls_run_command` / `::test_dry_run_does_not_start_the_blindspot_probe` |
| ⑤ | **机器闸门**：非部署机 ⇒ 退 **1**、具名（本机读数 + 部署机 HostName + 三个出口）、且**一次 run-command 都没发**；读数拿不到 ⇒ 退 **3**；身份相等 ⇒ `--host-assert` 退 0 且零副作用 | `::test_machine_gate_refuses_off_the_deploy_box` / `::test_machine_gate_is_undecidable_when_the_reading_is_unavailable` / `::test_host_assert_passes_on_the_deploy_box` |
| ⑥ | **版本闸门**：目标版本**不是** `origin/release` 的祖先（侧分支上的提交，经本地 bare 仓推送 —— 不真连网）⇒ 退 **1**、具名、并打印 `release..target` 的提交；`origin/release` 上的提交 ⇒ 通过；取不到远端 ⇒ 退 **3** | `::test_version_gate_refuses_a_sha_not_on_the_release_line` / `::test_version_gate_accepts_a_commit_on_the_release_line` / `::test_version_gate_is_undecidable_when_origin_is_unreachable` |
| ⑦ | **真发 + 发后同源自检 + 台账**：全桩 happy path ⇒ 退 0、三服务同源、打印 `SWITCH-BLINDSPOT failures=0 max_gap_ms=…`、打印可粘贴行 `PROD-RELEASE rc=0 version=… api=… web=… ai=… at=… operator=…`、台账**恰好追加 1 次** | `::test_apply_happy_path_reports_blindspot_and_appends_the_ledger_once` |
| ⑧ | **自检不同源 ⇒ 点名**：`admin-web` 的镜像 tag / 应用层 sha 停在旧版本 ⇒ 退 **1**，输出**点名 web** 且写出「≠ 目标」；**台账一次都不追加** | `::test_self_check_names_the_mismatched_service_and_skips_the_ledger` |
| ⑨ | **切换盲区会报**：探针在切换窗口里失败过（curl 桩每 3 次给一次 000）⇒ 打印 `failures>0` + `::warning::`，**但**发布整体仍退 0（改造 `deploy.sh` 不在本包范围） | `::test_blindspot_reports_failures_without_failing_the_release` |
| ⑩ | **`deploy.sh --help` 读不到 ⇒ 退 3**（不猜版本参数），并打印 `--help` 原文片段；把 `--help` 的版本参数换个名字（`--ref`）⇒ 脚本跟随（证明是**现读**，不是写死一个参数名） | `::test_missing_help_is_undecidable` / `::test_version_flag_is_read_from_help_not_hardcoded` |
| ⑪ | **盘点三态**：全部段 `rc=0` ⇒ `READONLY-INSPECT=OK` 且退 0；某段失败 ⇒ `INCOMPLETE failed=[…]` 且退 1；某段**缺失**（回读被截断）⇒ `INCOMPLETE missing=[…]` 且退 1；CLI 缺 ⇒ 退 **3** | `::test_inspect_reports_ok` / `::test_inspect_reports_a_failed_section` / `::test_inspect_reports_a_missing_section` / `::test_inspect_is_undecidable_without_the_cli` |
| ⑫ | **文档接线**：`docs/deployment/production-release.md` 必须写清「为什么与 GitHub 解耦」「inspect / dry-run / apply 怎么跑」「闸门与自检含义」「失败怎么读」「无感发布的现状与缺口（四条）」「资源告警走阿里云云监控」 | `::test_docs_cover_decoupling_gates_and_the_seamless_boundary` |
| ⑬ | 两个脚本都必须 `100755` 且 `bash -n` 通过（语法坏了的闸门等于没有闸门） | `::test_scripts_are_executable_and_parse` |

## 沙箱怎么造（零网络 / 零真发布 / 零云调用 / 零 LLM）

* **git 侧是真的**：沙箱里一个 `origin.git`（本地 bare）+ 一个检出；`release` 与 `main` 的相对关系按用例摆位，
  `hotfix` 侧分支提供一个**不是** `release` 祖先的 sha ⇒ 版本闸门的三态由**真脚本**给出（`origin` 是本地路径，不连网）；
* **云助手通道是桩**：`aliyun` 桩（python）记录**每次 argv**，
  `run-command` 给 `InvokeId`、`describe-invocation-result` 按**命令内容**回放预置输出（`--help` / `deploy.sh` /
  `docker ps` 自检 / `STREAMS=` drain / 台账追加 / 盘点载荷各有各的形态）—— 三种返回结构形态里本文件覆盖
  `InvocationResult`（另一种 `InvocationResults.InvocationResult` 由库的解析分支承担，见「边界」）；
* **443 应用层是桩**：`curl` 桩按模式给 `{"app","sha","tag"}` 或 `http_code`，`flaky` 模式每 3 次给一次 `000`
  ⇒ 盲区探针的失败读数可复算；
* **机器闸门读数可注入**：`MIGAO_PROD_HOST_ID`（本机身份）+ `MIGAO_PROD_SSH_CONFIG`（ssh 配置）是**读数**的口子，
  不是「跳过闸门」的开关。

## 边界（照实登记，别读成「已经发过一次生产」）

- **没有执行任何真实发布**：`--apply` 在本文件里全部打在桩上；真发必须在部署机上由人跑一次（PR body 的「未固化缺口」）。
- 判不了 `deploy.sh` 的真实参数面（盘上那份 `--help` 的真实输出不在研发机上）：脚本**现读** `--help`，
  读不到就退 **3**；本文件用两种 `--help` 形态证明「跟随而不是写死」。
- 判不了真实切换窗口的失败数（要看真发布）：`SWITCH-BLINDSPOT` 是**度量**，不是承诺；
  改造 `deploy.sh` / nginx 使窗口归零不在本包范围。
- 没有在 CI 侧加任何 workflow（本包**不改** `.github/workflows/**`）。
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSPECT = REPO_ROOT / "scripts" / "prod-inspect.sh"
RELEASE = REPO_ROOT / "scripts" / "prod-release.sh"
LIB = REPO_ROOT / "scripts" / "lib" / "prod-swas-run.sh"
DOCS = REPO_ROOT / "docs" / "deployment" / "production-release.md"

DEPLOY_HOST = "migao-prod-deploy"       # 部署机的 HostName（测试用；真机上由 ssh -G 现取，**不写死 IP**）
OTHER_HOST = "some-dev-laptop"          # 一台普通开发机
DEPLOY_ALIAS = "migao-deploy"           # 人与脚本共用的 SSH 别名
BASE_DOMAIN = "cytda.com"

#: 只读白名单：`prod-inspect.sh` 载荷里每个管道段的首词只许是这些
READONLY_WHITELIST = {
    "hostname", "date", "uptime", "df", "free", "docker", "cat", "ls", "du",
    "nginx", "crontab", "systemctl",
    # 只读过滤器（管道下游）
    "grep", "sort", "tail", "head", "awk", "sed", "cut", "wc", "egrep", "tr", "xargs",
}
#: `docker` 只许这两个子命令（`ps` / `system df`），其余一律判红
ALLOWED_DOCKER_SUBCOMMANDS = {"ps", "system"}

#: `prod-release.sh` 的类级写面禁令（发布只能通过盘上 `deploy.sh`）
FORBIDDEN_IN_RELEASE = (
    "docker restart", "docker rm", "docker stop", "docker kill", "docker prune",
    "docker system prune", "docker compose up", "docker compose down", "docker build",
    "systemctl restart", "systemctl stop", "systemctl start", "systemctl reload",
    "rm -rf", "rm -f", "nginx -s reload", "nginx -s stop",
)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "ci", "GIT_AUTHOR_EMAIL": "ci@example.com",
    "GIT_COMMITTER_NAME": "ci", "GIT_COMMITTER_EMAIL": "ci@example.com",
}


# ══════════════════════════════════════════════════════════════════════════════
# 桩：云助手 `aliyun`（python）/ 443 `curl`（bash）
# ══════════════════════════════════════════════════════════════════════════════

ALIYUN_STUB = r'''#!/usr/bin/env python3
"""云助手通道的桩：记录每次 argv，按**命令内容**回放预置输出（零网络）。"""
import base64
import json
import os
import sys

argv = sys.argv[1:]
LOG = os.environ["STUB_ALIYUN_LOG"]
STATE = os.environ["STUB_ALIYUN_STATE"]


os.makedirs(STATE, exist_ok=True)


def arg(name, default=""):
    if name in argv and argv.index(name) + 1 < len(argv):
        return argv[argv.index(name) + 1]
    return default


def counter(name):
    path = os.path.join(STATE, name)
    n = 0
    if os.path.exists(path):
        try:
            n = int(open(path, encoding="utf-8").read() or 0)
        except ValueError:
            n = 0
    n += 1
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(n))
    return n


def inspect_fixture(mode):
    sections = ["host", "disk_root", "disk_opt", "memory", "containers", "docker_df",
                "env_site", "deploy_dir", "deploy_usage", "nginx", "cron", "timers"]
    lines = []
    for name in sections:
        rc = 1 if (mode == "failed" and name == "nginx") else 0
        lines.append("@@SEC:%s@@" % name)
        lines.append("  读数 ...")
        if mode == "missing" and name == "timers":
            continue                      # 缺 END 标记 ⇒ 那一段判「没看到」
        lines.append("@@END:%s@@ rc=%d" % (name, rc))
    return "\n".join(lines) + "\n"


def postcheck_fixture(mode, target7):
    api, web, ai = target7, target7, target7
    if mode == "stale-web":
        web = "caf01e4"
    docker_lines = [
        "migao-admin-api|registry/admin-api:sha-%s" % api,
        "migao-ai-agent|registry/ai-agent-service:sha-%s" % ai,
    ]
    app_lines = ['{"app":"admin-api","sha":"%s0"}' % api, '{"app":"ai-agent","sha":"%s0"}' % ai]
    if mode != "missing-web":
        docker_lines.append("migao-admin-web|registry/admin-web:sha-%s" % web)
        app_lines.append('{"app":"admin-web","sha":"%s0"}' % web)
    return "\n".join(["--- docker ---"] + docker_lines + ["--- app-layer ---"] + app_lines) + "\n"


def render(content):
    target7 = os.environ.get("STUB_TARGET7", "0000000")
    if "swas-open" in content:
        return "", 0
    if "# READONLY-PAYLOAD-BEGIN" in content:                     # 只读盘点载荷
        return inspect_fixture(os.environ.get("STUB_INSPECT", "ok")), 0
    if "--help" in content:                                        # deploy.sh --help
        return os.environ.get("STUB_HELP", "--version <sha>  要发布的版本\n"), 0
    if "STREAMS=" in content:                                      # drain 读数
        return "STREAMS=%s container=migao-ai-agent\n" % os.environ.get("STUB_STREAMS", "0"), 0
    if "release-ledger.jsonl" in content:                           # 台账追加
        with open(os.path.join(STATE, "ledger-appended"), "w", encoding="utf-8") as fh:
            fh.write(content)
        return "", 0
    if "/opt/migao-deploy/deploy.sh" in content:                   # 真发
        import time
        with open(os.path.join(STATE, "deploy-ran"), "w", encoding="utf-8") as fh:
            fh.write(content)
        time.sleep(float(os.environ.get("STUB_DEPLOY_SLEEP", "0")))
        return "…蓝绿：green 健康 ⇒ 替换正式容器 ⇒ nginx -s reload…\n", int(os.environ.get("STUB_DEPLOY_RC", "0"))
    if "app-layer" in content:                                     # 发后自检
        return postcheck_fixture(os.environ.get("STUB_POSTCHECK", "match"), target7), 0
    return "", 0


with open(LOG, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": argv}, ensure_ascii=False) + "\n")

service = argv[1] if len(argv) > 1 else ""

if service == "run-command":
    content = arg("--command-content")
    n = counter("invoke")
    with open(os.path.join(STATE, "cmd-%d.txt" % n), "w", encoding="utf-8") as fh:
        fh.write(content)
    if os.environ.get("STUB_RUN_FAIL") == "1":
        sys.stderr.write("ERROR: InvalidAccessKeyId.NotFound\n")
        sys.exit(1)
    print(json.dumps({"InvokeId": "inv-%d" % n, "RequestId": "req-%d" % n}))
    sys.exit(0)

if service == "describe-invocation-result":
    invoke_id = arg("--invoke-id")
    idx = invoke_id.rsplit("-", 1)[-1]
    path = os.path.join(STATE, "cmd-%s.txt" % idx)
    content = ""
    if os.path.exists(path):
        content = open(path, encoding="utf-8").read()
    out, rc = render(content)
    shape = os.environ.get("STUB_DESCRIBE_SHAPE", "singular")
    output_b64 = base64.b64encode(out.encode("utf-8")).decode("ascii")
    # 真机形态（2026-11-23 部署机实测）= 单数 `InvocationResult` dict + 状态键 `InvocationStatus`
    singular = {"InvocationStatus": "Success", "ExitCode": rc, "Output": output_b64}
    if shape == "singular":
        print(json.dumps({"RequestId": "req", "InvocationResult": singular}, ensure_ascii=False))
    elif shape == "plural":                      # 另一种形态：InvocationResults.InvocationResult = [ ... ]
        print(json.dumps({"RequestId": "req", "InvocationResults": {"InvocationResult": [singular]}},
                         ensure_ascii=False))
    elif shape == "inferred":                    # 状态键缺失但有 ExitCode / Output ⇒ 推断「已结束」
        print(json.dumps({"RequestId": "req", "InvocationResult": {"ExitCode": 0, "Output": output_b64}},
                         ensure_ascii=False))
    elif shape == "failed_no_exit":               # 失败但云端没给 ExitCode ⇒ 不许读成 0
        print(json.dumps({"RequestId": "req", "InvocationResult": {
            "InvocationStatus": "Failed", "Output": output_b64}}, ensure_ascii=False))
    elif shape == "running":                      # 永远 Running ⇒ 轮询超时（判不了，且必须说清为什么）
        print(json.dumps({"RequestId": "req", "InvocationResult": {"InvocationStatus": "Running"}},
                         ensure_ascii=False))
    else:                                         # junk：字段全缺
        print(json.dumps({"RequestId": "req", "InvocationResult": {"Foo": "bar"}}, ensure_ascii=False))
    sys.exit(0)

sys.stderr.write("桩不认识这个子命令：%s\n" % " ".join(argv))
sys.exit(2)
'''

CURL_STUB = r'''#!/bin/bash
# 443 应用层 / 探针的桩：记录每次调用，按模式给答案（零网络）
echo "$*" >> "${STUB_CURL_LOG}"
state="${STUB_CURL_STATE}"
n=0
if [ -f "$state" ]; then n=$(cat "$state"); fi
n=$((n + 1))
printf '%s' "$n" > "$state"

is_sse=0
want_code=0
prev=""
url=""
for a in "$@"; do
  case "$a" in
    -N) is_sse=1 ;;
    http://*|https://*) url="$a" ;;
  esac
  if [ "$prev" = "-w" ] && [ "$a" = "%{http_code}" ]; then want_code=1; fi
  prev="$a"
done

code=200
if [ "${STUB_CURL_MODE:-ok}" = "flaky" ]; then
  if [ $((n % 2)) -eq 0 ]; then code=000; fi
fi

if [ "$is_sse" = "1" ]; then
  exit "${STUB_SSE_RC:-28}"
fi
if [ "$want_code" = "1" ]; then
  printf '%s' "$code"
  exit 0
fi
if [ "$code" = "000" ]; then
  exit 7
fi
printf '{"app":"admin-api","sha":"%s","tag":"sha-%s"}\n' "${STUB_CURL_SHA}" "$(printf '%s' "${STUB_CURL_SHA}" | cut -c1-7)"
exit 0
'''


# ══════════════════════════════════════════════════════════════════════════════
# 沙箱：一棵**真 git**（本地 bare origin）+ 两个桩
# ══════════════════════════════════════════════════════════════════════════════

def _git(cwd: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update(GIT_ENV)
    proc = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, f"git {' '.join(args)} 失败：{proc.stderr}"
    return proc.stdout.strip()


def _commit(root: Path, message: str) -> str:
    marker = root / "commit-log.txt"
    previous = marker.read_text(encoding="utf-8") if marker.exists() else ""
    marker.write_text(previous + message + "\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


class Sandbox:
    """`repo/`（真 git 检出 + 两个脚本 + lib）+ `origin.git`（本地 bare）+ 桩。"""

    def __init__(self, tmp_path: Path, *, help_text: str | None = None):
        self.tmp = Path(tmp_path)
        self.root = self.tmp / "repo"
        self.origin = self.tmp / "origin.git"
        self.state = self.tmp / "state"
        self.bin = self.tmp / "bin"
        self.aliyun_log = self.tmp / "aliyun.log"
        self.curl_log = self.tmp / "curl.log"
        self.curl_state = self.tmp / "curl-count"
        self.ssh_config = self.tmp / "ssh_config"
        self.help_text = help_text or "--version <sha>  要发布的版本\n"

        (self.root / "scripts" / "lib").mkdir(parents=True)
        shutil.copy2(INSPECT, self.root / "scripts" / "prod-inspect.sh")
        shutil.copy2(RELEASE, self.root / "scripts" / "prod-release.sh")
        shutil.copy2(LIB, self.root / "scripts" / "lib" / "prod-swas-run.sh")

        self.bin.mkdir()
        self._write_stub("aliyun", ALIYUN_STUB)
        self._write_stub("curl", CURL_STUB)

        self.ssh_config.write_text(
            f"Host {DEPLOY_ALIAS}\n  HostName {DEPLOY_HOST}.local\n  User deployer\n", encoding="utf-8"
        )
        self.cred_file = self.tmp / "aliyun-config.json"
        self.cred_file.write_text('{"profiles": [{"name": "prod"}]}', encoding="utf-8")
        self._build_git()

    # ── 桩 / git 摆位 ──────────────────────────────────────────────────────────
    def _write_stub(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def _build_git(self) -> None:
        subprocess.run(["git", "init", "-q", "--bare", str(self.origin)], check=True,
                       capture_output=True, env={**os.environ, **GIT_ENV})
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)], check=True,
                       capture_output=True, env={**os.environ, **GIT_ENV})
        self.base_sha = _commit(self.root, "base")
        _git(self.root, "remote", "add", "origin", str(self.origin))
        _git(self.root, "push", "-q", "origin", "main:main")

        # 发布线 = base（之后 main 前进，release 落后于 main，这是常态）
        _git(self.root, "checkout", "-q", "-b", "release")
        _git(self.root, "push", "-q", "origin", "release:release")
        self.release_sha = _git(self.root, "rev-parse", "HEAD")

        _git(self.root, "checkout", "-q", "main")
        self.main_sha = _commit(self.root, "main moves on")
        _git(self.root, "push", "-q", "origin", "main:main")

        # 侧分支：一个**不是** release 祖先的提交（版本闸门的红证素材）
        _git(self.root, "checkout", "-q", "-b", "hotfix")
        self.hotfix_sha = _commit(self.root, "hotfix only on a side branch")
        _git(self.root, "push", "-q", "origin", "hotfix:hotfix")

        _git(self.root, "checkout", "-q", "release")

    # ── 读数 / 运行 ────────────────────────────────────────────────────────────
    def env(self, *, host_id: str | None = DEPLOY_HOST, ssh_config: Path | str | None = None,
            postcheck: str = "match", deploy_rc: int = 0, inspect: str = "ok",
            curl_mode: str = "ok", streams: str = "0", run_fail: int = 0, deploy_sleep: float = 0.0,
            describe_shape: str = "singular", poll_attempts: int = 40,
            sse_url: str | None = None) -> dict[str, str]:
        env = os.environ.copy()
        env["PATH"] = f"{self.bin}{os.pathsep}{env.get('PATH', '')}"
        env["MIGAO_PROD_ALIYUN_BIN"] = str(self.bin / "aliyun")
        env["MIGAO_PROD_PYTHON_BIN"] = sys.executable
        env["MIGAO_PROD_CURL_BIN"] = str(self.bin / "curl")
        env["MIGAO_PROD_CRED_FILE"] = str(self.cred_file)
        env["MIGAO_PROD_SSH_CONFIG"] = str(self.ssh_config if ssh_config is None else ssh_config)
        env["MIGAO_PROD_BASE"] = BASE_DOMAIN
        env["MIGAO_PROD_POLL_INTERVAL"] = "0"
        if host_id is None:
            env.pop("MIGAO_PROD_HOST_ID", None)
        else:
            env["MIGAO_PROD_HOST_ID"] = host_id
        env["STUB_ALIYUN_LOG"] = str(self.aliyun_log)
        env["STUB_ALIYUN_STATE"] = str(self.state)
        env["STUB_CURL_LOG"] = str(self.curl_log)
        env["STUB_CURL_STATE"] = str(self.curl_state)
        env["STUB_CURL_MODE"] = curl_mode
        env["STUB_CURL_SHA"] = self.release_sha
        env["STUB_TARGET7"] = self.release_sha[:7]
        env["STUB_POSTCHECK"] = postcheck
        env["STUB_DEPLOY_RC"] = str(deploy_rc)
        env["STUB_DEPLOY_SLEEP"] = str(deploy_sleep)
        env["STUB_DESCRIBE_SHAPE"] = describe_shape
        env["MIGAO_PROD_POLL_ATTEMPTS"] = str(poll_attempts)
        env["STUB_INSPECT"] = inspect
        env["STUB_HELP"] = self.help_text
        env["STUB_STREAMS"] = streams
        env["STUB_RUN_FAIL"] = str(run_fail)
        if sse_url is None:
            env.pop("MIGAO_PROD_SSE_PROBE_URL", None)
        else:
            env["MIGAO_PROD_SSE_PROBE_URL"] = sse_url
        return env

    def run_inspect(self, *args: str, env: dict[str, str] | None = None):
        return subprocess.run(
            ["bash", str(self.root / "scripts" / "prod-inspect.sh"), *args],
            cwd=self.root, env=env if env is not None else self.env(),
            capture_output=True, text=True, timeout=300,
        )

    def run_release(self, *args: str, env: dict[str, str] | None = None):
        return subprocess.run(
            ["bash", str(self.root / "scripts" / "prod-release.sh"), *args],
            cwd=self.root, env=env if env is not None else self.env(),
            capture_output=True, text=True, timeout=300,
        )

    def aliyun_calls(self) -> list[list[str]]:
        if not self.aliyun_log.is_file():
            return []
        return [json.loads(line)["argv"] for line in self.aliyun_log.read_text(encoding="utf-8").splitlines() if line]

    def run_command_calls(self) -> list[list[str]]:
        return [argv for argv in self.aliyun_calls() if "run-command" in argv]

    def commands_sent(self) -> list[str]:
        out = []
        for argv in self.run_command_calls():
            if "--command-content" in argv:
                out.append(argv[argv.index("--command-content") + 1])
        return out

    def marker(self, name: str) -> str | None:
        path = self.state / name
        return path.read_text(encoding="utf-8") if path.is_file() else None


# ══════════════════════════════════════════════════════════════════════════════
# ① 只读白名单 / ② 发布脚本无写面
# ══════════════════════════════════════════════════════════════════════════════

def _payload_lines(text: str) -> list[str]:
    match = re.search(r"# READONLY-PAYLOAD-BEGIN\n(.*?)\n# READONLY-PAYLOAD-END", text, re.S)
    assert match, "找不到只读载荷块（# READONLY-PAYLOAD-BEGIN / END）"
    return [line for line in match.group(1).splitlines() if line.strip()]


def test_inspect_payload_is_readonly_whitelisted():
    """只读载荷逐条拆开：首词必须白名单、`docker` 只许 `ps` / `system`、不许任何重定向写面。"""
    lines = _payload_lines(INSPECT.read_text(encoding="utf-8"))
    assert len(lines) >= 10, f"只读载荷只有 {len(lines)} 条（盘点段被删了？）"
    checked = 0
    for line in lines:
        match = re.match(r"sec ([a-z_]+) ('|\")(.*)\2$", line)
        assert match, f"载荷行形态不对（应为 sec <名字> '<命令>'）：{line}"
        payload = match.group(3)
        assert ">" not in payload.replace("2>/dev/null", "").replace("2>&1", ""), f"载荷里有重定向（写面）：{payload}"
        for segment in re.split(r";|\|\||&&|\s\|\s", payload):
            segment = segment.strip()
            if not segment:
                continue
            word = segment.split()[0]
            assert word in READONLY_WHITELIST, f"非白名单命令 '{word}'：{segment}"
            if word == "docker":
                parts = segment.split()
                assert len(parts) > 1, segment
                # `exec` 只许进容器**跑只读的 `nginx -T`**（2026-11-23 真机：宿主没有 nginx 二进制）
                if parts[1] == "exec":
                    assert "nginx -T" in segment, f"docker exec 只许只读 nginx -T：{segment}"
                else:
                    assert parts[1] in ALLOWED_DOCKER_SUBCOMMANDS, \
                        f"docker 子命令不在白名单（只许 ps / system df）：{segment}"
            checked += 1
    assert checked >= 10, checked


def test_release_script_has_no_write_verbs():
    """发布脚本**不得**自带写面：所有改动只能发生在盘上 `deploy.sh` 里；出现 ⇒ 点名行号。"""
    offenders = []
    for number, line in enumerate(RELEASE.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue                     # 注释里交代「不做什么」不算写面
        for verb in FORBIDDEN_IN_RELEASE:
            if verb in line:
                offenders.append(f"{RELEASE.name}:{number}: {verb}  ⟵ {stripped}")
    assert not offenders, "prod-release.sh 出现了写动词（发布只能通过盘上 deploy.sh）：\n" + "\n".join(offenders)
    text = RELEASE.read_text(encoding="utf-8")
    assert "/opt/migao-deploy/deploy.sh" in text, "没有复用盘上 deploy.sh（自己另写一套部署逻辑？）"


# ══════════════════════════════════════════════════════════════════════════════
# ③④ --apply 闸门
# ══════════════════════════════════════════════════════════════════════════════

def test_apply_gate_is_static():
    """静态：dry-run 的 `exit 0` 必须**在**任何真发调用之前（照代码行号判）+ 有 `$APPLY` 守卫。"""
    lines = RELEASE.read_text(encoding="utf-8").splitlines()
    dry_exit = [i for i, line in enumerate(lines, 1) if "DRY-RUN=OK" in line]
    deploy_call = [i for i, line in enumerate(lines, 1) if "detect_deploy_flag" in line and "()" not in line]
    assert dry_exit, "找不到 dry-run 的出口（DRY-RUN=OK）"
    assert deploy_call, "找不到真发入口（detect_deploy_flag）"
    assert min(dry_exit) < min(deploy_call), "dry-run 的出口排在真发之后（不带 --apply 也会发）"
    assert re.search(r'\[\s*"\$APPLY"\s*-ne\s*1\s*\]', "\n".join(lines)), "没有 `$APPLY` 守卫"


def test_dry_run_never_calls_run_command(tmp_path: Path):
    """行为桩：实跑 `--dry-run` ⇒ 云助手桩**0 次调用**（一次 run-command 都没发）。"""
    box = Sandbox(tmp_path)
    proc = box.run_release()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY-RUN=OK" in proc.stdout, proc.stdout
    calls = box.run_command_calls()
    assert calls == [], f"dry-run 发了 run-command：{calls}"
    assert box.marker("deploy-ran") is None
    assert box.marker("ledger-appended") is None
    assert "SWITCH-BLINDSPOT" not in proc.stdout, "dry-run 启动了盲区探针（只在 --apply 才量）"


def test_dry_run_does_not_start_the_blindspot_probe(tmp_path: Path):
    """对照臂：`--apply` 才量盲区 —— dry-run 打的是「不启动」，并说明 apply 才读 `--help`。"""
    box = Sandbox(tmp_path)
    proc = box.run_release("--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "切换盲区探针：dry-run 不启动" in proc.stdout
    assert "--apply 时才执行" in proc.stdout, "没打印将要执行的远端命令（dry-run 的价值就在这一行）"
    assert "/opt/migao-deploy/deploy.sh" in proc.stdout


# ══════════════════════════════════════════════════════════════════════════════
# ⑤ 机器闸门
# ══════════════════════════════════════════════════════════════════════════════

def test_machine_gate_refuses_off_the_deploy_box(tmp_path: Path):
    """非部署机 ⇒ 退 1、具名（两台机器读数 + 三个出口）、且一次 run-command 都没发。"""
    box = Sandbox(tmp_path)
    proc = box.run_release("--apply", env=box.env(host_id=OTHER_HOST))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    err = proc.stderr
    assert "非部署机" in err and "拒绝发布" in err
    assert OTHER_HOST.lower() in err.lower(), "没报本机读数（判红不可归因）"
    assert f"{DEPLOY_HOST}.local" in err, "没报部署机的 HostName（判红不可归因）"
    assert f"ssh {DEPLOY_ALIAS}" in err, "没给出正确路径"
    assert "prod-inspect.sh" in err, "没给出「只看现场」的出口"
    assert box.run_command_calls() == [], "闸门没拦住：已经发了 run-command"


def test_machine_gate_is_undecidable_when_the_reading_is_unavailable(tmp_path: Path):
    """读数拿不到（ssh 配置读不出）⇒ 退 **3**（不可判定），不是「通过」也不是「判红」。"""
    box = Sandbox(tmp_path)
    proc = box.run_release("--host-assert", env=box.env(ssh_config=tmp_path / "no-such-ssh-config"))
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "不可判定" in proc.stderr
    assert "MIGAO_PROD_SSH_CONFIG" in proc.stderr, "没给出出口（怎么让它可判定）"


def test_host_assert_passes_on_the_deploy_box(tmp_path: Path):
    """身份相等 ⇒ `--host-assert` 退 0，且**零副作用**（不读线上、不发 run-command）。"""
    box = Sandbox(tmp_path)
    proc = box.run_release("--host-assert")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "本机就是部署机" in proc.stdout
    assert box.run_command_calls() == []


# ══════════════════════════════════════════════════════════════════════════════
# ⑥ 版本闸门（本地 bare 仓，不真连网）
# ══════════════════════════════════════════════════════════════════════════════

def test_version_gate_refuses_a_sha_not_on_the_release_line(tmp_path: Path):
    """目标版本不是 `origin/release` 的祖先（侧分支提交）⇒ 退 1、具名、给出 release..target 的提交。"""
    box = Sandbox(tmp_path)
    proc = box.run_release("--version", box.hotfix_sha)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    err = proc.stderr
    assert "目标版本不在发布线上" in err
    assert box.hotfix_sha[:7] in err
    assert "hotfix only on a side branch" in err, "没打印 release..target 上的提交（判红不可归因）"
    assert box.run_command_calls() == [], "版本不合规却已经开始发"


def test_version_gate_accepts_a_commit_on_the_release_line(tmp_path: Path):
    """对照臂：`origin/release` 上的提交 ⇒ 通过；并报出「main 领先 release 多少个提交（本次不发）」。"""
    box = Sandbox(tmp_path)
    proc = box.run_release("--version", box.release_sha)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "在发布线" in proc.stdout
    assert "本次不发" in proc.stdout, "没报 main 领先 release 的部分（人会以为发了最新）"
    assert box.run_command_calls() == []


def test_version_gate_is_undecidable_when_origin_is_unreachable(tmp_path: Path):
    """取不到远端 ⇒ 退 **3**（「不知道发布线在哪」≠「发布线没问题」）。"""
    box = Sandbox(tmp_path)
    _git(box.root, "remote", "set-url", "origin", str(tmp_path / "no-such-origin.git"))
    proc = box.run_release()
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "不可判定" in proc.stderr
    assert box.run_command_calls() == []


# ══════════════════════════════════════════════════════════════════════════════
# ⑦⑧⑨ 真发：同源自检 / 台账 / 切换盲区
# ══════════════════════════════════════════════════════════════════════════════

def test_apply_happy_path_reports_blindspot_and_appends_the_ledger_once(tmp_path: Path):
    """全桩 happy path：退 0 + 三服务同源 + `SWITCH-BLINDSPOT failures=0` + 可粘贴记录行 + 台账 1 次。"""
    box = Sandbox(tmp_path)
    proc = box.run_release("--apply")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout

    assert "SWITCH-BLINDSPOT failures=0" in out, out
    assert re.search(r"SWITCH-BLINDSPOT failures=0 max_gap_ms=\d+", out), out
    assert "SSE-PROBE=SKIPPED" in out, "没配置端点时必须明说 SKIPPED（不许假装在探）"

    rows = [line for line in out.splitlines() if line.startswith("PROD-RELEASE ")]
    assert len(rows) == 1, f"应恰好一行可粘贴台账行，实得 {rows}"
    row = rows[0]
    assert " rc=0 " in row and f"version={box.release_sha[:7]} " in row
    for key in ("api=", "web=", "ai=", "at=", "operator="):
        assert key in row, f"记录行缺 {key}：{row}"

    ledger = box.marker("ledger-appended")
    assert "release-ledger.jsonl" in (ledger or ""), "没有追加台账"
    ledger_cmds = [cmd for cmd in box.commands_sent() if "release-ledger.jsonl" in cmd]
    assert len(ledger_cmds) == 1, f"台账只许追加**一次**，实得 {len(ledger_cmds)} 次"
    assert ">>" in ledger_cmds[0], f"台账不是追加（用了覆写？）：{ledger_cmds[0]}"
    assert ledger.count("release-ledger.jsonl") == 1
    assert box.release_sha in ledger, "台账里没有完整目标 sha（事后没法对账）"
    deploy = box.marker("deploy-ran")
    assert deploy is not None and box.release_sha in deploy, "真发的命令里没有目标版本"
    assert "--version" in deploy, f"没有把版本按 --help 判定的参数传进去：{deploy}"


def test_self_check_names_the_mismatched_service_and_skips_the_ledger(tmp_path: Path):
    """自检不同源（admin-web 停在 caf01e4）⇒ 退 1、**点名 web**、且台账一次都不追加。"""
    box = Sandbox(tmp_path)
    proc = box.run_release("--apply", env=box.env(postcheck="stale-web"))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    err = proc.stderr
    assert "三服务身份不同源" in err
    assert re.search(r"✗ web：docker=caf01e4", err), err
    assert "≠ 目标" in err
    assert "admin-api" not in err.split("✗")[1][:40] if "✗" in err else True
    assert box.marker("ledger-appended") is None, "自检没通过却写了台账（半截发布被记成成功）"
    rows = [line for line in (proc.stdout + proc.stderr).splitlines() if line.startswith("PROD-RELEASE ")]
    assert rows and " rc=1 " in rows[0], "失败时也要打印记录行（rc=1）"


def test_blindspot_reports_failures_without_failing_the_release(tmp_path: Path):
    """切换窗口里失败过（curl 桩每 3 次给 000）⇒ 打印 failures>0 + `::warning::`，发布整体仍退 0。"""
    box = Sandbox(tmp_path)
    proc = box.run_release("--apply", env=box.env(curl_mode="flaky", deploy_sleep=0.7))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    match = re.search(r"SWITCH-BLINDSPOT failures=(\d+)", proc.stdout)
    assert match, proc.stdout
    assert int(match.group(1)) > 0, "探针没记到失败（盲区读数不可信）"
    assert "::warning::" in proc.stderr and "对用户无感" in proc.stderr


# ══════════════════════════════════════════════════════════════════════════════
# ⑩ deploy.sh --help 现读
# ══════════════════════════════════════════════════════════════════════════════

def test_missing_help_is_undecidable(tmp_path: Path):
    """`--help` 里没有版本参数 ⇒ 退 **3** 并打印 `--help` 原文片段（不猜参数名）。"""
    box = Sandbox(tmp_path, help_text="用法：bash deploy.sh [--dry-run]\n  没有版本参数\n")
    proc = box.run_release("--apply")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "不可判定" in proc.stderr
    assert "没有版本参数" in proc.stderr, "没打印 --help 原文片段"
    assert box.marker("deploy-ran") is None, "不知道版本参数却已经发了"


def test_version_flag_is_read_from_help_not_hardcoded(tmp_path: Path):
    """`--help` 给的是 `--ref` ⇒ 真发命令里用的是 `--ref`（证明是**现读**，不是写死 `--version`）。"""
    box = Sandbox(tmp_path, help_text="用法：bash deploy.sh --ref <sha> [--skip-health]\n")
    proc = box.run_release("--apply")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    deploy = box.marker("deploy-ran") or ""
    assert "--ref" in deploy and box.release_sha in deploy, deploy


# ══════════════════════════════════════════════════════════════════════════════
# ⑪ 只读盘点三态
# ══════════════════════════════════════════════════════════════════════════════

def test_inspect_reports_ok(tmp_path: Path):
    """全部段 rc=0 ⇒ `READONLY-INSPECT=OK` 且退 0；容量读数只作信息（不参与 rc）。"""
    box = Sandbox(tmp_path)
    proc = box.run_inspect()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "READONLY-INSPECT=OK" in proc.stdout
    sent = box.commands_sent()
    assert len(sent) == 1 and "# READONLY-PAYLOAD-BEGIN" in sent[0], "盘点不是一条固定只读载荷"
    assert "sec host '" in sent[0], "载荷里没有第一段（host）"
    assert "df -h /opt" in sent[0] and "docker system df" in sent[0]


def test_inspect_reports_a_failed_section(tmp_path: Path):
    """某段失败（nginx）⇒ 退 1、`INCOMPLETE failed=[nginx]`（缺的段就是没看到的现场）。"""
    box = Sandbox(tmp_path)
    proc = box.run_inspect(env=box.env(inspect="failed"))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "INCOMPLETE" in proc.stderr
    assert "failed=[nginx]" in proc.stderr, proc.stderr


def test_inspect_reports_a_missing_section(tmp_path: Path):
    """某段**缺失**（回读被截断）⇒ 退 1、`missing=[timers]` —— 不许把「没看到」读成「没问题」。"""
    box = Sandbox(tmp_path)
    proc = box.run_inspect(env=box.env(inspect="missing"))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "missing=[timers]" in proc.stderr, proc.stderr


def test_inspect_is_undecidable_without_the_cli(tmp_path: Path):
    """CLI 缺 ⇒ 退 **3** 并给出出口（装在哪 / 怎么显式指定），不许冒充「盘点通过」。"""
    box = Sandbox(tmp_path)
    env = box.env()
    env["MIGAO_PROD_ALIYUN_BIN"] = str(tmp_path / "no-such-aliyun")
    proc = box.run_inspect(env=env)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "不可判定" in proc.stderr
    assert "MIGAO_PROD_ALIYUN_BIN" in proc.stderr


# ══════════════════════════════════════════════════════════════════════════════
# ⑪b 轮询/解析：**真机形态必须读成成功**（2026-11-23 22:45 部署机真跑出来的缺陷）
# ══════════════════════════════════════════════════════════════════════════════
#
# 现场：`scripts/prod-inspect.sh` 在部署机上 rc=3「等不到执行结果（状态=未知，轮询 40 次）」，
# 而同一个 invoke-id 用独立脚本查是 `InvocationResult.InvocationStatus = Success / ExitCode = 0`。
# 根因 = 解析只认 `InvokeStatus`/`Status`，**没认 `InvocationStatus`** ⇒ 明明成功却判「未知」⇒ 轮询到超时。
# ⇒ 三条判据分别钉：单数形态（真机）/ 复数 list 形态 / 状态键缺失但有输出（推断），外加「超时要说清为什么」。

@pytest.mark.parametrize("shape", ["singular", "plural", "inferred"])
def test_poll_reads_the_real_shapes_as_success(tmp_path: Path, shape: str):
    """三种「执行已结束」形态都必须判**成功**（不许把 Success 读成「未知」）。

    `singular` = 真机形态（`InvocationResult` dict + `InvocationStatus`）；
    `plural`   = `InvocationResults.InvocationResult = [...]`；
    `inferred` = 状态键缺失但有 `ExitCode`/`Output` ⇒ 记为 `Success(推断)` 并照常返回。
    """
    box = Sandbox(tmp_path)
    proc = box.run_inspect(env=box.env(describe_shape=shape))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "READONLY-INSPECT=OK" in proc.stdout


def test_failed_status_without_exit_code_is_not_read_as_success(tmp_path: Path):
    """`InvocationStatus=Failed` 但云端**没给 `ExitCode``** ⇒ 不许读成 0（这条同时钉住「状态键认 `InvocationStatus`」）。

    没有状态键时，`Output` 非空会走「推断已结束」⇒ 返回 0 —— 正是 2026-11-23 真机缺陷的同族形态：
    **成功判不出来只是退 3，失败判成成功才是把半成品当交付**。
    """
    box = Sandbox(tmp_path)
    proc = box.run_inspect(env=box.env(describe_shape="failed_no_exit"))
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "远端执行状态 = Failed" in proc.stderr, proc.stderr


def test_poll_timeout_prints_the_response_body_excerpt(tmp_path: Path):
    """轮询超时 ⇒ 退 **3**，且**必须**打印最后一轮返回体片段（否则「判不了」说不出为什么）。"""
    box = Sandbox(tmp_path)
    env = box.env(describe_shape="running", poll_attempts=2)
    env["MIGAO_PROD_POLL_INTERVAL"] = "0"
    proc = box.run_inspect(env=env)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    err = proc.stderr
    assert "不可判定" in err and "等不到执行结果" in err
    assert "最后一轮返回体前 400 字节" in err, f"超时没打印返回体片段：{err}"
    assert "Running" in err, f"返回体片段里应能看到真实状态：{err}"


def test_missing_status_fields_is_undecidable_and_prints_the_body(tmp_path: Path):
    """返回体里既没有状态键也没有输出（`{"Foo": "bar"}`）⇒ 退 **3** + 打印返回体片段。"""
    box = Sandbox(tmp_path)
    env = box.env(describe_shape="junk", poll_attempts=2)
    env["MIGAO_PROD_POLL_INTERVAL"] = "0"
    proc = box.run_inspect(env=env)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "最后一轮返回体前 400 字节" in proc.stderr
    assert '"Foo"' in proc.stderr or "Foo" in proc.stderr, f"没把返回体打出来：{proc.stderr}"


# ══════════════════════════════════════════════════════════════════════════════
# ⑫⑬ 文档接线 / 脚本自身
# ══════════════════════════════════════════════════════════════════════════════

def test_docs_cover_decoupling_gates_and_the_seamless_boundary():
    """文档必须覆盖：解耦理由 / 三种跑法 / 闸门与自检 / 失败怎么读 / 无感发布的四条缺口 / 云监控口径。"""
    assert DOCS.is_file(), f"缺少 {DOCS}"
    text = DOCS.read_text(encoding="utf-8")
    for required in (
        "scripts/prod-inspect.sh",
        "scripts/prod-release.sh",
        "--apply",
        "22",
        "443",
        "~/.aliyun/config.json",
        "SWITCH-BLINDSPOT",
        "无感发布的现状与缺口",
        "server.shutdown=graceful",
        "expand/contract",
        "阿里云云监控",
        "deploy-prod.yml",
    ):
        assert required in text, f"文档缺关键内容：{required}"
    assert "备用" in text, "没写清 GitHub 那条 deploy-prod.yml 现在的地位（降级为备用）"


def test_scripts_are_executable_and_parse():
    """两个脚本都必须 `100755` 且 `bash -n` 通过（语法坏了的闸门等于没有闸门）。"""
    for path in (INSPECT, RELEASE):
        assert path.is_file(), f"缺少 {path}"
        assert path.stat().st_mode & 0o777 == 0o755, f"{path.name} 权限不是 100755：{oct(path.stat().st_mode & 0o777)}"
        proc = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert proc.returncode == 0, f"{path.name} 语法错：{proc.stderr}"
    assert LIB.is_file(), f"缺少通道实现 {LIB}"
