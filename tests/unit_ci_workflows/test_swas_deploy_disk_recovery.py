# case_ids: MC-087
"""部署链路「磁盘水位 × 回收」联动 + 构建后回收信号 + 被闸门挡住时的**收口归因**守卫（#6508 / #6505 / #6512）。

## 两条病（2026-10-07 真机实测，逐字读数）

**① 恢复出口在本机是空操作**（issue #6508）：运维提示写「构建缓存：`docker builder prune --filter until=168h`」，
而 `docker system df -v` 里缓存条目**全是 3 天前（72h）建的** ⇒ `until=168h` 匹配 **0 条**、`Total: 0B`
（实测：同一时刻 `until=48h` 解出 **6.745GB**）⇒ **照着提示敲解决不了问题**。
且 Build Cache **完全不在保留策略里**：Build Cache 12.44GB / 184 条 / 100% RECLAIMABLE，只增不减，
是磁盘单调爬升的主因；部署日志里那一格逐字是 `构建缓存：?`（**读数为空**）。

**② 被前置闸门挡住时收口文案误导**（issue #6505）：同一次 run 里，
远端说「构建前磁盘可用：4045MB < 门槛 4096MB ⇒ **中止构建**（旧容器保持不动、环境未受影响）」，
CI 收口却说「部署失败，**且自动回滚（tag=sha-e0e3bdf）也失败** ⇒ 环境可能处于坏状态，请**立即人工介入**」。
实际状态 = **构建根本没开始、正在跑的服务一动没动**；而「回滚也失败」与主部署**是同一道闸门**
（4045MB / 4046MB 都 < 4096MB），**不是第二次独立故障** ⇒ 排查方向被带偏（去救火 vs 去回收磁盘）。

**③ 构建后「回收量为 0」的假警 + 回收量口径错**（issue #6512，真机 run `37634071278` 逐字）：
那次部署**磁盘是健康的**（构建前可用 10059MB ≫ 门槛 4096MB），按 `pick_cache_window` 选 72h 档，
而这台机器上的缓存层都是几十分钟内建的 ⇒ 匹配 **0 条** ⇒ 回收量 0 **是预期结果、不是异常**；
脚本却**无条件**打 `::warning::缓存回收量为 0…需人工核对` ⇒ **每次健康部署一条黄标**
（告警疲劳 —— `migao-acceptance`「部分闭环」节的「永久噪音让真失败与噪音同形」，亦 #6505 同族）。
且回收量的**口径**错：用 **Δ(整盘已用)** 当回收量，把**构建自身写盘**混进来 ⇒「prune 腾 2GB +
构建写 2GB」读数 = 0；正确的量就在隔壁那行：**缓存占用差**（`构建缓存：X → Y`）。

## 本文件锁什么（每条判据都能单独变红；红证分散在 §二 注入 / §三·§四·§四之二 真跑 / §五）

| # | 判据 | 变红的形态 |
|---|---|---|
| 1 | 缓存**读数**在部署日志里，且**不许是 `?`**（读数真的打印，且缓存占字节可算） | 去掉读数 / 让 `docker system df` 失败仍报 `?` ⇒ 红 |
| 2 | 回收**按磁盘水位选窗口**（阶梯），并实现「清到阈值以上为止」 | 回到固定 `until=168h`（真机上 `Total: 0B` 的空操作）⇒ 红 |
| 3 | 缓存回收**只碰构建缓存**：清理段不许出现删镜像的命令 | 在缓存回收段里写 `docker image rm/rmi/prune` ⇒ 红（可能误删回滚点） |
| 4 | 清理段**不许出现 `$LAST_GOOD_FILE` / `rollback_tag` / `.last-good-tag`** ⇒ 结构上碰不到保留集 | 把那三个引用写进缓存段 ⇒ 红 |
| 5 | 闸门中止 ⇒ 远端打**机读标记** `ABORT_REASON=BUILD_MIN_FREE_MB`（与 `EFFECTIVE_TAG=` 同族） | 删掉标记 ⇒ 红 |
| 6 | 闸门中止**不许动环境**：不 build / 不 pull / 不 up / 不 rm 镜像 | 中止前先 pull 一次 ⇒ 红 |
| 7 | 构建后仍不足门槛 ⇒ **出口可选**（真跑阶梯，逐条可复算），且 `-af` 只在**恢复出口**里 | 出口又变成「再敲一遍 168h」⇒ 红 |
| 8 | `BUILD_MIN_FREE_MB` 的 **fail-closed 一字未改**：余量不足 ⇒ 仍**中止构建**、旧容器不动 | 改成「继续部署」⇒ 红 |
| 9 | CI 收口**按标记分支**：被前置闸门挡住 ⇒ 「未开始部署 / 环境未受影响」**且不出现**「环境可能处于坏状态」 | 只按 `exit != 0` 收口（= 改前形态）⇒ 红 |
| 10 | 回滚腿被**同一闸门**挡住 ⇒ 不得计入「环境可能坏」的证据 | 把它报成「回滚也失败 ⇒ 环境可能坏」⇒ 红 |
| 11 | 中途失败（无标记）⇒ 仍说「环境可能处于坏状态，请人工介入」（**双向对照**，防文案恒打印） | 把中途失败也说成「未开始部署」⇒ 红 |
| 12 | 构建后「回收量为 0」的告警**由水位守卫**（水位充裕 ⇒ 只打信息行「…属预期」） | 无条件告警（= #6512 ① 的改前形态）⇒ 红 |
| 13 | 回收量**口径 = 缓存占用差**（`cache_before − cache_after`；Δ已用只作参照） | 用 Δ整盘已用 ⇒「prune 腾 2GB + 构建写 2GB」读数 0 ⇒ 红（#6512 ②） |
| 14 | **类级**：构建段里**每一条** `::warning::` 都必须由门槛/水位（`_need_mb`）守卫 | 与「是否真需要回收」无关的告警 ⇒ 红（#6512 / #6505 同族） |

## 判定方式（零网络、零真机、零删除）

- **静态面**：只读仓内文本（`deploy/swas/deploy.sh` · `deploy/scripts/swas-deploy-ci.sh`），任何时刻同一读数；
- **执行面**：桩 `df` / `docker`（含 `system df` 的缓存读数）/ `curl` / `flock` / `timeout`，
  在 `tmp_path` 里跑**真实** `deploy.sh` 的**真实码路**；桩 `aliyun` 跑**真实** `swas-deploy-ci.sh`。
  全程**不联网、不碰真机、不删任何东西**（缓存读数与释放量都是可注入的假值 —— §28.1 出口①）。
- 判据**不读 `origin/main`**（CI 的 pr-check 是 `fetch-depth: 1`；先例见 test_swas_server_side_build.py）。

## 未固化 / 边界（照实登记，§19.1）

- 本判据证明的是「脚本在给定输入下会做什么」，**不是**「真机上 `docker builder prune` 真的解出 N GB」
  —— 后者只能真跑一次（issue #6508 给了复算命令）。
- 「清到阈值以上为止」的**阶梯档位**（`until=168h/72h/48h/24h/6h` → `-af` 兜底）是**人可读的取舍**，
  判据只钉住「按可用 MB 单调变紧 + 必到 `-af` 兜底 + 只碰构建缓存」，不钉具体档位的数值。
- 判不了「`-af` 兜底后稳态是否退化」：那是运行期读数（改源码 2s vs 冷构建 29.7min），静态判据看不见。
"""
from __future__ import annotations

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
CI_SH = REPO_ROOT / "deploy" / "scripts" / "swas-deploy-ci.sh"

PROJECT = "crpi-qdcgkzwx9p9zckga.cn-hangzhou.personal.cr.aliyuncs.com/ai-customer-service"
SERVICES = ("admin-api", "ai-agent", "admin-web")
FOREIGN_IMAGE = "nginx:alpine"

#: 闸门标记：与 `EFFECTIVE_TAG=` 同族的机读标记（issue #6505 建议的形态）
ABORT_REASON = "BUILD_MIN_FREE_MB"
#: 候选窗口阶梯的上界（7 天）：它同时也是**正常构建路径**的后回收窗口
DEFAULT_WINDOW_HOURS = 168

#: issue #6512 ① 的**逐字锚点**：改前形态 = 无条件打印的假警（水位充裕也发）
RECLAIM_ZERO_WARNING = "::warning::缓存回收量为 0"


# ══════════════════════════════════════════════════════════════════════════
# 读源 + 反空跑锚点
# ══════════════════════════════════════════════════════════════════════════

def read_deploy() -> str:
    assert DEPLOY_SH.is_file(), f"反空跑锚点：目标脚本不存在 → {DEPLOY_SH}"
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert "BUILD_SERVICE" in text, "反空跑锚点：deploy.sh 里找不到 BUILD_SERVICE（判据已过期）"
    return text


def read_ci() -> str:
    assert CI_SH.is_file(), f"反空跑锚点：目标脚本不存在 → {CI_SH}"
    text = CI_SH.read_text(encoding="utf-8")
    assert "capture_remote_log" in text, "反空跑锚点：swas-deploy-ci.sh 里找不到 capture_remote_log"
    return text


def _strip_comment(line: str) -> str:
    """剥掉行尾注释（引号内的 `#` 不算注释起点 —— 同 test_swas_server_side_build.py 的单遍扫描）。"""
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


def code(text: str) -> str:
    """剥注释后的全文（**行内**口径）—— 判据只吃**命令**，不吃说明文字。

    ⚠️ 已知边界（照实登记）：本口径按**行**判注释起点 ⇒ 跨行的单引号（CI 脚本里的 `say '…'`）
    会被当成未闭合引号、把后续行一起吃进「字符串里」。⇒ **CI 面的判据一律吃原文**；
    需要剥注释的脚本面（deploy.sh）用 `code_lines`（整行 `#` 口径）。
    """
    return "\n".join(_strip_comment(ln) for ln in text.splitlines())


def code_lines(text: str) -> str:
    """**整行**注释口径（只丢 `#` 起首的行）：不受跨行引号影响 ⇒ 用于 deploy.sh 的分支切段。"""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def deploy_code() -> str:
    return code(read_deploy())


def ci_code() -> str:
    return code(read_ci())


def function_body(text: str, name: str) -> str:
    """取 shell 函数体（`name() {` 的**内容**，不含收尾的 `}` 行）。取不到 ⇒ 显式失败（不是「通过」）。

    ⚠️ **收尾的 `}` 必须切掉**：首版把 `\n}` 一起留下 ⇒ 拼进外壳后多出一个 `}`，
    `bash -n` 照样过（`}` 单独一行是合法的空命令）但**函数根本没定义** ⇒ 判据静默退化
    （实测：`pick_cache_window` 恒返回空串，看上去像「窗口没随水位变紧」）。
    ⇒ 两种形态都收敛成同一个收尾切口：`\n}`（顶格）与 `\n  }`（缩进）。
    """
    # ⚠️ 用**配对花括号**口径（不用「找下一个顶格 `}`」）：单行定义（`f() { …; }`）与多行定义都要认，
    #    否则注入成单行的夹具会让 `function_body` 抛锚点异常（实测：判据以「判据已过期」而非「行为变了」收场）。
    m = re.search(rf"^{re.escape(name)}\(\) \{{", text, re.M)
    assert m, f"反空跑锚点：找不到函数 `{name}()` —— 判据已过期或脚本被改写"
    depth, i, n = 0, m.end() - 1, len(text)
    start = m.end()
    while i < n:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                body = text[start:i]
                assert body.strip(), f"函数 `{name}()` 的函数体为空（判据已过期）"
                return body
        i += 1
    raise AssertionError(f"函数 `{name}()` 的花括号没有配对（脚本语法已坏）")


