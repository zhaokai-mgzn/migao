# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""`deploy/scripts/swas-deploy-ci.sh` **部署链加固**守卫 —— issue #4767（2026-09-21 云测试环境事故）。

## 事故（主会话实测，非推断）

| 事实 | 读数 |
|---|---|
| `api.migaozn.com/health` | 🔴 502（nginx 连不上 admin-api 上游）⇒ 环境实际不可用 |
| 三条部署腿在 `ca724257e`（#4733） | **同时 failure** |
| 之后两条腿 | 挂住 `in_progress` 20+ 分钟（`updated` 冻住） |
| 后果 | 挂住的 run **占着 deploy-* 的 concurrency 组** ⇒ 后续 main 的部署全被挡住 |
| 真因可见性 | 远端 `deploy.sh` 输出是 **base64** 且被 `head -c 1500` 截断 ⇒ 只能解出前 3 行；最终靠 Aliyun CLI 上机看容器日志才拿到真因 |
| 环境状态 | 失败那次**把 admin-api 打下线且无回滚**（旧容器被替换、新容器起不来） |

## 本文件锁什么（三件要修的事，逐条都有可执行判据）

1. **硬超时**（`SWAS_DEPLOY_TIMEOUT_SECONDS`，默认 900s）：旧实现只有「180 次 × 20s」的**次数**上界，
   而单次 `aliyun` CLI 调用本身**无上界** ⇒ CLI 挂住时轮询永不返回。判据 = 墙钟 deadline +
   每次 CLI 调用过 `with_deadline`；**红证** = 注入「调用永不返回」（桩恒返回 `Running`）⇒ 必红且**有墙钟上界**。
2. **远端输出可读**：`InvocationResult.Output` 是 base64 ⇒ 解码后打印 + **完整落 `$GITHUB_STEP_SUMMARY`**；
   非 base64 原样打印（不吞信息）。**红证** = 注入一段已知错误文本 ⇒ summary 里能找到原文；
   反向红证 = 把解码去掉 ⇒ 同一条判据必红（判据有判别力）。
3. **失败不留坏状态**：远端 `deploy.sh` 是「先 `up -d` 再健康检查」⇒ 新容器起不来时旧容器已被替换。
   判据 = 失败**自动重试 1 次** → 仍失败则**回滚到上一个可用镜像 tag**（`.last-good-tag`）→ 仍不行
   ⇒ **显式告警**（`::error::`）。**红证** = 注入「新容器健康检查失败」+ 已知 PREV tag
   ⇒ 断言**第三次调用带的是旧 tag**（= 回滚真的发生了）。

## 判据形态

