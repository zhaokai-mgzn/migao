# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""`deploy/swas/deploy.sh` **配置与镜像 tag 同源**守卫 —— issue #5083（无方向审计 P2-2.8）。

## 病根（**审计实测**，逐字内联，§18.3：判据不读 `origin/main` 这类可变引用）

`deploy/swas/deploy.sh` 的配置同步段此前**无条件**取 `refs/heads/main` 的最新版
（修复前那一行**逐字**如下，取自本 PR 之前的脚本）：

    curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 15 --max-time 120 -o src.tar.gz https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/refs/heads/main

而**镜像**是按 commit 固定的（`sha-${GITHUB_SHA::7}`）⇒ **回滚到旧 `image_tag` 时，
配置仍是 main 的最新版** = 「旧镜像 + 新配置」（未定义行为），且**不报错、不告警**。
`IMAGE_TAG` 此前只用于镜像与回滚提示，**没有任何**「按 IMAGE_TAG 校验/固定配置」的逻辑。
这与本仓「部署结论以**容器真身**为唯一判据」同族 —— 配置也是"真身"的一部分。

## 续篇：**取配置本身也要能续、能重、可观测**（issue #6551；本文件同址扩写，不另立文件）

病根（**CI 逐字现取**，run 37726977789，2026-10-08）：

    curl: (28) Operation timed out after 120000 milliseconds with 41399245 out of 66570829 bytes received
      ❌ 取不到 tag=sha-046298d 对应的配置（ref=046298d）⇒ **中止部署**（绝不回落到 main 的配置）
    ⚠️ 自动重试仍失败 ⇒ **回滚到上一个可用镜像 tag=`sha-03b1132`**
      ❌ 取不到 tag=sha-03b1132 对应的配置（ref=03b1132）⇒ **中止部署**

关键读数：实测吞吐 = 41.4MB/120s ≈ **0.34MB/s**，而 66.5MB 要在 120s 内下完需 ≥0.55MB/s
⇒ **按构造就会偶发失败**；而整份日志里**只有一次** `curl: (28)`、**0 条** `Warning: Transient problem`
⇒ 参数面写着的 `--retry 3` **从未触发**（半途超时那一族不在它的覆盖里），**且没有任何东西会因此变红**。
后果：**主部署 / 自动重试 / 自动回滚三条路径被同一道闸门一起挡住**。

## 本文件锁什么（6 条判据，每条都有**能单独让它变红**的变异）

1. **配置 ref 与镜像 tag 同源**：配置 URL 的 ref 由 `config_ref_for_tag "$TAG"` 推导
   （`sha-<hex>` ⇒ 该 commit；其它 ⇒ `refs/tags/<tag>`）⇒ 脚本里**不存在**无条件取
   `refs/heads/main` 的路径（静态判据 + 执行式判据：URL 逐字断言）。
2. **回滚场景**：给定旧 `IMAGE_TAG` + 「main 已前进」夹具（main 的包里带 `CONFIG_MARKER=MAIN`）
   ⇒ 实际落到 `nginx/nginx.conf` 的必须是**该 tag 那份**（`CONFIG_MARKER=OLD`），不是 main 的。
3. **取不到匹配配置 ⇒ fail-closed**：非零退出 + 可行动报错；**main 的配置就在桩上可取**也不许回落到它
   （「没回落」是可断言的：URL 流水里没有 main、且没写任何配置文件）。
4. **既有安全护栏不削弱**：下载仍是 `curl -fsSL` + 超时预算、落点仍是三份 canonical 文件；
   `tag_to_sha()` 只有一份。
5. **可重 + 可观测 + 不被残包毒化（#6551 ①；口径经 #6550 实测改过一次）**：下载段必须有**显式重试循环**
   （不是只靠参数面的 `--retry`）；**每轮先删残包**（残包只会换来 `curl exit 33`）；**每次重试都要在
   日志里打一行**（含 `curl exit=` 与**本轮收到字节数**）；**下完之后 `tar` 解包失败也要显式 fail-closed**
   （残包不被信任）。
   🔴 **不许加 `-C -` 断点续传**（本文件原稿推过它，已被 #6550 的实测否掉）：`codeload.github.com`
   **不认 `Range`** —— `curl -r 0-1023` 拿到的是 `HTTP/2 200` + **整份流式返回**（响应头无
   `content-range`/`accept-ranges`）；盘上留半份时 `-C -` 会发 `Range:`、拿 200 ⇒ `curl exit 33`、**零进展**
   ⇒ 等于把「慢」换成「**永久卡死**」。预算沿用 #6550 的 **900s 字面量**（反向守卫：塞回 `-C -` 必红）。
6. **回滚路径与下载闸门解耦（#6551 ②）**：现盘配置的**物化 ref 标记 == 本次目标 ref** 且三份
   canonical 文件齐 ⇒ **不再下整仓**；取不到现盘配置才降级（`::warning::`）。判据**只认 ref 相同**
   ⇒ #5083 的「配置与镜像同源」fail-closed 语义**一字不改**。

## ⚠️ 红证的真实性边界（**照实登记，不粉饰**）

执行式判据跑的是**本机 + 桩化的外部依赖**（codeload / docker / flock / timeout），**不是**真实 SWAS 部署；
被桩化的是外部依赖，被测的是 `deploy.sh` 的**配置源推导与 fail-closed 编排**本身。
真实 `codeload` 形态已**只读实测**（本机 curl，2026-09-21）：`tar.gz/<7位短 sha>` ⇒ HTTP 200（8.6s）、
`tar.gz/refs/heads/main` ⇒ HTTP 200、`tar.gz/refs/tags/latest` ⇒ **404**（0.54s）、`tar.gz/deadbee` ⇒ **404**
—— 即「短 sha 可解析」「不存在的 tag/commit 取不到 ⇒ fail-closed 真的会触发」。
**未取证**：真实服务器的端到端部署/回滚（本 PR 无 SWAS 访问、无 docker）⇒ 见 PR body 的「未取证/边界」。

## 🔴 夹具合法性（2026-10-08 CI 实测补的一层，issue #6551）