def cache_section(text: str) -> str:
    """缓存回收的**落码面**：`builder_cache_recover()` 函数体 + `builder_cache_measure()` 函数体。"""
    return function_body(text, "builder_cache_recover") + "\n" + function_body(text, "builder_cache_measure")


def _inject(text: str, old: str, new: str) -> str:
    """替换注入；**没替换到 ⇒ 显式失败**（否则「注入式红证」是空跑）。"""
    assert old in text, f"注入锚点不存在（判据已过期）：{old[:70]!r}"
    out = text.replace(old, new, 1)
    assert out != text, "注入没有改变文本（空跑）"
    return out


# ══════════════════════════════════════════════════════════════════════════
# 判据本体（纯函数：文本进 → 违规清单出；注入式红证驱动**同一份本体**）
#
# ⚠️ 设计纪律（本文件踩过的坑，写在这里省得下一个人再踩）：
#   · **CI 面一律吃原文**：收口文案是 `say '…'` 的多行单引号 ⇒ 任何行内剥注释器都会把它当
#     未闭合引号吃掉（实测：`未开始部署` / `同一闸门` 剥完一个字不剩 ⇒ 假红）。
#   · **deploy.sh 面用 `code_lines`（整行 `#` 口径）**：既有说明文字里**故意**引用了被禁命令，
#     不剥会假红；行级口径不受跨行引号影响（`code()` 的行内口径会）。
#   · **锚点只用单行、稳定的串**（`echo "ABORT_REASON=…"` / `RECOVERY_ANCHOR=1` / `builder_cache_recover`），
#     不用「某行往后 N 字符」那种窗口（窗口会随排版漂移，实测锚到别的分支上）。

def problems_cache_readout(text: str) -> list:
    """判据 1：缓存读数必须**真的打进日志**，且**不许是 `?`**。"""
    v = []
    if "builder_cache_measure() {" not in text:
        v.append("找不到缓存读数函数 `builder_cache_measure()`（读数没有单一入口）")
    if "构建缓存" not in text:
        v.append("部署日志里没有「构建缓存」读数行")
    # 读数必须**算得出**（不是 `?:-` 兜底就完事）：必须有把 docker 的人类可读尺寸转成数的实现
    if not re.search(r"(B\|KB\|MB\|GB\|TB)|(\"KB\")|(\"GB\")", text):
        v.append("找不到尺寸→数值的解析（`docker system df` 报 `1.9GB` 这类人类可读串 ⇒ 不解析就是面包屑）")
    if "docker system df" not in text:
        v.append("找不到 `docker system df`（缓存读数的来源）")
    if "／构建缓存：${_cache_before_mb:-?} → ${_cache_after_mb:-?}" not in build_block(text):
        v.append("构建路径里没有「／构建缓存：<读数>」的打印行 ⇒ 读数没有接在真流程上（改前逐字是 `构建缓存：?`）")
    return v


def problems_ladder_links_to_waterline(text: str) -> list:
    """判据 2：回收窗口必须**按磁盘可用量选**（阶梯），并实现「清到阈值以上为止」。"""
    v = []
    if "builder_cache_recover() {" not in text:
        v.append("找不到 `builder_cache_recover()`（水位联动没有单一实现）")
    if "pick_cache_window() {" not in text:
        v.append("找不到 `pick_cache_window()`（窗口不是按水位选的）")
    src = code(text)
    win = function_body(text, "pick_cache_window") if "pick_cache_window() {" in src else ""
    if win:
        if len(re.findall(r"\$free\" -ge", win)) < 4:
            v.append(
                "`pick_cache_window` 没有拿磁盘可用量做**多处**分档比较（`\"$free\" -ge` 少于 4 处）"
                " ⇒ 阶梯退化成一个固定窗口（真机实测 `until=168h` 匹配 0 条 = 空操作）"
            )
    else:
        v.append("找不到 `pick_cache_window` 的函数体（判据已过期）")
    rec = function_body(text, "builder_cache_recover") if "builder_cache_recover() {" in src else ""
    if rec:
        # 「清到阈值以上为止」的两种合法形态：显式循环（while/for）**或** 逐档 + 每档之后重测。
        if not re.search(r"while|for ", rec) and len(re.findall(r"builder prune", rec)) < 2:
            v.append("`builder_cache_recover` 既没有循环、也没有多档递进 ⇒ 不是「清到阈值以上为止」")
        if "disk_free_mb" not in rec:
            v.append("`builder_cache_recover` 没有重测可用量 ⇒ 「到阈值为止」无从判定")
        if ' -lt "$want"' not in rec:
            v.append("`builder_cache_recover` 没有拿（重测后的）可用量与门槛比较 ⇒ 阶梯没有显式终止条件")
    else:
        v.append("找不到 `builder_cache_recover` 的函数体（判据已过期）")
    # 阶梯必须能降到最紧档（真机实测：168h 匹配 0 条 ⇒ 只有更短窗口/兜底档才解得开）
    if not re.search(r"builder prune (-af|--keep-storage)", src):
        v.append("阶梯里没有最紧档（真机实测 `until=168h` 是 `Total: 0B` ⇒ 没有兜底档就仍是空操作）")
    return v


def problems_only_build_cache_is_touched(text: str) -> list:
    """判据 3：缓存回收**只碰构建缓存**（清理段里不许出现任何删镜像的命令）。"""
    v = []
    if "builder_cache_recover() {" not in text:
        v.append("取不到缓存回收段的函数体（判据已过期）")
        return v
    sec = cache_section(text)
    for bad, why in (
        (r"docker\s+image\s+rm\b", "缓存段里出现 `docker image rm`（会删带 tag 的镜像）"),
        (r"docker\s+image\s+prune", "缓存段里出现 `docker image prune`（镜像清理不属于缓存回收）"),
        (r"docker\s+system\s+prune", "缓存段里出现 `docker system prune`（会连带删镜像/卷）"),
        (r"docker\s+rmi\b", "缓存段里出现 `docker rmi`（会删带 tag 的镜像）"),
        (r"docker\s+volume\s+rm", "缓存段里出现 `docker volume rm`（越权）"),
    ):
        if re.search(bad, sec):
            v.append(why)
    if "builder prune" not in sec:
        v.append("缓存段里没有 `builder prune`（判据锚点漂移）")
    return v


def problems_retention_set_untouched(text: str) -> list:
    """判据 4：缓存回收段**结构上碰不到保留集**（不许引用回滚点/保留集）。"""
    v = []
    if "builder_cache_recover() {" not in text:
        v.append("取不到缓存回收段的函数体（判据已过期）")
        return v
    sec = cache_section(text)
    for token, why in (
        ("LAST_GOOD_FILE", "缓存段引用了 `LAST_GOOD_FILE`（回滚点文件）"),
        ("rollback_tag", "缓存段引用了 `rollback_tag`（回滚点读取）"),
        (".last-good-tag", "缓存段引用了 `.last-good-tag`"),
        ("retained_tags", "缓存段引用了 `retained_tags`（保留集计算）"),
        ("cleanup_project_images", "缓存段调用了镜像清理 `cleanup_project_images`（越权）"),
    ):
        if token in sec:
            v.append(why)
    return v


def abort_slice(text: str) -> str:
    """闸门中止分支的**落码面**：从 `echo "ABORT_REASON=…"` 到该分支的 `exit 1`。

    ⚠️ 用 `code_lines`（整行 `#` 口径）：脚本里**多处**出现「中止」字样（构建上下文缺失 /
    compose 求值失败也各有一处）⇒ 「某行往后 N 字符」的窗口会锚到别的分支上（实测踩到）。
    """
    src = code_lines(text)
    k = src.find(f'echo "ABORT_REASON={ABORT_REASON}"')
    assert k > 0, f"反空跑锚点：找不到 `echo \"ABORT_REASON={ABORT_REASON}\"`（判据已过期）"
    # 🔴 起点必须是**分支守卫**（`if … -lt … _need_mb`），不是标记行本身：
    #    取标记行的话，「标记之前、分支之内」的语句（例如一个 pull）会落在切片外 ⇒ 判据看不见（实测）。
    guards = [mm.start() for mm in re.finditer(r'if \[ "\$\{?_df_mb:-0\}" -lt "\$\{?_need_mb" \]; then', src)]
    guards = [g for g in guards if g < k]
    assert guards, "反空跑锚点：中止分支没有守卫（`if … -lt … _need_mb`）—— 那本身就是 fail-closed 退化"
    i = guards[-1]
    j = src.find("exit 1", k)
    assert j > k, "反空跑锚点：中止分支没有收口 `exit 1`（判据已过期）"
    return src[i:j]


def problems_abort_marker(text: str) -> list:
    """判据 5：闸门中止必须打**机读标记**（与 `EFFECTIVE_TAG=` 同族）。"""
    v = []
    src = code_lines(text)
    if f"ABORT_REASON={ABORT_REASON}" not in src:
        v.append(f"闸门中止没有打机读标记 `ABORT_REASON={ABORT_REASON}`")
    if not re.search(r'^\s*echo "ABORT_REASON=', src, re.M):
        v.append("标记必须是**远端直接 echo** 出来的独立行（CI 按 `^ABORT_REASON=` 解析）")
    try:
        seg = abort_slice(text)
    except AssertionError as e:
        v.append(f"取不到中止分支：{e}")
        return v
    if "旧容器保持不动" not in seg:
        v.append("中止分支没有说清「旧容器保持不动」（环境状态读不到）")
    return v


def problems_abort_does_not_touch_env(text: str) -> list:
    """判据 6：闸门中止**不许动环境**（不 build / 不 pull / 不 up / 不删镜像）。

    🔴 只认**行首就是命令**的形态（`^\s*(timeout N )?docker …`）：出口说明里**故意**逐字写了
    `docker builder prune …`（教人怎么回收）⇒ 用 `docker\s+build` 这种松形态会把**说明文字**判红。
    """
    v = []
    try:
        seg = abort_slice(text)
    except AssertionError as e:
        v.append(f"取不到中止分支：{e}")
        return v
    for bad, why in (
        (r"^\s*(timeout\s+\S+\s+)?docker\s+build\b", "中止分支里执行了 `docker build`（应只中止，不构建）"),
        (r"^\s*docker\s+compose\s+pull\b", "中止分支里执行了 `docker compose pull`（动了镜像层）"),
        (r"^\s*docker\s+compose\s+up\b", "中止分支里执行了 `docker compose up`（动了容器）"),
        (r"^\s*docker\s+(image\s+rm|rmi)\b", "中止分支里删了镜像"),
    ):
        if re.search(bad, seg, re.M):
            v.append(why)
    return v