判据读的是**脚本当前文本 + 真实执行行为**（桩 `aliyun`），不是"与某个历史版本等值"（§18.3：不读可变引用）。
执行式红证**不联网、不碰真实云、不写共享 `/tmp`**（CLI 安装块的两处 `/tmp/aliyun*` 在沙箱副本里改指临时目录，
与 `test_swas_deploy_ci_bootstrap.py` 的既有手法一致）。
"""
import copy
import json
import os
import re
import shutil
import subprocess
import textwrap
from base64 import b64encode
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "deploy" / "scripts" / "swas-deploy-ci.sh"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

DEPLOY_WORKFLOWS = [
    "deploy-admin-api.yml",
    "deploy-frontend.yml",
    "deploy-ai-agent-service.yml",
]

# 注入用的已知文本（issue #4767 ② 的红证锚点：它必须能从 summary 里被原样找回）
KNOWN_TEXT = "已知错误注入串-DEPLOY-4767: cp: cannot stat '/tmp/whatever'"


def read_script() -> str:
    assert SCRIPT.is_file(), f"反空跑锚点：目标脚本不存在 → {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def function_body(text: str, name: str) -> str:
    """取 shell 函数体（`name() {` 到配对的 `}` 行）。取不到 ⇒ 显式失败（不是"通过"）。"""
    m = re.search(rf"^{re.escape(name)}\(\) \{{$", text, re.M)
    assert m, f"反空跑锚点：脚本里找不到函数 `{name}()` —— 判据已过期或脚本被改写"
    end = text.find("\n}\n", m.end())
    assert end != -1, f"函数 `{name}()` 没有配对的收尾 `}}`（脚本语法已坏）"
    return text[m.end():end]


# ══════════════════════════════════════════════════════════════════════════
# 一、静态判据
# ══════════════════════════════════════════════════════════════════════════

def test_deploy_phase_has_wall_clock_hard_timeout():
    """① 硬超时必须是**墙钟**上界（不是"次数 × 间隔"），且默认 ≤ 15 分钟（issue 要求）。"""
    text = read_script()
    m = re.search(r"^DEPLOY_TIMEOUT_SECONDS=\$\{SWAS_DEPLOY_TIMEOUT_SECONDS:-(\d+)\}", text, re.M)
    assert m, "找不到 `DEPLOY_TIMEOUT_SECONDS=${SWAS_DEPLOY_TIMEOUT_SECONDS:-<默认值>}`（硬超时的默认值锚点）"
    default = int(m.group(1))
    assert default <= 900, f"部署阶段硬超时默认值 {default}s > 900s（15min）—— issue #4767 要求 ≤15 分钟"
    assert re.search(r"^DEADLINE=\$\(\( \$\(date \+%s\) \+ DEPLOY_TIMEOUT_SECONDS \)\)$", text, re.M), (
        "硬超时必须是**墙钟** deadline（`DEADLINE=$(( $(date +%s) + DEPLOY_TIMEOUT_SECONDS ))`）——"
        "旧的「180 次 × 20s」次数上界挡不住「单次 CLI 调用挂住」"
    )
    assert re.search(r"remaining_seconds\(\)", text), "缺少 `remaining_seconds()`（deadline 的读取口）"


def test_every_cli_call_has_its_own_deadline():
    """① 单次 `aliyun` CLI 调用也必须有自己的上界（否则轮询循环的上界形同虚设）。"""
    text = read_script()
    assert "with_deadline() {" in text, "缺少 `with_deadline()`（单次子进程的硬上界执行器）"
    body = function_body(text, "with_deadline")
    assert "kill -TERM" in body and "kill -KILL" in body, (
        "`with_deadline` 必须在到点后强杀（先 TERM 再 KILL）—— 只 sleep 不杀等于没有上界"
    )
    run_cmd = function_body(text, "run_cmd")
    calls = re.findall(r"aliyun swas-open \"\$[kc]\"", run_cmd)
    assert calls, "`run_cmd` 里找不到 `aliyun swas-open` 调用（判据已过期）"
    assert "with_deadline" in run_cmd, (
        "`run_cmd` 必须让每次 aliyun 调用过 `with_deadline` —— CLI 自己挂住时轮询永不返回"
        "（2026-09-21 事故里 run 被钉在 in_progress 20+ 分钟）"
    )
    assert not re.search(r"^\s*out1=\$\(aliyun swas-open", text, re.M), (
        "仍有**裸** `out1=$(aliyun swas-open …)`（无上界调用）"
    )


def test_no_unbounded_sleep_in_deploy_loop():
    """① 轮询循环里不许有绕过 deadline 的 `sleep`（否则超时判定会被 sleep 拖过界）。"""
    text = read_script()
    assert re.search(r"^nap\(\) \{$", text, re.M), "缺少 `nap()`（受 deadline 约束的等待）"
    body = function_body(text, "nap")
    assert "remaining_seconds" in body, "`nap` 必须按剩余预算截断等待时长"
    # 轮询函数体里不得出现裸 `sleep`
    poll = function_body(text, "deploy_attempt")
    assert not re.search(r"^\s*sleep\s+\d", poll, re.M), (
        "`deploy_attempt` 里出现裸 `sleep <n>` —— 必须走 `nap`（受 deadline 约束）"
    )
    assert "remaining_seconds" in poll, "`deploy_attempt` 必须在每轮检查剩余预算"


def test_remote_output_is_base64_decoded_with_fallback():
    """② 远端输出必须**解码后**打印；非 base64 原样打印（不吞信息）。"""
    text = read_script()
    body = function_body(text, "extract_remote_log")
    assert "base64.b64decode" in body, (
        "`extract_remote_log` 里没有 `base64.b64decode` —— 把 base64 当「日志」等于没有日志"
    )
    assert "binascii.Error" in body, (
        "缺少**非 base64** 的容错分支（`binascii.Error`）—— 解码失败必须原样打印，不得吞掉信息"
    )
    assert "json.loads" in body, "`extract_remote_log` 必须先从 SWAS JSON 里取 `Output`"
    assert 'validate=True' in body, "`b64decode` 应带 `validate=True`（非 base64 立刻落到容错分支）"


def test_remote_output_lands_in_job_summary():
    """② 解码后的远端输出必须**完整落 job summary**（CI 日志会被截断，summary 不受影响）。"""
    text = read_script()
    assert "GITHUB_STEP_SUMMARY" in text, "脚本没有读 `$GITHUB_STEP_SUMMARY`"
    body = function_body(text, "emit_remote_log")
    assert "SUMMARY_FILE" in body, "`emit_remote_log` 没有把远端输出写进 summary"
    assert not re.search(r"head\s+-c\s+\d+", body), (
        "`emit_remote_log` 里出现 `head -c <n>` —— 远端输出被截断了（issue #4767 ② 的原始形态）"
    )


def test_failure_path_retries_once_then_rolls_back_then_alerts():
    """③ 失败 ⇒ 重试 1 次 ⇒ 仍失败 ⇒ 回滚到上一个可用 tag ⇒ 仍不行 ⇒ **显式告警**。"""
    text = read_script()
    assert re.search(r"PREV_GOOD_TAG", text), "脚本里没有回滚点（`PREV_GOOD_TAG`）"
    assert ".last-good-tag" in text, "脚本里没有远端 `.last-good-tag`（上一个可用镜像 tag 的记录点）"
    assert re.search(r"::error::", text), "失败路径没有 `::error::` 显式告警（不许让人从 502 反推）"
    # ⚠️ 回滚目标必须**先快照**再调用：`deploy_attempt` 会重置 `PREV_GOOD_TAG`（它承载的是
    #    **本次尝试**的远端回显）⇒ 直接用 `$PREV_GOOD_TAG` 会把回滚目标渲染成**空串**（实测踩到）
    snap = re.search(r"^ROLLBACK_TAG=\$PREV_GOOD_TAG$", text, re.M)
    assert snap, "回滚前没有 `ROLLBACK_TAG=$PREV_GOOD_TAG` 快照 —— 告警里的回滚目标会变成空串"
    call = re.search(r'^deploy_attempt\s+"\$ROLLBACK_TAG"\s+1$', text, re.M)
    assert call, (
        "没有「用上一个可用 tag 再跑一次 deploy」的回滚调用，或该调用丢了显式降级许可 —— "
        '期望 `deploy_attempt "$ROLLBACK_TAG" 1`（issue #4852 ②：回滚本身就是「往回走」，'
        "不带许可会被新增的「不许往回走」闸门挡掉）"
    )
    assert snap.start() < call.start(), "`ROLLBACK_TAG` 快照必须发生在回滚调用**之前**"
    assert re.search(r'deploy_attempt\s+"\$IMAGE_TAG"', text), "没有 `deploy_attempt \"$IMAGE_TAG\"` 调用"


def test_bootstrap_records_and_reports_last_good_tag():
    """③ 回滚点由 bootstrap 记录（成功才写）+ 回显（失败时可读）—— 不额外增加云调用。"""
    text = read_script()
    m = re.search(r'^BOOTSTRAP="', text, re.M)
    assert m, "反空跑锚点：扫不到 `BOOTSTRAP=\"` 赋值"
    i = m.end()
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            break
        i += 1
    raw = text[m.end():i]
    assert "PREV_GOOD_TAG=" in raw, "bootstrap 没有回显 `PREV_GOOD_TAG=`（失败时就拿不到回滚点）"
    assert ".last-good-tag" in raw, "bootstrap 没有读写 `.last-good-tag`"
    # 只在 deploy.sh 成功（rc=0）时写：失败把坏 tag 记成"上一个可用"= 回滚点被污染
    assert re.search(r"rc=\\\$\?.*?last-good-tag", raw, re.S), (
        "`.last-good-tag` 的写入必须发生在 `rc=$?` **之后**且以 rc=0 为条件"
    )
    assert re.search(r"\[ \\\$rc -eq 0 \]", raw), (
        "`.last-good-tag` 必须以 `[ $rc -eq 0 ]` 为条件写入 —— 否则失败的 tag 会覆盖回滚点"
    )


# ══════════════════════════════════════════════════════════════════════════
# 二、workflow：job 级硬超时（超时 ⇒ run 终止 ⇒ concurrency 锁释放）
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("wf", DEPLOY_WORKFLOWS)
def test_deploy_job_has_timeout_minutes(wf):
    """① 部署 job 必须有 `timeout-minutes` —— 脚本被卡死时由 GitHub 兜底终止 ⇒ 释放并发锁。"""
    path = WORKFLOWS_DIR / wf
    assert path.is_file(), f"反空跑锚点：workflow 不存在 → {path}"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    job = doc["jobs"]["build-and-deploy"]
    assert "timeout-minutes" in job, (
        f"{wf} 的 build-and-deploy 没有 `timeout-minutes` —— 卡死的 run 会永久占住 "
        "deploy-* 的 concurrency 组（2026-09-21 事故：后续 main 的部署全被挡住）"
    )
    assert 0 < int(job["timeout-minutes"]) <= 60, (
        f"{wf} 的 timeout-minutes={job['timeout-minutes']} 超出 (0,60] —— "
        "既要兜住「永久 in_progress」，也不能误杀正常构建（实测正常 job ≈5-11min）"
    )


@pytest.mark.parametrize("wf", DEPLOY_WORKFLOWS)
def test_deploy_job_keeps_its_gates(wf):
    """安全纪律：不许削弱门禁（不加 `continue-on-error`、不改 concurrency 语义）。"""
    path = WORKFLOWS_DIR / wf
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    job = doc["jobs"]["build-and-deploy"]
    assert "continue-on-error" not in job, f"{wf} 的部署 job 出现 `continue-on-error`（削弱门禁）"
    assert job["concurrency"]["group"].startswith("deploy-"), f"{wf} 的 concurrency group 被改坏"
    assert job["concurrency"]["cancel-in-progress"] is False, (
        f"{wf} 的 `cancel-in-progress` 被改成 true —— 会让并发的部署互相取消（改变语义）"
    )
    assert doc.get("permissions") == {"contents": "read"}, f"{wf} 的 permissions 被改动"


# ══════════════════════════════════════════════════════════════════════════
# 三、执行式红证（桩 `aliyun`，不联网、不碰真实云、不写共享 /tmp）
# ══════════════════════════════════════════════════════════════════════════

CURL_STUB = """#!/bin/bash
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -*) shift ;;
    *) shift ;;
  esac