本文件的执行式判据会**造脚本变体**（重建体 / 注入体）再交给 `bash` 跑。首版的重建手法是
「整段冻结替换」：只切到「物化 ref」标记行、**丢掉了配对的 `if`** ⇒ 变体留下**孤儿 `fi`**：`bash -n` 报
`syntax error near unexpected token 'fi'`（rc=2），而 **macOS 的 bash 3.2 对语法错不致命**
（错误之前那部分照跑、`exit status` 仍是 **0**）⇒ 本地全绿、**ubuntu bash 5.1（CI）rc=2 且 stdout 全空**。
⇒ 现有两条常驻判据：`test_every_reconstruction_is_a_legal_script`（每个变体先过 `bash -n`）与
`_bash_syntax_check()`（**夹具层 fail-closed**：`_prepare()` 里对**任何**要执行的文本做同一检查）。
**别把「rc==0」当成跑通了** —— 顺手记一句：本文件的执行式断言对**语法错**要额外看
`stdout 非空` / `stderr 无 syntax error`。
"""
import os
import re
import shutil
import subprocess
import tarfile
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "deploy" / "swas" / "deploy.sh"

# 段锚点（改脚本时这些字符串必须一起改；取不到 ⇒ 显式失败，不是「通过」）
CONFIG_SECTION_ANCHOR = "0. 配置源与镜像 tag **同源**"
CONFIG_ECHO_ANCHOR = "== 1. 同步 repo 内 canonical compose + nginx 配置"
DISK_ANCHOR = "== 1.9 磁盘水位预检"
NEXT_SECTION_ANCHOR = "# 1.5 AI 自动甄别配置自愈"
FETCH_REF_TOKEN = '"$CONFIG_TARBALL_BASE/$CONFIG_REF_RESOLVED"'
DERIVE_TOKEN = 'CONFIG_REF_RESOLVED=$(config_ref_for_tag "$TAG")'

# ── #6551 的锚点（取配置：可观测重试 / 现盘复用）──────────────────────────────
FETCH_FN = "config_fetch_tarball"          # 取配置包（重试循环所在）
REUSE_FN = "config_reuse_on_disk"          # 现盘配置复用判据
# ⚠️ 断点续传 token 在这里是**禁止出现**的那一个（#6550 实测：codeload 不支持 Range）——
#    它被 `test_injection_reintroduce_resume_goes_red` 当作「重新引入必红」的哨兵。
RESUME_REINTRODUCED_TOKEN = "-C -"
PURGE_TOKEN = "rm -f src.tar.gz"                             # 每轮**先删残包**（不能续传 ⇒ 残包只剩害处）
FETCH_LOOP_TOKEN = 'while [ "$try" -lt "$CONFIG_FETCH_ATTEMPTS" ]; do'   # 显式重试（控制流面）
RETRY_ECHO_TOKEN = "次重试"                                   # 重试必须**出声**
RETRY_FAIL_TOKEN = "次失败（curl exit="                        # 失败行要带读数
BOUND_TOKEN = "单次上界 900s"                                  # 本轮上界回显（#6550 的预算，逐字回显）
FETCH_CALLSITE = "if config_reuse_on_disk; then"
FETCH_ELIF_TOKEN = "if config_fetch_tarball; then"
LOCAL_IMAGE_SKIP_TOKEN = 'docker image inspect "$_reuse_img_ref"'
LOCAL_IMAGE_HEADER_TOKEN = '[ -n "$BUILD_SERVICE" ] && [ -z "$LOCAL_IMAGE_REF" ]'
MARKER_FILE_TOKEN = 'CONFIG_REF_MARKER_FILE=${CONFIG_REF_MARKER_FILE:-'
MARKER_WRITE_TOKEN = '> "$CONFIG_REF_MARKER_FILE"'
MARKER_LINE = 'printf \'%s\\n\' "$CONFIG_REF_RESOLVED" > "$CONFIG_REF_MARKER_FILE"'
REUSE_REF_TOKEN = '[ "$CONFIG_ON_DISK_REF" = "$CONFIG_REF_RESOLVED" ]'
REUSE_FILES_TOKEN = '[ -f docker-compose.yml ] && [ -f nginx/nginx.conf ] && [ -f docker-compose.bluegreen.yml ]'
TAR_SELFCHECK_TOKEN = "if ! tar xzf src.tar.gz -C src --strip-components=1; then"
FETCH_BLOCK_START = 'CONFIG_ON_DISK_REF=$(cat "$CONFIG_REF_MARKER_FILE" 2>/dev/null || true)'

# ⚠️ 这里**不内联**「修复前那一行 curl」的逐字副本（#6550 的教训，见 `_pre_fix_script`）：
#    预算/重试形态还在演进，冻结副本会让红证变成「与历史版本比对」而不是「与当前契约比对」。
CONFIG_URL_PREFIX = "https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/"
MAIN_REF = "refs/heads/main"

SERVICES = ("admin-api", "ai-agent", "admin-web")
OLD_TAG = "sha-aaaaaaa"      # 「旧」tag（= 回滚目标 / 排到后面的旧 run）
NEW_TAG = "sha-ccccccc"      # main 已前进后新部署的 tag（= 当前在跑）
MARKER_OLD = "OLD"
MARKER_MAIN = "MAIN"


# ══════════════════════════════════════════════════════════════════════════
# 读源 + 反空跑锚点
# ══════════════════════════════════════════════════════════════════════════

def read_deploy_sh() -> str:
    assert DEPLOY_SH.is_file(), f"反空跑锚点：目标脚本不存在 → {DEPLOY_SH}"
    text = DEPLOY_SH.read_text(encoding="utf-8")
    for anchor in (CONFIG_SECTION_ANCHOR, CONFIG_ECHO_ANCHOR, FETCH_REF_TOKEN, DERIVE_TOKEN,
                   FETCH_FN, REUSE_FN, MARKER_WRITE_TOKEN, PURGE_TOKEN):
        assert anchor in text, (
            f"反空跑锚点：deploy.sh 里找不到 {anchor!r}（判据已过期或脚本被改写）—— 这不是「通过」"
        )
    return text


def non_comment(text: str) -> str:
    """剥掉**整行注释**后的代码行 —— 判据只判「真的会执行的那一行」。"""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def section(text: str, start_anchor: str, end_anchor: str) -> str:
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


def _inject(text: str, old: str, new: str) -> str:
    """替换注入；**没替换到 ⇒ 显式失败**（否则「注入式红证」是空跑）。"""
    assert old in text, f"注入锚点不存在（判据已过期）：{old[:70]!r}"
    out = text.replace(old, new, 1)
    assert out != text, "注入没有改变文本（空跑）"
    return out


# ══════════════════════════════════════════════════════════════════════════
# 判据本体（纯函数：文本进 → 违规清单出；注入式红证驱动**同一份本体**）
# ══════════════════════════════════════════════════════════════════════════

def judge_config_same_source(text: str) -> list:
    """① 配置 ref 由镜像 tag 推导（绝不 main）；下载点唯一；推导点唯一。"""
    v = []
    code = non_comment(text)
    if MAIN_REF in code:
        v.append(f"代码里仍出现 `{MAIN_REF}` ⇒ 存在「无条件取 main 配置」的路径（本单要修的形态）")
    if code.count("CONFIG_TARBALL_BASE=${CONFIG_TARBALL_BASE:-") != 1:
        v.append("配置源不是恰好一处（`CONFIG_TARBALL_BASE` 定义出现多次/缺失 ⇒ 有第二条配置通道）")
    if code.count(FETCH_REF_TOKEN) != 1:
        v.append(f"配置下载 URL 不是恰好一处用 `{FETCH_REF_TOKEN}`（下载点被复制或绕过）")
    if code.count("CONFIG_REF_RESOLVED=$(config_ref_for_tag") != 1:
        v.append("配置 ref 的推导不是恰好一处（`config_ref_for_tag \"$TAG\"`）")
    if code.count("-o src.tar.gz") != 1:
        v.append("`-o src.tar.gz` 出现次数 ≠ 1（配置下载出现了第二条路径）")
    # ⚠️ 判的是**调用序**，不是函数体在文件里的位置（#6551 把 curl 收进了 `config_fetch_tarball()`，
    #    函数**定义**在推导之前、**调用**在推导之后 ⇒ 拿 `FETCH_REF_TOKEN` 的下标比大小会假红）。
    i_derive = text.find(DERIVE_TOKEN)
    i_callsite = text.find(FETCH_CALLSITE)
    i_disk = text.find(DISK_ANCHOR)
    if i_callsite < 0:
        v.append(f"找不到配置读取的调用点 `{FETCH_CALLSITE}`（判据已过期）")
    else:
        if i_derive > i_callsite:
            v.append("配置 ref 在**取配置之前**还没推导出来 ⇒ URL 里的 ref 不是它（判据形同虚设）")
        if i_callsite > i_disk:
            v.append("配置同步排在磁盘预检（1.9，会用 docker compose）**之后** ⇒ 配置可能缺位")
    body = function_body(text, "config_ref_for_tag")
    if "tag_to_sha" not in body:
        v.append("`config_ref_for_tag()` 没有复用 `tag_to_sha()`（形态判断会两处漂移）")
    if "refs/tags/" not in body:
        v.append("`config_ref_for_tag()` 缺少「非 sha tag ⇒ `refs/tags/<tag>`」的分支（tag 追不到 commit）")
    if MAIN_REF in body:
        v.append(f"`config_ref_for_tag()` 里出现 `{MAIN_REF}` ⇒ 推导本身能退回 main（判据自废）")
    if text.count("tag_to_sha() {") != 1:
        v.append(f"`tag_to_sha()` 定义出现 {text.count('tag_to_sha() {')} 次（必须恰好 1 份）")
    return v


def judge_fail_closed(text: str) -> list:
    """②③ 取不到匹配配置 ⇒ **非零退出 + 可行动报错**；包内容不完整同样 fail-closed。"""
    v = []
    sec = section(text, CONFIG_SECTION_ANCHOR, NEXT_SECTION_ANCHOR)
    # ⓐ ref 推导为空（tag 为空）⇒ 立即停
    m = re.search(r'if \[ -z "\$CONFIG_REF_RESOLVED" \]; then(.*?)\nfi\n', sec, re.S)
    if not m:
        v.append("找不到「配置 ref 为空 ⇒ 中止」的分支（fail-closed 判据已过期）")
    else:
        blk = m.group(1)
        if "exit 1" not in blk:
            v.append("配置 ref 为空时没有 `exit 1` ⇒ 会继续用**没有 ref 的 URL** 或 main 的配置")
        for token, why in (("拒绝用 main 的配置", "写明「拒绝用 main 的配置」"),
                           ("sha-", "给出可行动的修法（改用 sha-<7位hex>）")):
            if token not in blk:
                v.append(f"空 ref 分支缺少：{why}")
    # ⓑ 下载失败（404 / 重试预算用尽）⇒ 立即停，绝不回落
    i = sec.find("❌ 取不到 tag=${TAG} 对应的配置")
    if i < 0:
        v.append("找不到「下载失败 ⇒ 中止」的报错行（fail-closed 判据已过期）")
    else:
        blk = sec[i:i + 600]
        if "exit 1" not in blk:
            v.append("配置下载失败时没有 `exit 1` ⇒ 静默降级（本单禁止）")
        for token in ("绝不回落到 main 的配置", "移动 tag", "存在且可达"):
            if token not in blk:
                v.append(f"下载失败分支缺少可行动提示：{token!r}")
    # ⓒ 包内容不完整（旧 commit 无蓝绿 override / 被劫持的 200）⇒ 立即停，不混用 main 的同名文件
    # ⚠️ 缩进随脚本结构走 ⇒ 用 `\n *fi\n`，不写死空格数（本包把自检挪进了「取配置」分支）
    m = re.search(r'if \[ ! -f src/deploy/swas/docker-compose\.yml \](.*?)\n *fi\n', sec, re.S)
    if not m:
        v.append("找不到「包内容自检」分支（旧 commit 缺文件时会用 `cp` 报错兜底，报错不可行动）")
    else:
        blk = m.group(1)
        if "exit 1" not in blk:
            v.append("包内容不完整时没有 `exit 1`")
        for token in ("docker-compose.bluegreen.yml", "早于 #4785", "migao 仓库树"):
            if token not in blk:
                v.append(f"包内容自检分支缺少：{token!r}")
    # ⓓ 解包完整性自证（#6551 ①）：下载「成功」不等于包能用（残包 / 被劫持的 200）⇒ 解包失败也要 fail-closed
    j = sec.find(TAR_SELFCHECK_TOKEN)
    if j < 0:
        v.append("解包没有显式自证（`if ! tar xzf …; then … exit 1`）⇒ 残包会以 `set -e` 的裸报错收场、不可行动")
    else:
        blk = sec[j:j + 400]
        if "exit 1" not in blk:
            v.append("解包失败没有 `exit 1` ⇒ 残包会被当成配置继续用")
        for token in ("解不开", "残包"):
            if token not in blk:
                v.append(f"解包失败分支缺少可行动提示：{token!r}")
    return v


def judge_rails_intact(text: str) -> list:
    """④ 既有安全护栏不削弱：下载的 curl 预算/失败语义、以及配置落点仍是三份 canonical 文件。"""
    v = []
    sec = section(text, CONFIG_SECTION_ANCHOR, NEXT_SECTION_ANCHOR)
    fetch = [ln for ln in sec.splitlines() if "curl -fsSL" in ln]
    if len(fetch) != 1:
        v.append(f"配置下载的 curl 行不是恰好 1 行（{len(fetch)} 行）")
    else:
        # ⚠️ `--retry 3` **不再**是本判据的护栏项：issue #6551 把它换成**显式轮次**（同样是「从 0 重下」，
        #    但每轮都在日志里出声）。重试预算那条转由判据 ⑤ 把守，且**禁止**再与 `--retry` 叠加
        #    （3 轮 × 4 次 × 900s 会打破 #6550 的 4500s 预算契约）。
        for flag, why in (("-f", "HTTP 非 2xx 即失败（没有 -f ⇒ 404 也会「成功」）"),
                          ("--connect-timeout 15", "连接超时预算")):
            if flag not in fetch[0]:
                v.append(f"配置下载削弱了既有护栏：{flag}（{why}）")
        # ⚠️ 整体超时预算**不再钉死 120s 这个数值**（issue #6550：120s 下 66.5MB 永远下不完 ⇒ 部署停摆）
        #    ⇒ 改为「存在 ∧ ≥ 下界」。下界 600s 由实测推出（实测最慢 118 KB/s ⇒ 整仓 66.5MB 需 ~566s），
        #    与 tests/unit_ci_workflows/test_swas_config_tarball_fetch_budget.py::FLOOR_SECS 同源；
        #    上限（< CI 单次尝试预算）由那条判据把守 ⇒ 本判据只管「不削弱」，不重复它的射程。
        m_budget = re.search(r"--max-time\s+(\d+)", fetch[0])
        if not m_budget:
            v.append("配置下载削弱了既有护栏：`--max-time`（无界下载会挂住部署；issue #6550）")
        elif int(m_budget.group(1)) < 600:
            v.append(
                f"配置下载削弱了既有护栏：`--max-time {m_budget.group(1)}` < 600s"
                f"（实测 66.5MB @118~345KB/s 需要 ~566s；issue #6550）"
            )
    for token in ("cp src/deploy/swas/docker-compose.yml ./docker-compose.yml",
                  "cp src/deploy/swas/nginx.conf ./nginx/nginx.conf",
                  "cp src/deploy/swas/docker-compose.bluegreen.yml ./docker-compose.bluegreen.yml"):
        if token not in sec:
            v.append(f"canonical 配置落点被改动：找不到 `{token}`")
    return v


def judge_fetch_retry_observable(text: str) -> list:
    """⑤（#6551 ①）取配置要**能重、能看见、不被残包毒化**。

    ⚠️ 本判据**不要求**断点续传 —— 恰恰相反，`-C -` 是**禁止**的（#6550 实测：codeload 不支持
    Range ⇒ 有残包时 `-C -` 发出的 `Range:` 只会换来 200 + `curl exit 33`、零进展，
    把「慢」换成「永久卡死」）。
    """
    v = []
    sec = section(text, CONFIG_SECTION_ANCHOR, NEXT_SECTION_ANCHOR)
    body = function_body(text, FETCH_FN)
    fetch = [ln for ln in body.splitlines() if "curl -fsSL" in ln]
    if len(fetch) != 1:
        v.append(f"取配置的 curl 行不是恰好 1 行（{len(fetch)} 行）⇒ 判据读不到那一行的参数")
    elif RESUME_REINTRODUCED_TOKEN in fetch[0]:
        v.append("取配置的 curl 行带上了 `-C -`（#6550 实测：codeload 不支持 Range ⇒ 残包时 curl "
                 "exit 33、零进展 ⇒ 把「慢」换成「永久卡死」；**勿再引入**）")
    if FETCH_LOOP_TOKEN not in body:
        v.append("取配置没有**显式重试循环**（`while … CONFIG_FETCH_ATTEMPTS`）⇒ 「`--retry` 配了却不触发」会重演")
    if "--retry " in body:
        v.append("显式轮次之外仍留着 curl 自带的 `--retry`（不可见的重试）⇒ 次数会相乘，"
                 "病态最坏 3 轮 × 4 次 × 900s 会打破 #6550 的 4500s 预算契约")
    if PURGE_TOKEN not in body:
        v.append("每轮**没有先删残包**（`rm -f src.tar.gz`）⇒ 不能续传时残包只会把下一次尝试拖进 exit 33")
    if 'sleep "$CONFIG_FETCH_DELAY_SECONDS"' not in body:
        v.append("重试之间没有 `sleep`（退避）⇒ 会把瞬时故障连打成一串失败")
    # 🔴 重试必须**可观测**：事故的一部分正是「参数面写了重试、实际有没有触发没人知道」
    for token, why in ((RETRY_ECHO_TOKEN, "重试那一行（`… 第 N 次重试`）"),
                       (RETRY_FAIL_TOKEN, "失败那一行要带 `curl exit=` 读数"),
                       ("本轮收到", "失败行要带**本轮收到多少字节**（判「有没有进展」的唯一读数）")):
        if token not in body:
            v.append(f"重试不可观测：日志里没有 {why} ⇒ 下次再「静默不重试」也没人会知道")
    if BOUND_TOKEN not in sec:
        v.append("没有把本轮**上界回显**进日志（事故教训：参数面写了什么，日志里必须看得见）")
    return v


def judge_rollback_reuse(text: str) -> list:
    """⑥（#6551 ②）回滚目标的配置**已在盘上**时不得再下整仓；且不许放松「配置与镜像同源」。"""
    v = []
    sec = section(text, CONFIG_SECTION_ANCHOR, NEXT_SECTION_ANCHOR)
    body = function_body(text, REUSE_FN)
    if REUSE_REF_TOKEN not in body:
        v.append("复用判据没有比对 ref（`CONFIG_ON_DISK_REF` ≠ `CONFIG_REF_RESOLVED` 也复用）"
                 "⇒ 会「旧镜像 + 新配置」（#5083 的护栏被放松）")
    if REUSE_FILES_TOKEN not in body:
        v.append("复用判据没有校验三份 canonical 文件齐不齐 ⇒ 半套配置也会被复用")
    if "::warning::" not in body:
        v.append("现盘配置取不到时没有 `::warning::` ⇒ 降级是静默的（本单要治的形态）")
    if MARKER_FILE_TOKEN not in text:
        v.append("没有「物化 ref」标记文件的定义（复用判据没有可认的键）")
    i_reuse = sec.find(FETCH_CALLSITE)
    i_fetch = sec.find(FETCH_ELIF_TOKEN)
    if i_reuse < 0 or i_fetch < 0 or i_reuse > i_fetch:
        v.append(f"复用没有排在下载**之前**（要求 `{FETCH_CALLSITE}` → `{FETCH_ELIF_TOKEN}`）"
                 "⇒ 照样先下 66.5MB，回滚仍被同一道闸门挡住")
    j = sec.find(MARKER_WRITE_TOKEN)
    k = sec.find("cp src/deploy/swas/docker-compose.bluegreen.yml ./docker-compose.bluegreen.yml")
    if j < 0:
        v.append("没有在配置落盘后写「物化 ref」标记 ⇒ 下次永远无法复用（回滚仍被下载闸门挡住）")
    elif k < 0 or j < k:
        v.append("「物化 ref」标记写在配置落盘**之前** ⇒ 会谎报盘上配置的来源（复用判据失去意义）")
    # ── 构建上下文的解耦（C′ 特有；没有它，复用只是纸面权利）────────────────────
    # C′ 形态下 `src/` 是构建上下文，而 #5814 在构建成功后把它删掉 ⇒ 回滚态下「有配置、没源码树」。
    # 若不复用/不处理这一层，「回滚不再下载」就是空话（下载仍会被构建需要）。
    if LOCAL_IMAGE_SKIP_TOKEN not in sec:
        v.append("复用路径没有处理**构建上下文**（`docker image inspect \"$_reuse_img_ref\"`）："
                 "C′ 回滚态下源码树已被 #5814 删掉 ⇒ 仍会为了构建去下整仓（复用形同虚设）")
    if LOCAL_IMAGE_HEADER_TOKEN not in text:
        v.append(f"1.4 构建段没有 `{LOCAL_IMAGE_HEADER_TOKEN}` 的短路 ⇒ 就算本地已有镜像也会重建")
    if "local_image_ref_of" not in text:
        v.append("本地镜像 ref 的推导没有收成唯一一份（`local_image_ref_of`）⇒ 两处会漂移")
    return v