def precheck_block(text: str) -> str:
    """前置检查里的**带阈值恢复块**：`RECOVERY_ANCHOR=1` 那一块（含它外层守卫）。

    ⚠️ 锚点必须是**单行代码**串：`if [ "${_df_mb:-0}" -lt "$_need_mb" ]; then` 在多处出现，
    往后 N 字符的窗口会取到别处；`RECOVERY_ANCHOR=1` 是这一块**专属**且唯一。
    """
    src = code_lines(text)
    a = src.find("RECOVERY_ANCHOR=1")
    assert a > 0, "反空跑锚点：找不到前置检查恢复块的锚点（判据已过期）"
    i = src.rfind("if [", 0, a)
    assert i > 0, "反空跑锚点：恢复块没有守卫（判据已过期）"
    k = src.find("\n  fi", a)
    return src[i:k if k > a else i + 900]


def problems_aggressive_prune_only_in_recovery(text: str) -> list:
    """判据 7：`-af` 是**两档阶梯的第 2 档**，唯一落点是 `builder_cache_recover()`（受水位联动调用）。

    🔴 为什么用**行锚**（`CACHE_RECOVER_AF_CALL=1` / `RECOVER_TIER_1=1`）而不是比行内容：
    行内容比对在**夹具侧**（把函数体整段换掉再拼回）会因切法差异而假红（实测）；
    行锚是**逐字稳定**的，且「把 `-af` 挪到构建路径」时行锚**不会**跟着过去 ⇒ 注入必红。
    """
    v = []
    src = code_lines(text)
    if "builder_cache_recover() {" not in text:
        v.append("找不到水位联动函数 `builder_cache_recover()`（`-af` 没有受控的落点）")
        return v
    rec = code_lines(function_body(text, "builder_cache_recover"))
    for anchor, why in (
        ("RECOVER_TIER_1=1", "`-af` 前面没有第 1 档（按水位选的窗口）—— 阶梯没有落码"),
        ("RECOVER_TIER_2=1", "`-af` 没有第 2 档的档位标记（函数体内找不到 `RECOVER_TIER_2=1`）"),
        ("CACHE_RECOVER_AF_CALL=1", "`-af` 的调用点没有行锚（无法与说明文字区分）"),
    ):
        if anchor not in rec:
            v.append(f"`builder_cache_recover()` 里缺 `{anchor}`：{why}")
    if "docker builder prune -af" not in rec:
        v.append("函数体内找不到 `docker builder prune -af`（真机实测 `Total: 0B` 形态仍无兜底档）")
    # 🔴 无条件调用（每次部署都清光缓存）的形态 = `-af` 调用**出现在函数体之外**
    outside = src.count("CACHE_RECOVER_AF_CALL=1") - rec.count("CACHE_RECOVER_AF_CALL=1")
    if outside:
        v.append(f"`CACHE_RECOVER_AF_CALL` 有 {outside} 处落在 `builder_cache_recover()` **之外**（无条件清理）")
    return v


def problems_gate_fail_closed_kept(text: str) -> list:
    """判据 8：`BUILD_MIN_FREE_MB` 的 fail-closed **语义未改**（余量不足 ⇒ 仍中止构建）。"""
    v = []
    src = code_lines(text)
    if "BUILD_MIN_FREE_MB" not in src:
        v.append("找不到 `BUILD_MIN_FREE_MB`（门槛旋钮被删）")
    if "中止构建" not in src:
        v.append("找不到「中止构建」的 fail-closed 分支（不看环境就中止 = 换了另一种护栏）")
        return v
    if not re.search(r"if \[ \"\$\{?(_df_mb|_df_after_mb)[^\]]*\" -lt \"\$\{?_need_mb", src):
        v.append("中止判定不再由门槛（`_df_* -lt _need_mb`）驱动 ⇒ fail-closed 语义被改")
    # 恢复块（清缓存）之后**必须重新比一次门槛**，否则「清了就放行」= 悄悄取消护栏
    try:
        pc = precheck_block(text)
    except AssertionError as e:
        v.append(f"取不到恢复块：{e}")
        return v
    if not re.search(r'-lt "\$\{?_need_mb', pc):
        v.append("恢复块（清缓存）之后没有重新比门槛 ⇒ 「清完就放行」取消了 fail-closed 护栏")
    return v


# ── issue #6512：构建后「回收量为 0」的**假警**（①）与回收量的**口径**（②）────────────

def problems_reclaim_zero_warning_gated_by_waterline(text: str) -> list:
    """判据 12（issue #6512 ①）：回收量 0 的告警必须与**是否需要回收**绑定。

    现场（真机 run `37634071278`，结论 success）：构建前可用 10059MB ≫ 门槛 4096MB（**水位充裕**），
    按 `pick_cache_window` 选 72h 档，而本机缓存层都是几十分钟内建的 ⇒ 匹配 0 条 ⇒ 回收量 0
    **是预期**；改前却**无条件**打 `::warning::…需人工核对` ⇒ **每次健康部署一条黄标**
    （告警疲劳：「永久噪音让真失败与噪音同形」，与 #6505 同族）。
    """
    v = []
    src = code_lines(text)
    k = src.find(RECLAIM_ZERO_WARNING)
    if k < 0:
        v.append(f"找不到 `{RECLAIM_ZERO_WARNING}` 告警（判据锚点漂移 / 告警被整条删掉）")
        return v
    window = src[max(0, k - 600):k]
    # 🔴 守卫判定必须取**最近的那一条**控制行（口径与类级判据 14 同源）：取「前 600 字符里出现过」
    #    会被**信息行自己**（它引用了 `_df_after_mb`/`_need_mb`）喂绿 —— 实测：把守卫换成 `if false; then`
    #    后判据仍绿（判别力失效）。最近一行则当场红。
    guards = re.findall(r"^[ \t]*(?:if|elif) \[[^\n]*", src[:k], re.M)
    if not guards:
        v.append(f"`{RECLAIM_ZERO_WARNING}` 是**无条件**打印的 ⇒ 水位充裕时也发假警（issue #6512 ①）")
    elif not (re.search(r"_df_after_mb|_df_mb", guards[-1]) and "_need_mb" in guards[-1]
              and re.search(r"-l[et]|-g[et]", guards[-1])):
        v.append(
            "告警不由「回收后可用量 `_df_after_mb` vs 门槛 `_need_mb`」守卫（最近的控制行 ="
            f" `{guards[-1].strip()[:80]}`）⇒ 与「是否需要回收」无关"
            "（正是 issue #6512 ① 的改前形态：水位充裕也告警）"
        )
    if "if [" not in window:  # 保留窗口口径的一条：告警前面必须**有**条件分支（空跑锚点）
        v.append(f"`{RECLAIM_ZERO_WARNING}` 前面没有任何条件分支（判据锚点漂移）")
    if "属预期" not in build_block(text):
        v.append("水位充裕（不需要回收）时**没有信息行**说清「回收量 0 属预期」⇒ 读者仍会把它读成异常")
    return v


def problems_reclaim_metric_is_cache_delta(text: str) -> list:
    """判据 13（issue #6512 ②）：回收量的口径 = **构建缓存占用差**（不是 Δ整盘已用）。"""
    v = []
    src = code_lines(text)
    m = re.search(r"^\s*_reclaimed_mb=\$\(\(([^)]*)\)\)", src, re.M)
    if not m:
        v.append("找不到回收量的计算行 `_reclaimed_mb=$(( … ))`（判据锚点漂移）")
        return v
    expr = m.group(1)
    if "_cache_before_mb" not in expr or "_cache_after_mb" not in expr:
        v.append(
            "回收量口径不是**缓存占用差**（计算式里没有 `_cache_before_mb`/`_cache_after_mb`）："
            f"现状 `{expr.strip()}` ⇒ Δ整盘已用把**构建自身写盘**混了进来"
            "（「prune 腾 2GB + 构建写 2GB」读数 = 0 ⇒ 假警，issue #6512 ②）"
        )
    if "_used_after_mb" in expr:
        v.append("回收量仍取自 Δ整盘已用（`_used_*`）⇒ 假警的形状未消除")
    line = next((ln for ln in build_block(text).splitlines() if "缓存回收量：" in ln), "")
    if not line:
        v.append("构建后回收段没有「缓存回收量：」读数行")
    elif "_cache_before_mb" not in line or "_cache_after_mb" not in line:
        v.append("「缓存回收量：」行没有给出缓存占用差（前 → 后）⇒ 读数无法被复算")
    return v


def problems_build_block_warnings_are_waterline_gated(text: str) -> list:
    """判据 14（**类级**，issue #6512 / #6505 同族）：构建段里每条 `::warning::` 都要由门槛守卫。

    一类病（不是一处）：把「不需要 / 没发生」说成「有问题」⇒ 每次健康部署一条黄标 ⇒
    永久噪音让真失败与噪音同形。只钉「回收量」这一处样例不够 ⇒ 本判据对**整段**里每一条
    `::warning::` 判「它最近的条件行里必须出现门槛变量 `_need_mb`」（水位/门槛是「是否需要回收」的判据）。
    """
    v = []
    lines = build_block(text).splitlines()
    for i, ln in enumerate(lines):
        if "::warning::" not in ln:
            continue
        guards = [g for g in lines[max(0, i - 8):i + 1] if re.search(r"\b(if|elif) \[", g)]
        if not guards:
            v.append(f"构建段里的 `::warning::` 没有条件守卫：{ln.strip()[:90]}")
        elif "_need_mb" not in guards[-1]:
            v.append(
                "构建段里的 `::warning::` 不由门槛/水位守卫（最近的条件行里没有 `_need_mb`）"
                f" ⇒ 与「是否真需要回收」无关：{ln.strip()[:90]}"
            )
    return v


def problems_ci_branches_on_marker(text: str) -> list:
    """判据 9：CI 收口**按标记分支**，两条文案各自具名（全部在**原文**上判，见文件头的设计纪律）。"""
    v = []
    if "REMOTE_ABORT_REASON=$(printf" not in text:
        v.append("CI 脚本没有解析 `ABORT_REASON=`（仍只按 exit != 0 收口）")
    if "sed -n 's/^ *ABORT_REASON=//p'" not in text:
        v.append("`ABORT_REASON=` 的解析形态与同族标记（`EFFECTIVE_TAG=`）不一致（同族 = `printf | sed -n 's/^ *标记=//p'`）")
    if "**未开始部署**" not in text:
        v.append("收口文案里没有「**未开始部署**」⇒ 被前置闸门挡住时没有具名归因（issue #6505）")
        return v
    if "::error::**未开始部署**" not in text:
        v.append("「未开始部署」没有作为 `::error::` 收口（只出现在注释里 ≠ 收口）")
    if "环境未受影响" not in text:
        v.append("缺少「环境未受影响」的具名文案")
    # ⚠️ 锚点必须用**唯一**串 `::error::**未开始部署**`：`**未开始部署**` 在注释里也出现过
    #    （实测：第一次出现是给 `REMOTE_ABORT_REASON` 写的注释 ⇒ 邻域取到了函数定义那段）。
    i = text.find("::error::**未开始部署**")
    if i < 0:
        # ⚠️ 收口形态被破坏时**不许在这里抛**：上面那条「没有作为 `::error::` 收口」的违规
        #    **已经登记**（`v` 非空）⇒ 直接带着它返回。旧版这里无条件 `assert` ⇒ 注入式红证
        #    会在**判据本体**里抛 AssertionError（红的是夹具、不是判据），判别力反而读不出来。
        return v
    j = text.find("recovery_manual", i)
    seg = text[i:j + 200 if j > i else i + 3000]
    if "回收磁盘" not in seg or "扩容" not in seg:
        v.append("「未开始部署」的文案没有给出**可执行的出口**（回收磁盘 / 扩容）")
    return v


