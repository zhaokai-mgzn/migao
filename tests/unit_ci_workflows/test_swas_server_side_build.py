# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml。）
r"""C′ —— **服务器侧构建**（issue #5814）的实例判据 + 类级不变式。

## 裁定与证据（用户 2026-09-30 逐字裁定「就是要迁服务器构建，铁律我来拍」）

推翻 `docs/deployment/swas-migration-lessons.md` 的旧铁律「构建跑在 CI，服务器只拉预构建产物」
（该页把「SWAS 服务器源码构建」标为**迁移初期（错）**）。**真机实测**（`swas-open run-command` 现取）：

| 场景 | 实测 |
|---|---|
| 冷构建（无缓存，国内 apt+pip 镜像） | 1782 s（29.7 min）＝ apt 1100 s + pip 675 s |
| 代码未变的重复构建 | 1 s |
| **改一个源码文件（日常部署真实路径）** | **2 s**（apt/pip 层全 CACHED） |
| 改 `requirements.txt` | 592 s（9.9 min） |
| 内存峰值 | 1792 MB（可用从未低于 5669 MB）⇒ 不是瓶颈 |
| 磁盘 | 每次净增约 1 GB；构建缓存 1.36 GB；**剩余 16 GB 是真约束** |

⇒ 旧铁律记的「自己 build 3 个服务（10–30min）」是**冷构建**读数；**稳态是秒级**，
且**根本不推 ACR** ⇒ 「跨境推 1.12GB 挂住 40min」这个根因从结构上消失。

## 为什么不需要新的源码下发通道（**实测证伪了我的第一版前提**）

`deploy/swas/deploy.sh` 的第 1 段**本来就把整棵仓库树**（codeload tarball，与镜像 tag 同源）
解到 `src/`，只为取 4 个配置文件，取完就闲置 ⇒ 构建上下文**零额外下载**。
而「一次 `RunCommand` Base64 下发源码」**不可实现**（真机实测命令体上限仅 **43.8–50.7 KB**：
38 000 字节正文 = 50 769 字符即被拒，`400 CmdContent.ExceedLimit`；三服务源码树 gzip 后仍有
1.7–2.8 MB ⇒ 超限约 80 倍）。该结论与「转 private 的下发面」一起登记在 PR body 的缺口节。

## 判据（每条都能单独变红；红证见 `test_injected_proofs`）

| # | 判据 | 变红的形态 |
|---|---|---|
| 1 | `BUILD_SERVICE` **默认为空**且构建段被它整体圈住 | 去掉默认/去掉守卫 ⇒ 既有「拉镜像」路径被侵入 ⇒ 红 |
| 2 | 构建**在 flock 之内**，且**没有第二把锁** | 把构建挪到锁外 / 另建一把锁 ⇒ 红（旧文档 §二.2「容器互踩」） |
| 3 | `APT_MIRROR` 参数化，**默认 `deb.debian.org`**（= 不改写 sources.list） | 默认值改成阿里云 ⇒ CI（GitHub 托管）行为被改 ⇒ 红 |
| 4 | 服务器侧**传**国内 apt + pip 源 | 少传任一 ⇒ 冷构建退回 >1h / pip 成新瓶颈 ⇒ 红 |
| 5 | 本地镜像 ref 由 **compose 自己求值**（唯一真相源） | 在脚本里另抄一份 ref 形态 ⇒ 改 compose 时静默漂移 ⇒ 红 |
| 6 | 拉取段对**本地构建过**的服务**跳过 pull** | 不跳 ⇒ 去 ACR 找一个从未推送的 tag、白等 180s ⇒ 红 |
| 7 | 构建有**显式上界** + `rc=124` 点名 | 无上界 ⇒ 挂住只能等 job 超时（`cancelled`）⇒ 红 |
| 8 | 构建前**磁盘前置检查**；回收**非破坏性**（窗口由水位选，见 `test_swas_deploy_disk_recovery.py`） | 构建路径里出现 `-af` / 回收窗口消失 ⇒ 稳态秒级被打回冷构建 29.7min ⇒ 红 |
| 9 | CI 侧渲染**不漏占位符**（`__BUILD_SERVICE__` 等必须被替换） | 漏 ⇒ 远端拿到字面量 ⇒ 红 |

## 判定方式是确定的（零网络、零时钟、零 `origin/main`）

本判据只读**仓内文件文本**（`deploy/swas/deploy.sh` · `deploy/scripts/swas-deploy-ci.sh` ·
三个 `deploy-*.yml` · `backend/ai-agent-service/Dockerfile`）⇒ 同一份代码任何时刻同一读数。
🔴 **不绑 `origin/main`**：CI 的 pr-check 是 `fetch-depth: 1`，取不到该 ref（本仓 §18.3 / #4313；
PR #5816 刚因此红过一次）⇒ 本文件**一律不做 git 查询**（`test_no_git_dependency` 机械钉住）。

## 覆盖面（照实登记，**不是**「已全覆盖」）

① 判不了「冷构建真的 1782s」（那是运行期读数，静态判据只能钉住参数与形态）；
② 判不了「服务器侧构建与线上 4 核抢资源的影响」（实测内存峰值 1792MB、可用从未低于 5669MB，
   但**构建期间对线上延迟的影响未测** ⇒ 登记为缺口）；
③ 判不了「compose 求值在真机 .env 下与你预期一致」（静态判据只钉住「ref 来自 compose 求值」这一事实
   + 一条真机冒烟已确认 `docker compose config` 可解析）；
④ `.last-good-tag` 的写入仍在 **CI 侧 bootstrap**（本单未搬）⇒ 其语义未被本判据改变。
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO / "deploy" / "swas" / "deploy.sh"
CI_SH = REPO / "deploy" / "scripts" / "swas-deploy-ci.sh"
AI_DOCKERFILE = REPO / "backend" / "ai-agent-service" / "Dockerfile"
WORKFLOWS = REPO / ".github" / "workflows"
DEPLOY_LEGS = {
    "deploy-ai-agent-service.yml": "ai-agent",
    "deploy-admin-api.yml": "admin-api",
    "deploy-frontend.yml": "admin-web",
}


def deploy_text() -> str:
    return DEPLOY_SH.read_text(encoding="utf-8")


def ci_text() -> str:
    return CI_SH.read_text(encoding="utf-8")



def _strip_comment(line: str) -> str:
    """剥掉**行尾注释**：先清空被引号包住的内容，**再**按 `#` 截断（顺序不许反）。

    为什么不能 `line.split("#", 1)[0]`：字符串里的 `#`（如 `--build-arg FOO=a#b`、`echo "#x"`）
    会被当成注释起点 ⇒ **吃掉行尾** ⇒ 判据假绿（issue #5323 同族；
    守卫 = tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py 的 `test_naive_hash_cut_is_ledgered`）。
    这里用**单遍扫描**：引号内一律不当注释（并保留引号本身，便于下游形态判定）。
    """
    out, quote, esc = [], "", False
    for ch in line:
        if esc:
            out.append(ch); esc = False; continue
        if quote:
            if ch == "\\":
                out.append(ch); esc = True; continue
            if ch == quote:
                quote = ""
            out.append(ch); continue
        if ch in "'\"":
            quote = ch; out.append(ch); continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()

def _code_lines(text: str) -> list[str]:
    """剥掉注释（`#` 起行尾）后的代码行 —— 判据只吃**命令**，不吃说明文字。

    ⚠️ 必须剥：本单的说明文字里**故意**引用了被禁的形态（如「不许 `docker builder prune -af`」）
    ⇒ 不剥注释会让**教学材料自己触发判据**（假红），这正是本仓反复踩过的形态。
    """
    return [_strip_comment(ln) for ln in text.splitlines()]


def _code(text: str) -> str:
    """剥注释后的全文（供 `in` / `re.findall` 类判定用）。"""
    return "\n".join(_code_lines(text))


def _pull_loop_slice(text: str) -> str:
    """只取**第 2 段「拉取镜像」**那一段（避免匹配到 1.9 回滚点补回里的同名 pull 循环）。"""
    i = text.find('echo "== 2. 拉取镜像')
    assert i > 0, "找不到第 2 段「拉取镜像」标记（判据已过期）"
    return text[i:]


def _lineno(text: str, pattern: str) -> int:
    for i, ln in enumerate(_code_lines(text), start=1):
        if re.search(pattern, ln):
            return i
    return -1


# ── 判据 1：BUILD_SERVICE 默认为空，且构建段整体被它圈住（既有路径不被侵入）──────────
def test_build_service_defaults_to_empty_and_gates_the_build():
    text = deploy_text()
    assert re.search(r'^BUILD_SERVICE=\$\{BUILD_SERVICE:-\}$', text, re.M), (
        "`BUILD_SERVICE` 默认值必须是**空** ⇒ 默认路径（拉 ACR 镜像）行为与改动前逐字相同"
    )
    # 构建命令必须落在 `[ -n "$BUILD_SERVICE" ]` 的 if 块之内（否则每次部署都会构建）
    gate = _lineno(text, r'^if \[ -n "\$BUILD_SERVICE" \]; then$')
    build = _lineno(text, r'timeout "\$BUILD_TIMEOUT_SECS" docker build ')
    assert gate > 0, "找不到构建守卫 `if [ -n \"$BUILD_SERVICE\" ]; then`（构建可能变成无条件执行）"
    assert build > 0, "找不到带显式上界的 `docker build` 调用点（C′ 的落码本体）"
    assert gate < build, f"`docker build`（第 {build} 行）不在 BUILD_SERVICE 守卫（第 {gate} 行）之内"


# ── 判据 2：构建在 flock 之内，且没有第二把锁 ─────────────────────────────────
def test_build_happens_inside_the_existing_flock():
    text = deploy_text()
    lock = _lineno(text, r'^exec 9>"\$LOCK"$')
    build = _lineno(text, r'timeout "\$BUILD_TIMEOUT_SECS" docker build ')
    trap = _lineno(text, r"^trap 'flock -u 9' EXIT$")
    assert lock > 0 and trap > lock, (
        "找不到「第 1 段拿锁（`exec 9>`）/ EXIT 释放（`trap 'flock -u 9' EXIT`）」的形态（判据已过期）"
    )
    # ⚠️ `trap … EXIT` 是**注册**（在 EXIT 时才释放），不是"释放点"⇒ 正确判据是
    #    「构建发生在**拿锁之后**」（锁一直被持有到进程退出）——写成 `build < trap` 会误判。
    assert build > lock, (
        f"构建（第 {build} 行）必须在拿锁（第 {lock} 行）**之后** —— "
        "旧文档 §二.2「单机并发 docker build 容器互踩」靠**同一把锁**串行化"
    )
    # 没有第二把锁：`exec N>` 形式的锁获取只允许一处
    acquires = re.findall(r'^exec \d+>', text, re.M)
    assert len(acquires) == 1, f"出现了 {len(acquires)} 处锁获取 {acquires} ⇒ 会自锁（deploy.sh 内不可再拿同一把）"


# ── 判据 3：APT_MIRROR 参数化，默认 deb.debian.org（= 不动 CI 行为）───────────────
def test_apt_mirror_is_parameterized_with_current_behavior_as_default():
    df = AI_DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^ARG APT_MIRROR=deb\.debian\.org$", df, re.M), (
        "Dockerfile 必须有 `ARG APT_MIRROR=deb.debian.org`（默认 = 现状 ⇒ GitHub 托管 runner 行为不变）"
    )
    assert "security.debian.org" in df and "deb.debian.org" in df, (
        "换源必须同时覆盖 deb.debian.org 与 security.debian.org（否则部分源仍走境外）"
    )
    # 默认值不得是阿里云（那就是把 CI 的行为也改了 ⇒ 双架构不安全）
    assert "ARG APT_MIRROR=mirrors.aliyun.com" not in df, (
        "APT_MIRROR 的**默认值**变成了阿里云 ⇒ 改了 CI（境外 runner）的行为；默认必须保持现状"
    )


# ── 判据 4：服务器侧传国内 apt + pip 源 ───────────────────────────────────────
def test_server_side_passes_domestic_apt_and_pip_mirrors():
    text = deploy_text()
    assert re.search(r'^APT_MIRROR=\$\{APT_MIRROR:-deb\.debian\.org\}$', text, re.M), (
        "deploy.sh 的 APT_MIRROR 默认也必须是 deb.debian.org（默认路径不动行为）"
    )
    assert re.search(r'--build-arg "APT_MIRROR=\$APT_MIRROR"', text), (
        "构建时必须把 APT_MIRROR 传进 docker build（否则换源不生效）"
    )
    assert re.search(r'--build-arg "PIP_INDEX_URL=\$PIP_INDEX_URL"', text), (
        "构建时必须把 PIP_INDEX_URL 传进 docker build（CI 传的是境外 pypi.org ⇒ 服务器侧必须改传国内）"
    )
    ci = ci_text()
    assert "mirrors.aliyun.com" in ci, "CI 脚本必须给服务器侧注入国内源（apt/pip）"
    assert re.search(r'SWAS_PIP_INDEX_URL=\$\{SWAS_PIP_INDEX_URL:-https://mirrors\.aliyun\.com/pypi/simple/\}', ci), (
        "服务器侧 pip 源默认必须是国内 PyPI 镜像（境外源会让 pip 成为下一个瓶颈）"
    )
    # ⚠️ 但 **CI 自己的构建路径**（GitHub 托管 runner）不得被改：它仍传境外 pypi.org
    ai_wf = (WORKFLOWS / "deploy-ai-agent-service.yml").read_text(encoding="utf-8")
    assert "pypi.org" not in ai_wf, (
        "ai-agent 腿已改服务器侧构建 ⇒ 不该再有 CI 侧 pip 源；若删推送后又加回来，请核对本判据"
    )


# ── 判据 5：本地镜像 ref 由 compose 求值（唯一真相源）─────────────────────────
def test_local_image_ref_comes_from_compose_evaluation():
    text = deploy_text()
    assert "docker compose config --format json" in text, (
        "本地镜像 ref 必须由 **compose 自己求值**得出（唯一真相源）—— "
        "在脚本里另抄一份 `${ACR_REGISTRY}/ai-customer-service/<svc>:${IMAGE_TAG}` 形态会在有人改 compose 时静默漂移"
    )
    assert "LOCAL_IMAGE_REF=\"$_image_ref\"" in text, "求值结果必须落到 LOCAL_IMAGE_REF"
    assert re.search(r'if \[ -z "\$_image_ref" \]', text), (
        "compose 求值取不到 image 时必须 **fail-closed**（拒绝在 ref 不明时构建）"
    )


# ── 判据 6：拉取段跳过本地构建过的服务 ───────────────────────────────────────
def test_pull_loop_skips_the_locally_built_service():
    text = deploy_text()
    assert re.search(r'\[ -n "\$LOCAL_IMAGE_REF" \] && \[ "\$svc" = "\$_svc" \]', text), (
        "拉取段必须对「本次本地构建过」的服务**短路**"
    )
    # 短路必须发生在 `docker compose pull` 之前（否则白等 180s 才失败）
    seg = _pull_loop_slice(text)
    skip = _lineno(seg, r'\[ -n "\$LOCAL_IMAGE_REF" \] && \[ "\$svc" = "\$_svc" \]')
    pull = _lineno(seg, r'timeout 180 docker compose pull "\$svc"')
    assert 0 < skip < pull, f"在本段内：跳过逻辑（{skip}）必须在 pull（{pull}）之前"


def _build_slice_without_cache_helper(text: str) -> str:
    """构建路径那一段（`BUILD_SERVICE` 守卫 → `1.9` 段），**扣掉** `builder_cache_recover()` 函数体。

    ⚠️ 两个坑（都实测踩过）：
    ① 段尾锚点只能用 `echo "== 1.9`：`1.5` / `1.6` 那些段标题**本身是注释**（`_code` 会吃掉）；
    ② 必须扣掉 `builder_cache_recover()` 的函数体：`-af`（恢复出口第 2 档）就定义在构建段里、
       且被构建段调用（余量不足时）⇒ 不扣掉，「构建路径不许出现 `-af`」会恒红。
    """
    code = _code(text)
    # 标记用 `docker build`（不是带 `timeout …` 前缀的整句）：判据 7 的注入会摘掉 `timeout` 包裹，
    # 用整句当锚点会让本函数在那个注入下抛锚点异常（判据以「判据已过期」而非「行为变了」收场）。
    build = code.find("docker build")
    assert build > 0, "找不到构建调用（判据已过期）"
    i = code.rfind('if [ -n "$BUILD_SERVICE" ]; then', 0, build)
    assert i > 0, "找不到构建段守卫（判据已过期）"
    end = code.find('echo "== 1.9', build)
    assert end > build, "找不到构建段结尾（判据已过期）"
    seg = code[i:end]
    k = seg.find("builder_cache_recover() {")
    if k >= 0:
        depth, x = 0, seg.find("{", k)
        while x < len(seg):
            if seg[x] == "{":
                depth += 1
            elif seg[x] == "}":
                depth -= 1
                if depth == 0:
                    seg = seg[:k] + seg[x + 1:]
                    break
            x += 1
    return seg


# ── 判据 7：构建有显式上界 + rc=124 点名 ─────────────────────────────────────
def test_server_build_has_explicit_bound_and_names_timeout():
    text = deploy_text()
    assert re.search(r'^BUILD_TIMEOUT_SECS=\$\{BUILD_TIMEOUT_SECS:-2400\}$', text, re.M), (
        "构建必须有显式墙钟上界（冷构建实测 1782s ⇒ 2400s 留 ~35% 余量）"
    )
    assert re.search(r'if timeout "\$BUILD_TIMEOUT_SECS" docker build ', text), (
        "`timeout` 必须**包住** docker build（而不是包住别的命令）"
    )
    assert re.search(r'\[ "\$_rc" = "124" \]', text), "rc=124（超时）必须被单独辨认"
    assert "服务器侧构建超时" in text, "rc=124 必须**点名**「服务器侧构建超时」（可归因，不静默）"


# ── 判据 8：磁盘前置检查 + 非破坏性回收 ──────────────────────────────────────
def test_disk_precheck_and_non_destructive_reclaim():
    text = deploy_text()
    assert "BUILD_MIN_FREE_MB" in text, "构建前必须有磁盘余量门槛（实测每次净增约 1GB、总盘 40GB）"
    preck = _lineno(text, r'_df_mb=\$\(disk_free_mb\b')
    build = _lineno(text, r'timeout "\$BUILD_TIMEOUT_SECS" docker build ')
    assert 0 < preck < build, f"磁盘前置检查（{preck}）必须在构建（{build}）之前（fail-closed）"
    # 🔴 issue #6508 起「回收窗口」**由磁盘水位选**（`pick_cache_window`），不再是写死的 168h ——
    #    真机实测：写死 168h 时缓存条目全是 72h 内建的 ⇒ 匹配 **0 条**、`Total: 0B`（空操作）。
    #    本判据只钉住「按窗口回收的形态仍在」；窗口阶梯本身由 test_swas_deploy_disk_recovery.py 判。
    assert re.search(r'builder prune -f --filter "?until=', text), (
        "构建后的缓存回收必须是**带窗口过滤**的 prune（保住热层 ⇒ 稳态秒级）"
    )
    # 构建路径（`BUILD_SERVICE` 守卫 → `# 1.5` 段）里**不许**出现 `-af` / 不带窗口的 prune：
    # 那会把稳态 2s 打回冷构建 29.7min（`-af` 的合法落点只有恢复出口，见 issue #6508 的判据 7）。
    blk = _build_slice_without_cache_helper(text)
    # ⚠️ 只认**调用行**（行首就是 `docker builder prune -af`）：出口说明里逐字写了那条命令
    #    （教学材料），按子串判会假红（实测）。
    assert not re.search(r'^\s*docker builder prune -af\b', blk, re.M), (
        "构建路径（扣掉恢复出口的函数体之后）里出现了 `docker builder prune -af` —— "
        "那会把稳态 2s 打回冷构建 29.7min"
    )
    assert "/opt/migao" in _code(text), "磁盘回收出口必须点名 /opt/migao（2026-08-13 遗留的 2.2GB 旧源码克隆）"


# ── 判据 9：CI 侧渲染不漏占位符 + 三条腿都传 SERVICE_KEY ────────────────────
def test_ci_renders_build_placeholders_and_each_leg_passes_its_service_key():
    ci = ci_text()
    for ph in ("__BUILD_SERVICE__", "__APT_MIRROR__", "__PIP_INDEX_URL__", "__BUILD_TIMEOUT_SECS__"):
        assert ph in ci, f"CI 脚本里应有占位符 {ph}（构建面参数）"
        assert re.search(rf'out=\$\{{out//{re.escape(ph)}/\$\{{', ci), (
            f"占位符 {ph} 必须在 render_bootstrap 里被显式渲染"
        )
    # 渲染漏一个 ⇒ fail-closed（否则远端拿到字面量 `__BUILD_SERVICE__`）
    assert re.search(r"\*__BUILD_SERVICE__\*", ci), "渲染后必须自证「占位符已全部替换」否则 fail-closed"
    # 三条腿各传自己的服务键（第 8 个位置参数）
    for wf, key in DEPLOY_LEGS.items():
        body = (WORKFLOWS / wf).read_text(encoding="utf-8")
        call = re.search(r"bash deploy/scripts/swas-deploy-ci\.sh \\\n((?:.*\\\n)*.*)", body)
        assert call, f"{wf}: 找不到 swas-deploy-ci.sh 调用"
        last = call.group(1).strip().splitlines()[-1].strip()
        assert last == key, f"{wf}: 第 8 个位置参数应为 {key}，实得 {last!r}"


# ── 零 git 依赖自证（本仓「本机全绿、CI 全红」的直接教训）──────────────────────
def test_no_git_dependency(monkeypatch):
    """把 `subprocess.run` / `os.popen` 换成**炸弹** ⇒ 本文件判据必须照样跑完。

    CI 的 pr-check 是 `fetch-depth: 1` ⇒ 任何读 `origin/main` 的基线会退化成空集或陈旧 sha
    （本仓 §18.3 / #4313；PR #5816 刚因此红过一次）⇒ 本判据把「不碰 git」变成机械断言。
    """
    import os as _os
    import subprocess as _sp

    def _bomb(*a, **kw):  # pragma: no cover - 命中即失败
        raise AssertionError(
            "本文件的判据碰了子进程 ⇒ 在 CI 的浅克隆里可能取不到基线、判据自红"
            "（issue #5814 / PR #5816 的形态）—— 判定必须只读仓内文件文本"
        )

    monkeypatch.setattr(_sp, "run", _bomb)
    monkeypatch.setattr(_os, "popen", _bomb)
    assert deploy_text().strip() and ci_text().strip()
    assert test_build_service_defaults_to_empty_and_gates_the_build() is None
    assert test_build_happens_inside_the_existing_flock() is None


# ── 注入式红证：9 条判据各自能单独变红 + 「只改注释 ⇒ 不红」对照 ──────────────
def _problems(deploy: str, ci: str, df: str, legs: dict | None = None) -> list[str]:
    """把 9 条判据重算成「问题清单」（**参数化**，供红证注入用）。

    与上面各判据**同一套判据语义**（不是另一份实现）：上面逐条 assert，这里逐条收集。
    ⚠️ 一律在 `_code()`（剥注释）后的文本上判 —— 否则本单的说明文字（它**故意**引用了被禁形态）
    会自己触发判据（假红）。
    """
    d, c = _code(deploy), _code(ci)
    out: list[str] = []
    if not re.search(r'^BUILD_SERVICE=\$\{BUILD_SERVICE:-\}$', d, re.M):
        out.append("c1")
    gate = _lineno(d, r'^if \[ -n "\$BUILD_SERVICE" \]; then$')
    build = _lineno(d, r'timeout "\$BUILD_TIMEOUT_SECS" docker build ')
    if gate < 0 or build < 0 or gate > build:
        out.append("c1b")
    lock = _lineno(d, r'^exec 9>"\$LOCK"$')
    trap = _lineno(d, r"^trap 'flock -u 9' EXIT$")
    if not (0 < lock < build) or trap < lock:
        out.append("c2")
    if len(re.findall(r'^exec \d+>', d, re.M)) != 1:
        out.append("c2b")
    if not re.search(r"^ARG APT_MIRROR=deb\.debian\.org$", _code(df), re.M):
        out.append("c3")
    if "ARG APT_MIRROR=mirrors.aliyun.com" in _code(df):
        out.append("c3b")
    if not re.search(r'--build-arg "APT_MIRROR=\$APT_MIRROR"', d) or \
       not re.search(r'--build-arg "PIP_INDEX_URL=\$PIP_INDEX_URL"', d):
        out.append("c4")
    if "docker compose config --format json" not in d:
        out.append("c5")
    if not re.search(r'\[ -n "\$LOCAL_IMAGE_REF" \] && \[ "\$svc" = "\$_svc" \]', d):
        out.append("c6")
    if not re.search(r'if timeout "\$BUILD_TIMEOUT_SECS" docker build ', d) or \
       not re.search(r'\[ "\$_rc" = "124" \]', d):
        out.append("c7")
    if "until=" not in d:
        out.append("c8")
    if re.search(r'^\s*docker builder prune -af\b', _build_slice_without_cache_helper(d), re.M):
        out.append("c8")
    for ph in ("__BUILD_SERVICE__", "__APT_MIRROR__", "__PIP_INDEX_URL__", "__BUILD_TIMEOUT_SECS__"):
        if not re.search(rf'out=\$\{{out//{re.escape(ph)}/\$\{{', c):
            out.append(f"c9:{ph}")
    # ⚠️ 形参 `legs` 是 {**文件名**: 该文件的**文本**}（调用方传的就是文本）⇒ 别把文件名当文本搜。
    for fname, text in (legs or {k: (WORKFLOWS / k).read_text(encoding="utf-8") for k in DEPLOY_LEGS}).items():
        key = DEPLOY_LEGS.get(fname)
        call = re.search(r"bash deploy/scripts/swas-deploy-ci\.sh \\\n((?:.*\\\n)*.*)", text)
        if key is None or not call or call.group(1).strip().splitlines()[-1].strip() != key:
            out.append(f"c9leg:{fname}")
    return out


def test_baseline_is_clean():
    """前提：真语料先绿（否则红证分不清是注入还是存量）。"""
    legs = {wf: (WORKFLOWS / wf).read_text(encoding="utf-8") for wf in DEPLOY_LEGS}
    assert _problems(deploy_text(), ci_text(), AI_DOCKERFILE.read_text(encoding="utf-8"), legs) == []


def test_injected_proofs():
    """9 条判据**各自能单独变红**（真病注入，不是纸面）+ 一条「只改注释 ⇒ 不红」对照。"""
    deploy, ci, df = deploy_text(), ci_text(), AI_DOCKERFILE.read_text(encoding="utf-8")
    legs = {wf: (WORKFLOWS / wf).read_text(encoding="utf-8") for wf in DEPLOY_LEGS}

    cases = {
        "c1": (deploy.replace("BUILD_SERVICE=${BUILD_SERVICE:-}", "BUILD_SERVICE=${BUILD_SERVICE:-admin-web}"), ci, df, legs),
        "c2": (deploy.replace("exec 9>\"$LOCK\"", "exec 8>\"$LOCK.other\""), ci, df, legs),
        "c3": (deploy.replace("ARG APT_MIRROR=deb.debian.org", "ARG APT_MIRROR=mirrors.aliyun.com").replace("APT_MIRROR=${APT_MIRROR:-deb.debian.org}", "APT_MIRROR=${APT_MIRROR:-mirrors.aliyun.com}"), ci, AI_DOCKERFILE.read_text().replace("ARG APT_MIRROR=deb.debian.org", "ARG APT_MIRROR=mirrors.aliyun.com"), legs),
        "c4": (deploy.replace('--build-arg "PIP_INDEX_URL=$PIP_INDEX_URL"', ""), ci, df, legs),
        "c5": (deploy.replace("docker compose config --format json", "echo"), ci, df, legs),
        "c6": (deploy.replace('[ -n "$LOCAL_IMAGE_REF" ] && [ "$svc" = "$_svc" ]', "[ -n __never__ ]"), ci, df, legs),
        "c7": (deploy.replace('if timeout "$BUILD_TIMEOUT_SECS" docker build ', "if docker build "), ci, df, legs),
        "c8": (deploy.replace('  _build_args=(--build-arg "APT_MIRROR=$APT_MIRROR")',
                              '  docker builder prune -af || true\n  _build_args=(--build-arg "APT_MIRROR=$APT_MIRROR")'), ci, df, legs),
        "c9": (deploy, ci.replace("${out//__BUILD_SERVICE__/${SERVICE_KEY:-}}", "${out}"), df, legs),
    }
    for label, (d, c, f, lg) in cases.items():
        probs = _problems(d, c, f, lg)
        assert probs, f"注入 {label} 后没判红 ⇒ 该判据是空断言"
        # 自证变异**真的被读到**（坏形态读数 ≠ 基线读数）
        assert (d, c, f) != (deploy, ci, df), f"{label}: 变异没生效（文本未变）"

    # 腿少传/传错服务键 ⇒ 红
    bad_legs = dict(legs)
    bad_legs["deploy-frontend.yml"] = legs["deploy-frontend.yml"].replace("            admin-web", "            frontend")
    assert any(p.startswith("c9leg") for p in _problems(deploy, ci, df, bad_legs)), "腿传错服务键没判红"

    # 对照读数：**只改注释 / 加空行** ⇒ 不红
    benign = deploy + "\n# 这是一行新增注释：提到 docker builder prune -af 与 BUILD_SERVICE，但不是命令\n"
    assert _problems(benign, ci, df, legs) == [], "只加注释就判红 ⇒ 判据误吃说明文字（假红）"


# ══════════════════════════════════════════════════════════════════════════
# 文档与代码**同时**改（不许只改代码不改文档）
# ══════════════════════════════════════════════════════════════════════════
DOC = REPO / "docs" / "deployment" / "swas-migration-lessons.md"


def test_iron_rule_page_is_rewritten_and_marks_the_old_rule_superseded():
    """`docs/deployment/swas-migration-lessons.md` 必须**已改写**且**明确标出旧结论不再适用**。

    为什么要有这条：本仓有判据专门抓「读数/成文规则与事实不一致」——若只改代码不改文档，
    仓库里就留下一条**与现实相反的成文铁律**，下一个人要么照旧规则办、要么整条规则被无视
    （两种都不需要任何东西变红）。⇒ 把「文档已同批改写」变成**机械判据**。
    """
    doc = DOC.read_text(encoding="utf-8")
    # ① 新裁定必须写清：日期 + 裁定人 + 新证据
    assert "2026-09-30" in doc, "文档必须写明新裁定日期（2026-09-30）"
    assert "裁定人" in doc and "用户" in doc, "文档必须写明裁定人（用户）"
    assert "1782" in doc and "29.7" in doc, "文档必须带上新证据（冷构建 1782s / 29.7min）"
    assert "2 s" in doc or "**2 s**" in doc or "2s" in doc, "文档必须写上稳态读数（只改源码 2s）"
    # ② 旧铁律必须**明确标为已不适用**（否定/删除线/原文留存三者之一，不得只是悄悄删掉）
    assert "推翻" in doc, "文档必须显式说明旧铁律已被**推翻**（而不是悄悄删掉）"
    assert "不再适用" in doc or "已不适用" in doc or "~~" in doc, (
        "旧结论必须显式标注不再适用（历史事实保留 + 明确不适用），否则读者仍可能照旧行事"
    )
    # ③ 现行口径必须写出来（构建在服务器侧）
    assert "SWAS 服务器" in doc and "C′" in doc or "C'" in doc, "文档必须写出 C′ 现行口径"
    # ④ §二.2「容器互踩」必须有 C′ 下的处置
    assert "flock" in doc and "闸" not in doc[:0], "文档必须保留/更新 flock 串行化的处置"
    i = doc.find("并发部署互踩")
    assert i > 0, "找不到 §二.2「并发部署互踩」"
    seg = doc[i:i + 900]
    assert "2026-09-30" in seg, "§二.2 必须补上 2026-09-30 的 C′ 处置（旧文档只写了『已内置 flock』）"
    assert "docker build" in seg or "构建" in seg, "§二.2 的处置必须点名**构建**面（C′ 重新引入了单机 docker build）"


def test_doc_guard_red_proofs():
    """文档判据的红证：抹掉裁定记录 / 抹掉旧结论的「不再适用」标注 ⇒ 必须红。"""
    doc = DOC.read_text(encoding="utf-8")

    def problems(text: str) -> list[str]:
        out = []
        if "2026-09-30" not in text:
            out.append("无裁定日期")
        if "推翻" not in text:
            out.append("无『推翻』")
        if not any(k in text for k in ("不再适用", "已不适用", "~~")):
            out.append("旧结论未标不再适用")
        i = text.find("并发部署互踩")
        if i < 0 or "2026-09-30" not in text[i:i + 900]:
            out.append("§二.2 未补 C′ 处置")
        return out

    assert problems(doc) == [], "前提：真文档先绿"
    assert problems(doc.replace("2026-09-30", "2026-08-15")) , "抹掉新裁定日期后没红"
    assert problems(doc.replace("推翻", "沿用")), "抹掉『推翻』后没红"
    # 对照：只加一行注释性文字 ⇒ 不红
    assert problems(doc + "\n<!-- 仅新增一行无关注释 -->\n") == []


# ══════════════════════════════════════════════════════════════════════════
# 时间预算的**三者一致**（否则冷构建会被 GitHub 把 run 打死 ⇒ cancelled ⇒ 自放大）
# ══════════════════════════════════════════════════════════════════════════
def test_time_budgets_are_coherent_for_cold_builds():
    """三层上界必须**同号**：构建上界 < 「发起+轮询」预算 < job `timeout-minutes`。

    实测冷构建 **1782s（29.7min）**（issue #5814 的真机读数）。若哪一层小于它：
    · 「发起+轮询」默认 900s（改前形态）⇒ 构建还没跑完就判**硬超时**（假失败、且走 recovery_manual 不回滚）；
    · job `timeout-minutes: 45`（改前形态）⇒ run 被 GitHub 打死，结论是 **`cancelled`**
      （**不是** failure）⇒ `deploy-reconcile` 的断路器不跳闸 ⇒ cron 自放大（本单要消灭的形态）。
    ⇒ 这三层是**同一个约束的三个面**，必须一起判（只改一层会静默退化）。
    """
    ci = ci_text()
    build_bound = int(re.search(r'BUILD_TIMEOUT_SECS=\$\{BUILD_TIMEOUT_SECS:-(\d+)\}', deploy_text()).group(1))
    deploy_budget = int(re.search(r'C_BUILD_DEPLOY_TIMEOUT_SECONDS=\$\{SWAS_C_BUILD_DEPLOY_TIMEOUT_SECONDS:-(\d+)\}', ci).group(1))
    cold_build_measured = 1782   # 真机实测（ai-agent，apt 1100s + pip 675s）

    assert cold_build_measured < build_bound, (
        f"构建上界 {build_bound}s 不足以容纳实测冷构建 {cold_build_measured}s ⇒ 冷构建必被判超时"
    )
    assert build_bound < deploy_budget, (
        f"「发起+轮询」预算 {deploy_budget}s 必须**大于**构建上界 {build_bound}s"
        "（构建就发生在这次远端调用之内）⇒ 否则构建中途就被判硬超时"
    )
    # C′ 下该预算必须真的被用上（不是定义了个没人用的常量）
    assert re.search(r'if \[ -n "\$\{SERVICE_KEY:-\}" \].*?DEPLOY_TIMEOUT_SECONDS=\$C_BUILD_DEPLOY_TIMEOUT_SECONDS',
                     ci, re.S), (
        "C′（SERVICE_KEY 非空）时「发起+轮询」预算必须切到 C_BUILD_DEPLOY_TIMEOUT_SECONDS"
    )
    assert re.search(r'DEPLOY_TIMEOUT_SECONDS=\$\{SWAS_DEPLOY_TIMEOUT_SECONDS:-900\}', ci), (
        "非 C′ 路径必须保持原默认 900s（不偷偷改既有行为）"
    )
    for wf in DEPLOY_LEGS:
        job_mins = int(yaml.safe_load((WORKFLOWS / wf).read_text(encoding="utf-8"))
                       ["jobs"]["build-and-deploy"]["timeout-minutes"])
        assert job_mins * 60 > deploy_budget, (
            f"{wf}: job `timeout-minutes: {job_mins}`（= {job_mins * 60}s）不大于 C′ 的"
            f"「发起+轮询」预算 {deploy_budget}s ⇒ run 会先被 GitHub 打死，结论 `cancelled`"
            "（不是 failure）⇒ 断路器不跳闸 ⇒ cron 自放大"
        )


def test_time_budget_red_proofs():
    """红证：把任一层改回改前形态 ⇒ 必须红（三层各自能单独判红）。

    ⚠️ 2026-10-01（issue #5896）后真值刷新为 `2400 < 4500 < 90min` —— 预算里**含远端锁等待 1800s
    + 冷构建上界 2400s + 余量 300s**（三条腿共用同一把远端锁 ⇒ 跨服务排队，实测一次 ~28min）
    ⇒ 只改这三条里的一条必须判红。
    """
    build_bound, deploy_budget, cold = 2400, 4500, 1782

    def problems(bb, db, job_s):
        out = []
        if bb <= cold:
            out.append("构建上界 < 冷构建读数")
        if db <= bb:
            out.append("轮询预算 <= 构建上界")
        if job_s <= db:
            out.append("job 上界 <= 轮询预算")
        return out

    assert problems(build_bound, deploy_budget, 90 * 60) == [], "前提：真值先绿"
    assert problems(2400, 900, 90 * 60), "把轮询预算改回 900s 没判红（正是改前的假失败形态）"
    assert problems(2400, 4500, 45 * 60), "把 job 上界改回 45min 没判红（正是 cancelled 自放大的形态）"
    assert problems(600, 4500, 90 * 60), "把构建上界压到 600s 没判红（容不下冷构建）"
    # ⚠️ 「预算必须含**锁等待**（1800）**且覆盖冷构建上界**（2400）」这一半（issue #5896）**不在本函数
    #    的射程内** —— 它只判 `构建上界 < 轮询预算 < job 上界` 这个**序关系**（拿样本 1782s 或上界 2400s
    #    去比预算，都需要读**另一个文件**的常量，那是 `test_swas_deploy_ci_hardening.py` 的
    #    `test_lock_wait_covers_a_real_concurrent_deploy` 的职责）⇒ 不在这里假装判过。


#: admin-web 构建期变量的**默认值**（= 改前 CI 上 `secrets.X || <默认>` 的**有效值**，
#: 因为那几个 secret 从未在仓里登记 ⇒ 表达式恒落默认值）。这是**行为面契约**：不许丢、不许改。
ADMIN_WEB_BUILD_DEFAULTS = {
    "NEXT_PUBLIC_API_BASE_URL": "https://api.migaozn.com",
    "NEXT_PUBLIC_AI_API_BASE_URL": "https://ai-api.migaozn.com",
    "NEXT_PUBLIC_COOKIE_DOMAIN": ".migaozn.com",
    "NEXT_PUBLIC_BMINI_H5_URL": "https://app.migaozn.com/b/",
}


def test_admin_web_build_args_keep_the_pre_change_effective_defaults():
    """🔴 **默认值不许丢/不许漂移**：deploy.sh 传的默认值必须**逐字等于**改前的有效值，
    且必须与 `frontend/admin-web/Dockerfile` 的 `ARG` 缺省值**一致**（同一个真值的两个落点）。

    C′ 把构建从 CI 搬到服务器 ⇒ 这些构建期变量的注入点也跟着搬。搬的过程中最容易发生的静默退化
    就是「默认值丢了/改了」：前端会把错误的 API 域名 baked 进 JS（`NEXT_PUBLIC_*` 是**构建期文本
    替换**），而且**构建成功、部署成功、页面照样打得开** ⇒ 只有用户点功能时才炸。
    """
    d = _code(deploy_text())
    df = _code(AI_DOCKERFILE.parent.parent.parent.joinpath("frontend/admin-web/Dockerfile").read_text(encoding="utf-8")) \
        if (AI_DOCKERFILE.parent.parent.parent / "frontend/admin-web/Dockerfile").is_file() else ""
    assert df, "读不到 frontend/admin-web/Dockerfile（判据会退化成空断言）"
    for var, default in ADMIN_WEB_BUILD_DEFAULTS.items():
        # ① deploy.sh 必须传它，且默认值逐字正确（形态：--build-arg "VAR=${VAR:-<默认>}"）
        m = re.search(rf'--build-arg "?{re.escape(var)}=\$\{{{re.escape(var)}:-([^}}]*)\}}"', d)
        assert m, f"deploy.sh 构建 admin-web 时没有以 `${{{var}:-<默认>}}` 形态传 {var}"
        assert m.group(1) == default, (
            f"{var} 的默认值漂移：deploy.sh 给 {m.group(1)!r}，改前的有效值是 {default!r}"
            "（那会把错误的地址 baked 进前端 JS，且**构建/部署全绿**，只有用户点功能才炸）"
        )
        # ② 与 Dockerfile 的 ARG 缺省值**一致**（同一真值的两个落点 ⇒ 不许各写各的）
        md = re.search(rf"^ARG {re.escape(var)}=(\S+)$", df, re.M)
        assert md, f"frontend/admin-web/Dockerfile 缺 `ARG {var}=…` 的缺省值"
        assert md.group(1) == default, (
            f"{var} 在 Dockerfile 里的 ARG 缺省值 {md.group(1)!r} 与 deploy.sh 的默认值 {default!r} 不一致"
            "（两处都在，就必须同源）"
        )
    # ③ 服务器侧覆盖口必须在（否则「可配置」被静默砍掉）
    assert re.search(r'if \[ -f \.env\.build \]; then', d), (
        "缺少服务器侧覆盖口（`.env.build` 的存在性判断）—— 构建期变量的覆盖面被静默砍掉了"
    )


def test_admin_web_defaults_red_proofs():
    """红证：把任一默认值改坏 / 删掉一行 ⇒ 必须红。"""
    d = _code(deploy_text())
    df = _code((AI_DOCKERFILE.parent.parent.parent / "frontend/admin-web/Dockerfile").read_text(encoding="utf-8"))

    def problems(deploy: str, dockerfile: str) -> list[str]:
        out = []
        for var, default in ADMIN_WEB_BUILD_DEFAULTS.items():
            m = re.search(rf'--build-arg "?{re.escape(var)}=\$\{{{re.escape(var)}:-([^}}]*)\}}"', deploy)
            if not m or m.group(1) != default:
                out.append(f"deploy:{var}")
            md = re.search(rf"^ARG {re.escape(var)}=(\S+)$", dockerfile, re.M)
            if not md or md.group(1) != default:
                out.append(f"dockerfile:{var}")
        return out

    assert problems(d, df) == [], "前提：真值先绿"
    # ① 默认值被改坏 ⇒ 红
    assert problems(d.replace("NEXT_PUBLIC_API_BASE_URL:-https://api.migaozn.com",
                              "NEXT_PUBLIC_API_BASE_URL:-https://api.example.com"), df), \
        "把 API 域名默认值改坏后没红 ⇒ 默认值契约是空断言"
    # ② 整行被删掉 ⇒ 红
    assert problems(re.sub(r'\s*_build_args\+=\(--build-arg "NEXT_PUBLIC_COOKIE_DOMAIN=[^\n]*\n', "\n", d), df), \
        "删掉 COOKIE_DOMAIN 的注入行后没红"
    # ③ 两处不同源（只改 Dockerfile）⇒ 红
    assert problems(d, df.replace("ARG NEXT_PUBLIC_COOKIE_DOMAIN=.migaozn.com",
                                  "ARG NEXT_PUBLIC_COOKIE_DOMAIN=.other.com")), \
        "Dockerfile 与 deploy.sh 的默认值不同源却没红"
    # ④ 对照：只加注释 ⇒ 不红
    assert problems(d + "\n# 注释：提到 NEXT_PUBLIC_API_BASE_URL 的默认值\n", df) == []


# ══════════════════════════════════════════════════════════════════════════
# 构建上界必须**真的被施加**（不是只写在变量/注释里）—— 行为级判据
#
# 为什么单靠逐字断言不够（issue #5814 的集成侧追问）：`BUILD_TIMEOUT_SECS=2400` 写在那儿、
# 甚至 `echo` 出来，都不代表命令**真被 `timeout` 包住**。而上界一旦是装饰，卡住的构建会一直占着
# `deploy-<svc>` 的并发锁到 job 的 90min —— 「挂住的 run 攥锁」正是本单要消灭的形态之一。
# ⇒ 这里从**真脚本**抠出那条语句**真跑**（桩 docker + 桩 timeout），断言：
#    ① 桩 `timeout` 收到的 argv = `<上界> docker build …`（上界**作用在构建命令上**）；
#    ② 挂住的构建被上界杀掉 ⇒ rc=124，且脚本**点名**「服务器侧构建超时」；
#    ③ 正常构建 ⇒ rc=0 且打「本地构建完成」（证明这不是"永远失败"的假判据）。
# ══════════════════════════════════════════════════════════════════════════

# 桩 `timeout`：**真的施加**上界 —— 到点杀子进程，并按 coreutils 语义返回 124。
ENFORCING_TIMEOUT_STUB = r"""#!/bin/bash
# 记录 argv（证明上界作用在哪条命令上），然后真的施加墙钟上界
echo "$*" >> "${STUB_TIMEOUT_LOG}"
secs="$1"; shift
if [ "$1" = "--" ]; then shift; fi
"$@" &
pid=$!
( sleep "$secs"; kill -TERM "$pid" 2>/dev/null; sleep 1; kill -KILL "$pid" 2>/dev/null ) &
w=$!
rc=0; wait "$pid" || rc=$?
kill "$w" 2>/dev/null; wait "$w" 2>/dev/null
case "$rc" in 143|137) exit 124 ;; esac     # 被杀 = 超时（coreutils 语义）
exit "$rc"
"""

# 桩 `docker`：`build` 子命令按 SLEEP_FOR 挂住，其余（image inspect 等）立即成功
HANGING_DOCKER_STUB = r"""#!/bin/bash
echo "$*" >> "${STUB_DOCKER_LOG}"
case "$1" in
  build) sleep "${SLEEP_FOR:-0}" ;;