done
printf 'stub-cli-tarball' > "$out"
"""

FILE_STUB = """#!/bin/bash
echo "$1: gzip compressed data"
"""

SUDO_STUB = """#!/bin/bash
# 桩 sudo：**no-op**（真实脚本要写 /usr/local/bin，测试不许写沙箱外的路径）
exit 0
"""

TAR_STUB = """#!/bin/bash
# 桩 tar：只创建脚本随后会调用到的 `aliyun`（避免写真实 /tmp）
: > "$STUB_SANDBOX/aliyun"
chmod +x "$STUB_SANDBOX/aliyun"
exit 0
"""

# 桩 aliyun：按 `$ALIYUN_STATE/resp-<第 n 次 describe 调用>` 回放，缺省回落到 `resp-last`
ALIYUN_STUB = """#!/bin/bash
echo "$*" >> "$ALIYUN_LOG"
case "$*" in
  *configure*|*plugin*|*version*|*help*) echo "stub-aliyun ok"; exit 0 ;;
esac
if [ "$1" != "swas-open" ]; then echo "stub-aliyun ok"; exit 0; fi
case "$2" in
  run-command|RunCommand) echo '{"InvokeId":"t-stub-invoke"}'; exit 0 ;;
  describe-invocation-result|DescribeInvocationResult)
    n=0
    [ -f "$ALIYUN_STATE/n" ] && n=$(cat "$ALIYUN_STATE/n")
    n=$((n + 1))
    echo "$n" > "$ALIYUN_STATE/n"
    if [ -f "$ALIYUN_STATE/resp-$n" ]; then cat "$ALIYUN_STATE/resp-$n"; else cat "$ALIYUN_STATE/resp-last"; fi
    exit 0 ;;