def problems_gate_leg_not_counted_as_broken(text: str) -> list:
    """判据 10：回滚腿被**同一闸门**挡住 ⇒ 不得计入「环境可能坏」的证据。"""
    v = []
    for fn in ("is_gate_abort() {", "gate_abort_label() {"):
        if fn not in text:
            v.append(f"找不到闸门分诊函数 `{fn[:-3]}`（回滚腿与主部署无法区分）")
    if '"$(is_gate_abort)" = "1"' not in text:
        v.append("收口处没有按 `$(is_gate_abort)` 分支（仍只按 exit != 0）")
    if "环境可能处于坏状态" not in text:
        v.append("找不到「环境可能处于坏状态」的文案（判据锚点漂移）")
    if "**回滚腿被同一道闸门挡住**" not in text:
        v.append("回滚腿被同一闸门挡住时没有点名（读者会把它读成第二次独立故障）")
    # 🔴 硬绑定：闸门分支里**不许**出现「环境可能处于坏状态」（那正是本单要治的误导）
    k = text.find('if [ "$(is_gate_abort)" = "1" ]; then')
    if k < 0:
        v.append("找不到闸门分支的落码点")
    else:
        nxt = text.find('say "::error::部署失败（tag=', k + 1)
        gate_seg = text[k:nxt] if nxt > k else text[k:k + 2000]
        if "环境可能处于坏状态" in gate_seg:
            v.append("闸门分支里出现了「环境可能处于坏状态」（闸门中止不得被读成环境损坏）")
    return v


def all_violations(deploy: str, ci: str) -> list:
    return (
        problems_cache_readout(deploy)
        + problems_ladder_links_to_waterline(deploy)
        + problems_only_build_cache_is_touched(deploy)
        + problems_retention_set_untouched(deploy)
        + problems_abort_marker(deploy)
        + problems_abort_does_not_touch_env(deploy)
        + problems_aggressive_prune_only_in_recovery(deploy)
        + problems_gate_fail_closed_kept(deploy)
        + problems_reclaim_zero_warning_gated_by_waterline(deploy)
        + problems_reclaim_metric_is_cache_delta(deploy)
        + problems_build_block_warnings_are_waterline_gated(deploy)
        + problems_ci_branches_on_marker(ci)
        + problems_gate_leg_not_counted_as_broken(ci)
    )


def build_block(text: str) -> str:
    """构建路径那一段：**承载 `docker build` 的那个** `BUILD_SERVICE` 守卫 → `== 1.5` 段之前。

    ⚠️ 两处陷阱（都实测踩过）：
    ① `BUILD_SERVICE` 守卫在脚本里有**两处**（一处只是取 `_svc` / 一处真的构建）⇒ 必须按
       `timeout "$BUILD_TIMEOUT_SECS" docker build` 定位**真构建**那一处，不能取第一个；
    ② 切段必须在**剥注释之前**做 —— `== 1.5` 那个结尾标记本身是注释（`code()` 会吃掉它 ⇒ 切段失败）。
    """
    # ⚠️ 结尾锚点必须在**原文**里找：`# 1.5 ` 那行本身是注释（`code_lines` 会整行吃掉 ⇒ 切过头，
    #    实测「1.5 段之后的内容」被算进构建段 ⇒ 判据假绿）。
    build = text.find('timeout "$BUILD_TIMEOUT_SECS" docker build')
    assert build > 0, "反空跑锚点：找不到带显式上界的构建调用（判据已过期）"
    i = text.rfind('if [ -n "$BUILD_SERVICE" ]; then', 0, build)
    assert i > 0, "反空跑锚点：找不到构建段的守卫（判据已过期）"
    j = text.find("# 1.5 ", i)
    assert j > i, "反空跑锚点：找不到构建段的结尾标记（判据已过期）"
    seg = code_lines(text[i:j])
    assert "docker build" in seg, "构建段里没有构建调用（切段失败）"
    assert "== 1.9" not in seg, "切段切过头了（把后面的段也含进来了）"
    return seg


# ══════════════════════════════════════════════════════════════════════════
# 一、静态判据（读脚本当前文本）
# ══════════════════════════════════════════════════════════════════════════

def test_real_scripts_satisfy_every_judgement():
    v = all_violations(read_deploy(), read_ci())
    assert not v, "磁盘水位 × 回收 / 收口归因 判据未满足：\n- " + "\n- ".join(v)


@pytest.mark.parametrize("judge,bucket", [
    (problems_cache_readout, "deploy"),
    (problems_ladder_links_to_waterline, "deploy"),
    (problems_only_build_cache_is_touched, "deploy"),
    (problems_retention_set_untouched, "deploy"),
    (problems_abort_marker, "deploy"),
    (problems_abort_does_not_touch_env, "deploy"),
    (problems_aggressive_prune_only_in_recovery, "deploy"),
    (problems_gate_fail_closed_kept, "deploy"),
    (problems_reclaim_zero_warning_gated_by_waterline, "deploy"),
    (problems_reclaim_metric_is_cache_delta, "deploy"),
    (problems_build_block_warnings_are_waterline_gated, "deploy"),
    (problems_ci_branches_on_marker, "ci"),
    (problems_gate_leg_not_counted_as_broken, "ci"),
])
def test_each_judge_is_clean_on_the_real_scripts(judge, bucket):
    """逐条判据在真实脚本上各自干净（避免一条恒红被「整体红」掩盖）。"""
    v = judge(read_deploy() if bucket == "deploy" else read_ci())
    assert not v, f"{judge.__name__} 判红：\n- " + "\n- ".join(v)


# ══════════════════════════════════════════════════════════════════════════
# 二、注入式红证（每条判据各自可独立判红）
# ══════════════════════════════════════════════════════════════════════════

def test_injection_ladder_back_to_fixed_window_goes_red():
    """注入①：把「按水位选窗口」换回固定 `until=168h` 的空操作 ⇒ 判据 2 必红。"""
    text = read_deploy()
    injected = _inject(text, '  if [ "$free" -ge "$((want * 4))" ]; then echo 168',
                       "  if true; then echo 168")
    assert problems_ladder_links_to_waterline(injected), "换回固定窗口后没红（判据无判别力）"


def test_injection_abort_marker_removed_goes_red():
    """注入②：删掉 `ABORT_REASON=BUILD_MIN_FREE_MB` ⇒ 判据 5 必红。"""
    text = read_deploy()
    injected = _inject(text, f'echo "ABORT_REASON={ABORT_REASON}"\n', "")
    assert problems_abort_marker(injected), "删掉机读标记后没红（判据无判别力）"


def test_injection_cache_readout_removed_goes_red():
    """注入③：把缓存读数从构建路径摘掉 ⇒ 判据 1 必红。"""
    text = read_deploy()
    line = "／构建缓存：${_cache_before_mb:-?} → ${_cache_after_mb:-?}"
    assert line in text, "反空跑锚点：构建路径里找不到缓存读数打印行"
    injected = _inject(text, line, "／构建缓存：?（注入：读数被摘掉）")
    assert problems_cache_readout(injected), "摘掉读数后没红（判据无判别力）"


def test_injection_image_delete_in_cache_section_goes_red():
    """注入④：在缓存回收段里删镜像 ⇒ 判据 3 必红（越权会误删回滚点）。"""
    src = read_deploy()
    anchor = "    if docker builder prune -af >/dev/null 2>&1; then"
    injected = _inject(src, anchor, "    docker image rm -f nginx:alpine || true\n" + anchor)
    assert problems_only_build_cache_is_touched(injected), "缓存段删镜像后没红（判据无判别力）"


def test_injection_retention_token_in_cache_section_goes_red():
    """注入⑤：让缓存段引用回滚点 ⇒ 判据 4 必红（结构上碰到了保留集）。"""
    src = read_deploy()
    anchor = "  CACHE_RECOVER_CANDIDATE=1"
    injected = _inject(src, anchor, anchor + '\n  [ -n "$(rollback_tag)" ] || true')
    assert problems_retention_set_untouched(injected), "缓存段引用回滚点后没红（判据无判别力）"


def test_injection_environment_touched_before_abort_goes_red():
    """注入⑥：中止分支里先 pull 一次 ⇒ 判据 6 必红（环境被动过）。"""
    src = read_deploy()
    injected = _inject(src, f'    echo "ABORT_REASON={ABORT_REASON}"\n',
                       f'    docker compose pull admin-api >/dev/null 2>&1 || true\n'
                       f'    echo "ABORT_REASON={ABORT_REASON}"\n')
    assert problems_abort_does_not_touch_env(injected), "中止分支动环境后没红（判据无判别力）"


def test_injection_fail_closed_downgraded_goes_red():
    """注入⑦：把 fail-closed 改成「继续部署」⇒ 判据 8 必红（安全护栏被砍）。"""
    src = read_deploy()
    injected = _inject(src, '  if [ "${_df_mb:-0}" -lt "$_need_mb" ]; then',
                       "  if false; then")
    assert problems_gate_fail_closed_kept(injected), "砍掉 fail-closed 比较后没红（判据无判别力）"


def test_injection_ci_back_to_exit_code_only_goes_red():
    """注入⑧：CI 收口退回「只看 exit != 0」⇒ 判据 9 必红（正是改前形态）。"""
    ci = read_ci()
    # 🔴 锚点必须落在**消费机读标记的码路**上：`REMOTE_ABORT_REASON=$(printf` 全文**只出现一次**
    #    （`capture_remote_log` 里）——摘掉它 = 没有任何标记消费面 = 改前形态（只看 exit != 0）。
    # ⚠️ 不能拿 `**未开始部署**` 当锚点：它**首先**出现在给 `REMOTE_ABORT_REASON` 写的那段**注释**里
    #    （实测）⇒ `_inject` 只换第一处 = 只改注释、收口一字未动 ⇒ 判据照旧干净（假红）。
    injected = _inject(ci, "REMOTE_ABORT_REASON=$(printf", "REMOTE_ABORT_REASON_IGNORED=$(printf")
    assert problems_ci_branches_on_marker(injected), "退回只看退出码后没红（判据无判别力）"
    injected2 = re.sub(r"::error::(\*\*未开始部署\*\*)", r"::warning::\1", ci, count=1)
    assert injected2 != ci, "注入未生效（收口文案形态已漂移）"
    assert problems_ci_branches_on_marker(injected2), "把「未开始部署」降级成 warning 后没红（判据无判别力）"


