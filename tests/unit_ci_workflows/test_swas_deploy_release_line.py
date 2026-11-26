# case_ids: MC-347
"""`deploy/swas/deploy.sh` 的**发布线自检**守卫 —— issue #9086（2026-11-23 用户批准）。

## 为什么要有这条

「部署生产只认 `release`」此前只有**一处**闸门：`deploy-prod.yml` 的「发布线纪律（只认 release）」
步骤（判据 = `tests/unit_ci_workflows/test_deploy_prod_release_discipline.py`）。
而主机上的 `/opt/migao-deploy/deploy.sh`（= 仓库 `deploy/swas/deploy.sh` 自同步过去的那一份）
只保证「**配置 ref 与镜像 tag 同源**」（`config_ref_for_tag`，绝不回落 main），
**不判断这个 tag 属不属于 `release`** ⇒ 有人在主机上直接敲 `./deploy.sh sha-xxxxxxx` 就**整段绕过**它。

实测（2026-11-23 11:32–11:39）：手工跑 `deploy.sh` 之后只更新了 admin-api，admin-web 还是两天前的
镜像（**发成半截**），而脚本自己的结论是绿的、日志里没有任何异常 —— 「绕过闸门」这种形态
**不会自己变红**，除非部署脚本自己判。

## 钉住什么（四组）

1. **段存在且可静态定位**：`# >>> release-line-assert` / `# <<< release-line-assert` 成对
   （与 nginx 段的 `# >>> nginx-domain-assert` 同族），判据据此精确切段；
2. **该段必须真的判**：调用 `git merge-base --is-ancestor`、非祖先 `exit 2`、判不了 `exit 3`、
   逃生口 `ALLOW_UNVERIFIABLE_RELEASE` + ledger 追加 + `cut-release.sh` 指引（缺一即红）；
3. **该段必须早于任何部署动作**（**本单的核心**）：段结束行号 `<` 第一处真实
   `docker compose pull` / `docker compose up` / `docker build` / `registry_login` 调用的行号 ——
   「检查晚于部署 = 没检查」（那时容器已经被换掉，日志里的「拦住了」是假的）；
4. **行为**：把该段**原样抽出来**（不需要给脚本加测试专用钩子）+ 桩化 `git` / `docker` 真跑：

   | 场景 | 期望 |
   |---|---|
   | 目标是 release 祖先 | rc=0 + `RELEASE-LINE=OK target=<sha7> release=<sha7>` + 后续部署动作发生 |
   | 目标**不是**祖先 | rc=2 + 打印两个 sha/差多少提交 + **零** docker 写调用 |
   | 判不了（fetch 三次全失败 / 拿不到 release ref / 追不到 target） | rc=3 + **零** docker 写调用 |
   | 判不了 + 逃生口 | rc=0 + `::warning::RELEASE-LINE=UNVERIFIED` + ledger 追加一行（可 JSON 解析） |

## 注入式红证（实跑，四条；每次复原后转绿）

① 把该段挪到 `docker compose up` **之后** ⇒ 顺序判据红；
② 删掉 `exit 2` ⇒ 必填项判据红 **且** 非祖先场景实测 rc=0（放行）；
③ 去掉逃生口的 ledger 追加 ⇒ 必填项判据红 **且** 逃生口场景没有台账；
④ 把 `--is-ancestor` 换成 `git rev-parse` ⇒ 必填项判据红 **且** 非祖先场景被误放行。

## 边界（照实登记）

- **新检查从「下一次部署」起生效**：主机盘上跑的是**旧脚本**，脚本自同步（`# >>> deploy-selfsync`）
  要先把同源脚本落到盘上并 `exec` 重入，才执行得到本段 ⇒ 手工跑旧脚本那一轮不受保护（PR body 同口径）；
- 生产机到 github.com:443 时通时不通（#4852 实测 `git clone --filter=tree:0` 超时 32s）⇒ 本段
  **判不了就拒绝**（exit 3），逃生口必须显式给且会落账；这是**有意**不接受「静默放行」；
- 本判据只桩化外部依赖（`git` / `docker`），被测的是脚本自己的**编排逻辑**：不连生产、不跑部署。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "deploy" / "swas" / "deploy.sh"

BEGIN_MARK = "# >>> release-line-assert"
END_MARK = "# <<< release-line-assert"

# 桩回放用的假 sha（40 位；前 7 位就是日志里的 `<sha7>`）
TARGET_FULL = "0123456789abcdef0123456789abcdef01234567"
RELEASE_FULL = "89abcdef0123456789abcdef0123456789abcdef"
TARGET7 = TARGET_FULL[:7]
RELEASE7 = RELEASE_FULL[:7]
TAG = f"sha-{TARGET7}"

# 部署动作的「真调用」锚点（**排除注释与 echo 文案**：脚本里有 `echo "恢复：… docker compose pull …"`
# 这类**说明文字**，把它们当锚点会让顺序判据失去判别力）
ACTION_PATTERNS = (
    ("docker compose pull", re.compile(r"\bdocker compose pull\b")),
    ("docker compose up", re.compile(r"\bdocker compose up\b")),
    ("docker build", re.compile(r"\bdocker build\b")),
    ("registry_login 调用", re.compile(r"^registry_login$")),
)


# ── 文本级（静态）判定 ────────────────────────────────────────────────────────


def read_script() -> str:
    return DEPLOY_SH.read_text(encoding="utf-8")


def marker_lines(text: str) -> tuple[list[int], list[int]]:
    """`(BEGIN 出现行号[], END 出现行号[])`（1-based）。"""
    begins, ends = [], []
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip() == BEGIN_MARK:
            begins.append(i)
        elif line.strip() == END_MARK:
            ends.append(i)
    return begins, ends


def section_span(text: str) -> tuple[int, int]:
    """该段的 `(首行, 末行)` = 两个标记行（1-based）；标记不成对 ⇒ AssertionError（具名）。"""
    begins, ends = marker_lines(text)
    assert len(begins) == 1, f"`{BEGIN_MARK}` 必须恰好出现 1 次（实测 {begins}）"
    assert len(ends) == 1, f"`{END_MARK}` 必须恰好出现 1 次（实测 {ends}）"
    assert begins[0] < ends[0], f"标记顺序反了：begin@{begins[0]} end@{ends[0]}"
    return begins[0], ends[0]


def section_body(text: str) -> str:
    """标记**之间**的字节（可独立执行的那一段）。"""
    lines = text.splitlines()
    start, end = section_span(text)
    return "\n".join(lines[start:end - 1]) + "\n"


def judge_required(text: str) -> list[str]:
    """该段的**必备项**（缺一即红）。返回问题清单（空 = 通过）。"""
    problems: list[str] = []
    try:
        start, end = section_span(text)
    except AssertionError as exc:  # 标记缺失 / 重复 / 反序
        return [str(exc)]
    body = section_body(text)
    # 祖先判据必须是**提交图**语义（`merge-base --is-ancestor`），不是字符串前缀 / 时间戳。
    # ⚠️ 允许经段内的 `rl_git` 包装（它展开成 `git --git-dir=<发布线裸仓库> …`）：判据看的是
    #    「调的是不是那条 git 子命令」，不是「有没有手写 `git ` 三个字母」。
    if not re.search(r"(?:^|\s)(?:rl_git|git)\s+merge-base\s+--is-ancestor\b", body, re.M):
        problems.append(
            f"段内缺「祖先判据 `git merge-base --is-ancestor`」（段 {start}~{end} 行）"
            " —— 换成 `rev-parse` / `ls-remote` / 字符串比较都**不是**提交图判据"
        )
    # 取远端 ref 的调用同样允许经段内包装（`rl_git_fetch` = `rl_git … fetch` 的**唯一形态**，
    # 它把 GIT_TERMINAL_PROMPT / 低速上界 / `--filter=tree:0` 三件事收在一处，不让三处调用各写一份）。
    if not re.search(r"\bfetch\b", body):
        problems.append(f"段内缺「取 origin/release 的 `git fetch`」（段 {start}~{end} 行）")
    if "GIT_TERMINAL_PROMPT=0" not in body:
        problems.append(
            "段内的 fetch 没有关掉交互式凭据提示（`GIT_TERMINAL_PROMPT=0`）⇒ 生产机缺凭据时"
            "会在 https 认证提示上**永久挂住**（挂住比失败更坏：部署锁被占着）"
        )
    if "lowSpeedTime" not in body:
        problems.append(
            "段内的 fetch 没有**速率上界**（`http.lowSpeedTime`）⇒ 与脚本「不许无上界地挂住」"
            "（`BUILD_TIMEOUT_SECS` 那段）口径不一致"
        )
    required = {
        "取 `origin/release` 的 refspec（`+refs/heads/release:refs/remotes/origin/release`）":
            "'+refs/heads/release:refs/remotes/origin/release'",
        "`--force`（覆盖本地 ref）": "--force",
        "非祖先 ⇒ `exit 2`": "exit 2",
        "判不了 ⇒ `exit 3`": "exit 3",
        "逃生口 `ALLOW_UNVERIFIABLE_RELEASE`": "ALLOW_UNVERIFIABLE_RELEASE",
        "逃生口横幅 `::warning::RELEASE-LINE=UNVERIFIED`": "::warning::RELEASE-LINE=UNVERIFIED",
        "通过时打印 `RELEASE-LINE=OK target=`": "RELEASE-LINE=OK target=",
        "判不了时的原因具名（`RELEASE_LINE_WHY`）": "RELEASE_LINE_WHY",
        "差多少提交（`git rev-list --count`）": "rev-list --count",
        "可行动指引（`cut-release.sh`）": "cut-release.sh",
        "逃生口台账路径变量": "RELEASE_LEDGER_FILE",
    }
    for label, needle in required.items():
        if needle not in body:
            problems.append(f"段内缺「{label}」（找不到 `{needle}`；段 {start}~{end} 行）")
    # ledger 追加必须是**真的写盘**（判据 ③ 的红证对象）
    if not re.search(r'>>\s*"\$RELEASE_LEDGER_FILE"', body):
        problems.append('段内没有向 ledger **追加**（缺 `>> "$RELEASE_LEDGER_FILE"`）⇒ 逃生口不留痕')
    # ledger 行必须是可解析的 JSON 对象，且 decision 具名
    if '"decision":"unverified-release"' not in body:
        problems.append('ledger 行缺 `"decision":"unverified-release"`（绕过要可归因）')
    for key in ('"at"', '"target"', '"reason"'):
        if key not in body:
            problems.append(f"ledger 行缺键 {key}")
    # 逃生的**命令行**写法（`--allow-unverified-release`）与 env 写法等价：解析点在段外 ⇒ 全文找
    if "--allow-unverified-release" not in text:
        problems.append("全文缺 `--allow-unverified-release`（命令行逃生口与 env 写法必须等价）")
    return problems


def first_real_action_lines(text: str) -> list[tuple[str, int]]:
    """每一类部署动作**第一处真调用**的行号（跳过注释行与 `echo` 说明文字）。"""
    found: list[tuple[str, int]] = []
    for label, pattern in ACTION_PATTERNS:
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.startswith("echo"):
                continue
            if pattern.search(stripped):
                found.append((label, i))
                break
    return found


def judge_order(text: str) -> list[str]:
    """该段**必须早于**任何部署动作（本单核心：检查晚于部署 = 没检查）。"""
    try:
        _, end = section_span(text)
    except AssertionError as exc:
        return [str(exc)]
    problems: list[str] = []
    actions = first_real_action_lines(text)
    if not actions:
        return ["脚本里找不到任何部署动作锚点（判据已过期：deploy.sh 结构变了）—— 这不是「通过」"]
    for label, line in actions:
        if end >= line:
            problems.append(
                f"发布线自检段结束于第 {end} 行，但「{label}」在第 {line} 行才有（第 {line} 行）"
                f" ⇒ 检查**晚于部署** = 没检查"
            )
    return problems


# ── 行为面：抽段 + 桩化 git / docker 真跑 ─────────────────────────────────────

GIT_STUB = """#!/usr/bin/env bash
# 桩 git：回放判据要的五种回答，并把每次调用记进 $STUB_LOG
echo "git $*" >> "$STUB_LOG"
# 跳过全局选项（`--git-dir=…` / `-c key=value` 的**值**不是子命令）
cmd=""
skip=0
for a in "$@"; do
  if [ "$skip" = "1" ]; then skip=0; continue; fi
  case "$a" in
    -c) skip=1 ;;
    -*) ;;
    *) cmd=$a; break ;;
  esac