esac
echo "stub-aliyun: unknown $*"; exit 0
"""


def _write_exe(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _swas_json(status: str, output_text: str | None) -> str:
    payload = {"RequestId": "stub", "InvocationResult": {"InvocationStatus": status, "ExitCode": 0}}
    if output_text is not None:
        payload["InvocationResult"]["Output"] = b64encode(output_text.encode("utf-8")).decode("ascii")
    return json.dumps(payload)


def _prepare(tmp_path: Path, script_text: str | None):
    """沙箱：脚本副本（CLI 安装块的两处 `/tmp/aliyun*` 改指临时目录）+ 桩 bin。"""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)
    text = script_text if script_text is not None else read_script()
    text = text.replace("/tmp/aliyun", str(sandbox / "aliyun"))
    script = tmp_path / "swas-deploy-ci.sh"
    script.write_text(text, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_exe(bin_dir / "curl", CURL_STUB)
    _write_exe(bin_dir / "file", FILE_STUB)
    _write_exe(bin_dir / "sudo", SUDO_STUB)
    _write_exe(bin_dir / "tar", TAR_STUB)
    _write_exe(bin_dir / "aliyun", ALIYUN_STUB)
    return script, sandbox, bin_dir


def _run(tmp_path: Path, responses, *, script_text=None, timeout_seconds="4", extra_env=None):
    """跑脚本；`responses` = describe 调用依次回放的 JSON（用尽后重复最后一个）。"""
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    for i, r in enumerate(responses, start=1):
        (state / f"resp-{i}").write_text(r, encoding="utf-8")
    (state / "resp-last").write_text(responses[-1], encoding="utf-8")
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    log = tmp_path / "aliyun.log"
    log.write_text("", encoding="utf-8")
    script, sandbox, bin_dir = _prepare(tmp_path, script_text)

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_STEP_SUMMARY": str(summary),
        "ALIYUN_LOG": str(log),
        "ALIYUN_STATE": str(state),
        "STUB_SANDBOX": str(sandbox),
        "SWAS_DEPLOY_TIMEOUT_SECONDS": timeout_seconds,
        "SWAS_CLI_TIMEOUT_SECONDS": "3",
        "SWAS_POLL_INTERVAL_SECONDS": "1",
        "SWAS_RETRY_PAUSE_SECONDS": "0",
        **(extra_env or {}),
    }
    proc = subprocess.run(
        ["bash", str(script), "i-stub", "cn-hangzhou", "ak", "sk", "u", "p", "sha-new"],
        env=env, capture_output=True, text=True, timeout=180,
    )
    return proc.returncode, proc.stdout + proc.stderr, summary.read_text(encoding="utf-8"), log.read_text(encoding="utf-8")


def _describe_invocations(log: str) -> int:
    return sum(1 for ln in log.splitlines() if "describe-invocation-result" in ln)


def _run_command_contents(log: str) -> list[str]:
    return [ln for ln in log.splitlines() if "run-command" in ln]


# ── 红证 ①：注入「调用永不返回」 ──────────────────────────────────────────

def test_hung_invocation_fails_fast_and_does_not_poll_forever(tmp_path):
    """① **红证**：桩恒返回 `Running`（模拟"调用永不返回"）⇒ 必红，且**在墙钟上界内**结束。

    旧实现（180 次 × 20s，且单次 CLI 无上界）在这里会跑满 60 分钟；新实现必须
    在 `SWAS_DEPLOY_TIMEOUT_SECONDS` 附近退出 —— 这就是"不占锁"的机制：脚本 exit 1
    ⇒ job 失败 ⇒ `deploy-*` 的 concurrency 组释放。
    """
    import time

    t0 = time.monotonic()
    rc, out, summary, log = _run(tmp_path, [_swas_json("Running", None)], timeout_seconds="4")
    elapsed = time.monotonic() - t0

    assert rc != 0, f"恒 Running 时脚本仍然退出 0（rc={rc}）⇒ 无限轮询未修好\n{out[-800:]}"
    assert "硬超时" in out, f"超时路径没有显式报「硬超时」：\n{out[-800:]}"
    assert "硬超时" in summary, "超时未落 job summary（CI 日志会被截断）"
    assert elapsed < 60, f"恒 Running 时耗时 {elapsed:.1f}s —— 远超墙钟上界（应为 ~4s 量级）"
    assert _describe_invocations(log) >= 2, "桩没被轮询到 ≥2 次 ⇒ 这条红证没真正走到轮询循环"


def test_timeout_path_reports_recovery_manual(tmp_path):
    """① 超时后必须给**可执行的恢复手册**（`gh run cancel` / `rerun`），不让人自己猜。"""
    rc, out, summary, _ = _run(tmp_path, [_swas_json("Running", None)], timeout_seconds="4")
    assert rc != 0
    blob = out + summary
    assert "gh run cancel" in blob, "超时告警里没有 `gh run cancel`（清并发锁的确切命令）"
    assert "gh run rerun" in blob, "超时告警里没有 `gh run rerun`（恢复推进的确切命令）"


# ── 红证 ②：注入已知错误文本 ⇒ summary 里能找到原文 ────────────────────────

def test_known_error_text_is_readable_in_stdout_and_summary(tmp_path):
    """② **红证**：远端输出是 base64，注入一段已知错误文本 ⇒ stdout 与 summary 里都能找到**原文**。"""
    rc, out, summary, _ = _run(
        tmp_path, [_swas_json("Success", f"== 3. 健康检查 ==\n{KNOWN_TEXT}\n")],
    )
    assert rc == 0, f"Success 场景脚本应退出 0（rc={rc}）\n{out[-800:]}"
    assert KNOWN_TEXT in out, f"解码后的原文没出现在 stdout：\n{out[-800:]}"
    assert KNOWN_TEXT in summary, f"解码后的原文没落进 job summary：\n{summary[-800:]}"
    assert "== 3. 健康检查 ==" in summary, "远端输出的**上下文行**没落进 summary（summary 必须是完整输出）"


def test_base64_is_never_printed_as_the_log(tmp_path):
    """② 不许把 base64 当"日志"：base64 形态**不得**出现在 summary 里。"""
    payload = f"== 3. 健康检查 ==\n{KNOWN_TEXT}\n"
    encoded = b64encode(payload.encode()).decode("ascii")
    rc, out, summary, _ = _run(tmp_path, [_swas_json("Success", payload)])
    assert rc == 0
    assert encoded not in summary, "summary 里出现 base64 原文 —— 解码没生效（把 base64 当日志）"
    assert encoded not in out, "stdout 里出现 base64 原文 —— 解码没生效"


def test_non_base64_output_is_printed_verbatim(tmp_path):
    """② 容错：非 base64 的 `Output` 必须**原样打印**（解码失败不得吞信息）。"""
    raw = "这不是 base64：plain-text-output-4767 ✓"
    doc = json.dumps({"InvocationResult": {"InvocationStatus": "Success", "Output": raw}})
    rc, out, summary, _ = _run(tmp_path, [doc])
    assert rc == 0
    assert raw in out, f"非 base64 输出没有原样打印：\n{out[-600:]}"
    assert raw in summary, "非 base64 输出没有落 summary"


def test_missing_output_field_still_prints_the_json(tmp_path):
    """② 容错：连 `Output` 字段都没有 ⇒ 打印原始 JSON（不静默吞掉诊断信息）。"""
    doc = json.dumps({"InvocationResult": {"InvocationStatus": "Success", "ErrorInfo": "stub-no-output"}})
    rc, out, summary, _ = _run(tmp_path, [doc])
    assert rc == 0
    assert "stub-no-output" in out + summary, "无 Output 字段时原始 JSON 被吞掉了"


def test_decoding_criterion_has_discriminating_power(tmp_path):
    """② **反向红证**：把「解码」注入掉（改成不解码）⇒ 上面那条判据**必红**。

    不会红的断言 = 空断言。这里证明「原文出现在 summary 里」这条判据真的能判红。
    """
    real = read_script()
    anchor = "base64.b64decode(out.strip(), validate=True)"
    assert anchor in real, f"注入点已漂移（判据过期）：{anchor!r}"
    broken = real.replace(anchor, "out.strip().encode()")
    assert broken != real, "注入未生效（判据自证）"

    payload = f"== 3. 健康检查 ==\n{KNOWN_TEXT}\n"
    rc, out, summary, _ = _run(tmp_path, [_swas_json("Success", payload)], script_text=broken)
    assert rc == 0, "注入后脚本应仍能跑完（只去掉解码）"
    assert KNOWN_TEXT not in summary, (
        "去掉解码后原文仍出现在 summary 里 ⇒ 该判据没有判别力（空断言）"
    )


# ── 红证 ③：注入「新容器健康检查失败」⇒ 回滚到上一个可用镜像 ──────────────

def _failed_with_prev(prev_tag: str) -> str:
    body = (
        "== 2. 拉取镜像（tag=sha-new）==\n"
        " Container migao-deploy-admin-api-1  Recreated\n"
        "== 3. 健康检查 ==\n"
        "  admin-api -> 000 (retry 1)\n"
        "  ❌ admin-api 健康检查未通过（重试 10 次仍未就绪）\n"
        f"{KNOWN_TEXT}\n"
        f"PREV_GOOD_TAG={prev_tag}\n"
    )
    return _swas_json("Failed", body)


def test_health_check_failure_retries_then_rolls_back_to_previous_tag(tmp_path):
    """③ **红证**：注入「新容器健康检查失败」⇒ 重试 1 次 ⇒ 回滚到**上一个可用 tag** ⇒ 显式告警。

    判据（可验证的"旧容器仍在服务"）：
      · 第 1、2 次 `run-command` 带的是**新** tag（首次 + 重试）；
      · 第 3 次 `run-command` 带的是**旧** tag（`PREV_GOOD_TAG`）⇒ 回滚真的发出去了；
      · 脚本仍 exit 非零（部署本身失败），且 summary 里有 `::error::` 级显式告警 + 已知错误原文。
    """
    rc, out, summary, log = _run(
        tmp_path,
        [_failed_with_prev("sha-old"), _failed_with_prev("sha-old"), _swas_json("Success", "== 回滚完成 ==\n")],
        timeout_seconds="30",
    )
    contents = _run_command_contents(log)
    assert len(contents) == 3, f"期望 3 次 run-command（首次 + 重试 + 回滚），实际 {len(contents)} 次：\n{log}"
    assert "sha-new" in contents[0], "第 1 次调用不是新 tag"
    assert "sha-new" in contents[1], f"第 2 次调用（自动重试）不是新 tag：\n{contents[1][:400]}"
    assert "sha-old" in contents[2], (
        f"第 3 次调用（回滚）没有带上一个可用 tag `sha-old` ⇒ 失败后旧容器不会回来：\n{contents[2][:400]}"
    )
    assert "sha-new" not in contents[2], "回滚调用里仍带新 tag（回滚没生效）"
    assert rc != 0, "部署失败时脚本必须退出非零（不许把失败改 skip）"
    assert "::error::" in out, "回滚后没有 `::error::` 显式告警"
    err_lines = [ln for ln in out.splitlines() if "::error::" in ln]
    assert any("sha-old" in ln for ln in err_lines), (
        f"`::error::` 告警没有**点名回滚目标 tag**（实测踩到：用回滚尝试重置后的变量会渲染成空串）\n{err_lines}"
    )
    assert "sha-old" in summary, "summary 里没有回滚目标 tag（事后无法追溯环境回到了哪个版本）"
    assert KNOWN_TEXT in summary, "summary 里找不到注入的已知错误原文（真错仍然看不见）"


def test_retry_then_rollback_failure_alerts_loudly(tmp_path):
    """③ 回滚也失败 ⇒ 必须**显式告警**"环境可能处于坏状态 + 人工介入"，而不是让人从 502 反推。"""
    rc, out, summary, log = _run(
        tmp_path,
        [_failed_with_prev("sha-old"), _failed_with_prev("sha-old"), _failed_with_prev("sha-old")],
        timeout_seconds="30",
    )
    assert rc != 0
    assert len(_run_command_contents(log)) == 3, "回滚调用没发生"
    blob = out + summary
    assert "::error::" in blob, "没有 `::error::` 告警"
    assert "回滚" in blob and "失败" in blob, f"告警没说清「回滚也失败」：\n{blob[-900:]}"
    assert "人工介入" in blob, "告警没有要求人工介入"


def test_no_rollback_target_alerts_instead_of_pretending(tmp_path):
    """③ 没有回滚点（首次部署 / 取不到 tag）⇒ **显式告警**，不许假装回滚成功。"""
    rc, out, summary, log = _run(
        tmp_path,
        [
            _swas_json("Failed", f"PREV_GOOD_TAG=\n{KNOWN_TEXT}\n"),
            _swas_json("Failed", f"PREV_GOOD_TAG=\n{KNOWN_TEXT}\n"),
        ],
        timeout_seconds="30",
    )
    assert rc != 0
    assert len(_run_command_contents(log)) == 2, (
        f"没有回滚点时不应用旧 tag 再调一次 deploy（实际 {len(_run_command_contents(log))} 次）"
    )
    assert "::error::" in out + summary, "没有回滚点时没有显式告警"


def test_prev_tag_equal_to_current_tag_is_not_a_rollback(tmp_path):
    """③ 回滚点 == 本次 tag（同 sha 重跑）⇒ 回滚无意义，必须只告警不空跑。"""
    rc, out, summary, log = _run(
        tmp_path,
        [_failed_with_prev("sha-new"), _failed_with_prev("sha-new")],
        timeout_seconds="30",
    )
    assert rc != 0
    assert len(_run_command_contents(log)) == 2, (
        "PREV tag 与本次 tag 相同时不应再调一次 deploy（回滚无意义）"
    )
    assert "::error::" in out + summary


def test_rollback_criterion_has_discriminating_power(tmp_path):
    """③ **反向红证**：把「用 PREV tag 回滚」注入掉 ⇒ 上面那条判据必红。"""
    real = read_script()
    anchor = 'deploy_attempt "$ROLLBACK_TAG"'
    assert anchor in real, f"注入点已漂移（判据过期）：{anchor!r}"
    broken = real.replace(anchor, 'echo "（注入：不回滚）"')
    assert broken != real, "注入未生效（判据自证）"
    rc, out, summary, log = _run(
        tmp_path,
        [_failed_with_prev("sha-old"), _failed_with_prev("sha-old")],
        script_text=broken, timeout_seconds="30",
    )
    assert rc != 0
    assert len(_run_command_contents(log)) == 2, (
        "注入掉回滚后仍然出现第 3 次调用 ⇒ 该判据没有判别力（空断言）"
    )


# ══════════════════════════════════════════════════════════════════════════
# 四、防漂移：脚本本身仍可被 bash 解析（改坏 shell 语法是"停掉所有人的部署"的最短路径）
# ══════════════════════════════════════════════════════════════════════════

def test_script_is_syntactically_valid():
    """`bash -n` 语法自检（本单改的是全流水线基建，语法错会停掉所有人的部署）。"""
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, f"脚本语法错误：\n{proc.stderr}"


def test_script_has_no_shared_tmp_workspace_regression():
    """#4625 的并发隔离判据不得回退（本单在 bootstrap 里加了 PREV tag 探测）。"""
    text = read_script()
    assert "/tmp/migao-src" not in text, "共享固定路径回归（issue #4625）"
    assert "mktemp -d" in text and "mktemp" in text, "per-run 唯一路径回归（issue #4625）"
    assert shutil.which("bash"), "环境里没有 bash"


