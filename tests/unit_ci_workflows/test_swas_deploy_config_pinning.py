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

## 本文件锁什么（4 条判据，每条都有**能单独让它变红**的变异）

1. **配置 ref 与镜像 tag 同源**：配置 URL 的 ref 由 `config_ref_for_tag "$TAG"` 推导
   （`sha-<hex>` ⇒ 该 commit；其它 ⇒ `refs/tags/<tag>`）⇒ 脚本里**不存在**无条件取
   `refs/heads/main` 的路径（静态判据 + 执行式判据：URL 逐字断言）。
2. **回滚场景**：给定旧 `IMAGE_TAG` + 「main 已前进」夹具（main 的包里带 `CONFIG_MARKER=MAIN`）
   ⇒ 实际落到 `nginx/nginx.conf` 的必须是**该 tag 那份**（`CONFIG_MARKER=OLD`），不是 main 的。
3. **取不到匹配配置 ⇒ fail-closed**：非零退出 + 可行动报错；**main 的配置就在桩上可取**也不许回落到它
   （「没回落」是可断言的：URL 流水里没有 main、且没写任何配置文件）。
4. **既有安全护栏不削弱**：下载仍是 `curl -fsSL` + 重试/超时预算；`tag_to_sha()` 只有一份。

## ⚠️ 红证的真实性边界（**照实登记，不粉饰**）

执行式判据跑的是**本机 + 桩化的外部依赖**（codeload / docker / flock / timeout），**不是**真实 SWAS 部署；
被桩化的是外部依赖，被测的是 `deploy.sh` 的**配置源推导与 fail-closed 编排**本身。
真实 `codeload` 形态已**只读实测**（本机 curl，2026-09-21）：`tar.gz/<7位短 sha>` ⇒ HTTP 200（8.6s）、
`tar.gz/refs/heads/main` ⇒ HTTP 200、`tar.gz/refs/tags/latest` ⇒ **404**（0.54s）、`tar.gz/deadbee` ⇒ **404**
—— 即「短 sha 可解析」「不存在的 tag/commit 取不到 ⇒ fail-closed 真的会触发」。
**未取证**：真实服务器的端到端部署/回滚（本 PR 无 SWAS 访问、无 docker）⇒ 见 PR body 的「未取证/边界」。
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

# 修复前的那一行（**逐字内联**，见模块 docstring；内联而不是 `git show origin/main:…`
# —— 后者会随合并变成"修复后"文本 ⇒ 判据自红，§18.3）
PRE_FIX_FETCH_LINE = (
    "curl -fsSL --retry 3 --retry-delay 5 --connect-timeout 15 --max-time 120 -o src.tar.gz "
    "https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/refs/heads/main"
)

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
    for anchor in (CONFIG_SECTION_ANCHOR, CONFIG_ECHO_ANCHOR, FETCH_REF_TOKEN, DERIVE_TOKEN):
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
    i_derive = text.find(DERIVE_TOKEN)
    i_fetch = text.find(FETCH_REF_TOKEN)
    i_disk = text.find(DISK_ANCHOR)
    if i_derive > i_fetch:
        v.append("配置 ref 在**下载之后**才推导 ⇒ URL 里的 ref 不是它（判据形同虚设）")
    if i_fetch > i_disk:
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
    # ⓑ 下载失败（404 等）⇒ 立即停，绝不回落
    m = re.search(r'if ! curl -fsSL(.*?)\nfi\n', sec, re.S)
    if not m:
        v.append("找不到「下载失败 ⇒ 中止」的 `if ! curl …` 分支（fail-closed 判据已过期）")
    else:
        blk = m.group(1)
        if "exit 1" not in blk:
            v.append("配置下载失败时没有 `exit 1` ⇒ 静默降级（本单禁止）")
        for token in ("绝不回落到 main 的配置", "移动 tag", "存在且可达"):
            if token not in blk:
                v.append(f"下载失败分支缺少可行动提示：{token!r}")
    # ⓒ 包内容不完整（旧 commit 无蓝绿 override / 被劫持的 200）⇒ 立即停，不混用 main 的同名文件
    m = re.search(r'if \[ ! -f src/deploy/swas/docker-compose\.yml \](.*?)\nfi\n', sec, re.S)
    if not m:
        v.append("找不到「包内容自检」分支（旧 commit 缺文件时会用 `cp` 报错兜底，报错不可行动）")
    else:
        blk = m.group(1)
        if "exit 1" not in blk:
            v.append("包内容不完整时没有 `exit 1`")
        for token in ("docker-compose.bluegreen.yml", "早于 #4785", "migao 仓库树"):
            if token not in blk:
                v.append(f"包内容自检分支缺少：{token!r}")
    return v


