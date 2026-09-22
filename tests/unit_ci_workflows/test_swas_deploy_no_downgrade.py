# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""`deploy/swas/deploy.sh` **「不许往回走」闸门**守卫 —— issue #4852（P0：排队的旧 run 静默回退生产）。

## 事故机理（**生产 CI 实测**，非推断）

三条部署腿共用**同一把 server 侧 flock**（`deploy/swas/deploy.sh`，窗口 600s）⇒ run 按**创建时刻**
排队，而 main 在排队期间前进 ⇒ **为旧 commit 创建的 run 会在更新的 run 成功之后才执行**：

| run | head | 创建 | 远端执行 | 实际部署 |
|---|---|---|---|---|
| `35499382654` deploy-admin-api | `56c8c5107` | 08:22 | ~08:30 | `sha-56c8c51` |
| `35499604094` deploy-admin-api | `ace521ff1` | 08:27 | ~08:38 | `sha-ace521f` |
| `35499280090` deploy-ai-agent | **`7b03ed3d7`** | **08:20** | **~08:42** | **`sha-7b03ed3`** ✗ |

第三条自己的日志里已经打出「回滚点 sha-ace521f」（= 它**知道**更新的部署刚成功）却仍然往回部署；
健康检查三个全 200、run 结论 success、`✅ SWAS 部署成功（tag=sha-7b03ed3）` ⇒ **三重绿、零告警**，
线上长期跑旧代码（`https://app.migaozn.com/s/<短码>` 实测 401 = 该 tag 早于 `/s/**` 放行）。

## 本文件锁什么

1. **闸门形态**（静态，读脚本**当前文本** —— §18.3：不读 `origin/main` 这类可变引用）：
   判据段（2.05）必须**在 flock 之内**、**在拉取/蓝绿之前**；逐服务取「**当前在跑**的 tag」
   （`docker compose ps -q` + `docker inspect`，不是 `.last-good-tag`）；拉取循环由闸门筛出的
   `$ALLOWED_SERVICES` 驱动；「往回走」⇒ **跳过该服务 + `::warning::`**（不静默）。
2. **判据语义**：祖先关系必须是**提交图**语义（锚点行 `git merge-base --is-ancestor` +
   `ancestry_verdict()` 的 `ahead/behind/identical/未知` 映射），**不是**字符串比较/时间戳。
3. **fail-open 但告警**：判不出（非 sha tag / 取不到在跑 tag / API 拿不到 / 分叉）⇒ 放行 + `::warning::`。
4. **显式回滚仍能往回走**（`ALLOW_DOWNGRADE=1` 由 `workflow_dispatch -f image_tag=` 路径注入，
   #4767 的自动回滚那次尝试同样带它）—— 日志必须写明「这是显式回滚」。
5. **本次实际生效 tag 逐服务一行**（`EFFECTIVE_TAG=<svc>:<tag>`）落 `$GITHUB_STEP_SUMMARY` +
   部署结论行（CI 侧 `deploy/scripts/swas-deploy-ci.sh` 解析并渲染）。
6. **既有护栏逐条不削弱**：flock 串行、#4785 严格蓝绿、#4767 失败即回滚 + 断路器、
   #4808 镜像保留策略与回滚点三道防线、`.blue-green-off` 逃生口、`wait_healthy` 唯一一份。

## 🔴 事故形态的**可执行复现**（本文件的重点）

桩化 docker/curl/flock/timeout，跑**真实 `deploy.sh` 的真实码路**：
「在跑的 tag = `sha-ace521f`（更新的那次刚成功）」+「本次 target = `sha-7b03ed3`（旧 run）」+
「compare 判据 = `ahead`（= target 是在跑的祖先）」这一组输入下：
· **修复后** ⇒ 三个服务**全被跳过** + 三条 `::warning::` + 零 `up -d`，`EFFECTIVE_TAG` 说的是在跑的那个；
· **修复前**（把闸门段机械剥离 = 改动前的码路）⇒ 三个服务**全被重建为旧 tag** + **零告警** + exit 0
  —— 与生产事故逐字同形（这就是「静默回退」的可执行复现）。

## ⚠️ 红证的真实性边界（**照实登记，不粉饰**）