def all_violations(text: str) -> list:
    return (judge_config_same_source(text) + judge_fail_closed(text) + judge_rails_intact(text)
            + judge_fetch_retry_observable(text) + judge_rollback_reuse(text))


# ══════════════════════════════════════════════════════════════════════════
# 一、静态判据（读脚本当前文本）
# ══════════════════════════════════════════════════════════════════════════

def test_real_script_satisfies_every_judgement():
    v = all_violations(read_deploy_sh())
    assert v == [], "配置同源判据未满足：\n- " + "\n- ".join(v)


@pytest.mark.parametrize("judge_name", [
    "judge_config_same_source",
    "judge_fail_closed",
    "judge_rails_intact",
    "judge_fetch_retry_observable",
    "judge_rollback_reuse",
])
def test_each_judge_is_clean_on_the_real_script(judge_name):
    """逐条判据在真实脚本上各自干净（避免一条恒红被「整体红」掩盖）。"""
    v = globals()[judge_name](read_deploy_sh())
    assert v == [], f"{judge_name} 判红：\n- " + "\n- ".join(v)


def test_script_is_syntactically_valid():
    """`bash -n`：这个脚本语法错 = **停掉所有人的部署**。"""
    proc = subprocess.run(["bash", "-n", str(DEPLOY_SH)], capture_output=True, text=True)
    assert proc.returncode == 0, f"deploy.sh 语法错误：\n{proc.stderr}"


def test_pre_fix_line_is_really_gone():
    """反空跑：修复前那一行**真的**不在脚本里（判据不是「它还在但没人读」）。"""
    text = read_deploy_sh()
    assert f'"{CONFIG_URL_PREFIX}{MAIN_REF}"' not in text, "配置 URL 仍指向 main"
    assert MAIN_REF not in non_comment(text), f"代码里仍有 `{MAIN_REF}`"


# ── 推导本体：把脚本里的真函数拿出来跑（行为判据，不是文本判据）──────────────

def _run_config_ref(tag: str) -> str:
    text = read_deploy_sh()
    script = (
        "tag_to_sha() {" + function_body(text, "tag_to_sha") + "\n}\n"
        "config_ref_for_tag() {" + function_body(text, "config_ref_for_tag") + "\n}\n"
        'config_ref_for_tag "$1"\n'
    )
    assert "refs/tags/" in script and "tag_to_sha" in script, "反空跑：抽取的函数体不完整"
    proc = subprocess.run(["bash", "-c", script, "bash", tag], capture_output=True, text=True)
    assert proc.returncode == 0, f"推导函数执行失败（tag={tag!r}）：{proc.stderr}"
    return proc.stdout.strip()


@pytest.mark.parametrize("tag,want", [
    ("sha-7b03ed3", "7b03ed3"),                       # CI 的正常形态：短 sha
    ("sha-0f3e7e826b1c9d4a5e6f708192a3b4c5d6e7f809", "0f3e7e826b1c9d4a5e6f708192a3b4c5d6e7f809"),
    ("v1.2.3", "refs/tags/v1.2.3"),                   # semver ⇒ tag ref（tag→commit 的解析）
    ("latest", "refs/tags/latest"),                   # 移动 tag ⇒ 也会得到一个**可 404 的** ref
    ("sha-abc", "refs/tags/sha-abc"),                 # 太短 ⇒ 不是 commit ⇒ 走 tag 分支
    ("sha-XYZ1234", "refs/tags/sha-XYZ1234"),         # 非 hex ⇒ 走 tag 分支
    ("", ""),                                         # 空 tag ⇒ 空 ref（调用点 fail-closed）
])
def test_config_ref_derivation_table(tag, want):
    """判据 ①：配置 ref 由镜像 tag 推导；**任何输入都不产出 main**。"""
    got = _run_config_ref(tag)
    assert got == want, f"tag={tag!r} 的配置 ref 应为 {want!r}，实得 {got!r}"
    assert MAIN_REF not in got, f"tag={tag!r} 竟然推导出 main 的配置 ref ⇒ 本单的病根回来了"


# ══════════════════════════════════════════════════════════════════════════
# 二、注入式红证（每条判据各自可独立判红；注入必须真的落到文本上）
# ══════════════════════════════════════════════════════════════════════════

def test_injection_restore_main_url_goes_red():
    """注入①：把配置 URL 换回**修复前那一行**（取 main）⇒ 判据 ① 必红。"""
    injected = _inject(read_deploy_sh(), FETCH_REF_TOKEN,
                       '"https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/refs/heads/main"')
    assert judge_config_same_source(injected) != [], "换回 main 取配置后判据没红（判据无判别力）"


def test_injection_derivation_returns_main_goes_red():
    """注入②：让推导本体在非 sha tag 时返回 `refs/heads/main` ⇒ 判据 ① 必红。"""
    injected = _inject(read_deploy_sh(), 'if [ -n "$t" ]; then echo "refs/tags/$t"; fi',
                       'if [ -n "$t" ]; then echo "refs/heads/main"; fi')
    assert judge_config_same_source(injected) != [], "推导退回 main 后判据没红（判据无判别力）"


def test_injection_duplicate_tag_to_sha_goes_red():
    """注入③：把 `tag_to_sha()` 复制一份（两处形态判断会漂移）⇒ 判据 ① 必红。"""
    text = read_deploy_sh()
    body = function_body(text, "tag_to_sha")
    injected = text + f"\ntag_to_sha() {{{body}}}\n"
    assert judge_config_same_source(injected) != [], "复制推导函数后判据没红（判据无判别力）"


