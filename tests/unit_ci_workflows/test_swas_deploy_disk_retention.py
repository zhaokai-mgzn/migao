# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012，
#   见 .github/cases/misc.yml 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""`deploy/swas/deploy.sh` 的**磁盘保留策略 × 回滚点**守卫 —— issue #4808。

## 病根（**主会话实测**，非推断）

部署后那句 `docker image prune -f` **不带 `-a`** ⇒ 只清 dangling（无 tag）镜像 ⇒
带 tag 的 `sha-*` 旧镜像**永远不被清** ⇒ 每次部署堆积 ≈3.14GB
（admin-web 1.72G + ai-agent 1.12G + admin-api 0.30G，实测读数）⇒ 磁盘单调爬升；
到 >90% 才触发 `docker system prune -af --volumes`（深度清理）——**它会把带 tag 的也删**，
包括 `.last-good-tag` 指向的那一套 ⇒ **#4767 的「失败即回滚」在深度清理之后就没有回滚点了**
✗✗，而且**是静默的**（日志里只有一行「清理后磁盘: N%」）。

## 本文件锁什么

1. **静态判据**（读脚本**当前文本**，不读可变引用 —— 见技能 §18.3）：
   部署后的清理必须走**保留策略**（保留「当前在用 + `.last-good-tag` + 最近 N 个」），
   清理只按**本项目命名空间前缀**筛；回滚点有**两道**保护（保留集 + 删除循环里一条**不看保留集**
   的独立护栏）且清理后**事后自检**告警；磁盘水位与回滚点**完整度**每次部署都报；
   深度清理段必须先记回滚点、清理后复核并补回；
   **未削弱 #4785（蓝绿化）与 #4767（硬超时/输出解码/失败即回滚）**。
2. **注入式红证**：每条判据各自可独立判红，且注入必须真的落到文本上（否则显式失败）。
3. **执行式红证**（桩 `docker` / `curl` / `flock` / `timeout` / `df`，跑**真实** `deploy.sh`
   的**真实码路**）：
   - 🔴 改前形态（`docker image prune -f` + 深度清理不补回）⇒ 注入「磁盘 95%」⇒
     **回滚点被深度清理删掉且没人补回**；
   - ✅ 改后形态 ⇒ 同一次注入下**回滚点仍在**（被复核 + 补回）；
   - 保留策略真的删旧、真的留回滚点与最近 N 个；**非本项目镜像（nginx:alpine）一根毫毛都不动**；
   - **保留集被算空**（模拟 `retained_tags` 缺陷）⇒ 独立护栏仍保住回滚点；**拆掉护栏**后
     同一次注入下回滚点必然消失（证明这条断言非恒真）；
   - 回滚点缺失/只剩部分服务 ⇒ `::warning::` 显式告警（不静默）。

## 「深度清理会删回滚点」的**触发窗口**（照实登记，不是推断）

回滚点（`.last-good-tag`）**通常**等于正在运行的那一套（CI 在 `deploy.sh` rc=0 之后才写它），
此时 `docker system prune -af` 因容器仍引用而不动它。**危险窗口 = 上一次部署失败之后**：
#4785 蓝绿失败时容器已被换成**新** tag（running 指向失败 tag），而 `.last-good-tag` 仍是
上一个可用 tag ⇒ 该镜像**无容器引用**；而失败部署本身会推高磁盘（重复 pull）⇒ 下一次部署
1.9 段（`>90%` 深度清理）恰好在这个窗口里跑 ⇒ **回滚点被删，且旧脚本一个字都不说** ——
**这正是最需要回滚点的时刻**。执行式红证里 `running_tag="sha-new"` 而 `.last-good-tag=sha-old`
复现的就是这个状态。

## ⚠️ 红证的真实性边界（**照实登记，不粉饰**）

执行式红证跑的是**本机 + 桩化的外部依赖**（docker / curl / flock / timeout / df），
**不是**真实 SWAS 环境实测 —— 桩化的是「外部依赖」，被测的是 `deploy.sh` 的**清理与回滚编排本身**。
真机读数（2026-09-21 只读探针，`aliyun swas-open run-command`）已登记在 issue #4808 与 PR 描述里；
**本 PR 未做真实远端部署验证**（部署脚本 ⇒ 保持 draft 由人放行）。
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

PROJECT = "crpi-qdcgkzwx9p9zckga.cn-hangzhou.personal.cr.aliyuncs.com/ai-customer-service"
SERVICES = ("admin-api", "ai-agent-service", "admin-web")
FOREIGN_IMAGE = "nginx:alpine"

# 改前形态的清理段（**逐字内联**，取自本 PR 之前的脚本；内联而不是 `git show origin/main:…`
# —— 后者会随合并变成「修复后」文本 ⇒ 判据自红，技能 §18.3）
OLD_CLEANUP_SNIPPET = (
    "# 磁盘自愈：清理悬空/过期镜像（#2571 复现防护：旧镜像堆积曾导致磁盘 100% 部署失败）\n"
    "# 只清 <none> 悬空镜像与未被容器引用的旧版本，运行中镜像不受影响\n"
    'docker image prune -f || echo "⚠️ docker image prune 失败（不影响本次部署）"\n'
    "# 额外水位告警：磁盘 >85% 时明确提示，便于及时介入\n"
    'DISK_PCT=$(df / | awk \'NR==2 {gsub("%","",$5); print $5}\')\n'
    'if [ "${DISK_PCT:-0}" -gt 85 ]; then\n'
    '  echo "⚠️ 磁盘水位 ${DISK_PCT}% > 85%，建议清理（docker image prune -a / 扩容）"\n'
    "fi\n"
)