执行式红证跑的是**本机 + 桩化的外部依赖**（docker / curl / flock / timeout），
**不是**真实 SWAS 环境实测；被桩化的是外部依赖，被测的是 `deploy.sh` 的**编排判据本身**。
真机只读观测（本 PR 采集，原文见 PR body）：服务器上 `git 2.43.7` 在、`api.github.com` 200/0.6s、
`git clone --filter=tree:0 https://github.com/...` **超时**（⇒ 判据走 compare API 而不是本地 git）、
`docker compose ps -q <svc>` + `docker inspect` 能取到各服务在跑 tag、`/usr/bin/python3` 在。
本机无 docker、无 SWAS 访问 ⇒ **本 PR 未做真实远端部署验证**（上真机后的可执行判据见
`docs/wiki/CI-CD.md` 的「不许往回走」小节）。
"""
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "deploy" / "swas" / "deploy.sh"
CI_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "swas-deploy-ci.sh"
WORKFLOWS = {
    name: REPO_ROOT / ".github" / "workflows" / name
    for name in ("deploy-admin-api.yml", "deploy-ai-agent-service.yml", "deploy-frontend.yml")
}

# 判据锚点（改脚本时这些字符串必须一起改；守卫测试据此判「判据是否还在」）
GATE_ANCHOR = "2.05 「不许往回走」闸门"
EFFECTIVE_ANCHOR = "== 2.1 本次实际生效 tag"
PULL_ANCHOR = "== 2. 拉取镜像"
SERVICES = ("admin-api", "ai-agent", "admin-web")
ALLOW_ENV = "${{ steps.tag.outputs.MODE == 'rollback' && '1' || '0' }}"

# 事故数据（**逐字取自生产 run**，见 issue #4852 的铁证表）
OLD_TAG = "sha-7b03ed3"      # 排到后面的旧 run 的目标 tag
NEW_TAG = "sha-ace521f"      # 更新的那次部署已生效的 tag（= 当前在跑）
FWD_TAG = "sha-9f9f9f9"      # 正常前进场景的目标 tag


# ══════════════════════════════════════════════════════════════════════════
# 读源 + 反空跑锚点
# ══════════════════════════════════════════════════════════════════════════

def read_deploy_sh() -> str:
    assert DEPLOY_SH.is_file(), f"反空跑锚点：目标脚本不存在 → {DEPLOY_SH}"
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert GATE_ANCHOR in text, (
        "反空跑锚点：deploy.sh 里找不到「不许往回走」闸门（判据已过期或脚本被改写）—— 这不是「通过」"
    )
    return text


def read_ci_script() -> str:
    assert CI_SCRIPT.is_file(), f"反空跑锚点：目标脚本不存在 → {CI_SCRIPT}"
    text = CI_SCRIPT.read_text(encoding="utf-8")
    assert "EFFECTIVE_TAG" in text, "反空跑锚点：CI 脚本里找不到 EFFECTIVE_TAG 解析（判据已过期）"
    assert "__ALLOW_DOWNGRADE__" in text, "反空跑锚点：CI 脚本里找不到降级许可占位符（判据已过期）"
    return text


def read_workflow(name: str) -> str:
    path = WORKFLOWS[name]
    assert path.is_file(), f"反空跑锚点：workflow 不存在 → {path}"
    return path.read_text(encoding="utf-8")


def non_comment(text: str) -> str:
    """剥掉**整行注释**后的代码行 —— 判据只判「真的会执行的那一行」。"""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def section(text: str, start_anchor: str, end_anchor: str) -> str:
    """取 [start_anchor, end_anchor) 之间的文本；取不到 ⇒ 显式失败（不是「通过」）。"""
    i = text.find(start_anchor)
    assert i >= 0, f"反空跑锚点：找不到段起点 {start_anchor!r}"
    j = text.find(end_anchor, i)
    assert j > i, f"反空跑锚点：找不到段终点 {end_anchor!r}（起点之后）"
    return text[i:j]


def function_body(text: str, name: str) -> str:
    """取 shell 函数体（`name() {` 到配对的 `}` 行）。取不到 ⇒ 显式失败。"""
    m = re.search(rf"^{re.escape(name)}\(\) \{{$", text, re.M)
    assert m, f"反空跑锚点：脚本里找不到函数 `{name}()`"
    end = text.find("\n}\n", m.end())
    assert end != -1, f"函数 `{name}()` 没有配对的收尾 `}}`（脚本语法已坏）"
    return text[m.end():end]


# ══════════════════════════════════════════════════════════════════════════
# 判据本体（二）：降级许可的**语义**判据（issue #5128）
#
# 被替换掉的旧判据是**逐字钉住一行字面量**：
#
#     bootstrap=${bootstrap//__ALLOW_DOWNGRADE__/$allow}
#
# 必须出现在 `deploy_attempt` 里。它防的是真事故（「许可渲染被搬走/重排 ⇒ 静默失效」），
# 但**失败信息不解释意图**，而且**钉住了实现位置**：#5120 的实现包把许可渲染搬进
# `render_bootstrap`（结果仍生效）就被误红 ⇒ 下一个重构者会看到「一条红判据 + 一个
# 看起来可以顺手放宽的断言」，而放宽它恰恰丢掉保护（issue #5128 正文）。
#
# ⇒ 本节的判据**只断言语义**：**真正发给远端执行的那条命令里，许可已被渲染成 `<allow>`**。
#    它不关心渲染点写在哪一行、在哪个函数里（合法重构不误红），
#    但四种真失效都会被抓住（见本节末尾的注入式红证，**每种单独一条**）：
#    ① 渲染点被**删** ② 渲染点被挪到**不生效**的位置（渲染进没人用的变量）
#    ③ 占位符从 `BOOTSTRAP` 模板里**消失**（渲染点成了空转） ④ 渲染成**常量**（`allow` 不生效）。
#    前三种的后果是「执行命令里仍留占位符 / 命令根本没发出去」，第四种是「许可值被写死」
#    —— 都是本单要防的**静默失效**（远端 deploy.sh 的闸门会按「许可状态未知」或错误许可放行/误挡）。
#
# 手法：把 `deploy_attempt` 及其调用链上的函数**原样抽出来**真跑（不重写、不复刻），
# 只桩掉 `run_cmd`（拦住 `aliyun` CLI）与 `nap`（不真等），并**捕获**它实际收到的
# `--command-content` —— 那就是远端真正会执行的那条命令。
# ══════════════════════════════════════════════════════════════════════════

# 抽函数用的段界：从「deploy.sh 与镜像 tag 同源」那一节（含 `bootstrap_tag_to_sha` /
# `bootstrap_ref_for_tag` / `render_bootstrap`）到**主流程**（主流程只调用 `deploy_attempt`）
PROBE_START = "# ⑤ 部署脚本**自己**也必须与镜像 tag 同源"
PROBE_END = "# ── 主流程 "
# `deploy_attempt` 调用链上的函数（缺任一个 ⇒ `function_body` 显式失败，不是「通过」）
PROBE_FUNCS = ("bootstrap_tag_to_sha", "bootstrap_ref_for_tag", "render_bootstrap", "deploy_attempt")
# 桩 `run_cmd`：把真正要执行的命令落盘，并回一个「三次都没 InvokeId」的响应（脚本随即走
# `RunCommand 三次均失败` 分支退出 —— 本判据只看**被执行命令的内容**，不看退出码）
RUN_CMD_STUB = """
run_cmd() {
  local k=$1 c=$2; shift 2
  local arg prev=""
  for arg in "$@"; do
    if [ "$prev" = "--command-content" ]; then printf '%s' "$arg" > "$CAPTURED_CMD"; fi
    prev=$arg
  done
  printf '%s' '{"InvokeId": ""}'
  return 0
}
nap() { return 0; }
"""


def bootstrap_template(ci_text: str, *, require_placeholder: bool = True) -> str:
    """取脚本里 `BOOTSTRAP="…"` 的**取值**（被渲染的模板）。

    ⚠️ 反空跑锚点：取不到 / 取成空串 ⇒ **显式失败**。少了它，探针会在「模板为空」下空跑
    ——`render_bootstrap` 渲染空串、`case *__ALLOW_DOWNGRADE__*` 不匹配 ⇒ 判据**恒绿**
    （本单实测踩到：探针第一版就是这样静默空跑的）。
    """
    m = re.search(r"^BOOTSTRAP=(.+)$", ci_text, re.M)
    assert m, "反空跑锚点：脚本里找不到 `BOOTSTRAP=` 模板（判据已过期）"
    value = _shell_double_quoted(m.group(1))
    assert value.strip(), "反空跑锚点：`BOOTSTRAP` 模板解析成空串 ⇒ 探针会空跑（不是「通过」）"
    if require_placeholder:
        assert "__ALLOW_DOWNGRADE__" in value, (
            "反空跑锚点：`BOOTSTRAP` 模板里没有许可占位符 ⇒ 语义判据无从施加（不是「通过」）"
        )
    return value


def _shell_double_quoted(raw: str) -> str:
    r"""取 shell 双引号字符串的**字面内容**（`\$` / `\"` 等转义**原样保留**）。

    ⚠️ 不能用 `shlex.split(posix=True)`：它会把 `\$` 解成 `$`、把 `\"` 解成 `"` ——
    模板一变形，`render_bootstrap` 里的字面量替换（`${IMAGE_TAG}` / `__BOOTSTRAP_REF__`）
    就匹配不上 ⇒ 渲染出半成品 ⇒ **探针静默跑偏**（本单实测踩到）。
    """
    i = raw.find('"')
    assert i >= 0, f"`BOOTSTRAP=` 不是双引号字符串（形态已变）：{raw[:80]!r}"
    out, j = [], i + 1
    while j < len(raw):
        ch = raw[j]
        if ch == "\\":
            out.append(raw[j:j + 2]); j += 2; continue
        if ch == '"':
            return "".join(out)
        out.append(ch); j += 1
    raise AssertionError(f"`BOOTSTRAP=` 的双引号没有闭合：{raw[:80]!r}")


def probe_region(ci_text: str) -> str:
    """`deploy_attempt` 及其调用链所在的段（`function_body` 只能取单个函数，这里取整段）。"""
    i = ci_text.find(PROBE_START)
    assert i >= 0, f"反空跑锚点：找不到 `deploy_attempt` 段的注释头 {PROBE_START!r}（判据已过期）"
    j = ci_text.find(PROBE_END, i)
    assert j > i, f"反空跑锚点：找不到主流程段 {PROBE_END!r}（判据已过期）"
    return ci_text[i:j]


def deploy_attempt_command(ci_text: str, tmp_path: Path, tag: str, allow: str,
                           *, require_placeholder: bool = True) -> str:
    """真跑 `deploy_attempt`，返回它**实际发给远端执行**的命令（`--command-content` 的值）。

    只桩外部依赖（`run_cmd` ⇒ `aliyun` CLI、`nap` ⇒ `sleep`）；被测的是脚本自己的渲染编排。
    """
    region = probe_region(ci_text)
    # 调用方按场景分子目录（每个场景各一份探针）⇒ 目录得先存在（否则捕获文件写不出）
    tmp_path.mkdir(parents=True, exist_ok=True)
    parts = [
        "set -uo pipefail",
        f'CAPTURED_CMD={shlex.quote(str(tmp_path / "captured-cmd"))}',
        'IMAGE_TAG="sha-1a1a1a1"',
        'INSTANCE_ID="i-probe"',
        'REGION="cn-probe"',
        'REGISTRY_SETUP=""',
        # 被渲染的模板本身（**必给**：缺了它渲染出空串 ⇒ 判据恒绿、探针空跑）。
        # ⚠️ 走**环境变量**而不是拼进源码：模板里带 `\$` / `\"` 转义，一旦经 shell 引号再解释
        #    一遍就会被改写（`${IMAGE_TAG}` 的替换随之失配 ⇒ 探针静默跑偏，本单实测踩到）。
        'BOOTSTRAP="$PROBE_BOOTSTRAP"',
        'DEPLOY_TIMEOUT_SECONDS=1',
        'CLI_TIMEOUT_SECONDS=1',
        'POLL_INTERVAL_SECONDS=0',
        'RETRY_PAUSE_SECONDS=0',
        'DEADLINE=$(( $(date +%s) + DEPLOY_TIMEOUT_SECONDS ))',
        'remaining_seconds() { echo $(( DEADLINE - $(date +%s) )); }',
    ]
    for name in PROBE_FUNCS:
        parts.append(f"{name}() {{{function_body(region, name)}\n}}")
    # ⚠️ 桩必须定义在**被抽出来的真实函数之后**：shell 函数是「后定义覆盖先定义」，
    #    反过来写会让脚本里那份真 `run_cmd`（要调 `aliyun` CLI）生效 ⇒ 探针静默跑偏。
    parts.append(RUN_CMD_STUB)
    parts.append(f'deploy_attempt {shlex.quote(tag)} {shlex.quote(allow)}')
    probe = "\n".join(parts)
    proc = subprocess.run(
        ["bash", "-c", probe], capture_output=True, text=True, timeout=60,
        env={**os.environ, "PROBE_BOOTSTRAP": bootstrap_template(
            ci_text, require_placeholder=require_placeholder)},
    )
    captured = tmp_path / "captured-cmd"
    if captured.is_file():
        return captured.read_text(encoding="utf-8")
    # 没捕获到 = `deploy_attempt` **在把命令交给远端之前就 fail-closed 早退**了（判据要抓的形态之一：
    # 命令根本没发出去 ⇒ 许可自然也没到远端）。这里**不能**报「反空跑失败」，而是返回空串让判据判红；
    # 真·空跑（脚本语法坏 / 抽不到函数）由 `function_body` 与 `bootstrap_template` 的反空跑锚点兜住。
    assert proc.returncode == 0, f"探针非预期失败（不是「许可未送达」那种早退）：\n{proc.stdout}\n{proc.stderr}"
    return ""


# ══════════════════════════════════════════════════════════════════════════
# 判据本体（纯函数：文本进 → 违规清单出；注入式红证驱动**同一份本体**）
# ══════════════════════════════════════════════════════════════════════════

def judge_gate_shape(text: str) -> list:
    """① 闸门在 flock 之内、在拉取/蓝绿之前；逐服务取「在跑 tag」；拉取循环由闸门筛出的集合驱动。"""
    v = []
    i_lock = text.find("flock -n 9")
    i_gate = text.find(GATE_ANCHOR)
    i_pull = text.find(PULL_ANCHOR)
    i_bg = text.find("2.5 严格蓝绿")
    if i_lock < 0:
        v.append("找不到 flock 获取行（并发串行护栏没了）")
    if i_pull < 0 or i_bg < 0:
        v.append("找不到拉取段（2.）或蓝绿段（2.5）—— 判据已过期")
    if i_lock >= 0 and i_gate < i_lock:
        v.append("闸门出现在 flock **之前** —— 两个部署会各自基于过期的「在跑 tag」判定（判据失效）")
    if i_gate > i_pull:
        v.append("闸门排在拉取段**之后** —— 拉取已经发生，跳过也不省事（且顺序与设计不符）")
    if i_gate > i_bg:
        v.append("闸门排在蓝绿段**之后** —— 容器已经被替换，闸门形同虚设")
    # 取「当前在跑」的判据必须是**运行中的容器**，不是 .last-good-tag（那是「上次成功」的记号）
    body = function_body(text, "running_tag_of")
    for token in ('docker compose ps -q "$svc"', "docker inspect --format '{{.Config.Image}}'"):
        if token not in body:
            v.append(f"`running_tag_of()` 里缺少 {token!r} —— 取不到「当前在跑」的容器 ⇒ 判据不成立")
    if "LAST_GOOD_FILE" in body or "rollback_tag" in body:
        v.append("`running_tag_of()` 读了 `.last-good-tag` —— 那是「上次成功」而不是「当前在跑」，判据会错")
    # 拉取循环必须由闸门筛出的集合驱动（否则跳过无效 = 静默回退）
    pull_sec = section(text, PULL_ANCHOR, EFFECTIVE_ANCHOR)
    if "for svc in $ALLOWED_SERVICES; do" not in pull_sec:
        v.append("拉取循环不是由 `$ALLOWED_SERVICES`（闸门筛出的集合）驱动 ⇒ 跳过不生效")
    if "for svc in admin-api ai-agent admin-web; do" in pull_sec:
        v.append("拉取循环仍无条件遍历三个服务 ⇒ 闸门被绕过")
    if non_comment(text).count('if timeout 180 docker compose pull "$svc"') != 1:
        v.append("逐服务拉取那一行被改动或复制（原本是「拉不到就跳过该服务」的唯一一份判据）")
    return v


def judge_verdict_semantics(text: str) -> list:
    """② 祖先关系 = **提交图**语义（`git merge-base --is-ancestor` 锚点 + 状态映射），不是字符串/时间戳。"""
    v = []
    if text.count("ancestry_verdict() {") != 1:
        v.append(f"`ancestry_verdict()` 定义出现 {text.count('ancestry_verdict() {')} 次（必须恰好 1 次）")
    if "git merge-base --is-ancestor <target> <current>" not in text:
        v.append("判据段没有写明「= `git merge-base --is-ancestor <target> <current>`」（语义锚点丢失）")
    body = function_body(text, "ancestry_verdict")
    if "$DOWNGRADE_API" not in body:
        v.append("`ancestry_verdict()` 没走 `$DOWNGRADE_API`（判据源被换掉或有第二条路径）")
    for pat, want in (
        (r"ahead\)\s+echo downgrade", "ahead ⇒ downgrade（current 在 target 之后 ⇒ target 是祖先）"),
        (r"behind\)\s+echo forward", "behind ⇒ forward（target 是后代 ⇒ 正常前进）"),
        (r"identical\)\s+echo same", "identical ⇒ same（同 commit 重跑）"),
        (r"\*\)\s+echo unknown", "其它 ⇒ unknown（fail-open + 告警）"),
    ):
        if not re.search(pat, body):
            v.append(f"`ancestry_verdict()` 缺少映射：{want}")
    gate = section(text, GATE_ANCHOR, PULL_ANCHOR)
    if not re.search(r'verdict=\$\(ancestry_verdict "\$TAG" "\$cur"\)', gate):
        v.append("闸门不是用 `ancestry_verdict` 得出判据（有第二条/别处的判据源 ⇒ 会漂移）")
    # 用字符串比较或时间戳当判据 = 本单明令禁止（sha-* 的字典序与提交序无关）
    for bad in (r'\[\s*"\$TAG"\s*[<>]', r'\[\s*"\$cur"\s*[<>]', r"docker inspect.*\.Created", r"\$\(date .*\).*verdict"):
        if re.search(bad, gate):
            v.append(f"闸门里出现字符串比较/时间戳当判据（禁止）：{bad}")
    return v


def judge_skip_and_fail_open(text: str) -> list:
    """③ 「往回走」⇒ 跳过 + `::warning::`；判不出 ⇒ fail-open **但必须告警**。"""
    v = []
    gate = section(text, GATE_ANCHOR, PULL_ANCHOR)
    m = re.search(r'elif \[ "\$verdict" = "downgrade" \]; then(.*?)\n  elif ', gate, re.S)
    if not m:
        v.append("找不到 `verdict = downgrade` 分支（判据已过期）")
    else:
        blk = m.group(1)
        if "::warning::" not in blk:
            v.append("「往回走」分支没有 `::warning::` ⇒ 静默回退（本单的事故形态）")
        if "continue" not in blk:
            v.append("「往回走」分支没有 `continue` ⇒ 该服务仍会被部署（跳过没生效）")
        if "SKIPPED_SERVICES=" not in blk:
            v.append("「往回走」没有记账（`SKIPPED_SERVICES`）⇒ summary 里无法给出被跳过的服务")
    m = re.search(r'elif \[ "\$verdict" = "unknown" \]; then(.*?)\n  fi\n', gate, re.S)
    if not m:
        v.append("找不到 `verdict = unknown` 分支（fail-open 判据已过期）")
    else:
        blk = m.group(1)
        if "::warning::" not in blk:
            v.append("判不出时没有 `::warning::` ⇒ 静默放行（等于把「无判据」伪装成「已判过」）")
        if "continue" in blk:
            v.append("判不出时 `continue`（跳过）—— issue 要求的是 **fail-open 但告警**，不是静默不部署")
    if "ALLOWED_SERVICES=\"$ALLOWED_SERVICES $svc\"" not in gate:
        v.append("闸门没有把服务加入 `$ALLOWED_SERVICES`（拉取循环接不上）")
    # 「一次部署内同『在跑 tag』只查一次 API」的缓存（匿名 API 限 60 次/小时/IP）
    if "VERDICT_CACHE_CUR" not in gate or "VERDICT_CACHE_VAL" not in gate:
        v.append("闸门里没有「同『在跑 tag』只查一次」的缓存 ⇒ 一次部署 3 次 API 调用，会撞匿名限额")
    return v


def judge_allow_downgrade(text: str) -> list:
    """④ 显式回滚仍能往回走：许可只能由**显式路径**注入，且日志写明「这是显式回滚」。"""
    v = []
    if "ALLOW_DOWNGRADE=${ALLOW_DOWNGRADE:-0}" not in text:
        v.append("deploy.sh 缺少 `ALLOW_DOWNGRADE=${ALLOW_DOWNGRADE:-0}`（缺省必须是「不给许可」）")
    gate = section(text, GATE_ANCHOR, PULL_ANCHOR)
    m = re.search(r'if \[ "\$ALLOW_DOWNGRADE" = "1" \]; then(.*?)\n  elif ', gate, re.S)
    if not m:
        v.append("闸门里找不到 `ALLOW_DOWNGRADE = 1` 放行分支（显式回滚会被误挡）")
    else:
        blk = m.group(1)
        if "显式回滚" not in blk:
            v.append("放行分支没有写明「这是显式回滚」")
        if "continue" in blk:
            v.append("放行分支竟然 `continue`（显式回滚被跳过 ⇒ 人回不去）")
    # 反向：许可不许在脚本里被硬打开
    if re.search(r"^ALLOW_DOWNGRADE=1", text, re.M):
        v.append("脚本里把 `ALLOW_DOWNGRADE` 硬写成 1（普通部署也会放行 ⇒ 闸门失效）")
    return v


def judge_effective_tags(text: str) -> list:
    """⑤ 「本次实际生效 tag」逐服务一行（含被闸门跳过的服务）。"""
    v = []
    sec = section(text, EFFECTIVE_ANCHOR, "2.5 严格蓝绿")
    if "for svc in admin-api ai-agent admin-web; do" not in sec:
        v.append("实际生效 tag 不是**逐服务**给出（必须是三个服务各一行）")
    if "EFFECTIVE_TAG=${svc}:${eff}" not in sec:
        v.append("找不到 `EFFECTIVE_TAG=${svc}:${eff}`（CI 侧解析的契约行）")
    if 'DOWNGRADE_SKIPPED=${svc}:${TAG}:' not in sec:
        v.append("找不到 `DOWNGRADE_SKIPPED=…`（被跳过的服务与判据数据没有落日志）")
    if 'case " $UP_SERVICES " in' not in sec or "eff=$TAG" not in sec:
        v.append("生效 tag 没有按「是否在 `$UP_SERVICES` 里」判定 ⇒ 跳过的服务会谎报本次 target")
    return v


def judge_rails_intact(text: str) -> list:
    """⑥ 既有护栏锚点逐条仍在（删任一条 ⇒ 判红）。"""
    v = []
    for token in ('exec 9>"$LOCK"', "flock -n 9", "flock -w 600 9", "trap 'flock -u 9' EXIT"):
        if token not in text:
            v.append(f"flock 串行护栏被改动：找不到 `{token}`")
    if text.count("wait_healthy() {") != 1:
        v.append(f"`wait_healthy()` 定义出现 {text.count('wait_healthy() {')} 次（必须恰好 1 份判据）")
    if "HC_RETRIES=${HC_RETRIES:-10}" not in text or "HC_INTERVAL_SECONDS=${HC_INTERVAL_SECONDS:-10}" not in text:
        v.append("健康检查重试预算被放宽（默认必须是 10 次 × 10s）")
    if non_comment(text).count('docker compose up -d --no-deps "$svc"') != 1:
        v.append("正式容器替换调用不是恰好 1 次（#4785 蓝绿的「验证后才切」前提被破坏）")
    if "BG_OFF_FILE=${BG_OFF_FILE:-" not in text or "跳过蓝绿预验证" not in text:
        v.append("`.blue-green-off` 逃生口被改动（#4785 的应急放行口）")
    # #4808 镜像保留策略 × 回滚点三道防线
    if text.count("cleanup_project_images() {") != 1:
        v.append("`cleanup_project_images()` 不是恰好 1 份（保留策略判据被复制/删除）")
    for token, why in (
        ('if [ -n "$prev" ] && [ "$tag" = "$prev" ]; then', "#4808 ②「不看保留集」的逐镜像护栏"),
        ("保留策略清理后回滚点", "#4808 ③ 清理后的事后自检告警"),
        ("RB_BEFORE", "#4808 ② 深度清理前后复核回滚点"),
        ("补回失败", "#4808 ② 从 ACR 补回失败即告警"),
    ):
        if token not in text:
            v.append(f"保留策略/回滚点护栏被削弱：找不到 `{token}`（{why}）")
    if text.count("report_rollback_point") < 3:
        v.append("`report_rollback_point` 调用点 <2 处（部署前后各一次的可观测性被砍）")
    return v


def judge_ci_wiring(ci_text: str, wf_texts: dict) -> list:
    """⑦ CI 侧接线：许可注入（含 #4767 自动回滚）+ 实际生效 tag 落 summary + 结论行。"""
    v = []
    if 'ALLOW_DOWNGRADE=${ALLOW_DOWNGRADE:-0}' not in ci_text:
        v.append("CI 脚本没有读 `ALLOW_DOWNGRADE`（许可永远送不到远端）")
    if re.search(r"case \"\$ALLOW_DOWNGRADE\" in\n\s+1\) ;;", ci_text) is None:
        v.append("CI 脚本没有「只认 1，其它一律当 0」的收敛（环境意外注入即可打开闸门）")
    if "export ALLOW_DOWNGRADE=__ALLOW_DOWNGRADE__;" not in ci_text:
        v.append("bootstrap 没有把许可注入远端 deploy.sh（闸门拿不到许可）")
    if "&& bash /opt/migao-deploy/deploy.sh ${IMAGE_TAG}" not in ci_text:
        v.append("bootstrap 的 deploy.sh 调用形态被改动（#4767 的原子安装形态是既有护栏）")
    # ⚠️ 降级许可的渲染**不在这里**做逐字判据（issue #5128）：逐字钉住一行会把「合法重构」
    #    （把渲染搬进 `render_bootstrap`、结果仍生效）误判成红，而失败信息也不解释意图。
    #    ⇒ 语义判据 = `judge_permit_reaches_the_executed_command()`
    #      （真跑在 `test_executed_command_carries_the_rendered_permit()` 里）：
    #      **真正发给远端执行的命令里，许可占位符必须已被替换掉**（残留 = 静默失效 ⇒ 红）。
    #      下面两条仍是**便宜的结构性前哨**（占位符存在 + 渲染后仍留占位符会报错），
    #      与语义判据互补：前哨能给出「为什么」的可读失败信息，语义判据才是真正拦得住的那条。
    if "__ALLOW_DOWNGRADE__" not in ci_text:
        v.append("BOOTSTRAP 模板里没有许可占位符 ⇒ 降级许可根本无从注入（闸门会拒掉显式回滚）")
    if "*__ALLOW_DOWNGRADE__*" not in ci_text or "降级许可注入未生效" not in ci_text:
        v.append("渲染后仍留占位符时不报错 ⇒ 会在「许可状态未知」下静默部署")
    if 'local tag=$1 allow=${2:-0}' not in ci_text:
        v.append("`deploy_attempt` 没有 per-attempt 的许可参数（自动回滚那次尝试无法单独放行）")
    if 'deploy_attempt "$ROLLBACK_TAG" 1' not in ci_text:
        v.append("#4767 的自动回滚没有带显式降级许可 ⇒ 回滚会被新闸门挡掉（削弱既有护栏）")
    if "显式回滚" not in ci_text:
        v.append("CI 侧没有写明「这是显式回滚」")
    # 实际生效 tag：解析 + 渲染 + 落 summary + 结论行
    for token, why in (
        ("sed -n 's/^ *EFFECTIVE_TAG=//p'", "解析远端逐服务生效 tag"),
        ("sed -n 's/^ *DOWNGRADE_SKIPPED=//p'", "解析被闸门跳过的服务"),
        ("report_effective_tags", "把生效 tag 写进 summary"),
        ("effective_suffix", "把生效 tag 拼进部署结论行"),
    ):
        if token not in ci_text:
            v.append(f"CI 侧缺少「{why}」（{token}）")
    if ci_text.count("report_effective_tags") < 4:
        v.append(
            f"`report_effective_tags` 调用点 {ci_text.count('report_effective_tags')} < 3 处"
            "（第 1 次 / 自动重试 / 回滚 三条路径都要报）"
        )
    if ci_text.count("$(effective_suffix)") < 3:
        v.append("部署结论行（成功/重试成功/已回滚）没有逐条带上「实际生效 tag」")
    # workflow 侧：许可只能由 MODE=rollback 这条显式路径给出
    for name, text in wf_texts.items():
        if f"ALLOW_DOWNGRADE: {ALLOW_ENV}" not in text:
            v.append(f"{name}: Deploy 步骤没有按 MODE=rollback 注入 `ALLOW_DOWNGRADE: {ALLOW_ENV}`")
        if re.search(r"ALLOW_DOWNGRADE: ['\"]?1['\"]?\s*$", text, re.M):
            v.append(f"{name}: `ALLOW_DOWNGRADE` 被硬写成 1（普通 push 部署也会放行）")
        if "MODE=rollback" not in text or "MODE=build" not in text:
            v.append(f"{name}: 找不到 MODE=rollback/build 的判定（许可注入的前提没了）")
    return v