# ══════════════════════════════════════════════════════════════════════════
# 五、`deploy-reconcile.yml` 与新逻辑的**打架**（issue #4767 ③ 的射程内）
#
# 事故记录：「对账补偿会反复重新触发部署 ⇒ 覆盖手工回滚（实测 2 次）」。两条机制：
#   (a) 对账基准取了 `GITHUB_SHA`，而 PR 事件下它是 **PR 的 merge commit**（不是 main HEAD）
#       ⇒ `sha-<7>` 镜像**永远不存在** ⇒ 每个 PR opened 都重新 dispatch 三条部署；
#   (b) 没有断路器：同一个**已失败**的 commit 会被每 20 分钟自动重试一次
#       ⇒ 把「已回滚到上一个可用镜像」的环境**再打挂一次**。
# ══════════════════════════════════════════════════════════════════════════

RECONCILE = "deploy-reconcile.yml"
RECONCILE_STEP = "Reconcile deploys"


def reconcile_run() -> str:
    """从 workflow 里**逐字取出**对账 step 的脚本（取不到 ⇒ 显式失败，不是"通过"）。"""
    path = WORKFLOWS_DIR / RECONCILE
    assert path.is_file(), f"反空跑锚点：workflow 不存在 → {path}"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = doc["jobs"]["reconcile"]["steps"]
    for s in steps:
        if s.get("name") == RECONCILE_STEP:
            body = s.get("run", "")
            assert body.strip(), f"{RECONCILE} 的 `{RECONCILE_STEP}` 没有 run 脚本"
            return body
    raise AssertionError(f"反空跑锚点：{RECONCILE} 里找不到 step `{RECONCILE_STEP}`（判据已过期）")


def check_reconcile_baseline(text: str) -> None:
    assert re.search(r"^HEAD_SHA=\$\(git rev-parse HEAD\)$", text, re.M), (
        "对账基准必须取 **checkout 出来的 main HEAD**（`HEAD_SHA=$(git rev-parse HEAD)`）"
    )
    assert re.search(r'^HEAD7="\$\{HEAD_SHA::7\}"$', text, re.M), "HEAD7 必须由 HEAD_SHA 派生"
    assert 'HEAD7="${GITHUB_SHA::7}"' not in text, (
        "对账基准又回到了 `GITHUB_SHA`：`pull_request` 事件下它是 **PR 的 merge commit**（不是 main HEAD）"
        "⇒ `sha-<7>` 镜像永远不存在 ⇒ 每个 PR opened 都重新 dispatch 三条部署（覆盖手工回滚）"
    )


def check_reconcile_breaker(text: str) -> None:
    assert re.search(r'gh run list --workflow "\$wf" --branch main --limit 30', text), (
        "断路器必须查对应 deploy workflow 的 run 历史"
        "（`gh run list --workflow \"$wf\" --branch main --limit 30`；`$wf` 由逐服务调用传入）"
    )
    assert "--json headSha,conclusion" in text, "断路器必须按 `headSha,conclusion` 取数"
    # issue #4827：断路器的判据必须是**被部署的那个 commit** = **main HEAD**。
    # dispatch 出去后 deploy 构建的 tag 是 `sha-${GITHUB_SHA::7}`（各 deploy workflow 的
    # `Resolve image tag`）⇒ 「被部署的 commit」就是 main HEAD；换成 CODE_SHA（最后一个改代码
    # 的 commit）会去查一个 dispatch **永远构建不出来**的 tag ⇒ 断路器结构性永不触发
    # （那不是加固，是把 #4767 的护栏废掉）。
    assert '--arg s "$HEAD_SHA"' in text, (
        "断路器的 head_sha 判据必须绑定 **main HEAD**（`--arg s \"$HEAD_SHA\"`）"
    )
    assert "select(.headSha == $s)" in text, (
        "断路器必须只匹配**同一个 head_sha**（不是「最近一次失败」这种模糊判据）"
    )
    assert "CODE_SHA" not in text, (
        "断路器/镜像基准又出现了 `CODE_SHA`：dispatch 只会构建 `sha-<main HEAD>`，"
        "按「最后一个改代码的 commit」判缺失 ⇒ 那个 tag 永远建不出来 ⇒ 每个后续 docs 提交"
        "都重复 dispatch（3 服务全量重建重部署：502 窗口 + 覆盖回滚，issue #4827）"
    )
    assert re.search(r'\[ "\$last" = "failure" \]; then', text), (
        "断路器必须以 `conclusion == failure` 为唯一触发条件"
    )
    m = re.search(r'if \[ "\$last" = "failure" \]; then(.*?)\n\s*fi\n', text, re.S)
    assert m, "断路器的 `if [ \"$last\" = failure ]` 分支结构变了（判据已过期）"
    branch = m.group(1)
    # 命中分支里只允许出现「人工重跑」提示（`echo`），**不许**真的 dispatch
    dispatch_calls = [
        ln.strip() for ln in branch.splitlines()
        if "gh workflow run" in ln and not ln.strip().startswith("echo")
    ]
    assert "SKIPPED=$((SKIPPED + 1))" in branch and not dispatch_calls, (
        "断路器命中后必须**跳过该服务的补部署**（命中分支里不许出现真的 `gh workflow run`）"
    )
    assert '2>/dev/null || echo "[]"' in text, (
        "断路器必须 **fail-open**：`gh run list` 查询失败 ⇒ 取空列表（本检查出错绝不停掉对账）"
    )
    assert '// ""' in text, (
        "断路器必须 **fail-open**：无记录 / 结论非 failure（含 cancelled）⇒ 取空串 ⇒ 照旧补部署"
    )


def test_reconcile_baseline_is_checked_out_main_head():
    """(a) 对账基准 = main HEAD，不是 `GITHUB_SHA`（PR 事件下后者是 merge commit）。"""
    check_reconcile_baseline(reconcile_run())


def test_reconcile_has_failure_circuit_breaker():
    """(b) 同一 commit 的部署**已失败过** ⇒ 不自动补部署（fail-open）。"""
    check_reconcile_breaker(reconcile_run())