def test_injection_drop_fetch_fail_closed_goes_red():
    """注入④：下载失败不再 `exit 1`（= 静默继续用旧/无配置）⇒ 判据 ③ 必红。"""
    text = read_deploy_sh()
    injected = _inject(
        text,
        'echo "  ❌ 取不到 tag=${TAG} 对应的配置（ref=${CONFIG_REF_RESOLVED}）⇒ **中止部署**（绝不回落到 main 的配置）"',
        'echo "  ⚠️ 取不到配置，继续（静默降级）"',
    )
    # 去掉紧随其后的 `exit 1`（缩进随脚本结构走 ⇒ 正则，不写死空格数）
    injected, n = re.subn(r'(否则核对：该 commit/tag 在 zhaokai-mgzn/migao 上存在且可达"\n)\s*exit 1\n',
                          r"\1", injected, count=1)
    assert n == 1, "反空跑锚点：找不到「下载失败 ⇒ exit 1」那一行"
    assert judge_fail_closed(injected) != [], "去掉下载失败的 fail-closed 后判据没红（判据无判别力）"


def test_injection_drop_empty_ref_gate_goes_red():
    """注入⑤：删掉「ref 为空 ⇒ 中止」整段 ⇒ 判据 ③ 必红。"""
    text = read_deploy_sh()
    m = re.search(r'if \[ -z "\$CONFIG_REF_RESOLVED" \]; then(.*?)\nfi\n', text, re.S)
    assert m, "反空跑锚点：找不到空 ref 闸门"
    injected = text[:m.start()] + text[m.end():]
    assert DERIVE_TOKEN in injected, "注入误删了推导行（红证会变成别的原因）"
    assert judge_fail_closed(injected) != [], "删掉空 ref 闸门后判据没红（判据无判别力）"


def test_injection_drop_package_selfcheck_goes_red():
    """注入⑥：删掉包内容自检（旧 commit 缺蓝绿 override 时会静默半套配置）⇒ 判据 ③ 必红。"""
    text = read_deploy_sh()
    m = re.search(r'if \[ ! -f src/deploy/swas/docker-compose\.yml \](.*?)\n *fi\n', text, re.S)
    assert m, "反空跑锚点：找不到包内容自检"
    injected = text[:m.start()] + text[m.end():]
    assert "cp src/deploy/swas/docker-compose.yml" in injected
    assert judge_fail_closed(injected) != [], "删掉包内容自检后判据没红（判据无判别力）"


def test_injection_weaken_curl_rails_goes_red():
    """注入⑦：去掉 `-f`（HTTP 404 也会被当成功）⇒ 判据 ④ 必红。"""
    injected = _inject(read_deploy_sh(), "curl -fsSL", "curl -sSL")
    assert judge_rails_intact(injected) != [], "去掉 `-f` 后判据没红（判据无判别力）"


def test_injection_drop_timeout_budget_goes_red():
    """注入⑧：去掉 `--max-time`（下载可能无限挂住部署）⇒ 判据 ④ 必红。

    ⚠️ 按**正则**摘标志、不写死数值：issue #6550 把预算 120s → 900s，写死会让下次调预算时
    红证变成「锚点过期」而不是判据变红。
    ⚠️ 且**只认代码那一行**（`(?= -o src.tar.gz)`）：注释里也可以出现同样的字样，
    按「第一处」改会打到注释上 ⇒ 判据不红（实测踩过）。
    """
    text = read_deploy_sh()
    injected, n = re.subn(r" --max-time \d+(?= -o src\.tar\.gz)", "", text, count=1)
    assert n == 1 and injected != text, "变异没生效 ⇒ 红证空跑"
    assert judge_rails_intact(injected) != [], "去掉整体超时预算后判据没红（判据无判别力）"


def test_injection_shrink_timeout_budget_goes_red():
    """注入⑨：把预算改回**修复前**的 120s（issue #6550 的病根值）⇒ 判据 ④ 必红。

    ⚠️ 锚点同 ⑧：`(?= -o src.tar.gz)` 把变异钉在**代码那一行**上（注释里的同款字样不算）。
    """
    text = read_deploy_sh()
    injected, n = re.subn(r"--max-time \d+(?= -o src\.tar\.gz)", "--max-time 120", text, count=1)
    assert n == 1 and injected != text, "变异没生效 ⇒ 红证空跑"
    assert judge_rails_intact(injected) != [], "预算退回 120s 后判据没红（判据无判别力）"


# ── #6551 的注入（每条都对应上面的一条判据；「参数面回退 ⇒ 红」逐步可查）────────────

def test_injection_reintroduce_resume_goes_red():
    """注入⑩（#6551 ① 的**反向**守卫）：把 `-C -` 塞回取配置那一行 ⇒ 判据 ⑤ 必红。

    为什么是「塞回去必红」而不是「删掉必红」：#6550 用实测否掉了续传（codeload 不支持 Range
    ⇒ 有残包时 `curl exit 33`、零进展 ⇒ 把「慢」换成「永久卡死」，登记为**勿再引入**）⇒
    本判据站在「不许再进来」这一侧。
    """
    injected = _inject(read_deploy_sh(), "curl -fsSL --connect-timeout 15",
                       "curl -fsSL -C - --connect-timeout 15")
    assert RESUME_REINTRODUCED_TOKEN in injected, "注入没生效（红证空跑）"
    assert judge_fetch_retry_observable(injected) != [], "重新引入续传后判据没红（判据无判别力）"


def test_injection_drop_partial_purge_goes_red():
    """注入⑪（#6551 ①）：删掉「每轮先删残包」⇒ 判据 ⑤ 必红（残包会把下一轮拖进 exit 33）。"""
    injected = _inject(read_deploy_sh(), PURGE_TOKEN, "true")
    assert judge_fetch_retry_observable(injected) != [], "删掉残包清理后判据没红（判据无判别力）"


def test_injection_drop_retry_loop_goes_red():
    """注入⑫（#6551 ①）：把重试预算改成 1（参数面删掉重试）⇒ 判据 ⑤ 必红。"""
    injected = _inject(read_deploy_sh(), FETCH_LOOP_TOKEN, 'while [ "$try" -lt 1 ]; do')
    assert judge_fetch_retry_observable(injected) != [], "删掉重试循环后判据没红（判据无判别力）"


def test_injection_keep_curl_retry_alongside_loop_goes_red():
    """注入⑬（#6551 ① + #6550 的预算契约）：把 curl 自带的 `--retry 3` 与显式轮次**叠在一起**
    ⇒ 判据 ⑤ 必红（次数相乘 ⇒ 病态最坏 3 轮 × 4 次 × 900s，打破 4500s 预算契约）。"""
    injected = _inject(read_deploy_sh(), "curl -fsSL --connect-timeout 15",
                       "curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 15")
    assert judge_fetch_retry_observable(injected) != [], "叠加两套重试后判据没红（判据无判别力）"


def test_injection_drop_retry_echo_goes_red():
    """注入⑭（#6551 ①，**本单的核心教训**）：只删「重试那一行日志」⇒ 判据 ⑤ 必红。

    事故的一部分正是「参数面写了重试、实际有没有触发、而**没有任何东西会因此变红**」
    ⇒ 「重试可观测」必须是**会红**的判据，不是一句注释。
    """
    text = read_deploy_sh()
    m = re.search(r'\n *echo "  ⚠️ 第 \$\{try\}/\$\{CONFIG_FETCH_ATTEMPTS\} 次失败（curl exit=\$\{rc\}，本轮收到 \$\{have\} 字节）⇒ \*\*第 \$\(\(try \+ 1\)\) 次重试\*\*.*?\n', text)
    assert m, "反空跑锚点：找不到重试日志行"
    injected = text[:m.start()] + "\n" + text[m.end():]
    assert RETRY_ECHO_TOKEN not in injected, "注入没删掉重试行（红证会空跑）"
    assert judge_fetch_retry_observable(injected) != [], "删掉重试日志后判据没红（判据无判别力）"


def test_injection_drop_reuse_ref_key_goes_red():
    """注入⑮（#6551 ②）：复用判据不再比对 ref（只要求「标记非空」）⇒ 判据 ⑥ 必红。

    ⚠️ 这条注入同时是**护栏回归**的哨兵：一旦复用不认 ref，就会「旧镜像 + 新配置」（#5083）。
    """
    injected = _inject(read_deploy_sh(), REUSE_REF_TOKEN, '[ -n "$CONFIG_ON_DISK_REF" ]')
    assert judge_rollback_reuse(injected) != [], "复用不再比对 ref 后判据没红（判据无判别力）"


def test_injection_disable_reuse_goes_red():
    """注入⑯（#6551 ②）：把复用判据整个短路（`if false`）⇒ 判据 ⑥ 必红（复用没排在下载之前）。"""
    injected = _inject(read_deploy_sh(), FETCH_CALLSITE, "if false; then")
    assert judge_rollback_reuse(injected) != [], "短路复用后判据没红（判据无判别力）"


def test_comment_only_change_is_not_red():
    """注入⑰（对照，判据不吞真判据也不被文案喂红）：**只改注释** ⇒ 五条判据全绿。"""
    text = read_deploy_sh()
    injected = text.replace("# ⚠️ 这一段是「配置与镜像同源」的**唯一**落点（issue #5083）",
                            "# ⚠️ 这一段是「配置与镜像同源」的**唯一**落点（issue #5083；注释改动，不该判红）", 1)
    assert injected != text, "注入没生效（对照是空跑）"
    assert all_violations(injected) == [], "只改注释竟判红：\n- " + "\n- ".join(all_violations(injected))


# ══════════════════════════════════════════════════════════════════════════
# 三、执行式判据（桩 codeload/docker/flock/timeout，跑真实 deploy.sh 的真实码路）
# ══════════════════════════════════════════════════════════════════════════

CURL_STUB = """#!/bin/bash
# 桩 curl：① 配置包 → 按 URL 里的 **ref** 取夹具（没有该 ref 的夹具 ⇒ 退出 22 = `curl -f` 的失败语义）；
#          ② GitHub compare API → 按 $ANCESTRY_DIR/<pair> 回放 status（缺 ⇒ 22）；
#          ③ 健康检查 → 按 $HC_STATE/hc-<端口>（缺 ⇒ 200）。
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
  *"/tar.gz/"*)
    printf '%s\\n' "$url" >> "$CONFIG_URL_LOG"
    ref=${url##*/tar.gz/}
    safe=$(printf '%s' "$ref" | tr '/:' '__')
    if [ ! -f "$CONFIG_DIR/$safe.tar.gz" ]; then exit 22; fi
    cp "$CONFIG_DIR/$safe.tar.gz" "$out"; exit 0 ;;
  *api.github.com*)
    pair=${url##*/}
    st=$(cat "$ANCESTRY_DIR/$pair" 2>/dev/null || true)
    if [ -z "$st" ]; then exit 22; fi
    printf '{"status": "%s"}\\n' "$st"
    exit 0 ;;
esac
port=$(printf '%s' "$url" | sed -n 's#^http://127\\.0\\.0\\.1:\\([0-9][0-9]*\\)/.*#\\1#p')
code=$(cat "$HC_STATE/hc-$port" 2>/dev/null || echo 200)
if [ -n "$out" ]; then : > "$out"; fi
if [ -n "$fmt" ]; then printf '%s' "$code"; fi
exit 0
"""