def all_deploy_violations(text: str) -> list:
    return (
        judge_gate_shape(text)
        + judge_verdict_semantics(text)
        + judge_skip_and_fail_open(text)
        + judge_allow_downgrade(text)
        + judge_effective_tags(text)
        + judge_rails_intact(text)
    )


# ══════════════════════════════════════════════════════════════════════════
# 一、静态判据（读脚本当前文本）
# ══════════════════════════════════════════════════════════════════════════

def test_real_files_satisfy_every_judgement():
    text = read_deploy_sh()
    v = all_deploy_violations(text)
    assert v == [], "闸门判据未满足：\n- " + "\n- ".join(v)
    v = judge_ci_wiring(read_ci_script(), {n: read_workflow(n) for n in WORKFLOWS})
    assert v == [], "CI 侧接线未满足：\n- " + "\n- ".join(v)


@pytest.mark.parametrize("judge_name", [
    "judge_gate_shape",
    "judge_verdict_semantics",
    "judge_skip_and_fail_open",
    "judge_allow_downgrade",
    "judge_effective_tags",
    "judge_rails_intact",
])
def test_each_deploy_judge_is_clean_on_the_real_script(judge_name):
    """逐条判据在真实脚本上各自干净（避免一条恒红被「整体红」掩盖）。"""
    v = globals()[judge_name](read_deploy_sh())
    assert v == [], f"{judge_name} 判红：\n- " + "\n- ".join(v)


