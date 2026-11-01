# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI / 流程结构类 L0 不变式统一挂 MC-012 ——
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""生产告警**触达**：三类事件（5xx / 证书到期 / 发布失败）必须能真的响（上线审计 P0-04，issue #8203）。

## 病（审计原文，逐字）

> 5xx 计数阈值 + 证书到期（P0-01）+ 发布失败（P0-02/P1-04）三类事件必须能真的响，落到一个有人看的通道；
> 当前只有腿本身红/绿，无告警触达。（`acceptance/2026-10-31-launch-audit/findings.md` 的 P0-04 行）

`docs/deployment/production-deployment.md::5. 生产安全基线` 把「SLS 采集 + 告警（CPU/内存/磁盘/5xx/健康检查）
触达值班」列为**必须项**，而仓库里此前没有任何 5xx 判据、也没有统一的投递出口。

## 被守的三条路径（每条都能单独变红）

| 事件类 | 判据本体 | 投递通道 | 去重 |
|---|---|---|---|
| **5xx** | `deploy/scripts/prod-5xx-window.sh`（只读合成探针，0/1/3） | `scripts/prod_alert.sh` ⇒ issue `[prod-alert]` + webhook（可选） | key + 读数分级 |
| **证书到期** | `deploy/scripts/tls-expiry-check.sh`（P0-01，21 天阈值，0/1/3） | 同上（`--key tls-expiry`） | key + 读数分级 |
| **发布失败** | `scripts/deploy_leg_failure_reaction.sh`（既有，issue #6526 B） | issue `[deploy-leg] … 部署失败（合并后未上线）` + `priority/P1` | 腿名（标题） |
| （部署后回归） | `.github/workflows/post-deploy-eval.yml` 的 `Create Issue on failure (dedup guard)` | issue `[Post-Deploy] …` | 同日同标题 |

## 判据（会怎么红）

1. **三态**：5xx 探针喂「全 2xx」⇒ `rc=0`、「全 502」⇒ `rc=1`、「连不上」⇒ `rc=3`、「全 404」⇒ `rc=3`。
2. **注入（阈值真的是旋钮）**：同一份「2 次 502」读数，`PROD_5XX_THRESHOLD=3` ⇒ `rc=0`；
   改成 `1` ⇒ `rc=1`。阈值写成 `0` ⇒ `rc=2`（fail-closed：0 会让「零 5xx」也告警，等于毁掉判据）。
3. **幂等（同一事件只一条）**：同一 key+bucket 连跑两次 ⇒ **一次** `issue create`、**零**次 `issue comment`；
   bucket 变了 ⇒ 才追加一条评论。
4. **不泄密**：正文含疑似凭据（`token=` / `LTAI…` / `AKIA…`）⇒ `rc=1` 且**一个 gh 调用都不发**。
5. **通道缺失不静默**：显式选 webhook 却没有 `MIGAO_ALERT_WEBHOOK_URL` ⇒ `rc=3`；issue 通道不可用 ⇒ `rc=3`。
6. **接线**：`post-merge-verify.yml` 真跑这两个判据本体 + 投递本体，且都排在 `if: failure()` 的 P1 出口**之前**
   （放后面 = 判红不产生对话 = 静默）；`always()` + `!= 'pull_request'`（PR 的红只该反映 PR）。
7. **类级**：三类事件**各自**都要有「判据本体 + 通道」这一对 —— 删掉任一类 ⇒ 红（不是只守 5xx 一条）。

## 边界（照实登记，§19.1）

- 5xx 判据是**合成探针**（窗口内对几个面发若干次 GET），**不是**全站 5xx 率：它证明的是「探针窗口里
  这些面回了多少 5xx」。宿主机 nginx access log 的面需要 SSH 凭据（本仓探针位没有），登记为未覆盖。
- 判据**不联网跑生产**（PR 的绿不该取决于生产此刻的状态）：执行式用例喂本机 stub server；线上面由
  `post-merge-verify` 的 push / 每日 / 手动三个既有触发面承担。
