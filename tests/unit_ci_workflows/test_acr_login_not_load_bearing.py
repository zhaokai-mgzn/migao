# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
r"""ACR 登录**不承重**守卫 —— issue #6526 A（登录是未重试的 fail-fast 前置 ⇒ 一次网络 RST 打死整条腿）。

## 病（issue #6526 A，逐条锚点）

修前四处调用点都是**未重试的 fail-fast 前置**：
`echo "${{ secrets.ACR_PASSWORD }}" | docker login …`（`deploy-admin-api.yml` / `deploy-frontend.yml` /
`deploy-reconcile.yml`）与 `docker login … --password ${{ secrets.ACR_PASSWORD }}`
（`deploy-ai-agent-service.yml`，密码还上了**命令行**）。网络 RST / TLS 抖动**一次**就打死整条腿。

而 C′（issue #5814）之后 **CI 不构建、不推 ACR**（自证步 = `deploy-frontend.yml` 的
`Assert server-side build (no ACR push)`；构建在服务器侧 `deploy/scripts/swas-deploy-ci.sh`）
⇒ CI 侧登录**已不承重**，却仍握着一票否决。**让一个不承重的步骤否决整条腿，就是本单要治的病。**

## 两态（唯一接口差异 = 末位 `--fatal`）

| 态 | 调用点 | 3 次仍失败时 |
|---|---|---|
| **不承重**（默认） | 三条部署腿 + 对账腿 | 具名 `::warning::` + 关键 stderr ⇒ **`exit 0`** |
| **承重**（`--fatal`） | `bmini-h5-publish.yml`（把产物装进传输镜像**真的推到 ACR**） | 具名 `::error::` ⇒ **非零退出** |

## 判据

| # | 判什么 | 回归时会怎么红 |
|---|---|---|
| 1 | 任何 `.github/workflows/*.yml` 的可执行行里**不许有裸 `docker login`**（必须走 helper） | 把裸 `docker login` 写回来 ⇒ 具名报出 `<file>::<step>` |
| 2 | 不许出现 `--password ${{` / `--password $` 形态（密码上命令行） | ai-agent 那种形态回来 ⇒ 红 |
| 3 | `scripts/acr_login.sh` 存在 + 三件套（重试上界 / `timeout` / `--password-stdin`） | 有人把重试或 `timeout` 删掉 ⇒ 红 |
| 4 | 失败路径：不带 `--fatal` ⇒ `exit 0` + `::warning::`；带 ⇒ 非零 + `::error::` | 把「不承重」改成判红（= 本单的病复发）⇒ 红 |
| 5 | **行为面（执行式）**：桩 `docker` 前 2 次失败、第 3 次成功 ⇒ **重试真的发生**且 rc=0 | 把重试循环摘掉 ⇒ 红 |
| 6 | **行为面**：3 次全失败 + `--fatal` ⇒ 非零；不带 ⇒ `exit 0` | 两态互换 / 都判红 / 都放行 ⇒ 红 |
| 7 | **接线双向**：`bmini-h5-publish.yml` **必须**带 `--fatal`；三条部署腿 + 对账腿**必须不带** | 形态反了（任一方向）⇒ 红 |
| 8 | **元守卫**：任何跑 ACR 登录的腿都必须走 helper（判据 1 已覆盖全仓面，此处具名复述） | 新腿接裸登录 ⇒ 红 |
| 9 | 具名确定性闸门检出**不调 `gh`**（`REACT_LOG_FILE` 离线面）—— 由同批的反应步判据承担 | —— |
| 10 | **判别力自证**：把 helper 的 `exit 0` 改成 `exit 1` / 摘掉 `timeout` / 把裸登录写回 workflow ⇒ 各自判红；**只改注释 ⇒ 不红** | 判据退化成空断言 ⇒ 红 |

## 边界（照实登记）

- **登录本身成不成功**判不了（本机无 ACR 凭据、不联网）：判据 5/6 只判**重试与两态退出语义**（用桩）。
- **`timeout` 的「真的会杀挂住的 docker」**判不了（那要真挂住的 docker）—— 只判 `timeout` 在**活代码行**里。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
HELPER = REPO_ROOT / "scripts" / "acr_login.sh"
BASH = "/bin/bash"

NON_FATAL = ("deploy-admin-api.yml", "deploy-frontend.yml",
             "deploy-ai-agent-service.yml", "deploy-reconcile.yml")
FATAL = ("bmini-h5-publish.yml",)

ACTIVE_LINE = re.compile(r"^\s*[^#\s]")            # 「活代码行」：非空且非注释
DOCKER_LOGIN = re.compile(r"(?<![-\w.])docker\s+login\b")
PASSWORD_ON_ARGV = re.compile(r"--password\s+\$\{?\{?")   # `--password ${{ … }}` / `--password $VAR`


def _jobs():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_id, job in (doc.get("jobs") or {}).items():
            if isinstance(job, dict):
                for step in job.get("steps") or []:
                    if isinstance(step, dict):
                        yield path, job_id, step


# ══════════════════════════════════════════════════════════════════════════
# 一、静态面（真语料，全仓 workflow）
# ══════════════════════════════════════════════════════════════════════════

def test_workflow_docker_login_is_always_the_helper():
    """判据 1 + 8：任何 workflow 都不许在**活代码行**上裸调 `docker login`（元守卫：全仓面）。"""
    bad = []
    for path, _job, step in _jobs():
        body = step.get("run")
        if not isinstance(body, str):
            continue
        for line in body.splitlines():
            if ACTIVE_LINE.match(line) and DOCKER_LOGIN.search(line):
                bad.append(f"{path.name}::{step.get('name')}  →  {line.strip()}")
    assert not bad, (
        "workflow 的 run 正文里出现裸 `docker login` —— 必须走唯一实现 `scripts/acr_login.sh`"
        "（issue #6526 A：那四处旧形态是未重试的 fail-fast 前置，一次网络 RST 就打死整条腿）：\n  "
        + "\n  ".join(bad)
        + "\n修法：`run: bash scripts/acr_login.sh ${{ env.ACR_REGISTRY }} \"${{ secrets.ACR_USERNAME }}\" "
          "\"${{ secrets.ACR_PASSWORD }}\"`（承重腿再加 `--fatal`）。"
    )


def test_password_never_on_the_command_line():
    """判据 2：不许出现密码上命令行的形态（`--password ${{ … }}` / `--password $VAR`）。"""
    bad = []
    for path, _job, step in _jobs():
        body = step.get("run")
        if not isinstance(body, str):
            continue
        for line in body.splitlines():
            if ACTIVE_LINE.match(line) and PASSWORD_ON_ARGV.search(line):
                bad.append(f"{path.name}::{step.get('name')}  →  {line.strip()}")
    assert not bad, (
        "密码出现在命令行上（会进 docker 的 argv / `ps` / 日志）—— 唯一允许的形态是 "
        "`--password-stdin`（helper 内部）：\n  " + "\n  ".join(bad)
    )


def test_helper_has_retry_bound_timeout_and_stdin():
    """判据 3：helper 必须同时有重试上界 / `timeout` / `--password-stdin`。"""
    text = HELPER.read_text(encoding="utf-8")
    active = "\n".join(l for l in text.splitlines() if ACTIVE_LINE.match(l))
    assert re.search(r"^MAX_ATTEMPTS=\d+$", active, re.M), "helper 缺 `MAX_ATTEMPTS=<n>`（重试上界）"
    assert int(re.search(r"^MAX_ATTEMPTS=(\d+)$", active, re.M).group(1)) >= 2, (
        "重试上界 <2 ⇒ 等于没重试（issue #6526 A 要求 3 次）"
    )
    assert re.search(r'"\$TIMEOUT_BIN" "\$ATTEMPT_TIMEOUT" docker login', active), (
        "helper 缺单次尝试的墙钟上界（`\"$TIMEOUT_BIN\" \"$ATTEMPT_TIMEOUT\" docker login`）——"
        "挂住的 `docker login` 会一直等到 job 的 timeout-minutes"
    )
    assert re.search(r'command -v (g?timeout)', active), (
        "helper 必须**可移植地**取 timeout（macOS 本机没有 `timeout`；硬调 ⇒ 本机执行式判据全数假红）"
    )
    assert "--password-stdin" in active, "helper 必须用 `--password-stdin`"
    assert "--password " not in active.replace("--password-stdin", ""), (
        "helper 里出现了 `--password <值>`（密码上命令行）—— 只许 `--password-stdin`"
    )
    assert re.search(r'^\s*if \[ "\$i" -lt "\$MAX_ATTEMPTS" \]; then$', active, re.M), (
        "helper 缺「还有下一次才退避」的判断（退避 5s/10s 的锚点）"
    )


def test_helper_failure_paths_are_two_state():
    """判据 4：不承重 ⇒ `exit 0` + `::warning::`；承重 ⇒ 非零 + `::error::`。"""
    text = HELPER.read_text(encoding="utf-8")
    assert 'FATAL="yes"' in text and '"${4:-}" = "--fatal"' in text, (
        "helper 的接口必须是 `<registry> <username> <password> [--fatal]`（两态，issue #6526 的规格补丁）"
    )
    assert re.search(r'\[ "\$FATAL" = "yes" \]', text), "helper 必须按 `--fatal` 拐弯"
    # 承重分支：::error:: + exit 1
    assert "::error::" in text and re.search(r":error::.*\n.*\n?.*exit 1", text, re.S), (
        "承重分支必须 `::error::` + 非零退出（bmini 那条腿真的推 ACR）"
    )
    # 不承重分支：::warning:: + exit 0
    tail = text[text.index('if [ "$FATAL" = "yes" ]'):]
    assert "::warning::" in tail and re.search(r"exit 0$", tail.rstrip() + "\n", re.M), (
        "不承重分支必须**具名 `::warning::` + `exit 0`** —— 让不承重的步骤否决整条腿正是本单要治的病"
    )


def test_wiring_is_bidirectional():
    """判据 7：承重 ⇄ 不承重的**接线**必须双向对上（形态反了 ⇒ 红）。"""
    got = {}
    for path in FATAL + NON_FATAL:
        doc = yaml.safe_load((WORKFLOWS / path).read_text(encoding="utf-8")) or {}
        calls = []
        for job in (doc.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if isinstance(step, dict) and isinstance(step.get("run"), str):
                    if "scripts/acr_login.sh" in step["run"]:
                        calls.append(step["run"])
        assert len(calls) == 1, f"{path}：必须**恰好一处** ACR 登录调用点（现取 {len(calls)} 处）→ {calls}"
        got[path] = "--fatal" in calls[0]
    for path in FATAL:
        assert got[path], (
            f"{path}：**承重**腿（把产物装进传输镜像推到 ACR）的登录失败必须判红 ⇒ 调用必须带 `--fatal`"
        )
    for path in NON_FATAL:
        assert not got[path], (
            f"{path}：**不承重**腿（C′ 后 CI 不推 ACR）**不许**带 `--fatal` —— 带了就等于把本单治的病"
            "原样装回去（一个不承重的步骤否决整条腿）"
        )


# ══════════════════════════════════════════════════════════════════════════
# 二、行为面（执行式：桩 `docker`，真 `timeout`）
# ══════════════════════════════════════════════════════════════════════════

DOCKER_STUB = """#!/usr/bin/env bash
# 桩：`calls` 累加；按 `DOCKER_EXIT_SEQ`（逗号分隔，用尽后沿用最后一个）给退出码。
n=$(cat "$DOCKER_CALLS" 2>/dev/null || echo 0); n=$((n + 1)); printf '%s' "$n" > "$DOCKER_CALLS"
code=0
if [ -n "${DOCKER_EXIT_SEQ:-}" ]; then
  IFS=',' read -r -a seq <<< "$DOCKER_EXIT_SEQ"
  idx=$((n - 1)); [ "$idx" -ge "${#seq[@]}" ] && idx=$(( ${#seq[@]} - 1 ))
  code="${seq[$idx]}"
fi
if [ "${DOCKER_SLEEP:-}" != "" ] && [ "$code" != "0" ]; then sleep "$DOCKER_SLEEP"; fi
echo "stub: docker $*" >&2
exit "$code"
"""


def _run_helper(tmp_path: Path, *, args: list[str], exit_seq: str = "1,1,0",
                attempt_timeout: str = "30", docker_sleep: str = "") -> tuple:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "docker"
    stub.write_text(DOCKER_STUB, encoding="utf-8")
    stub.chmod(0o755)
    calls = tmp_path / "docker-calls"
    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        "DOCKER_EXIT_SEQ": exit_seq,
        "DOCKER_CALLS": str(calls),
        "DOCKER_SLEEP": docker_sleep,
        "ACR_LOGIN_ATTEMPT_TIMEOUT_SECONDS": attempt_timeout,
    })
    proc = subprocess.run([BASH, str(HELPER), *args], env=env,
                          capture_output=True, text=True, timeout=120)
    n = int((calls.read_text(encoding="utf-8") or "0").strip() or "0") if calls.exists() else 0
    return proc, n


def test_retry_actually_happens_and_succeeds_on_third(tmp_path):
    """判据 5：前 2 次失败、第 3 次成功 ⇒ 真的重试了，且 rc=0。"""
    proc, calls = _run_helper(tmp_path, args=["reg.example.com", "user", "pw"], exit_seq="1,1,0")
    assert calls == 3, f"重试没发生：桩 `docker` 只被调了 {calls} 次（应为 3）\n{proc.stdout}{proc.stderr}"
    assert proc.returncode == 0, f"第 3 次成功却不 rc=0 → {proc.returncode}\n{proc.stdout}{proc.stderr}"
    assert "登录成功" in proc.stdout, f"成功路径缺读数：{proc.stdout!r}"


def test_non_fatal_state_exits_zero_after_all_attempts_fail(tmp_path):
    """判据 6a：3 次全失败 + **不带** `--fatal` ⇒ `exit 0` + 具名 `::warning::`。"""
    proc, calls = _run_helper(tmp_path, args=["reg.example.com", "user", "pw"], exit_seq="1")
    assert calls == 3, f"应重试到上界 3 次（现取 {calls}）"
    assert proc.returncode == 0, (
        f"非承重态必须 `exit 0`（issue #6526 A）—— 现取 rc={proc.returncode}\n{proc.stdout}{proc.stderr}"
    )
    joined = proc.stdout + proc.stderr
    assert "::warning::ACR 登录失败" in joined, f"缺具名 `::warning::`：{joined!r}"
    assert "stub: docker" in joined, f"必须把 docker 的关键 stderr 行打出来（不吞信息）：{joined!r}"


def test_fatal_state_is_nonzero_after_all_attempts_fail(tmp_path):
    """判据 6b：3 次全失败 + **带** `--fatal` ⇒ 非零 + `::error::`。"""
    proc, calls = _run_helper(tmp_path, args=["reg.example.com", "user", "pw", "--fatal"], exit_seq="1")
    assert calls == 3, f"应重试到上界 3 次（现取 {calls}）"
    assert proc.returncode != 0, (
        f"承重态必须非零退出（bmini 那条腿真的推 ACR）—— 现取 rc={proc.returncode}\n{proc.stdout}{proc.stderr}"
    )
    assert "::error::" in (proc.stdout + proc.stderr), "承重态的失败必须具名 `::error::`"


@pytest.mark.skipif(
    shutil.which("timeout") is None and shutil.which("gtimeout") is None,
    reason="本机没有 `timeout`/`gtimeout`（macOS 默认如此）⇒ helper 诚实降级为「直跑 + warning」，"
           "这一条只能在 runner/装了 coreutils 的机器上取读数（CI 是 ubuntu，有）。"
           "⚠️ 如实登记：这条判据在 macOS 本机**取不到读数**，不是「通过」。",
)
def test_hung_docker_login_is_bounded_by_timeout(tmp_path):
    """判据 3 的行为面：每次尝试都被真 `timeout` 包住（挂住的 docker 不许拖过界）。"""
    import time
    t0 = time.monotonic()
    proc, calls = _run_helper(tmp_path, args=["reg.example.com", "user", "pw", "--fatal"],
                              exit_seq="1", attempt_timeout="2", docker_sleep="30")
    dt = time.monotonic() - t0
    assert calls == 3, f"每次尝试都必须发生（现取 {calls}）"
    assert dt < 25, f"3 次 × 2s 的尝试本应 <25s，实测 {dt:.1f}s ⇒ `timeout` 没生效（挂住的 docker 拖过了界）"
    assert proc.returncode != 0, "承重态 + 超时 ⇒ 非零"


# ══════════════════════════════════════════════════════════════════════════
# 三、判别力自证（注入式红证：证明上面每一条都会红）
# ══════════════════════════════════════════════════════════════════════════

def _lint_docker_login(docs: dict[str, str]) -> list[str]:
    """判据 1 的**纯函数**形态（真语料与注入语料走同一条路）。"""
    bad = []
    for name, text in docs.items():
        doc = yaml.safe_load(text) or {}
        for job in (doc.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if isinstance(step, dict) and isinstance(step.get("run"), str):
                    for line in step["run"].splitlines():
                        if ACTIVE_LINE.match(line) and DOCKER_LOGIN.search(line):
                            bad.append(f"{name}::{step.get('name')}")
    return sorted(set(bad))


def test_docker_login_lint_has_discriminating_power():
    """判据 10a：把裸 `docker login` 写回 ⇒ 判据 1 必红；只改注释 ⇒ 不红。"""
    real = {p.name: p.read_text(encoding="utf-8") for p in sorted(WORKFLOWS.glob("*.yml"))}
    assert _lint_docker_login(real) == [], "真语料上判据 1 已经不干净（前置条件不成立）"
    # 注入：把 ai-agent 那一步换成裸 login（逐字还原旧形态）
    src = real["deploy-ai-agent-service.yml"]
    broken = src.replace(
        'run: bash scripts/acr_login.sh ${{ env.ACR_REGISTRY }} "${{ secrets.ACR_USERNAME }}" "${{ secrets.ACR_PASSWORD }}"',
        "run: echo x | docker login ${{ env.ACR_REGISTRY }} -u u --password-stdin", 1)
    assert broken != src, "注入未生效：ai-agent 的登录调用没找到（判据已过期）"
    hits = _lint_docker_login({**real, "deploy-ai-agent-service.yml": broken})
    assert hits, "把裸 `docker login` 写回来却**没红** ⇒ 判据 1 是空断言"
    # 反向对照：只改注释 ⇒ 不红
    note_only = {**real, "deploy-ai-agent-service.yml": src.replace(
        "# 判据 = tests/", "# 判据（改了注释而已）= tests/", 1)}
    assert note_only["deploy-ai-agent-service.yml"] != src, "注释注入未生效"
    assert _lint_docker_login(note_only) == [], "只改注释就判红 ⇒ 守卫被自己的文案喂红"


def test_helper_criterion_has_discriminating_power():
    """判据 10b：摘掉 `timeout` / 把 `exit 0` 改成 `exit 1` ⇒ 判据 3 / 4 必红。"""
    text = HELPER.read_text(encoding="utf-8")
    # 摘掉 timeout（把 `timeout "$ATTEMPT_TIMEOUT"` 删掉）
    no_timeout = text.replace('"$TIMEOUT_BIN" "$ATTEMPT_TIMEOUT" docker login', "docker login", 1)
    assert no_timeout != text, "注入未生效：helper 里找不到带墙钟上界的 docker login"
    active = "\n".join(l for l in no_timeout.splitlines() if ACTIVE_LINE.match(l))
    assert not re.search(r'"\$TIMEOUT_BIN" "\$ATTEMPT_TIMEOUT" docker login', active), (
        "摘掉墙钟上界后判据 3 仍绿 ⇒ 那条断言是空断言"
    )
    # 把**不承重分支**（`::warning::` 之后那一个）的 `exit 0` 改成 `exit 1`（= 本单的病复发）
    marker = "降级为告警、不判红"
    head, sep, tail = text.rpartition("exit 0")
    assert sep == "exit 0" and marker in head, "注入未生效：找不到不承重分支末尾的 `exit 0`"
    tail_broken = head + "exit 1" + tail
    assert tail_broken != text, "注入未生效"
    tail_after_fatal = tail_broken[tail_broken.index('if [ "$FATAL" = "yes" ]'):]
    assert not re.search(r"^exit 0$", tail_after_fatal, re.M), (
        "把不承重分支改成 `exit 1` 之后，`--fatal` 之后仍有一个 `exit 0` ⇒ 判据 4 的那条断言是空断言"
    )