def test_scripts_are_syntactically_valid():
    """`bash -n` 语法自检：这两个脚本语法错 = **停掉所有人的部署**。"""
    for path in (DEPLOY_SH, CI_SCRIPT):
        proc = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert proc.returncode == 0, f"{path.name} 语法错误：\n{proc.stderr}"


def test_workflows_are_valid_yaml_and_permissions_unchanged():
    """workflow 仍是合法 YAML，且部署 job 的必需护栏（concurrency/超时）没被顺手改掉。"""
    for name in WORKFLOWS:
        doc = yaml.safe_load(read_workflow(name))
        assert doc["permissions"] == {"contents": "read"}, f"{name}: permissions 被放宽"
        job = doc["jobs"]["build-and-deploy"]
        assert job["timeout-minutes"] == 45, f"{name}: 硬超时兜底（#4767 ①）被改动"
        assert job["concurrency"]["cancel-in-progress"] is False, f"{name}: 部署并发语义被改动"


# ══════════════════════════════════════════════════════════════════════════
# 二、注入式红证（每条判据各自可独立判红；注入必须真的落到文本上）
# ══════════════════════════════════════════════════════════════════════════

def _inject(text: str, old: str, new: str) -> str:
    """替换注入；**没替换到 ⇒ 显式失败**（否则「注入式红证」是空跑）。"""
    assert old in text, f"注入锚点不存在（判据已过期）：{old[:70]!r}"
    out = text.replace(old, new, 1)
    assert out != text, "注入没有改变文本（空跑）"
    return out


def test_injection_remove_gate_warning_goes_red():
    """注入①：把「往回走」分支的 `::warning::` 删掉（= 静默回退）⇒ 必红。"""
    text = read_deploy_sh()
    injected = _inject(
        text,
        '    echo "  ::warning::${svc} **跳过**：target=${TAG} 是**当前在跑 tag=${cur} 的祖先**',
        '    echo "  ${svc} 跳过：target=${TAG} 是**当前在跑 tag=${cur} 的祖先**',
    )
    assert judge_skip_and_fail_open(injected) != [], "去掉告警后判据没红（判据无判别力）"


def test_injection_remove_skip_continue_goes_red():
    """注入②：把「往回走」分支的 `continue` 删掉（= 仍然部署旧 tag）⇒ 必红。"""
    text = read_deploy_sh()
    injected = _inject(
        text,
        '    SKIPPED_SERVICES="$SKIPPED_SERVICES $svc"\n    continue\n',
        '    SKIPPED_SERVICES="$SKIPPED_SERVICES $svc"\n',
    )
    assert judge_skip_and_fail_open(injected) != [], "去掉跳过后判据没红（判据无判别力）"


def test_injection_flip_verdict_mapping_goes_red():
    """注入③：把 `ahead ⇒ downgrade` 的映射改掉（= 判据语义反了）⇒ 必红。"""
    text = read_deploy_sh()
    injected = _inject(text, "    ahead)     echo downgrade ;;", "    ahead)     echo forward ;;")
    assert judge_verdict_semantics(injected) != [], "改反映射后判据没红（判据无判别力）"


def test_injection_allow_downgrade_default_on_goes_red():
    """注入④：`ALLOW_DOWNGRADE` 缺省改成 1（= 闸门对普通部署也放行）⇒ 必红。"""
    text = read_deploy_sh()
    injected = _inject(
        text,
        "ALLOW_DOWNGRADE=${ALLOW_DOWNGRADE:-0}",
        "ALLOW_DOWNGRADE=${ALLOW_DOWNGRADE:-1}",
    )
    assert judge_allow_downgrade(injected) != [], "缺省放行后判据没红（判据无判别力）"


def test_injection_drop_effective_tag_lines_goes_red():
    """注入⑤：删掉「逐服务实际生效 tag」⇒ 必红（这正是不变量 3 的判据）。"""
    text = read_deploy_sh()
    injected = _inject(text, 'echo "  EFFECTIVE_TAG=${svc}:${eff}"', 'echo "  tag=${eff}"')
    assert judge_effective_tags(injected) != [], "删掉生效 tag 后判据没红（判据无判别力）"


def test_injection_bypass_gate_in_pull_loop_goes_red():
    """注入⑥：拉取循环不再走闸门筛出的集合（= 闸门被绕过）⇒ 必红。"""
    text = read_deploy_sh()
    injected = _inject(
        text,
        "for svc in $ALLOWED_SERVICES; do\n  if timeout 180 docker compose pull",
        "for svc in admin-api ai-agent admin-web; do\n  if timeout 180 docker compose pull",
    )
    assert judge_gate_shape(injected) != [], "绕过闸门后判据没红（判据无判别力）"


def test_injection_drop_running_container_criterion_goes_red():
    """注入⑦：`running_tag_of` 改成读 `.last-good-tag`（= 判据换成「上次成功」）⇒ 必红。"""
    text = read_deploy_sh()
    injected = _inject(
        text,
        '  cid=$(docker compose ps -q "$svc" 2>/dev/null || true)',
        '  cid=$(rollback_tag)',
    )
    assert judge_gate_shape(injected) != [], "换掉在跑判据后没红（判据无判别力）"


def test_injection_weaken_existing_rails_goes_red():
    """注入⑧：削弱一条**既有**护栏（回滚点的独立护栏）⇒ 必红（护栏不许被顺手砍）。"""
    text = read_deploy_sh()
    injected = _inject(
        text,
        '    if [ -n "$prev" ] && [ "$tag" = "$prev" ]; then',
        '    if false; then',
    )
    assert judge_rails_intact(injected) != [], "削弱既有护栏后没红（判据无判别力）"


def test_injection_ci_rollback_without_permit_goes_red():
    """注入⑨：自动回滚不带降级许可（= #4767 的回滚会被闸门挡掉）⇒ 必红。"""
    ci = read_ci_script()
    injected = _inject(ci, 'deploy_attempt "$ROLLBACK_TAG" 1', 'deploy_attempt "$ROLLBACK_TAG" 0')
    assert judge_ci_wiring(injected, {n: read_workflow(n) for n in WORKFLOWS}) != [], (
        "回滚不带许可后判据没红（判据无判别力）"
    )


def test_injection_ci_drop_summary_report_goes_red():
    """注入⑩：CI 侧不再把生效 tag 落 summary（= 不变量 3 的落点消失）⇒ 必红。"""
    ci = read_ci_script()
    injected = ci.replace("report_effective_tags\n", "")
    assert injected != ci, "注入没有改变文本（空跑）"
    assert judge_ci_wiring(injected, {n: read_workflow(n) for n in WORKFLOWS}) != [], (
        "去掉 summary 上报后判据没红（判据无判别力）"
    )


def test_injection_workflow_permit_always_on_goes_red():
    """注入⑪：把 workflow 的许可固定成 1（= 人人都能往回部署）⇒ 必红。"""
    wfs = {n: read_workflow(n) for n in WORKFLOWS}
    wfs["deploy-admin-api.yml"] = _inject(
        wfs["deploy-admin-api.yml"], f"ALLOW_DOWNGRADE: {ALLOW_ENV}", "ALLOW_DOWNGRADE: '1'",
    )
    assert judge_ci_wiring(read_ci_script(), wfs) != [], "许可固定为 1 后判据没红（判据无判别力）"


# ══════════════════════════════════════════════════════════════════════════
# 三、执行式红证（桩 docker/curl/flock/timeout，跑真实 deploy.sh 的真实码路）
# ══════════════════════════════════════════════════════════════════════════