def test_reconcile_baseline_criterion_has_discriminating_power():
    """(a) 反向红证：把基准注入回 `GITHUB_SHA` ⇒ 判据必红。"""
    real = reconcile_run()
    check_reconcile_baseline(real)  # 前提：真文本先绿
    broken = real.replace('HEAD7="${HEAD_SHA::7}"', 'HEAD7="${GITHUB_SHA::7}"')
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_reconcile_baseline(broken)


def test_reconcile_breaker_criterion_has_discriminating_power():
    """(b) 反向红证：把 head_sha 判据换成「任意 run」⇒ 判据必红（模糊判据会误跳过）。"""
    real = reconcile_run()
    check_reconcile_breaker(real)
    broken = real.replace("select(.headSha == $s)", "select(true)")
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_reconcile_breaker(broken)


def test_reconcile_breaker_baseline_criterion_has_discriminating_power():
    """(b) 反向红证：把基准退回 `CODE_SHA` ⇒ 判据必红（会查一个永不存在的 tag）。"""
    real = reconcile_run()
    check_reconcile_breaker(real)
    broken = real.replace('--arg s "$HEAD_SHA"', '--arg s "$CODE_SHA"')
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_reconcile_breaker(broken)


def test_reconcile_keeps_its_safety_gates():
    """安全纪律：对账 workflow 的门禁与权限不得被改动。"""
    doc = yaml.safe_load((WORKFLOWS_DIR / RECONCILE).read_text(encoding="utf-8"))
    job = doc["jobs"]["reconcile"]
    assert job.get("timeout-minutes"), f"{RECONCILE} 的 reconcile job 丢了 `timeout-minutes`"
    assert doc.get("permissions") == {"contents": "read", "actions": "write"}, (
        f"{RECONCILE} 的 permissions 被改动"
    )
    assert "continue-on-error" not in job, f"{RECONCILE} 出现 `continue-on-error`（削弱门禁）"

# ══════════════════════════════════════════════════════════════════════════
# 六、「兜底静默失效」（issue #4827）：对账**不许有任何静默短路**，判定必须可观测
#
# 事故（2026-09-20 07:32:04 run 35497126164，`workflow_dispatch`，main HEAD `593504de9`）：
# 报 **success 且零 dispatch**，而 3 个提交之前、5 分钟前的 `634b53f90`（fix(api) #4641）
# 的镜像**一个都没构建**（部署触发被吞）。
#
# 🔴 **真根因不是「HEAD 恰好是 docs 提交」，而是结构性永远跳过**：旧 step
# `Schedule code-change check` 的判据是
#   `if git log --oneline -10 --name-only origin/main | grep -qE "…"; then CODE_CHANGED=1; fi`
# 而 GitHub 的 `shell: bash` 本身就是 `bash --noprofile --norc -e -o pipefail`（该 step 另
# 声明了 `set -euo pipefail`）⇒ `grep -q` 首个命中即退出并关闭管道 ⇒ `git log` 死于
# **SIGPIPE(141)** ⇒ **pipefail 把整条管道的状态取为 141** ⇒ `if` 取**假**分支 ⇒
# `CODE_CHANGED` **恒为 0**（本地逐字复现 40/40 全 0；去掉 pipefail 同一条命令转 1；
# 直接读管道状态 = 141）⇒ 写 `SKIP_RECONCILE=1` ⇒ `Reconcile deploys` 被
# `if: env.SKIP_RECONCILE != '1'` **整步跳过** ⇒ **每一次** schedule/workflow_dispatch
# 对账都是 success + 零动作 —— 这才是「本会话 4 次全 success、每次都要人手动
# `gh workflow run`」的机制。
# （issue 原文猜的「HEAD 无代码改动」是**假结论**：`593504de9` 往前 10 个提交里有 24 个
#  代码路径文件。执行式复现见 `tests/unit_ci_workflows/test_reconcile_no_silent_skip.py`。）
#
# 「静默」有三个来源，本节逐个钉死，**每条都带反向红证**（防空断言）：
#   ⓐ 短路（`SKIP_RECONCILE` / step 的 `if:`）⇒ 整步不跑却报 success；
#   ⓑ `pipefail` + `grep -q` 陷阱（**产生** ⓐ 的机制）⇒ 连机制一起钉；
#   ⓒ 「跑了但没说为什么没动」⇒ 每个判定分支都要 echo + 落 `$GITHUB_STEP_SUMMARY`。
# ══════════════════════════════════════════════════════════════════════════

# 对账项名 → deploy/发布 workflow（真值源；`check_reconcile_paths_match_deploy_triggers` 据此反查）
# ⚠️ 这是「必须逐服务对账的腿」的**单一真值源**：往 `deploy-reconcile.yml` 加/删一条
#    `reconcile_one` 而不同时改这里（或反之）⇒ `set(calls) == set(SVC_TO_DEPLOY_WORKFLOW)` 判红
#    ⇒ 「加了腿但没登记 / 登记了腿但没接线」两种半成品都进不来（issue #5001 的形态）。
SVC_TO_DEPLOY_WORKFLOW = {
    "admin-api": "deploy-admin-api.yml",
    "ai-agent-service": "deploy-ai-agent-service.yml",
    "admin-web": "deploy-frontend.yml",
    # worker-h5（issue #5001）：**静态落地面腿**（发布 `frontend/worker-h5/**` 到静态根 `w/`），
    # 无镜像 ⇒ 对账走漂移判据 ②；它的触发面只有 `push: main` + `workflow_dispatch`，而被
    # `GITHUB_TOKEN` 合并的 auto-merge **吞掉那个 push** ⇒ 缺了这条腿就等于「改动静默不发布」。
    "worker-h5": "worker-h5-publish.yml",
}


def reconcile_job() -> dict:
    doc = yaml.safe_load((WORKFLOWS_DIR / RECONCILE).read_text(encoding="utf-8"))
    return doc["jobs"]["reconcile"]


def reconcile_steps() -> list:
    return reconcile_job()["steps"]


def workflow_text() -> str:
    return (WORKFLOWS_DIR / RECONCILE).read_text(encoding="utf-8")


def non_comment_lines(text: str) -> str:
    """只保留**可执行**行（丢掉整行注释）——注释里解释旧机制不算「用了它」。"""
    return "\n".join(
        ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
    )


def check_reconcile_has_no_short_circuit(steps: list, whole: str) -> None:
    """ⓐ 对账 step 不得被任何短路跳过；那个跳过标记的**概念**必须整体从可执行行里消失。"""
    reconcile = [s for s in steps if s.get("name") == RECONCILE_STEP]
    assert reconcile, f"反空跑锚点：找不到 step `{RECONCILE_STEP}`"
    assert reconcile[0].get("if") is None, (
        f"对账 step 又带 `if:`（{reconcile[0].get('if')!r}）—— 条件短路会让它**不跑却报 success**"
        "（issue #4827：兜底没兜住，且是静默的）"
    )
    code = non_comment_lines(whole)
    assert "SKIP_RECONCILE" not in code, (
        "workflow 的可执行行里又出现短路标记：标记一回来，「静默 success」就会跟着回来（issue #4827）"
    )
    assert "gh pr view" not in code, (
        "又出现 PR 文件表 path 过滤：对账跑的是 **main HEAD**，与「触发它的那个 PR 是不是纯"
        "文档」无关（issue #4827）"
    )


# `pipefail` 环境下不许把 `grep -q` 放管道里当条件（SIGPIPE ⇒ 恒假分支）
# ⚠️ 不能只匹配 `-q`：真实写法是 `grep -qE "…"`（组合旗标）⇒ 认「旗标簇里含 q」。
GREP_FLAG_CLUSTER = re.compile(r"\bgrep\s+(?:-[A-Za-z]+\s+)*-([A-Za-z]+)")