# 改前形态的**深度清理段**（同样**逐字内联**，取自本 PR 之前的脚本 `git show HEAD:deploy/swas/deploy.sh`）：
# 它直接 prune，**不记、不复核、也不补回**回滚点 ⇒ 回滚点在这一步静默消失。
OLD_DEEP_CLEAN_BRANCH = (
    'if [ "${DISK_PCT:-0}" -gt 90 ]; then\n'
    '  echo "  ⚠️ 磁盘水位 ${DISK_PCT}% > 90%，先深度清理再继续部署"\n'
    "  docker system prune -af --volumes 2>/dev/null || docker system prune -af 2>/dev/null || true\n"
    "  journalctl --vacuum-size=50M >/dev/null 2>&1 || true\n"
    "  DISK_PCT2=$(df / | awk 'NR==2 {gsub(\"%\",\"\",$5); print $5}')\n"
    '  echo "  清理后磁盘: ${DISK_PCT2}%（原 ${DISK_PCT}%）"\n'
    '  if [ "${DISK_PCT2:-0}" -gt 95 ]; then\n'
    '    echo "  ❌ 深度清理后磁盘仍 >95%（${DISK_PCT2}%），中止部署避免故障"\n'
    "    echo \"   人工介入：ssh 服务器排查大文件（du -xhd1 / | sort -rh | head）\"\n"
    "    exit 1\n"
    "  fi\n"
)


# ══════════════════════════════════════════════════════════════════════════
# 读源 + 反空跑锚点
# ══════════════════════════════════════════════════════════════════════════

def read_deploy_sh() -> str:
    assert DEPLOY_SH.is_file(), f"反空跑锚点：目标脚本不存在 → {DEPLOY_SH}"
    text = DEPLOY_SH.read_text(encoding="utf-8")
    assert "2.7 镜像保留策略清理" in text, (
        "反空跑锚点：deploy.sh 里找不到保留策略清理段（判据已过期或脚本被改写）—— 这不是「通过」"
    )
    return text


def non_comment(text: str) -> str:
    """剥掉**整行注释**后的代码行 —— 判据只判「真的会执行的那一行」（注释里刻意引用了旧写法）。"""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _inject(text: str, old: str, new: str) -> str:
    """替换注入；**没替换到 ⇒ 显式失败**（否则「注入式红证」是空跑）。"""
    assert old in text, f"注入锚点不存在（判据已过期）：{old[:70]!r}"
    out = text.replace(old, new, 1)
    assert out != text, "注入没有改变文本（空跑）"
    return out


# ══════════════════════════════════════════════════════════════════════════
# 判据本体（纯函数：文本进 → 违规清单出；注入式红证驱动**同一份本体**）
# ══════════════════════════════════════════════════════════════════════════

def judge_retention_replaces_dangling_only_prune(text: str) -> list:
    """① 部署后的清理必须是**保留策略**，不能只是「清 dangling」那一句。"""
    v = []
    code = non_comment(text)
    if "cleanup_project_images" not in code:
        v.append("部署后清理没有走保留策略（找不到 `cleanup_project_images` 调用）")
    if "retained_tags" not in code:
        v.append("找不到保留集计算 `retained_tags`（保留策略没有判据来源）")
    if "docker image prune -a" in code:
        v.append("代码里出现 `docker image prune -a`（不带保留集 ⇒ 会连带删掉回滚点）")
    # 保留策略必须真的调用（不只是定义）
    if not re.search(r"^\s*cleanup_project_images \"", code, re.M):
        v.append("`cleanup_project_images` 只定义未调用（保留策略没有生效）")
    return v


def judge_rollback_point_protected(text: str) -> list:
    """② 回滚点**只许保留**（两道独立防线 + 事后自检）：

    ① 它在保留集里（`retained_tags "$TAG" "$PREV_GOOD"`）；
    ② 删除循环里另有一条**不看 `$keep_file`** 的独立护栏 ⇒ 保留集算空也删不掉它；
    ③ 清理后**事后自检**（清理前完整 / 清理后不完整 ⇒ `::warning::`），不许静默。
    """
    v = []
    if 'retained_tags "$TAG" "$PREV_GOOD"' not in text:
        v.append("保留集没有把 `.last-good-tag`（`$PREV_GOOD`）算进去")
    if "rollback_tag()" not in text:
        v.append("找不到 `rollback_tag()`（回滚点的唯一读取口径）")
    if "LAST_GOOD_FILE" not in text:
        v.append("找不到 `LAST_GOOD_FILE`（回滚点文件路径没有变量化 ⇒ 测试不可注入）")
    # ② 独立护栏：删除循环里必须有一条不看 keep_file 的回滚点豁免，且真的 `continue` 跳过删除
    m = re.search(r"^cleanup_project_images\(\) \{(.*?)\n\}", text, re.S | re.M)
    if not m:
        v.append("找不到 `cleanup_project_images()`（清理没有单一入口）")
    else:
        guard = re.search(r'if \[ -n "\$prev" \] && \[ "\$tag" = "\$prev" \]; then(.*?)fi', m.group(1), re.S)
        if not guard:
            v.append("删除循环里没有「回滚点永不删」的独立护栏（保留集算错时会静默删掉回滚点）")
        elif "continue" not in guard.group(1):
            v.append("回滚点护栏没有 `continue`（拦住了却没跳过删除）")
    # ③ 事后自检：清理吃掉回滚点必须告警
    if "::warning::保留策略清理后回滚点" not in text:
        v.append("清理后没有回滚点事后自检告警（静默失去回滚能力 = 本单要治的形态）")
    if "report_rollback_point" not in text:
        v.append("找不到 `report_rollback_point`（回滚点是否还在没有可观测出口）")
    return v


def judge_only_own_project_images(text: str) -> list:
    """③ 清理**只按本项目命名空间前缀**筛 ⇒ 不可能误删非本项目镜像。"""
    v = []
    if "PROJECT_IMAGE_PREFIX=${PROJECT_IMAGE_PREFIX:-ai-customer-service/}" not in text:
        v.append("找不到本项目命名空间前缀默认值（`ai-customer-service/`）—— 前缀漂移会误删别人镜像")
    m = re.search(r"^project_images\(\) \{(.*?)\n\}", text, re.S | re.M)
    if not m:
        v.append("找不到 `project_images()`（清理候选集没有单一来源）")
    elif 'grep -F "$PROJECT_IMAGE_PREFIX"' not in m.group(1):
        v.append("`project_images()` 没有按 `$PROJECT_IMAGE_PREFIX` 过滤（会列出别人的镜像）")
    if "docker system prune -af" in non_comment(text) and "docker system prune -af" not in text:
        v.append("深度清理命令形态异常")
    return v