CURL_STUB = """#!/bin/bash
# 桩 curl：① codeload 源码包 → 预置 tar；② 健康检查 → 按 $HC_STATE/hc-<端口>；
#          ③ GitHub compare API → 按 $ANCESTRY_DIR/<target>..<current> 回放 `status`
out=""; url=""; fmt=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w) fmt="$2"; shift 2 ;;
    -H) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in
  *codeload.github.com*) cp "$STUB_TAR" "$out"; exit 0 ;;
  *api.github.com*)
    pair=${url##*/}
    echo "$pair" >> "$API_CALL_LOG"
    st=$(cat "$ANCESTRY_DIR/$pair" 2>/dev/null || true)
    # 没有回放文件 ⇒ 按 `curl -f` 的失败语义退出（模拟「API 取不到」⇒ 判据必须 fail-open + 告警）
    if [ -z "$st" ]; then exit 22; fi
    # **真实响应形态**：顶层 status 在前，后面还有 commits[].status（= 解析必须认顶层那一个）
    printf '{"url": "https://api.github.com/repos/zhaokai-mgzn/migao/compare/%s", "status": "%s", "ahead_by": 4, "behind_by": 0, "commits": [{"status": "modified"}]}\\n' "$pair" "$st"
    exit 0 ;;
esac
port=$(printf '%s' "$url" | sed -n 's#^http://127\\.0\\.0\\.1:\\([0-9][0-9]*\\)/.*#\\1#p')
code=$(cat "$HC_STATE/hc-$port" 2>/dev/null || echo 200)
if [ -n "$out" ]; then : > "$out"; fi
if [ -n "$fmt" ]; then printf '%s' "$code"; fi
exit 0
"""

DOCKER_STUB = """#!/bin/bash
# 桩 docker：记录调用（顺序敏感）；`compose ps -q <svc>` / `inspect --format … <cid>` 回放
# $RUNNING_DIR/<svc> 里的「当前在跑」镜像（文件不存在 ⇒ 该服务没有在跑容器）
echo "docker $*" >> "$DOCKER_LOG"
last=""; for a in "$@"; do last="$a"; done
case "$1 $2" in
  "compose ps")
    if [ -f "$RUNNING_DIR/$last" ]; then echo "cid-$last"; fi
    exit 0 ;;
esac
case "$1" in
  inspect)
    svc=${last#cid-}
    if [ -f "$RUNNING_DIR/$svc" ]; then cat "$RUNNING_DIR/$svc"; fi
    exit 0 ;;
  compose)
    case "$*" in *exec*) exit "${STUB_RELOAD_RC:-0}" ;; esac
    exit 0 ;;
esac
exit 0
"""

FLOCK_STUB = """#!/bin/bash
# 桩 flock：no-op（macOS 无 flock；锁语义由既有守卫 test_swas_deploy_blue_green.py 静态覆盖）
exit 0
"""

TIMEOUT_STUB = """#!/bin/bash
# 桩 timeout：只透传（测的是 deploy.sh 的编排，不是 timeout 本身）
shift
exec "$@"
"""