def grep_q_as_pipe_consumer(body: str):
    """返回「把 `grep -q…` 当**管道消费者**」的那一行（没有则 None）。"""
    for line in body.splitlines():
        for m in GREP_FLAG_CLUSTER.finditer(line):
            if "|" not in line[: m.start()]:
                continue  # 该 grep 之前没有管道 ⇒ 不是消费者
            if "q" in m.group(1).lower():
                return line.strip()
    return None


def check_reconcile_no_pipefail_grep_q_trap(steps: list) -> None:
    """ⓑ `-o pipefail` + `grep -q` 早退 ⇒ 生产者 SIGPIPE(141) ⇒ `if` 恒取假分支（真根因）。"""
    for s in steps:
        line = grep_q_as_pipe_consumer(non_comment_lines(s.get("run", "") or ""))
        assert line is None, (
            f"step `{s.get('name')}` 里出现 `… | grep -q …`：GitHub 的 `shell: bash` 带 "
            "`-eo pipefail`，`grep -q` 早退会把生产者的 SIGPIPE(141) 变成整条管道的退出码 ⇒ "
            f"`if` 恒取假分支（#4827 的真根因）→ {line!r}"
        )


def check_reconcile_image_baseline_is_main_head(text: str) -> None:
    """镜像基准必须是 **main HEAD**：dispatch 出去构建的 tag 就是 `sha-<main HEAD>`。"""
    assert re.search(r'^\s*local image="[^\n]*:sha-\$\{HEAD7\}"$', text, re.M), (
        "镜像名必须由 `HEAD7`（= main HEAD 前 7 位）派生；`CODE7`/`CODE_SHA` 那种「最后一个"
        "改代码的 commit」永远建不出对应 tag ⇒ 每个后续 docs 提交都重复 dispatch"
        "（3 服务全量重建重部署 = #3235 的 502 窗口 + #4767 ③ 的覆盖回滚风险）"
    )
    assert "CODE_SHA" not in text and "CODE7" not in text, "又出现 `CODE_SHA`/`CODE7` 基准（issue #4827）"
    assert "git rev-list" not in text, (
        "又用 `git rev-list -1 HEAD -- <paths>` 当基准：depth=1 浅克隆下它对 docs HEAD 返回空 "
        "⇒ 退化成裸 HEAD，等于没改（issue #4827）"
    )


def check_reconcile_drift_criterion(text: str) -> None:
    """有没有东西要部署，必须由**漂移判据**决定（自上次成功部署 P 起有无代码改动）。"""
    assert re.search(
        r"^\s*p=\$\(printf .*select\(\.conclusion == \"success\"\).*headSha", text, re.M
    ), (
        "缺「上次成功部署的 commit」的取数（`conclusion == \"success\"` 的最新 run 的 headSha）"
        "—— 没有它，「docs 提交不空转 dispatch」就无从判定（issue #4827 / #3235）"
    )
    assert re.search(r'^\s*drift=\$\(git log --oneline -1 "\$\{p\}\.\.HEAD" -- "\$\{pathspec\[@\]\}"', text, re.M), (
        "缺漂移判据本体：`git log --oneline -1 \"${p}..HEAD\" -- \"${pathspec[@]}\"`（空 = 无漂移）"
    )
    assert 'pathspec=( "$svc_path" )' in text, "缺少按服务取代码路径的 pathspec 组装"
    assert "declare -A" not in text, (
        "对账正文用了 bash4 关联数组（`declare -A`）：macOS 自带 bash 3.2 跑不起来 ⇒ "
        "执行式守护测试退化成 CI-only（改用函数参数，见 step 内的注释）"
    )
    # ✅ `git log` 的输出只进**命令替换**（不是 `| grep -q`）⇒ 不触发 ⓑ 的陷阱
    assert "GIT_FAIL" not in text and "?git-failed" in text, (
        "git 判不了时必须走 fail-open（`?git-failed` ⇒ 按兜底补部署 + ::warning::），不许静默放过"
    )
    # `fetch-depth: 0` 是漂移判据的**前提**（P 必须可达）
    checkout = [s for s in reconcile_steps() if str(s.get("uses", "")).startswith("actions/checkout")]
    assert checkout, f"{RECONCILE} 里找不到 actions/checkout"
    assert checkout[0].get("with", {}).get("fetch-depth") == 0, (
        "checkout 必须 `fetch-depth: 0`：depth=1 时 P 不可达 ⇒ `git log P..HEAD` 报错 ⇒ "
        "判据退化成「每次都判有改动」⇒ 每个 docs 提交都空转 dispatch（issue #4827）"
    )


# 逐服务调用的形态：`reconcile_one <svc> <deploy workflow> <代码路径> <排除项或 "">`
RECONCILE_CALL = re.compile(r'^reconcile_one\s+(\S+)\s+(\S+)\s+(\S+)\s+(?:"([^"]*)"|(\S+))\s*$', re.M)


def parse_reconcile_calls(text: str) -> dict:
    """解析逐服务调用行（`declare -A` 已被排除 ⇒ 函数参数就是唯一真值）。"""
    calls = {}
    for m in RECONCILE_CALL.finditer(text):
        svc, wf, path, excl_q, excl_b = m.groups()
        assert svc not in calls, f"`reconcile_one {svc}` 出现了两次（判据已过期）"
        calls[svc] = {"wf": wf, "path": path, "excl": excl_q if excl_q is not None else excl_b}
    # 条数由**登记册**派生（不写死数字）：写死会让「加了一条腿」与「登记册」两处投影分叉
    # ——#5001 的病根正是「登记/接线只有一处」（当时写死 3，worker-h5 落在两处之外）。
    assert len(calls) == len(SVC_TO_DEPLOY_WORKFLOW), (
        f"逐服务调用数必须等于登记册条目数 {len(SVC_TO_DEPLOY_WORKFLOW)} → 实得 {sorted(calls)}"
    )
    return calls


def check_reconcile_paths_match_deploy_triggers(text: str) -> None:
    """逐服务代码路径必须与各自 deploy workflow 的 `on.push.paths` **逐字对齐**。

    这是本单最容易悄悄写错的地方（原稿的 `apps`/`packages` 根本不是任何 deploy 的触发路径），
    所以判据**反查真值源**（deploy workflow 的 `on.push.paths`），不写死常量。
    """
    calls = parse_reconcile_calls(text)
    assert set(calls) == set(SVC_TO_DEPLOY_WORKFLOW), f"服务集合不符：{sorted(calls)}"
    for svc, wf in SVC_TO_DEPLOY_WORKFLOW.items():
        assert calls[svc]["wf"] == wf, f"{svc} 的 deploy workflow 应为 `{wf}`（实得 {calls[svc]['wf']!r}）"
        assert (WORKFLOWS_DIR / wf).is_file(), f"反空跑锚点：{wf} 不存在（判据已过期）"
        doc = yaml.safe_load((WORKFLOWS_DIR / wf).read_text(encoding="utf-8"))
        # ⚠️ YAML 1.1 里裸 `on` 会被解析成布尔 True（PyYAML 已知坑）⇒ 两种键都试
        on = doc.get("on")
        if on is None:
            on = doc.get(True)
        assert isinstance(on, dict) and "push" in on, f"{wf} 的 `on.push` 结构变了（判据已过期）"
        paths = [str(p) for p in on["push"]["paths"]]
        includes = [p for p in paths if not p.startswith("!")]
        excludes = [p.lstrip("!") for p in paths if p.startswith("!")]
        assert includes, f"反空跑锚点：{wf} 没有 `on.push.paths` 正向项"
        assert calls[svc]["path"] in [p.split("/**")[0] for p in includes], (
            f"reconcile 里 {svc} 的代码路径 {calls[svc]['path']!r} 与 `{wf}` 的 on.push.paths "
            f"{includes} 不一致（path 对齐错 ⇒ 要么漏补真漂移，要么空转 dispatch）"
        )
        for ex in excludes:
            prefix = ex.split("/**")[0]
            assert calls[svc]["excl"] == f":(exclude){prefix}", (
                f"`{wf}` 的排除项 {prefix!r} 没在 reconcile 里体现（实得 {calls[svc]['excl']!r}）"
            )