def judge_observability(text: str) -> list:
    """④ 磁盘水位**与**回滚点存在性都要可观测/可告警（不是只在 >90% 说一句）。"""
    v = []
    if "DISK_WARN_PCT=${DISK_WARN_PCT:-" not in text:
        v.append("找不到磁盘水位告警阈值（`DISK_WARN_PCT`）")
    if text.count("::warning::") < 3:
        v.append(f"`::warning::` 出口只有 {text.count('::warning::')} 处（水位 / 回滚点 / 补回失败 至少要 3 处）")
    if "清理后磁盘水位" not in text:
        v.append("部署后没有报「清理后磁盘水位」")
    # 水位告警必须在**常规路径**（不只是 >90% 的分支里）
    m = re.search(r"if \[ \"\$\{DISK_PCT:-0\}\" -gt \"\$DISK_WARN_PCT\" \]; then(.*?)\nfi\n", text, re.S)
    if not m:
        v.append("找不到常规路径的磁盘水位告警分支")
    return v


def judge_deep_clean_restores_rollback_point(text: str) -> list:
    """⑤ 深度清理（`system prune -af`）必须先记回滚点、清理后复核并**补回**。"""
    v = []
    m = re.search(r"if \[ \"\$\{DISK_PCT:-0\}\" -gt 90 \]; then(.*?)\nelse\n", text, re.S)
    if not m:
        v.append("找不到磁盘 >90% 的深度清理分支")
        return v
    blk = non_comment(m.group(1))   # 注释里刻意引用了该命令（说明文字）⇒ 位置比较只判代码行
    i_rb = blk.find("RB_BEFORE=$(rollback_tag)")
    i_prune = blk.find("docker system prune -af")
    if i_rb < 0:
        v.append("深度清理前没有记下回滚点（`RB_BEFORE=$(rollback_tag)`）⇒ 无法复核")
    if i_prune < 0:
        v.append("深度清理分支里找不到 `docker system prune -af`（判据已过期）")
    if i_rb >= 0 and i_prune >= 0 and i_rb > i_prune:
        v.append("回滚点是在**深度清理之后**才记的 —— 那时镜像已经没了")
    if "rollback_point_present" not in blk:
        v.append("深度清理后没有复核回滚点（`rollback_point_present`）")
    if "docker compose pull" not in blk:
        v.append("深度清理把回滚点删了却没有补回（`docker compose pull`）")
    if "::warning::" not in blk:
        v.append("补回失败时没有 `::warning::` 告警（静默失去回滚能力）")
    return v


def judge_no_regression_of_4785_and_4767(text: str) -> list:
    """⑥ 未削弱 #4785（蓝绿化）与 #4767（失败即回滚）—— 逐条锚点在改动后必须仍在。"""
    v = []
    for token, why in (
        ("== 2.5 严格蓝绿预验证", "#4785 的蓝绿段"),
        ('if ! wait_healthy "$GPORT" "$GREEN" "$GPATH"; then', "#4785 的 green 健康检查"),
        ('docker compose up -d --no-deps "$svc"', "#4785 的正式容器替换点"),
        ("BG_OFF_FILE", "#4785 的应急开关"),
        ("MemAvailable", "#4785 的内存预检"),
        ("跳过蓝绿预验证", "#4785 的应急开关提示"),
        ("docker compose exec -T nginx nginx -s reload || docker compose restart nginx", "#4785 的 nginx 优雅重载"),
        ("wait_healthy() {", "#4785 的唯一健康检查判据"),
        ("HC_RETRIES=${HC_RETRIES:-10}", "#4785 的健康检查重试预算"),
        ("flock -w 600 9", "整脚本 flock"),
        ("旧容器保持不动", "#4785 的失败路径提示语"),
        ("交给 CI 侧 #4767 的「失败即回滚」", "#4767 的回滚兜底接线"),
        ("docker image prune -f", "#4767 之前的 dangling 兜底清理（保留策略之外仍需清 dangling）"),
    ):
        if token not in text:
            v.append(f"{why} 被削弱/删除：找不到 `{token[:60]}`")
    if text.count("wait_healthy() {") != 1:
        v.append("健康检查判据不再唯一一份（两份判据会漂移）")
    return v


def all_violations(text: str) -> list:
    return (
        judge_retention_replaces_dangling_only_prune(text)
        + judge_rollback_point_protected(text)
        + judge_only_own_project_images(text)
        + judge_observability(text)
        + judge_deep_clean_restores_rollback_point(text)
        + judge_no_regression_of_4785_and_4767(text)
    )


# ══════════════════════════════════════════════════════════════════════════
# 一、静态判据（读脚本当前文本）
# ══════════════════════════════════════════════════════════════════════════

def test_real_script_satisfies_every_judgement():
    text = read_deploy_sh()
    v = all_violations(text)
    assert not v, "保留策略/回滚点判据未满足：\n- " + "\n- ".join(v)


@pytest.mark.parametrize("judge_name", [
    "judge_retention_replaces_dangling_only_prune",
    "judge_rollback_point_protected",
    "judge_only_own_project_images",
    "judge_observability",
    "judge_deep_clean_restores_rollback_point",
    "judge_no_regression_of_4785_and_4767",
])
def test_each_judge_is_clean_on_the_real_script(judge_name):
    """逐条判据在真实脚本上必须各自干净（避免一条判据恒红被「整体红」掩盖）。"""
    v = globals()[judge_name](read_deploy_sh())
    assert not v, f"{judge_name} 判红：\n- " + "\n- ".join(v)


def test_project_prefix_matches_compose_image_namespace():
    """前缀默认值必须与 `deploy/swas/docker-compose.yml` 的镜像命名空间一致（防漂移）。"""
    compose = (REPO_ROOT / "deploy" / "swas" / "docker-compose.yml").read_text(encoding="utf-8")
    for svc in ("admin-api", "ai-agent-service", "admin-web"):
        assert f"/ai-customer-service/{svc}:" in compose, f"compose 里找不到 {svc} 的镜像命名空间"
    assert "PROJECT_IMAGE_PREFIX=${PROJECT_IMAGE_PREFIX:-ai-customer-service/}" in read_deploy_sh()