def _write_exe(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _make_src_tar(dest: Path) -> None:
    """造一个 `migao-main/deploy/swas/*` 的 tar（配合 `--strip-components=1`）。"""
    stage = dest.parent / "stage" / "migao-main" / "deploy" / "swas"
    stage.mkdir(parents=True, exist_ok=True)
    for name in ("docker-compose.yml", "docker-compose.bluegreen.yml", "nginx.conf"):
        shutil.copy(REPO_ROOT / "deploy" / "swas" / name, stage / name)
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(dest.parent / "stage" / "migao-main", arcname="migao-main")


def _prepare(tmp_path: Path, script_text: str) -> tuple:
    """沙箱：脚本副本（改写绝对路径）+ 桩 bin + 源码 tar + .env 文件。"""
    work = tmp_path / "opt-migao-deploy"
    work.mkdir(parents=True, exist_ok=True)
    text = script_text
    # 绝对路径改写（同 test_swas_deploy_blue_green.py / test_swas_deploy_ci_bootstrap.py 的既有手法）：
    # 只改**路径**，不改逻辑
    text = text.replace("/opt/migao-deploy", str(work))
    text = text.replace("/tmp/migao-deploy.lock", str(work / "deploy.lock"))
    text = text.replace("/tmp/hc_", f"{work}/hc_")
    script = work / "deploy.sh"
    script.write_text(text, encoding="utf-8")
    # 配置 fail-closed 前置：显式声明 SMS_BYPASS_CODE（否则脚本按设计中止）
    (work / ".env.admin-api").write_text("SMS_BYPASS_CODE=123456\n", encoding="utf-8")
    (work / ".env.ai-agent").write_text("SMS_BYPASS_CODE=123456\n", encoding="utf-8")
    tar_path = tmp_path / "src.tar.gz"
    _make_src_tar(tar_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_exe(bin_dir / "curl", CURL_STUB)
    _write_exe(bin_dir / "docker", DOCKER_STUB)
    _write_exe(bin_dir / "flock", FLOCK_STUB)
    _write_exe(bin_dir / "timeout", TIMEOUT_STUB)
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    return work, script, bin_dir, state, tar_path


def _run(tmp_path: Path, script_text: str, *, running: dict, ancestry: dict,
         tag: str = OLD_TAG, extra_env: dict | None = None):
    """跑脚本。

    running:  {服务: tag} —— 「当前在跑」的镜像 tag（缺该服务 ⇒ 没有在跑容器 ⇒ 判据 unknown）
    ancestry: {"<target>..<current>": status} —— compare API 的回放（缺 ⇒ API 取不到）
    """
    work, script, bin_dir, state, tar_path = _prepare(tmp_path, script_text)
    running_dir = tmp_path / "running"
    running_dir.mkdir(exist_ok=True)
    repos = {"admin-api": "admin-api", "ai-agent": "ai-agent-service", "admin-web": "admin-web"}
    for svc, t in running.items():
        (running_dir / svc).write_text(f"reg.example.com/ai-customer-service/{repos[svc]}:{t}\n", encoding="utf-8")
    anc_dir = tmp_path / "ancestry"
    anc_dir.mkdir(exist_ok=True)
    for pair, status in ancestry.items():
        (anc_dir / pair).write_text(status, encoding="utf-8")
    docker_log = tmp_path / "docker.log"
    docker_log.write_text("", encoding="utf-8")
    api_log = tmp_path / "api.log"
    api_log.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DOCKER_LOG": str(docker_log),
        "API_CALL_LOG": str(api_log),
        "RUNNING_DIR": str(running_dir),
        "ANCESTRY_DIR": str(anc_dir),
        "HC_STATE": str(state),
        "STUB_TAR": str(tar_path),
        "HC_RETRIES": "2",
        "HC_INTERVAL_SECONDS": "0",
        # /proc/meminfo 在 macOS 不存在 ⇒ 预检恒判 0MB；把门槛设为 0 以聚焦编排
        "BG_MEM_NEED_MB": "0",
        "BG_OFF_FILE": str(work / ".blue-green-off"),
        **(extra_env or {}),
    }
    proc = subprocess.run(
        ["bash", str(script), tag],
        cwd=str(work), env=env, capture_output=True, text=True, timeout=300,
    )
    return proc, docker_log.read_text(encoding="utf-8"), api_log.read_text(encoding="utf-8")


def _accident_inputs() -> tuple:
    """事故形态的输入（**逐字取自生产 run #4852**）：旧 run 排到更新的一次之后。"""
    running = {svc: NEW_TAG for svc in SERVICES}
    # compare/7b03ed3...ace521f ⇒ ahead（= current 在 target 之后 ⇒ target 是祖先 ⇒ 往回走）
    ancestry = {f"{OLD_TAG[4:]}...{NEW_TAG[4:]}": "ahead"}
    return running, ancestry


def _deployed_services(log: str) -> list:
    """docker 桩日志里**正式容器**被 `up -d` 替换过的服务（`*-green` 不算）。"""
    return [
        svc for svc in SERVICES
        if re.search(rf"up -d --no-deps {re.escape(svc)}$", log, re.M)
    ]


def test_exec_accident_is_skipped_with_warning(tmp_path):
    """🔴 红证（本单验收判据 ①）：**旧 tag 排在新 tag 之后执行 ⇒ 跳过 + 告警**。

    输入 = 生产事故逐字：在跑 `sha-ace521f`（更新的那次刚成功）/ target `sha-7b03ed3`（旧 run）/
    判据 `ahead`（target 是在跑的祖先）。断言：三个服务**一个都不许被替换**、
    三条 `::warning::`、零 `up -d --no-deps <svc>`、`EFFECTIVE_TAG` 说的仍是**在跑的那个**。
    """
    running, ancestry = _accident_inputs()
    proc, log, _ = _run(tmp_path, read_deploy_sh(), running=running, ancestry=ancestry)
    assert proc.returncode == 0, f"闸门跳过不应让部署失败：\n{proc.stdout}\n{proc.stderr}"
    for svc in SERVICES:
        assert f"::warning::{svc} **跳过**" in proc.stdout, (
            f"{svc} 没有被明确跳过并告警：\n{proc.stdout}"
        )
        assert f"EFFECTIVE_TAG={svc}:{NEW_TAG}" in proc.stdout, (
            f"{svc} 的「实际生效 tag」没有说是**在跑的那个**：\n{proc.stdout}"
        )
        assert f"DOWNGRADE_SKIPPED={svc}:{OLD_TAG}:{NEW_TAG}" in proc.stdout, (
            f"{svc} 缺 `DOWNGRADE_SKIPPED` 判据数据（事后无法对账）：\n{proc.stdout}"
        )
    assert _deployed_services(log) == [], (
        "旧 run 把服务重建成了旧 tag（= 事故形态仍然发生）：\n" + log
    )
    assert not re.search(rf"compose pull {re.escape('admin-api')}$", log, re.M), (
        "被跳过的服务仍然被 pull（跳过应发生在拉取**之前**）:\n" + log
    )
    # nginx 仍照常更新（闸门只针对三个带 tag 的服务；「跳过」不等于「本次不部署」）
    assert re.search(r"up -d --no-deps nginx$", log, re.M), "nginx 没有被更新（流程没走完）:\n" + log


def test_exec_pre_fix_form_silently_downgrades(tmp_path):
    """🔴 事故形态的**修复前复现**（判别力红证）：同一组输入 + 剥离闸门的码路 ⇒ 静默回退 + 三重绿。

    「修复前」= 把闸门段（2.05）与生效 tag 段（2.1）机械剥离、拉取循环还原成无条件遍历三个服务
    —— 这正是本 PR 之前 `deploy.sh` 的码路（闸门是**纯增量**，没有动拉取/蓝绿/告警任何一行）。
    """
    old = _pre_fix_script(read_deploy_sh())
    running, ancestry = _accident_inputs()
    proc, log, _ = _run(tmp_path, old, running=running, ancestry=ancestry)
    assert proc.returncode == 0, f"修复前的码路本来就报 success（三重绿的一部分）：\n{proc.stdout}"
    assert sorted(_deployed_services(log)) == sorted(SERVICES), (
        "修复前的码路居然没有回退服务（判据锚点已过期）：\n" + log
    )
    assert not re.search(r"::warning::.*(跳过|往回走)", proc.stdout), (
        f"修复前的码路居然告警了（= 事故的「零告警」不复现）：\n{proc.stdout}"
    )
    assert "EFFECTIVE_TAG=" not in proc.stdout, (
        "修复前的码路居然给了逐服务生效 tag（= 事故的「说法误导」不复现）"
    )
    assert "✅ SWAS 部署成功" not in proc.stdout, (
        "deploy.sh 不该自己下「部署成功」结论（那是 CI 侧的话；这里只是防止判据与 CI 混淆）"
    )


def test_exec_forward_deploy_still_updates_everything(tmp_path):
    """正向：正常前进（在跑的是 target 的祖先）⇒ 三个服务照常部署、零「往回走」告警。"""
    running = {svc: NEW_TAG for svc in SERVICES}
    ancestry = {f"{FWD_TAG[4:]}...{NEW_TAG[4:]}": "behind"}
    proc, log, _ = _run(tmp_path, read_deploy_sh(), running=running, ancestry=ancestry, tag=FWD_TAG)
    assert proc.returncode == 0, f"正常前进被挡了：\n{proc.stdout}\n{proc.stderr}"
    assert sorted(_deployed_services(log)) == sorted(SERVICES), f"有服务没被部署：\n{log}"
    assert "**跳过**" not in proc.stdout, f"正常前进却出现「跳过」：\n{proc.stdout}"
    assert "允许部署=[admin-api ai-agent admin-web]" in proc.stdout, proc.stdout
    for svc in SERVICES:
        assert f"EFFECTIVE_TAG={svc}:{FWD_TAG}" in proc.stdout, proc.stdout


def test_exec_explicit_rollback_still_moves_backwards(tmp_path):
    """🔴 红证（验收判据 ②）：**显式回滚**（`ALLOW_DOWNGRADE=1`）⇒ 仍能往回走 + 日志写明。"""
    running, ancestry = _accident_inputs()
    proc, log, _ = _run(
        tmp_path, read_deploy_sh(), running=running, ancestry=ancestry,
        extra_env={"ALLOW_DOWNGRADE": "1"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sorted(_deployed_services(log)) == sorted(SERVICES), (
        f"显式回滚被闸门挡住了（人回不去）:\n{log}"
    )
    assert "**这是显式回滚**" in proc.stdout, f"日志没有写明「这是显式回滚」：\n{proc.stdout}"
    assert "**跳过**" not in proc.stdout, f"显式回滚不该跳过：\n{proc.stdout}"
    assert "允许部署=[admin-api ai-agent admin-web]" in proc.stdout, proc.stdout
    for svc in SERVICES:
        assert f"EFFECTIVE_TAG={svc}:{OLD_TAG}" in proc.stdout, proc.stdout


def test_exec_unknown_verdict_fails_open_with_warning(tmp_path):
    """判不出（API 取不到）⇒ **放行但告警**（fail-open，不静默）—— 判据不许把「未知」当「已判过」。"""
    running = {svc: NEW_TAG for svc in SERVICES}
    proc, log, _ = _run(tmp_path, read_deploy_sh(), running=running, ancestry={})
    assert proc.returncode == 0, f"fail-open 抛错会变成「部署被挡」：\n{proc.stdout}"
    assert sorted(_deployed_services(log)) == sorted(SERVICES), f"fail-open 没有放行：\n{log}"
    for svc in SERVICES:
        assert f"::warning::{svc} 判不出" in proc.stdout, (
            f"{svc} 判不出却没有告警（静默放行 = 把「无判据」伪装成「已判过」）：\n{proc.stdout}"
        )


def test_exec_no_running_container_fails_open(tmp_path):
    """首次部署（没有在跑容器）⇒ 判不出 ⇒ fail-open + 告警，不许因此挡住首次上线。"""
    proc, log, _ = _run(tmp_path, read_deploy_sh(), running={}, ancestry={})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sorted(_deployed_services(log)) == sorted(SERVICES), f"首次部署被挡：\n{log}"
    for svc in SERVICES:
        assert f"::warning::{svc} 判不出" in proc.stdout, proc.stdout


def test_exec_non_sha_tag_fails_open(tmp_path):
    """`latest` 这类非 sha tag 没有提交序 ⇒ fail-open + 告警（不许拿字符串比较硬判）。"""
    running = {svc: NEW_TAG for svc in SERVICES}
    # 即使 API 桩**故意**回放 ahead（说明「不该被查询」），非 sha tag 也必须走 unknown 分支
    ancestry = {f"latest..{NEW_TAG[4:]}": "ahead"}
    proc, log, _ = _run(tmp_path, read_deploy_sh(), running=running, ancestry=ancestry, tag="latest")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert sorted(_deployed_services(log)) == sorted(SERVICES), f"非 sha tag 被挡：\n{log}"
    for svc in SERVICES:
        assert f"::warning::{svc} 判不出" in proc.stdout, proc.stdout


def _skipped_services_from(stdout: str) -> list:
    """从 stdout 的 `EFFECTIVE_TAG=<svc>:<tag>` 反推被跳过的服务（生效 tag ≠ 本次 target）。

    （`_deployed_services` 读的是 docker 桩日志；这一条是**不依赖日志**的交叉判据。）
    """
    out = []
    for svc in SERVICES:
        m = re.search(rf"EFFECTIVE_TAG={re.escape(svc)}:(\S+)", stdout)
        assert m, f"stdout 里找不到 {svc} 的 EFFECTIVE_TAG：\n{stdout}"
        if m.group(1) != OLD_TAG:
            out.append(svc)
    return out


def test_exec_only_one_api_call_per_distinct_running_tag(tmp_path):
    """一次部署内同「在跑 tag」**只查一次** API（匿名 API 限 60 次/小时/IP；三个服务同 tag ⇒ 1 次）。

    判据 = 桩 curl 的**调用流水**（`$API_CALL_LOG`），不是「看起来只调了一次」。
    """
    running, ancestry = _accident_inputs()
    proc, _, api = _run(tmp_path, read_deploy_sh(), running=running, ancestry=ancestry)
    calls = [ln for ln in api.splitlines() if ln.strip()]
    assert proc.returncode == 0 and "跳过" in proc.stdout, proc.stdout
    assert proc.stdout.count("**跳过**") == 3, proc.stdout
    assert calls == [f"{OLD_TAG[4:]}...{NEW_TAG[4:]}"], (
        f"三个同「在跑 tag」的服务查了 {len(calls)} 次 API（应恰好 1 次）⇒ 会撞匿名限额：\n{api}"
    )
    # 反向（判别力）：三个服务**各自**不同的在跑 tag ⇒ 就该查 3 次（判据不是「恒为 1 次」）
    mixed = {"admin-api": NEW_TAG, "ai-agent": "sha-1111111", "admin-web": "sha-2222222"}
    anc = {f"{OLD_TAG[4:]}...{t[4:]}": "ahead" for t in sorted(set(mixed.values()))}
    proc2, _, api2 = _run(tmp_path / "mixed", read_deploy_sh(), running=mixed, ancestry=anc)
    calls2 = [ln for ln in api2.splitlines() if ln.strip()]
    assert proc2.returncode == 0, proc2.stdout + proc2.stderr
    assert len(calls2) == 3, f"在跑 tag 各不相同却只查了 {len(calls2)} 次（缓存键错了）：\n{api2}"
    assert sorted(_skipped_services_from(proc2.stdout)) == sorted(SERVICES), proc2.stdout


def _pre_fix_script(text: str) -> str:
    """把闸门段（2.05）与生效 tag 段（2.1）机械剥离、拉取循环还原为无条件遍历 —— 即**修复前**的码路。

    不做任何「手写旧实现」：只删掉本 PR 新增的两段 + 还原被本 PR 改了的那一行（`$ALLOWED_SERVICES`）。
    剥离后若仍残留闸门标识 ⇒ **显式失败**（否则这条红证是空跑）。
    """
    def line_start(i: int) -> int:
        return text.rfind("\n", 0, i) + 1

    i_anchor = text.find(GATE_ANCHOR)
    assert i_anchor > 0, "反空跑锚点：找不到闸门段锚点"
    i_gate = line_start(line_start(i_anchor) - 1)          # 再退一行 = 段首的 `# ═…` 边框线
    i_pull = line_start(text.find(PULL_ANCHOR, i_gate))    # 保留拉取段（闸门是纯增量，这段没被改）
    i_eff_c = text.find("# ── 2.1 ", i_pull)               # 生效 tag 段的注释头
    assert i_eff_c > i_pull, "反空跑锚点：找不到生效 tag 段的注释头"
    i_eff = line_start(i_eff_c)
    i_bg_anchor = text.find("2.5 严格蓝绿", i_eff)
    assert i_bg_anchor > i_eff, "反空跑锚点：找不到蓝绿段锚点"
    i_bg = line_start(line_start(i_bg_anchor) - 1)         # 含蓝绿段的 `# ═…` 边框线
    out = text[:i_gate] + text[i_pull:i_eff] + text[i_bg:]
    out = _inject(out, "for svc in $ALLOWED_SERVICES; do", "for svc in admin-api ai-agent admin-web; do")
    for token in ("ALLOW_DOWNGRADE", "ancestry_verdict", "EFFECTIVE_TAG", "ALLOWED_SERVICES",
                  "DOWNGRADE_SKIPPED"):
        assert token not in out, f"剥离后仍残留 `{token}` ⇒ 「修复前」的码路不成立（红证空跑）"
    assert "for svc in admin-api ai-agent admin-web; do\n  if timeout 180 docker compose pull" in out, (
        "剥离后的拉取循环不是修复前的形态（红证空跑）"
    )
    return out


def test_pre_fix_reconstruction_is_faithful():
    """反空跑：剥离出来的「修复前」码路必须**只**少了闸门（既有护栏全在）。"""
    old = _pre_fix_script(read_deploy_sh())
    assert judge_rails_intact(old) == [], "剥离后既有护栏反而少了 ⇒ 剥离手法有缺陷：\n- " + "\n- ".join(
        judge_rails_intact(old)
    )
    assert "== 2. 拉取镜像" in old and "2.5 严格蓝绿" in old and "== 3. 健康检查" in old, old[-300:]


def test_exec_discriminating_power_of_the_gate(tmp_path):
    """🔴 反向红证（判别力）：把判据映射注入坏（`ahead ⇒ forward`）⇒ **修复后**的脚本也会回退。

    这一条证明上面「跳过 + 告警」的断言**不是空断言**：判据一旦失效，同一次注入下
    三个服务就会被重建为旧 tag（= 事故复发）。
    """
    broken = _inject(read_deploy_sh(), "    ahead)     echo downgrade ;;", "    ahead)     echo forward ;;")
    running, ancestry = _accident_inputs()
    proc, log, _ = _run(tmp_path, broken, running=running, ancestry=ancestry)
    assert proc.returncode == 0, proc.stdout
    assert sorted(_deployed_services(log)) == sorted(SERVICES), (
        f"判据被注入坏后仍然没回退（= 断言无判别力）：\n{log}"
    )
    assert not re.search(r"::warning::.*往回走", proc.stdout), proc.stdout


def test_exec_discriminating_power_of_allow_downgrade_branch(tmp_path):
    """🔴 反向红证：把显式回滚放行分支注入掉 ⇒ 「显式回滚」那条判据必红（人回不去）。"""
    broken = _inject(
        read_deploy_sh(),
        '  if [ "$ALLOW_DOWNGRADE" = "1" ]; then\n    echo "  ↩ ${svc}：**显式回滚**放行',
        '  if false; then\n    echo "  ↩ ${svc}：**显式回滚**放行',
    )
    running, ancestry = _accident_inputs()
    proc, log, _ = _run(tmp_path, broken, running=running, ancestry=ancestry,
                     extra_env={"ALLOW_DOWNGRADE": "1"})
    assert proc.returncode == 0, proc.stdout
    assert _deployed_services(log) == [], (
        f"注入掉放行分支后仍能降级（= 该断言无判别力）：\n{log}"
    )


def test_exec_discriminating_power_of_fail_open_warning(tmp_path):
    """🔴 反向红证：把 fail-open 的告警注入掉 ⇒ 「判不出必告警」那条判据必红（静默放行）。"""
    broken = _inject(
        read_deploy_sh(),
        '    echo "  ::warning::${svc} 判不出「target vs 在跑」的提交序',
        '    echo "  ${svc} 判不出「target vs 在跑」的提交序',
    )
    running = {svc: NEW_TAG for svc in SERVICES}
    proc, _, _ = _run(tmp_path, broken, running=running, ancestry={})
    assert f"::warning::{SERVICES[0]} 判不出" not in proc.stdout, (
        "注入掉告警后仍出现 ::warning:: ⇒ 断言无判别力"
    )


# ══════════════════════════════════════════════════════════════════════════
# 四、CI 侧渲染（真跑 `swas-deploy-ci.sh` 里的解析/渲染函数，含**真实** `say` → $GITHUB_STEP_SUMMARY）
# ══════════════════════════════════════════════════════════════════════════

REMOTE_LOG_SAMPLE = f"""== 2.05 「不许往回走」闸门（issue #4852）==
  ::warning::admin-api **跳过**：target={OLD_TAG} 是**当前在跑 tag={NEW_TAG} 的祖先**
  ::warning::ai-agent **跳过**：target={OLD_TAG} 是**当前在跑 tag={NEW_TAG} 的祖先**
  ::warning::admin-web **跳过**：target={OLD_TAG} 是**当前在跑 tag={NEW_TAG} 的祖先**
== 2.1 本次实际生效 tag（逐服务）==
  EFFECTIVE_TAG=admin-api:{NEW_TAG}
  EFFECTIVE_TAG=ai-agent:{NEW_TAG}
  EFFECTIVE_TAG=admin-web:{NEW_TAG}
  DOWNGRADE_SKIPPED=admin-api:{OLD_TAG}:{NEW_TAG}
  DOWNGRADE_SKIPPED=ai-agent:{OLD_TAG}:{NEW_TAG}
  DOWNGRADE_SKIPPED=admin-web:{OLD_TAG}:{NEW_TAG}
PREV_GOOD_TAG={NEW_TAG}
"""


def _probe_functions(script_text: str, names: list, body: str, env: dict) -> str:
    """把脚本里的若干 shell 函数**原样**抽出来跑（真实实现，不是复刻）。"""
    parts = ["set -euo pipefail", "SUMMARY_FILE=${GITHUB_STEP_SUMMARY:-}"]
    for name in names:
        parts.append(f"{name}() {{{function_body(script_text, name)}\n}}")
    parts.append(body)
    probe = "\n".join(parts)
    proc = subprocess.run(["bash", "-c", probe], capture_output=True, text=True, timeout=60, env=env)
    assert proc.returncode == 0, f"probe 失败：\n{proc.stdout}\n{proc.stderr}\n--- probe ---\n{probe}"
    return proc.stdout


def test_ci_summary_carries_effective_tags_per_service(tmp_path):
    """🔴 不变量 3 的落点：解析远端标记 → 逐服务生效 tag 落 **$GITHUB_STEP_SUMMARY** + 结论行。"""
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary), "REMOTE_LOG": REMOTE_LOG_SAMPLE}
    out = _probe_functions(
        read_ci_script(), ["say", "effective_tags_line", "effective_suffix", "report_effective_tags"],
        'capture_probe() { :; }\n'
        'EFFECTIVE_TAGS=$(printf "%s\\n" "$REMOTE_LOG" | sed -n "s/^ *EFFECTIVE_TAG=//p")\n'
        'DOWNGRADE_SKIPS=$(printf "%s\\n" "$REMOTE_LOG" | sed -n "s/^ *DOWNGRADE_SKIPPED=//p")\n'
        'report_effective_tags\n'
        'echo "SUFFIX=$(effective_suffix)"\n',
        env,
    )
    text = summary.read_text(encoding="utf-8")
    assert f"`admin-api={NEW_TAG} / ai-agent={NEW_TAG} / admin-web={NEW_TAG}`" in text, (
        f"summary 里没有逐服务「实际生效 tag」：\n{text}"
    )
    for svc in SERVICES:
        assert f"target={OLD_TAG} 是当前在跑 {NEW_TAG} 的祖先" in text, (
            f"summary 没有说明 {svc} 为什么被跳过：\n{text}"
        )
    assert "gh workflow run deploy-admin-api.yml -f image_tag=<tag>" in text, (
        f"summary 没有给出「故意回滚」的显式路径：\n{text}"
    )
    assert f"本次实际生效：`admin-api={NEW_TAG}" in out, f"部署结论行没带生效 tag：\n{out}"
    assert "跳过" in text, "summary 掩盖了「有服务被跳过」这件事"


def test_ci_summary_says_unknown_when_markers_are_absent(tmp_path):
    """远端没打标记（旧版 deploy.sh）⇒ summary 必须**明写「未知」**，而不是静默省掉这一项。"""
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary), "REMOTE_LOG": "== 2. 拉取镜像 ==\n"}
    out = _probe_functions(
        read_ci_script(), ["say", "effective_tags_line", "effective_suffix", "report_effective_tags"],
        'EFFECTIVE_TAGS=$(printf "%s\\n" "$REMOTE_LOG" | sed -n "s/^ *EFFECTIVE_TAG=//p")\n'
        'DOWNGRADE_SKIPS=$(printf "%s\\n" "$REMOTE_LOG" | sed -n "s/^ *DOWNGRADE_SKIPPED=//p")\n'
        'report_effective_tags\n'
        'echo "SUFFIX=$(effective_suffix)"\n',
        env,
    )
    text = summary.read_text(encoding="utf-8")
    assert "无法**给出「实际生效 tag 逐服务」" in text, f"没标记时没有明写「无法给出」：\n{text}"
    assert "不是「已确认生效」" in text, f"没标记时没有区分「未知」与「已确认」：\n{text}"
    assert "部署.sh 版本早于" in out or "deploy.sh 版本早于" in out, out