def test_injection_aggressive_prune_into_build_path_goes_red():
    """注入⑨：把 `-af` 挪进构建路径（无条件清光缓存）⇒ 判据 7 必红。"""
    src = read_deploy()
    injected = _inject(src, '  _build_args=(--build-arg "APT_MIRROR=$APT_MIRROR")',
                       '  CACHE_RECOVER_AF_CALL=1\n  docker builder prune -af || true\n'
                       '  _build_args=(--build-arg "APT_MIRROR=$APT_MIRROR")')
    assert problems_aggressive_prune_only_in_recovery(injected), "构建路径出现 -af 后没红（判据无判别力）"


def test_injection_reclaim_warning_ungated_goes_red():
    """注入⑩（issue #6512 ①）：把「水位充裕 ⇒ 信息行」的守卫拆掉 ⇒ 判据 12 与类级判据 14 必红。"""
    injected = _inject(read_deploy(), '    if [ "${_df_after_mb:-0}" -ge "$_need_mb" ]; then',
                       "    if false; then")
    assert problems_reclaim_zero_warning_gated_by_waterline(injected), "拆掉水位守卫后没红（判据无判别力）"
    assert problems_build_block_warnings_are_waterline_gated(injected), "类级守卫（判据 14）没红"


def test_injection_reclaim_metric_back_to_used_delta_goes_red():
    """注入⑪（issue #6512 ②）：把回收量口径换回 Δ整盘已用 ⇒ 判据 13 必红（改前形态）。"""
    injected = _inject(read_deploy(), "    _reclaimed_mb=$(( _cache_before_mb - _cache_after_mb ))",
                       "    _reclaimed_mb=$(( ${_used_before_mb:-0} - ${_used_after_mb:-0} ))")
    assert problems_reclaim_metric_is_cache_delta(injected), "换回 Δ已用后没红（判据无判别力）"


def test_injection_reclaim_info_line_removed_goes_red():
    """注入⑫：删掉「属预期」的信息行 ⇒ 判据 12 必红（水位充裕的读者仍会被引去「人工核对」）。"""
    src = read_deploy()
    injected = re.sub(r"[^\n]*属预期[^\n]*\n", "", src, count=1)
    assert injected != src, "注入未生效（信息行形态已漂移）"
    assert problems_reclaim_zero_warning_gated_by_waterline(injected), "删掉信息行后没红（判据无判别力）"


def test_comment_only_change_stays_green():
    """对照读数：只加注释（哪怕提到被禁形态）⇒ 不红（判据不吃自己的说明文字）。"""
    benign_d = read_deploy() + "\n# 备注：这里提到 docker builder prune -af 与 ABORT_REASON 以及 构建缓存：?\n"
    benign_c = read_ci() + "\n# 备注：也提到「未开始部署」「环境可能处于坏状态」但不是代码\n"
    assert all_violations(benign_d, benign_c) == [], "只加注释就判红 ⇒ 判据误吃说明文字（假红）"


# ══════════════════════════════════════════════════════════════════════════
# 三、执行式红证：窗口阶梯（真跑函数本体，桩 docker，逐档可复算）
# ══════════════════════════════════════════════════════════════════════════