# ══════════════════════════════════════════════════════════════════════════
# 二、注入式红证（每条判据各自可独立判红）
# ══════════════════════════════════════════════════════════════════════════

def test_injection_back_to_dangling_only_prune_goes_red():
    """注入①：把保留策略段换回旧的「只清 dangling」⇒ 判据必红。"""
    text = read_deploy_sh()
    i = text.find("echo \"== 2.7 镜像保留策略清理")
    j = text.find('echo "== 3. 健康检查')
    assert 0 < i < j, "反空跑锚点：保留策略段边界定位失败"
    injected = text[:i] + OLD_CLEANUP_SNIPPET + text[j:]
    assert judge_retention_replaces_dangling_only_prune(injected), "换回旧清理后没红（判据无判别力）"


def test_injection_drop_rollback_from_retain_set_goes_red():
    """注入②：保留集里去掉回滚点 ⇒ 必红（回滚点会被当旧镜像删掉）。"""
    injected = _inject(
        read_deploy_sh(),
        'retained_tags "$TAG" "$PREV_GOOD" "$KEEP_RECENT_TAGS" > "$KEEP_FILE"',
        'retained_tags "$TAG" "" "$KEEP_RECENT_TAGS" > "$KEEP_FILE"',
    )
    assert judge_rollback_point_protected(injected), "去掉回滚点后没红（判据无判别力）"


def test_injection_silent_rollback_loss_goes_red():
    """注入③：拆掉独立护栏 / 把事后自检告警改成静默 ⇒ 必红。"""
    text = read_deploy_sh()
    no_guard = _inject(text, 'if [ -n "$prev" ] && [ "$tag" = "$prev" ]; then', "if false; then")
    assert judge_rollback_point_protected(no_guard), "拆掉回滚点护栏后没红（判据无判别力）"
    silent = _inject(
        text,
        '  echo "  ::warning::保留策略清理后回滚点',
        '  echo "  ℹ️ 保留策略清理后回滚点',
    )
    assert judge_rollback_point_protected(silent), "去掉事后自检告警后没红（判据无判别力）"


def test_injection_unfiltered_image_list_goes_red():
    """注入④：`project_images()` 去掉命名空间过滤 ⇒ 必红（会误删非本项目镜像）。"""
    injected = _inject(
        read_deploy_sh(),
        '    | grep -F "$PROJECT_IMAGE_PREFIX" || true',
        '    | cat || true',
    )
    assert judge_only_own_project_images(injected), "去掉前缀过滤后没红（判据无判别力）"


def test_injection_drop_deep_clean_restore_goes_red():
    """注入⑤：深度清理后不再复核/补回回滚点 ⇒ 必红（= 本单要治的静默形态）。"""
    text = read_deploy_sh()
    i = text.find("  if [ -n \"$RB_BEFORE\" ]; then")
    j = text.find('  if [ "${DISK_PCT2:-0}" -gt 95 ]; then')
    assert 0 < i < j, "反空跑锚点：深度清理复核段边界定位失败"
    injected = text[:i] + text[j:]
    assert judge_deep_clean_restores_rollback_point(injected), "去掉复核/补回后没红（判据无判别力）"


def test_injection_weaken_blue_green_goes_red():
    """注入⑥：削弱 #4785（删掉 green 健康检查）⇒ 必红（证明本守卫会拦回归）。"""
    injected = _inject(
        read_deploy_sh(),
        'if ! wait_healthy "$GPORT" "$GREEN" "$GPATH"; then',
        "if false; then",
    )
    assert judge_no_regression_of_4785_and_4767(injected), "削弱蓝绿后没红（判据无判别力）"


# ══════════════════════════════════════════════════════════════════════════
# 三、执行式红证（桩外部依赖，跑真实 deploy.sh 的真实码路）
# ══════════════════════════════════════════════════════════════════════════

CURL_STUB = """#!/bin/bash
# 桩 curl：① codeload 源码包 → 把预置 tar 拷过去；② 健康检查 → 恒 200
out=""; url=""; fmt=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w) fmt="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in
  *codeload.github.com*) cp "$STUB_TAR" "$out"; exit 0 ;;
esac
if [ -n "$out" ]; then : > "$out"; fi
if [ -n "$fmt" ]; then printf '%s' "${HC_CODE:-200}"; fi
exit 0
"""

# 桩 docker：维护 `$STATE/images`（`repo:tag` 逐行）+ 记录调用日志。
#   · `image prune -f`（旧写法）⇒ **只删无 tag 的 dangling**，带 tag 的一个都不动（这正是病根）
#   · `system prune -af`  ⇒ 删掉**未被运行容器占用**的镜像（= 深度清理，回滚点也删）
#   · `image rm <ref>`    ⇒ 真的从状态里删掉
#   · `image inspect`     ⇒ 存在 = 0，不存在 = 1
DOCKER_STUB = """#!/bin/bash
log() { echo "docker $*" >> "$DOCKER_LOG"; }
images() { cat "$STATE/images" 2>/dev/null || true; }
running() { cat "$STATE/running" 2>/dev/null || true; }
case "$*" in
  "images --format "*)
    images
    exit 0 ;;
  "image inspect "*)
    ref=$3
    if images | grep -qxF "$ref"; then exit 0; else exit 1; fi ;;
  "image rm "*)
    ref=$3
    if images | grep -qxF "$ref"; then
      grep -vxF "$ref" "$STATE/images" > "$STATE/images.tmp" || true
      mv "$STATE/images.tmp" "$STATE/images"
      echo "removed $ref" >> "$STATE/removed"
      exit 0
    fi
    exit 1 ;;
  "image prune -f"|"image prune -f "*)
    grep ':<none>' "$STATE/images" > "$STATE/pruned" 2>/dev/null || true
    grep -v ':<none>' "$STATE/images" > "$STATE/images.tmp" || true
    mv "$STATE/images.tmp" "$STATE/images"
    exit 0 ;;
  "system prune -af"*)
    : > "$STATE/deep-pruned"
    keep=$(running)
    : > "$STATE/images.tmp"
    while IFS= read -r img; do
      [ -n "$img" ] || continue
      if printf '%s\\n' "$keep" | grep -qxF "$img"; then echo "$img" >> "$STATE/images.tmp"; fi
    done < "$STATE/images"
    mv "$STATE/images.tmp" "$STATE/images"
    exit 0 ;;
  "login "*)
    # `docker login --password-stdin`：必须**消费 stdin**，否则上游 `echo` 吃 SIGPIPE
    # （pipefail ⇒ 整条管道非零 ⇒ set -e 误杀）
    cat >/dev/null 2>&1 || true
    exit 0 ;;
  "compose pull "*)
    svc=${3}
    if [ -n "${STUB_PULL_FAIL_TAG:-}" ] && [ "$IMAGE_TAG" = "$STUB_PULL_FAIL_TAG" ]; then exit 1; fi
    echo "${PROJECT_PREFIX}/${svc}:${IMAGE_TAG}" >> "$STATE/images"
    sort -u "$STATE/images" -o "$STATE/images"
    echo "pulled ${svc}:${IMAGE_TAG}" >> "$STATE/pulls"
    exit 0 ;;
esac
log "$@"
exit 0
"""