# ── #6551 ① 红证专用桩 curl：对配置包 URL 做**真实的分段响应** ────────────────────
#   第一轮按 `$FAIL_PLAN`（剩余次数）**截断**响应：只写一半就 `exit 28`
#   （= 真 curl 的 `(28) Operation timed out … with X out of Y bytes received`，与事故同族）；
#   后续轮次识别 `-C -`：偏移 = **盘上现有字节数**，**只发剩下的那段**（真 curl 的 `Range` 语义），
#   并把 `Range: bytes=N-` 记进 `$RANGE_LOG` ⇒ 「第二次请求真的带了 Range」「续传后的包逐字节等于夹具」
#   都是**可断言**的读数（`test_exec_resume_retry_observable`）。
CURL_RANGE_STUB = """#!/bin/bash
out=""; url=""; fmt=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w) fmt="$2"; shift 2 ;;
    -C) shift 2 ;;
    -H) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in
  *"/tar.gz/"*)
    printf '%s\\n' "$url" >> "$CONFIG_URL_LOG"
    ref=${url##*/tar.gz/}
    safe=$(printf '%s' "$ref" | tr '/:' '__')
    src="$CONFIG_DIR/$safe.tar.gz"
    if [ ! -f "$src" ]; then exit 22; fi
    total=$(wc -c < "$src" | tr -d ' ')
    have=0
    if [ -n "$out" ] && [ -f "$out" ]; then have=$(wc -c < "$out" | tr -d ' '); fi
    printf 'Range: bytes=%s-\\n' "$have" >> "$RANGE_LOG"
    fail=0
    if [ -f "$FAIL_PLAN" ]; then fail=$(cat "$FAIL_PLAN"); fi
    if [ "$fail" -gt 0 ]; then
      printf '%s' "$((fail - 1))" > "$FAIL_PLAN"
      cut=$(( have + (total - have) / 2 ))
      if [ -n "$out" ]; then tail -c +$((have + 1)) "$src" | head -c $((cut - have)) >> "$out"; fi
      echo "curl: (28) Operation timed out after 300000 milliseconds with $cut out of $total bytes received" >&2
      exit 28
    fi
    if [ -n "$out" ]; then tail -c +$((have + 1)) "$src" >> "$out"; fi
    exit 0 ;;
  *api.github.com*)
    pair=${url##*/}
    st=$(cat "$ANCESTRY_DIR/$pair" 2>/dev/null || true)
    if [ -z "$st" ]; then exit 22; fi
    printf '{"status": "%s"}\\n' "$st"
    exit 0 ;;
esac
port=$(printf '%s' "$url" | sed -n 's#^http://127\\.0\\.0\\.1:\\([0-9][0-9]*\\)/.*#\\1#p')
code=$(cat "$HC_STATE/hc-$port" 2>/dev/null || echo 200)
if [ -n "$out" ]; then : > "$out"; fi
if [ -n "$fmt" ]; then printf '%s' "$code"; fi
exit 0
"""

DOCKER_STUB = """#!/bin/bash
# 桩 docker：记录调用；`compose ps -q <svc>` / `inspect --format … <cid>` 回放 $RUNNING_DIR/<svc>；
# `compose config --format json` 回放三服务的 `image:`（#6551 ② 的「本地镜像」判据要用它）；
# `image inspect <ref>` 只认 $IMAGE_DIR/<ref 转义> 这个「本地已有」标记（缺 ⇒ 1，与真 docker 同语义）。
echo "docker $*" >> "$DOCKER_LOG"
last=""; for a in "$@"; do last="$a"; done
case "$1 $2" in
  "compose ps")
    if [ -f "$RUNNING_DIR/$last" ]; then echo "cid-$last"; fi
    exit 0 ;;
  "compose config")
    printf '{"services":{"admin-api":{"image":"dockerstub/admin-api:%s"},"ai-agent":{"image":"dockerstub/ai-agent:%s"},"admin-web":{"image":"dockerstub/admin-web:%s"}}}\\n' "$IMAGE_TAG" "$IMAGE_TAG" "$IMAGE_TAG"
    exit 0 ;;
  "image inspect")
    key=$(printf '%s' "$last" | tr '/:' '__')
    if [ -n "$IMAGE_DIR" ] && [ -f "$IMAGE_DIR/$key" ]; then exit 0; fi
    exit 1 ;;
esac
case "$1" in
  inspect)
    svc=${last#cid-}
    if [ -f "$RUNNING_DIR/$svc" ]; then cat "$RUNNING_DIR/$svc"; fi
    exit 0 ;;
esac
exit 0
"""