def judge_rails_intact(text: str) -> list:
    """④ 既有安全护栏不削弱：下载的 curl 预算/失败语义、以及配置落点仍是三份 canonical 文件。"""
    v = []
    sec = section(text, CONFIG_SECTION_ANCHOR, NEXT_SECTION_ANCHOR)
    fetch = [ln for ln in sec.splitlines() if "curl -fsSL" in ln]
    if len(fetch) != 1:
        v.append(f"配置下载的 curl 行不是恰好 1 行（{len(fetch)} 行）")
    else:
        for flag, why in (("-f", "HTTP 非 2xx 即失败（没有 -f ⇒ 404 也会「成功」）"),
                          ("--retry 3", "重试预算"),
                          ("--connect-timeout 15", "连接超时预算"),
                          ("--max-time 120", "整体超时预算")):
            if flag not in fetch[0]:
                v.append(f"配置下载削弱了既有护栏：{flag}（{why}）")
    for token in ("cp src/deploy/swas/docker-compose.yml ./docker-compose.yml",
                  "cp src/deploy/swas/nginx.conf ./nginx/nginx.conf",
                  "cp src/deploy/swas/docker-compose.bluegreen.yml ./docker-compose.bluegreen.yml"):
        if token not in sec:
            v.append(f"canonical 配置落点被改动：找不到 `{token}`")
    return v


def all_violations(text: str) -> list:
    return judge_config_same_source(text) + judge_fail_closed(text) + judge_rails_intact(text)


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
    assert PRE_FIX_FETCH_LINE not in text, "修复前那一行仍在脚本里 ⇒ 配置仍随 main 漂移"
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
        '  echo "  ❌ 取不到 tag=${TAG} 对应的配置（ref=${CONFIG_REF_RESOLVED}）⇒ **中止部署**（绝不回落到 main 的配置）"',
        '  echo "  ⚠️ 取不到配置，继续（静默降级）"',
    )
    injected = _inject(injected, "  echo \"     · 否则核对：该 commit/tag 在 zhaokai-mgzn/migao 上存在且可达\"\n  exit 1\n",
                       "  echo \"     · 否则核对：该 commit/tag 在 zhaokai-mgzn/migao 上存在且可达\"\n")
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
    m = re.search(r'if \[ ! -f src/deploy/swas/docker-compose\.yml \](.*?)\nfi\n', text, re.S)
    assert m, "反空跑锚点：找不到包内容自检"
    injected = text[:m.start()] + text[m.end():]
    assert "cp src/deploy/swas/docker-compose.yml" in injected
    assert judge_fail_closed(injected) != [], "删掉包内容自检后判据没红（判据无判别力）"


def test_injection_weaken_curl_rails_goes_red():
    """注入⑦：去掉 `-f`（HTTP 404 也会被当成功）⇒ 判据 ④ 必红。"""
    injected = _inject(read_deploy_sh(), "if ! curl -fsSL --retry 3", "if ! curl -sSL --retry 3")
    assert judge_rails_intact(injected) != [], "去掉 `-f` 后判据没红（判据无判别力）"


def test_injection_drop_timeout_budget_goes_red():
    """注入⑧：去掉 `--max-time 120`（下载可能无限挂住部署）⇒ 判据 ④ 必红。"""
    injected = _inject(read_deploy_sh(), "--connect-timeout 15 --max-time 120 -o src.tar.gz",
                       "--connect-timeout 15 -o src.tar.gz")
    assert judge_rails_intact(injected) != [], "去掉整体超时预算后判据没红（判据无判别力）"


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