done
case "$cmd" in
  init)
    d=""
    for a in "$@"; do d=$a; done
    mkdir -p "$d"
    exit 0
    ;;
  fetch)
    if [ "${STUB_FETCH_FAIL:-0}" = "1" ]; then exit 128; fi
    exit 0
    ;;
  rev-parse)
    obj=""
    for a in "$@"; do
      case "$a" in
        -*) continue ;;
        *) obj=$a ;;
      esac
    done
    case "$obj" in
      refs/remotes/origin/release*)
        if [ "${STUB_NO_RELEASE:-0}" = "1" ]; then exit 1; fi
        echo "$STUB_RELEASE_SHA"
        exit 0
        ;;
    esac
    if [ "${STUB_UNRESOLVED_TARGET:-0}" = "1" ]; then exit 1; fi
    echo "$STUB_TARGET_SHA"
    exit 0
    ;;
  merge-base)
    if [ "${STUB_ANCESTOR:-1}" = "1" ]; then exit 0; fi
    exit 1
    ;;
  rev-list)
    echo "${STUB_AHEAD:-7}"
    exit 0
    ;;
esac
exit 0
"""

DOCKER_STUB = """#!/usr/bin/env bash
# 桩 docker：只记账（本判据断言「非祖先时**零**写调用」）
echo "docker $*" >> "$DOCKER_LOG"
exit 0
"""


def _write_exe(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def run_section(tmp_path: Path, body: str | None = None, *, extra_env: dict | None = None,
                with_deploy_after: bool = True) -> dict:
    """把该段**原样**抽出来跑（后面接一条部署动作，用来看它有没有被拦住）。

    `body=None` ⇒ 取仓库脚本里那一段的真字节；否则用调用方给的（注入式红证）。
    """
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_exe(bin_dir / "git", GIT_STUB)
    _write_exe(bin_dir / "docker", DOCKER_STUB)

    sec = body if body is not None else section_body(read_script())
    script = work / "section.sh"
    tail = "\ndocker compose up -d --no-deps admin-api\n" if with_deploy_after else ""
    script.write_text("set -euo pipefail\n" + sec + "\necho SECTION-PASSED\n" + tail, encoding="utf-8")

    stub_log = work / "git.log"
    docker_log = work / "docker.log"
    ledger = work / "release-ledger.jsonl"
    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(work),
        "TAG": TAG,
        "RELEASE_LINE_GIT_DIR": str(work / ".release-line.git"),
        "RELEASE_LINE_REMOTE": "https://example.invalid/zhaokai-mgzn/migao",
        "RELEASE_LINE_FETCH_DELAY_SECONDS": "0",
        "RELEASE_LEDGER_FILE": str(ledger),
        "ALLOW_UNVERIFIABLE_RELEASE": "0",
        # 本文件的行为面默认按**生产**口径跑（2026-11-24 起闸门有环境作用域）：
        # 显式 `enforce` 让既有用例的语义不受域名默认值影响；域名的三态由专门用例覆盖。
        "MIGAO_RELEASE_LINE": "enforce",
        "STUB_LOG": str(stub_log),
        "DOCKER_LOG": str(docker_log),
        "STUB_TARGET_SHA": TARGET_FULL,
        "STUB_RELEASE_SHA": RELEASE_FULL,
    }
    env.update(extra_env or {})
    proc = subprocess.run(
        ["bash", str(script)], cwd=str(work), env=env,
        capture_output=True, text=True, timeout=120,
    )
    return {
        "rc": proc.returncode,
        "out": proc.stdout + proc.stderr,
        "git_log": stub_log.read_text(encoding="utf-8") if stub_log.exists() else "",
        "docker_log": docker_log.read_text(encoding="utf-8") if docker_log.exists() else "",
        "ledger": ledger.read_text(encoding="utf-8") if ledger.exists() else "",
    }


# ── 一、静态：段存在 + 必备项 + 顺序 ───────────────────────────────────────────


def test_section_exists_with_static_markers():
    """锚点成对存在（判据据此切段；段被删/被改名 ⇒ 这里先红）。"""
    start, end = section_span(read_script())
    assert end - start > 20, f"该段只有 {end - start} 行 —— 不像「会判三态 + 逃生口」的实体（被判空？）"


def test_required_calls_present():
    """必备项齐（merge-base --is-ancestor / exit 2 / exit 3 / 逃生口 / ledger / 指引）。"""
    problems = judge_required(read_script())
    assert problems == [], "发布线自检段缺必备项：\n  " + "\n  ".join(problems)


def test_section_runs_before_any_deploy_action():
    """**本单核心**：该段必须早于任何真实部署动作（拉镜像 / 构建 / 起容器 / registry 登录）。"""
    problems = judge_order(read_script())
    assert problems == [], "顺序判据红：\n  " + "\n  ".join(problems)


def test_order_anchor_really_skips_echo_and_comment_lines():
    """反空跑：动作锚点**不吃**注释与 echo 文案（否则顺序判据恒真 = 没有判别力）。"""
    text = "# docker compose up -d\necho \"恢复：docker compose pull admin-api\"\ndocker compose up -d --no-deps nginx\n"
    found = first_real_action_lines(text)
    assert ("docker compose up", 3) in found, found
    assert all(line == 3 for _, line in found), f"锚点吃到了注释 / echo 文案：{found}"


# ── 二、行为：真跑那一段（桩化 git / docker） ─────────────────────────────────


def test_ancestor_passes_and_deploy_proceeds(tmp_path):
    """祖先 ⇒ `RELEASE-LINE=OK target=<sha7> release=<sha7>`，且后面的部署动作照常发生。"""
    r = run_section(tmp_path)
    assert r["rc"] == 0, r["out"]
    assert f"RELEASE-LINE=OK target={TARGET7} release={RELEASE7}" in r["out"], r["out"]
    assert r["docker_log"].strip(), "祖先场景下部署动作不该被拦住（docker 零调用）"
    assert r["ledger"] == "", "正常部署不写逃生口台账"


def test_non_ancestor_refuses_with_exit_2_and_no_docker_write(tmp_path):
    """非祖先 ⇒ rc=2、打印两个 sha/差多少提交、**零** docker 写调用。"""
    r = run_section(tmp_path, extra_env={"STUB_ANCESTOR": "0", "STUB_AHEAD": "12"})
    assert r["rc"] == 2, f"rc={r['rc']}（期望 2）\n{r['out']}"
    assert "RELEASE-LINE=VIOLATION" in r["out"], r["out"]
    assert TARGET_FULL in r["out"] and RELEASE_FULL in r["out"], r["out"]
    assert "12 个提交" in r["out"], r["out"]
    assert "cut-release.sh" in r["out"], r["out"]
    assert r["docker_log"] == "", f"非祖先却动了 docker：{r['docker_log']}"
    assert "SECTION-PASSED" not in r["out"], "非祖先却继续跑下去了"


def test_merge_base_receives_target_and_release_ref(tmp_path):
    """判据调的是 `merge-base --is-ancestor <target> refs/remotes/origin/release`（参数不许错位）。"""
    r = run_section(tmp_path)
    assert r["rc"] == 0, r["out"]
    mb = [ln for ln in r["git_log"].splitlines() if "merge-base" in ln]
    assert len(mb) == 1, f"merge-base 调用次数异常：{mb}"
    assert "--is-ancestor" in mb[0] and TARGET_FULL in mb[0], mb[0]
    assert "refs/remotes/origin/release" in mb[0], mb[0]


def test_fetch_retries_three_times_then_refuses_with_exit_3(tmp_path):
    """fetch 三次全失败 ⇒ rc=3（fail-closed），且重试**三次都出声**（不许静默）。"""
    r = run_section(tmp_path, extra_env={"STUB_FETCH_FAIL": "1"})
    assert r["rc"] == 3, f"rc={r['rc']}（期望 3）\n{r['out']}"
    assert "RELEASE-LINE=UNVERIFIED" in r["out"], r["out"]
    fetches = [ln for ln in r["git_log"].splitlines() if " fetch " in ln]
    assert len(fetches) == 3, f"fetch 次数 = {len(fetches)}（期望 3）\n{r['git_log']}"
    assert r["docker_log"] == "", f"判不了却动了 docker：{r['docker_log']}"
    assert r["ledger"] == "", "没有逃生口时不许落账（否则台账会把默认拒绝写成放行）"


def test_unresolvable_release_ref_is_unverifiable(tmp_path):
    """fetch 成功但拿不到 release ref ⇒ 判不了 ⇒ rc=3。"""
    r = run_section(tmp_path, extra_env={"STUB_NO_RELEASE": "1"})
    assert r["rc"] == 3, f"rc={r['rc']}（期望 3）\n{r['out']}"
    assert "取不到 origin/release 的 ref" in r["out"], r["out"]


def test_unresolvable_target_is_unverifiable(tmp_path):
    """追不到 target commit ⇒ 判不了 ⇒ rc=3（不许用短 sha 前缀「凑」一个祖先结论）。"""
    r = run_section(tmp_path, extra_env={"STUB_UNRESOLVED_TARGET": "1"})
    assert r["rc"] == 3, f"rc={r['rc']}（期望 3）\n{r['out']}"
    assert "追不到" in r["out"], r["out"]


def test_escape_hatch_continues_and_writes_ledger(tmp_path):
    """逃生口 ⇒ 继续部署 + `::warning::RELEASE-LINE=UNVERIFIED` + ledger 一行（JSON 可解析）。"""
    r = run_section(tmp_path, extra_env={"STUB_FETCH_FAIL": "1", "ALLOW_UNVERIFIABLE_RELEASE": "1"})
    assert r["rc"] == 0, f"rc={r['rc']}（逃生口应放行）\n{r['out']}"
    assert "::warning::RELEASE-LINE=UNVERIFIED" in r["out"], r["out"]
    assert r["docker_log"].strip(), "逃生口放行后部署动作应继续"
    lines = [ln for ln in r["ledger"].splitlines() if ln.strip()]
    assert len(lines) == 1, f"台账行数 = {len(lines)}（期望 1）\n{r['ledger']}"
    row = json.loads(lines[0])
    assert row["decision"] == "unverified-release", row
    assert row["target"] == TAG, row
    assert row["reason"], row
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", row["at"]), row


# ── 三、注入式红证（每次复原后上面两条必绿） ──────────────────────────────────


def _move_section_to_end(text: str) -> str:
    """红证 ①：把该段挪到文件**末尾**（= 一切 `docker compose up` / `pull` / `build` 之后）。"""
    lines = text.splitlines()
    start, end = section_span(text)
    section = lines[start - 1:end]
    rest = lines[:start - 1] + lines[end:]
    return "\n".join(rest + [""] + section) + "\n"


def _drop_line(text: str, needle: str) -> str:
    lines = [ln for ln in text.splitlines() if needle not in ln]
    return "\n".join(lines) + "\n"


def test_red_proof_1_section_after_deploy_is_red():
    """① 段挪到部署之后 ⇒ 顺序判据必红；复原（原文本）必绿。"""
    base = read_script()
    mutated = _move_section_to_end(base)
    problems = judge_order(mutated)
    assert problems, "把自检段挪到 `docker compose up` 之后，顺序判据**没有**变红（判据无判别力）"
    assert any("晚于部署" in p for p in problems), problems
    assert judge_order(base) == [], "原文本应当是绿的"


def test_red_proof_2_dropping_exit_2_is_red(tmp_path):
    """② 删掉 `exit 2` ⇒ 必填项判据红 **且** 非祖先场景被放行（行为面也红）。"""
    base = read_script()
    mutated = _drop_line(base, "    exit 2")
    assert len(mutated) < len(base), "注入没生效（没删到东西）"
    problems = judge_required(mutated)
    assert any("exit 2" in p for p in problems), problems
    r = run_section(tmp_path, section_body(mutated), extra_env={"STUB_ANCESTOR": "0"})
    assert r["rc"] != 2, "删掉 exit 2 后仍然 rc=2 ⇒ 注入没打中判据对象"
    assert r["docker_log"].strip(), "删掉 exit 2 后应当**错误地**继续部署（这正是要拦住的形态）"


def test_red_proof_3_dropping_ledger_append_is_red(tmp_path):
    """③ 去掉逃生口的 ledger 追加 ⇒ 必填项判据红 **且** 逃生口场景没有台账。

    ⚠️ 注入形态是「**改重定向**」（`>> "$RELEASE_LEDGER_FILE"` → `>/dev/null`）而不是「删那一行」：
    删掉 `if …; then` 那一行会留下语法残骸（bash 直接 rc=2），行为面就成了**语法错**而不是
    「跑了但没记账」—— 那种红证是假的（它证明不了判据抓的是「没留痕」）。
    """
    base = read_script()
    mutated = base.replace('>> "$RELEASE_LEDGER_FILE" 2>/dev/null', '>/dev/null 2>/dev/null')
    assert mutated != base, "注入没生效（没改到重定向）"
    problems = judge_required(mutated)
    assert any("RELEASE_LEDGER_FILE" in p or "追加" in p for p in problems), problems
    r = run_section(tmp_path, section_body(mutated),
                    extra_env={"STUB_FETCH_FAIL": "1", "ALLOW_UNVERIFIABLE_RELEASE": "1"})
    assert r["rc"] == 0, f"注入后应仍然放行（只是没记账），实测 rc={r['rc']}\n{r['out']}"
    assert "::warning::RELEASE-LINE=UNVERIFIED" in r["out"], r["out"]
    assert r["ledger"] == "", f"改掉追加后仍写了台账：{r['ledger']}"
    assert judge_required(base) == [], judge_required(base)


def test_red_proof_4_is_ancestor_replaced_by_rev_parse_is_red(tmp_path):
    """④ `merge-base --is-ancestor` 换成 `git rev-parse` ⇒ 必填项判据红 **且** 非祖先被误放行。"""
    base = read_script()
    mutated = base.replace(
        "rl_git merge-base --is-ancestor",
        "rl_git rev-parse",
    )
    assert mutated != base, "注入没生效（没替换到东西）"
    problems = judge_required(mutated)
    assert any("merge-base --is-ancestor" in p for p in problems), problems
    # 复原（原文本）必绿 —— 红证是「判据对注入敏感」，不是「判据本来就红」
    assert judge_required(base) == [], judge_required(base)
    r = run_section(tmp_path, section_body(mutated), extra_env={"STUB_ANCESTOR": "0"})
    assert r["rc"] == 0, f"换成 rev-parse 后本应**误放行**（rc=0），实测 rc={r['rc']}\n{r['out']}"
    assert r["docker_log"].strip(), "换成 rev-parse 后应当错误地继续部署"


# ── 环境作用域（2026-11-24 修 P0：闸门此前无环境判别，把测试环境锁死）─────────────

def test_non_prod_domain_skips_the_gate_loudly_and_touches_no_network(tmp_path):
    """测试环境（`migaozn.com`）发的是 **main 线上的分支提交** ⇒ 闸门必须**跳过并出声**，
    且**一次 git 调用都不发**（连 fetch 都不该试）。

    事故现场：run **45302667932**，`01:21:10Z` / `01:23:30Z` 两次
    `❌ RELEASE-LINE=UNVERIFIED ⇒ 拒绝部署`（PR #9100 的测试腿被自己的闸门锁死）。
    """
    r = run_section(tmp_path, extra_env={"MIGAO_RELEASE_LINE": "auto", "MIGAO_PUBLIC_DOMAIN": "migaozn.com"})
    assert r["rc"] == 0, r["out"]
    assert "RELEASE-LINE=SKIPPED reason=non-prod" in r["out"], r["out"]
    assert r["git_log"] == "", f"测试环境不该去取发布线；git 调用：{r['git_log']}"
    assert "SECTION-PASSED" in r["out"], "跳过闸门后部署应继续（否则测试环境发不出去）"


def test_prod_domain_auto_still_enforces(tmp_path):
    """生产域名（`cytda.com`）+ `auto` ⇒ 照旧判：非祖先 ⇒ rc=2（跳过的只是非生产）。"""
    r = run_section(tmp_path, extra_env={
        "MIGAO_RELEASE_LINE": "auto", "MIGAO_PUBLIC_DOMAIN": "cytda.com",
        "STUB_ANCESTOR": "0", "STUB_AHEAD": "12",
    })
    assert r["rc"] == 2, r["out"]
    assert "RELEASE-LINE=VIOLATION" in r["out"], r["out"]
    assert r["docker_log"] == "", f"非祖先却动了 docker：{r['docker_log']}"


def test_explicit_enforce_on_a_test_domain_also_checks(tmp_path):
    """显式 `enforce` ⇒ 即使域名是测试域也照判（生产侧加保险的口径）。"""
    r = run_section(tmp_path, extra_env={
        "MIGAO_RELEASE_LINE": "enforce", "MIGAO_PUBLIC_DOMAIN": "migaozn.com", "STUB_ANCESTOR": "0",
    })
    assert r["rc"] == 2, r["out"]
    assert "RELEASE-LINE=VIOLATION" in r["out"], r["out"]


def test_explicit_off_is_loud_not_silent(tmp_path):
    """显式 `off` ⇒ 跳过，但必须**出声**（静默跳过 = 这条判据等于没有）。"""
    r = run_section(tmp_path, extra_env={"MIGAO_RELEASE_LINE": "off", "MIGAO_PUBLIC_DOMAIN": "cytda.com"})
    assert r["rc"] == 0, r["out"]
    assert "RELEASE-LINE=SKIPPED" in r["out"], r["out"]