def test_ci_render_survives_leading_whitespace_and_blank_lines(tmp_path):
    """健壮性：远端输出带前导空格/空行时仍能解析（`sed` 允许前导空格）。"""
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    log = "  EFFECTIVE_TAG=admin-api:sha-1a1a1a1\n\n    EFFECTIVE_TAG=ai-agent:sha-1a1a1a1\n"
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary), "REMOTE_LOG": log}
    out = _probe_functions(
        read_ci_script(), ["say", "effective_tags_line", "effective_suffix", "report_effective_tags"],
        'EFFECTIVE_TAGS=$(printf "%s\\n" "$REMOTE_LOG" | sed -n "s/^ *EFFECTIVE_TAG=//p")\n'
        'DOWNGRADE_SKIPS=""\n'
        'report_effective_tags\n',
        env,
    )
    assert "admin-api=sha-1a1a1a1" in out, out
    assert "ai-agent=sha-1a1a1a1" in out, out


def test_ci_full_path_from_base64_remote_output_to_summary(tmp_path):
    """🔴 端到端（CI 侧）：**真实** `capture_remote_log`（base64 解码 + 解析）→ **真实** `say` 落 summary。

    远端输出在 CI 上是 **base64** 的 `InvocationResult.Output`（#4767 ②）⇒ 这一条把
    「解码 → 解析 `EFFECTIVE_TAG=` → 渲染 → `$GITHUB_STEP_SUMMARY`」整条链跑一遍（不手工摆变量）。
    """
    import json
    from base64 import b64encode

    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    payload = f"== deploy.sh 输出 ==\n{REMOTE_LOG_SAMPLE}"
    res = json.dumps({
        "InvocationResult": {
            "InvocationStatus": "Success",
            "Output": b64encode(payload.encode()).decode("ascii"),
        }
    })
    env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary), "RES": res}
    out = _probe_functions(
        read_ci_script(),
        ["say", "extract_remote_log", "capture_remote_log", "effective_tags_line",
         "effective_suffix", "report_effective_tags"],
        'capture_remote_log "$RES"\n'
        'report_effective_tags\n'
        'echo "SUFFIX=$(effective_suffix)"\n',
        env,
    )
    text = summary.read_text(encoding="utf-8")
    assert f"`admin-api={NEW_TAG} / ai-agent={NEW_TAG} / admin-web={NEW_TAG}`" in text, text
    assert f"PREV_GOOD_TAG={NEW_TAG}" not in text, "summary 里混进了原始标记行（应只渲染人的可读行）"
    assert b64encode(payload.encode()).decode("ascii") not in text, "summary 里出现 base64（解码没生效）"
    assert f"本次实际生效：`admin-api={NEW_TAG}" in out, out


# ══════════════════════════════════════════════════════════════════════════
# 五、降级许可渲染的**语义**判据（issue #5128）—— 替换掉原先「逐字钉住一行」的形态
# ══════════════════════════════════════════════════════════════════════════

# 降级许可渲染点（现状 = `deploy_attempt` 里就地渲染那一行）。**只**作为注入锚点；
# 判据本体**不钉它**（钉住实现位置正是本单要修掉的形态）。
ALLOW_RENDER = "bootstrap=${bootstrap//__ALLOW_DOWNGRADE__/$allow}"
# `render_bootstrap` 里 tag/ref 渲染的最后一步 —— 「把许可渲染搬进 render_bootstrap」的注入点
REF_RENDER_TAIL = "out=${out//__BOOTSTRAP_REF__/$ref}"

# 许可必须落到**真正发给远端执行**的那条命令里（未渲染 / 渲染进没人用的变量 ⇒ 都不是这个形态）。
# 取值随 `allow` 变（判据**不**只认 1：allow=0 也必须**显式**注入 0，而不是留占位符或干脆不注入）。
def permit_in_command(allow: str) -> str:
    return f"export ALLOW_DOWNGRADE={allow};"