- 投递**不测真 GitHub API**：执行式用例喂本机 stub `gh` / stub `curl`（记录调用 + 落盘正文），
  证明的是「投递语义（去重/通道选择/拒绝泄密）」；「线上真开出一条单」由接线后的 run 日志
  （`PROD-ALERT-SUMMARY` 行）承担。
- **不发短信/邮件**：外部账号属「需用户配置」，登记在 `docs/deployment/observability-minimum.md`。
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = REPO_ROOT / "deploy" / "scripts" / "prod-5xx-window.sh"
EMITTER = REPO_ROOT / "scripts" / "prod_alert.sh"
TLS_CHECK = REPO_ROOT / "deploy" / "scripts" / "tls-expiry-check.sh"
LEG_REACTION = REPO_ROOT / "scripts" / "deploy_leg_failure_reaction.sh"
POST_MERGE = REPO_ROOT / ".github" / "workflows" / "post-merge-verify.yml"
POST_DEPLOY_EVAL = REPO_ROOT / ".github" / "workflows" / "post-deploy-eval.yml"
DEPLOY_RECONCILE = REPO_ROOT / ".github" / "workflows" / "deploy-reconcile.yml"

CHANNEL_MARKERS = ("[prod-alert]", "[deploy-leg]", "[Post-Deploy]")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _env(**overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update({k: str(v) for k, v in overrides.items()})
    return env


# ══════════════════════════════════════════════════════════════════════════
# 一、5xx 探针：三态（执行式，真脚本 + 本机 stub server）
# ══════════════════════════════════════════════════════════════════════════


class _StubHandler(BaseHTTPRequestHandler):
    """`/ok` ⇒ 200 · `/boom` ⇒ 502 · 其它 ⇒ 404（一个 stub 覆盖三种面）。"""

    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 的接口
        if self.path.startswith("/boom"):
            code, body = 502, b"bad gateway"
        elif self.path.startswith("/ok"):
            code, body = 200, b"ok"
        else:
            code, body = 404, b"not found"
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静音（stub server 不要污染测试输出）
        return


@pytest.fixture()
def stub_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _run_probe(urls: str, **overrides: str):
    values = {
        "PROD_5XX_URLS": urls,
        "PROD_5XX_ROUNDS": "2",
        "PROD_5XX_INTERVAL": "0",  # 窗口内不 sleep（判据要快）
        "PROD_5XX_TIMEOUT": "5",
    }
    values.update(overrides)
    env = _env(**values)
    return subprocess.run(
        ["bash", str(PROBE)], capture_output=True, text=True, env=env, timeout=120, cwd=str(REPO_ROOT)
    )


def test_probe_is_green_when_faces_answer_without_5xx(stub_server):
    out = _run_probe(f"{stub_server}/ok")
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    assert "PROD-5XX-SUMMARY rc=0" in out.stdout
    assert "fivexx=0" in out.stdout


def test_probe_alerts_when_5xx_reaches_threshold(stub_server):
    out = _run_probe(f"{stub_server}/boom", PROD_5XX_THRESHOLD="2")
    assert out.returncode == 1, f"5xx 达阈值必须退 1，实测 {out.returncode}\n{out.stdout}"
    assert "PROD-5XX-SUMMARY rc=1" in out.stdout
    assert "fivexx=2" in out.stdout, out.stdout


def test_injection_lowering_the_threshold_turns_the_same_reading_into_an_alert(stub_server):
    """注入：**同一份读数**，只把阈值改小 ⇒ 告警触发（证明阈值真的是判定旋钮，不是装饰）。"""
    urls = f"{stub_server}/ok {stub_server}/boom"  # 2 轮 × 2 面 = 4 次请求，其中 2 次 502
    relaxed = _run_probe(urls, PROD_5XX_THRESHOLD="3")
    strict = _run_probe(urls, PROD_5XX_THRESHOLD="1")
    assert relaxed.returncode == 0, f"阈值 3 时 2 次 5xx 不该告警：\n{relaxed.stdout}"
    assert strict.returncode == 1, f"阈值 1 时同样读数必须告警：\n{strict.stdout}"
    assert "fivexx=2" in strict.stdout and "fivexx=2" in relaxed.stdout


def test_zero_threshold_is_rejected_fail_closed(stub_server):
    """阈值 0 会让「零 5xx」也告警 ⇒ 判据失效；必须 fail-closed（rc=2），不许当成正常配置。"""
    out = _run_probe(f"{stub_server}/ok", PROD_5XX_THRESHOLD="0")
    assert out.returncode == 2, f"阈值 0 必须退 2，实测 {out.returncode}\n{out.stdout}"
    assert "reason=bad_threshold" in out.stdout


def test_probe_is_unknown_when_unreachable():
    out = _run_probe("http://127.0.0.1:1/api/version")
    assert out.returncode == 3, f"连不上必须退 3（3 不当 0 读），实测 {out.returncode}\n{out.stdout}"
    assert "PROD-5XX-SUMMARY rc=3" in out.stdout


def test_probe_is_unknown_when_no_face_answers_2xx_or_3xx(stub_server):
    """全 4xx：没有一个面证明「服务在正常应答」⇒ 3（**不是** ok —— 「5xx 为零」不等于「面是好的」）。"""
    out = _run_probe(f"{stub_server}/missing")
    assert out.returncode == 3, f"全 4xx 必须退 3，实测 {out.returncode}\n{out.stdout}"
    assert "reason=no_ok_face" in out.stdout


def test_window_seconds_reading_matches_the_actual_pacing(stub_server):
    """窗口读数必须等于**轮间间隔 × (轮数−1)**：单轮没有轮间间隔 ⇒ 0s；两轮 ⇒ 1×INTERVAL。

    读数与行为不一致会误导排障（"≈ 15s 窗口" 实际是 0s 或反过来）。
    """
    single = _run_probe(f"{stub_server}/ok", PROD_5XX_ROUNDS="1", PROD_5XX_INTERVAL="5")
    assert single.returncode == 0, single.stdout
    assert "window_s=0" in single.stdout, f"单轮窗口必须读 0s：\n{single.stdout}"

    two = _run_probe(f"{stub_server}/ok", PROD_5XX_ROUNDS="2", PROD_5XX_INTERVAL="1")
    assert two.returncode == 0, two.stdout
    assert "window_s=1" in two.stdout, f"两轮 × 轮间 1s ⇒ 窗口 1s：\n{two.stdout}"


# ══════════════════════════════════════════════════════════════════════════
# 二、投递出口：stub gh / stub curl（真脚本 + 记录调用）
# ══════════════════════════════════════════════════════════════════════════

STUB_GH = r"""#!/usr/bin/env bash
# 最小 gh 替身：只实现 prod_alert.sh 用到的那几条（记录每次调用，便于断言「有没有写」）。
set -uo pipefail
STATE="${STUB_GH_STATE:?}"
echo "gh $*" >> "${STUB_GH_LOG:?}"
if [ -n "${STUB_GH_FAIL:-}" ] && [ "${STUB_GH_FAIL}" = "$2" ]; then
  echo "stub-gh: injected failure on $2" >&2
  exit 1
fi
case "$1 $2" in
  "issue list")
    if [ -s "$STATE/issue_no" ]; then cat "$STATE/issue_no"; fi
    exit 0
    ;;
  "issue view")
    [ -s "$STATE/issue_no" ] || { echo "stub-gh: no such issue" >&2; exit 1; }
    cat "$STATE/body" 2>/dev/null || true
    [ -f "$STATE/comments" ] && cat "$STATE/comments"
    exit 0
    ;;
  "issue create")
    cat > "$STATE/body"
    printf '4242\n' > "$STATE/issue_no"
    echo "https://example.invalid/issues/4242"
    exit 0
    ;;
  "issue comment")
    cat >> "$STATE/comments"
    exit 0
    ;;
  "issue edit")
    exit 0
    ;;
esac
exit 0
"""

STUB_CURL = r"""#!/usr/bin/env bash
# 最小 curl 替身：记录 argv 与 stdin（webhook payload），按 STUB_CURL_RC 决定成败。
set -uo pipefail
echo "curl $*" >> "${STUB_CURL_LOG:?}"
cat > "${STUB_CURL_PAYLOAD:?}" || true
exit "${STUB_CURL_RC:-0}"
"""


@pytest.fixture()
def channels(tmp_path):
    state = tmp_path / "gh-state"
    state.mkdir()
    gh = tmp_path / "gh"
    gh.write_text(STUB_GH, encoding="utf-8")
    gh.chmod(0o755)
    curl = tmp_path / "curl"
    curl.write_text(STUB_CURL, encoding="utf-8")
    curl.chmod(0o755)
    return {
        "state": state,
        "gh": gh,
        "curl": curl,
        "gh_log": tmp_path / "gh.log",
        "curl_log": tmp_path / "curl.log",
        "payload": tmp_path / "payload.json",
        "tmp": tmp_path,
    }


def _emit(channels, body: str, *, bucket: str = "rc1_1-5", key: str = "5xx-window", extra=None):
    channels["gh_log"].touch()
    body_file = channels["tmp"] / "body.md"
    body_file.write_text(body, encoding="utf-8")
    values = {
        "STUB_GH_STATE": str(channels["state"]),
        "STUB_GH_LOG": str(channels["gh_log"]),
        "STUB_CURL_LOG": str(channels["curl_log"]),
        "STUB_CURL_PAYLOAD": str(channels["payload"]),
        "MIGAO_ALERT_GH_BIN": str(channels["gh"]),
        "MIGAO_ALERT_CURL_BIN": str(channels["curl"]),
        "MIGAO_ALERT_CHANNEL": "issue",
        "MIGAO_ALERT_WEBHOOK_URL": "",
        "MIGAO_ALERT_RUN_URL": "https://example.invalid/run/777",
    }
    values.update(extra or {})
    env = _env(**values)
    return subprocess.run(
        [
            "bash",
            str(EMITTER),
            "--key",
            key,
            "--title",
            "[prod-alert] 生产 5xx 计数超阈值（合成探针窗口）",
            "--bucket",
            bucket,
            "--body-file",
            str(body_file),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        cwd=str(REPO_ROOT),
    )


def _gh_calls(channels) -> list[str]:
    text = channels["gh_log"].read_text(encoding="utf-8") if channels["gh_log"].exists() else ""
    return [line for line in text.splitlines() if line.strip()]


def test_first_alert_opens_one_issue_and_only_one(channels):
    out = _emit(channels, "### 5xx 窗口\n\nfivexx=4 band=1-5\n")
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    calls = _gh_calls(channels)
    assert sum("issue create" in c for c in calls) == 1, calls
    assert not any("issue comment" in c for c in calls), f"首轮不该评论：{calls}"
    assert "delivered=created" in out.stdout
    body = (channels["state"] / "body").read_text(encoding="utf-8")
    assert "run/777" in body, f"值班单正文必须带 run 链接（可归因）：{body}"
    assert "migao-alert fp=" in body, f"值班单正文必须带去重指纹（否则下一轮无法去重）：{body}"


def test_same_event_twice_produces_exactly_one_issue_and_no_extra_comment(channels):
    """幂等（审计要求 3：同一事件不许每轮刷屏）：同 key + 同分级连跑两次 ⇒ 1 条单、0 条新评论。"""
    body = "### 5xx 窗口\n\nfivexx=4 band=1-5\n"
    first = _emit(channels, body)
    second = _emit(channels, body)
    assert first.returncode == 0 and second.returncode == 0, f"{first.stdout}\n{second.stdout}"
    calls = _gh_calls(channels)
    assert sum("issue create" in c for c in calls) == 1, f"只该开一条单：{calls}"
    assert not any("issue comment" in c for c in calls), f"同分级不该追加评论：{calls}"
    assert "delivered=deduped" in second.stdout, second.stdout


def test_changed_reading_band_adds_one_comment_not_a_second_issue(channels):
    assert _emit(channels, "fivexx=4 band=1-5\n", bucket="rc1_1-5").returncode == 0
    out = _emit(channels, "fivexx=11 band=6-20\n", bucket="rc1_6-20")
    assert out.returncode == 0, out.stdout
    calls = _gh_calls(channels)
    assert sum("issue create" in c for c in calls) == 1, f"分级变了也该复用同一条单：{calls}"
    assert sum("issue comment" in c for c in calls) == 1, f"分级变了只追加一条：{calls}"
    assert "delivered=commented" in out.stdout


def test_suspected_secret_in_body_is_refused_before_any_channel_call(channels):
    out = _emit(channels, "日志行：Authorization: token=abcdef123456\n")
    assert out.returncode == 1, f"命中疑似凭据必须拒绝发送（rc=1），实测 {out.returncode}\n{out.stdout}"
    assert "reason=suspected_secret" in out.stdout
    assert _gh_calls(channels) == [], "拒绝发送时不许有任何 gh 调用（别把凭据送到 issue 上）"


def test_issue_channel_unavailable_is_loud_rc3(channels):
    out = _emit(channels, "x\n", extra={"MIGAO_ALERT_GH_BIN": str(channels["tmp"] / "no-such-gh")})
    assert out.returncode == 3, f"通道不可用必须 rc=3（不静默），实测 {out.returncode}\n{out.stdout}"
    assert "reason=gh_missing" in out.stdout


def test_webhook_selected_without_url_is_loud_rc3(channels):
    out = _emit(channels, "x\n", extra={"MIGAO_ALERT_CHANNEL": "webhook", "MIGAO_ALERT_GH_BIN": ""})
    assert out.returncode == 3, f"选了 webhook 却没 URL ⇒ rc=3，实测 {out.returncode}\n{out.stdout}"
    assert "reason=webhook_unconfigured" in out.stdout


def test_webhook_channel_posts_when_configured(channels):
    out = _emit(
        channels,
        "### 5xx 窗口\n\nfivexx=4 band=1-5\n",
        extra={
            "MIGAO_ALERT_CHANNEL": "webhook",
            "MIGAO_ALERT_WEBHOOK_URL": "https://hook.example.invalid/robot",
            "MIGAO_ALERT_RUN_URL": "https://example.invalid/run/1",
        },
    )
    assert out.returncode == 0, f"{out.stdout}\n{out.stderr}"
    log = channels["curl_log"].read_text(encoding="utf-8")
    assert "-X POST" in log, log
    payload = channels["payload"].read_text(encoding="utf-8")
    assert '"key":"5xx-window"' in payload, payload
    assert '"fp":"5xx-window_rc1_1-5"' in payload, payload
    assert _gh_calls(channels) == [], "只选了 webhook 时不该再调 gh"


def test_dry_run_touches_no_channel(channels):
    out = _emit(channels, "x\n", extra={"MIGAO_ALERT_DRY_RUN": "1"})
    assert out.returncode == 0, out.stdout
    assert "delivered=dry-run" in out.stdout
    assert _gh_calls(channels) == []
    assert not channels["curl_log"].exists()


# ══════════════════════════════════════════════════════════════════════════
# 三、接线（判据存在但没人跑 = 假绿）+ 注入式红证
# ══════════════════════════════════════════════════════════════════════════


def _steps(path: Path, job: str) -> list[dict]:
    doc = yaml.safe_load(_read(path))
    return doc["jobs"][job].get("steps") or []


def _wiring_problems(steps: list[dict]) -> list[str]:
    """本腿的告警接线：判据本体 + 投递本体都在**同一个** step 里真跑，且排在 `if: failure()` 钩子之前。"""
    problems: list[str] = []
    runs = [str(s.get("run", "")) for s in steps]
    # 5xx / TLS 各自的那一步必须**自己**把「判据 + 投递」都跑起来：只有判据 ⇒ 只红不响；
    # 只有投递 ⇒ 没有事件可发。
    probe_idx = [i for i, r in enumerate(runs) if "prod-5xx-window.sh" in r]
    tls_idx = [i for i, r in enumerate(runs) if "tls-expiry-check.sh" in r]
    hook_idx = [i for i, s in enumerate(steps) if "failure()" in str(s.get("if", ""))]

    if not probe_idx:
        problems.append("5xx 判据本体没有被任何 step 调用（判据存在但没人跑 = 假绿）")
    if not tls_idx:
        problems.append("TLS 判据本体没有被任何 step 调用（P0-01 的判定面消失了）")
    if not any("prod_alert.sh" in r for r in runs):
        problems.append("没有任何 step 调 `scripts/prod_alert.sh`（判红只让腿变红，没人被惊动）")
    if not hook_idx:
        problems.append("没有 `if: failure()` 的 P1 出口（判红不建单）")

    for label, idx in (("5xx", probe_idx), ("TLS", tls_idx)):
        if idx and "prod_alert.sh" not in runs[idx[0]]:
            problems.append(f"{label} 判据那一步没有接告警投递（判红了也没人被告知）")
        if idx and hook_idx and not idx[0] < hook_idx[0]:
            problems.append(
                f"{label} 判据排在 `if: failure()` 值班单之后（判红不产生对话 = 静默）"
                f"（实测 {label}={idx} hook={hook_idx}）"
            )

    for label, i in [(("5xx"), i) for i in probe_idx] + [(("TLS"), i) for i in tls_idx]:
        if_cond = str(steps[i].get("if", ""))
        env = steps[i].get("env") or {}
        if "GH_TOKEN" not in env:
            problems.append(
                f"{label} 那一步缺 `GH_TOKEN`（Actions **不会**自动注入 `github.token`）"
                "⇒ 投递必 rc=3、只剩一条 warning = 又回到静默（issue #8203）"
            )
        if "MIGAO_ALERT_RUN_URL" not in env:
            problems.append(f"{label} 那一步缺 `MIGAO_ALERT_RUN_URL`（值班单里没有 run 链接 ⇒ 不可归因）")
        if i in probe_idx and "always()" not in if_cond:
            problems.append("5xx 探针必须 `if: always()`（判定步判红时生产 5xx 仍要被探到）")
        if "pull_request" not in if_cond:
            problems.append(
                "生产探针必须排除 `pull_request`（PR 的红只该反映 PR，不该因为生产此刻的状态判红）"
            )
    return problems


def test_post_merge_leg_wires_the_5xx_and_tls_alerts():
    problems = _wiring_problems(_steps(POST_MERGE, "verify"))
    assert problems == [], "\n".join(problems)


def test_removing_the_alert_wiring_turns_it_red():
    """接线判据的判别力：摘掉投递 / 摘掉探针 / 把探针挪到钩子之后 ⇒ 各能单独变红。"""
    baseline = _steps(POST_MERGE, "verify")
    assert _wiring_problems(baseline) == [], "基线已被弄坏（红证前提自证失败）"

    mut = [dict(s) for s in baseline]
    for step in mut:
        if "prod_alert.sh" in str(step.get("run", "")):
            step["run"] = str(step["run"]).replace("prod_alert.sh", "echo skipped")
    assert _wiring_problems(mut) != [], "摘掉投递之后没红 ⇒ 空断言"

    mut = [dict(s) for s in baseline]
    for step in mut:
        if "prod-5xx-window.sh" in str(step.get("run", "")):
            step["run"] = str(step["run"]).replace("prod-5xx-window.sh", "echo skipped")
    assert _wiring_problems(mut) != [], "摘掉 5xx 探针之后没红 ⇒ 空断言"

    # 把探针挪到 `if: failure()` 钩子之后（= 判红不产生值班单）
    probe_step = next(s for s in baseline if "prod-5xx-window.sh" in str(s.get("run", "")))
    order_fixed = [s for s in baseline if s is not probe_step] + [probe_step]
    assert order_fixed[-1] is probe_step, "变异未生效（自证失败）"
    assert _wiring_problems(order_fixed) != [], "把探针挪到钩子之后没红 ⇒ 空断言"

    # 摘掉 `GH_TOKEN`（Actions 不自动注入 ⇒ 投递必 rc=3，只剩 warning = 静默）
    mut = [dict(s) for s in baseline]
    hit = False
    for step in mut:
        if "prod-5xx-window.sh" in str(step.get("run", "")) and step.get("env"):
            step["env"] = {k: v for k, v in step["env"].items() if k != "GH_TOKEN"}
            hit = True
    assert hit, "变异点失配：5xx 探针步没有 env（红证不得是空断言）"
    assert _wiring_problems(mut) != [], "摘掉 GH_TOKEN 之后没红 ⇒ 空断言"


def test_all_three_event_classes_have_a_judge_and_a_channel():
    """类级元守卫（审计 P0-04 的原文口径）：**三类事件各自**都要有「判据本体 + 有人看的通道」。"""
    post_merge = "\n".join(str(s.get("run", "")) for s in _steps(POST_MERGE, "verify"))

    # ① 5xx：判据本体 + 投递
    assert "deploy/scripts/prod-5xx-window.sh" in post_merge, "5xx 判据本体没接线"
    assert CHANNEL_MARKERS[0] in post_merge, "5xx 告警没有落到 `[prod-alert]` 通道（标题前缀）"

    # ② 证书到期：判据本体 + 投递
    assert "deploy/scripts/tls-expiry-check.sh" in post_merge, "证书到期判据本体没接线"
    tls_step = next(s for s in _steps(POST_MERGE, "verify") if "tls-expiry-check.sh" in str(s.get("run", "")))
    assert "--key tls-expiry" in str(tls_step.get("run", "")), "证书到期的告警没有独立的去重键（会与 5xx 混一条单）"

    # ③ 发布失败：既有腿级反应 + 部署后回归的失败钩子（都在 main 上，删任一条 ⇒ 本判据红）
    assert "deploy_leg_failure_reaction.sh" in _read(DEPLOY_RECONCILE), "部署腿失败的反应步被摘掉了"
    reaction = _read(LEG_REACTION)
    assert CHANNEL_MARKERS[1] in reaction, "`[deploy-leg]` 通道前缀消失（部署失败的告警没法按腿去重）"
    assert "priority/P1" in reaction, "部署失败的值班单没有 `priority/P1`（没人看的标签不算通道）"
    eval_text = _read(POST_DEPLOY_EVAL)
    assert CHANNEL_MARKERS[2] in eval_text, "部署后回归的失败单前缀消失"
    assert "Create Issue on failure" in eval_text, "部署后回归失败不再建单（静默）"


def test_alerting_scripts_never_run_with_shell_tracing():
    """不泄密（静态面）：`set -x` 会把展开后的 argv（可能含凭据）打到 CI 日志里 —— 两个新脚本都不许有。"""
    for path in (PROBE, EMITTER):
        text = _read(path)
        assert not re.search(r"^\s*set -[a-z]*x", text, re.MULTILINE), f"{path.name} 打开了 shell tracing"
        assert "echo $" not in text, f"{path.name} 里出现未加引号的环境变量展开（容易把值打进日志）"


if __name__ == "__main__":  # pragma: no cover - 手工复算入口
    raise SystemExit(pytest.main([__file__, "-q"]))