def _run_window_picker(tmp_path: Path, free_mb: int, cache_mb: int,
                       env_extra: dict | None = None) -> str:
    """把**真** `pick_cache_window()` 抠出来真跑（零 docker、零网络），回它选的窗口。

    ⚠️ 本函数的哈希表只喂一个变量（磁盘可用 MB）⇒ 判的是「窗口随水位单调变紧」这一条**契约**。
    """
    src = code(read_deploy())
    body = function_body(src, "pick_cache_window")
    ladder_lines = [ln for ln in src.splitlines() if re.match(r"^BUILD_CACHE_LADDER=|^CACHE_WINDOW_LADDER=", ln)]
    assert ladder_lines, "反空跑锚点：找不到窗口阶梯常量（判据已过期）"
    harness = (
        "#!/bin/bash\nset -euo pipefail\n"
        + "\n".join(ladder_lines) + "\n"
        + 'disk_free_mb() { echo "${FAKE_FREE_MB}"; }\n'
        + 'cache_total_mb() { echo "${FAKE_CACHE_MB}"; }\n'
        + "pick_cache_window() {" + body + "\n}\n"
        # ⚠️ 喂进去的必须是**可用量**（不是脚本的位置参数）：首版写成 `"$1"` ⇒ 喂的是门槛 4096
        # ⇒ 任何水位都落同一档（实测恒 48h、判据退化成「恒真」）。
        + 'pick_cache_window "$FAKE_FREE_MB"\n'
    )
    script = tmp_path / "picker.sh"
    script.write_text(harness, encoding="utf-8")
    env = {
        **os.environ,
        "FAKE_FREE_MB": str(free_mb),
        "FAKE_CACHE_MB": str(cache_mb),
        **(env_extra or {}),
    }
    proc = subprocess.run(["bash", str(script), "4096"], cwd=str(tmp_path), env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"窗口选择器真跑失败：\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout.strip()


def test_window_tightens_as_free_space_drops(tmp_path):
    """判据 2 的**行为面**：可用量越小 ⇒ 窗口越紧（单调），且最紧档 = 兜底（`all`/`-af`）。"""
    free_hi = int(_run_window_picker(tmp_path, free_mb=20000, cache_mb=13000))
    free_mid = int(_run_window_picker(tmp_path, free_mb=5000, cache_mb=13000))
    free_lo = int(_run_window_picker(tmp_path, free_mb=3100, cache_mb=13000))
    assert free_hi > free_mid > free_lo, (
        f"窗口没有随水位单调变紧：充裕={free_hi}h / 临界={free_mid}h / 告急={free_lo}h"
        "（改前形态是**恒** 168h ⇒ 真机上 `Total: 0B` 的空操作）"
    )
    assert free_lo <= 24, (
        f"告急档仍选到 {free_lo}h —— 真机实测缓存条目全是 72h 内建的 ⇒ 不降到更短窗口就是空操作"
    )
    hardest = int(_run_window_picker(tmp_path, free_mb=100, cache_mb=13000))
    assert hardest <= 6, (
        f"最紧档应落到「连几小时内的缓存也清」（实测缓存 100% RECLAIMABLE ⇒ 必然解得出空间），实得 {hardest!r}"
    )


def test_window_picker_red_proof_when_waterline_ignored(tmp_path):
    """行为面红证：把 `pick_cache_window` 换成「恒 168」⇒ 上面那条判据必红（判别力自证）。"""
    src = code(read_deploy())
    body = function_body(src, "pick_cache_window")
    ladder_lines = [ln for ln in src.splitlines() if re.match(r"^BUILD_CACHE_LADDER=|^CACHE_WINDOW_LADDER=", ln)]
    harness = (
        "#!/bin/bash\nset -euo pipefail\n"
        + "\n".join(ladder_lines) + "\n"
        + 'disk_free_mb() { echo "${FAKE_FREE_MB}"; }\n'
        + 'cache_total_mb() { echo "${FAKE_CACHE_MB}"; }\n'
        + "pick_cache_window() { echo 168; }\n"
        + 'pick_cache_window "$1"\n'
    )
    script = tmp_path / "picker-broken.sh"
    script.write_text(harness, encoding="utf-8")
    env = {**os.environ, "FAKE_FREE_MB": "100", "FAKE_CACHE_MB": "13000"}
    proc = subprocess.run(["bash", str(script), "4096"], cwd=str(tmp_path), env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.stdout.strip() == "168", "注入了固定窗口却读不到 168（红证空跑）"
    assert body != " echo 168; return 0; ", "（自证：注入的形态与真实现不同）"


# ══════════════════════════════════════════════════════════════════════════
# 四、执行式红证：真跑 deploy.sh（桩 df / docker / curl / flock / timeout）
# ══════════════════════════════════════════════════════════════════════════

# 桩 `df -Pk /`：按调用序号回放注入值（`DF_FREE_MB_SEQ` 逗号序列；用尽后重复末值）。
DF_STUB = r"""#!/bin/bash
n=$(cat "$STATE_DIR/df-calls" 2>/dev/null || echo 0)
n=$((n + 1)); echo "$n" > "$STATE_DIR/df-calls"
val=$(printf '%s' "${DF_FREE_MB_SEQ:-9000}" | cut -d, -f"$n")
if [ -z "$val" ]; then val=$(printf '%s' "${DF_FREE_MB_SEQ:-9000}" | awk -F, '{print $NF}'); fi
echo "Filesystem     1K-blocks     Used Available Use% Mounted on"
awk -v mb="$val" 'BEGIN { printf "/dev/vda3  41943040 30000000 %d  80%% /\n", mb * 1024 }'
"""

# 桩 `docker`：只实现本判据需要的那几条子命令；其余一律成功（构建/健康检查不占本判据面）。
# ⚠️ 缓存占用是**状态量**（issue #6512 判据 13 需要「prune 真的让读数变小」）：`STUB_PRUNE_FREED_MB`
#    非空时，`builder prune` 会把状态文件里的占用减掉那么多 ⇒ `docker system df` 的后续读数随之变小
#    （真机口径）。**不设它时行为与改前逐字相同**（常量读数），既有判据不受影响。
DOCKER_STUB = r"""#!/bin/bash
cache_state() { printf '%s' "$STATE_DIR/cache-size"; }
cache_now() {
  if [ -f "$(cache_state)" ]; then cat "$(cache_state)"
  else printf '%s' "${STUB_CACHE_SIZE:-}"; fi
}
case "$*" in
  "system df --format "*)
    cur=$(cache_now)
    [ -n "$cur" ] || exit 1
    # ⚠️ `--format '{{.Type}} {{.Size}}'` 的真形态 = **两列**（`Build Cache <SIZE>`）：
    #    写三列会让夹具与真机不同源（真机上 `$3` 是空串 ⇒ 读数退化成 `?`）。
    echo "TYPE            SIZE"
    echo "Images          4.1GB"
    echo "Build Cache     ${cur}"
    # ⚠️ 第三列才是 SIZE（第一列是条目数 TOTAL）—— 与真机 `docker system df` 一致
    exit 0 ;;
  "system df -v"*)
    cur=$(cache_now)
    [ -n "$cur" ] || exit 1
    echo "Build cache usage: $(printf '%s' "$cur" | sed 's/[A-Za-z]//g')MB"
    exit 0 ;;
  "builder prune "*)
    echo "$*" >> "$STATE_DIR/cache-prunes"
    if [ "${STUB_PRUNE_RC:-0}" = "0" ] && [ -n "${STUB_PRUNE_FREED_MB:-}" ]; then
      base=$(printf '%s' "$(cache_now)" | sed 's/[A-Za-z]//g'); [ -n "$base" ] || base=0
      new=$(( base - STUB_PRUNE_FREED_MB )); [ "$new" -lt 0 ] && new=0
      printf '%sMB' "$new" > "$(cache_state)"
    fi
    exit "${STUB_PRUNE_RC:-0}" ;;
  "images --format "*)
    echo "nginx:alpine"
    exit 0 ;;
  "image inspect "*) exit 0 ;;
  "compose config"*)
    echo '{"services": {"admin-api": {"image": "reg.example/ai-customer-service/admin-api:sha-new"}}}'
    exit 0 ;;
  "compose pull "*)
    echo "pull $*" >> "$STATE_DIR/pulls"
    exit 0 ;;
  "compose up "*) echo "up $*" >> "$STATE_DIR/ups"; exit 0 ;;
esac
echo "docker $*" >> "$STATE_DIR/docker-other"
exit 0
"""

CURL_STUB = r"""#!/bin/bash
# 桩 curl：codeload 源码包 → 把预置 tar 拷过去（`file://` 下只传路径）；其余 → 写空 + 回 200（健康检查）
out=""; fmt=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w) fmt="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in
  *codeload.github.com*|file://*) cp "$STUB_TAR" "$out"; exit 0 ;;
esac
if [ -n "$out" ]; then : > "$out"; fi
if [ -n "$fmt" ]; then printf '200'; fi
exit 0
"""

# 桩 `file`（CI 侧：CLI 安装块用它校验下载物是 gzip）—— 只伪装「那是 gzip」这一句
REAL_FILE_STUB = r"""#!/bin/bash
echo "$1: gzip compressed data, from Unix"
exit 0
"""

# 桩 `curl`（CI 侧）：把 CLI 的 .tgz 造成**真 gzip**（否则 `tar xzf` 当场失败、脚本 exit 2）
FAKE_CURL_STUB = r"""#!/bin/bash
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -*) shift ;;
    *) shift ;;
  esac
done
if [ -n "$out" ]; then printf '\037\213\010\000' > "$out"; fi
exit 0
"""


def rebase_tmp_paths(text: str, root: Path) -> str:
    """把脚本里的绝对路径改指到沙箱（**只改路径、不改逻辑**；与既有夹具同手法）。

    ⚠️ 必须**先**重写路径、**后**注入桩文本：桩文本里也带 `/tmp/hc_`，顺序反了会把桩自己改坏
    （实测踩到 —— 与 `test_swas_deploy_ci_bootstrap.py` 的既有纪律同族）。
    """
    out = text.replace("/opt/migao-deploy", str(root / "opt-migao-deploy") if root.name == "sandbox" else str(root))
    out = out.replace("/tmp/migao-deploy.lock", str(root / "deploy.lock"))
    out = out.replace("/tmp/hc_", f"{root}/hc_")
    out = out.replace("/tmp/aliyun", str(root / "aliyun"))
    return out


def make_src_tar(dest: Path) -> None:
    """造一个**真**源码包（含 4 个 canonical 配置）⇒ 第 1 段的自检能通过，脚本能走到构建段。"""
    stage = dest.parent / "stage" / "migao-main"
    for rel in ("deploy/swas/docker-compose.yml", "deploy/swas/deploy.sh"):
        (stage / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, stage / rel)
    (stage / "deploy/swas/docker-compose.bluegreen.yml").write_text(
        "services: {}\n", encoding="utf-8")
    (stage / "deploy/swas/nginx.conf").write_text("worker_processes 1;\n", encoding="utf-8")
    # 最小构建上下文（`src/backend/admin-api/Dockerfile`）：1.4 段在构建前会自检它
    (stage / "backend/admin-api").mkdir(parents=True, exist_ok=True)
    (stage / "backend/admin-api/Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(stage, arcname="migao-main")

FLOCK_STUB = "#!/bin/bash\nexit 0\n"
TIMEOUT_STUB = "#!/bin/bash\nshift\nexec \"$@\"\n"


def _write_exe(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _run_deploy(tmp_path: Path, *, df_seq: str, cache_size: str = "",
                env_extra: dict | None = None, script_text: str | None = None):
    """跑**真实** `deploy.sh`（桩外部依赖）。返回 (proc, state, 输出文本)。"""
    work = tmp_path / "opt-migao-deploy"
    work.mkdir(exist_ok=True)
    text = rebase_tmp_paths(script_text if script_text is not None else read_deploy(), work)
    script = work / "deploy.sh"
    script.write_text(text, encoding="utf-8")
    tar_path = tmp_path / "src.tar.gz"
    make_src_tar(tar_path)
    for env_file in (".env.admin-api", ".env.ai-agent", ".env.registry"):
        (work / env_file).write_text("SMS_BYPASS_CODE=1\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    (state / "pulls").write_text("", encoding="utf-8")
    (state / "ups").write_text("", encoding="utf-8")
    (state / "cache-prunes").write_text("", encoding="utf-8")
    (state / "docker-other").write_text("", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("df", DF_STUB), ("docker", DOCKER_STUB), ("curl", CURL_STUB),
                       ("flock", FLOCK_STUB), ("timeout", TIMEOUT_STUB)):
        _write_exe(bin_dir / name, body)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STATE_DIR": str(state),
        "CONFIG_TARBALL_BASE": f"file://{tmp_path}",
        "STUB_TAR": str(tar_path),
        "DF_FREE_MB_SEQ": df_seq,
        "STUB_CACHE_SIZE": cache_size,
        "BUILD_SERVICE": "admin-api",
        "BUILD_MIN_FREE_MB": "4096",
        "BUILD_CACHE_GATE_MB": "1",
        "LOCK_WAIT_SECONDS": "5",
        "HC_RETRIES": "1",
        "HC_INTERVAL_SECONDS": "0",
        "BG_MEM_NEED_MB": "0",
        "BG_OFF_FILE": str(work / ".blue-green-off"),
        "LAST_GOOD_FILE": str(work / ".last-good-tag"),
        "PROJECT_IMAGE_PREFIX": "ai-customer-service/",
        **(env_extra or {}),
    }
    proc = subprocess.run(["bash", str(script), "sha-new"], cwd=str(work), env=env,
                          capture_output=True, text=True, errors="replace", timeout=300)
    return proc, state, proc.stdout + proc.stderr


def test_exec_cache_readout_is_a_number_never_a_question_mark(tmp_path):
    """判据 1 的行为面：真机 `构建缓存：?` 的形态必须消失 —— 读数打得出**数值**。"""
    proc, _state, out = _run_deploy(tmp_path, df_seq="9000", cache_size="1.9GB")
    assert "构建缓存" in out, f"日志里没有构建缓存读数行：\n{out[-1500:]}"
    assert "构建缓存：?" not in out, f"读数仍是 `?`（正是 issue #6508 的现场形态）：\n{out[-1500:]}"
    assert re.search(r"构建缓存[^\n]*?(19\d\d|2048|1945)MB", out), (
        f"1.9GB 的读数没有被解析成带数值的形态：\n{[l for l in out.splitlines() if '构建缓存' in l]}"
    )


def test_exec_gate_abort_emits_marker_and_touches_nothing(tmp_path):
    """判据 5+6+8 的行为面：门槛不足 ⇒ 打标记、中止、**不动环境**（不 build / 不 pull / 不 up）。"""
    # 前置 4045MB（<4096）⇒ 清缓存后仍只有 3000MB ⇒ 必然走 fail-closed 中止分支
    proc, state, out = _run_deploy(tmp_path, df_seq="4045,3000,3000", cache_size="12.4GB")
    assert proc.returncode != 0, f"余量不足竟然没中止：\n{out[-1500:]}"
    assert f"ABORT_REASON={ABORT_REASON}" in out, (
        f"中止时没有打机读标记（issue #6505 要的形态）：\n{out[-1500:]}"
    )
    assert "中止构建" in out and "旧容器保持不动" in out, f"中止文案缺失：\n{out[-1500:]}"
    assert (state / "pulls").read_text(encoding="utf-8").strip() == "", "中止前动了镜像（pull）"
    assert (state / "ups").read_text(encoding="utf-8").strip() == "", "中止前动了容器（up）"
    assert not re.search(r"构建命令：timeout|本地构建完成", out), (
        f"中止分支里竟然走到了构建（出口文案里的 `docker builder prune` 不算）：\n{out[-1500:]}"
    )


def test_exec_recovery_actually_runs_a_ladder_with_nonzero_reclaim(tmp_path):
    """判据 2+7 的行为面：水位告急 ⇒ **真跑**窗口阶梯，且清理量非零（真机空操作的对立面）。"""
    # 前置 4045MB ⇒ 逐档清到阈值以上为止（桩在第二次 df 起回 9000MB）
    proc, state, out = _run_deploy(tmp_path, df_seq="4045,9000", cache_size="12.4GB",
                                   env_extra={"STUB_CACHE_SIZE": "12.4GB"})
    assert proc.returncode == 0, f"自愈后应该继续部署：\n{out[-2000:]}"
    prunes = (state / "cache-prunes").read_text(encoding="utf-8")
    assert prunes.strip(), "水位告急时根本没跑缓存回收（= 改前的空操作形态）"
    assert "until=" in prunes, f"回收没有带窗口过滤：{prunes!r}"
    assert re.search(r"缓存回收量：-?\d+MB", out), (
        f"回收没有把「清理量」打进日志（失败可见性）：\n{[l for l in out.splitlines() if '缓存' in l]}"
    )
    assert re.search(r"／构建缓存：\d+ → \d+（清理档=\d）", out), (
        f"日志里读不到缓存读数的「前 → 后」形态：\n{[l for l in out.splitlines() if '缓存' in l]}"
    )


def test_exec_recovery_never_touches_images_or_retention_set(tmp_path):
    """判据 3+4 的行为面：缓存回收全程**只碰构建缓存**（没有任何镜像删除调用）。"""
    proc, state, out = _run_deploy(tmp_path, df_seq="4045,9000", cache_size="12.4GB")
    # ⚠️ 只看**缓存回收那一段**的调用：`docker image prune -f` 是 2.7 段**保留策略**的兜底
    #    （既有行为，不在本单射程）⇒ 判据必须按段落切，不能拿整跑日志判「越权」。
    i = out.find("== 1.4 C′ 服务器侧构建")
    j = out.find("== 1.9 磁盘水位预检", i)
    assert i > 0 and j > i, f"取不到构建段：\n{out[-2000:]}"
    seg = out[i:j]
    calls = [ln for ln in seg.splitlines() if "docker " in ln and "echo" not in ln]
    for bad in ("image rm", "image prune", "system prune", "rmi"):
        assert not any(re.search(rf"docker\s+{bad}", ln) for ln in calls), (
            f"缓存回收路径里出现了 `docker {bad}`（越权）：\n" + "\n".join(calls)
        )
    assert "rollback" not in out.lower() or ".last-good-tag" not in out, (
        "缓存回收段引用了回滚点（结构上碰到了保留集）"
    )


def test_exec_cache_prune_failure_is_visible_and_still_fails_closed(tmp_path):
    """失败可见性：`docker builder prune` 失败 ⇒ 必须出声（`::warning::`），且**仍然** fail-closed。"""
    proc, state, out = _run_deploy(tmp_path, df_seq="4045,3000,3000", cache_size="12.4GB",
                                   env_extra={"STUB_PRUNE_RC": "1"})
    assert proc.returncode != 0, "prune 失败 + 余量不足 ⇒ 必须中止"
    # ⚠️ 「失败可见」在本码路里的**逐字形态** = `builder_cache_recover` 失败分支打的那两行
    #    `⚠️ docker builder prune … 失败（…）`。`::warning::` 是**构建后**回收量=0 那一段
    #    （deploy.sh 2.7）才用的 GitHub 注解形态 —— 本场景在**构建前**的闸门上就 fail-closed 中止
    #    （3000MB < 4096MB）⇒ **走不到**那里。夹具原来拿 `::warning::` 当锚点 = 锚到**另一条码路**
    #    （判据恒红、与实现无关）。改钉这条码路真实的「被点名说出」（改前形态 = 静默：没有失败行）。
    assert re.search(r"⚠️ docker builder prune[^\n]*失败", out), (
        f"prune 失败没有出声（静默失败 = 本单要治的形态）：\n{out[-2000:]}"
    )
    assert "缓存回收" in out, f"prune 失败时没有任何缓存回收上下文：\n{out[-2000:]}"
    assert f"ABORT_REASON={ABORT_REASON}" in out, "fail-closed 中止时仍未打标记"


def test_exec_no_cache_reading_still_aborts_and_says_so(tmp_path):
    """读不到缓存（`docker system df` 失败）⇒ 不许静默：读数显式标 `?`/未知，且仍 fail-closed。"""
    proc, _state, out = _run_deploy(tmp_path, df_seq="4045,3000,3000", cache_size="")
    assert proc.returncode != 0, "读不到缓存不该让闸门失效"
    assert f"ABORT_REASON={ABORT_REASON}" in out
    assert "无法读数" in out or "读数不可得" in out or "?" in out, (
        "缓存读不到时没有任何显式说明（静默 = 与改前同样的形态）"
    )


# ══════════════════════════════════════════════════════════════════════════
# 四之二、issue #6512：构建后「回收量为 0」的**假警**与回收量的**口径**
#
# 现场（真机 run `37634071278`，结论 success，逐字）：
# ```
# 构建前磁盘可用：10059MB（门槛 4096MB）
# 🧹 缓存回收：水位 10053MB ⇒ 选窗口 72h
# 构建后磁盘可用：10052MB（构建前 10059MB）／构建缓存：6839 → 6839（清理档=1）
# 缓存回收量：0MB（已用 28042MB → 28042MB；档位 1/2）
# ##[warning]缓存回收量为 0（构建缓存 6839MB，清理档 1/2）—— 出口没有真的腾出空间，需人工核对
# ```
# ⇒ 水位充裕（10059 ≫ 4096）+ 缓存层都是几十分钟内的 ⇒ 72h 档匹配 0 条 ⇒ 0 **是预期**。
# 桩 `df` 的 `Used` 列不随缓存变化 ⇒ 夹具里的 Δ整盘已用**恒为 0**，恰好等价于 issue 描述的场景
# 「prune 腾 2GB + 构建自身写 2GB ⇒ Δused = 0」（判据 13 的判别力正来自这一点）。
# ══════════════════════════════════════════════════════════════════════════

#: 水位充裕（真机读数形态：构建前 10059MB ≫ 门槛 4096MB）
GENEROUS_DF_SEQ = "10059,10000,10050,10052,10052"
#: 构建**后**掉到门槛以下（`_df_after_mb` = 3000MB < 4096MB）⇒ 回收量 0 时**必须**告警
LOW_WATERLINE_DF_SEQ = "9000,9000,9000,9000,3000"


def test_exec_generous_waterline_zero_reclaim_is_info_not_warning(tmp_path):
    """判据 12 的行为面（issue #6512 ① 的现场）：水位充裕 + 缓存差 0 ⇒ 只打信息行，**不得**告警。"""
    proc, state, out = _run_deploy(tmp_path, df_seq=GENEROUS_DF_SEQ, cache_size="6839MB")
    assert proc.returncode == 0, f"健康部署（水位充裕）不该失败：\n{out[-2000:]}"
    assert RECLAIM_ZERO_WARNING not in out, (
        "🔴 水位充裕（可用 10052MB ≫ 门槛 4096MB）时仍发「回收量为 0」的假警"
        "（正是 issue #6512 ① 的现场）:\n" + "\n".join(l for l in out.splitlines() if "缓存" in l)
    )
    assert re.search(r"缓存回收量：0MB", out), f"读数行缺失/形态漂移：\n{out[-1500:]}"
    info = [l for l in out.splitlines() if "属预期" in l]
    assert info, f"水位充裕时没有信息行说清「回收量 0 属预期」：\n{out[-1500:]}"
    assert "水位充裕" in info[0] and "72h" in info[0], (
        f"信息行没有说清「为什么是 0」（水位充裕 + 按 N h 档未匹配到可回收层）：{info[0]!r}"
    )
    assert "until=72h" in (state / "cache-prunes").read_text(encoding="utf-8"), (
        "阶梯没有按水位选到 72h 档（判据锚点漂移）"
    )


def test_exec_low_waterline_zero_reclaim_still_warns(tmp_path):
    """判据 12 的反向面（**防反向假绿**）：水位告急（3000MB < 门槛）+ 回收量 0 ⇒ **必须**告警。

    没有这一条，「把告警整行删掉」也能让上一条变绿 —— 那是把假警修成**假绿**。
    同时钉住既有护栏：`BUILD_CACHE_RECLAIM_INSUFFICIENT` 的「下次构建会被拦」一字未动。
    """
    proc, _state, out = _run_deploy(tmp_path, df_seq=LOW_WATERLINE_DF_SEQ, cache_size="6839MB")
    assert RECLAIM_ZERO_WARNING in out, (
        f"水位告急（可用 3000MB < 门槛 4096MB）而回收量为 0 却不告警 ⇒ 告警被一并删掉（反向假绿）：\n{out[-2000:]}"
    )
    assert "属预期" not in out, "水位告急时也说「属预期」⇒ 把真异常说成正常"
    assert "ABORT_REASON=BUILD_CACHE_RECLAIM_INSUFFICIENT" in out, "既有护栏（下次会被拦）的机读标记被动了"
    assert "下次构建会被前置检查拦住" in out, "既有护栏（下次会被拦）的告警文案被动了"
    assert proc.returncode == 0, "构建后余量不足只告警、本次部署继续（既有语义）"


def test_exec_reclaim_metric_is_cache_delta_not_used_delta(tmp_path):
    """判据 13 的行为面：注入「prune 腾 2GB + Δ整盘已用 = 0」⇒ 回收量读数**必须**是缓存占用差。"""
    proc, _state, out = _run_deploy(tmp_path, df_seq="9000", cache_size="6839MB",
                                    env_extra={"STUB_PRUNE_FREED_MB": "2048"})
    assert proc.returncode == 0, f"健康部署不该失败：\n{out[-2000:]}"
    assert "缓存回收量：2048MB" in out, (
        "回收量口径不是缓存占用差（prune 腾了 2048MB，读数却不是 2048MB）：\n"
        + "\n".join(l for l in out.splitlines() if "缓存回收量" in l or "整盘已用" in l)
    )
    assert re.search(r"整盘已用 (\d+)MB → \1MB", out), (
        f"夹具没有建模「Δ整盘已用 = 0」⇒ 本条的判别力不成立（旧口径在这种场景恰好读 0）：\n{out[-1500:]}"
    )
    assert RECLAIM_ZERO_WARNING not in out, "明明腾出空间了，却仍发「回收量为 0」的告警"


def test_exec_cache_readout_unavailable_never_fabricates_zero(tmp_path):
    """读数不可得（`docker system df` 失败）⇒ 显式说「无法判定」，**不许**拿 0 冒充「没腾出空间」。"""
    proc, _state, out = _run_deploy(tmp_path, df_seq="9000", cache_size="")
    assert proc.returncode == 0, f"读数不可得不该让部署崩掉：\n{out[-2000:]}"
    assert re.search(r"缓存回收量：无法判定", out), f"读数不可得时没有显式说明：\n{out[-1500:]}"
    assert RECLAIM_ZERO_WARNING not in out, "读数不可得却谎报「回收量为 0」"


def test_exec_red_proof_generous_waterline_warning_gate_removed(tmp_path):
    """反向红证（§28.1 出口①）：拆掉水位守卫（恒走告警分支）⇒ 同一**充裕**水位夹具必发假警。"""
    injected = _inject(read_deploy(), '    if [ "${_df_after_mb:-0}" -ge "$_need_mb" ]; then',
                       "    if false; then")
    proc, _state, out = _run_deploy(tmp_path, df_seq=GENEROUS_DF_SEQ, cache_size="6839MB",
                                    script_text=injected)
    assert RECLAIM_ZERO_WARNING in out, (
        f"拆掉水位守卫后仍读不到假警 ⇒ 上面那条判据没有判别力：\n{out[-1500:]}"
    )


def test_exec_red_proof_low_waterline_warning_deleted(tmp_path):
    """反向红证：把告警整行删掉 ⇒ 水位告急的夹具上**读不到**任何告警（判据 12 反向面判别力自证）。"""
    src = read_deploy()
    injected = re.sub(r'[ \t]*echo "  ::warning::缓存回收量为 0[^\n]*\n', "", src, count=1)
    assert injected != src, "注入未生效（告警行形态已漂移）"
    proc, _state, out = _run_deploy(tmp_path, df_seq=LOW_WATERLINE_DF_SEQ, cache_size="6839MB",
                                    script_text=injected)
    assert RECLAIM_ZERO_WARNING not in out, "删掉告警后仍打印 ⇒ 注入没落在告警上"


def test_exec_red_proof_used_delta_metric_reads_zero(tmp_path):
    """反向红证：口径换回 **Δ整盘已用** ⇒ 同一「prune 腾 2GB」夹具读数变 0（改前的假警形状）。"""
    injected = _inject(read_deploy(), "    _reclaimed_mb=$(( _cache_before_mb - _cache_after_mb ))",
                       "    _reclaimed_mb=$(( ${_used_before_mb:-0} - ${_used_after_mb:-0} ))")
    proc, _state, out = _run_deploy(tmp_path, df_seq="9000", cache_size="6839MB",
                                    env_extra={"STUB_PRUNE_FREED_MB": "2048"}, script_text=injected)
    assert "缓存回收量：0MB" in out, (
        "换回 Δ整盘已用后读数没变 0 ⇒ 口径判据没有判别力：\n"
        + "\n".join(l for l in out.splitlines() if "缓存回收量" in l)
    )
    assert "缓存回收量：2048MB" not in out


# ══════════════════════════════════════════════════════════════════════════
# 五、执行式红证：真跑 swas-deploy-ci.sh（桩 aliyun）—— 收口归因
# ══════════════════════════════════════════════════════════════════════════

ALIYUN_STUB = r"""#!/bin/bash
echo "$*" >> "$ALIYUN_LOG"
n=$(cat "$STATE_DIR/aliyun-calls" 2>/dev/null || echo 0)
n=$((n + 1)); echo "$n" > "$STATE_DIR/aliyun-calls"
case "$1 $2" in
  "help swas-open") echo "Usage: aliyun swas-open ..."; exit 0 ;;
  "version ") echo "aliyun-cli 3.0.0-stub"; exit 0 ;;
  "swas-open run-command")
    echo '{"InvokeId":"inv-1","RequestId":"req-1"}'; exit 0 ;;
  "swas-open describe-invocation-result")
    # 🔴 响应按**本子命令的第几次调用**回放，不是 CLI 的**全局**调用序号：
    #    全局序号把 `aliyun version` / `configure` / `plugin install` / `run-command` 一起算进去
    #    （实测第一次 describe 已经排到全局第 5 次）⇒ `aliyun-resp-1..N` **永远取不到**，
    #    每次都回落到 `-last` ⇒ 「第 1 次**中途**失败 + 回滚腿被同一闸门挡住」这类**有序**场景
    #    退化成「每次都读同一份」= 夹具没有建模现实（实测：回滚腿根本没被发起）。
    m=$(cat "$STATE_DIR/aliyun-describe-calls" 2>/dev/null || echo 0)
    m=$((m + 1)); echo "$m" > "$STATE_DIR/aliyun-describe-calls"
    f="$STATE_DIR/aliyun-resp-$m"
    [ -f "$f" ] || f="$STATE_DIR/aliyun-resp-last"
    cat "$f"; exit 0 ;;
esac
exit 0
"""


def _swas_resp(status: str, remote_text: str) -> str:
    import base64
    import json as _json
    payload = {
        "RequestId": "stub",
        "InvocationResult": {
            "InvocationStatus": status,
            "ExitCode": 0 if status == "Success" else 1,
            "Output": base64.b64encode(remote_text.encode("utf-8")).decode("ascii"),
        },
    }
    return _json.dumps(payload)


#: 逐字的**现场读数**（issue #6505）：两次远端输出都是同一道闸门
GATE_ABORT_REMOTE = (
    "== 1.4 C′ 服务器侧构建（admin-api，在 flock 之内；tag=sha-new）==\n"
    "  构建前磁盘可用：4045MB（门槛 4096MB）\n"
    "  ❌ 磁盘可用 4045MB < 门槛 4096MB ⇒ **中止构建**（旧容器保持不动、环境未受影响）\n"
    f"ABORT_REASON={ABORT_REASON}\n"
)
MIDWAY_FAILURE_REMOTE = (
    "== 2. 拉取镜像（tag=sha-new）==\n"
    "== 3. 健康检查 ==\n"
    "  ❌ admin-api 健康检查未通过（重试 10 次仍未就绪）\n"
    "PREV_GOOD_TAG=sha-old\n"
)


def _run_ci(tmp_path: Path, responses, *, script_text: str | None = None):
    """跑**真实** `swas-deploy-ci.sh`（桩 aliyun / curl / file / sudo / tar）。返回 (rc, out, summary, log)。"""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)
    text = rebase_tmp_paths(script_text if script_text is not None else read_ci(), sandbox)
    script = tmp_path / "swas-deploy-ci.sh"
    script.write_text(text, encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    # 假 aliyun 本体（CI 的安装块会把它 `sudo mv` 到 /usr/local/bin ⇒ 桩 sudo 变成 exec ⇒ 必须可执行）
    (sandbox / "aliyun").write_text(ALIYUN_STUB, encoding="utf-8")
    (sandbox / "aliyun").chmod(0o755)
    for i, r in enumerate(responses, start=1):
        (state / f"aliyun-resp-{i}").write_text(r, encoding="utf-8")
    (state / "aliyun-resp-last").write_text(responses[-1], encoding="utf-8")
    log = tmp_path / "aliyun.log"
    log.write_text("", encoding="utf-8")
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("aliyun", ALIYUN_STUB), ("curl", FAKE_CURL_STUB),
                       ("file", REAL_FILE_STUB),
                       ("sudo", "#!/bin/bash\nshift\nexec \"$@\"\n"),
                       ("tar", "#!/bin/bash\nexit 0\n")):
        _write_exe(bin_dir / name, body)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_STEP_SUMMARY": str(summary),
        "ALIYUN_LOG": str(log),
        "STATE_DIR": str(state),
        "SWAS_DEPLOY_TIMEOUT_SECONDS": "10",
        "SWAS_CLI_TIMEOUT_SECONDS": "3",
        "SWAS_POLL_INTERVAL_SECONDS": "1",
        "SWAS_RETRY_PAUSE_SECONDS": "0",
    }
    proc = subprocess.run(["bash", str(script), "i-stub", "cn-hangzhou", "ak", "sk", "u", "p", "sha-new"],
                          env=env, capture_output=True, text=True, timeout=180)
    return proc.returncode, proc.stdout + proc.stderr, summary.read_text(encoding="utf-8"), log.read_text(encoding="utf-8")


def _run_command_count(log: str) -> int:
    return sum(1 for ln in log.splitlines() if "run-command" in ln and "help" not in ln)


def test_ci_gate_abort_names_never_started_and_never_says_env_broken(tmp_path):
    """判据 9（红证核心）：注入「门槛抬到余量之上」⇒ 收口必须说「**未开始部署**」且**不出现**「环境可能坏」。

    双向对照（防「文案恒打印」）见下一条 `test_ci_midway_failure_still_says_env_may_be_broken`。
    """
    rc, out, summary, log = _run_ci(tmp_path, [
        _swas_resp("Failed", GATE_ABORT_REMOTE),
        _swas_resp("Failed", GATE_ABORT_REMOTE),
    ])
    blob = out + summary
    assert rc != 0, "部署没成功，退出码必须非零"
    assert "未开始部署" in blob, f"收口没有说「未开始部署」（issue #6505 的核心）：\n{blob[-2000:]}"
    assert "环境未受影响" in blob, f"收口没有说「环境未受影响」：\n{blob[-2000:]}"
    assert "环境可能处于坏状态" not in blob, (
        f"🔴 被前置闸门挡住却仍说「环境可能处于坏状态」（正是 issue #6505 的误导）：\n{blob[-2000:]}"
    )
    assert "立即人工介入" not in blob, "闸门中止不是「立即人工介入」的场景（出口是回收磁盘 / 扩容）"
    # 出口必须可行动
    assert "回收磁盘" in blob or "扩容" in blob, f"收口没有给出口：\n{blob[-2000:]}"
    # 回滚腿不许被计入「环境可能坏」的证据 ⇒ 只在**同一闸门**上时报「回滚也被同一闸门挡住」
    assert "自动回滚" not in blob or "同一闸门" in blob, (
        f"把回滚腿报成了独立故障（同一原因被读成两次失败）：\n{blob[-2000:]}"
    )


def test_ci_midway_failure_still_says_env_may_be_broken(tmp_path):
    """判据 11（**双向对照**）：部署**中途**失败（无标记）⇒ 仍必须说「环境可能处于坏状态，请人工介入」。

    没有这一条，「未开始部署」那句就可能变成恒打印的假文案。
    """
    rc, out, summary, log = _run_ci(tmp_path, [
        _swas_resp("Failed", MIDWAY_FAILURE_REMOTE),
        _swas_resp("Failed", MIDWAY_FAILURE_REMOTE),
        _swas_resp("Failed", MIDWAY_FAILURE_REMOTE),
    ])
    blob = out + summary
    assert rc != 0
    assert "环境可能处于坏状态" in blob, f"中途失败反而没有报「环境可能坏」：\n{blob[-2000:]}"
    assert "人工介入" in blob, f"中途失败没有要求人工介入：\n{blob[-2000:]}"
    assert "未开始部署" not in blob, "中途失败被说成「未开始部署」（归因反了）"
    assert "自动回滚" in blob, "中途失败仍然必须走「失败即回滚」"


def test_ci_rollback_leg_blocked_by_same_gate_is_not_evidence_of_damage(tmp_path):
    """判据 10：主部署**中途**失败 + 回滚腿被**同一闸门**挡住 ⇒ 不许把回滚计入「环境可能坏」。

    这一条与上一条**成对**：上一条证明「中途失败仍会报环境可能坏」，本条证明「回滚腿被同一闸门
    挡住时**不增加**任何关于环境健康的证据 —— 报告必须点名是同一道闸门」。
    """
    rc, out, summary, log = _run_ci(tmp_path, [
        _swas_resp("Failed", MIDWAY_FAILURE_REMOTE),
        _swas_resp("Failed", MIDWAY_FAILURE_REMOTE),
        _swas_resp("Failed", GATE_ABORT_REMOTE),
    ])
    blob = out + summary
    assert rc != 0
    # 🔴 夹具自证：三次尝试必须**真的按序发出去**（第 1/2 次部署 + 回滚腿）。没有这一条，
    #    「响应没按序回放 ⇒ 回滚腿根本没被发起」会让下面那条判据以「文案缺失」收场，
    #    掩盖夹具坏掉（实测：全局调用序号当索引时，回滚腿一次都没发）。
    assert _run_command_count(log) == 3, (
        f"夹具没有把三次尝试按序喂出去（第 1/2 次部署 + 回滚腿）：\n{log}"
    )
    assert "同一闸门" in blob or "被同一道闸门挡住" in blob, (
        f"回滚腿被同一闸门挡住却没有点名（读者会把它读成第二次独立故障）：\n{blob[-2000:]}"
    )
    # 主部署是中途中止 ⇒ 环境状态确实未知 ⇒ 保留人工介入，但必须把「回滚失败」的归因写对
    assert "环境可能处于坏状态" in blob, "主部署中途失败仍应提示人工介入"


def test_ci_gate_abort_red_proof_only_exit_code_branching(tmp_path):
    """反向红证（判别力自证）：把 CI 退回「只看 exit != 0」⇒ 同一次注入下必现误导文案。

    注入手法 = 把 CI 脚本里对标记的解析行**整段摘掉**（等价于改前形态：没有任何机读标记消费面）。
    """
    ci = read_ci()
    broken = ci.replace('REMOTE_ABORT_REASON=$(printf', 'REMOTE_ABORT_REASON_IGNORED=$(printf')
    assert broken != ci, "注入未生效（解析行不存在）"
    rc, out, summary, log = _run_ci(tmp_path, [
        _swas_resp("Failed", GATE_ABORT_REMOTE),
        _swas_resp("Failed", GATE_ABORT_REMOTE),
    ], script_text=broken)
    blob = out + summary
    assert rc != 0
    assert "未开始部署" not in blob, (
        "注入（摘掉标记消费）后仍打印「未开始部署」⇒ 该判据没有判别力（文案恒打印 / 空断言）"
    )