DOCKER_STUB = """#!/bin/bash
# 桩 docker：记录调用；`compose ps -q <svc>` / `inspect --format … <cid>` 回放 $RUNNING_DIR/<svc>
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


def _prepare(tmp_path: Path, script_text: str, fixtures: dict) -> tuple:
    """沙箱：脚本副本（改写绝对路径）+ 桩 bin + 各 ref 的配置夹具 + .env 文件。"""
    work = tmp_path / "opt-migao-deploy"
    work.mkdir(parents=True, exist_ok=True)
    text = script_text
    text = text.replace("/opt/migao-deploy", str(work))
    text = text.replace("/tmp/migao-deploy.lock", str(work / "deploy.lock"))
    text = text.replace("/tmp/hc_", f"{work}/hc_")
    script = work / "deploy.sh"
    script.write_text(text, encoding="utf-8")
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
    _write_exe(bin_dir / "curl", CURL_STUB)
    _write_exe(bin_dir / "docker", DOCKER_STUB)
    _write_exe(bin_dir / "flock", FLOCK_STUB)
    _write_exe(bin_dir / "timeout", TIMEOUT_STUB)
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    return work, script, bin_dir, state, config_dir


def _run(tmp_path: Path, script_text: str, *, tag: str, fixtures: dict,
         running: dict | None = None, ancestry: dict | None = None, extra_env: dict | None = None):
    """跑脚本。

    fixtures: {ref: marker} —— 桩上**可取到**的配置包（ref 不在其中 ⇒ 404 ⇒ 22）
    running:  {服务: tag} —— 「当前在跑」的镜像 tag（缺 ⇒ 没有在跑容器 ⇒ 判据 unknown）
    ancestry: {"<target>..<current>": status} —— compare API 回放（缺 ⇒ API 取不到）
    """
    work, script, bin_dir, state, config_dir = _prepare(tmp_path, script_text, fixtures)
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
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DOCKER_LOG": str(docker_log),
        "CONFIG_URL_LOG": str(url_log),
        "CONFIG_DIR": str(config_dir),
        "RUNNING_DIR": str(running_dir),
        "ANCESTRY_DIR": str(anc_dir),
        "HC_STATE": str(state),
        "HC_RETRIES": "2",
        "HC_INTERVAL_SECONDS": "0",
        # /proc/meminfo 在 macOS 不存在 ⇒ 预检恒判 0MB；把门槛设为 0 以聚焦编排
        "BG_MEM_NEED_MB": "0",
        "BG_OFF_FILE": str(work / ".blue-green-off"),
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
    assert urls == [f"{CONFIG_URL_PREFIX}refs/tags/latest"], (
        f"没有去取该 tag 对应的 ref，或取过 main：{urls}"
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


def _pre_fix_script(text: str) -> str:
    """把配置下载那一段**只还原成修复前的 URL**（其余一字不动）—— 即「修复前」的码路。

    这样红证隔离的**正是**本单的那一处差异（配置 ref），不是别的改动。
    """
    m = re.search(r"if ! curl -fsSL[^\n]*\n(?:.*\n)*?fi\n", text)
    assert m, "反空跑锚点：找不到配置下载段"
    out = text[:m.start()] + PRE_FIX_FETCH_LINE + "\n" + text[m.end():]
    assert PRE_FIX_FETCH_LINE in out, "还原没生效（红证空跑）"
    assert FETCH_REF_TOKEN not in out, "还原后仍残留按 tag 推导的 URL（红证空跑）"
    assert DERIVE_TOKEN in out, "还原误伤了推导行（红证会变成别的原因）"
    return out


def test_pre_fix_reconstruction_is_faithful():
    """反空跑：还原出来的「修复前」码路必须**只**少了配置同源这一件事。"""
    old = _pre_fix_script(read_deploy_sh())
    assert judge_rails_intact(old) == [], "还原后既有护栏反而少了 ⇒ 还原手法有缺陷：\n- " + "\n- ".join(
        judge_rails_intact(old)
    )
    assert judge_config_same_source(old) != [], "还原后判据①竟然还是干净的 ⇒ 判据没有判别力"
    assert "cp src/deploy/swas/nginx.conf ./nginx/nginx.conf" in old


def test_exec_pre_fix_takes_main_config(tmp_path):
    """🔴 判别力红证：**同一组输入**下，「修复前」的码路取到的就是 **main 的最新配置**。

    这一条证明上面两条执行式断言（落盘 marker 必须是该 tag 那份）**不是空断言**：
    只把配置 ref 换回 main，旧镜像就会配上 main 的新配置（= 本单要修的病根）。
    """
    fixtures = {MAIN_REF: MARKER_MAIN, "aaaaaaa": MARKER_OLD}
    proc, log, urls, work = _run(tmp_path, _pre_fix_script(read_deploy_sh()), tag=OLD_TAG, fixtures=fixtures)
    assert proc.returncode == 0, f"修复前的码路本来就报成功（静默）：\n{proc.stdout}"
    assert urls == [f"{CONFIG_URL_PREFIX}refs/heads/main"], f"修复前没取 main（锚点过期）：{urls}"
    landed = _landed_nginx(work)
    assert f"CONFIG_MARKER={MARKER_MAIN}" in landed, (
        f"修复前竟没配上 main 的配置（= 事故不复现）：\n{landed[-200:]}"
    )
    assert f"CONFIG_MARKER={MARKER_OLD}" not in landed, "修复前用了该 tag 的配置（= 事故不复现）"