FLOCK_STUB = """#!/bin/bash
# 桩 flock：no-op（macOS 无 flock；锁语义由既有守卫 test_swas_deploy_blue_green.py 覆盖）
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


def _make_config_tar(dest: Path, marker: str, *, with_bluegreen: bool = True) -> None:
    """造一个 `migao-<marker>/deploy/swas/*` 的配置包（配合 `--strip-components=1`）。

    内容与仓库里的 canonical 配置**一致**，只多一行 `# CONFIG_MARKER=<marker>` ——
    测试据此断言「落盘的那份配置到底来自哪个 ref」（内容级判据，不看日志措辞）。
    """
    stage = dest.parent / f"stage-{marker}" / f"migao-{marker}" / "deploy" / "swas"
    stage.mkdir(parents=True, exist_ok=True)
    names = ["docker-compose.yml", "nginx.conf"]
    if with_bluegreen:
        names.append("docker-compose.bluegreen.yml")
    for name in names:
        shutil.copy(REPO_ROOT / "deploy" / "swas" / name, stage / name)
    nginx = stage / "nginx.conf"
    nginx.write_text(nginx.read_text(encoding="utf-8") + f"\n# CONFIG_MARKER={marker}\n", encoding="utf-8")
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(dest.parent / f"stage-{marker}" / f"migao-{marker}", arcname=f"migao-{marker}")


def _bash_syntax_check(text: str, label: str) -> None:
    """夹具层 **fail-closed 自证**：任何要被**执行**的脚本文本，先过**同一个 `bash`** 的 `bash -n`。

    为什么必须在夹具层（issue #6551 的 CI 红，2026-10-08 实测）：
      · 重建体（首版「整段冻结替换」产出的「修复前形态」）曾**丢掉配对的 `if`** ⇒ 留下**孤儿 `fi`**，
        脚本根本过不了解析（`bash -n` ⇒ `rc=2`、`syntax error near unexpected token 'fi'`）；
      · 而 **macOS 的 bash 3.2 对语法错不致命**（实测：逐块解析 ⇒ 错误前的那部分**照跑**、
        stderr 打一行、**exit status 仍是 0**）⇒ 本地「全绿」；ubuntu 的 **bash 5.1** 直接 `rc=2`、
        stdout **一个字都没有** ⇒ 只有 CI 才红。
    ⇒ **「重建体必须先是合法脚本」**：否则判据是在一个连解析都过不了的夹具上做业务断言 —— 那种绿
       **毫无根据**（本轮实测）。这条自证自己也能红（见 `test_fixture_syntax_selfcheck_goes_red_on_a_broken_variant`）。
    """
    proc = subprocess.run(["bash", "-n"], input=text, capture_output=True, text=True)
    assert proc.returncode == 0, (
        f"夹具不合法（{label}）：过不了 `bash -n`（rc={proc.returncode}）—— "
        "重建体 / 注入体必须先是**合法脚本**，否则判据是在一个连解析都过不了的夹具上做断言"
        "（macOS bash 3.2 对语法错**不致命** ⇒ 前半段照跑、exit status 仍是 0 ⇒ 绿得毫无根据）：\n"
        f"{proc.stderr.strip()[:400]}"
    )


def _prepare(tmp_path: Path, script_text: str, fixtures: dict, *,
             curl_body: str = CURL_STUB, seed: dict | None = None) -> tuple:
    """沙箱：脚本副本（改写绝对路径）+ 桩 bin + 各 ref 的配置夹具 + .env 文件。

    seed: {工作目录内相对路径: 文本} —— 预置**现盘状态**（#6551 ② 的复用判据要用它：
          `.config-ref` 标记 + 三份 canonical 配置）。
    """
    work = tmp_path / "opt-migao-deploy"
    work.mkdir(parents=True, exist_ok=True)
    text = script_text
    text = text.replace("/opt/migao-deploy", str(work))
    text = text.replace("/tmp/migao-deploy.lock", str(work / "deploy.lock"))
    text = text.replace("/tmp/hc_", f"{work}/hc_")
    # 🔴 夹具层 fail-closed：**每一个**要执行的变体（真身 / 重建体 / 注入体）先自证是合法脚本。
    #    放在这里 ⇒ 所有执行式判据（含各注入）都被这一条兜住，而不是只兜「我知道的那两个重建体」。
    _bash_syntax_check(text, "沙箱里的 deploy.sh 副本")
    script = work / "deploy.sh"
    script.write_text(text, encoding="utf-8")
    for rel, body in (seed or {}).items():
        dest = work / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
    # 配置 fail-closed 前置：显式声明 SMS_BYPASS_CODE（否则脚本按设计中止）
    (work / ".env.admin-api").write_text("SMS_BYPASS_CODE=123456\n", encoding="utf-8")
    (work / ".env.ai-agent").write_text("SMS_BYPASS_CODE=123456\n", encoding="utf-8")
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    for ref, marker in fixtures.items():
        safe = ref.replace("/", "_").replace(":", "_")
        _make_config_tar(config_dir / f"{safe}.tar.gz", marker,
                         with_bluegreen=(marker != "NOBLUEGREEN"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_exe(bin_dir / "curl", curl_body)
    _write_exe(bin_dir / "docker", DOCKER_STUB)
    _write_exe(bin_dir / "flock", FLOCK_STUB)
    _write_exe(bin_dir / "timeout", TIMEOUT_STUB)
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    return work, script, bin_dir, state, config_dir


def _run(tmp_path: Path, script_text: str, *, tag: str, fixtures: dict,
         running: dict | None = None, ancestry: dict | None = None, extra_env: dict | None = None,
         curl_body: str = CURL_STUB, seed: dict | None = None, fail_plan_count: int = 0,
         local_images: list | None = None):
    """跑脚本。

    fixtures: {ref: marker} —— 桩上**可取到**的配置包（ref 不在其中 ⇒ 404 ⇒ 22）
    running:  {服务: tag} —— 「当前在跑」的镜像 tag（缺 ⇒ 没有在跑容器 ⇒ 判据 unknown）
    ancestry: {"<target>..<current>": status} —— compare API 回放（缺 ⇒ API 取不到）
    curl_body: 桩 curl 的实现（默认单段桩；`CURL_RANGE_STUB` = 支持 `-C -` 的分段桩）
    seed:     {工作目录内相对路径: 文本} —— 预置现盘状态（#6551 ②）
    fail_plan_count: 分段桩**前 N 轮**截断响应（模拟半途超时 ⇒ `curl: (28)`）
    local_images: 桩 docker 认为「**本地已有**」的镜像 ref（#6551 ② 的 C′ 回滚腿判据）
    """
    work, script, bin_dir, state, config_dir = _prepare(tmp_path, script_text, fixtures,
                                                        curl_body=curl_body, seed=seed)
    running_dir = tmp_path / "running"
    running_dir.mkdir(exist_ok=True)
    repos = {"admin-api": "admin-api", "ai-agent": "ai-agent-service", "admin-web": "admin-web"}
    for svc, t in (running or {}).items():
        (running_dir / svc).write_text(f"reg.example.com/ai-customer-service/{repos[svc]}:{t}\n",
                                       encoding="utf-8")
    anc_dir = tmp_path / "ancestry"
    anc_dir.mkdir(exist_ok=True)
    for pair, status in (ancestry or {}).items():
        (anc_dir / pair).write_text(status, encoding="utf-8")
    docker_log = tmp_path / "docker.log"
    docker_log.write_text("", encoding="utf-8")
    url_log = tmp_path / "config-url.log"
    url_log.write_text("", encoding="utf-8")
    range_log = tmp_path / "range.log"
    range_log.write_text("", encoding="utf-8")
    fail_plan = tmp_path / "fail-plan"
    fail_plan.write_text(str(fail_plan_count), encoding="utf-8")
    image_dir = tmp_path / "images"
    image_dir.mkdir(exist_ok=True)
    for ref in (local_images or []):
        (image_dir / ref.replace("/", "_").replace(":", "_")).write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DOCKER_LOG": str(docker_log),
        "CONFIG_URL_LOG": str(url_log),
        "RANGE_LOG": str(range_log),
        "FAIL_PLAN": str(fail_plan),
        "IMAGE_DIR": str(image_dir),
        "CONFIG_DIR": str(config_dir),
        "RUNNING_DIR": str(running_dir),
        "ANCESTRY_DIR": str(anc_dir),
        "HC_STATE": str(state),
        "HC_RETRIES": "2",
        "HC_INTERVAL_SECONDS": "0",
        # /proc/meminfo 在 macOS 不存在 ⇒ 预检恒判 0MB；把门槛设为 0 以聚焦编排
        "BG_MEM_NEED_MB": "0",
        "BG_OFF_FILE": str(work / ".blue-green-off"),
        # 重试退避对**判据**无意义（判的是「有没有重试、有没有出声」）⇒ 归零，别让测试白等
        "CONFIG_FETCH_DELAY_SECONDS": "0",
        **(extra_env or {}),
    }
    proc = subprocess.run(["bash", str(script), tag], cwd=str(work), env=env,
                          capture_output=True, text=True, timeout=300)
    return proc, docker_log.read_text(encoding="utf-8"), _urls(url_log.read_text(encoding="utf-8")), work


def _urls(url_log: str) -> list:
    return [ln for ln in url_log.splitlines() if ln.strip()]


def _landed_nginx(work: Path) -> str:
    """落盘的 canonical nginx 配置（不存在 ⇒ 空串 = 本次没写任何配置）。"""
    path = work / "nginx" / "nginx.conf"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_exec_normal_deploy_uses_config_from_image_commit(tmp_path):
    """🔴 判据 ①（执行式）：正常部署（`sha-aaaaaaa`）⇒ 配置 URL 就是**该 commit**，不是 main。

    夹具里 **main 的配置也在**（marker=MAIN）⇒ 这条断言不是「main 取不到」，而是「main 没被取」。
    """
    fixtures = {MAIN_REF: MARKER_MAIN, "aaaaaaa": MARKER_OLD}
    proc, log, urls, work = _run(tmp_path, read_deploy_sh(), tag=OLD_TAG, fixtures=fixtures)
    assert proc.returncode == 0, f"正常部署不该失败：\n{proc.stdout}\n{proc.stderr}"
    assert urls == [f"{CONFIG_URL_PREFIX}aaaaaaa"], (
        f"配置不是按镜像 commit 取的（URL 流水 = {urls}）⇒ 配置仍随 main 漂移"
    )
    assert all(MAIN_REF not in u for u in urls), f"取过 main 的配置：{urls}"
    landed = _landed_nginx(work)
    assert f"CONFIG_MARKER={MARKER_OLD}" in landed, f"落盘配置不是该 tag 那份：\n{landed[-200:]}"
    assert f"CONFIG_MARKER={MARKER_MAIN}" not in landed, "落盘配置竟来自 main（本单的病根）"


def test_exec_rollback_uses_target_tag_config_not_main(tmp_path):
    """🔴 判据 ②（执行式，**回滚场景**）：main 已前进后回滚到旧 tag ⇒ 配置取**旧 tag 那份**。

    输入：在跑 `sha-ccccccc`（更新的那次刚成功）+ 显式回滚许可（`ALLOW_DOWNGRADE=1`，
    = #4852 的 `gh workflow run … -f image_tag=` / #4767 的失败即回滚）+ target `sha-aaaaaaa`；
    夹具里 main 的配置**带 `CONFIG_MARKER=MAIN`**（= 「main 已前进」）⇒ 落到盘上的必须是 OLD 那份。
    """
    fixtures = {MAIN_REF: MARKER_MAIN, "aaaaaaa": MARKER_OLD}
    running = {svc: NEW_TAG for svc in SERVICES}
    ancestry = {"aaaaaaa...ccccccc": "ahead"}   # target 是在跑的祖先 ⇒ 往回走（需许可放行）
    proc, log, urls, work = _run(tmp_path, read_deploy_sh(), tag=OLD_TAG, fixtures=fixtures,
                                 running=running, ancestry=ancestry, extra_env={"ALLOW_DOWNGRADE": "1"})
    assert proc.returncode == 0, f"显式回滚不该失败：\n{proc.stdout}\n{proc.stderr}"
    assert "**这是显式回滚**" in proc.stdout, proc.stdout
    assert sorted(svc for svc in SERVICES if re.search(rf"up -d --no-deps {svc}$", log, re.M)) == sorted(SERVICES), (
        f"回滚没有真的替换服务：\n{log}"
    )
    landed = _landed_nginx(work)
    assert f"CONFIG_MARKER={MARKER_OLD}" in landed, (
        f"回滚时配置不是目标 tag 那份 ⇒ 「旧镜像 + 新配置」（本单的病根）：\n{landed[-200:]}"
    )
    assert f"CONFIG_MARKER={MARKER_MAIN}" not in landed, "回滚时用了 main 的配置（本单的病根）"
    assert urls == [f"{CONFIG_URL_PREFIX}aaaaaaa"], urls


def test_exec_unresolvable_tag_fails_closed_and_never_uses_main(tmp_path):
    """🔴 判据 ③（执行式）：追不到 commit 的 tag（`latest`）⇒ **非零退出**，且**绝不**回落 main。

    关键：夹具里 **main 的配置是可取的**（`refs/heads/main` 有包）⇒ 「没回落」是**可断言**的
    （URL 流水里没有 main、且没有写任何配置文件），而不是「反正取不到」。
    """
    fixtures = {MAIN_REF: MARKER_MAIN}
    proc, log, urls, work = _run(tmp_path / "latest-case", read_deploy_sh(), tag="latest", fixtures=fixtures)
    assert (tmp_path / "latest-case" / "config" / "refs_heads_main.tar.gz").is_file(), (
        "反空跑：main 的配置夹具必须真的在桩上可取（否则「没回落」不可断言）"
    )
    assert proc.returncode != 0, f"追不到配置却报成功（静默降级）：\n{proc.stdout}"
    assert "取不到 tag=latest 对应的配置" in proc.stdout, proc.stdout
    assert "绝不回落到 main 的配置" in proc.stdout, proc.stdout
    assert "移动 tag" in proc.stdout, f"报错不可行动（没告诉人怎么办）：\n{proc.stdout}"
    assert urls == [f"{CONFIG_URL_PREFIX}refs/tags/latest"] * int(
        _declared_default(read_deploy_sh(), "CONFIG_FETCH_ATTEMPTS")), (
        f"没有去取该 tag 对应的 ref，或取过 main，或重试预算与声明的默认值不符：{urls}"
    )
    assert _landed_nginx(work) == "", "fail-closed 之后仍写了配置（= 回落了）"
    assert not re.search(r"compose (pull|up)", log, re.M), f"fail-closed 之后仍动了容器：\n{log}"


def test_exec_incomplete_config_package_fails_closed(tmp_path):
    """🔴 判据 ③（执行式，第二种 fail-closed）：该 commit 的配置**不完整**（缺蓝绿 override）⇒ 中止。

    形态 = 回滚到早于 #4785 的 commit：它的配置包里没有 `docker-compose.bluegreen.yml`。
    main 的包**在桩上可取**（完整）⇒ 断言脚本**没有**拿 main 的同名文件补上。
    """
    fixtures = {MAIN_REF: MARKER_MAIN, "bbbbbbb": "NOBLUEGREEN"}
    proc, log, urls, work = _run(tmp_path, read_deploy_sh(), tag="sha-bbbbbbb", fixtures=fixtures)
    assert proc.returncode != 0, f"配置不完整却报成功：\n{proc.stdout}"
    assert "找不到 canonical 配置" in proc.stdout, proc.stdout
    assert "早于 #4785" in proc.stdout, f"报错不可行动：\n{proc.stdout}"
    assert urls == [f"{CONFIG_URL_PREFIX}bbbbbbb"], f"取过别的 ref（可能回落 main）：{urls}"
    assert _landed_nginx(work) == "", "配置不完整却写了文件（半套配置）"
    assert not re.search(r"compose (pull|up)", log, re.M), f"fail-closed 之后仍动了容器：\n{log}"


def test_exec_semver_tag_uses_tag_ref(tmp_path):
    """非 sha tag（`v1.2.3`）⇒ 取 `refs/tags/v1.2.3`（tag→commit 的解析），**不是 main**。"""
    fixtures = {MAIN_REF: MARKER_MAIN, "refs_tags_v1.2.3": "SEMVER"}
    proc, log, urls, work = _run(tmp_path, read_deploy_sh(), tag="v1.2.3", fixtures=fixtures)
    assert proc.returncode == 0, f"semver tag 部署不该失败：\n{proc.stdout}\n{proc.stderr}"
    assert urls == [f"{CONFIG_URL_PREFIX}refs/tags/v1.2.3"], urls
    assert "CONFIG_MARKER=SEMVER" in _landed_nginx(work), _landed_nginx(work)[-200:]


def _declared_default(text: str, name: str) -> str:
    """取脚本里 `${NAME:-<默认值>}` 的默认值（判据据此断言「预算与日志读数是同一份」）。"""
    m = re.search(rf"^{name}=\$\{{{name}:-([^}}]*)\}}$", text, re.M)
    assert m, f"反空跑锚点：{name} 没有 `${{NAME:-<默认值>}}` 形态的默认值"
    return m.group(1)

# ── 重建体（#6551 的 CI 红之后：**每一个**变体都先过 `bash -n`，见 `_bash_syntax_check`）──

def _range_headers(base: Path) -> list:
    """分段桩记下的 `Range: …` 流水（缺文件 ⇒ 空表 = 桩没被走到）。

    #6551 用它**反向**证明一件事：整个取配置过程**一发偏移 `Range` 都不发**（`-C -` 已被 #6550
    实测禁用）⇒ 不存在「假装续传」的路径。
    """
    p = base / "range.log"
    return [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()] if p.is_file() else []


def _pre_fix_script(text: str) -> str:
    """#5083 **之前**的取配置段（URL 取 `refs/heads/main`，其余一字不动）。

    这样红证隔离的**正是**本单的那一处差异（配置 ref），不是别的改动。

    ⚠️ 还原手法 = **从当前脚本出发、只把 URL 换回 `refs/heads/main`**（而不是拼接历史那一行的
    逐字副本）：issue #6550 把整体超时预算 120s → 900s 之后，若仍拼接历史副本，还原出来的
    「修复前」码路会**多出**一处预算差异 ⇒ `judge_rails_intact` 判红、本函数声称的「只少了配置
    同源这一件事」不再成立（实测：那种还原在 #6550 上判红）。#6551 沿用同一纪律：**只做结构注入**。
    """
    out = _inject(text, FETCH_REF_TOKEN, f'"{CONFIG_URL_PREFIX}{MAIN_REF}"')
    assert FETCH_REF_TOKEN not in out, "还原后仍残留按 tag 推导的 URL（红证空跑）"
    assert DERIVE_TOKEN in out, "还原误伤了推导行（红证会变成别的原因）"
    return out


def _pre_6551_script(text: str) -> str:
    """#6551 **之前**的取配置**行为**：不认现盘配置（照样下载）+ 只有一次尝试。

    同样**不拼接历史副本**，只用两个结构注入（都点在 #6551 自己新增的那两处）：
      ① 复用判据短路（`if false`）⇒ 永远走「下载」分支（= 改动前没有复用这回事）；
      ② 轮次预算改成 1（改**默认值**，见函数体）⇒ 只有一次尝试（= 改动前那一次 + curl 自己**不可见**的重试）。
    改完必须仍是**合法脚本**（`_bash_syntax_check` 兜底 —— 这正是本轮 CI 红暴露的那一层）。
    """
    out = _inject(text, FETCH_CALLSITE, "if false; then")
    # 轮次预算改成 1（**改默认值**而不是改循环字面量）：这样「还会不会再试一轮」的两处判断
    # （循环条件与重试日志）**一致**，重建体不会打出自相矛盾的「第 2 次重试」。
    out = _inject(out, "CONFIG_FETCH_ATTEMPTS=${CONFIG_FETCH_ATTEMPTS:-3}",
                  "CONFIG_FETCH_ATTEMPTS=${CONFIG_FETCH_ATTEMPTS:-1}")
    _bash_syntax_check(out, "_pre_6551_script 重建体")
    return out


# ── #6551 的 CI 红（2026-10-08）：夹具自己必须先是**合法脚本**）────────────────────
# 逐字读数（**修前**，本机复现）：
#   $ bash -n /tmp/pre5083.sh
#   /tmp/pre5083.sh: line 584: syntax error near unexpected token `fi'      ⇒ rc=2
#   而**执行**它是一个更坏的故事：macOS bash 3.2 逐块解析 ⇒ 错误之前那部分**照跑**、
#   stderr 只留一行 `syntax error`、**exit status 仍是 0** ⇒ 本地「全绿」；
#   ubuntu bash 5.1 直接 `rc=2` 且 stdout **一个字都没有** ⇒ 只有 CI 红。
# ⇒ 下面两条把「重建体先是合法脚本」钉成**会红**的判据（红证见第二条）。

def test_every_reconstruction_is_a_legal_script():
    """🔴 类级固化：**每一个**重建变体在拿去执行之前，先过**同一个 `bash`** 的 `bash -n`。"""
    text = read_deploy_sh()
    for label, variant in (("deploy.sh 真身", text),
                           ("_pre_fix_script 重建体", _pre_fix_script(text)),
                           ("_pre_6551_script 重建体", _pre_6551_script(text))):
        _bash_syntax_check(variant, label)      # 不合法 ⇒ 当场红 + 打印出错行


def test_fixture_syntax_selfcheck_goes_red_on_a_broken_variant():
    """🔴 自证的红证：故意弄坏（删掉配对的 `if`、留下**孤儿 `fi`** —— 正是本轮 CI 的形态）
    ⇒ **夹具自证先红**，且红在「夹具不合法」这条上，而不是在业务断言上。"""
    broken = _inject(read_deploy_sh(), 'if [ "$CONFIG_REUSED" = "1" ]; then\n', "")
    with pytest.raises(AssertionError) as ei:
        _bash_syntax_check(broken, "故意弄坏的变体")
    msg = str(ei.value)
    assert "夹具不合法" in msg, f"自证红在别的地方（不是「夹具不合法」）：{msg}"
    assert "syntax error" in msg, f"自证没打印出错行：{msg}"


def test_pre_fix_reconstruction_is_faithful():
    """反空跑：还原出来的「修复前」码路必须**只**换了那一处（其余一字不动）。"""
    text = read_deploy_sh()
    old = _pre_fix_script(text)
    assert judge_config_same_source(old) != [], "还原后判据①竟然还是干净的 ⇒ 判据没有判别力"
    assert judge_rails_intact(old) == [], "还原误伤了护栏面（红证会变成别的原因）"
    assert old.count("cp src/deploy/swas/nginx.conf ./nginx/nginx.conf") == 1, "还原误伤了配置落点"
    assert f'"{CONFIG_URL_PREFIX}{MAIN_REF}"' in old, "还原没换上「取 main」的 URL（红证空跑）"
    assert MARKER_WRITE_TOKEN in old, "还原误伤了「物化 ref」标记那一段"
    assert FETCH_CALLSITE in old and FETCH_ELIF_TOKEN in old, "还原误伤了取配置的调用结构"
    # #6551 的还原：URL 仍按 tag 推导（#5083 的修法仍在），只少了「复用 + 多轮重试」。
    old6551 = _pre_6551_script(text)
    assert FETCH_REF_TOKEN in old6551, "#6551 的还原误伤了配置同源的 URL（红证会变成别的原因）"
    assert "if false; then" in old6551, "#6551 的还原没短路复用（红证空跑）"
    assert "CONFIG_FETCH_ATTEMPTS=${CONFIG_FETCH_ATTEMPTS:-1}" in old6551, (
        "#6551 的还原没把轮次预算改成 1（红证空跑）"
    )
    assert MAIN_REF not in non_comment(old6551), "#6551 的还原把配置源换回了 main（红证会变成别的原因）"


def test_exec_pre_fix_takes_main_config(tmp_path):
    """🔴 判别力红证：**同一组输入**下，「修复前」的码路取到的就是 **main 的最新配置**。

    这一条证明上面两条执行式断言（落盘 marker 必须是该 tag 那份）**不是空断言**：
    只把配置 ref 换回 main，旧镜像就会配上 main 的新配置（= #5083 要修的病根）。
    """
    fixtures = {MAIN_REF: MARKER_MAIN, "aaaaaaa": MARKER_OLD}
    proc, log, urls, work = _run(tmp_path, _pre_fix_script(read_deploy_sh()), tag=OLD_TAG,
                                 fixtures=fixtures)
    assert proc.returncode == 0, f"修复前的码路本来就报成功（静默）：\n{proc.stdout}"
    # 🔴 只断言 rc 不够（#6551 的 CI 红）：bash 3.2 会把语法错**宽容掉**（前半段照跑、rc 仍 0）
    assert proc.stdout.strip(), f"重建体 stdout 为空（= CI 上那个形态：bash 5.1 rc=2 且零输出）：\n{proc.stderr}"
    assert "syntax error" not in proc.stderr, f"重建体有语法错（本地 bash 3.2 会宽容掉 ⇒ 假绿）：\n{proc.stderr}"
    assert urls == [f"{CONFIG_URL_PREFIX}refs/heads/main"], f"修复前没取 main（锚点过期）：{urls}"
    landed = _landed_nginx(work)
    assert f"CONFIG_MARKER={MARKER_MAIN}" in landed, (
        f"修复前竟没配上 main 的配置（= 事故不复现）：\n{landed[-200:]}"
    )
    assert f"CONFIG_MARKER={MARKER_OLD}" not in landed, "修复前用了该 tag 的配置（= 事故不复现）"


# ══════════════════════════════════════════════════════════════════════════
# 四、#6551 执行式判据（① 可观测重试；② 回滚路径与下载闸门解耦）
# ══════════════════════════════════════════════════════════════════════════

def test_exec_retry_is_observable_and_restarts_from_zero(tmp_path):
    """🔴 判据 ⑤（执行式）：第一轮**半途截断**（桩截断响应 ⇒ `curl: (28)` 同族）
    ⇒ 第二轮**重新取一次**成功，且**每一次重试都在日志里出声**。

    四条机器读数（内容级 / 流水级，不看措辞）：
      ① `stdout` 里有「第 1/N 次失败（curl exit=…，本轮收到 X 字节）⇒ **第 2 次重试**」；
      ② `X > 0` ⇒ 失败行给的是**真实读数**（判「有没有进展」的唯一依据）；
      ③ 两轮的偏移**都是 0** ⇒ 第二轮是**从 0 重取**、上一轮的残包已被删 —— 与 #6550 的实测一致
         （codeload 不支持 Range ⇒ 不许假装续传；`-C -` 登记为**勿再引入**）；
      ④ 盘上 `src.tar.gz` 与桩上的夹具**逐字节相同** ⇒ 重取没有拼出坏包。
    """
    fixtures = {MAIN_REF: MARKER_MAIN, "aaaaaaa": MARKER_OLD}
    proc, log, urls, work = _run(tmp_path, read_deploy_sh(), tag=OLD_TAG, fixtures=fixtures,
                                 curl_body=CURL_RANGE_STUB, fail_plan_count=1)
    assert proc.returncode == 0, f"截断一次后应当靠重试成功：\n{proc.stdout}\n{proc.stderr}"
    ranges = _range_headers(tmp_path)
    assert ranges == ["Range: bytes=0-", "Range: bytes=0-"], (
        f"两轮都必须是「从 0 重取」（残包已删、且不发偏移）；实得：{ranges}"
    )
    m = re.search(r"第 1/\d+ 次失败（curl exit=\d+，本轮收到 (\d+) 字节）⇒ \*\*第 2 次重试\*\*", proc.stdout)
    assert m, f"重试没有在日志里出声（本单的核心教训）：\n{proc.stdout}"
    assert int(m.group(1)) > 0, f"失败行没有给出真实字节数：{m.group(0)}"
    fixture = tmp_path / "config" / "aaaaaaa.tar.gz"
    assert (work / "src.tar.gz").read_bytes() == fixture.read_bytes(), (
        "重取后的包与夹具不是逐字节相同 ⇒ 拼出了坏包"
    )
    assert f"CONFIG_MARKER={MARKER_OLD}" in _landed_nginx(work), "重试成功后配置没落盘"
    assert (work / ".config-ref").read_text(encoding="utf-8").strip() == "aaaaaaa", (
        "「物化 ref」标记没写对 ⇒ 下次（含回滚）复用不了现盘配置"
    )
    assert "单次上界 900s" in proc.stdout, f"没有把本轮上界回显进日志：\n{proc.stdout}"


def test_exec_pre_6551_single_attempt_fails_on_truncated_response(tmp_path):
    """🔴 判别力红证（#6551 ①）：**同一组输入**下，改动前的码路（**只有一次尝试**）在
    「第一轮截断」上**必失败**（`取不到 tag=… 对应的配置` ⇒ 中止部署）—— 这正是本单现场。

    ⚠️ 桩不模拟 `--retry`：与**现取事故读数一致**（半途超时那一族它从不触发）——
    真实 `curl --retry 3` 的逐字读数见 PR body 的「真 curl + 本地桩」红证。
    """
    fixtures = {MAIN_REF: MARKER_MAIN, "aaaaaaa": MARKER_OLD}
    proc, log, urls, work = _run(tmp_path, _pre_6551_script(read_deploy_sh()), tag=OLD_TAG,
                                 fixtures=fixtures, curl_body=CURL_RANGE_STUB, fail_plan_count=1)
    assert proc.returncode != 0, f"截断响应下改动前竟成功了（红证空跑）：\n{proc.stdout}"
    assert "syntax error" not in proc.stderr, f"重建体有语法错（本地 bash 3.2 会宽容掉 ⇒ 假绿）：\n{proc.stderr}"
    assert "取不到 tag=sha-aaaaaaa 对应的配置" in proc.stdout, proc.stdout
    assert RETRY_ECHO_TOKEN not in proc.stdout, f"改动前不该有任何重试行：\n{proc.stdout}"
    assert _landed_nginx(work) == "", "改动前失败却写了配置（= 不该发生的降级）"


def test_exec_rollback_reuses_on_disk_config_without_download(tmp_path):
    """🔴 判据 ⑥（执行式，**回滚路径解耦**）：现盘配置 == 目标 ref ⇒ **一次下载都不发**。

    形态（= 本单现场）：上一次成功部署留下 `.config-ref` 与三份 canonical 配置；本次是
    **回滚到同一 tag**（`deploy_attempt "$ROLLBACK_TAG"`）。桩上**该 ref 根本没有夹具**
    （`fixtures={}` ⇒ 任何下载都 404）⇒ 只要 rc==0，就证明「没去下载」，而不是「下载碰巧成功」。
    """
    seed = {
        ".config-ref": f"{OLD_TAG.removeprefix('sha-')}\n",
        "docker-compose.yml": "# CONFIG_MARKER=ON_DISK-compose\n",
        "nginx/nginx.conf": "# CONFIG_MARKER=ON_DISK-nginx\n",
        "docker-compose.bluegreen.yml": "# CONFIG_MARKER=ON_DISK-bluegreen\n",
    }
    proc, log, urls, work = _run(tmp_path, read_deploy_sh(), tag=OLD_TAG, fixtures={}, seed=seed)
    assert proc.returncode == 0, f"回滚复现盘配置不该失败：\n{proc.stdout}\n{proc.stderr}"
    assert urls == [], f"复用现盘配置时**仍在下载整仓**（本单的病根）：{urls}"
    assert "跳过整仓下载" in proc.stdout, f"复用没有被日志说出来（不可观测）：\n{proc.stdout}"
    assert "CONFIG_MARKER=ON_DISK-nginx" in _landed_nginx(work), (
        f"复用路径竟改写了现盘配置：\n{_landed_nginx(work)[-200:]}"
    )
    assert re.search(r"up -d --no-deps", log, re.M), f"复用后没有继续部署：\n{log}"


def test_exec_reuse_disabled_falls_back_to_download_and_fails_closed(tmp_path):
    """🔴 判据 ⑥ **双向**（判别力红证）：把复用判据短路（`return 1`）⇒ **同一组输入**下
    立刻回到「下载 404 ⇒ 中止部署」⇒ 证明上面那条「一次下载都不发」是复用**真的在起作用**。"""
    seed = {
        ".config-ref": f"{OLD_TAG.removeprefix('sha-')}\n",
        "docker-compose.yml": "# CONFIG_MARKER=ON_DISK-compose\n",
        "nginx/nginx.conf": "# CONFIG_MARKER=ON_DISK-nginx\n",
        "docker-compose.bluegreen.yml": "# CONFIG_MARKER=ON_DISK-bluegreen\n",
    }
    injected = _inject(read_deploy_sh(), REUSE_REF_TOKEN + " || return 1", "return 1")
    proc, log, urls, work = _run(tmp_path, injected, tag=OLD_TAG, fixtures={}, seed=seed)
    assert proc.returncode != 0, f"复用被短路后竟然还成功（红证空跑）：\n{proc.stdout}"
    assert urls != [], "复用被短路后应当回到下载路径（URL 流水为空 ⇒ 红证空跑）"
    assert "取不到 tag=sha-aaaaaaa 对应的配置" in proc.stdout, proc.stdout


def test_exec_reuse_requires_same_ref(tmp_path):
    """判据 ⑥ 的**护栏面**：现盘配置来自**别的 ref**（标记不匹配）⇒ 必须重新下载（不许复用）。

    这是「配置与镜像同源」不收放松的机械证据：盘上有三份文件也**不算**，ref 对不上就得取目标那份。
    """
    seed = {
        ".config-ref": "ccccccc\n",
        "docker-compose.yml": "# CONFIG_MARKER=ON_DISK-compose\n",
        "nginx/nginx.conf": "# CONFIG_MARKER=ON_DISK-nginx\n",
        "docker-compose.bluegreen.yml": "# CONFIG_MARKER=ON_DISK-bluegreen\n",
    }
    fixtures = {MAIN_REF: MARKER_MAIN, "aaaaaaa": MARKER_OLD}
    proc, log, urls, work = _run(tmp_path, read_deploy_sh(), tag=OLD_TAG, fixtures=fixtures, seed=seed)
    assert proc.returncode == 0, f"标记不匹配时应当下载：\n{proc.stdout}\n{proc.stderr}"
    assert urls == [f"{CONFIG_URL_PREFIX}aaaaaaa"], f"标记不匹配却没取目标 ref 的配置：{urls}"
    assert f"CONFIG_MARKER={MARKER_OLD}" in _landed_nginx(work), (
        "标记不匹配时复用了别 ref 的现盘配置 ⇒ 「旧镜像 + 新配置」（#5083 护栏被放松）"
    )


def test_exec_reuse_with_incomplete_on_disk_config_warns_and_downloads(tmp_path):
    """判据 ⑥ 的**降级面**：标记对得上但三份 canonical 文件**不齐** ⇒ `::warning::` + 重新下载。"""
    seed = {
        ".config-ref": f"{OLD_TAG.removeprefix('sha-')}\n",
        "docker-compose.yml": "# CONFIG_MARKER=ON_DISK-compose\n",
        "nginx/nginx.conf": "# CONFIG_MARKER=ON_DISK-nginx\n",
        # 故意缺 docker-compose.bluegreen.yml（半套现盘配置）
    }
    fixtures = {MAIN_REF: MARKER_MAIN, "aaaaaaa": MARKER_OLD}
    proc, log, urls, work = _run(tmp_path, read_deploy_sh(), tag=OLD_TAG, fixtures=fixtures, seed=seed)
    assert proc.returncode == 0, f"降级为下载后应当成功：\n{proc.stdout}\n{proc.stderr}"
    assert "::warning::" in proc.stdout, f"降级没有出声：\n{proc.stdout}"
    assert "三份 canonical 配置不齐" in proc.stdout, proc.stdout
    assert urls == [f"{CONFIG_URL_PREFIX}aaaaaaa"], urls
    assert f"CONFIG_MARKER={MARKER_OLD}" in _landed_nginx(work), "降级后没有用下载到的那份配置"


# ── C′ 形态的回滚腿（#6551 ② 的另一半：构建上下文）─────────────────────────────
# C′（#5814）下 `src/` 是**构建上下文**，而 deploy.sh 在构建成功后按磁盘策略把它删掉（~84MB 常驻）
# ⇒ 回滚到「上一次成功部署」那个 tag 时，盘上**有配置、没有源码树**。若只看配置，复用就是纸面权利：
# 下载仍会被「构建需要源码树」拉回来。下面两条就是这一层的判据（正向 + 双向）。

def _cprime_reuse_seed() -> dict:
    return {
        ".config-ref": f"{OLD_TAG.removeprefix('sha-')}\n",
        "docker-compose.yml": "# CONFIG_MARKER=ON_DISK-compose\n",
        "nginx/nginx.conf": "# CONFIG_MARKER=ON_DISK-nginx\n",
        "docker-compose.bluegreen.yml": "# CONFIG_MARKER=ON_DISK-bluegreen\n",
    }


def test_exec_cprime_rollback_skips_download_and_build_when_image_local(tmp_path):
    """🔴 判据 ⑥（执行式，**C′ 回滚腿**）：源码树不在盘上、但本地已有该 tag 的镜像
    ⇒ 复用现盘配置 + **跳过服务器侧构建** ⇒ **一次下载都不发、一次构建都不发**，部署照常继续。

    形态 = 本单现场：回滚到 `.last-good-tag`（上一轮成功部署留下的配置在盘上，回滚点镜像在本地）。
    桩上**任何 ref 都没有夹具**（`fixtures={}`）⇒ rc==0 就证明「没去下载」。
    """
    proc, log, urls, work = _run(tmp_path, read_deploy_sh(), tag=OLD_TAG, fixtures={},
                                 seed=_cprime_reuse_seed(), extra_env={"BUILD_SERVICE": "admin-api"},
                                 local_images=[f"dockerstub/admin-api:{OLD_TAG}"])
    assert proc.returncode == 0, f"C′ 回滚（配置在盘 + 镜像在本地）不该失败：\n{proc.stdout}\n{proc.stderr}"
    assert urls == [], f"复用现盘配置时仍在下载整仓（本单的病根）：{urls}"
    assert "跳过服务器侧构建" in proc.stdout, f"没有跳过构建 ⇒ C′ 回滚腿仍与下载闸门耦合：\n{proc.stdout}"
    assert not re.search(r"^docker build", log, re.M), f"仍发起了构建（本地镜像已是权威来源）：\n{log}"
    assert re.search(r"up -d --no-deps admin-api$", log, re.M), f"跳过构建后没有继续部署：\n{log}"


def test_exec_cprime_rollback_without_local_image_falls_back_and_fails_closed(tmp_path):
    """🔴 判据 ⑥ **双向**：同一状态但本地**没有**该 tag 的镜像 ⇒ 必须取源码树（下载）⇒
    桩上取不到 ⇒ **中止部署**。证明「跳过构建」不是无条件放行，fail-closed 语义没被放松。
    """
    proc, log, urls, work = _run(tmp_path, read_deploy_sh(), tag=OLD_TAG, fixtures={},
                                 seed=_cprime_reuse_seed(), extra_env={"BUILD_SERVICE": "admin-api"},
                                 local_images=[])
    assert proc.returncode != 0, f"本地没有镜像竟然还成功（红证空跑）：\n{proc.stdout}"
    assert urls != [], "应当回到下载路径（URL 流水为空 ⇒ 红证空跑）"
    assert "取不到 tag=sha-aaaaaaa 对应的配置" in proc.stdout, proc.stdout
    assert _landed_nginx(work) == "# CONFIG_MARKER=ON_DISK-nginx\n", (
        "拒绝复用之后不该改写现盘配置（fail-closed）"
    )