def judge_permit_reaches_the_executed_command(ci_text: str, tmp_path: Path, tag: str, allow: str,
                                              *, require_placeholder: bool = True) -> list:
    """语义判据本体（纯函数：文本进 → 违规清单出；注入式红证驱动**同一份本体**）。

    = 「**真正发给远端执行的那条命令里，许可已被渲染成 `<allow>`**」。

    这一条**不关心渲染点写在哪一行、在哪个函数里**（⇒ 合法重构不误红），但它同时覆盖三种真失效：
    ① 渲染点被**删**、② 渲染点被挪到**不生效**的位置（渲染进没人用的变量）、
    ③ 占位符从模板里**消失** —— 三者的共同后果都是「远端拿到的命令里没有 `ALLOW_DOWNGRADE=<值>`」，
    而远端 deploy.sh 的闸门在「许可状态未知」下的行为正是本单要防的**静默失效**。
    """
    cmd = deploy_attempt_command(
        ci_text, tmp_path, tag, allow, require_placeholder=require_placeholder,
    )
    v = []
    if "__ALLOW_DOWNGRADE__" in cmd:
        v.append(
            "发给远端执行的命令里仍留许可占位符 `__ALLOW_DOWNGRADE__`"
            "（远端会拿到「许可状态未知」⇒ 降级许可**静默失效**）"
        )
    want = permit_in_command(allow)
    if want not in cmd:
        v.append(f"发给远端执行的命令里没有注入许可（找不到 `{want}`）⇒ 许可没送到远端")
    if "bash /opt/migao-deploy/deploy.sh " not in cmd:
        v.append("发给远端执行的命令不是预期的 `bash /opt/migao-deploy/deploy.sh` 调用（判据锚点已过期）")
    return v


# ⚠️ **本判据不校验 tag 是否已渲染进命令**（有意，实测依据）：`render_bootstrap` 里的 tag 替换是
#    `${var//pat/repl}` —— **bash 4+ 形态**，而 macOS 自带 `/bin/bash` 是 **3.2**（本机实测：
#    探针里那两行渲染**静默不生效**）⇒ 在 3.2 上「tag 已渲染」恒假。tag 同源本身由
#    tests/unit_ci_workflows/test_swas_bootstrap_same_source_guard.py 的 `render_bootstrap` 判据承担；
#    本判据只管**许可**（`export ALLOW_DOWNGRADE=<allow>;` 那一段不依赖任何 bash 4 特性）。


def test_executed_command_carries_the_rendered_permit(tmp_path):
    """🔴 语义判据本体在**真实脚本**上干净（许可 1 / 0 两种取值各跑一次）。

    这是原「逐字钉住一行」判据要保护的东西的**语义形态**：`#5128` 的验收判据 ①②③ 都由它承担。
    """
    ci = read_ci_script()
    for allow in ("1", "0"):
        v = judge_permit_reaches_the_executed_command(
            ci, tmp_path / f"permit-{allow}", "sha-1a1a1a1", allow)
        assert v == [], f"许可={allow} 时语义判据判红：\n- " + "\n- ".join(v)


def test_legit_refactor_moving_the_render_does_not_go_red(tmp_path):
    """🔴 验收判据 ①：**合法重构不误红** —— 许可渲染搬进 `render_bootstrap` 且仍生效 ⇒ 判据必绿。

    这一条在**旧的逐字判据**下是**红**的（#5120 的实现包实测撞到）；这正是本单要修的东西。
    """
    ci = legit_refactor_moving_the_render_into_render_bootstrap(read_ci_script())
    assert ALLOW_RENDER not in ci, "注入后仍留着旧渲染行 ⇒ 这条红证是空跑（没真的搬走）"
    for token in ("render_bootstrap() {", "deploy_attempt() {", REF_RENDER_TAIL):
        assert token in ci, f"注入把脚本改坏了（找不到 {token!r}）⇒ 红证空跑"
    v = judge_permit_reaches_the_executed_command(ci, tmp_path / "refactor", "sha-1a1a1a1", "1")
    assert v == [], "合法重构被误判为「许可失效」：\n- " + "\n- ".join(v)


def _render_bootstrap_with_sed(ci_text: str) -> str:
    """把 `render_bootstrap` 的许可渲染换成**可移植**写法（`sed`）。

    ⚠️ 不是可有可无的细节：macOS 自带 `/bin/bash` 是 **3.2**，**不支持** `${var//pat/repl}`
    （本单实测：本机探针里那两行渲染**静默不生效**）⇒ 「搬进 `render_bootstrap`」若沿用
    bash 4+ 的写法，本机探针跑的是**半成品**。`sed` 形态在两个 bash 版本上语义一致。
    """
    return _inject(
        ci_text, REF_RENDER_TAIL,
        REF_RENDER_TAIL + "\n  out=$(printf '%s' \"$out\" | sed \"s/__ALLOW_DOWNGRADE__/$allow/g\")",
    )


def legit_refactor_moving_the_render_into_deploy_attempt(ci_text: str) -> str:
    """**合法重构（另一种）**：`render_bootstrap` 把渲染收敛到它**自己内部**（原地改一行），
    `deploy_attempt` 里那一行随之删掉 —— 渲染点换了写法与位置，但结果照样进执行命令。"""
    region = probe_region(ci_text)
    assert ALLOW_RENDER in region, f"注入锚点不存在（判据已过期）：{ALLOW_RENDER!r}"
    out = ci_text.replace(ALLOW_RENDER + "\n", "", 1)
    assert out != ci_text, "注入没有改变文本（空跑）"
    return _inject(
        out, "  printf '%s' \"$out\"",
        '  printf %s "${out//__ALLOW_DOWNGRADE__/$allow}"',
    )


def legit_refactor_moving_the_render_into_deploy_attempt_wrapper(ci_text: str) -> str:
    """**合法重构（第三种）**：`deploy_attempt` 用 `printf` + 命令替换（换掉参数展开写法）。"""
    return _inject(
        ci_text, ALLOW_RENDER,
        'bootstrap=$(printf %s "$bootstrap" | sed "s/__ALLOW_DOWNGRADE__/$allow/g")',
    )


def legit_refactor_moving_the_render_into_render_bootstrap(ci_text: str) -> str:
    """**合法重构（本单的主形态）**：#5120 的实现包最初想做、结果被旧判据误红的那一步 ——
    把许可渲染从 `deploy_attempt` 搬进 `render_bootstrap`（tag + ref + 许可一起渲染）。

    结果**仍生效**：`render_bootstrap` 的输出就是 `bootstrap`，照样进执行命令。
    """
    region = probe_region(ci_text)
    assert ALLOW_RENDER in region, f"注入锚点不存在（判据已过期）：{ALLOW_RENDER!r}"
    out = ci_text.replace(ALLOW_RENDER + "\n", "", 1)
    assert out != ci_text, "注入没有改变文本（空跑）"
    return _render_bootstrap_with_sed(out)


@pytest.mark.parametrize("refactor", [
    legit_refactor_moving_the_render_into_render_bootstrap,
    legit_refactor_moving_the_render_into_deploy_attempt,
    legit_refactor_moving_the_render_into_deploy_attempt_wrapper,
])
def test_legit_refactors_do_not_go_red(tmp_path, refactor):
    """🔴 验收判据 ①（三种**不同机制**的合法重构各跑一次）：都不许误红。

    旧判据对三种都红（它们都改了 `deploy_attempt` 里那一行的形态/位置），
    而语义判据只问「执行命令里许可对不对」⇒ 三种都绿。
    """
    ci = refactor(read_ci_script())
    assert ALLOW_RENDER not in ci, f"{refactor.__name__}: 注入后仍留着旧渲染行 ⇒ 红证空跑"
    v = judge_permit_reaches_the_executed_command(ci, tmp_path / "ok", "sha-1a1a1a1", "1")
    assert v == [], f"{refactor.__name__}: 合法重构被误红：\n- " + "\n- ".join(v)


@pytest.mark.parametrize("how,inject,need_placeholder", [
    ("渲染点删除", lambda ci: _inject(ci, ALLOW_RENDER + "\n", ""), True),
    ("渲染到不生效的位置（渲染进没人用的变量）", lambda ci: _inject(
        ci, ALLOW_RENDER, "local permit_only=${bootstrap//__ALLOW_DOWNGRADE__/$allow}",
    ), True),
    ("占位符从 BOOTSTRAP 模板里消失（渲染点成了空转）", lambda ci: _inject(
        ci, "export ALLOW_DOWNGRADE=__ALLOW_DOWNGRADE__; ", "",
    ), False),
    ("渲染成常量（许可值不生效：回滚也被当普通部署）", lambda ci: _inject(
        ci, ALLOW_RENDER, "bootstrap=${bootstrap//__ALLOW_DOWNGRADE__/0}",
    ), True),
])
def test_real_failure_modes_go_red(tmp_path, how, inject, need_placeholder):
    """🔴 验收判据 ②：**真失效必须红** —— 四种形态各自**单独**让判据红（不是「一起红」）。

    第三种（占位符从模板里消失）下，模板里**本来就没有**占位符 ⇒ 显式关掉那条「模板必须含占位符」
    的反空跑锚点（它是给另外三种形态兜底的，在这里会先于判据触发）。
    """
    v = judge_permit_reaches_the_executed_command(
        inject(read_ci_script()), tmp_path / "broken", "sha-1a1a1a1", "1",
        require_placeholder=need_placeholder,
    )
    assert v != [], f"「{how}」之后判据没红（= 判据无判别力）"


def legacy_literal_criterion(ci_text: str) -> list:
    """**旧判据逐字内联**（#5128 要替换掉的那条，取自改动前的 `judge_ci_wiring`）：
    只问「`deploy_attempt` 里有没有那一行字面量」，不问「许可有没有真的进执行命令」。"""
    return [] if ALLOW_RENDER in ci_text else ["`deploy_attempt` 没有渲染许可占位符"]


def test_legacy_literal_pin_would_misfire_on_legit_refactor(tmp_path):
    """🔴 红证（本单的病根 / 验收判据 ① 的「改前红」）：**旧的逐字判据**在合法重构上**会红**。

    逐字内联旧判据（不引用实现），证明它正是 #5120 的实现包撞到的那一条：
    许可渲染一搬进 `render_bootstrap`，字面量就消失 ⇒ 旧判据判红，**而结果其实仍生效**
    （同一份文本在新判据下是绿的 —— 这就是本单要达成的效果）。
    """
    ci = read_ci_script()
    assert legacy_literal_criterion(ci) == [], "现状（就地渲染）下旧判据本该是绿的（反空跑）"
    refactored = legit_refactor_moving_the_render_into_render_bootstrap(ci)
    assert legacy_literal_criterion(refactored) != [], "合法重构居然没让旧判据红 ⇒ 这条红证是空跑"
    assert judge_permit_reaches_the_executed_command(refactored, tmp_path / "legacy", "sha-1a1a1a1", "1") == [], (
        "新判据在合法重构上也红了（本单没修好）"
    )