FLOCK_STUB = "#!/bin/bash\nexit 0\n"
TIMEOUT_STUB = "#!/bin/bash\nshift\nexec \"$@\"\n"

# 桩 df：第 1 次回 `$DF_FIRST`（用于注入「部署前 >90%」），之后回 `$DF_REST`。
# 也支持 `DF_SEQ`（逗号序列，**超出长度回落最后一个**）—— 用于精确注入「清理后 OK、补回后 >95%」。
# ⚠️ 必须输出**两行**（表头 + 数据行）—— 被测脚本用 `awk 'NR==2 …$5'` 取百分比，
# 只回一行的话取到的是空串（判据会退化成「恒真」）。
DF_STUB = """#!/bin/bash
n=$(cat "$STATE/df-calls" 2>/dev/null || echo 0)
n=$((n + 1)); echo "$n" > "$STATE/df-calls"
if [ -n "${DF_SEQ:-}" ]; then
  pct=$(printf '%s' "$DF_SEQ" | cut -d, -f"$n")
  if [ -z "$pct" ]; then pct=$(printf '%s' "$DF_SEQ" | awk -F, '{print $NF}'); fi
elif [ "$n" -le 1 ]; then pct="${DF_FIRST:-76}"; else pct="${DF_REST:-76}"; fi
echo "Filesystem      Size  Used Avail Use% Mounted on"
echo "/dev/vda3        40G   29G  9.2G  ${pct}% /"
"""