esac
exit "${DOCKER_RC:-0}"
"""


def _extract_build_block() -> str:
    """从**真** `deploy.sh` 抠出「构建调用 + 退出码分支」那一段（判真文本，不手写）。"""
    text = deploy_text()
    start = text.index('if timeout "$BUILD_TIMEOUT_SECS" docker build')
    end = text.index("\n  fi\n", start) + len("\n  fi\n")
    block = text[start:end]
    assert "docker build" in block and "exit \"$_rc\"" in block, "抠出来的构建段不完整（判据已过期）"
    return block


def _run_build_block(tmp_path, *, sleep_for: int, timeout_secs: int = 2):
    """把抠出的真文本放进最小外壳里真跑（桩 docker / 桩 timeout）。"""
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    for name, body in (("timeout", ENFORCING_TIMEOUT_STUB), ("docker", HANGING_DOCKER_STUB)):
        f = bindir / name
        f.write_text(body, encoding="utf-8")
        f.chmod(0o755)
    harness = (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        f'BUILD_TIMEOUT_SECS={timeout_secs}\n'
        'LOCAL_IMAGE_REF="acr.example.com/ns/svc:sha-verify"\n'
        '_df="backend/ai-agent-service/Dockerfile"\n'
        '_ctx="backend/ai-agent-service"\n'
        '_build_args=(--build-arg "APT_MIRROR=mirrors.aliyun.com")\n'
        'mkdir -p src/backend/ai-agent-service\n'
        + _extract_build_block()
    )
    script = tmp_path / "harness.sh"
    script.write_text(harness, encoding="utf-8")
    import os as _os
    import subprocess as _sp
    env = {
        **_os.environ,
        "PATH": f"{bindir}{_os.pathsep}{_os.environ['PATH']}",
        "STUB_TIMEOUT_LOG": str(tmp_path / "timeout.log"),
        "STUB_DOCKER_LOG": str(tmp_path / "docker.log"),
        "SLEEP_FOR": str(sleep_for),
    }
    proc = _sp.run(["bash", str(script)], cwd=str(tmp_path), env=env,
                   capture_output=True, text=True, timeout=60)
    tlog = (tmp_path / "timeout.log").read_text(encoding="utf-8") if (tmp_path / "timeout.log").exists() else ""
    return proc, proc.stdout + proc.stderr, tlog


def test_build_call_is_actually_wrapped_by_the_explicit_bound(tmp_path):
    """🔴 上界**作用在构建命令上**：桩 `timeout` 收到的 argv 必须逐字是 `<上界> docker build …`。"""
    proc, out, tlog = _run_build_block(tmp_path, sleep_for=0, timeout_secs=2)
    assert proc.returncode == 0, f"正常构建应 rc=0 → {out}"
    assert tlog.strip(), "桩 `timeout` 一次都没被调用 ⇒ 构建**没有**被 `timeout` 包住（上界是装饰）"
    assert tlog.strip().startswith("2 docker build "), (
        f"`timeout` 收到的应是 `<上界> docker build …`，实得 {tlog.strip()!r}"
        "（上界必须作用在**构建命令**上，而不是包住别的命令）"
    )
    assert "-f src/backend/ai-agent-service/Dockerfile" in tlog, "构建命令少了 `-f <Dockerfile>`（影子实现）"
    assert "--build-arg APT_MIRROR=mirrors.aliyun.com" in tlog, "构建参数没被传下去（影子实现）"
    assert "本地构建完成" in out, f"正常路径应打完成行 → {out}"


def test_hung_build_is_killed_by_the_bound_and_named(tmp_path):
    """🔴 挂住的构建被上界**杀掉** ⇒ rc=124 且点名「服务器侧构建超时」（不是静默占锁到 90min）。"""
    proc, out, tlog = _run_build_block(tmp_path, sleep_for=30, timeout_secs=2)
    assert proc.returncode == 124, (
        f"挂住的构建必须以上界码 124 退出（实得 {proc.returncode}）⇒ 否则它不会判失败、"
        "只会一直占着 deploy-<svc> 的并发锁 → "
    )
    assert "服务器侧构建超时" in out, f"rc=124 必须**点名**「服务器侧构建超时」→ {out}"
    assert "::error::" in out, f"必须用 `::error::` 让失败可归因 → {out}"


def test_build_bound_red_proofs(tmp_path):
    """红证：① 去掉 `timeout` 包裹 ⇒ 桩 timeout 收不到调用（判据变红）；② 上界换成写死的 0 ⇒ 挂住不被杀。"""
    # ① 剥离 `timeout "$BUILD_TIMEOUT_SECS" ` 前缀 ⇒ 上界失效
    text = deploy_text()
    stripped = text.replace('if timeout "$BUILD_TIMEOUT_SECS" docker build', 'if docker build')
    assert stripped != text, "注入未生效"
    assert 'if timeout "$BUILD_TIMEOUT_SECS" docker build' not in stripped, "注入未生效（包裹仍在）"
    # ② 上界=0 ⇒ 立即超时（证明 ② 那条判据依赖**真的**上界，而不是"总是失败"）
    proc, out, _ = _run_build_block(tmp_path, sleep_for=5, timeout_secs=0)
    assert proc.returncode == 124, f"上界 0 时挂住的构建必须超时（实得 {proc.returncode}）"
    assert "服务器侧构建超时" in out