def check_reconcile_decision_is_observable(text: str) -> None:
    """ⓒ 每个判定分支都必须把**依据**写进 `$GITHUB_STEP_SUMMARY`（不许静默 success）。"""
    assert "GITHUB_STEP_SUMMARY" in text, "对账结论没落 job summary ⇒ 后来人看不出它为什么没动"
    for branch, needle in (
        ("断路器命中", "⛔ ${svc}：main HEAD ${HEAD7} 的部署**已失败过**"),
        ("镜像已存在", "✅ ${svc} 镜像 ${image} 已存在"),
        ("无漂移", "✅ ${svc}：自上次成功部署 ${p:0:7} 起"),
        ("镜像缺失→dispatch", "⚠️ ${svc} 镜像 ${image} 缺失且 HEAD 的代码状态未部署"),
    ):
        assert needle in text, f"缺少「{branch}」分支的日志（判据已过期？）"
    assert text.count('>> "$SUMMARY"') >= 6, (
        "落 summary 的次数不足：表头 + 4 类判定依据（断路器/镜像已存在/无漂移/dispatch）+ 结论"
        "都要写（issue #4827）"
    )
    assert "**结论**：dispatch=${MISSING}" in text, "缺结论行（dispatch=/无漂移=/断路器跳过=/判定失败=）"
    assert "::notice::" in text and "::warning::" in text, (
        "无 dispatch 时要有 `::notice::` 总判定、判据不可用时要 `::warning::` —— 都要显式出声"
    )


def test_reconcile_has_no_silent_short_circuit():
    """ⓐ 对账不得被任何短路跳过（事故 35497126164 的形态）。"""
    check_reconcile_has_no_short_circuit(reconcile_steps(), workflow_text())


def test_reconcile_has_no_pipefail_grep_q_trap():
    """ⓑ `-o pipefail` + `grep -q` 陷阱不得复现（事故 35497126164 的**真根因**）。"""
    check_reconcile_no_pipefail_grep_q_trap(reconcile_steps())


def test_reconcile_image_baseline_is_main_head():
    """镜像判定基准 = main HEAD（不是「最后一个改代码的 commit」）。"""
    check_reconcile_image_baseline_is_main_head(reconcile_run())


def test_reconcile_uses_drift_criterion_not_commit_count():
    """「要不要补部署」由漂移判据（自上次成功部署起有无代码改动）决定，不是「最近 10 个提交」。"""
    check_reconcile_drift_criterion(reconcile_run())


def test_reconcile_paths_align_with_deploy_triggers():
    """逐服务代码路径与各 deploy workflow 的 `on.push.paths` 逐字对齐（反查真值源）。"""
    check_reconcile_paths_match_deploy_triggers(reconcile_run())


def test_reconcile_decision_is_observable_in_summary():
    """ⓒ 不 dispatch 时必须显式说明依据并落 summary（不许静默 success）。"""
    check_reconcile_decision_is_observable(reconcile_run())


# ── 反向红证（每条判据都必须会红，否则是空断言）─────────────────────────────

def test_reconcile_short_circuit_criterion_has_discriminating_power():
    """ⓐ 反向红证：把 `SKIP_RECONCILE` 短路注入回对账 step ⇒ 判据必红。"""
    steps, whole = reconcile_steps(), workflow_text()
    check_reconcile_has_no_short_circuit(steps, whole)  # 前提：真文本先绿
    idx = next(i for i, s in enumerate(steps) if s.get("name") == RECONCILE_STEP)
    broken = copy.deepcopy(steps)
    broken[idx]["if"] = "env.SKIP_RECONCILE != '1'"
    assert broken != steps, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_reconcile_has_no_short_circuit(broken, whole)
    # 短路标记本身也要有判别力（把写入语句注入回文本）
    with pytest.raises(AssertionError):
        check_reconcile_has_no_short_circuit(steps, whole + '\necho "SKIP_RECONCILE=1" >> "$GITHUB_ENV"\n')


def test_reconcile_pipefail_grep_q_criterion_has_discriminating_power():
    """ⓑ 反向红证：把 `git log … | grep -q` 注回 ⇒ 判据必红（并证明该写法确实恒假）。"""
    steps = reconcile_steps()
    check_reconcile_no_pipefail_grep_q_trap(steps)
    broken = copy.deepcopy(steps)
    body_step = next(s for s in broken if s.get("name") == RECONCILE_STEP)
    body_step["run"] = body_step["run"] + (
        '\nCODE_CHANGED=0\n'
        'if git log --oneline -10 --name-only HEAD | grep -qE "^(backend/admin-api)/"; then\n'
        '  CODE_CHANGED=1\n'
        'fi\n'
    )
    assert broken != steps, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_reconcile_no_pipefail_grep_q_trap(broken)


def test_reconcile_baseline_criterion_has_discriminating_power():
    """反向红证：把镜像基准退回 `CODE7` ⇒ 判据必红。"""
    real = reconcile_run()
    check_reconcile_image_baseline_is_main_head(real)
    broken = real.replace(':sha-${HEAD7}"', ':sha-${CODE7}"')
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_reconcile_image_baseline_is_main_head(broken)


def test_reconcile_drift_criterion_has_discriminating_power():
    """反向红证：删掉漂移判据（`git log P..HEAD`）⇒ 判据必红。"""
    real = reconcile_run()
    check_reconcile_drift_criterion(real)
    broken = real.replace('drift=$(git log --oneline -1 "${p}..HEAD"', 'drift=$(true')
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_reconcile_drift_criterion(broken)


def test_reconcile_path_alignment_criterion_has_discriminating_power():
    """反向红证：把 admin-web 的路径写成原稿的 `frontend`（过宽）⇒ 判据必红。"""
    real = reconcile_run()
    check_reconcile_paths_match_deploy_triggers(real)
    broken = real.replace(
        "reconcile_one admin-web deploy-frontend.yml frontend/admin-web",
        "reconcile_one admin-web deploy-frontend.yml frontend",
    )
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_reconcile_paths_match_deploy_triggers(broken)


def test_reconcile_worker_h5_leg_criterion_has_discriminating_power():
    """🔴 反向红证（issue #5001）：**删掉 worker-h5 那条对账腿** ⇒ 判据必红（防空断言）。

    这是本单的**实例判据**：worker-h5 曾经落在 `SVC_TO_DEPLOY_WORKFLOW` 之外 ⇒ 改了
    `frontend/worker-h5/**` 的 PR 经 auto-merge 合并后工人端**静默不发布**（线上文件仍是旧的，
    无红无告警）。本判据把「腿必须存在」变成会红的断言 —— 它红时可归因到「登记册里的腿没接线」，
    出口是可行动的（补回那一行，或从登记册里删掉该服务）。
    """
    real = reconcile_run()
    check_reconcile_paths_match_deploy_triggers(real)  # 前提：真文本先绿
    broken = re.sub(r"^reconcile_one worker-h5 .*\n", "", real, flags=re.M)
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_reconcile_paths_match_deploy_triggers(broken)


def test_reconcile_observability_criterion_has_discriminating_power():
    """ⓒ 反向红证：把落 summary 的语句全去掉 ⇒ 判据必红。"""
    real = reconcile_run()
    check_reconcile_decision_is_observable(real)
    broken = real.replace('>> "$SUMMARY"', '>> /dev/null')
    assert broken != real, "注入未生效（判据自证）"
    with pytest.raises(AssertionError):
        check_reconcile_decision_is_observable(broken)