def _write_exe(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _make_src_tar(dest: Path) -> None:
    stage = dest.parent / "stage" / "migao-main" / "deploy" / "swas"
    stage.mkdir(parents=True, exist_ok=True)
    for name in ("docker-compose.yml", "docker-compose.bluegreen.yml", "nginx.conf"):
        shutil.copy(REPO_ROOT / "deploy" / "swas" / name, stage / name)
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(dest.parent / "stage" / "migao-main", arcname="migao-main")


def _project_ref(svc: str, tag: str) -> str:
    return f"{PROJECT}/{svc}:{tag}"


def _seed_images(*, tags, running_tag, foreign=FOREIGN_IMAGE) -> str:
    lines = [foreign]
    for tag in tags:
        for svc in SERVICES:
            lines.append(_project_ref(svc, tag))
    return "\n".join(lines) + "\n"


def _run(tmp_path: Path, script_text: str, *, images: str, running_tag: str,
         df_first: str = "76", df_rest: str = "76", extra_env: dict | None = None):
    """跑真实 `deploy.sh`（桩 docker/curl/flock/timeout/df）。返回 (proc, docker_log, state)。"""
    work = tmp_path / "opt-migao-deploy"
    work.mkdir(exist_ok=True)
    text = script_text
    # 绝对路径改写（只改**路径**，不改逻辑；同 test_swas_deploy_blue_green.py 的既有手法）
    text = text.replace("/opt/migao-deploy", str(work))
    text = text.replace("/tmp/migao-deploy.lock", str(work / "deploy.lock"))
    text = text.replace("/tmp/hc_", f"{work}/hc_")
    script = work / "deploy.sh"
    script.write_text(text, encoding="utf-8")
    (work / ".env.admin-api").write_text("SMS_BYPASS_CODE=123456\n", encoding="utf-8")
    (work / ".env.ai-agent").write_text("SMS_BYPASS_CODE=123456\n", encoding="utf-8")
    (work / ".env.registry").write_text("ACR_USERNAME=u\nACR_PASSWORD=p\n", encoding="utf-8")
    tar_path = tmp_path / "src.tar.gz"
    _make_src_tar(tar_path)
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    (state / "images").write_text(images, encoding="utf-8")
    (state / "running").write_text(
        "\n".join(_project_ref(svc, running_tag) for svc in SERVICES) + f"\n{PROJECT}/admin-web:{running_tag}\n",
        encoding="utf-8",
    )
    (state / "pulls").write_text("", encoding="utf-8")
    (state / "removed").write_text("", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_exe(bin_dir / "curl", CURL_STUB)
    _write_exe(bin_dir / "docker", DOCKER_STUB)
    _write_exe(bin_dir / "flock", FLOCK_STUB)
    _write_exe(bin_dir / "timeout", TIMEOUT_STUB)
    _write_exe(bin_dir / "df", DF_STUB)
    docker_log = tmp_path / "docker.log"
    docker_log.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DOCKER_LOG": str(docker_log),
        "STATE": str(state),
        "STUB_TAR": str(tar_path),
        "PROJECT_PREFIX": PROJECT,
        "HC_RETRIES": "2",
        "HC_INTERVAL_SECONDS": "0",
        "BG_MEM_NEED_MB": "0",
        "BG_OFF_FILE": str(work / ".blue-green-off"),
        "LAST_GOOD_FILE": str(work / ".last-good-tag"),
        "DF_FIRST": df_first,
        "DF_REST": df_rest,
        **(extra_env or {}),
    }
    proc = subprocess.run(
        ["bash", str(script), "sha-new"], cwd=str(work), env=env,
        capture_output=True, text=True, errors="replace", timeout=300,
    )
    return proc, docker_log.read_text(encoding="utf-8"), state


def _final_images(state: Path) -> set:
    return {ln for ln in (state / "images").read_text(encoding="utf-8").splitlines() if ln.strip()}


# ── 3.1 保留策略：真的删旧、真的留回滚点与最近 N 个、不碰非本项目镜像 ──────────

def test_exec_retention_keeps_current_rollback_and_recent(tmp_path):
    """✅ 正向：`.last-good-tag=sha-old`，本地有 old/prev/other 三代 ⇒
    只留 {当前 new, 回滚点 old, 最近 1 个 prev}，删掉 other。"""
    work_probe = tmp_path / "opt-migao-deploy"
    work_probe.mkdir(exist_ok=True)
    (work_probe / ".last-good-tag").write_text("sha-old\n", encoding="utf-8")
    proc, log, state = _run(
        tmp_path,
        read_deploy_sh(),
        images=_seed_images(tags=["sha-old", "sha-prev", "sha-other"], running_tag="sha-old"),
        running_tag="sha-old",
    )
    assert proc.returncode == 0, f"部署没成功：\n{proc.stdout}\n{proc.stderr}"
    final = _final_images(state)
    assert _project_ref("admin-api", "sha-new") in final, "当前在用的镜像被删了（部署当场自毁）"
    assert _project_ref("admin-api", "sha-old") in final, "🔴 回滚点（.last-good-tag）被清掉了"
    assert _project_ref("ai-agent-service", "sha-old") in final, "🔴 回滚点（ai-agent）被清掉了"
    assert FOREIGN_IMAGE in final, "🔴 非本项目镜像（nginx:alpine）被误删了"
    assert not any("sha-other" in x for x in final), f"保留策略没有删掉旧镜像：{sorted(final)}"
    # 「最近 N 个」的语义：`tail -n 1` 取排序后最后一个 ⇒ 保留 sha-prev（不是 sha-other）
    assert _project_ref("admin-api", "sha-prev") in final, (
        f"保留集里的「最近 1 个」没被保留：{sorted(final)}"
    )
    assert "保留策略" in proc.stdout, proc.stdout
    assert "🛡️  保留回滚点 sha-old" in proc.stdout, proc.stdout
    assert "回滚点 tag=sha-old：本项目 3/3 个服务镜像都在本地" in proc.stdout, proc.stdout


def test_exec_retention_keeps_recent_n(tmp_path):
    """保留集里「最近 N 个」生效：KEEP_RECENT_TAGS=2 ⇒ old + new + 最近 2 个。"""
    work_probe = tmp_path / "opt-migao-deploy"
    work_probe.mkdir(exist_ok=True)
    (work_probe / ".last-good-tag").write_text("sha-old\n", encoding="utf-8")
    proc, log, state = _run(
        tmp_path,
        read_deploy_sh().replace("KEEP_RECENT_TAGS=${KEEP_RECENT_TAGS:-1}", "KEEP_RECENT_TAGS=${KEEP_RECENT_TAGS:-2}"),
        images=_seed_images(tags=["sha-a1", "sha-a2", "sha-a3", "sha-old"], running_tag="sha-old"),
        running_tag="sha-old",
    )
    assert proc.returncode == 0, proc.stdout
    final = _final_images(state)
    kept_tags = {x.rsplit(":", 1)[1] for x in final if "ai-customer-service/" in x}
    assert "sha-old" in kept_tags, f"回滚点被删：{sorted(kept_tags)}"
    assert "sha-new" in kept_tags, f"当前在用被删：{sorted(kept_tags)}"
    assert len(kept_tags) == 4, (
        f"KEEP_RECENT_TAGS=2 ⇒ 保留集 = 当前 + 回滚点 + 最近 2 个 = 4 个 tag，实际 {sorted(kept_tags)}"
    )
    assert "sha-a3" in kept_tags and "sha-a2" in kept_tags, f"最近 N 个没保留：{sorted(kept_tags)}"
    assert "sha-a1" not in kept_tags, f"超出 N 的旧镜像没删：{sorted(kept_tags)}"


def test_exec_no_rollback_marker_deletes_only_old(tmp_path):
    """`.last-good-tag` 不存在（本改动上线前/首次部署）⇒ 只留当前 + 最近 N 个，且不报错。"""
    proc, log, state = _run(
        tmp_path,
        read_deploy_sh(),
        images=_seed_images(tags=["sha-1", "sha-2"], running_tag="sha-1"),
        running_tag="sha-1",
    )
    assert proc.returncode == 0, proc.stdout
    final = _final_images(state)
    assert _project_ref("admin-api", "sha-new") in final
    assert FOREIGN_IMAGE in final
    assert "回滚点：" in proc.stdout and ".last-good-tag 为空" in proc.stdout, proc.stdout


# ── 3.2 🔴 红证：注入「镜像堆积到 90%+」⇒ 深度清理与回滚点 ────────────────────

def test_exec_deep_clean_deletes_rollback_point_then_restores_it(tmp_path):
    """🔴 红证（issue #4808 验收判据）：**注入磁盘 95% ⇒ 深度清理**。

    断言链（每一步都真的发生，不是恒真判据）：
      ① 桩里确实跑过 `docker system prune -af`（`deep-pruned` 标记）；
      ② 深度清理**确实**删掉了回滚点 `sha-old` 的镜像（这就是「改前」的机理）；
      ③ 改后的脚本**复核到它没了**、**真的重新 pull 了 3 个服务**（`pulls` 文件）；
      ④ 最终回滚点 `sha-old` **仍在**，且日志里明确说「已补回」。
    """
    work_probe = tmp_path / "opt-migao-deploy"
    work_probe.mkdir(exist_ok=True)
    (work_probe / ".last-good-tag").write_text("sha-old\n", encoding="utf-8")
    proc, log, state = _run(
        tmp_path,
        read_deploy_sh(),
        images=_seed_images(tags=["sha-old"], running_tag="sha-new"),
        running_tag="sha-new",     # 回滚点**不是**运行中的那一套 ⇒ 深度清理会删它
        df_first="95",             # 注入：部署前磁盘 95% ⇒ 触发深度清理
        df_rest="70",
    )
    assert proc.returncode == 0, f"部署没成功：\n{proc.stdout}\n{proc.stderr}"
    assert (state / "deep-pruned").is_file(), "深度清理根本没跑（注入没生效 ⇒ 红证是空跑）"
    pulls = (state / "pulls").read_text(encoding="utf-8")
    assert pulls.count(":sha-old") == 3, (
        f"回滚点被深度清理删掉后没有补回 3 个服务（实际 pulls={pulls!r}）"
    )
    final = _final_images(state)
    assert _project_ref("admin-api", "sha-old") in final, "🔴 回滚点在深度清理之后仍然缺失"
    assert "深度清理把回滚点 tag=sha-old 删了" in proc.stdout, proc.stdout
    assert "回滚点 tag=sha-old 已补回" in proc.stdout, proc.stdout
    # 🔴 顺序可辨（issue #4808 复审要求）：**清理已完成 ⇒ 空间已释放 ⇒ 现在才补回**
    assert "补回顺序：深度清理**已完成**" in proc.stdout, proc.stdout
    assert proc.stdout.index("清理后磁盘: ") < proc.stdout.index("补回顺序：深度清理**已完成**"), (
        "补回发生在「清理后水位」之前 ⇒ 补回的 3.14GB 会叠在 >90% 的水位上（顺序反了）"
    )
    # 补回**真的花了多少空间** + 补回后水位，都要进日志
    assert "补回回滚点占用空间：" in proc.stdout, proc.stdout
    assert "补回后磁盘水位：" in proc.stdout, proc.stdout


def test_exec_restore_pushing_disk_over_95_aborts_cleanly(tmp_path):
    """🔴 fail-closed：深度清理后水位 OK，但**补回回滚点本身**把磁盘顶过 95% ⇒ 中止部署。

    此时**回滚点已经补回**（回滚能力没丢），且**尚未拉取/替换任何容器**（中止是干净的，
    旧容器照常服务）—— 宁可本次不部署，也不在磁盘将满时硬上（复审要求：顺序 + fail-closed）。
    """
    work_probe = tmp_path / "opt-migao-deploy"
    work_probe.mkdir(exist_ok=True)
    (work_probe / ".last-good-tag").write_text("sha-old\n", encoding="utf-8")
    proc, log, state = _run(
        tmp_path,
        read_deploy_sh(),
        images=_seed_images(tags=["sha-old"], running_tag="sha-new"),
        running_tag="sha-new",
        extra_env={"DF_SEQ": "95,70,97"},   # 部署前 95% / 清理后 70% / 补回后 97%
    )
    assert proc.returncode != 0, f"补回后 >95% 竟然没中止：\n{proc.stdout}"
    assert (state / "pulls").read_text(encoding="utf-8").count(":sha-old") == 3, (
        "中止前必须先把回滚点补回（否则中止本身又丢了一次回滚能力）"
    )
    assert "补回回滚点后磁盘 97% > 95%" in proc.stdout, proc.stdout
    assert "== 2. 拉取镜像" not in proc.stdout, (
        f"中止发生在拉新镜像之后 ⇒ 不干净（旧容器已被动过）：\n{proc.stdout}"
    )


def test_exec_old_form_deep_clean_loses_rollback_point(tmp_path):
    """🔴 反向红证（判别力）：还原成**改前形态** ⇒ 同一次注入下**回滚点必然消失**。

    改前形态（两段都**逐字内联** HEAD 版本）：深度清理段**不记也不补**回滚点
    + 部署后只 `docker image prune -f`。证明正向那条不是空断言：同样的「磁盘 95%」，
    旧脚本跑完回滚点**镜像本身**就没了，而且**没有任何补回**。
    （新加的观测段保留在改前形态里 —— 它不影响本判据的落点：回滚点是否还在。）
    """
    text = read_deploy_sh()
    a = text.find('if [ "${DISK_PCT:-0}" -gt 90 ]; then')
    b = text.find('else\n  echo "  磁盘水位 ${DISK_PCT}%（≤90%，OK）"')
    assert 0 < a < b, "反空跑锚点：>90% 深度清理段边界定位失败"
    old = text[:a] + OLD_DEEP_CLEAN_BRANCH + text[b:]      # 深度清理不记不复核不补回
    c = old.find('echo "== 2.7 镜像保留策略清理')
    d = old.find('echo "== 3. 健康检查')
    assert 0 < c < d, "反空跑锚点：保留策略段边界定位失败"
    old = old[:c] + OLD_CLEANUP_SNIPPET + old[d:]          # 部署后只清 dangling
    assert old != text and 'cleanup_project_images "$TAG"' not in old
    # 反空跑锚点：改前形态里深度清理**仍在**（否则注入的 95% 根本不会触发清理 ⇒ 红证空跑）
    assert "docker system prune -af" in non_comment(old)
    assert 'RB_BEFORE=$(rollback_tag)' not in old, "改前形态里不该有回滚点复核（还原没生效）"

    work_probe = tmp_path / "opt-migao-deploy"
    work_probe.mkdir(exist_ok=True)
    (work_probe / ".last-good-tag").write_text("sha-old\n", encoding="utf-8")
    proc, log, state = _run(
        tmp_path, old,
        images=_seed_images(tags=["sha-old"], running_tag="sha-new"),
        running_tag="sha-new",
        df_first="95", df_rest="70",
    )
    assert (state / "deep-pruned").is_file(), "深度清理根本没跑（注入没生效 ⇒ 红证是空跑）"
    final = _final_images(state)
    assert _project_ref("admin-api", "sha-old") not in final, (
        f"改前形态居然保住了回滚点（判据锚点已过期）：{sorted(final)}"
    )
    assert "已补回" not in proc.stdout, f"改前形态不该有补回：\n{proc.stdout}"
    assert "深度清理把回滚点" not in proc.stdout, f"改前形态不该有回滚点告警：\n{proc.stdout}"


def test_exec_deep_clean_pull_failure_warns_loudly(tmp_path):
    """回滚点补回**失败** ⇒ 必须 `::warning::` 显式告警（静默失去回滚能力 = 本单要治的形态）。"""
    work_probe = tmp_path / "opt-migao-deploy"
    work_probe.mkdir(exist_ok=True)
    (work_probe / ".last-good-tag").write_text("sha-old\n", encoding="utf-8")
    proc, log, state = _run(
        tmp_path, read_deploy_sh(),
        images=_seed_images(tags=["sha-old"], running_tag="sha-new"),
        running_tag="sha-new",
        df_first="95", df_rest="70",
        # 只让**回滚点那一轮** pull 失败（当前 tag 的常规拉取不受影响 ⇒ 部署照常成功）
        extra_env={"STUB_PULL_FAIL_TAG": "sha-old"},
    )
    assert proc.returncode == 0, f"部署本身不该失败：\n{proc.stdout}\n{proc.stderr}"
    assert "深度清理把回滚点 tag=sha-old 删了" in proc.stdout, proc.stdout
    assert "::warning::回滚点 tag=sha-old **补回失败**" in proc.stdout, (
        f"补回失败没有显式告警：\n{proc.stdout}"
    )
    assert "已补回" not in proc.stdout, f"补回明明失败了却报告成功：\n{proc.stdout}"
    assert _project_ref("admin-api", "sha-old") not in _final_images(state)


def test_exec_rollback_point_survives_broken_keep_set(tmp_path):
    """🔴 红证（保留集 fail-closed）：把保留集**故意算空**（模拟 `retained_tags` 出缺陷）。

    有独立护栏 ⇒ 回滚点 `sha-old` 被 `🛡️` 拦住、**仍在**，非回滚点旧镜像照删 ✓；
    把护栏拆掉 ⇒ 同一次注入下回滚点**必然消失**（证明这条断言不是恒真）。
    """
    text = read_deploy_sh()
    broken_keep = _inject(
        text,
        'retained_tags "$TAG" "$PREV_GOOD" "$KEEP_RECENT_TAGS" > "$KEEP_FILE"',
        ': > "$KEEP_FILE"',
    )
    work_a = tmp_path / "a" / "opt-migao-deploy"
    work_a.mkdir(parents=True, exist_ok=True)
    (work_a / ".last-good-tag").write_text("sha-old\n", encoding="utf-8")
    proc, log, state = _run(
        tmp_path / "a", broken_keep,
        images=_seed_images(tags=["sha-old", "sha-extra"], running_tag="sha-old"),
        running_tag="sha-old",
    )
    assert proc.returncode == 0, proc.stdout
    final = _final_images(state)
    assert _project_ref("admin-api", "sha-old") in final, (
        "🔴 保留集为空时回滚点被删了（独立护栏没生效）"
    )
    assert "🛡️  保留回滚点 sha-old" in proc.stdout, proc.stdout
    assert not any("sha-extra" in x for x in final), (
        f"保留集为空 ⇒ 非回滚点的旧镜像应当被删：{sorted(final)}"
    )
    # 反向（判别力）：拆掉独立护栏 ⇒ 同一次注入下回滚点必然消失
    no_guard = _inject(broken_keep, 'if [ -n "$prev" ] && [ "$tag" = "$prev" ]; then', "if false; then")
    work_b = tmp_path / "b" / "opt-migao-deploy"
    work_b.mkdir(parents=True, exist_ok=True)
    (work_b / ".last-good-tag").write_text("sha-old\n", encoding="utf-8")
    proc2, _, state2 = _run(
        tmp_path / "b", no_guard,
        images=_seed_images(tags=["sha-old", "sha-extra"], running_tag="sha-old"),
        running_tag="sha-old",
    )
    assert _project_ref("admin-api", "sha-old") not in _final_images(state2), (
        "拆掉护栏 + 保留集为空 ⇒ 回滚点居然还在（判据没有判别力）"
    )


def test_exec_observability_reports_watermark_and_rollback_point(tmp_path):
    """③ 可观测：每次部署都报「清理后磁盘水位」**与**「回滚点是否还在」。"""
    work_probe = tmp_path / "opt-migao-deploy"
    work_probe.mkdir(exist_ok=True)
    (work_probe / ".last-good-tag").write_text("sha-old\n", encoding="utf-8")
    proc, log, state = _run(
        tmp_path,
        read_deploy_sh(),
        images=_seed_images(tags=["sha-old"], running_tag="sha-old"),
        running_tag="sha-old",
        df_first="85", df_rest="72",
    )
    assert proc.returncode == 0, proc.stdout
    assert "清理后磁盘水位：72%" in proc.stdout, proc.stdout
    assert "回滚点 tag=sha-old：本项目 3/3 个服务镜像都在本地" in proc.stdout, proc.stdout
    assert "::warning::磁盘水位 85%" in proc.stdout, proc.stdout


def test_exec_partial_rollback_point_warns(tmp_path):
    """③ 可观测的非恒真判据：回滚点**只回来 1/3 个服务** ⇒ 必须 `::warning::`。

    「回滚点是否还在」不能只看「有没有一个镜像」—— 3 个服务缺 2 个时回滚是残缺的，
    必须告警（旧写法 `rollback_point_present` 只看 ≥1 个 ⇒ 这里会静默）。
    """
    work_probe = tmp_path / "opt-migao-deploy"
    work_probe.mkdir(exist_ok=True)
    (work_probe / ".last-good-tag").write_text("sha-old\n", encoding="utf-8")
    proc, log, state = _run(
        tmp_path,
        read_deploy_sh(),
        images=f"{FOREIGN_IMAGE}\n{_project_ref('ai-agent-service', 'sha-old')}\n",
        running_tag="sha-old",
    )
    assert proc.returncode == 0, proc.stdout
    assert "::warning::回滚点 tag=sha-old 只剩 1/3 个服务镜像" in proc.stdout, proc.stdout
    assert "只能回滚部分服务" in proc.stdout, proc.stdout
